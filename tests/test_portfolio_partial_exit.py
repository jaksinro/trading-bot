from tradingbot.portfolio import Portfolio
from tradingbot.types import OrderResult, Side


def test_partial_sell_reduces_quantity_but_keeps_lot_open():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=10.0, price=100.0, timestamp=1, status="filled"))
    lot_id = portfolio.positions[0].lot_id

    portfolio.apply_fill(OrderResult(Side.SELL, quantity=4.0, price=110.0, timestamp=2, status="filled", reason="partial_take_profit"), lot_id=lot_id)

    assert len(portfolio.positions) == 1  # le lot reste ouvert
    assert portfolio.positions[0].quantity == 6.0
    assert portfolio.positions[0].lot_id == lot_id
    assert portfolio.positions[0].partial_exit_done is True


def test_partial_sell_records_a_trade_history_entry():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=10.0, price=100.0, timestamp=1, status="filled"))
    lot_id = portfolio.positions[0].lot_id

    portfolio.apply_fill(OrderResult(Side.SELL, quantity=4.0, price=110.0, timestamp=2, status="filled", reason="partial_take_profit"), lot_id=lot_id)

    assert len(portfolio.trade_history) == 1
    trade = portfolio.trade_history[0]
    assert trade["quantity"] == 4.0
    assert trade["pnl"] == (4.0 * 110.0) - (4.0 * 100.0)  # pas de frais ici
    assert trade["partial"] is True
    assert trade["lot_id"] == lot_id


def test_partial_sell_splits_entry_fee_proportionally():
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.01)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=10.0, price=100.0, timestamp=1, status="filled"))
    lot_id = portfolio.positions[0].lot_id
    entry_fee = portfolio.positions[0].entry_fee  # 10*100*0.01 = 10.0

    portfolio.apply_fill(OrderResult(Side.SELL, quantity=4.0, price=110.0, timestamp=2, status="filled", reason="partial_take_profit"), lot_id=lot_id)

    # 40% de la quantite vendue -> 40% du frais d'entree impute a cette vente
    expected_entry_fee_share = entry_fee * 0.4
    trade = portfolio.trade_history[0]
    exit_fee = 4.0 * 110.0 * 0.01
    assert trade["fees_paid"] == exit_fee + expected_entry_fee_share
    # le lot restant garde le solde du frais d'entree (60%)
    assert portfolio.positions[0].entry_fee == entry_fee - expected_entry_fee_share


def test_partial_sell_updates_cash_correctly():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=10.0, price=100.0, timestamp=1, status="filled"))
    cash_after_buy = portfolio.cash  # 1000 - 1000 = 0

    portfolio.apply_fill(OrderResult(Side.SELL, quantity=4.0, price=110.0, timestamp=2, status="filled"), lot_id=portfolio.positions[0].lot_id)

    assert portfolio.cash == cash_after_buy + 4.0 * 110.0


def test_full_sell_of_remaining_quantity_after_partial_still_closes_lot():
    """Une fois la sortie partielle faite, vendre le RESTE (quantite exacte
    restante) doit bien fermer completement le lot (pas rester bloque en
    'partiel' indefiniment)."""
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=10.0, price=100.0, timestamp=1, status="filled"))
    lot_id = portfolio.positions[0].lot_id
    portfolio.apply_fill(OrderResult(Side.SELL, quantity=4.0, price=110.0, timestamp=2, status="filled"), lot_id=lot_id)

    portfolio.apply_fill(OrderResult(Side.SELL, quantity=6.0, price=120.0, timestamp=3, status="filled"), lot_id=lot_id)

    assert len(portfolio.positions) == 0
    assert len(portfolio.trade_history) == 2


def test_selling_exact_full_quantity_in_one_order_is_not_treated_as_partial():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=10.0, price=100.0, timestamp=1, status="filled"))
    lot_id = portfolio.positions[0].lot_id

    portfolio.apply_fill(OrderResult(Side.SELL, quantity=10.0, price=110.0, timestamp=2, status="filled"), lot_id=lot_id)

    assert len(portfolio.positions) == 0
    assert "partial" not in portfolio.trade_history[0]
