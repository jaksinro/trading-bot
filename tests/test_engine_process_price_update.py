from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class BuyOnFirstCallStrategy(Strategy):
    def __init__(self):
        self.calls = 0

    def on_candle(self, candle):
        self.calls += 1
        if self.calls == 1:
            return Signal(side=Side.BUY, reason="test")
        return None


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i * 60_000, open=close, high=close, low=close, close=close, volume=1.0)


def test_process_price_update_never_calls_the_strategy():
    strategy = BuyOnFirstCallStrategy()
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(stop_loss_pct=0.02))
    engine = Engine(strategy, risk_manager, executor, portfolio)

    engine.process_candle(make_candle(0, 100.0))  # achete via la strategie (1er appel)
    assert strategy.calls == 1

    engine.process_price_update(make_candle(1, 90.0))  # -10%, sous le prix d'achat -> stop-loss
    assert strategy.calls == 1  # la strategie n'a jamais ete rappelee
    assert len(portfolio.positions) == 0  # stop-loss declenche par le tick fin, pas la bougie strategie


def test_process_price_update_triggers_profit_lock_between_strategy_candles():
    strategy = BuyOnFirstCallStrategy()
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(
        stop_loss_pct=None, profit_lock_arm_pct=0.01, profit_lock_trigger_pct=0.007,
    ))
    engine = Engine(strategy, risk_manager, executor, portfolio)

    engine.process_candle(make_candle(0, 100.0))  # achat
    engine.process_price_update(make_candle(1, 102.0))  # +2%, arme le verrou
    assert len(portfolio.positions) == 1  # pas encore vendu, gain toujours au-dessus du declenchement

    engine.process_price_update(make_candle(2, 100.5))  # +0.5%, sous le seuil de 0.7% -> vend
    assert len(portfolio.positions) == 0
    assert portfolio.trade_history[-1]["reason"] == "profit_lock"


def test_process_price_update_records_equity_without_a_new_position():
    strategy = BuyOnFirstCallStrategy()
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig())
    engine = Engine(strategy, risk_manager, executor, portfolio)

    engine.process_price_update(make_candle(0, 100.0))
    assert len(portfolio.equity_curve) == 1
    assert len(portfolio.positions) == 0  # aucun signal genere, strategie jamais consultee


def test_check_lot_exits_matches_process_candle_behavior():
    """check_lot_exits (extrait de _decide) doit se comporter a l'identique
    de l'ancien code inline - non-regression du refactoring."""
    strategy = BuyOnFirstCallStrategy()
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(stop_loss_pct=0.02))
    engine = Engine(strategy, risk_manager, executor, portfolio)

    engine.process_candle(make_candle(0, 100.0))
    messages = engine.check_lot_exits(make_candle(1, 90.0))
    assert any("stop-loss" in m for m in messages)
    assert len(portfolio.positions) == 0
