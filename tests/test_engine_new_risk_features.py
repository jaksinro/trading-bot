from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class AlwaysBuyStrategy(Strategy):
    def on_candle(self, candle):
        return Signal(side=Side.BUY, reason="test")


class NoSignalStrategy(Strategy):
    def on_candle(self, candle):
        return None


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_trailing_stop_closes_position_after_pullback():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.5, stop_loss_pct=0.5, trailing_stop_pct=0.05))
    engine = Engine(NoSignalStrategy(), risk_manager, executor, portfolio)

    executor.place_order(Side.BUY, 1.0, 100.0, timestamp=0)
    engine.process_candle(make_candle(1, 150.0))  # le prix monte : peak_price suit
    engine.process_candle(make_candle(2, 140.0))  # chute de 6.7% depuis le pic (150) : trailing stop declenche

    assert len(portfolio.positions) == 0
    assert portfolio.trade_history[0]["reason"] == "trailing_stop"


def test_profit_lock_closes_position_once_armed_and_retraced():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(
        max_position_size_pct=0.5, stop_loss_pct=None,
        profit_lock_arm_pct=0.005, profit_lock_trigger_pct=0.0043,
    ))
    engine = Engine(NoSignalStrategy(), risk_manager, executor, portfolio)

    executor.place_order(Side.BUY, 1.0, 100.0, timestamp=0)
    engine.process_candle(make_candle(1, 100.6))  # pic +0.6% : arme le verrou
    engine.process_candle(make_candle(2, 100.40))  # retombe a +0.40% (<= 0.43%) : vend

    assert len(portfolio.positions) == 0
    assert portfolio.trade_history[0]["reason"] == "profit_lock"


def test_no_stop_loss_when_disabled_position_stays_open_despite_crash():
    """Etape 9 : stop_loss_pct=None est une decision assumee, pas un oubli -
    la position doit rester ouverte meme apres une chute severe, tant
    qu'aucune autre sortie (take-profit/trailing/verrou de gain) n'est
    configuree ou declenchee."""
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.5, stop_loss_pct=None))
    engine = Engine(NoSignalStrategy(), risk_manager, executor, portfolio)

    executor.place_order(Side.BUY, 1.0, 100.0, timestamp=0)
    engine.process_candle(make_candle(1, 50.0))   # -50%
    engine.process_candle(make_candle(2, 10.0))   # -90%

    assert len(portfolio.positions) == 1  # toujours ouverte, aucun stop-loss ne s'est declenche
    assert portfolio.trade_history == []


def test_second_buy_blocked_while_first_position_losing():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.1, max_concurrent_positions=3, stop_loss_pct=0.5))
    engine = Engine(AlwaysBuyStrategy(), risk_manager, executor, portfolio)

    engine.process_candle(make_candle(0, 100.0))  # 1er achat a 100
    engine.process_candle(make_candle(1, 90.0))  # prix baisse : la position est en perte, achat bloque

    assert len(portfolio.positions) == 1  # pas de 2e lot ouvert
