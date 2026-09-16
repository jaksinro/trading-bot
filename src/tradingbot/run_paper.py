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
from collections import deque
from pathlib import Path

import yaml
from dotenv import load_dotenv

from tradingbot.analysis.atr_sizer import AtrSizer
from tradingbot.analysis.price_level_sizer import PriceLevelSizer
from tradingbot.analysis.probability_gate import ProbabilityGate
from tradingbot.analysis.trend_filter import TrendFilter
from tradingbot.engine import Engine
from tradingbot.execution.paper_executor import PaperExecutor
from tradingbot.mm_engine import MarketMakingEngine
from tradingbot.process_lock import acquire_lock
from tradingbot.reporting.dashboard import MASTER_DASHBOARD_PATH, write_dashboard
from tradingbot.reporting.logger import TradeLogger
from tradingbot.reporting.stats import build_orders_table, compute_report
from tradingbot.risk.risk_manager import MarketMakingConfig, RiskConfig, RiskManager
from tradingbot.run_backtest import build_strategy
from tradingbot.shared_pool import SharedPool
from tradingbot.types import Candle

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


def _row_to_candle(row) -> Candle:
    return Candle(
        timestamp=int(row[0]),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
    )


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
    history = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=warmup_needed + 1)
    closed_history = history[:-1]  # on exclut la bougie en cours de formation
    for row in closed_history:
        candle = _row_to_candle(row)
        if hasattr(strategy, "on_candle"):
            strategy.on_candle(candle)  # signal ignore : pure mise en etat
        # MarketMakingStrategy n'a pas d'etat a "rechauffer" (pas de fenetre
        # glissante, sa cotation depend seulement de la bougie courante et de
        # l'inventaire) - seul price_history/trend_filter/atr_sizer restent
        # utiles pour l'affichage dashboard, deja geres ci-dessous.
        if price_history is not None:
            price_history.append([candle.timestamp, candle.close])
        if trend_filter is not None:
            trend_filter.update(candle.close)
        if atr_sizer is not None:
            atr_sizer.update(candle)
        if price_level_sizer is not None:
            price_level_sizer.update(candle)
    return int(closed_history[-1][0]) if closed_history else None


def main(config_path: str) -> None:
    load_dotenv()

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    instance_name = config["name"]
    lock_path = Path(f"bot_{instance_name}.lock")
    acquire_lock(lock_path)
    dashboard_already_existed = MASTER_DASHBOARD_PATH.exists()

    api_key = os.environ.get("BINANCE_TESTNET_API_KEY", "")
    api_secret = os.environ.get("BINANCE_TESTNET_API_SECRET", "")

    strategy = build_strategy(config)
    is_market_making = config["strategy"]["type"] == "market_making"
    risk_manager = None if is_market_making else RiskManager(RiskConfig(**config["risk"]))
    mm_config = MarketMakingConfig(**config["risk"]) if is_market_making else None
    executor = PaperExecutor(config["exchange"], config["symbol"], api_key, api_secret)
    logger = TradeLogger(config["name"])
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

    shared_pool = SharedPool()
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
    elif not is_first_ever_run:
        logger.log_event(
            "info",
            f"Reprise apres coupure : {len(executor.portfolio.positions)} position(s) ouverte(s) restauree(s)",
        )
        print(f"Reprise de session : {len(executor.portfolio.positions)} position(s) ouverte(s) restauree(s).")

    baseline_price = executor.exchange.fetch_ticker(config["symbol"])["last"]

    # Etat de depart persiste immediatement : si le PC s'eteint avant meme la
    # premiere bougie traitee, une reprise ulterieure retrouve quand meme cet
    # etat (plutot qu'un open_positions vide venant d'un run precedent).
    logger.save_open_positions(executor.portfolio.positions)

    exchange = executor.exchange
    warmup_candles = config.get("warmup_candles", DEFAULT_WARMUP_CANDLES)
    last_seen_ts = warm_up_strategy(
        exchange, config["symbol"], config["timeframe"], strategy, warmup_candles,
        price_history, trend_filter, atr_sizer, price_level_sizer,
    )
    print(f"Strategie rechauffee avec {warmup_candles} bougies d'historique.")

    timeframe_seconds = exchange.parse_timeframe(config["timeframe"])
    poll_interval_seconds = min(60, timeframe_seconds)

    # Surveillance des sorties a granularite fine (EF-53) - demande de
    # l'utilisateur ("ce reglage sur tous les bots") : verifie stop-loss/
    # verrou de gain/trailing plus souvent que le timeframe d'entree, sans
    # attendre la bougie suivante. Reutilise le prix deja recupere via le
    # ticker a chaque cycle de sondage (aucun appel reseau supplementaire).
    # Sans objet pour le market making (pas de `process_price_update`,
    # cotation continue par nature) - `exit_check_timeframe` y est ignore.
    exit_check_timeframe = config.get("exit_check_timeframe")
    exit_check_interval_seconds = (
        exchange.parse_timeframe(exit_check_timeframe)
        if exit_check_timeframe and not is_market_making
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
    )
    if not dashboard_already_existed:
        webbrowser.open(MASTER_DASHBOARD_PATH.resolve().as_uri())

    try:
        while True:
            candle = poll_new_closed_candle(exchange, config["symbol"], config["timeframe"], last_seen_ts)
            current_price = candle.close if candle is not None else exchange.fetch_ticker(config["symbol"])["last"]

            if candle is not None:
                engine.process_candle(candle)
                logger.save_open_positions(executor.portfolio.positions)
                logger.log_equity(candle.timestamp, executor.portfolio.equity(candle.close))
                price_history.append([candle.timestamp, candle.close])
                last_seen_ts = candle.timestamp
                print(f"[{candle.timestamp}] close={candle.close} equity={executor.portfolio.equity(candle.close):.2f}")
                last_exit_check_ts = time.time()  # la bougie complete vient deja de verifier les sorties
            elif exit_check_interval_seconds is not None:
                now = time.time()
                if now - last_exit_check_ts >= exit_check_interval_seconds:
                    last_exit_check_ts = now
                    fine_candle = Candle(
                        timestamp=int(now * 1000), open=current_price, high=current_price,
                        low=current_price, close=current_price, volume=0.0,
                    )
                    messages = engine.process_price_update(fine_candle)
                    if messages:
                        logger.save_open_positions(executor.portfolio.positions)
                        logger.log_equity(fine_candle.timestamp, executor.portfolio.equity(current_price))
                        for message in messages:
                            print(f"[{fine_candle.timestamp}] (surveillance fine) {message}")

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
