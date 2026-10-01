"""Point d'entree CLI pour lancer un backtest a partir d'une config YAML.

Usage:
    python -m tradingbot.run_backtest config/example_instance.yml
"""

import sys

import yaml

from tradingbot.analysis.atr_sizer import AtrSizer
from tradingbot.analysis.trend_filter import TrendFilter
from tradingbot.data_feed import fetch_historical_candles, filter_candles, parse_iso_to_ms
from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.mm_engine import MarketMakingEngine
from tradingbot.portfolio import Portfolio
from tradingbot.reporting.stats import compute_report
from tradingbot.risk.risk_manager import MarketMakingConfig, RiskConfig, RiskManager
from tradingbot.strategies.buy_and_hold import BuyAndHoldStrategy
from tradingbot.strategies.dip_bounce import DipBounceStrategy
from tradingbot.strategies.market_making import MarketMakingStrategy
from tradingbot.strategies.mean_dip import MeanDipStrategy
from tradingbot.strategies.mean_reversion import MeanReversionStrategy
from tradingbot.strategies.rsi_range import RsiRangeStrategy
from tradingbot.strategies.scalp_dip import ScalpDipStrategy
from tradingbot.strategies.slope_dip import SlopeDipStrategy
from tradingbot.strategies.trend_regime import TrendRegimeStrategy
from tradingbot.strategies.volume_profile import VolumeProfileStrategy
from tradingbot.strategies.sma_cross import SmaCrossStrategy

STRATEGY_REGISTRY = {
    "sma_cross": SmaCrossStrategy,
    "scalp_dip": ScalpDipStrategy,
    "mean_reversion": MeanReversionStrategy,
    "rsi_range": RsiRangeStrategy,
    "market_making": MarketMakingStrategy,
    "dip_bounce": DipBounceStrategy,
    "mean_dip": MeanDipStrategy,
    "slope_dip": SlopeDipStrategy,
    "buy_and_hold": BuyAndHoldStrategy,
    "trend_regime": TrendRegimeStrategy,
    "volume_profile": VolumeProfileStrategy,
}


def build_strategy(config: dict):
    strategy_config = dict(config["strategy"])
    strategy_type = strategy_config.pop("type")
    strategy_cls = STRATEGY_REGISTRY[strategy_type]
    return strategy_cls(**strategy_config)


def build_trend_filter(config: dict) -> TrendFilter | None:
    trend_filter_config = config.get("trend_filter") or {}
    if not trend_filter_config.get("enabled"):
        return None
    return TrendFilter(ema_period=trend_filter_config.get("ema_period", 200))


def build_atr_sizer(config: dict) -> AtrSizer | None:
    atr_sizing_config = config.get("atr_sizing") or {}
    if not atr_sizing_config.get("enabled"):
        return None
    return AtrSizer(
        atr_period=atr_sizing_config.get("atr_period", 14),
        baseline_period=atr_sizing_config.get("baseline_period", 100),
        min_size_multiplier=atr_sizing_config.get("min_size_multiplier", 0.2),
    )


def main(config_path: str) -> None:
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    since_iso = config["backtest"]["since"]
    candles = fetch_historical_candles(
        exchange_id=config["exchange"],
        symbol=config["symbol"],
        timeframe=config["timeframe"],
        since_iso=since_iso,
    )
    # `fetch_historical_candles` renvoie tout le cache local des qu'il couvre
    # la date demandee (voir sa docstring) - potentiellement PLUS que
    # `since_iso` si le cache a ete construit avec une periode plus large
    # auparavant (ex: un sweep de parametres ayant deja tout charge depuis
    # une date plus ancienne). Filtrer ici est indispensable, pas juste une
    # precaution : sans ca, un backtest cense commencer a une date precise
    # (ex: le debut d'une periode de test out-of-sample) se retrouve
    # silencieusement a rejouer un historique plus long, faussant le resultat.
    candles = filter_candles(candles, parse_iso_to_ms(since_iso), None)
    print(f"{len(candles)} bougies chargees pour {config['symbol']} ({config['timeframe']})")

    strategy = build_strategy(config)
    is_market_making = config["strategy"]["type"] == "market_making"

    if is_market_making:
        mm_config = MarketMakingConfig(**config["risk"])
        portfolio = Portfolio(starting_capital=config["backtest"]["starting_capital"], fee_pct=mm_config.fee_pct)
        executor = BacktestExecutor(portfolio)
        engine = MarketMakingEngine(strategy, executor, portfolio)
    else:
        risk_manager = RiskManager(RiskConfig(**config["risk"]))
        portfolio = Portfolio(starting_capital=config["backtest"]["starting_capital"], fee_pct=risk_manager.config.fee_pct)
        executor = BacktestExecutor(portfolio)
        trend_filter = build_trend_filter(config)
        atr_sizer = build_atr_sizer(config)
        engine = Engine(strategy, risk_manager, executor, portfolio, trend_filter=trend_filter, atr_sizer=atr_sizer)

    engine.run_backtest(candles)

    report = compute_report(portfolio)
    print(f"Capital de depart   : {report.starting_capital:.2f}")
    print(f"Capital final        : {report.ending_equity:.2f}")
    print(f"Rendement total      : {report.total_return_pct * 100:.2f} %")
    print(f"Drawdown max          : {report.max_drawdown_pct * 100:.2f} %")
    print(f"P&L realise           : {report.realized_pnl:.2f}")
    print(f"Frais payes           : {portfolio.total_fees_paid:.2f}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m tradingbot.run_backtest <config.yml>")
        sys.exit(1)
    main(sys.argv[1])
