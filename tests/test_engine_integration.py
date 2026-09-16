from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.sma_cross import SmaCrossStrategy
from tradingbot.types import Candle


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_full_backtest_loop_produces_consistent_equity_curve():
    strategy = SmaCrossStrategy(short_window=2, long_window=4)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.5))
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    engine = Engine(strategy, risk_manager, executor, portfolio)

    closes = [100, 100, 100, 100, 105, 110, 115, 108, 102, 95, 90, 95, 100]
    candles = [make_candle(i, c) for i, c in enumerate(closes)]

    engine.run_backtest(candles)

    assert len(portfolio.equity_curve) == len(candles)
    final_equity = portfolio.equity(closes[-1])
    assert final_equity == portfolio.cash + portfolio.position.quantity * closes[-1]
    assert final_equity > 0
