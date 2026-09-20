"""Scanner multi-actions (EF-66, demande de l'utilisateur : "un bot qui
analyse plusieurs actions, et qui decide de quand investir sur une action").
Surveille PLUSIEURS symboles en meme temps et achete celui (ou ceux) dont le
creux est le plus profond quand `dip_bounce` declenche un signal - meme
regle appliquee uniformement a chaque action du panier, la plus forte
l'emporte en cas de signaux multiples le meme jour (decision validee avec
l'utilisateur, pas de comparaison relative type "la seule qui baisse").

BACKTEST UNIQUEMENT dans ce lot (decision validee) - pas de paper trading,
pas d'integration dashboard.

Design deliberement AUTONOME - n'importe ni ne modifie `Portfolio`/`Engine`/
`types.Position` : ces classes coeur sont concues pour UN SEUL instrument a
la fois (`Portfolio.equity()` multiplie la quantite totale de positions par
UN SEUL prix courant ; `RiskManager.validate()` compare le prix du candidat
achete aux positions ouvertes en supposant implicitement un instrument
unique). Les etendre pour un vrai support multi-symbole toucherait 6
fichiers centraux utilises par tous les bots crypto EN PRODUCTION - risque
de regression juge disproportionne pour un lot backtest (voir STC pour le
detail de l'exploration qui a mene a cette decision).

Reutilise ce qui est deja generique :
- `fetch_historical_candles` (deja trivialement bouclable par symbole).
- `DipBounceStrategy` (une instance PAR symbole, chacune avec son propre
  etat de fenetre glissante - aucun partage d'etat entre symboles).
- Les methodes PURES de `RiskManager`
  (`should_stop_loss`/`should_trailing_stop`/`should_take_profit`/
  `should_profit_lock`, chacune `(Position, prix_actuel) -> bool`) - sures a
  reutiliser tant qu'on leur passe le prix DU BON symbole pour chaque
  position, ce que fait ce module (jamais le prix d'un autre symbole).
  `size_for_signal` egalement reutilise pour le dimensionnement des achats.
- **Non reutilise** : `RiskManager.validate()` (sa regle anti-accumulation
  compare le prix du candidat achete aux prix d'entree de TOUTES les
  positions ouvertes, ce qui n'a de sens qu'a instrument unique) -
  reimplementee simplement ci-dessous (`_any_position_losing`), reevaluee
  avec le prix propre de CHAQUE position, pas celui du candidat.
"""

import argparse
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from tradingbot.data_feed import fetch_historical_candles
from tradingbot.reporting.stats import compute_buy_and_hold_return_pct
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.dip_bounce import DipBounceStrategy
from tradingbot.types import Candle, Position, Side

# Meme panier que TOP_STOCKS dans reporting/dashboard.py, pour rester
# coherent avec ce qui est deja propose a l'utilisateur dans le formulaire.
DEFAULT_UNIVERSE = [
    "TTE.PA", "ORA.PA", "GLE.PA", "RNO.PA", "AF.PA", "MT.AS",
    "AI.PA", "MC.PA", "OR.PA", "SAN.PA", "BNP.PA",
]


@dataclass
class OpenLot:
    symbol: str
    position: Position


@dataclass
class ClosedTrade:
    symbol: str
    entry_timestamp: int
    entry_price: float
    exit_timestamp: int
    exit_price: float
    quantity: float
    reason: str
    pnl: float


@dataclass
class ScannerResult:
    starting_capital: float
    ending_cash: float
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    open_lots: list[OpenLot] = field(default_factory=list)
    equity_curve: list[tuple[str, float]] = field(default_factory=list)
    per_symbol_benchmark_pct: dict[str, float] = field(default_factory=dict)


def _day_key(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def scan_and_rank(
    candles_today: dict[str, Candle],
    strategies: dict[str, DipBounceStrategy],
    recent_windows: dict[str, deque],
    held_symbols: set[str],
) -> list[tuple[str, float]]:
    """Fait avancer la strategie de CHAQUE symbole d'une bougie - y compris
    ceux deja detenus - puis ne retient que les signaux BUY des symboles
    SANS position ouverte, tries du creux le plus profond au moins profond.

    Important : `held_symbols` filtre uniquement quels signaux sont
    RETENUS, jamais quels symboles avancent leur strategie - exactement le
    meme principe que `dip_bounce.py` documente pour l'anti-doublon a
    instrument unique (la strategie voit TOUJOURS chaque bougie, l'etat
    "deja en position" ne doit jamais geler son horloge interne). Sans ca,
    la fenetre glissante d'un symbole detenu resterait figee pendant sa
    detention puis reprendrait avec des donnees perimees des sa revente -
    bug reel trouve en testant ce module (`test_stop_loss_on_one_symbol_...`).

    `depth = (rolling_min - close) / rolling_min` : plus c'est grand, plus
    la cloture est basse par rapport a sa fenetre recente propre - meme
    logique de proximite que celle qui declenche `DipBounceStrategy`
    elle-meme, calculee ici independamment (fenetre glissante parallele,
    alimentee des memes clotures dans le meme ordre) pour classer plusieurs
    signaux simultanes sans toucher a l'etat interne prive de la strategie."""
    candidates = []
    for symbol, candle in candles_today.items():
        if symbol not in strategies:
            continue
        window = recent_windows[symbol]
        signal = strategies[symbol].on_candle(candle)
        window.append(candle.close)
        if symbol in held_symbols or signal is None or signal.side != Side.BUY:
            continue
        rolling_min = min(window)
        depth = (rolling_min - candle.close) / rolling_min
        candidates.append((symbol, depth))
    candidates.sort(key=lambda c: c[1], reverse=True)
    return candidates


def _any_position_losing(open_lots: list[OpenLot], candles_today: dict[str, Candle]) -> bool:
    """Equivalent de `RiskManager.config.block_buy_if_any_position_losing`
    (EF-23) mais correct a plusieurs symboles : compare le prix DU JOUR de
    CHAQUE position a SON PROPRE prix d'entree - jamais le prix d'un candidat
    different contre l'entree d'un autre symbole."""
    for lot in open_lots:
        candle = candles_today.get(lot.symbol)
        if candle is not None and candle.close < lot.position.avg_entry_price:
            return True
    return False


# --- Couts reels, mesures et non supposes (EF-74) ---
#
# `fee_pct` seul sous-estimait massivement les couts de ce bot. Deux postes
# manquaient, tous deux ecrasants a la taille de position visee ici :
#
# 1. **Le plancher de commission IBKR.** Mesure le 2026-09-18 contre le
#    compte paper reel (`whatIfOrder`, qui chiffre un ordre sans le
#    transmettre) sur Euronext Paris : la commission ne descend JAMAIS sous
#    3,00 EUR par ordre, et ce plancher domine jusqu'a environ 12 000 EUR
#    d'ordre (au-dela, 0,025 % de la valeur prend le relais). Sur une
#    position de 200 EUR, cela represente 1,5 % - contre 0,20 EUR (0,1 %)
#    que modelisait l'ancien calcul, soit un facteur 15.
# 2. **La taxe francaise sur les transactions financieres**, 0,4 % depuis le
#    2025-04-01, prelevee A L'ACHAT seulement, sur les titres de societes
#    dont le siege est en France et la capitalisation depasse 1 milliard
#    d'euros. Approximation assumee : appliquee aux tickers `.PA`, ce qui
#    couvre tout l'univers francais du scanner et exclut correctement
#    Amsterdam.
#
# Consequence a 200 EUR de position : 3,00 + 0,80 a l'achat et 3,00 a la
# vente, soit environ 3,4 % d'aller-retour a absorber avant tout gain.
IBKR_MIN_COMMISSION_EUR = 3.0
IBKR_LARGE_ORDER_PCT = 0.00025
FRENCH_FTT_PCT = 0.004


def order_commission(value: float, fee_pct: float, fee_fixed: float = IBKR_MIN_COMMISSION_EUR) -> float:
    """Commission d'un ordre : un pourcentage, mais jamais moins que le
    plancher du courtier. C'est ce plancher qui decide de la viabilite d'une
    strategie a petites positions, donc il ne peut pas rester implicite."""
    return max(fee_fixed, value * fee_pct)


def purchase_tax(symbol: str, value: float, ftt_pct: float = FRENCH_FTT_PCT) -> float:
    """Taxe sur les transactions financieres, a l'ACHAT uniquement. Une vente
    n'en paie pas : c'est ce qui rend le cout d'un aller-retour asymetrique."""
    return value * ftt_pct if symbol.upper().endswith(".PA") else 0.0


def run_multi_symbol_backtest(
    universe: list[str], since_iso: str, capital: float,
    strategy_params: dict, risk_params: dict,
    exchange: str = "yfinance", timeframe: str = "1d",
) -> ScannerResult:
    """Point d'entree CLI/simple : telecharge (`fetch_historical_candles`,
    mis en cache disque par symbole) puis delegue a `simulate` - separe pour
    permettre a un sweep de parametres de telecharger UNE SEULE FOIS par
    symbole et reutiliser les memes bougies en memoire sur des centaines de
    combinaisons, plutot que de re-declencher cette fonction (et son cout de
    lecture Parquet) a chaque combinaison testee."""
    candles_by_symbol: dict[str, list[Candle]] = {
        symbol: fetch_historical_candles(exchange_id=exchange, symbol=symbol, timeframe=timeframe, since_iso=since_iso)
        for symbol in universe
    }
    return simulate(candles_by_symbol, capital, strategy_params, risk_params)


def simulate(
    candles_by_symbol: dict[str, list[Candle]], capital: float, strategy_params: dict, risk_params: dict,
) -> ScannerResult:
    """Coeur de la simulation, isole de tout telechargement - prend des
    bougies DEJA chargees (et eventuellement deja decoupees train/test par
    l'appelant) pour chaque symbole de l'univers."""
    universe = list(candles_by_symbol.keys())
    candles_by_day: dict[str, dict[str, Candle]] = {}
    for symbol, candles in candles_by_symbol.items():
        for candle in candles:
            candles_by_day.setdefault(_day_key(candle.timestamp), {})[symbol] = candle

    all_days = sorted(candles_by_day.keys())

    strategies = {s: DipBounceStrategy(**strategy_params) for s in universe}
    trend_ma_period = strategy_params.get("trend_ma_period", 24)
    recent_windows = {s: deque(maxlen=trend_ma_period) for s in universe}
    risk_manager = RiskManager(RiskConfig(**risk_params))
    max_concurrent = risk_manager.config.max_concurrent_positions

    cash = capital
    open_lots: list[OpenLot] = []
    closed_trades: list[ClosedTrade] = []
    equity_curve: list[tuple[str, float]] = []
    last_known_price: dict[str, float] = {}
    next_lot_id = 1

    for day in all_days:
        candles_today = candles_by_day[day]
        for symbol, candle in candles_today.items():
            last_known_price[symbol] = candle.close

        # 1) Verifie les sorties sur chaque position ouverte, avec le prix
        # DU JOUR pour SON PROPRE symbole (jamais celui d'un autre).
        still_open = []
        for lot in open_lots:
            candle = candles_today.get(lot.symbol)
            if candle is None:
                still_open.append(lot)  # jour non ouvre pour ce symbole (ferie local, decalage de place) - rien a verifier
                continue
            current_price = candle.close
            lot.position.peak_price = max(lot.position.peak_price, current_price)
            reason = None
            if risk_manager.should_stop_loss(lot.position, current_price):
                reason = "stop_loss"
            elif risk_manager.should_trailing_stop(lot.position, current_price):
                reason = "trailing_stop"
            elif risk_manager.should_take_profit(lot.position, current_price):
                reason = "take_profit"
            elif risk_manager.should_profit_lock(lot.position, current_price):
                reason = "profit_lock"
            if reason is None:
                still_open.append(lot)
                continue
            proceeds = lot.position.quantity * current_price
            fee = order_commission(proceeds, risk_manager.config.fee_pct)
            cost_basis = lot.position.quantity * lot.position.avg_entry_price + lot.position.entry_fee
            cash += proceeds - fee
            closed_trades.append(ClosedTrade(
                symbol=lot.symbol, entry_timestamp=lot.position.entry_timestamp,
                entry_price=lot.position.avg_entry_price, exit_timestamp=candle.timestamp,
                exit_price=current_price, quantity=lot.position.quantity, reason=reason,
                pnl=proceeds - fee - cost_basis,
            ))
        open_lots = still_open

        # 2) Scanne les symboles libres, classe les signaux par profondeur.
        held_symbols = {lot.symbol for lot in open_lots}
        ranked = scan_and_rank(candles_today, strategies, recent_windows, held_symbols)

        # 3) Achete dans l'ordre de force jusqu'a epuisement du cash/positions.
        block_new_buys = risk_manager.config.block_buy_if_any_position_losing and _any_position_losing(open_lots, candles_today)
        if not block_new_buys:
            for symbol, _depth in ranked:
                if len(open_lots) >= max_concurrent:
                    break
                candle = candles_today[symbol]
                reference_capital = min(capital, cash)
                quantity = risk_manager.size_for_signal(reference_capital, candle.close)
                cost = quantity * candle.close
                fee = (order_commission(cost, risk_manager.config.fee_pct)
                       + purchase_tax(symbol, cost))
                if quantity <= 0 or cost + fee > cash:
                    continue
                cash -= cost + fee
                open_lots.append(OpenLot(symbol=symbol, position=Position(
                    quantity=quantity, avg_entry_price=candle.close, entry_timestamp=candle.timestamp,
                    lot_id=next_lot_id, entry_fee=fee, peak_price=candle.close,
                )))
                next_lot_id += 1

        day_equity = cash + sum(
            lot.position.quantity * last_known_price.get(lot.symbol, lot.position.avg_entry_price)
            for lot in open_lots
        )
        equity_curve.append((day, day_equity))

    benchmark_pct = {
        symbol: (compute_buy_and_hold_return_pct(candles) or 0.0) * 100
        for symbol, candles in candles_by_symbol.items()
        if candles
    }

    return ScannerResult(
        starting_capital=capital, ending_cash=cash, closed_trades=closed_trades,
        open_lots=open_lots, equity_curve=equity_curve, per_symbol_benchmark_pct=benchmark_pct,
    )


def format_report(result: ScannerResult, universe: list[str], since: str, strategy_params: dict, risk_params: dict) -> str:
    final_equity = result.equity_curve[-1][1] if result.equity_curve else result.starting_capital
    total_return_pct = (final_equity - result.starting_capital) / result.starting_capital * 100
    basket_benchmark_pct = (
        sum(result.per_symbol_benchmark_pct.values()) / len(result.per_symbol_benchmark_pct)
        if result.per_symbol_benchmark_pct else 0.0
    )

    lines = [
        "=== Rapport de backtest - scanner multi-actions ===",
        f"Genere le          : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Univers ({len(universe)}) : {', '.join(universe)}",
        f"Periode            : {since} -> maintenant",
        "",
        "Parametres de la strategie (identiques pour chaque action) :",
    ]
    for key, value in strategy_params.items():
        lines.append(f"  - {key} = {value}")
    lines.append("")
    lines.append("Parametres de risque :")
    for key, value in risk_params.items():
        lines.append(f"  - {key} = {value}")
    lines += [
        "",
        "--- Performance ---",
        f"Capital de depart      : {result.starting_capital:.2f}",
        f"Capital final          : {final_equity:.2f}",
        f"Rendement total        : {total_return_pct:+.2f} %",
        f"Benchmark panier egal-pondere (buy&hold moyen des {len(result.per_symbol_benchmark_pct)} actions) : {basket_benchmark_pct:+.2f} %",
        f"Positions encore ouvertes en fin de periode : {len(result.open_lots)}",
    ]
    if result.open_lots:
        for lot in result.open_lots:
            lines.append(f"  - {lot.symbol} : {lot.position.quantity:.4f} @ {lot.position.avg_entry_price:.2f}")

    lines += ["", "--- Trades (par ordre chronologique) ---", f"Nombre de trades : {len(result.closed_trades)}"]
    wins = [t for t in result.closed_trades if t.pnl > 0]
    if result.closed_trades:
        lines.append(f"Taux de reussite : {len(wins) / len(result.closed_trades) * 100:.1f} %")
        lines.append(f"P&L total realise : {sum(t.pnl for t in result.closed_trades):+.2f}")
    for trade in result.closed_trades:
        lines.append(
            f"  {trade.symbol:<8} entree {trade.entry_price:.2f} -> sortie {trade.exit_price:.2f} "
            f"({trade.reason}) : {trade.pnl:+.2f}"
        )

    lines += ["", "--- Repartition par action (buy&hold individuel, pour comparaison) ---"]
    for symbol, pct in sorted(result.per_symbol_benchmark_pct.items(), key=lambda kv: kv[1], reverse=True):
        trades_for_symbol = sum(1 for t in result.closed_trades if t.symbol == symbol)
        lines.append(f"  {symbol:<8} buy&hold {pct:+7.2f} % | {trades_for_symbol} trade(s) du scanner")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest d'un scanner multi-actions (dip_bounce sur un panier, le creux le plus profond l'emporte)")
    parser.add_argument("--universe", default=",".join(DEFAULT_UNIVERSE), help="Tickers separes par des virgules")
    parser.add_argument("--exchange", default="yfinance", help="Source de donnees (defaut: yfinance)")
    parser.add_argument("--timeframe", default="1d", help="Timeframe (defaut: 1d - seul supporte pour yfinance)")
    parser.add_argument("--since", required=True, help="Debut de periode, AAAA-MM-JJ")
    parser.add_argument("--capital", type=float, default=1000.0, help="Capital de depart partage entre toutes les actions (defaut: 1000)")
    parser.add_argument("--trend-ma-period", dest="trend_ma_period", type=int, default=10, help="Fenetre de tendance en jours (defaut: 10)")
    parser.add_argument("--dip-threshold-pct", dest="dip_threshold_pct", type=float, default=1.0, help="Seuil de creux en %% (defaut: 1)")
    parser.add_argument("--stop-loss-pct", dest="stop_loss_pct", type=float, default=12.0, help="Stop-loss en %% (defaut: 12, vide desactive via --no-stop-loss)")
    parser.add_argument("--no-stop-loss", dest="no_stop_loss", action="store_true", help="Desactive le stop-loss")
    # Le trailing stop (et NON un take-profit fixe) est la sortie par defaut : un
    # take-profit plafonne le gain de chaque trade, ce qui coute tres cher sur les
    # actions fortement tendancielles de l'univers, et empeche toute reprise de
    # position ensuite (dip_bounce n'a plus de creux a acheter dans une hausse
    # soutenue). Mesure a l'appui, voir STC §3.49.
    parser.add_argument("--trailing-stop-pct", dest="trailing_stop_pct", type=float, default=10.0, help="Trailing stop en %% (defaut: 10, vide desactive via --no-trailing-stop)")
    parser.add_argument("--no-trailing-stop", dest="no_trailing_stop", action="store_true", help="Desactive le trailing stop")
    parser.add_argument("--take-profit-pct", dest="take_profit_pct", type=float, default=None, help="Vend des que ce gain latent est atteint, en %% (desactive par defaut - plafonne le gain par trade, mesure comme nettement moins bon que le trailing stop)")
    parser.add_argument("--profit-lock-arm-pct", dest="profit_lock_arm_pct", type=float, default=None, help="Arme le verrou de gain une fois ce gain latent depasse, en %% (optionnel, avec --profit-lock-trigger-pct)")
    parser.add_argument("--profit-lock-trigger-pct", dest="profit_lock_trigger_pct", type=float, default=None, help="Vend si le gain retombe a ou sous ce seuil une fois le verrou arme, en %% (optionnel, avec --profit-lock-arm-pct)")
    parser.add_argument("--max-concurrent-positions", dest="max_concurrent_positions", type=int, default=5, help="Nombre d'actions detenues en parallele au maximum (defaut: 5)")
    parser.add_argument("--max-position-size-pct", dest="max_position_size_pct", type=float, default=33.0, help="Taille de position max en %% du capital de reference (defaut: 33)")
    parser.add_argument("--fee-pct", dest="fee_pct", type=float, default=0.1, help="Frais par ordre en %% (defaut: 0.1)")
    parser.add_argument("--no-block-buy-if-losing", dest="no_block_buy_if_losing", action="store_true", help="N'empeche pas les nouveaux achats quand une position est deja en perte (EF-23, actif par defaut)")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    universe = [s.strip().upper() for s in args.universe.split(",") if s.strip()]

    strategy_params = {"trend_ma_period": args.trend_ma_period, "dip_threshold_pct": args.dip_threshold_pct / 100}
    risk_params = {
        "max_position_size_pct": args.max_position_size_pct / 100,
        "stop_loss_pct": None if args.no_stop_loss else args.stop_loss_pct / 100,
        "max_concurrent_positions": args.max_concurrent_positions,
        "trailing_stop_pct": None if args.no_trailing_stop else (args.trailing_stop_pct / 100),
        "take_profit_pct": (args.take_profit_pct / 100) if args.take_profit_pct else None,
        "profit_lock_arm_pct": (args.profit_lock_arm_pct / 100) if args.profit_lock_arm_pct else None,
        "profit_lock_trigger_pct": (args.profit_lock_trigger_pct / 100) if args.profit_lock_trigger_pct else None,
        "fee_pct": args.fee_pct / 100,
        "block_buy_if_any_position_losing": not args.no_block_buy_if_losing,
    }

    result = run_multi_symbol_backtest(
        universe=universe, since_iso=f"{args.since}T00:00:00Z", capital=args.capital,
        strategy_params=strategy_params, risk_params=risk_params,
        exchange=args.exchange, timeframe=args.timeframe,
    )
    print(format_report(result, universe, args.since, strategy_params, risk_params))


if __name__ == "__main__":
    main(sys.argv[1:])
