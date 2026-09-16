from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class AlwaysBuyStrategy(Strategy):
    def on_candle(self, candle):
        return Signal(side=Side.BUY, reason="test")


class FakeGate:
    def __init__(self, allowed: bool, probability: float = 0.5, min_probability: float = 0.55):
        self.allowed = allowed
        self.probability = probability
        self.min_probability = min_probability
        self.calls = 0

    def allows_buy(self):
        self.calls += 1
        return self.allowed, self.probability


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def build_engine(gate):
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.5))
    decisions = []
    engine = Engine(
        AlwaysBuyStrategy(), risk_manager, executor, portfolio,
        on_decision=lambda c, m: decisions.append(m), probability_gate=gate,
    )
    return engine, decisions, executor


def test_blocks_buy_when_gate_disallows():
    gate = FakeGate(allowed=False, probability=0.3, min_probability=0.55)
    engine, decisions, executor = build_engine(gate)

    engine.process_candle(make_candle(0, 100.0))

    assert "bloque par le filtre de probabilite" in decisions[0]
    assert "30%" in decisions[0]
    assert executor.get_position().quantity == 0.0
    assert gate.calls == 1


def test_allows_buy_when_gate_allows():
    gate = FakeGate(allowed=True, probability=0.7)
    engine, decisions, executor = build_engine(gate)

    engine.process_candle(make_candle(0, 100.0))

    assert "Achat execute" in decisions[0]
    assert executor.get_position().quantity > 0.0


def test_no_gate_behaves_as_before():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.5))
    decisions = []
    engine = Engine(
        AlwaysBuyStrategy(), risk_manager, executor, portfolio,
        on_decision=lambda c, m: decisions.append(m),
    )

    engine.process_candle(make_candle(0, 100.0))

    assert "Achat execute" in decisions[0]


def test_gate_not_consulted_for_sell_signals():
    class AlwaysSellStrategy(Strategy):
        def on_candle(self, candle):
            return Signal(side=Side.SELL, reason="test")

    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    executor.place_order(Side.BUY, 1.0, 100.0, timestamp=0)  # position ouverte au prealable
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.5))
    gate = FakeGate(allowed=False)
    engine = Engine(AlwaysSellStrategy(), risk_manager, executor, portfolio, probability_gate=gate)

    engine.process_candle(make_candle(1, 100.0))

    assert gate.calls == 0
