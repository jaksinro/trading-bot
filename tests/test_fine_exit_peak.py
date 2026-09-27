"""Le plus haut qui sert au trailing stop doit survivre a un redemarrage du bot
(constate le 2026-09-27 sur ETH_youenn : mis a jour toutes les 5 minutes en
memoire, mais enregistre seulement a la bougie horaire)."""
from types import SimpleNamespace

from tradingbot.reporting import logger as logger_module
from tradingbot.reporting.logger import TradeLogger
from tradingbot.run_paper import fine_exit_check
from tradingbot.types import Position


class PeakOnlyEngine:
    """Comme Engine.check_lot_exits : met a jour le plus haut, ne vend pas."""
    def __init__(self, positions):
        self.positions = positions

    def process_price_update(self, candle):
        for p in self.positions:
            p.peak_price = max(p.peak_price, p.avg_entry_price, candle.close)
        return []


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(logger_module, "DATA_DIR", tmp_path)
    position = Position(quantity=0.0185, avg_entry_price=2691.53, entry_timestamp=0, lot_id=1,
                        entry_fee=0.05, peak_price=2691.53)
    executor = SimpleNamespace(portfolio=SimpleNamespace(positions=[position], equity=lambda price: 0.0))
    return position, executor, TradeLogger("PEAK_TEST")


def test_peak_seen_between_candles_survives_a_restart(tmp_path, monkeypatch):
    position, executor, trade_logger = _setup(tmp_path, monkeypatch)
    engine = PeakOnlyEngine([position])
    fine_exit_check(engine, executor, trade_logger, 2709.68, now=1_000)
    fine_exit_check(engine, executor, trade_logger, 2700.00, now=1_300)   # repli : le plus haut ne baisse pas
    trade_logger.close()

    restored = TradeLogger("PEAK_TEST").load_open_positions()           # "redemarrage"
    assert restored[0].peak_price == 2709.68


def test_no_equity_point_written_when_nothing_is_sold(tmp_path, monkeypatch):
    position, executor, trade_logger = _setup(tmp_path, monkeypatch)
    fine_exit_check(PeakOnlyEngine([position]), executor, trade_logger, 2709.68, now=1_000)
    assert trade_logger.load_equity_curve() == []
