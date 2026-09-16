from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle


class NoSignalStrategy(Strategy):
    def on_candle(self, candle):
        return None


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def build_engine():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig())
    decisions = []
    engine = Engine(NoSignalStrategy(), risk_manager, executor, portfolio, on_decision=lambda c, m: decisions.append(m))
    return engine, decisions


def test_first_candle_has_no_delta_but_shows_price():
    engine, decisions = build_engine()
    engine.process_candle(make_candle(0, 100.0))
    assert "100.0000" in decisions[0]
    assert "%" not in decisions[0]


def test_second_candle_shows_positive_delta():
    engine, decisions = build_engine()
    engine.process_candle(make_candle(0, 100.0))
    engine.process_candle(make_candle(1, 105.0))
    assert "+5.0000" in decisions[1]
    assert "+5.00%" in decisions[1]


def test_price_drop_shows_negative_delta():
    engine, decisions = build_engine()
    engine.process_candle(make_candle(0, 100.0))
    engine.process_candle(make_candle(1, 95.0))
    assert "-5.0000" in decisions[1]
    assert "-5.00%" in decisions[1]
