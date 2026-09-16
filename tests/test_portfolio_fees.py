from tradingbot.portfolio import Portfolio
from tradingbot.types import OrderResult, Side


def test_no_fee_by_default():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=1, status="filled"))
    assert portfolio.cash == 900.0
    assert portfolio.total_fees_paid == 0.0


def test_fee_deducted_on_buy():
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.001)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=1, status="filled"))
    # cout = 100, frais = 0.1 -> cash = 1000 - 100 - 0.1
    assert portfolio.cash == 899.9
    assert portfolio.total_fees_paid == 0.1


def test_fee_deducted_on_both_legs_reduces_trade_pnl():
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.01)  # 1% pour un calcul simple
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=1, status="filled"))
    portfolio.apply_fill(OrderResult(Side.SELL, quantity=1.0, price=110.0, timestamp=2, status="filled"))

    # sans frais : pnl = 10. Avec 1% sur chaque jambe : frais achat = 1, frais vente = 1.1
    trade = portfolio.trade_history[0]
    assert trade["fees_paid"] == 1.0 + 1.1
    assert trade["pnl"] == (110.0 - 1.1) - 100.0 - 1.0
    assert portfolio.total_fees_paid == 1.0 + 1.1


def test_on_trade_closed_callback_invoked():
    events = []
    portfolio = Portfolio(starting_capital=1000.0, on_trade_closed=lambda trade: events.append(trade))
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=1, status="filled"))
    assert events == []  # pas appele pour un achat

    portfolio.apply_fill(OrderResult(Side.SELL, quantity=1.0, price=110.0, timestamp=2, status="filled"))
    assert len(events) == 1
    assert events[0]["pnl"] == 10.0
