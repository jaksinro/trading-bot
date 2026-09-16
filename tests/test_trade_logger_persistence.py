from tradingbot.reporting.logger import TradeLogger
from tradingbot.types import Position


def test_log_and_reload_closed_trade(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("persist_test")
    trade = {
        "entry_timestamp": 1, "entry_price": 100.0, "timestamp": 2, "exit_price": 110.0,
        "quantity": 1.0, "pnl": 10.0, "reason": "take_profit", "lot_id": 5, "fees_paid": 0.2,
    }
    logger.log_closed_trade(trade)
    logger.close()

    reloaded_logger = TradeLogger("persist_test")
    trades = reloaded_logger.load_closed_trades()
    reloaded_logger.close()

    assert len(trades) == 1
    assert trades[0]["entry_price"] == 100.0
    assert trades[0]["pnl"] == 10.0
    assert trades[0]["reason"] == "take_profit"
    assert trades[0]["lot_id"] == 5


def test_load_closed_trades_empty_when_none_logged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("empty_test")
    assert logger.load_closed_trades() == []
    logger.close()


def test_log_and_reload_equity_curve(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("equity_test")
    logger.log_equity(1, 1000.0)
    logger.log_equity(2, 1010.0)
    logger.log_equity(3, 990.0)
    logger.close()

    reloaded_logger = TradeLogger("equity_test")
    curve = reloaded_logger.load_equity_curve()
    reloaded_logger.close()

    assert curve == [(1, 1000.0), (2, 1010.0), (3, 990.0)]


def test_load_equity_curve_respects_limit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("equity_limit_test")
    for i in range(10):
        logger.log_equity(i, float(i))
    logger.close()

    reloaded_logger = TradeLogger("equity_limit_test")
    curve = reloaded_logger.load_equity_curve(limit=3)
    reloaded_logger.close()

    assert curve == [(7, 7.0), (8, 8.0), (9, 9.0)]


def test_save_and_reload_open_positions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("open_positions_test")
    positions = [
        Position(quantity=1.5, avg_entry_price=100.0, entry_timestamp=10, lot_id=1, entry_fee=0.1, peak_price=105.0),
        Position(quantity=2.0, avg_entry_price=50.0, entry_timestamp=20, lot_id=2, entry_fee=0.05, peak_price=52.0),
    ]
    logger.save_open_positions(positions)
    logger.close()

    reloaded_logger = TradeLogger("open_positions_test")
    reloaded = reloaded_logger.load_open_positions()
    reloaded_logger.close()

    assert len(reloaded) == 2
    assert reloaded[0].lot_id == 1
    assert reloaded[0].quantity == 1.5
    assert reloaded[0].avg_entry_price == 100.0
    assert reloaded[0].entry_timestamp == 10
    assert reloaded[0].entry_fee == 0.1
    assert reloaded[0].peak_price == 105.0
    assert reloaded[1].lot_id == 2


def test_save_open_positions_replaces_previous_state(tmp_path, monkeypatch):
    """Une position clôturée entre deux sauvegardes ne doit plus apparaître :
    save_open_positions reflète toujours l'ensemble exact des lots ouverts a
    l'instant T, ce n'est pas un journal d'ajouts."""
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("open_positions_replace_test")
    logger.save_open_positions([Position(quantity=1.0, avg_entry_price=10.0, lot_id=1)])
    logger.save_open_positions([Position(quantity=2.0, avg_entry_price=20.0, lot_id=2)])

    reloaded = logger.load_open_positions()
    logger.close()

    assert len(reloaded) == 1
    assert reloaded[0].lot_id == 2


def test_save_open_positions_empty_list_clears_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("open_positions_clear_test")
    logger.save_open_positions([Position(quantity=1.0, avg_entry_price=10.0, lot_id=1)])
    logger.save_open_positions([])

    assert logger.load_open_positions() == []
    logger.close()


def test_load_open_positions_empty_when_none_saved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("open_positions_empty_test")
    assert logger.load_open_positions() == []
    logger.close()
