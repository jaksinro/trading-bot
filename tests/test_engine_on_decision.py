from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


class NoSignalStrategy(Strategy):
    def on_candle(self, candle):
        return None


class AlwaysBuyStrategy(Strategy):
    def on_candle(self, candle):
        return Signal(side=Side.BUY, reason="test")


class AlwaysSellStrategy(Strategy):
    def on_candle(self, candle):
        return Signal(side=Side.SELL, reason="test")


def build_engine(strategy, risk_config=None, starting_capital=1000.0):
    portfolio = Portfolio(starting_capital=starting_capital)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(risk_config or RiskConfig(max_position_size_pct=0.5))
    decisions = []
    engine = Engine(strategy, risk_manager, executor, portfolio, on_decision=lambda c, m: decisions.append(m))
    return engine, decisions


def test_no_signal_message():
    engine, decisions = build_engine(NoSignalStrategy())
    engine.process_candle(make_candle(0, 100.0))
    assert "Aucun signal de la strategie" in decisions[0]


def test_buy_executed_message():
    engine, decisions = build_engine(AlwaysBuyStrategy())
    engine.process_candle(make_candle(0, 100.0))
    assert "Achat execute" in decisions[0]
    assert "test" in decisions[0]


def test_buy_ignored_when_already_in_position():
    engine, decisions = build_engine(AlwaysBuyStrategy())
    engine.process_candle(make_candle(0, 100.0))  # 1er achat
    engine.process_candle(make_candle(1, 100.0))  # 2e signal, deja au max de positions simultanees
    assert "Achat ignore" in decisions[1]
    assert "limite" in decisions[1]


def test_sell_ignored_when_flat():
    engine, decisions = build_engine(AlwaysSellStrategy())
    engine.process_candle(make_candle(0, 100.0))
    assert "Vente ignore" in decisions[0]
    assert "aucune position" in decisions[0]


def test_stop_loss_message():
    engine, decisions = build_engine(NoSignalStrategy(), RiskConfig(max_position_size_pct=0.5, stop_loss_pct=0.02))
    engine.executor.place_order(Side.BUY, 1.0, 100.0, timestamp=0)
    engine.process_candle(make_candle(1, 97.0))  # chute de 3%, au-dela du seuil de 2%
    assert "stop-loss" in decisions[0]
