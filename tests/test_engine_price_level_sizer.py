from tradingbot.analysis.price_level_sizer import PriceLevelSizer
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


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i * 3_600_000, open=close, high=close, low=close, close=close, volume=1.0)


def test_buy_size_increased_when_price_below_month_average():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.5))
    price_level_sizer = PriceLevelSizer(min_size_multiplier=0.5, max_size_multiplier=1.5)
    strategy = BuyOnLastCandleStrategy(trigger_call_index=5)
    engine = Engine(strategy, risk_manager, executor, portfolio, price_level_sizer=price_level_sizer)

    for i in range(5):
        engine.process_candle(make_candle(i, close=100.0))
    engine.process_candle(make_candle(5, close=90.0))  # achat ici, sous la moyenne du mois

    assert len(portfolio.positions) == 1
    normal_quantity = risk_manager.size_for_signal(portfolio.starting_capital, 90.0)
    assert portfolio.positions[0].quantity > normal_quantity


def test_buy_size_unchanged_when_no_price_level_sizer():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.5))
    strategy = BuyOnLastCandleStrategy(trigger_call_index=0)
    engine = Engine(strategy, risk_manager, executor, portfolio, price_level_sizer=None)

    engine.process_candle(make_candle(0, close=90.0))

    expected_quantity = risk_manager.size_for_signal(1000.0, 90.0)
    assert portfolio.positions[0].quantity == expected_quantity


def test_price_level_sizer_updates_every_candle_even_without_signal():
    price_level_sizer = PriceLevelSizer()
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.1))

    class NoSignalStrategy(Strategy):
        def on_candle(self, candle):
            return None

    engine = Engine(NoSignalStrategy(), risk_manager, executor, portfolio, price_level_sizer=price_level_sizer)
    engine.process_candle(make_candle(0, close=102.0))

    assert price_level_sizer.month_average == 102.0
