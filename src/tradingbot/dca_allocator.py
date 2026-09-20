"""Bot d'investissement regulier (EF-67, demande de l'utilisateur : "un bot
qui me permettrait d'investir intelligement de l'argent et de le faire se
fructifier").

POURQUOI CE BOT PLUTOT QU'UN BOT DE SIGNAUX. Toutes les recherches de
parametres menees dans ce projet (EF-19/EF-26 crypto, EF-64 actions, EF-66
scanner multi-actions : 972 combinaisons) aboutissent au meme constat
out-of-sample : aucune strategie testee ne bat de facon reproductible un
panier diversifie achete et garde. Ce module ne cherche donc PAS a predire
le marche. Il automatise les trois seules choses qui ameliorent un resultat
d'investissement sans necessiter le moindre edge predictif :

1. La regularite : verser une somme fixe a date fixe, sans jamais attendre
   "un meilleur point d'entree" (le reflexe le plus couteux de
   l'investisseur particulier).
2. Le retour a l'allocation cible : ce qui a trop monte est allege au profit
   de ce qui a baisse - le seul arbitrage de marche qui resiste
   statistiquement, parce qu'il est mecanique et contra-cyclique.
3. La mesure honnete : rendement pondere par les flux (un "rendement total"
   n'a aucun sens quand on ajoute de l'argent en cours de route), drawdown
   maximal, frais reels, et comparaison a des references a FLUX IDENTIQUES.

AUCUN STOP-LOSS, VOLONTAIREMENT. C'est l'inverse du reste du projet, et
c'est deliberé : vendre parce que ca baisse est precisement ce qui detruit
le rendement d'une approche achetee-et-gardee (et transforme une baisse
temporaire en perte definitive). Le risque est ici gere par la
diversification et l'horizon, pas par des sorties.

Design AUTONOME, meme precedent que `multi_symbol_scanner.py` (voir STC
§3.49) et pour la meme raison : `Position`/`Portfolio`/`Engine`/`Strategy`
sont concus pour UN SEUL instrument pilote par des signaux de prix, alors
qu'un bot d'investissement regulier est multi-actions par nature et pilote
par un CALENDRIER. `Strategy.on_candle(candle) -> Signal | None` ne peut
structurellement pas exprimer "verser 200 EUR le premier jour ouvre du
mois, repartis sur ce qui est le plus en retard sur sa cible". Reutilise ce
qui est deja generique : `fetch_historical_candles` (par symbole) et
`compute_buy_and_hold_return_pct` (reference par action).

QUANTITES ENTIERES. Les actions s'achetent par titre entier chez un
courtier comme IBKR (voir `ib_paper_executor.py`) : le backtest le modelise
honnetement, ce qui est loin d'etre un detail avec des versements modestes
et des actions cheres (une seule action LVMH vaut plusieurs centaines
d'euros). Le reliquat non investissable reste en liquidites et est reporte.
"""

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from tradingbot.data_feed import fetch_historical_candles, filter_candles, parse_iso_to_ms
from tradingbot.reporting.stats import compute_buy_and_hold_return_pct
from tradingbot.types import Candle

# Panier par defaut : le meme que `TOP_STOCKS` (dashboard) et
# `DEFAULT_UNIVERSE` (scanner), en equipondere. Ce n'est PAS une
# recommandation d'allocation - juste un point de depart coherent avec le
# reste du projet, a remplacer par le choix de l'utilisateur via --weights.
DEFAULT_UNIVERSE = [
    "TTE.PA", "ORA.PA", "GLE.PA", "RNO.PA", "AF.PA", "MT.AS",
    "AI.PA", "MC.PA", "OR.PA", "SAN.PA", "BNP.PA",
]


@dataclass
class PlannedOrder:
    """Ordre DECIDE mais pas encore execute. Sert d'interface commune entre
    la decision (pure, partagee) et son execution - en memoire pour le
    backtest, chez le courtier pour le paper trading."""
    symbol: str
    side: str
    quantity: int
    reference_price: float
    reason: str


@dataclass
class Trade:
    day: str
    symbol: str
    side: str
    quantity: int
    price: float
    fee: float
    reason: str


@dataclass
class AllocatorResult:
    initial_capital: float
    contributions: list[tuple[str, float]] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    holdings: dict[str, float] = field(default_factory=dict)
    cash: float = 0.0
    equity_curve: list[tuple[str, float]] = field(default_factory=list)
    per_symbol_benchmark_pct: dict[str, float] = field(default_factory=dict)
    last_prices: dict[str, float] = field(default_factory=dict)
    money_weighted_return_pct: float | None = None
    max_drawdown_pct: float = 0.0
    years: float = 0.0

    @property
    def total_invested(self) -> float:
        return self.initial_capital + sum(amount for _, amount in self.contributions)

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1][1] if self.equity_curve else self.initial_capital

    @property
    def total_fees(self) -> float:
        return sum(trade.fee for trade in self.trades)


def _day_key(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _max_drawdown_pct(equity_curve: list[tuple[str, float]]) -> float:
    """Sur un portefeuille alimente par des versements, la baisse se mesure
    par rapport au pic d'equity atteint, exactement comme dans
    `reporting/stats.compute_report` - un versement qui fait monter l'equity
    deplace le pic, il ne masque pas une baisse."""
    peak = float("-inf")
    worst = 0.0
    for _, equity in equity_curve:
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, (peak - equity) / peak)
    return worst * 100


def annualised_money_weighted_return_pct(
    cashflows: list[tuple[int, float]], final_value: float, final_day_index: int,
) -> float | None:
    """Taux de rendement annualise pondere par les flux (equivalent d'un TRI).

    Indispensable ici : avec des versements etales, un "rendement sur le
    capital de depart" est denue de sens (de l'argent verse le dernier mois
    n'a pas eu le temps de travailler). On resout par dichotomie le taux r
    tel que la valeur future de tous les versements, capitalisee a r,
    egale la valeur finale du portefeuille."""
    if not cashflows or final_value <= 0 or final_day_index <= 0:
        return None

    def future_value_at(rate: float) -> float:
        return sum(
            amount * (1 + rate) ** ((final_day_index - day_index) / 365.0)
            for day_index, amount in cashflows
        )

    low, high = -0.95, 10.0
    if future_value_at(low) > final_value:
        return low * 100  # perte quasi totale : en dehors de la plage de recherche
    for _ in range(200):
        mid = (low + high) / 2
        if future_value_at(mid) < final_value:
            low = mid
        else:
            high = mid
    return (low + high) / 2 * 100


def _portfolio_value(holdings: dict[str, float], prices: dict[str, float]) -> float:
    return sum(quantity * prices[symbol] for symbol, quantity in holdings.items() if symbol in prices)


def _order_fee(order_value: float, fee_pct: float, fee_fixed: float) -> float:
    """Un courtier reel facture un MINIMUM par ordre (3,00 EUR MESURE sur
    Euronext chez IBKR), pas un simple pourcentage. Ce plancher change tout
    pour un bot a versements modestes : eclater 200 EUR sur 11 lignes fait
    des ordres de 18 EUR, sur lesquels 3,00 EUR representent 17 % - de quoi
    annuler n'importe quel gain d'allocation. Ignorer ce plancher menerait a
    recommander un reglage qui ne survit pas au contact d'un vrai courtier."""
    return max(fee_fixed, order_value * fee_pct)


def _committed_cost(
    committed: dict[str, int], prices: dict[str, float], fee_pct: float, fee_fixed: float,
) -> float:
    total = 0.0
    for symbol, quantity in committed.items():
        if quantity <= 0:
            continue
        value = quantity * prices[symbol]
        total += value + _order_fee(value, fee_pct, fee_fixed)
    return total


def _invest_available_cash(
    cash: float, holdings: dict[str, float], prices: dict[str, float], weights: dict[str, float],
    fee_pct: float, day: str, trades: list[Trade], reason: str, follow_drift: bool,
    fee_fixed: float = 0.0, min_order_value: float = 0.0,
) -> float:
    orders = plan_buy_orders(
        cash, holdings, prices, weights, fee_pct, fee_fixed, min_order_value, follow_drift, reason,
    )
    return apply_orders(orders, cash, holdings, fee_pct, fee_fixed, day, trades)


def plan_buy_orders(
    cash: float, holdings: dict[str, float], prices: dict[str, float], weights: dict[str, float],
    fee_pct: float, fee_fixed: float, min_order_value: float, follow_drift: bool, reason: str,
) -> list[PlannedOrder]:
    """Decide QUOI acheter, sans rien executer ni muter.

    Fonction pure, partagee telle quelle par le backtest (`simulate`) et par
    l'execution reelle (`run_dca.py`) : c'est la garantie que le bot qui
    passe de vrais ordres prend exactement les memes decisions que celui
    qu'on a mesure sur 11 ans. Dupliquer cette logique cote live serait le
    moyen le plus sur de les faire diverger en silence.

    `follow_drift=True` dirige l'argent neuf vers ce qui est le plus EN
    RETARD sur sa cible (le rééquilibrage se fait alors par les versements,
    sans rien vendre, donc sans frais de vente ni plus-value imposable
    declenchee). `follow_drift=False` repartit selon les poids cibles fixes
    en ignorant la derive."""
    investable = [s for s in weights if s in prices and prices[s] > 0]
    if not investable or cash <= 0:
        return []

    if not follow_drift:
        # Le versement est reparti selon les poids cibles fixes ; ce qui
        # n'est pas investissable (ordre trop petit pour valoir ses frais)
        # reste en liquidites et attend le mois suivant.
        orders = []
        budget_at_start, remaining = cash, cash
        for symbol in investable:
            price = prices[symbol]
            quantity = int(budget_at_start * weights[symbol] / price)
            while quantity > 0:
                cost = quantity * price
                fee = _order_fee(cost, fee_pct, fee_fixed)
                if cost + fee <= remaining and cost >= min_order_value:
                    remaining -= cost + fee
                    orders.append(PlannedOrder(symbol, "buy", quantity, price, reason))
                    break
                if cost < min_order_value:
                    break
                quantity -= 1
        return orders

    # Allocation gloutonne titre par titre : a chaque tour on engage UNE
    # action de la ligne actuellement la plus en retard sur sa cible, puis on
    # reevalue. Recalculer l'ecart apres chaque achat est essentiel - une
    # allocation proportionnelle en une passe, suivie d'une passe "depense le
    # reliquat", sur-concentrait la derniere ligne servie et declenchait
    # ensuite une vente correctrice : des frais payes a l'aller ET au retour
    # pour degrader l'allocation (bug reel trouve en test).
    # Les frais se calculent PAR ORDRE : ajouter une action a une ligne deja
    # engagee ne coute pas un nouveau frais fixe, alors qu'ouvrir une
    # nouvelle ligne si. La decision doit voir ce cout complet, d'ou
    # l'engagement prealable plutot qu'un debit action par action.
    committed: dict[str, int] = defaultdict(int)
    while True:
        total_value = _portfolio_value(holdings, prices) + cash
        best_symbol, best_shortfall = None, 0.0
        for symbol in investable:
            trial = dict(committed)
            trial[symbol] = trial.get(symbol, 0) + 1
            if _committed_cost(trial, prices, fee_pct, fee_fixed) > cash:
                continue
            held_value = (holdings.get(symbol, 0.0) + committed[symbol]) * prices[symbol]
            shortfall = total_value * weights[symbol] - held_value
            if shortfall > best_shortfall:
                best_symbol, best_shortfall = symbol, shortfall
        if best_symbol is None:
            break
        committed[best_symbol] += 1

    # Un ordre trop petit paierait plus de frais qu'il ne vaut : ce cash
    # attend le mois suivant plutot que d'etre grignote.
    return [
        PlannedOrder(symbol, "buy", quantity, prices[symbol], reason)
        for symbol, quantity in committed.items()
        if quantity > 0 and quantity * prices[symbol] >= min_order_value
    ]


def plan_rebalance_sells(
    cash: float, holdings: dict[str, float], prices: dict[str, float], weights: dict[str, float],
    min_order_value: float,
) -> list[PlannedOrder]:
    """Decide QUOI alleger pour revenir vers l'allocation cible, sans rien
    executer. Le produit des ventes est ensuite redeploye via
    `plan_buy_orders` - en deux temps, parce qu'en execution reelle il faut
    connaitre le produit REELLEMENT encaisse avant de le reinvestir.

    `min_order_value` ecarte les micro-ordres : sans ce plancher, le bot
    paie des frais fixes pour corriger des ecarts de quelques euros, et sur
    un portefeuille encore petit il churne indefiniment parce que la
    contrainte du titre entier rend la cible exacte inatteignable (bug reel
    mesure : 51 320 ordres et 19 % des versements partis en frais)."""
    total_value = _portfolio_value(holdings, prices) + cash
    orders = []
    for symbol, quantity in holdings.items():
        if symbol not in prices or quantity <= 0:
            continue
        price = prices[symbol]
        excess_value = quantity * price - total_value * weights.get(symbol, 0.0)
        if excess_value < min_order_value:
            continue
        to_sell = min(int(excess_value / price), int(quantity))
        if to_sell <= 0 or to_sell * price < min_order_value:
            continue
        orders.append(PlannedOrder(symbol, "sell", to_sell, price, "rebalance"))
    return orders


def apply_orders(
    orders: list[PlannedOrder], cash: float, holdings: dict[str, float],
    fee_pct: float, fee_fixed: float, day: str, trades: list[Trade],
) -> float:
    """Applique des ordres planifies a un etat EN MEMOIRE (backtest). En
    execution reelle, c'est `run_dca.py` qui les envoie au courtier et
    enregistre les fills reels a la place."""
    for order in orders:
        value = order.quantity * order.reference_price
        fee = _order_fee(value, fee_pct, fee_fixed)
        if order.side == "buy":
            if value + fee > cash:
                continue
            cash -= value + fee
            holdings[order.symbol] = holdings.get(order.symbol, 0.0) + order.quantity
        else:
            cash += value - fee
            holdings[order.symbol] = holdings.get(order.symbol, 0.0) - order.quantity
        trades.append(Trade(
            day, order.symbol, order.side, order.quantity, order.reference_price, fee, order.reason,
        ))
    return cash


def _rebalance(
    cash: float, holdings: dict[str, float], prices: dict[str, float], weights: dict[str, float],
    fee_pct: float, day: str, trades: list[Trade], min_order_value: float, fee_fixed: float,
) -> float:
    sells = plan_rebalance_sells(cash, holdings, prices, weights, min_order_value)
    cash = apply_orders(sells, cash, holdings, fee_pct, fee_fixed, day, trades)
    buys = plan_buy_orders(
        cash, holdings, prices, weights, fee_pct, fee_fixed, min_order_value,
        follow_drift=True, reason="rebalance",
    )
    return apply_orders(buys, cash, holdings, fee_pct, fee_fixed, day, trades)


def simulate(
    candles_by_symbol: dict[str, list[Candle]],
    weights: dict[str, float],
    initial_capital: float = 0.0,
    monthly_contribution: float = 200.0,
    rebalance_band_pct: float | None = 5.0,
    fee_pct: float = 0.001,
    follow_drift_on_contribution: bool = True,
    min_rebalance_interval_days: int = 90,
    min_order_value: float = 50.0,
    fee_fixed: float = 0.0,
) -> AllocatorResult:
    """Simule le bot jour par jour sur des bougies DEJA chargees.

    `rebalance_band_pct` est un ecart ABSOLU en points de pourcentage : avec
    5, une ligne ciblee a 10% est rééquilibrée si elle sort de [5%, 15%].
    `None` desactive toute vente (l'allocation n'est alors corrigee que par
    les versements) - c'est la reference "DCA sans rééquilibrage".

    `min_rebalance_interval_days` plafonne la FREQUENCE des rééquilibrages
    (90 jours = trimestriel, la pratique courante). Indispensable : la bande
    seule ne suffit pas, car sur un portefeuille encore petit la cible est
    inatteignable a cause des titres entiers, donc la bande reste depassee
    en permanence et le bot rééquilibre chaque jour en brulant des frais.
    """
    candles_by_day: dict[str, dict[str, Candle]] = defaultdict(dict)
    for symbol, candles in candles_by_symbol.items():
        for candle in candles:
            candles_by_day[_day_key(candle.timestamp)][symbol] = candle
    all_days = sorted(candles_by_day)
    if not all_days:
        return AllocatorResult(initial_capital=initial_capital)

    result = AllocatorResult(initial_capital=initial_capital)
    holdings: dict[str, float] = {}
    prices: dict[str, float] = {}
    cash = initial_capital
    cashflows: list[tuple[int, float]] = []
    if initial_capital > 0:
        cashflows.append((0, initial_capital))
    months_funded: set[str] = set()
    first_day = date.fromisoformat(all_days[0])
    # Autorise un premier rééquilibrage des que la bande est depassee, sans
    # attendre un premier intervalle complet.
    last_rebalance_index = -min_rebalance_interval_days

    for day_index, day in enumerate(all_days):
        for symbol, candle in candles_by_day[day].items():
            prices[symbol] = candle.close

        # Premier jour OUVRE de chaque mois calendaire : on ne peut pas
        # verser "le 1er" en dur, les bourses sont fermees certains 1ers.
        month = day[:7]
        is_contribution_day = monthly_contribution > 0 and month not in months_funded
        if is_contribution_day:
            months_funded.add(month)
            cash += monthly_contribution
            cashflows.append((day_index, monthly_contribution))
            result.contributions.append((day, monthly_contribution))

        # On n'investit qu'aux jours de versement (et au premier jour, pour
        # un capital initial) : tenter d'investir le reliquat chaque jour
        # multiplierait les petits ordres, donc les frais fixes, pour un
        # gain de temps d'exposition negligeable.
        if is_contribution_day or day_index == 0:
            cash = _invest_available_cash(
                cash, holdings, prices, weights, fee_pct, day, result.trades,
                "contribution", follow_drift=follow_drift_on_contribution,
                fee_fixed=fee_fixed, min_order_value=min_order_value,
            )

        if rebalance_band_pct is not None and day_index - last_rebalance_index >= min_rebalance_interval_days:
            total_value = _portfolio_value(holdings, prices) + cash
            if total_value > 0:
                worst_drift_pct = max(
                    abs(holdings.get(s, 0.0) * prices.get(s, 0.0) / total_value - w) * 100
                    for s, w in weights.items()
                )
                if worst_drift_pct > rebalance_band_pct:
                    cash = _rebalance(
                        cash, holdings, prices, weights, fee_pct, day, result.trades,
                        min_order_value, fee_fixed,
                    )
                    last_rebalance_index = day_index

        result.equity_curve.append((day, _portfolio_value(holdings, prices) + cash))

    result.holdings = {s: q for s, q in holdings.items() if q > 0}
    result.cash = cash
    result.last_prices = dict(prices)
    result.per_symbol_benchmark_pct = {
        symbol: (compute_buy_and_hold_return_pct(candles) or 0.0) * 100
        for symbol, candles in candles_by_symbol.items() if candles
    }
    result.money_weighted_return_pct = annualised_money_weighted_return_pct(
        cashflows, result.final_equity, len(all_days) - 1,
    )
    result.max_drawdown_pct = _max_drawdown_pct(result.equity_curve)
    result.years = (date.fromisoformat(all_days[-1]) - first_day).days / 365.0
    return result


def run_backtest(
    weights: dict[str, float], since_iso: str, initial_capital: float, monthly_contribution: float,
    rebalance_band_pct: float | None, fee_pct: float, exchange: str = "yfinance", timeframe: str = "1d",
    fee_fixed: float = 0.0, follow_drift_on_contribution: bool = False, min_order_value: float = 50.0,
) -> tuple[AllocatorResult, AllocatorResult, AllocatorResult]:
    """Renvoie (bot, reference DCA sans rééquilibrage, reference versements
    a poids fixes) - trois simulations aux FLUX DE TRESORERIE IDENTIQUES,
    seule facon honnete d'isoler ce que le rééquilibrage apporte reellement
    plutot que de mesurer le marche qui monte."""
    # `fetch_historical_candles` renvoie TOUT son cache local des qu'il
    # couvre la date demandee (comportement documente, EF-01) : c'est a
    # l'appelant de recouper la periode, sinon le backtest demarre des
    # annees trop tot et faussE le rendement annualise (meme bug que celui
    # corrige dans `run_backtest.py`, voir STC §3.47).
    since_ms = parse_iso_to_ms(since_iso) or 0
    candles_by_symbol = {
        symbol: filter_candles(
            fetch_historical_candles(exchange_id=exchange, symbol=symbol, timeframe=timeframe, since_iso=since_iso),
            since_ms, None,
        )
        for symbol in weights
    }
    common = dict(
        candles_by_symbol=candles_by_symbol, weights=weights, initial_capital=initial_capital,
        monthly_contribution=monthly_contribution, fee_pct=fee_pct, fee_fixed=fee_fixed,
        min_order_value=min_order_value,
    )
    bot = simulate(
        **common, rebalance_band_pct=rebalance_band_pct,
        follow_drift_on_contribution=follow_drift_on_contribution,
    )
    with_rebalance = simulate(**common, rebalance_band_pct=5.0, follow_drift_on_contribution=True)
    drift_no_rebalance = simulate(**common, rebalance_band_pct=None, follow_drift_on_contribution=True)
    return bot, with_rebalance, drift_no_rebalance


def format_report(
    bot: AllocatorResult, with_rebalance: AllocatorResult, drift_no_rebalance: AllocatorResult,
    weights: dict[str, float], since: str, monthly_contribution: float, rebalance_band_pct: float | None,
) -> str:
    lines = [
        "=== Bot d'investissement regulier - rapport de backtest ===",
        f"Genere le          : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Periode            : {since} -> maintenant ({bot.years:.1f} ans)",
        f"Versement mensuel  : {monthly_contribution:.2f} | capital initial : {bot.initial_capital:.2f}",
        f"Bande de rééquilibrage : {'desactivee' if rebalance_band_pct is None else f'+/- {rebalance_band_pct:.1f} points'}",
        f"Allocation cible ({len(weights)} lignes) : " + ", ".join(f"{s} {w * 100:.1f}%" for s, w in weights.items()),
        "",
        "--- Resultat ---",
        f"Total verse            : {bot.total_invested:10.2f}",
        f"Valeur finale          : {bot.final_equity:10.2f}  (dont liquidites non investies : {bot.cash:.2f})",
        f"Gain                   : {bot.final_equity - bot.total_invested:+10.2f}",
        f"Rendement annualise pondere par les flux : {bot.money_weighted_return_pct:+.2f} % / an"
        if bot.money_weighted_return_pct is not None else "Rendement annualise : non calculable",
        f"Baisse maximale subie  : -{bot.max_drawdown_pct:.2f} %",
        f"Frais payes            : {bot.total_fees:.2f} ({bot.total_fees / bot.total_invested * 100:.2f} % du total verse)"
        if bot.total_invested else "Frais payes : 0",
        f"Nombre d'ordres        : {len(bot.trades)} ({sum(1 for t in bot.trades if t.side == 'sell')} ventes de rééquilibrage)",
        "",
        "--- Comparaison a flux identiques (ce que les variantes 'intelligentes' apportent vraiment) ---",
    ]
    for label, res in [
        ("Ce bot (reglage retenu)", bot),
        ("Variante : versements diriges + rééquilibrage", with_rebalance),
        ("Variante : versements diriges, sans rééquilibrage", drift_no_rebalance),
    ]:
        rate = f"{res.money_weighted_return_pct:+6.2f} %/an" if res.money_weighted_return_pct is not None else "    n/a"
        lines.append(
            f"  {label:<38} valeur {res.final_equity:10.2f} | {rate} | baisse max -{res.max_drawdown_pct:5.2f} % | {len(res.trades):3d} ordres"
        )

    lines += ["", "--- Detail des lignes detenues ---"]
    total_value = _portfolio_value(bot.holdings, bot.last_prices) + bot.cash
    for symbol in sorted(bot.holdings, key=lambda s: bot.holdings[s] * bot.last_prices.get(s, 0), reverse=True):
        value = bot.holdings[symbol] * bot.last_prices.get(symbol, 0.0)
        actual_pct = value / total_value * 100 if total_value else 0.0
        target_pct = weights.get(symbol, 0.0) * 100
        lines.append(
            f"  {symbol:<8} {bot.holdings[symbol]:6.0f} titres | valeur {value:9.2f} | "
            f"{actual_pct:5.1f} % (cible {target_pct:4.1f} %) | buy&hold de l'action {bot.per_symbol_benchmark_pct.get(symbol, 0.0):+7.2f} %"
        )

    lines += [
        "",
        "Rappel : aucun stop-loss dans ce bot, volontairement (vendre sur une baisse",
        "est ce qui detruit le rendement d'une approche achetee-et-gardee). Le risque",
        "est gere par la diversification et l'horizon de detention.",
    ]
    return "\n".join(lines)


def parse_weights(spec: str) -> dict[str, float]:
    """Accepte "TTE.PA,ORA.PA" (equipondere automatiquement) ou
    "TTE.PA:40,ORA.PA:60" (poids explicites, normalises a 100%)."""
    entries = [e.strip() for e in spec.split(",") if e.strip()]
    if not entries:
        raise ValueError("Allocation vide")
    if any(":" in e for e in entries):
        weights = {}
        for entry in entries:
            symbol, _, value = entry.partition(":")
            weights[symbol.strip().upper()] = float(value)
        total = sum(weights.values())
        if total <= 0:
            raise ValueError("La somme des poids doit etre positive")
        return {s: w / total for s, w in weights.items()}
    return {e.upper(): 1 / len(entries) for e in entries}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backtest d'un bot d'investissement regulier (versements programmes + retour a l'allocation cible, sans stop-loss)"
    )
    parser.add_argument("--weights", default=",".join(DEFAULT_UNIVERSE), help="Allocation : 'A,B,C' (equipondere) ou 'A:40,B:60' (poids en %%)")
    parser.add_argument("--since", required=True, help="Debut de periode, AAAA-MM-JJ")
    parser.add_argument("--initial-capital", dest="initial_capital", type=float, default=0.0, help="Somme investie au premier jour (defaut: 0)")
    parser.add_argument("--monthly", dest="monthly_contribution", type=float, default=200.0, help="Versement mensuel, au premier jour ouvre du mois (defaut: 200)")
    parser.add_argument("--rebalance-band-pct", dest="rebalance_band_pct", type=float, default=5.0, help="Ecart absolu en POINTS de %% declenchant un rééquilibrage (defaut: 5)")
    parser.add_argument("--no-rebalance", dest="no_rebalance", action="store_true", help="Desactive les ventes de rééquilibrage (l'allocation n'est corrigee que par les versements)")
    parser.add_argument("--fee-pct", dest="fee_pct", type=float, default=0.1, help="Frais par ordre en %% (defaut: 0.1)")
    parser.add_argument("--fee-fixed", dest="fee_fixed", type=float, default=3.0, help="Frais MINIMUM par ordre, en euros (defaut: 3.0, MESURE chez IBKR sur Euronext Paris le 2026-09-18 via whatIfOrder, et non estime) - determinant pour un bot a petits versements")
    parser.add_argument("--follow-drift", dest="follow_drift", action="store_true", help="Dirige l'argent neuf vers les lignes en retard sur leur cible, au lieu de respecter les poids fixes (mesure comme PERDANT sur un panier d'actions individuelles, voir STC)")
    parser.add_argument("--min-order-value", dest="min_order_value", type=float, default=50.0, help="Valeur minimale d'un ordre (defaut: 50) - en dessous, les frais mangent l'operation, le cash attend le mois suivant")
    parser.add_argument("--exchange", default="yfinance", help="Source de donnees (defaut: yfinance)")
    parser.add_argument("--timeframe", default="1d", help="Timeframe (defaut: 1d)")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    weights = parse_weights(args.weights)
    band = None if args.no_rebalance else args.rebalance_band_pct
    bot, with_rebalance, drift_no_rebalance = run_backtest(
        weights=weights, since_iso=f"{args.since}T00:00:00Z", initial_capital=args.initial_capital,
        monthly_contribution=args.monthly_contribution, rebalance_band_pct=band,
        fee_pct=args.fee_pct / 100, exchange=args.exchange, timeframe=args.timeframe,
        fee_fixed=args.fee_fixed, follow_drift_on_contribution=args.follow_drift,
        min_order_value=args.min_order_value,
    )
    print(format_report(
        bot, with_rebalance, drift_no_rebalance, weights, args.since, args.monthly_contribution, band,
    ))


if __name__ == "__main__":
    main(sys.argv[1:])
