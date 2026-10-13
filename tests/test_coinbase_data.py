"""Cours Coinbase (EF-116) : prefixe de place, pages courtes et trous sans echange."""
from tradingbot.data_feed import _fetch_until_now, split_symbol

M = 60_000


def test_split_symbol():
    assert split_symbol("COINBASE:ETH/USD") == ("coinbase", "ETH/USD")
    assert split_symbol("ETH/USDT") == ("binance", "ETH/USDT")
    assert split_symbol("ETH/USD:USD-891230") == ("binance", "ETH/USD:USD-891230")   # contrat, pas un prefixe


class FakeCoinbase:
    """300 bougies par page au plus, et une heure sans aucun echange."""

    def __init__(self, end):
        self.end = end
        self.rows = [[t, 1, 2, 0.5, 1.5, 3] for t in range(0, end, M) if not 600 * M <= t < 660 * M]

    def parse_timeframe(self, tf):
        return 60

    def milliseconds(self):
        return self.end

    def fetch_ohlcv(self, symbol, timeframe, since, limit):
        return [r for r in self.rows if since <= r[0] < since + limit * M][:limit]


def test_pages_until_now_and_skips_gaps():
    ex = FakeCoinbase(end=2000 * M)
    rows = _fetch_until_now(ex, "ETH/USD", "1m", 0)
    assert len(rows) == 2000 - 60 and rows[-1][0] == 1999 * M
    assert len({r[0] for r in rows}) == len(rows)
