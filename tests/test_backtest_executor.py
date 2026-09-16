from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.types import Side


def test_buy_then_sell_updates_cash_and_position():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)

    executor.place_order(Side.BUY, quantity=1.0, price=100.0, timestamp=1)
    assert portfolio.cash == 900.0
    assert executor.get_position().quantity == 1.0
    assert executor.get_position().avg_entry_price == 100.0

    executor.place_order(Side.SELL, quantity=1.0, price=110.0, timestamp=2)
    assert portfolio.cash == 1010.0
    assert executor.get_position().quantity == 0.0
    assert portfolio.realized_pnl == 10.0


def test_rejects_zero_or_negative_quantity():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)

    result = executor.place_order(Side.BUY, quantity=0.0, price=100.0, timestamp=1)
    assert result.status == "rejected"
    assert portfolio.cash == 1000.0
