from tradingbot.portfolio import Portfolio
from tradingbot.types import OrderResult, Side


def test_sell_records_trade_with_pnl():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=1, status="filled"))
    portfolio.apply_fill(OrderResult(Side.SELL, quantity=1.0, price=110.0, timestamp=2, status="filled"))

    assert len(portfolio.trade_history) == 1
    assert portfolio.trade_history[0]["pnl"] == 10.0


def test_buy_does_not_record_trade():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=1, status="filled"))
    assert portfolio.trade_history == []


def test_losing_trade_recorded_with_negative_pnl():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=1, status="filled"))
    portfolio.apply_fill(OrderResult(Side.SELL, quantity=1.0, price=90.0, timestamp=2, status="filled"))
    assert portfolio.trade_history[0]["pnl"] == -10.0
