"""Point d'entree CLI pour lancer une instance en mode paper (testnet).

Usage:
    python -m tradingbot.run_paper config/example_instance.yml

Necessite BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET dans .env
(voir .env.example). Aucun argent reel n'est engage (EF-04 de la STB).

Chaque instance (une config = une instance, voir STB section 3.2) a son
propre verrou anti-doublon, mais elles partagent toutes le meme dashboard
(dashboard.html) avec un onglet par instance : lance plusieurs bots, ils
apparaissent tous dans la meme page.
"""

import datetime
import os
import sys
import time
import webbrowser
import zlib
from collections import deque
from pathlib import Path

import yaml
from dotenv import load_dotenv

from tradingbot.analysis.atr_sizer import AtrSizer
from tradingbot.analysis.price_level_sizer import PriceLevelSizer
from tradingbot.analysis.probability_gate import ProbabilityGate
from tradingbot.analysis.trend_filter import TrendFilter
from tradingbot.engine import Engine
from tradingbot.execution.ib_paper_executor import IBPaperExecutor
from tradingbot.execution.paper_executor import PaperExecutor
from tradingbot.mm_engine import MarketMakingEngine
from tradingbot.process_lock import acquire_lock
from tradingbot.reporting.dashboard import MASTER_DASHBOARD_PATH, write_dashboard
from tradingbot.reporting.logger import TradeLogger
from tradingbot.reporting.stats import build_orders_table, compute_report
from tradingbot.risk.risk_manager import MarketMakingConfig, RiskConfig, RiskManager
from tradingbot.run_backtest import build_strategy
from tradingbot.shared_pool import SharedPool
from tradingbot.manual_triggers import EXECUTED, REJECTED, TriggerStore
from tradingbot.types import Candle, Side, Signal

IBKR_SHARED_POOL_DB_PATH = "data/shared_pool_ibkr.db"  # panier de capital SEPARE du panier crypto (EF-65)

DEFAULT_WARMUP_CANDLES = 50
MAX_RECENT_LOGS = 10
MAX_PRICE_HISTORY_POINTS = 200


def restore_persisted_state(portfolio, logger: TradeLogger) -> bool:
    """Recharge l'historique des trades clotures, la courbe de capital et les
    positions encore ouvertes depuis SQLite (EF-25, EF-27). Retourne True si
    c'est un tout premier lancement (rien a restaurer), False s'il s'agit
    d'une reprise apres coupure (extinction du PC, crash, redemarrage)."""
    portfolio.trade_history = logger.load_closed_trades()
    portfolio.realized_pnl = sum(t["pnl"] for t in portfolio.trade_history)
    portfolio.total_fees_paid = sum(t.get("fees_paid", 0.0) for t in portfolio.trade_history)
    portfolio.equity_curve = logger.load_equity_curve()

    positions_from_db = logger.load_open_positions()
    is_first_ever_run = not (positions_from_db or portfolio.trade_history or portfolio.equity_curve)

    known_lot_ids = [t.get("lot_id") or 0 for t in portfolio.trade_history]
    known_lot_ids += [p.lot_id for p in positions_from_db]
    if known_lot_ids:
        portfolio._next_lot_id = max(known_lot_ids) + 1

    if not is_first_ever_run:
        # On ignore la position "devinee" a partir du solde reel de l'exchange
        # (PaperExecutor._load_portfolio_from_exchange) : plusieurs bots
        # partagent le meme compte testnet, cette estimation peut donc
        # attribuer a tort le solde d'un AUTRE bot. Notre propre historique
        # SQLite est la seule source de verite fiable pour CETTE instance.
        portfolio.positions = positions_from_db

    return is_first_ever_run


def trend_status(trend_filter: TrendFilter | None, current_price: float) -> dict | None:
    """Resume l'etat du filtre de tendance pour l'affichage dashboard (voir
    la feuille de route performance, etape 1) : None si le filtre n'est pas
    active pour cette instance."""
    if trend_filter is None:
        return None
    return {
        "ema_period": trend_filter.ema_period,
        "ema": trend_filter.ema,
        "is_bullish": trend_filter.is_bullish(current_price) if trend_filter.ema is not None else None,
    }


def atr_sizer_status(atr_sizer: AtrSizer | None) -> dict | None:
    """Resume l'etat du sizing par volatilite pour l'affichage dashboard
    (feuille de route performance, etape 2). None si desactive."""
    if atr_sizer is None:
        return None
    return {
        "atr_period": atr_sizer.atr_period,
        "baseline_period": atr_sizer.baseline_period,
        "size_multiplier": atr_sizer.size_multiplier() if atr_sizer.atr is not None else None,
    }


def price_level_sizer_status(price_level_sizer: PriceLevelSizer | None) -> dict | None:
    """Resume l'etat du sizing par niveau de prix pour l'affichage dashboard
    (idee proposee par l'utilisateur). None si desactive."""
    if price_level_sizer is None:
        return None
    return {
        "month_average": price_level_sizer.month_average,
        "min_size_multiplier": price_level_sizer.min_size_multiplier,
        "max_size_multiplier": price_level_sizer.max_size_multiplier,
    }


def compute_restored_cash(capital_allocated: float, realized_pnl: float, positions: list) -> float:
    """Reconstruit le cash a partir du capital de depart : le cash n'est pas
    persiste directement, il se deduit entierement des trades clotures deja
    nets de frais (realized_pnl) et du capital immobilise dans les positions
    encore ouvertes (prix d'entree x quantite + frais d'entree)."""
    tied_up = sum(p.quantity * p.avg_entry_price + p.entry_fee for p in positions)
    return capital_allocated + realized_pnl - tied_up


def flatten_existing_position(executor, symbol: str, logger: TradeLogger) -> None:
    """Vide toute position deja presente au demarrage (ex: solde de test
    offert par le testnet Binance) pour repartir a zero. Sans ca, le bot
    croit etre deja en position et attend un signal de vente avant de
    pouvoir acheter, ce qui peut prendre tres longtemps sans rapport avec
    la strategie.

    CT-27 (bug reel constate) : cette position vient du solde REEL de
    l'exchange (`PaperExecutor._load_portfolio_from_exchange`), jamais
    achetee via NOTRE `capital_allocated` (deja reinitialise a part dans
    `main()`) - la vendre via `portfolio.apply_fill` (ancienne version)
    creditait a tort son PRODUIT COMPLET sur notre cash, gonflant l'equity
    de plusieurs centaines d'unites des le tout premier demarrage, sans le
    moindre trade de strategie (constate sur `BTC_SWING_V2`/`ETH_SWING_V2` :
    equity a +272/+101 avant meme un warmup complet). L'ordre de vente est
    toujours passe REELLEMENT sur l'exchange (evite de laisser trainer de la
    poussiere qui fausserait un futur redemarrage), mais n'est plus jamais
    impute a notre portefeuille : ni cash, ni P&L, ni historique de trades -
    purement un nettoyage cote exchange, invisible cote strategie/stats."""
    positions = executor.get_positions()
    if not positions:
        return

    current_price = executor.exchange.fetch_ticker(symbol)["last"]
    for position in positions:
        try:
            rounded_quantity = float(executor.exchange.amount_to_precision(symbol, position.quantity))
            if rounded_quantity > 0:
                executor.exchange.create_order(symbol, "market", "sell", rounded_quantity)
        except Exception as e:
            logger.log_event(
                "warning",
                f"Impossible de liquider sur l'exchange la position preexistante ({position.quantity}) : {e} "
                f"- ignoree localement quand meme (jamais comptee dans notre capital).",
            )
        logger.log_event(
            "info",
            f"Position preexistante ({position.quantity}) ignoree au demarrage - solde de test sans lien "
            f"avec le capital alloue, jamais comptee dans le P&L.",
        )
        print(f"Position preexistante ({position.quantity}) ignoree au demarrage (hors capital alloue, sans impact sur le P&L).")
    executor.portfolio.positions = []


def ignore_existing_position(executor, logger: TradeLogger) -> None:
    """Premier lancement SANS liquidation (`flatten_on_start: false`, EF-98) :
    le solde trouve sur l'exchange n'appartient pas a ce bot - sur un compte
    testnet PARTAGE, c'est celui des autres bots ou du panier manuel. On ne le
    vend pas (c'etait l'incident du 2026-09-26) et on ne l'adopte pas non plus :
    bug reel du 2026-10-01, ETH_MOMENTUM a son lancement s'est attribue les
    0,0928 ETH d'ETH_youenn et d'ETH_TREND_REGIME (gain affiche +50 % sans aucun
    ordre, aucun achat possible, et sa premiere vente aurait vendu leur ETH).
    Meme regle qu'a la reprise de session (`restore_persisted_state`) : seul
    l'historique propre du bot fait foi."""
    for position in executor.portfolio.positions:
        message = (f"Solde preexistant sur l'exchange ({position.quantity}) ignore au premier lancement : "
                   "ni vendu ni attribue a ce bot (compte partage, flatten_on_start desactive).")
        logger.log_event("info", message)
        print(message)
    executor.portfolio.positions = []


def poll_new_closed_candle(exchange, symbol: str, timeframe: str, last_seen_ts: int | None) -> Candle | None:
    """Recupere la derniere bougie CLOSE (pas celle en cours de formation)."""
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=2)
    if len(ohlcv) < 2:
        return None
    closed_row = ohlcv[-2]  # la derniere ligne (ohlcv[-1]) est la bougie en cours, non close
    timestamp = int(closed_row[0])
    if last_seen_ts is not None and timestamp <= last_seen_ts:
        return None
    return _row_to_candle(closed_row)


def fine_exit_check(engine, executor, logger: TradeLogger, current_price: float, now: float) -> list[str]:
    """Verification des sorties entre deux bougies (surveillance fine, 5m).

    Les positions sont enregistrees a CHAQUE passage, pas seulement quand une
    vente a lieu : ce passage met a jour le plus haut (`peak_price`) qui sert
    au trailing stop. Enregistre seulement a la bougie horaire, il etait perdu
    a chaque redemarrage du bot - qui repartait d'un plus haut plus ancien,
    donc d'un trailing plus bas (constate le 2026-09-27 sur ETH_youenn : plus
    haut en base 2691.53, soit le prix d'achat, contre 2709.68 vu en memoire)."""
    fine_candle = Candle(
        timestamp=int(now * 1000), open=current_price, high=current_price,
        low=current_price, close=current_price, volume=0.0,
    )
    messages = engine.process_price_update(fine_candle)
    logger.save_open_positions(executor.portfolio.positions)
    if messages:
        logger.log_equity(fine_candle.timestamp, executor.portfolio.equity(current_price))
        for message in messages:
            print(f"[{fine_candle.timestamp}] (surveillance fine) {message}")
    return messages


def strategy_chart_levels(strategy) -> list[dict]:
    """Niveaux de prix propres a la strategie, a tracer sur le graphique
    (EF-88) : `[{"price", "label", "kind"}]`. Liste vide pour une strategie
    qui n'en expose pas - jamais d'erreur pour un simple affichage."""
    getter = getattr(strategy, "chart_levels", None)
    if getter is None:
        return []
    try:
        return [lvl for lvl in getter() if lvl.get("price")]
    except Exception:
        return []


def is_transient_network_error(error: BaseException) -> bool:
    """Vrai pour une erreur de RESEAU passagere (coupure, delai depasse,
    exchange momentanement indisponible, limite de debit) - qu'il suffit de
    reessayer. Faux pour tout le reste (erreur de logique, cle invalide,
    symbole inconnu) : celles-la doivent continuer a arreter le bot plutot
    que d'etre masquees par des essais sans fin."""
    try:
        import ccxt

        if isinstance(error, ccxt.NetworkError):  # inclut RequestTimeout, ExchangeNotAvailable, DDoSProtection
            return True
        if isinstance(error, ccxt.ExchangeError):
            return False
    except ImportError:
        pass
    try:
        import requests

        if isinstance(error, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            return True
    except ImportError:
        pass
    return isinstance(error, (ConnectionError, TimeoutError))


def build_market_data_exchange(exchange_id: str, fallback=None):
    """Client ccxt PUBLIC (aucune cle, aucun ordre possible) pour les donnees de
    marche du mode paper. Repli sur `fallback` (le client testnet) si le
    client public ne peut pas etre construit, pour ne jamais empecher un bot
    de demarrer - le message de rechauffement incomplet signalera alors la
    limite du testnet."""
    try:
        import ccxt

        return getattr(ccxt, exchange_id)({"enableRateLimit": True})
    except Exception:
        return fallback


def _row_to_candle(row) -> Candle:
    return Candle(
        timestamp=int(row[0]),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
    )


EXCHANGE_OHLCV_PAGE_LIMIT = 1000


def _fetch_ohlcv_paginated(exchange, symbol: str, timeframe: str, total: int) -> list:
    """Recupere les `total` dernieres bougies, en plusieurs requetes si besoin.

    BUG CORRIGE : Binance plafonne a 1000 bougies par requete (verifie
    empiriquement - demander 2001 en renvoie 1000). L'ancienne version faisait
    UNE seule requete, si bien que toute config avec `warmup_candles` > 999
    demarrait avec une strategie SOUS-RECHAUFFEE, sans erreur ni
    avertissement : son EMA restait influencee par sa valeur d'amorce et ses
    decisions en direct divergeaient de tout backtest. Le defaut etait
    silencieux, donc invisible.

    En dessous du plafond, on garde exactement l'ancien chemin a une requete :
    les bots existants (rechauffement de 100 a 500 bougies) ne changent pas
    de comportement."""
    if total <= EXCHANGE_OHLCV_PAGE_LIMIT:
        return exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=total)

    step_ms = exchange.parse_timeframe(timeframe) * 1000
    since = exchange.milliseconds() - total * step_ms
    rows: list = []
    seen: set[int] = set()
    while len(rows) < total:
        page = exchange.fetch_ohlcv(
            symbol, timeframe=timeframe, since=since, limit=EXCHANGE_OHLCV_PAGE_LIMIT,
        )
        fresh = [row for row in page if row[0] not in seen]
        if not fresh:
            break  # l'exchange ne renvoie plus rien de nouveau : on s'arrete
        rows.extend(fresh)
        seen.update(row[0] for row in fresh)
        since = fresh[-1][0] + step_ms
    return rows[-total:]


def warm_up_strategy(
    exchange, symbol: str, timeframe: str, strategy, warmup_candles: int,
    price_history: deque | None = None, trend_filter: TrendFilter | None = None,
    atr_sizer: AtrSizer | None = None, price_level_sizer: PriceLevelSizer | None = None,
) -> int | None:
    """Alimente la strategie avec l'historique recent sans passer d'ordres,
    pour ne pas attendre `warmup_candles` heures avant le premier signal
    possible en mode paper. Alimente aussi `price_history` (si fourni) pour
    que le graphique du cours affiche immediatement du contexte au lieu de
    partir d'une page blanche (EF-28), `trend_filter` (si fourni) pour que
    son EMA ne soit pas "a froid" au premier signal d'achat reel, `atr_sizer`
    (si fourni) pour que sa baseline de volatilite soit deja formee avant le
    premier achat reel, et `price_level_sizer` (si fourni) pour que sa
    moyenne du mois calendaire en cours soit deja alimentee par l'historique
    plutot que de repartir de zero au demarrage."""
    warmup_needed = max(
        warmup_candles,
        trend_filter.ema_period if trend_filter else 0,
        atr_sizer.baseline_period if atr_sizer else 0,
    )
    # +2 : la bougie en cours (exclue) et la derniere close (laissee a la boucle, voir ci-dessous) ;
    # le rechauffage garde ainsi ses `warmup_needed` bougies completes.
    history = _fetch_ohlcv_paginated(exchange, symbol, timeframe, warmup_needed + 2)
    closed_history = history[:-1]  # on exclut la bougie en cours de formation
    # La DERNIERE bougie close n'est pas consommee ici : la boucle du bot la
    # recupere aussitot (poll_new_closed_candle, plus recente que la valeur
    # renvoyee) et la traite comme une vraie decision. Bug reel (2026-10-09) :
    # elle etait absorbee par le rechauffage, signal ignore, et le bot attendait
    # la cloture SUIVANTE - ETH_MOMENTUM (bougies jour, relance a chaque
    # ouverture de session) n'a pris aucune decision en 8 jours, sa seule
    # cloture etant a 2 h du matin, PC eteint.
    closed_history = closed_history[:-1]
    for row in closed_history:
        candle = _row_to_candle(row)
        if hasattr(strategy, "on_candle"):
            strategy.on_candle(candle)  # signal ignore : pure mise en etat
        # MarketMakingStrategy n'a pas d'etat a "rechauffer" (pas de fenetre
        # glissante, sa cotation depend seulement de la bougie courante et de
        # l'inventaire) - seul price_history/trend_filter/atr_sizer restent
        # utiles pour l'affichage dashboard, deja geres ci-dessous.
        if price_history is not None:
            price_history.append([candle.timestamp, candle.close, candle.open, candle.high, candle.low])
        if trend_filter is not None:
            trend_filter.update(candle.close)
        if atr_sizer is not None:
            atr_sizer.update(candle)
        if price_level_sizer is not None:
            price_level_sizer.update(candle)
    return int(closed_history[-1][0]) if closed_history else None


def _derive_ib_client_id(instance_name: str) -> int:
    """Chaque bot IBKR lance en sous-processus separe doit avoir un
    identifiant de connexion TWS UNIQUE - `zlib.crc32` (deterministe,
    contrairement au `hash()` natif de Python qui est aleatoire par
    processus depuis PYTHONHASHSEED) derive un entier stable a partir du nom
    du bot, evitant toute collision entre bots lances simultanement sans
    configuration manuelle. Surchargeable via `ibkr_client_id` dans la
    config si une collision se produit malgre tout (tres improbable a
    quelques bots)."""
    return (zlib.crc32(instance_name.encode()) % 9000) + 100


def _ib_row_to_candle(bar) -> Candle:
    bar_date = bar.date
    if hasattr(bar_date, "timestamp"):
        ts_ms = int(bar_date.timestamp() * 1000)
    else:  # bougie journaliere : ib_async renvoie un datetime.date, pas datetime.datetime
        ts_ms = int(datetime.datetime.combine(bar_date, datetime.time(tzinfo=datetime.timezone.utc)).timestamp() * 1000)
    return Candle(
        timestamp=ts_ms, open=float(bar.open), high=float(bar.high),
        low=float(bar.low), close=float(bar.close), volume=float(bar.volume),
    )


def ib_poll_new_closed_candle(ib, contract, last_seen_ts: int | None) -> Candle | None:
    """Equivalent de `poll_new_closed_candle` (ccxt) pour IBKR - BOUGIES
    JOURNALIERES uniquement (voir STC §3.46/§3.48 : simplification assumee,
    evite toute logique explicite d'heures de marche).

    L'affirmation precedente de cette docstring - "`reqHistoricalData` ne
    renvoie que des bougies deja closes, pas besoin d'exclure la derniere
    ligne" - etait **FAUSSE**, et refutee empiriquement le 2026-09-18
    (EF-75) : en pleine seance sur Euronext Paris, trois lectures successives
    de `TTE.PA` ont renvoye la MEME bougie du jour avec un volume qui
    montait (5 227 648 -> 5 241 433) et une cloture qui bougeait
    (79,505 -> 79,44 -> 79,48). La bougie du jour est bien incluse, et en
    cours de formation.

    La derniere ligne est donc exclue, **comme le faisait deja
    `ib_warm_up_strategy`** - les deux fonctions se contredisaient sur le
    comportement de la meme API, et c'est celle-ci qui avait tort.

    CONSEQUENCE ASSUMEE : le bot agit sur la derniere cloture COMPLETE, donc
    celle de la veille, et passe son ordre au prix du jour. Un backtest, lui,
    achete au cours de cloture qui a produit le signal - un prix qu'on ne
    peut connaitre qu'apres coup. Le paper est donc ici plus honnete que le
    backtest, et un ecart entre les deux est attendu (voir STC §3.58)."""
    bars = ib.reqHistoricalData(
        contract, endDateTime="", durationStr="5 D", barSizeSetting="1 day", whatToShow="TRADES", useRTH=True,
    )
    closed = bars[:-1]
    if not closed:
        return None
    candle = _ib_row_to_candle(closed[-1])
    if last_seen_ts is not None and candle.timestamp <= last_seen_ts:
        return None
    return candle


def ib_warm_up_strategy(
    ib, contract, strategy, warmup_candles: int,
    price_history: deque | None = None, trend_filter: TrendFilter | None = None,
    atr_sizer: AtrSizer | None = None, price_level_sizer: PriceLevelSizer | None = None,
) -> int | None:
    """Equivalent de `warm_up_strategy` (ccxt) pour IBKR - meme role, memes
    parametres, seule la source de l'historique change (`reqHistoricalData`
    au lieu de `fetch_ohlcv`)."""
    warmup_needed = max(
        warmup_candles,
        trend_filter.ema_period if trend_filter else 0,
        atr_sizer.baseline_period if atr_sizer else 0,
    )
    # +10 jours de marge : les jours non ouvres (week-ends/feries) ne
    # produisent aucune bougie, il faut demander plus de jours calendaires
    # que de bougies voulues pour etre sur d'en obtenir assez.
    bars = ib.reqHistoricalData(
        contract, endDateTime="", durationStr=f"{warmup_needed + 10} D",
        barSizeSetting="1 day", whatToShow="TRADES", useRTH=True,
    )
    closed_history = bars[-(warmup_needed + 1):-1] if len(bars) > warmup_needed else bars[:-1]
    for bar in closed_history:
        candle = _ib_row_to_candle(bar)
        if hasattr(strategy, "on_candle"):
            strategy.on_candle(candle)
        if price_history is not None:
            price_history.append([candle.timestamp, candle.close, candle.open, candle.high, candle.low])
        if trend_filter is not None:
            trend_filter.update(candle.close)
        if atr_sizer is not None:
            atr_sizer.update(candle)
        if price_level_sizer is not None:
            price_level_sizer.update(candle)
    if not closed_history:
        # EF-75 : ce cas renvoyait None SANS RIEN DIRE. Un bot demarrait donc
        # sur une strategie non rechauffee - donc prete a signaler n'importe
        # quoi - et n'echouait que bien plus loin, sur un message sans
        # rapport avec la cause reelle (contrat non qualifie, abonnement de
        # donnees absent, ticker mal traduit). Zero bougie journaliere n'est
        # jamais un etat de demarrage normal pour une action : on echoue ici.
        raise ValueError(
            f"IBKR n'a renvoye aucune bougie journaliere exploitable pour {contract.symbol} "
            f"({warmup_needed + 10} jours demandes, {len(bars)} bougie(s) recue(s)). Causes "
            "habituelles : contrat mal qualifie, ou abonnement aux donnees de marche absent "
            "pour cette place. Lance `python -m tradingbot.diagnose_ibkr` pour situer le probleme."
        )
    return _ib_row_to_candle(closed_history[-1]).timestamp


def ib_fetch_last_price(ib, contract) -> float:
    """Prix "actuel" pour IBKR en mode journalier : la cloture de la
    derniere bougie journaliere disponible (pas un flux temps reel, qui
    demanderait un abonnement aux donnees de marche IBKR meme en paper) -
    coherent avec le choix assume de bougies journalieres uniquement."""
    bars = ib.reqHistoricalData(
        contract, endDateTime="", durationStr="5 D", barSizeSetting="1 day", whatToShow="TRADES", useRTH=True,
    )
    if not bars:
        raise ValueError(f"Aucune bougie IBKR renvoyee pour {contract.symbol} - impossible d'en deduire un prix.")
    return float(bars[-1].close)


def main(config_path: str) -> None:
    load_dotenv()

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    instance_name = config["name"]
    lock_path = Path(f"bot_{instance_name}.lock")
    acquire_lock(lock_path)
    dashboard_already_existed = MASTER_DASHBOARD_PATH.exists()

    # EF-65 : "ibkr_paper" bascule sur le paper trading actions (Interactive
    # Brokers) au lieu du testnet Binance - meme esprit (argent fictif),
    # broker different. Voir STC §3.48 pour le detail de ce qui differe.
    is_ibkr = config["exchange"] == "ibkr_paper"

    strategy = build_strategy(config)
    is_market_making = config["strategy"]["type"] == "market_making"
    risk_manager = None if is_market_making else RiskManager(RiskConfig(**config["risk"]))
    mm_config = MarketMakingConfig(**config["risk"]) if is_market_making else None

    if is_ibkr:
        ib_host = os.environ.get("IBKR_HOST", "127.0.0.1")
        ib_port = int(os.environ.get("IBKR_PORT", "7497"))
        client_id = config.get("ibkr_client_id") or _derive_ib_client_id(instance_name)
        executor = IBPaperExecutor(config["symbol"], host=ib_host, port=ib_port, client_id=client_id)
    else:
        api_key = os.environ.get("BINANCE_TESTNET_API_KEY", "")
        api_secret = os.environ.get("BINANCE_TESTNET_API_SECRET", "")
        executor = PaperExecutor(config["exchange"], config["symbol"], api_key, api_secret)
    logger = TradeLogger(config["name"])
    # EF-88 : ordres "acheter si le cours descend sous X" poses depuis le
    # dashboard, stockes dans la base de CE bot et executes par lui.
    manual_triggers = TriggerStore(logger.db_path)
    recent_logs: deque[list] = deque(maxlen=MAX_RECENT_LOGS)
    price_history: deque[list] = deque(maxlen=MAX_PRICE_HISTORY_POINTS)

    # Frais de transaction simules (EF-22) et journalisation des trades clotures.
    executor.portfolio.fee_pct = mm_config.fee_pct if is_market_making else risk_manager.config.fee_pct
    executor.portfolio.on_trade_closed = logger.log_closed_trade

    # Les stats (win rate, P&L, courbe de capital) et les positions encore
    # ouvertes survivent aux redemarrages (EF-25, EF-27) : sans ca, chaque
    # "Modifier" ou coupure (extinction du PC) remettait tout a zero en
    # memoire alors que l'historique complet existe deja en SQLite.
    is_first_ever_run = restore_persisted_state(executor.portfolio, logger)

    def _on_decision(candle: Candle, message: str) -> None:
        ts = datetime.datetime.fromtimestamp(candle.timestamp / 1000).strftime("%H:%M:%S")
        recent_logs.append([ts, message])
        # EF-83 : les decisions ne vivaient qu'en MEMOIRE (`recent_logs`), perdues
        # a chaque redemarrage - et le PC redemarre chaque jour. Impossible alors
        # de savoir, apres coup, pourquoi un bot n'avait pas achete pendant
        # une semaine de regime haussier. Chaque decision est desormais
        # journalisee en base (une ligne par bougie, ~24 par jour et par bot).
        logger.log_event("decision", f"[bougie {ts}] {message}")
        print(f"[decision {ts}] {message}", flush=True)

    probability_filter_config = config.get("probability_filter") or {}
    probability_gate = None
    if probability_filter_config.get("enabled"):
        probability_gate = ProbabilityGate(
            exchange_id=config["exchange"],
            symbol=config["symbol"],
            min_probability=probability_filter_config.get("min_probability", 0.55),
            lookback_years=probability_filter_config.get("lookback_years", 3.0),
            n_simulations=probability_filter_config.get("n_simulations", 200_000),
        )
        print(
            f"Filtre de probabilite active : seuil {probability_gate.min_probability:.0%}, "
            f"{probability_gate.lookback_years} ans d'historique."
        )

    trend_filter_config = config.get("trend_filter") or {}
    trend_filter = None
    if trend_filter_config.get("enabled"):
        trend_filter = TrendFilter(ema_period=trend_filter_config.get("ema_period", 200))
        print(f"Filtre de tendance active : EMA{trend_filter.ema_period}.")

    atr_sizing_config = config.get("atr_sizing") or {}
    atr_sizer = None
    if atr_sizing_config.get("enabled"):
        atr_sizer = AtrSizer(
            atr_period=atr_sizing_config.get("atr_period", 14),
            baseline_period=atr_sizing_config.get("baseline_period", 100),
            min_size_multiplier=atr_sizing_config.get("min_size_multiplier", 0.2),
        )
        print(f"Sizing par volatilite active : ATR{atr_sizer.atr_period}/baseline{atr_sizer.baseline_period}.")

    price_level_sizing_config = config.get("price_level_sizing") or {}
    price_level_sizer = None
    if price_level_sizing_config.get("enabled"):
        price_level_sizer = PriceLevelSizer(
            min_size_multiplier=price_level_sizing_config.get("min_size_multiplier", 0.5),
            max_size_multiplier=price_level_sizing_config.get("max_size_multiplier", 1.5),
        )
        print(
            f"Sizing par niveau de prix active : "
            f"x{price_level_sizer.min_size_multiplier}-x{price_level_sizer.max_size_multiplier} "
            f"selon la moyenne du mois calendaire."
        )

    capital_allocated = config.get("capital_allocated")
    if capital_allocated is None:
        # Depuis le passage au panier de capital commun (STC section 3.5 revisee),
        # ce plafond est obligatoire pour toute instance : sans lui, un bot pourrait
        # viser la totalite du panier partage et affamer les 7 autres. L'ancien mode
        # "pas de plafond configure = on prend le solde reel du compte" n'a plus de
        # sens des lors que ce compte est explicitement partage entre plusieurs bots.
        raise ValueError(
            f"'capital_allocated' est obligatoire dans la config ({config_path}) : "
            "chaque bot doit declarer son plafond de mise dans le panier commun."
        )
    # `starting_capital` reste le plafond DE BASE de ce bot (module dynamiquement
    # par sa performance recente via shared_pool.effective_cap, voir Engine) - ce
    # n'est plus un budget qui lui serait exclusivement reserve : l'argent reel vient
    # desormais du panier commun (shared_pool.py), partage entre tous les bots.
    executor.portfolio.starting_capital = capital_allocated
    if is_first_ever_run:
        executor.portfolio.cash = capital_allocated
    else:
        executor.portfolio.cash = compute_restored_cash(
            capital_allocated, executor.portfolio.realized_pnl, executor.portfolio.positions
        )

    # Panier SEPARE pour les bots actions IBKR (EF-65) - ne jamais melanger
    # le capital crypto et le capital actions dans le meme fichier.
    shared_pool = SharedPool(IBKR_SHARED_POOL_DB_PATH) if is_ibkr else SharedPool()
    shared_pool.seed_if_empty(capital_allocated)  # sans effet si le panier existe deja (cas normal)
    known_order_costs = [o["quantity"] * o["price"] for o in logger.load_recent_buy_orders()]
    shared_pool.reconcile_orphaned_reservations(instance_name, known_order_costs)

    if is_market_making:
        engine = MarketMakingEngine(
            strategy, executor, executor.portfolio,
            on_fill=lambda order: logger.log_order(order, mode="paper"),
            on_decision=_on_decision,
            shared_pool=shared_pool,
            instance_name=instance_name,
            capital_cap=capital_allocated,
        )
    else:
        engine = Engine(
            strategy, risk_manager, executor, executor.portfolio,
            on_fill=lambda order: logger.log_order(order, mode="paper"),
            on_decision=_on_decision,
            probability_gate=probability_gate,
            trend_filter=trend_filter,
            atr_sizer=atr_sizer,
            price_level_sizer=price_level_sizer,
            shared_pool=shared_pool,
            instance_name=instance_name,
            capital_cap=capital_allocated,
        )

    logger.log_event("info", f"Demarrage mode paper pour {config['name']} ({config['symbol']})")

    if is_first_ever_run and config.get("flatten_on_start", True):
        flatten_existing_position(executor, config["symbol"], logger)
    elif is_first_ever_run:
        ignore_existing_position(executor, logger)
    elif not is_first_ever_run:
        logger.log_event(
            "info",
            f"Reprise apres coupure : {len(executor.portfolio.positions)} position(s) ouverte(s) restauree(s)",
        )
        print(f"Reprise de session : {len(executor.portfolio.positions)} position(s) ouverte(s) restauree(s).")

    # A partir d'ici, `fetch_current_price()`/`fetch_closed_candle(last_ts)`
    # abstraient la source de donnees (ccxt vs IBKR, EF-65) - le reste de la
    # boucle ne connait plus la difference. Cote ccxt, ce sont EXACTEMENT
    # les memes appels qu'avant (aucun changement de comportement crypto).
    if is_ibkr:
        fetch_current_price = lambda: ib_fetch_last_price(executor.ib, executor.contract)
        fetch_closed_candle = lambda last_ts: ib_poll_new_closed_candle(executor.ib, executor.contract, last_ts)
        timeframe_seconds = 86_400  # bougies journalieres uniquement pour IBKR (STC §3.46/§3.48)
    else:
        # EF-83 : les DONNEES de marche viennent du marche PUBLIC reel, les
        # ORDRES restent sur le testnet (executor.exchange). Le testnet Binance
        # ne conserve qu'environ 14 jours de bougies (339 en 1h, verifie) : un
        # bot demandant 500/1000/2000 bougies de rechauffement en recevait 338,
        # sa strategie n'atteignait jamais sa maturite et restait MUETTE - trois
        # bots en regime haussier franc n'ont pas passe un seul ordre en six
        # jours. Le marche public a tout l'historique, et c'est la serie de prix
        # sur laquelle la strategie a ete validee.
        exchange = build_market_data_exchange(config["exchange"], executor.exchange)
        fetch_current_price = lambda: exchange.fetch_ticker(config["symbol"])["last"]
        fetch_closed_candle = lambda last_ts: poll_new_closed_candle(exchange, config["symbol"], config["timeframe"], last_ts)
        timeframe_seconds = exchange.parse_timeframe(config["timeframe"])

    baseline_price = fetch_current_price()

    # Etat de depart persiste immediatement : si le PC s'eteint avant meme la
    # premiere bougie traitee, une reprise ulterieure retrouve quand meme cet
    # etat (plutot qu'un open_positions vide venant d'un run precedent).
    logger.save_open_positions(executor.portfolio.positions)

    warmup_candles = config.get("warmup_candles", DEFAULT_WARMUP_CANDLES)
    if is_ibkr:
        last_seen_ts = ib_warm_up_strategy(
            executor.ib, executor.contract, strategy, warmup_candles,
            price_history, trend_filter, atr_sizer, price_level_sizer,
        )
    else:
        last_seen_ts = warm_up_strategy(
            exchange, config["symbol"], config["timeframe"], strategy, warmup_candles,
            price_history, trend_filter, atr_sizer, price_level_sizer,
        )
    # EF-83 : ce message affichait le nombre DEMANDE, pas le nombre RECU - il
    # annoncait "500 bougies" pendant que la strategie n'en avait vu que 338.
    fed = getattr(strategy, "_seen", None)
    needed = getattr(strategy, "warmup_candles", None)
    if fed is not None and needed is not None and fed < needed:
        missing = needed - fed
        message = (
            f"RECHAUFFEMENT INCOMPLET : {fed} bougies recues sur {needed} necessaires - la strategie restera "
            f"MUETTE (aucun achat ni vente) pendant encore {missing} bougie(s) {config['timeframe']}, "
            "et repartira de zero a chaque redemarrage. Source de donnees trop courte ?"
        )
        logger.log_event("warning", message)
        print(message, flush=True)
    else:
        print(f"Strategie rechauffee avec {fed if fed is not None else warmup_candles} bougies d'historique.")

    poll_interval_seconds = min(60, timeframe_seconds)

    # Surveillance des sorties a granularite fine (EF-53) - demande de
    # l'utilisateur ("ce reglage sur tous les bots") : verifie stop-loss/
    # verrou de gain/trailing plus souvent que le timeframe d'entree, sans
    # attendre la bougie suivante. Reutilise le prix deja recupere via le
    # ticker a chaque cycle de sondage (aucun appel reseau supplementaire).
    # Sans objet pour le market making (pas de `process_price_update`,
    # cotation continue par nature) ni pour IBKR (bougies journalieres
    # uniquement, une surveillance plus fine n'aurait pas de sens la ou le
    # choix assume est justement d'eviter toute granularite intrajournaliere) -
    # `exit_check_timeframe` y est ignore dans les 2 cas.
    exit_check_timeframe = config.get("exit_check_timeframe")
    exit_check_interval_seconds = (
        exchange.parse_timeframe(exit_check_timeframe)
        if exit_check_timeframe and not is_market_making and not is_ibkr
        else None
    )
    last_exit_check_ts = time.time()
    if exit_check_interval_seconds is not None:
        print(f"Surveillance des sorties activee : toutes les {exit_check_timeframe}.")

    # build_orders_table() (reporting/stats.py) affiche des prix cibles
    # stop-loss/take-profit calcules a partir d'une RiskConfig - concept sans
    # sens pour le market making (pas de stop-loss/take-profit). On lui passe
    # une RiskConfig par defaut uniquement pour l'affichage, sans impact sur
    # la logique de trading (qui passe par MarketMakingEngine/MarketMakingConfig).
    display_risk_config = RiskConfig() if is_market_making else risk_manager.config

    print(f"Mode paper demarre sur {config['symbol']} ({config['timeframe']}). Ctrl+C pour arreter.")

    write_dashboard(
        instance_name=instance_name,
        symbol=config["symbol"],
        mode="paper",
        portfolio=executor.portfolio,
        current_price=baseline_price,
        updated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        logs=list(recent_logs),
        probability_up_24h=(probability_gate.current_probability() if probability_gate else None),
        orders=build_orders_table(executor.portfolio, display_risk_config),
        price_history=list(price_history),
        trend_filter_status=trend_status(trend_filter, baseline_price),
        atr_sizer_status=atr_sizer_status(atr_sizer),
        price_level_sizer_status=price_level_sizer_status(price_level_sizer),
        pool_available_cash=shared_pool.available_cash(),
        effective_cap=shared_pool.effective_cap(instance_name, capital_allocated),
        chart_levels=strategy_chart_levels(strategy),
    )
    if not dashboard_already_existed:
        webbrowser.open(MASTER_DASHBOARD_PATH.resolve().as_uri())

    try:
        network_outage_since = None
        while True:
            # EF-85 : une SEULE coupure reseau tuait le bot. Le 2026-09-25 a
            # 02h09, `fetch_ticker` a recu "connexion fermee par l'hote
            # distant" ; l'exception a remonte jusqu'ici, le processus est
            # mort, et le bot ETH est reste six heures a l'arret AVEC une
            # position ouverte - donc sans pouvoir la vendre si la tendance
            # s'etait retournee. Seule la LECTURE des donnees de marche est
            # rattrapee ici : aucun ordre n'est passe a ce stade, reessayer
            # au cycle suivant est sans risque. Une erreur pendant le
            # traitement d'une bougie (qui peut passer un ordre) continue,
            # elle, de remonter : son etat serait ambigu.
            try:
                candle = fetch_closed_candle(last_seen_ts)
                current_price = candle.close if candle is not None else fetch_current_price()
            except Exception as e:
                if not is_transient_network_error(e):
                    raise
                if network_outage_since is None:
                    network_outage_since = time.time()
                    message = f"Coupure reseau, nouvel essai toutes les {poll_interval_seconds}s : {type(e).__name__}: {str(e)[:160]}"
                    logger.log_event("warning", message)
                    print(message, flush=True)
                time.sleep(poll_interval_seconds)
                continue
            if network_outage_since is not None:
                message = f"Reseau retabli apres {time.time() - network_outage_since:.0f}s de coupure."
                logger.log_event("info", message)
                print(message, flush=True)
                network_outage_since = None

            if candle is not None:
                engine.process_candle(candle)
                logger.save_open_positions(executor.portfolio.positions)
                logger.log_equity(candle.timestamp, executor.portfolio.equity(candle.close))
                price_history.append([candle.timestamp, candle.close, candle.open, candle.high, candle.low])
                last_seen_ts = candle.timestamp
                print(f"[{candle.timestamp}] close={candle.close} equity={executor.portfolio.equity(candle.close):.2f}")
                last_exit_check_ts = time.time()  # la bougie complete vient deja de verifier les sorties
            elif exit_check_interval_seconds is not None:
                now = time.time()
                if now - last_exit_check_ts >= exit_check_interval_seconds:
                    last_exit_check_ts = now
                    fine_exit_check(engine, executor, logger, current_price, now)

            # EF-88 : ordres poses a la main - verifies a chaque passage (toutes les
            # minutes) sur le cours du moment, executes par le MEME chemin qu'un
            # signal de la strategie (garde-fous compris).
            if not is_market_making:
                for trigger in manual_triggers.due(current_price):
                    if not manual_triggers.claim(trigger["id"]):
                        continue  # annule entre-temps par l'utilisateur : ne part pas
                    now_ms = int(time.time() * 1000)
                    tick = Candle(timestamp=now_ms, open=current_price, high=current_price,
                                  low=current_price, close=current_price, volume=0.0)
                    # EF-89 : un ordre de vente ferme TOUTES les positions du bot, comme
                    # un signal de vente de la strategie (meme chemin, memes garde-fous).
                    is_sell = trigger.get("side") == "sell"
                    try:
                        results = engine.process_manual_signal(
                            Signal(side=Side.SELL if is_sell else Side.BUY, reason="ordre_manuel"), tick,
                        )
                    except Exception as e:
                        manual_triggers.finish(trigger["id"], REJECTED, f"erreur : {type(e).__name__}: {e}")
                        logger.log_event("warning", f"Ordre manuel #{trigger['id']} en erreur : {e}")
                        raise  # une erreur pendant un ordre reste fatale : etat ambigu (voir EF-85)
                    detail = " ; ".join(results) or "aucun resultat"
                    ok = any(r.startswith("Vente executee" if is_sell else "Achat execute") for r in results)
                    manual_triggers.finish(trigger["id"], EXECUTED if ok else REJECTED,
                                           f"cours {current_price} (seuil {trigger['trigger_price']}) : {detail}")
                    sens = "au-dessus de" if trigger.get("direction") == "above" else "sous"
                    logger.log_event("info", f"Ordre manuel #{trigger['id']} ({'vente' if is_sell else 'achat'} {sens} {trigger['trigger_price']}) : {detail}")
                    print(f"[ordre manuel #{trigger['id']}] {detail}", flush=True)
                    logger.save_open_positions(executor.portfolio.positions)

            write_dashboard(
                instance_name=instance_name,
                symbol=config["symbol"],
                mode="paper",
                portfolio=executor.portfolio,
                current_price=current_price,
                updated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                logs=list(recent_logs),
                probability_up_24h=(probability_gate.current_probability() if probability_gate else None),
                orders=build_orders_table(executor.portfolio, display_risk_config),
                price_history=list(price_history),
                trend_filter_status=trend_status(trend_filter, current_price),
                atr_sizer_status=atr_sizer_status(atr_sizer),
                price_level_sizer_status=price_level_sizer_status(price_level_sizer),
                pool_available_cash=shared_pool.available_cash(),
                effective_cap=shared_pool.effective_cap(instance_name, capital_allocated),
                chart_levels=strategy_chart_levels(strategy),
            )
            time.sleep(poll_interval_seconds)
    except KeyboardInterrupt:
        print("Arret demande par l'utilisateur.")
        logger.log_event("info", "Arret manuel du mode paper")
    finally:
        report = compute_report(executor.portfolio)
        print(f"Rendement total : {report.total_return_pct * 100:.2f} %")
        logger.close()
        shared_pool.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m tradingbot.run_paper <config.yml>")
        sys.exit(1)
    main(sys.argv[1])
