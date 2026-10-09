"""Data Feed (STC section 3.2, EF-01 de la STB).

Recupere l'historique OHLCV via ccxt (crypto) et le met en cache localement
en Parquet pour eviter de re-telecharger a chaque backtest.

EF-63 (2026-09-16, demande de l'utilisateur - "passer aux actions") :
`exchange_id="yfinance"` bascule sur Yahoo Finance (bougies JOURNALIERES
uniquement - voir `_fetch_yfinance_dataframe`) pour backtester des actions
(ex: TotalEnergies, ticker "TTE.PA") - meme pipeline de cache Parquet que la
crypto, `Engine`/`Strategy`/`RiskManager`/`Portfolio` ne voient que des
`Candle` et n'ont besoin d'aucun changement."""

from datetime import datetime, timezone
from pathlib import Path

import ccxt
import pandas as pd
import yfinance as yf

from tradingbot.types import Candle, FundingRatePoint

CACHE_DIR = Path("data_cache")


def _safe_symbol(symbol: str) -> str:
    # Les perpetuels lineaires (ex: "BTC/USDT:USDT") contiennent aussi ":".
    return symbol.replace("/", "-").replace(":", "-")


def _cache_path(exchange_id: str, symbol: str, timeframe: str) -> Path:
    return CACHE_DIR / f"{exchange_id}_{_safe_symbol(symbol)}_{timeframe}.parquet"


def _funding_cache_path(exchange_id: str, symbol: str) -> Path:
    return CACHE_DIR / f"{exchange_id}_{_safe_symbol(symbol)}_funding.parquet"


def parse_iso_to_ms(since_iso: str) -> int | None:
    """Equivalent generique de `exchange.parse8601` (ccxt) pour la branche
    `yfinance` - `datetime.fromisoformat` gere deja le suffixe "Z" depuis
    Python 3.11. Retourne `None` sur une date sans heure, comme ccxt, pour
    garder le meme comportement de cache (voir docstring appelante)."""
    try:
        dt = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def filter_candles(candles: list[Candle], since_ms: int, until_ms: int | None) -> list[Candle]:
    """Utilitaire generique reutilise par `run_backtest.py` et
    `backtest_lab.py` - vit ici (pas dans `backtest_lab.py`) pour eviter un
    import circulaire (`backtest_lab.py` importe deja `run_backtest.py` pour
    son `STRATEGY_REGISTRY`)."""
    return [c for c in candles if c.timestamp >= since_ms and (until_ms is None or c.timestamp <= until_ms)]


def _fetch_yfinance_dataframe(symbol: str, timeframe: str, since_ms: int | None, download_fn=None) -> pd.DataFrame:
    """EF-63 : recupere l'historique d'une action via Yahoo Finance -
    UNIQUEMENT en bougies journalieres (historique intrajournalier Yahoo
    trop limite, ~2 ans, pour un backtest fiable comparable a la crypto ;
    le journalier a un historique quasi illimite et evite completement la
    question des heures de marche fermees - aucune bougie n'existe pour un
    jour non ouvre, pas besoin de le gerer explicitement)."""
    if timeframe != "1d":
        raise ValueError(
            "seul le timeframe '1d' est supporte pour les actions (exchange_id='yfinance') - "
            "l'historique intrajournalier Yahoo Finance est trop limite pour un backtest fiable"
        )
    download = download_fn if download_fn is not None else yf.download
    start = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc) if since_ms is not None else None
    raw = download(symbol, start=start, interval="1d", auto_adjust=True, progress=False)
    if hasattr(raw.columns, "get_level_values"):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw.reset_index()
    raw.columns = [str(c).lower() for c in raw.columns]
    return pd.DataFrame({
        "timestamp": raw["date"].astype("datetime64[ms]").astype("int64"),
        "open": raw["open"], "high": raw["high"], "low": raw["low"], "close": raw["close"], "volume": raw["volume"],
    })


def fetch_historical_candles(
    exchange_id: str, symbol: str, timeframe: str, since_iso: str, use_cache: bool = True, exchange=None,
    yf_download_fn=None,
) -> list[Candle]:
    """`exchange` (optionnel) permet d'injecter un client factice pour les
    tests, comme `fetch_funding_rate_history` - ignore si `exchange_id`
    vaut `"yfinance"` (pas de client ccxt dans ce cas, voir `yf_download_fn`
    pour l'equivalent injectable de ce chemin, EF-63).

    Le cache est ignore (et une recuperation fraiche est lancee) si son
    historique le plus ancien est POSTERIEUR a `since_iso` demande - sinon
    une periode plus ancienne que ce qui avait ete mis en cache la premiere
    fois renverrait silencieusement 0 bougie apres filtrage par l'appelant
    (bug reel : un cache 1m etroit pour DOGE/USDT, construit pour une autre
    periode, masquait totalement une periode differente demandee ensuite
    depuis l'onglet Test/Backtest du dashboard). Meme regle appliquee au
    cache `yfinance`."""
    cache_path = _cache_path(exchange_id, symbol, timeframe)
    is_yfinance = exchange_id == "yfinance"
    if is_yfinance:
        since_ms = parse_iso_to_ms(since_iso)
    else:
        if exchange is None:
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class()
        since_ms = exchange.parse8601(since_iso)

    if use_cache and cache_path.exists():
        df = pd.read_parquet(cache_path)
        if since_ms is None or df.empty or df["timestamp"].min() <= since_ms:
            return _dataframe_to_candles(df)

    if is_yfinance:
        df = _fetch_yfinance_dataframe(symbol, timeframe, since_ms, yf_download_fn)
    else:
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


def extend_cache_to_now(exchange_id: str, symbol: str, timeframe: str, exchange=None) -> int:
    """Complete le cache par la FIN avec les bougies parues depuis (EF-100).
    `fetch_historical_candles` ne relit jamais l'exchange une fois le cache
    cree : l'atelier de backtest s'arretait au jour du premier telechargement.
    Ne touche pas au debut du cache. Renvoie le nombre de bougies ajoutees ;
    la bougie en cours (non close) n'est jamais gardee."""
    cache_path = _cache_path(exchange_id, symbol, timeframe)
    if exchange_id == "yfinance" or not cache_path.exists():
        return 0
    df = pd.read_parquet(cache_path)
    if df.empty:
        return 0
    if exchange is None:
        exchange = getattr(ccxt, exchange_id)()
    step = exchange.parse_timeframe(timeframe) * 1000
    now = exchange.milliseconds()
    rows: list[list[float]] = []
    since = int(df["timestamp"].max()) + 1
    while since + step <= now:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
        closed = [r for r in batch if r[0] + step <= now]   # bougies closes seulement
        if not closed:
            break
        rows.extend(closed)
        since = closed[-1][0] + 1
        if len(batch) < 1000:
            break
    if not rows:
        return 0
    new = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    merged = pd.concat([df, new]).drop_duplicates("timestamp", keep="last").sort_values("timestamp")
    merged.reset_index(drop=True).to_parquet(cache_path)
    return len(merged) - len(df)


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
