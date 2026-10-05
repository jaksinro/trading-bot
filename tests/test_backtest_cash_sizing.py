"""EF-99 : le backtest dimensionne sur le cash reel et ne passe jamais a credit."""
from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class AlwaysBuy(Strategy):
    def on_candle(self, candle: Candle):
        return Signal(side=Side.BUY)


def _candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_executor_rejects_buy_above_cash():
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.001)
    executor = BacktestExecutor(portfolio)
    order = executor.place_order(Side.BUY, quantity=11.0, price=100.0, timestamp=1)
    assert order.status == "rejected"
    assert portfolio.cash == 1000.0
    assert executor.get_positions() == []


def test_executor_rejects_buy_when_fees_exceed_cash():
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.001)
    executor = BacktestExecutor(portfolio)
    # 1000 de cout exact, mais les frais portent le total a 1001 > cash
    assert executor.place_order(Side.BUY, 10.0, 100.0, 1).status == "rejected"
    assert executor.place_order(Side.BUY, 9.99, 100.0, 1).status == "filled"


def test_sell_is_never_blocked_by_cash_check():
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.001)
    executor = BacktestExecutor(portfolio)
    executor.place_order(Side.BUY, 9.0, 100.0, 1)
    assert executor.place_order(Side.SELL, 9.0, 50.0, 2).status == "filled"


def test_cash_never_negative_after_series_of_losses():
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.001)
    engine = Engine(
        AlwaysBuy(), RiskManager(RiskConfig(max_position_size_pct=0.99, max_concurrent_positions=50, stop_loss_pct=None, block_buy_if_any_position_losing=False, max_daily_loss_pct=1.0)),
        BacktestExecutor(portfolio), portfolio,
    )
    price = 100.0
    candles = []
    for i in range(60):
        price *= 0.9  # chute continue : chaque lot est en perte latente
        candles.append(_candle(i, price))
    engine.run_backtest(candles)
    assert portfolio.cash >= -1e-6
    assert portfolio.equity(price) > 0


def test_first_buy_sized_like_before_when_cash_equals_capital():
    portfolio = Portfolio(starting_capital=1000.0)
    engine = Engine(AlwaysBuy(), RiskManager(RiskConfig(max_position_size_pct=0.1)), BacktestExecutor(portfolio), portfolio)
    engine.run_backtest([_candle(0, 100.0)])
    assert portfolio.position.quantity == 1.0  # 10 % de 1000 a 100


def test_buy_size_follows_cash_after_a_loss():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.cash = 400.0
    engine = Engine(AlwaysBuy(), RiskManager(RiskConfig(max_position_size_pct=0.5)), BacktestExecutor(portfolio), portfolio)
    engine.run_backtest([_candle(0, 100.0)])
    assert portfolio.position.quantity == 2.0  # 50 % de 400, pas de 1000
