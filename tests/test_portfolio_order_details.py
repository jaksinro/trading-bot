from tradingbot.portfolio import Portfolio
from tradingbot.types import OrderResult, Side


def test_trade_history_records_entry_and_exit_details():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=10, status="filled"))
    portfolio.apply_fill(
        OrderResult(Side.SELL, quantity=1.0, price=110.0, timestamp=20, status="filled", reason="take_profit")
    )

    trade = portfolio.trade_history[0]
    assert trade["entry_price"] == 100.0
    assert trade["entry_timestamp"] == 10
    assert trade["exit_price"] == 110.0
    assert trade["quantity"] == 1.0
    assert trade["reason"] == "take_profit"
    assert trade["pnl"] == 10.0


def test_position_tracks_entry_timestamp_on_buy():
    portfolio = Portfolio(starting_capital=1000.0)
    assert portfolio.position.entry_timestamp == 0
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=42, status="filled"))
    assert portfolio.position.entry_timestamp == 42
