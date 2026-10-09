"""Bougies fines du profil de volume, comme TradingView (EF-109)."""
import pytest

from tradingbot.profile_source import aggregate, attach_preloaded, fetch_plan, from_exchange, lower_minutes, preloaded
from tradingbot.strategies.volume_profile import VolumeProfileStrategy
from tradingbot.types import Candle

M = 60_000


def k(t, price=100.0, volume=1.0):
    return Candle(timestamp=t, open=price, high=price + 1, low=price - 1, close=price, volume=volume)


@pytest.mark.parametrize("chart,lower", [("1m", 1), ("5m", 1), ("15m", 1), ("30m", 5), ("1h", 10),
                                         ("2h", 15), ("4h", 30), ("1d", 60)])
def test_tradingview_lower_timeframe_table(chart, lower):
    assert lower_minutes(chart) == lower


def test_ten_minutes_are_built_from_five_minute_candles():
    assert fetch_plan("1h") == ("5m", 2)
    assert fetch_plan("15m") == ("1m", 1)
    merged = aggregate([k(0, 100, 1), k(5 * M, 103, 2), k(10 * M, 99, 4)], 2, 5)
    assert [(x.timestamp, x.volume, x.high, x.close) for x in merged] == [(0, 3.0, 104.0, 103.0), (10 * M, 4.0, 100.0, 99.0)]


def test_preloaded_source_returns_only_closed_candles_of_the_interval():
    src = preloaded([k(i * M) for i in range(10)], M)
    assert [x.timestamp for x in src(2 * M, 5 * M)] == [2 * M, 3 * M, 4 * M]


class FakeExchange:
    def __init__(self, n):
        self.rows = [[i * M, 1, 2, 0.5, 1.5, 3] for i in range(n)]
        self.calls = 0

    def fetch_ohlcv(self, symbol, timeframe, since, limit):
        self.calls += 1
        return [r for r in self.rows if r[0] >= since][:limit]


def test_exchange_source_pages_through_the_session():
    ex = FakeExchange(2500)
    got = from_exchange(ex, "ETH/USDT", "15m", page=1000)(0, 1440 * M)
    assert len(got) == 1440 and got[-1].timestamp == 1439 * M and ex.calls == 2


def test_attach_only_when_the_strategy_asks_for_it():
    s = VolumeProfileStrategy()
    assert attach_preloaded(s, "15m", lambda tf: [k(0)]) and s._profile_source is not None
    off = VolumeProfileStrategy(lower_timeframe_profile=False)
    assert not attach_preloaded(off, "15m", lambda tf: [k(0)])
