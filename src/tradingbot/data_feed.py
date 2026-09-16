"""Data Feed (STC section 3.2, EF-01 de la STB).

Recupere l'historique OHLCV via ccxt et le met en cache localement en
Parquet pour eviter de re-telecharger a chaque backtest.
"""

from pathlib import Path

import ccxt
import pandas as pd

from tradingbot.types import Candle, FundingRatePoint

CACHE_DIR = Path("data_cache")


def _safe_symbol(symbol: str) -> str:
    # Les perpetuels lineaires (ex: "BTC/USDT:USDT") contiennent aussi ":".
    return symbol.replace("/", "-").replace(":", "-")


def _cache_path(exchange_id: str, symbol: str, timeframe: str) -> Path:
    return CACHE_DIR / f"{exchange_id}_{_safe_symbol(symbol)}_{timeframe}.parquet"


def _funding_cache_path(exchange_id: str, symbol: str) -> Path:
    return CACHE_DIR / f"{exchange_id}_{_safe_symbol(symbol)}_funding.parquet"


def fetch_historical_candles(
    exchange_id: str, symbol: str, timeframe: str, since_iso: str, use_cache: bool = True, exchange=None
) -> list[Candle]:
    """`exchange` (optionnel) permet d'injecter un client factice pour les
    tests, comme `fetch_funding_rate_history`.

    Le cache est ignore (et une recuperation fraiche est lancee) si son
    historique le plus ancien est POSTERIEUR a `since_iso` demande - sinon
    une periode plus ancienne que ce qui avait ete mis en cache la premiere
    fois renverrait silencieusement 0 bougie apres filtrage par l'appelant
    (bug reel : un cache 1m etroit pour DOGE/USDT, construit pour une autre
    periode, masquait totalement une periode differente demandee ensuite
    depuis l'onglet Test/Backtest du dashboard)."""
    cache_path = _cache_path(exchange_id, symbol, timeframe)
    if exchange is None:
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class()
    since_ms = exchange.parse8601(since_iso)

    if use_cache and cache_path.exists():
        df = pd.read_parquet(cache_path)
        if since_ms is None or df.empty or df["timestamp"].min() <= since_ms:
            return _dataframe_to_candles(df)

    all_rows: list[list[float]] = []
    fetch_since_ms = since_ms
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=fetch_since_ms, limit=1000)
        if not batch:
            break
        all_rows.extend(batch)
        fetch_since_ms = batch[-1][0] + 1
        if len(batch) < 1000:
            break

    df = pd.DataFrame(all_rows, columns=["timestamp", "open", "high", "low", "close", "volume"])

    CACHE_DIR.mkdir(exist_ok=True)
    df.to_parquet(cache_path)

    return _dataframe_to_candles(df)


def fetch_funding_rate_history(
    exchange_id: str, symbol: str, since_iso: str, use_cache: bool = True, exchange=None
) -> list[FundingRatePoint]:
    """Historique des versements de funding d'un contrat perpetuel (etape 8,
    feuille de route performance - funding rate arbitrage). `symbol` au
    format perpetuel lineaire unifie ccxt (ex: "BTC/USDT:USDT"), pas le
    symbole spot. `exchange` (optionnel) permet d'injecter un client factice
    pour les tests, comme `control_server.fetch_price_history`."""
    cache_path = _funding_cache_path(exchange_id, symbol)
    if use_cache and exchange is None and cache_path.exists():
        df = pd.read_parquet(cache_path)
        return _dataframe_to_funding_points(df)

    if exchange is None:
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class()
    since_ms = exchange.parse8601(since_iso)

    all_rows: list[dict] = []
    while True:
        batch = exchange.fetch_funding_rate_history(symbol, since=since_ms, limit=1000)
        if not batch:
            break
        all_rows.extend(batch)
        since_ms = batch[-1]["timestamp"] + 1
        if len(batch) < 1000:
            break

    df = pd.DataFrame(
        [{"timestamp": r["timestamp"], "funding_rate": r["fundingRate"]} for r in all_rows]
    )

    if use_cache and exchange is None:
        CACHE_DIR.mkdir(exist_ok=True)
        df.to_parquet(cache_path)

    return _dataframe_to_funding_points(df)


def _dataframe_to_funding_points(df: pd.DataFrame) -> list[FundingRatePoint]:
    return [
        FundingRatePoint(timestamp=int(row.timestamp), funding_rate=float(row.funding_rate))
        for row in df.itertuples()
    ]


def _dataframe_to_candles(df: pd.DataFrame) -> list[Candle]:
    return [
        Candle(
            timestamp=int(row.timestamp),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in df.itertuples()
    ]
