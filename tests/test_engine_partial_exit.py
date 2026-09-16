from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class NoSignalStrategy(Strategy):
    def on_candle(self, candle):
        return None


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_partial_take_profit_sells_only_configured_fraction():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(
        max_position_size_pct=0.5, stop_loss_pct=0.5, partial_take_profit_pct=0.05, partial_exit_fraction=0.5,
    ))
    engine = Engine(NoSignalStrategy(), risk_manager, executor, portfolio)

    executor.place_order(Side.BUY, 10.0, 100.0, timestamp=0)
    engine.process_candle(make_candle(1, 106.0))  # +6% : palier partiel atteint

    assert len(portfolio.positions) == 1
    assert portfolio.positions[0].quantity == 5.0  # moitie vendue
    assert portfolio.positions[0].partial_exit_done is True
    assert len(portfolio.trade_history) == 1
    assert portfolio.trade_history[0]["reason"] == "partial_take_profit"


def test_partial_take_profit_triggers_only_once():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(
        max_position_size_pct=0.5, stop_loss_pct=0.5, partial_take_profit_pct=0.05, partial_exit_fraction=0.5,
    ))
    engine = Engine(NoSignalStrategy(), risk_manager, executor, portfolio)

    executor.place_order(Side.BUY, 10.0, 100.0, timestamp=0)
    engine.process_candle(make_candle(1, 106.0))  # declenche la sortie partielle
    engine.process_candle(make_candle(2, 120.0))  # prix monte encore : ne redeclenche pas de 2e sortie partielle

    assert len(portfolio.trade_history) == 1  # toujours une seule sortie partielle


def test_remaining_position_still_respects_stop_loss_after_partial_exit():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(
        max_position_size_pct=0.5, stop_loss_pct=0.05, partial_take_profit_pct=0.05, partial_exit_fraction=0.5,
    ))
    engine = Engine(NoSignalStrategy(), risk_manager, executor, portfolio)

    executor.place_order(Side.BUY, 10.0, 100.0, timestamp=0)
    engine.process_candle(make_candle(1, 106.0))  # sortie partielle : reste 5.0
    engine.process_candle(make_candle(2, 94.0))  # chute de plus de 5% depuis l'entree : stop-loss sur le reste

    assert len(portfolio.positions) == 0
    assert len(portfolio.trade_history) == 2
    assert portfolio.trade_history[1]["reason"] == "stop_loss"
    assert portfolio.trade_history[1]["quantity"] == 5.0


def test_no_partial_exit_when_not_configured():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.5, stop_loss_pct=0.5))
    engine = Engine(NoSignalStrategy(), risk_manager, executor, portfolio)

    executor.place_order(Side.BUY, 10.0, 100.0, timestamp=0)
    engine.process_candle(make_candle(1, 200.0))  # forte hausse, pas de palier configure

    assert len(portfolio.positions) == 1
    assert portfolio.positions[0].quantity == 10.0
    assert portfolio.trade_history == []
