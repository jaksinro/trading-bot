from tradingbot.analysis.trend_filter import TrendFilter
from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class AlwaysBuyStrategy(Strategy):
    def on_candle(self, candle):
        return Signal(side=Side.BUY, reason="test")


class BuyOnLastCandleStrategy(Strategy):
    """N'emet un signal d'achat que sur le dernier appel attendu, pour
    pouvoir faire monter l'EMA (via des bougies neutres) avant de tester le
    filtre sur une bougie de decision precise."""

    def __init__(self, trigger_call_index: int):
        self.trigger_call_index = trigger_call_index
        self._calls = 0

    def on_candle(self, candle):
        signal = Signal(side=Side.BUY, reason="test") if self._calls == self.trigger_call_index else None
        self._calls += 1
        return signal


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_buy_blocked_when_price_below_ema():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.1))
    trend_filter = TrendFilter(ema_period=5)
    strategy = BuyOnLastCandleStrategy(trigger_call_index=5)
    engine = Engine(strategy, risk_manager, executor, portfolio, trend_filter=trend_filter)

    for i, price in enumerate([100.0, 100.0, 100.0, 100.0, 100.0]):
        engine.process_candle(make_candle(i, price))
    engine.process_candle(make_candle(5, 80.0))  # prix sous l'EMA (~100) : achat bloque

    assert len(portfolio.positions) == 0


def test_buy_allowed_when_price_above_ema():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.1))
    trend_filter = TrendFilter(ema_period=5)
    strategy = BuyOnLastCandleStrategy(trigger_call_index=5)
    engine = Engine(strategy, risk_manager, executor, portfolio, trend_filter=trend_filter)

    for i, price in enumerate([100.0, 100.0, 100.0, 100.0, 100.0]):
        engine.process_candle(make_candle(i, price))
    engine.process_candle(make_candle(5, 120.0))  # prix au-dessus de l'EMA (~100) : achat autorise

    assert len(portfolio.positions) == 1


def test_trend_filter_updates_every_candle_even_without_signal():
    trend_filter = TrendFilter(ema_period=5)
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.1))

    class NoSignalStrategy(Strategy):
        def on_candle(self, candle):
            return None

    engine = Engine(NoSignalStrategy(), risk_manager, executor, portfolio, trend_filter=trend_filter)
    engine.process_candle(make_candle(0, 100.0))
    assert trend_filter.ema == 100.0


def test_disabled_trend_filter_does_not_affect_buys():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.1))
    engine = Engine(AlwaysBuyStrategy(), risk_manager, executor, portfolio, trend_filter=None)

    engine.process_candle(make_candle(0, 100.0))

    assert len(portfolio.positions) == 1
