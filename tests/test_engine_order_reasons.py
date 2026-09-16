from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class AlwaysBuyStrategy(Strategy):
    def on_candle(self, candle):
        return Signal(side=Side.BUY, reason="dip_detecte")


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_stop_loss_sell_recorded_with_reason():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.5, stop_loss_pct=0.02))
    engine = Engine(AlwaysBuyStrategy(), risk_manager, executor, portfolio)

    executor.place_order(Side.BUY, 1.0, 100.0, timestamp=0)
    engine.process_candle(make_candle(1, 97.0))  # chute de 3%, au-dela du stop-loss

    assert portfolio.trade_history[0]["reason"] == "stop_loss"


def test_take_profit_sell_recorded_with_reason():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.5, stop_loss_pct=0.5, take_profit_pct=0.02))
    engine = Engine(AlwaysBuyStrategy(), risk_manager, executor, portfolio)

    executor.place_order(Side.BUY, 1.0, 100.0, timestamp=0)
    engine.process_candle(make_candle(1, 103.0))  # gain de 3%, au-dela du take-profit

    assert portfolio.trade_history[0]["reason"] == "take_profit"
