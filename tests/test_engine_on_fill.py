from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class AlwaysBuyStrategy(Strategy):
    def __init__(self):
        self._bought = False

    def on_candle(self, candle):
        if not self._bought:
            self._bought = True
            return Signal(side=Side.BUY)
        return None


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_on_fill_hook_called_for_each_order():
    fills = []
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    engine = Engine(
        AlwaysBuyStrategy(),
        RiskManager(RiskConfig(max_position_size_pct=0.5)),
        executor,
        portfolio,
        on_fill=fills.append,
    )

    engine.process_candle(make_candle(0, 100.0))

    assert len(fills) == 1
    assert fills[0].side == Side.BUY
