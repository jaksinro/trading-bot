import pytest

from tradingbot import control_server
from tradingbot.control_server import fetch_price_history


class FakePriceExchange:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def fetch_ohlcv(self, symbol, timeframe, limit):
        self.calls.append((symbol, timeframe, limit))
        return self.rows[-limit:]


def _rows(n):
    return [[i * 1000, 1.0, 1.0, 1.0, 100.0 + i, 1.0] for i in range(n)]


@pytest.fixture(autouse=True)
def clear_price_history_cache():
    control_server._price_history_cache.clear()
    yield
    control_server._price_history_cache.clear()


def test_fetch_price_history_maps_range_to_timeframe_and_limit():
    fake = FakePriceExchange(_rows(200))
    points = fetch_price_history("BTC/USDT", "1h", exchange=fake)
    assert fake.calls == [("BTC/USDT", "1m", 60)]
    assert len(points) == 60


def test_fetch_price_history_returns_timestamp_close_pairs():
    fake = FakePriceExchange(_rows(500))
    points = fetch_price_history("BTC/USDT", "1an", exchange=fake)
    assert points[0] == [int((500 - 365) * 1000), 100.0 + (500 - 365)]
    assert len(points) == 365


def test_fetch_price_history_rejects_unknown_range():
    fake = FakePriceExchange(_rows(10))
    with pytest.raises(ValueError, match="periode inconnue"):
        fetch_price_history("BTC/USDT", "bogus_range", exchange=fake)


def test_fetch_price_history_caches_result_per_symbol_and_range():
    fake = FakePriceExchange(_rows(500))
    fetch_price_history("ETH/USDT", "5ans", exchange=fake)
    fetch_price_history("ETH/USDT", "5ans", exchange=fake)
    assert len(fake.calls) == 1


def test_fetch_price_history_does_not_share_cache_across_symbols():
    fake = FakePriceExchange(_rows(500))
    fetch_price_history("ETH/USDT", "1j", exchange=fake)
    fetch_price_history("BTC/USDT", "1j", exchange=fake)
    assert len(fake.calls) == 2
