import pandas as pd
import pytest

from tradingbot.data_feed import fetch_funding_rate_history, fetch_historical_candles


class FakeCandleExchange:
    def __init__(self, rows, parse8601_result=None):
        self.rows = rows
        self.calls = []
        self._parse8601_result = parse8601_result

    def parse8601(self, iso: str):
        return self._parse8601_result

    def fetch_ohlcv(self, symbol, timeframe=None, since=None, limit=None):
        self.calls.append((symbol, timeframe, since, limit))
        batch = [r for r in self.rows if since is None or r[0] >= since][:limit]
        return batch


def _ohlcv_rows(n, start_ms=0, step_ms=60_000):
    return [[start_ms + i * step_ms, 1.0, 1.0, 1.0, 1.0, 1.0] for i in range(n)]


def test_fetch_historical_candles_uses_cache_when_it_covers_the_requested_period(tmp_path, monkeypatch):
    import tradingbot.data_feed as data_feed
    monkeypatch.setattr(data_feed, "CACHE_DIR", tmp_path)
    cache_path = tmp_path / "binance_BTC-USDT_1m.parquet"
    tmp_path.mkdir(exist_ok=True)
    pd.DataFrame(_ohlcv_rows(5, start_ms=0), columns=["timestamp", "open", "high", "low", "close", "volume"]).to_parquet(cache_path)

    fake = FakeCandleExchange([], parse8601_result=0)
    candles = fetch_historical_candles("binance", "BTC/USDT", "1m", "2024-01-01T00:00:00Z", exchange=fake)

    assert len(candles) == 5
    assert fake.calls == []  # cache suffisant, aucun appel reseau


def test_fetch_historical_candles_bypasses_a_cache_narrower_than_the_requested_period(tmp_path, monkeypatch):
    import tradingbot.data_feed as data_feed
    monkeypatch.setattr(data_feed, "CACHE_DIR", tmp_path)
    cache_path = tmp_path / "binance_BTC-USDT_1m.parquet"
    tmp_path.mkdir(exist_ok=True)
    # cache existant ne couvre que depuis start_ms=10_000_000 - la periode demandee (since_ms=0) est plus ancienne.
    pd.DataFrame(_ohlcv_rows(5, start_ms=10_000_000), columns=["timestamp", "open", "high", "low", "close", "volume"]).to_parquet(cache_path)

    fake = FakeCandleExchange(_ohlcv_rows(3, start_ms=0), parse8601_result=0)
    candles = fetch_historical_candles("binance", "BTC/USDT", "1m", "2024-01-01T00:00:00Z", exchange=fake)

    assert len(candles) == 3
    assert candles[0].timestamp == 0
    assert len(fake.calls) == 1  # cache ignore, une vraie recuperation a eu lieu


def test_fetch_historical_candles_keeps_cache_when_since_cannot_be_parsed(tmp_path, monkeypatch):
    import tradingbot.data_feed as data_feed
    monkeypatch.setattr(data_feed, "CACHE_DIR", tmp_path)
    cache_path = tmp_path / "binance_BTC-USDT_1m.parquet"
    tmp_path.mkdir(exist_ok=True)
    pd.DataFrame(_ohlcv_rows(2, start_ms=10_000_000), columns=["timestamp", "open", "high", "low", "close", "volume"]).to_parquet(cache_path)

    fake = FakeCandleExchange([], parse8601_result=None)  # comme ccxt sur une date sans heure
    candles = fetch_historical_candles("binance", "BTC/USDT", "1m", "2024-01-01", exchange=fake)

    assert len(candles) == 2
    assert fake.calls == []


def _fake_yfinance_download(rows):
    """`rows` : liste de (date_iso, open, high, low, close, volume) - imite
    le DataFrame renvoye par `yfinance.download` (colonnes capitalisees,
    index de dates nomme "Date"), sans MultiIndex (comme un vrai appel
    reussi le renvoie pour un seul ticker sur les versions recentes de la
    librairie observees, mais le code aplatit un MultiIndex si present)."""
    calls = []

    def download_fn(symbol, start=None, interval=None, auto_adjust=None, progress=None):
        calls.append({"symbol": symbol, "start": start, "interval": interval})
        df = pd.DataFrame(
            [{"Date": pd.Timestamp(r[0]), "Open": r[1], "High": r[2], "Low": r[3], "Close": r[4], "Volume": r[5]} for r in rows]
        ).set_index("Date")
        return df

    download_fn.calls = calls
    return download_fn


def test_fetch_historical_candles_yfinance_maps_daily_bars_to_candles(tmp_path, monkeypatch):
    import tradingbot.data_feed as data_feed
    monkeypatch.setattr(data_feed, "CACHE_DIR", tmp_path)
    download_fn = _fake_yfinance_download([
        ("2026-09-14", 79.5, 80.09, 79.0, 79.53, 3641360),
        ("2026-09-15", 79.14, 80.55, 78.94, 80.49, 3047143),
    ])

    candles = fetch_historical_candles(
        "yfinance", "TTE.PA", "1d", "2026-09-01T00:00:00Z", exchange=None, yf_download_fn=download_fn,
    )

    assert len(candles) == 2
    assert candles[0].open == 79.5
    assert candles[0].close == 79.53
    assert candles[1].volume == 3047143
    assert candles[0].timestamp < candles[1].timestamp
    assert download_fn.calls[0]["symbol"] == "TTE.PA"
    assert download_fn.calls[0]["interval"] == "1d"


def test_fetch_historical_candles_yfinance_rejects_non_daily_timeframe():
    download_fn = _fake_yfinance_download([])
    with pytest.raises(ValueError):
        fetch_historical_candles("yfinance", "TTE.PA", "1h", "2026-09-01T00:00:00Z", yf_download_fn=download_fn)
    assert download_fn.calls == []  # rejete avant tout appel reseau


def test_fetch_historical_candles_yfinance_uses_cache_when_it_covers_the_requested_period(tmp_path, monkeypatch):
    import tradingbot.data_feed as data_feed
    monkeypatch.setattr(data_feed, "CACHE_DIR", tmp_path)
    cache_path = tmp_path / "yfinance_TTE.PA_1d.parquet"
    tmp_path.mkdir(exist_ok=True)
    pd.DataFrame(_ohlcv_rows(5, start_ms=1_700_000_000_000), columns=["timestamp", "open", "high", "low", "close", "volume"]).to_parquet(cache_path)

    download_fn = _fake_yfinance_download([])
    candles = fetch_historical_candles(
        "yfinance", "TTE.PA", "1d", "2023-11-15T00:00:00Z", yf_download_fn=download_fn,
    )

    assert len(candles) == 5
    assert download_fn.calls == []  # cache suffisant, aucun appel reseau


def test_fetch_historical_candles_yfinance_bypasses_a_cache_narrower_than_the_requested_period(tmp_path, monkeypatch):
    import tradingbot.data_feed as data_feed
    monkeypatch.setattr(data_feed, "CACHE_DIR", tmp_path)
    cache_path = tmp_path / "yfinance_TTE.PA_1d.parquet"
    tmp_path.mkdir(exist_ok=True)
    # cache existant ne couvre que depuis une date recente - une periode plus ancienne est demandee.
    pd.DataFrame(_ohlcv_rows(5, start_ms=1_800_000_000_000), columns=["timestamp", "open", "high", "low", "close", "volume"]).to_parquet(cache_path)

    download_fn = _fake_yfinance_download([("2020-01-02", 50.0, 51.0, 49.0, 50.5, 1000)])
    candles = fetch_historical_candles(
        "yfinance", "TTE.PA", "1d", "2020-01-01T00:00:00Z", yf_download_fn=download_fn,
    )

    assert len(candles) == 1
    assert candles[0].open == 50.0
    assert len(download_fn.calls) == 1  # cache ignore, une vraie recuperation a eu lieu


class FakeFundingExchange:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def parse8601(self, iso: str) -> int:
        return 0

    def fetch_funding_rate_history(self, symbol, since=None, limit=None):
        self.calls.append((symbol, since, limit))
        batch = [r for r in self.rows if r["timestamp"] >= since][:limit]
        return batch


def _rows(n, rate=0.0001):
    return [{"timestamp": i * 28_800_000, "fundingRate": rate} for i in range(n)]


def test_fetch_funding_rate_history_maps_rows_to_points():
    fake = FakeFundingExchange(_rows(5, rate=0.0002))
    points = fetch_funding_rate_history("binance", "BTC/USDT:USDT", "2024-01-01T00:00:00Z", exchange=fake)
    assert len(points) == 5
    assert points[0].funding_rate == 0.0002
    assert points[0].timestamp == 0
    assert points[-1].timestamp == 4 * 28_800_000


def test_fetch_funding_rate_history_paginates_when_batch_is_full(monkeypatch):
    # 1500 lignes : 2 appels necessaires (limit=1000 code en dur).
    fake = FakeFundingExchange(_rows(1500))
    points = fetch_funding_rate_history("binance", "BTC/USDT:USDT", "2024-01-01T00:00:00Z", exchange=fake)
    assert len(points) == 1500
    assert len(fake.calls) == 2
    assert fake.calls[0][1] == 0  # premier appel depuis since=0 (parse8601 factice)
    assert fake.calls[1][1] == 999 * 28_800_000 + 1  # reprend juste apres le dernier timestamp recu


def test_fetch_funding_rate_history_stops_on_empty_batch():
    fake = FakeFundingExchange([])
    points = fetch_funding_rate_history("binance", "BTC/USDT:USDT", "2024-01-01T00:00:00Z", exchange=fake)
    assert points == []
    assert len(fake.calls) == 1


def test_fetch_funding_rate_history_does_not_touch_cache_when_exchange_injected(tmp_path, monkeypatch):
    import tradingbot.data_feed as data_feed
    monkeypatch.setattr(data_feed, "CACHE_DIR", tmp_path)
    fake = FakeFundingExchange(_rows(3))
    fetch_funding_rate_history("binance", "BTC/USDT:USDT", "2024-01-01T00:00:00Z", exchange=fake)
    assert list(tmp_path.iterdir()) == []
