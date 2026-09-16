from tradingbot.portfolio import Portfolio
from tradingbot.types import OrderResult, Side


def test_multiple_buys_create_separate_lots():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=1, status="filled"))
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=110.0, timestamp=2, status="filled"))

    assert len(portfolio.positions) == 2
    assert portfolio.positions[0].avg_entry_price == 100.0
    assert portfolio.positions[1].avg_entry_price == 110.0
    assert portfolio.positions[0].lot_id != portfolio.positions[1].lot_id


def test_sell_closes_specific_lot_by_id():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=1, status="filled"))
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=110.0, timestamp=2, status="filled"))
    second_lot_id = portfolio.positions[1].lot_id

    portfolio.apply_fill(
        OrderResult(Side.SELL, quantity=1.0, price=120.0, timestamp=3, status="filled"), lot_id=second_lot_id
    )

    assert len(portfolio.positions) == 1
    assert portfolio.positions[0].avg_entry_price == 100.0  # le premier lot reste ouvert
    assert portfolio.trade_history[0]["entry_price"] == 110.0  # c'est bien le 2e lot qui a ete vendu
    assert portfolio.trade_history[0]["pnl"] == 10.0


def test_sell_without_lot_id_closes_oldest_fifo():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=1, status="filled"))
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=110.0, timestamp=2, status="filled"))

    portfolio.apply_fill(OrderResult(Side.SELL, quantity=1.0, price=120.0, timestamp=3, status="filled"))

    assert len(portfolio.positions) == 1
    assert portfolio.positions[0].avg_entry_price == 110.0  # le plus ancien (100.0) a ete ferme
    assert portfolio.trade_history[0]["entry_price"] == 100.0


def test_equity_sums_all_open_positions():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=1, status="filled"))
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=2.0, price=50.0, timestamp=2, status="filled"))

    # cash = 1000 - 100 - 100 = 800 ; positions = 1.0 + 2.0 = 3.0 unites
    assert portfolio.equity(current_price=60.0) == 800.0 + 3.0 * 60.0


def test_position_property_returns_oldest_lot_for_backward_compat():
    portfolio = Portfolio(starting_capital=1000.0)
    assert portfolio.position.is_open is False

    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=1, status="filled"))
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=200.0, timestamp=2, status="filled"))

    assert portfolio.position.avg_entry_price == 100.0
