from tradingbot.portfolio import Portfolio
from tradingbot.reporting.logger import TradeLogger
from tradingbot.run_paper import compute_restored_cash, restore_persisted_state
from tradingbot.types import Position


def test_first_ever_run_when_nothing_persisted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("fresh_bot")
    portfolio = Portfolio(starting_capital=1000.0)

    is_first_ever_run = restore_persisted_state(portfolio, logger)

    assert is_first_ever_run is True
    assert portfolio.positions == []
    logger.close()


def test_resumes_open_positions_from_previous_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("resumed_bot")
    logger.save_open_positions(
        [Position(quantity=2.0, avg_entry_price=100.0, entry_timestamp=10, lot_id=3, entry_fee=0.2, peak_price=105.0)]
    )
    portfolio = Portfolio(starting_capital=1000.0)

    is_first_ever_run = restore_persisted_state(portfolio, logger)

    assert is_first_ever_run is False
    assert len(portfolio.positions) == 1
    assert portfolio.positions[0].lot_id == 3
    assert portfolio.positions[0].peak_price == 105.0
    logger.close()


def test_resumes_when_only_closed_trades_exist_no_open_position(tmp_path, monkeypatch):
    """Un bot qui a deja clos au moins un trade a deja vecu une session,
    meme s'il n'a plus de position ouverte au moment de la coupure : il ne
    doit pas etre traite comme un tout premier lancement (pas de flatten
    inutile, pas de reset de cash a capital_allocated brut)."""
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("closed_only_bot")
    logger.log_closed_trade(
        {"entry_timestamp": 1, "entry_price": 100.0, "timestamp": 2, "exit_price": 110.0,
         "quantity": 1.0, "pnl": 9.5, "reason": "take_profit", "lot_id": 1, "fees_paid": 0.5}
    )
    portfolio = Portfolio(starting_capital=1000.0)

    is_first_ever_run = restore_persisted_state(portfolio, logger)

    assert is_first_ever_run is False
    assert portfolio.positions == []
    assert portfolio.realized_pnl == 9.5
    logger.close()


def test_next_lot_id_accounts_for_both_closed_and_open_lots(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("lot_id_bot")
    logger.log_closed_trade(
        {"entry_timestamp": 1, "entry_price": 100.0, "timestamp": 2, "exit_price": 110.0,
         "quantity": 1.0, "pnl": 9.5, "reason": "signal", "lot_id": 5, "fees_paid": 0.5}
    )
    logger.save_open_positions([Position(quantity=1.0, avg_entry_price=50.0, lot_id=3)])
    portfolio = Portfolio(starting_capital=1000.0)

    restore_persisted_state(portfolio, logger)

    assert portfolio._next_lot_id == 6
    logger.close()


def test_compute_restored_cash_deducts_tied_up_capital_and_adds_pnl():
    positions = [Position(quantity=2.0, avg_entry_price=100.0, entry_fee=0.4)]
    cash = compute_restored_cash(capital_allocated=1000.0, realized_pnl=25.0, positions=positions)
    # 1000 (depart) + 25 (pnl deja realise) - (2*100 + 0.4) immobilise
    assert cash == 1000.0 + 25.0 - 200.4


def test_compute_restored_cash_with_no_open_positions():
    cash = compute_restored_cash(capital_allocated=500.0, realized_pnl=-10.0, positions=[])
    assert cash == 490.0
