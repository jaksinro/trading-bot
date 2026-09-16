from tradingbot.analysis.atr_sizer import AtrSizer
from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class BuyOnLastCandleStrategy(Strategy):
    def __init__(self, trigger_call_index: int):
        self.trigger_call_index = trigger_call_index
        self._calls = 0

    def on_candle(self, candle):
        signal = Signal(side=Side.BUY, reason="test") if self._calls == self.trigger_call_index else None
        self._calls += 1
        return signal


def make_candle(i: int, high: float, low: float, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=high, low=low, close=close, volume=1.0)


def test_buy_size_reduced_during_volatility_spike():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.5))
    atr_sizer = AtrSizer(atr_period=5, baseline_period=20, min_size_multiplier=0.2)
    strategy = BuyOnLastCandleStrategy(trigger_call_index=25)
    engine = Engine(strategy, risk_manager, executor, portfolio, atr_sizer=atr_sizer)

    for i in range(20):
        engine.process_candle(make_candle(i, high=101.0, low=100.0, close=100.5))  # calme
    for i in range(20, 25):
        engine.process_candle(make_candle(i, high=200.0, low=100.0, close=150.0))  # pic de volatilite
    engine.process_candle(make_candle(25, high=200.0, low=100.0, close=150.0))  # achat ici

    assert len(portfolio.positions) == 1
    normal_quantity = risk_manager.size_for_signal(portfolio.starting_capital, 150.0)
    assert portfolio.positions[0].quantity < normal_quantity


def test_buy_size_unchanged_when_no_atr_sizer():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.5))
    strategy = BuyOnLastCandleStrategy(trigger_call_index=0)
    engine = Engine(strategy, risk_manager, executor, portfolio, atr_sizer=None)

    engine.process_candle(make_candle(0, high=200.0, low=100.0, close=150.0))

    expected_quantity = risk_manager.size_for_signal(1000.0, 150.0)
    assert portfolio.positions[0].quantity == expected_quantity


def test_atr_sizer_updates_every_candle_even_without_signal():
    atr_sizer = AtrSizer(atr_period=5, baseline_period=20)
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.1))

    class NoSignalStrategy(Strategy):
        def on_candle(self, candle):
            return None

    engine = Engine(NoSignalStrategy(), risk_manager, executor, portfolio, atr_sizer=atr_sizer)
    engine.process_candle(make_candle(0, high=105.0, low=100.0, close=102.0))

    assert atr_sizer.atr == 5.0
