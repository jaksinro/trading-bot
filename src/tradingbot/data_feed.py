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


# EF-117 : profondeur d'historique Yahoo Finance par unite (jours ; None = sans limite).
YF_DEPTH_DAYS = {"1d": None, "1h": 729, "30m": 59, "15m": 59, "5m": 59, "1m": 6}
YF_STEP_MS = {"1d": 86_400_000, "1h": 3_600_000, "30m": 1_800_000, "15m": 900_000, "5m": 300_000, "1m": 60_000}

# EF-116 : places dont les pages sont plus courtes que demande (Coinbase : 300 bougies) et qui
# sautent les minutes sans echange - une page incomplete n'y signifie PAS la fin de l'historique.
SHORT_PAGE_EXCHANGES = {"coinbase"}


def _fetch_until_now(exchange, symbol: str, timeframe: str, since_ms: int) -> list:
    """Pagination jusqu'a la derniere bougie close, trous sans echange compris."""
    tf_ms = exchange.parse_timeframe(timeframe) * 1000
    now = exchange.milliseconds()
    rows, since = [], since_ms
    while since < now - tf_ms:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=300)
        if not batch:
            since += 300 * tf_ms              # fenetre sans aucun echange : on la saute
            continue
        rows.extend(batch)
        since = batch[-1][0] + 1
    return rows


def split_symbol(symbol: str, default_exchange: str = "binance") -> tuple[str, str]:
    """EF-116 : "COINBASE:ETH/USD" -> ("coinbase", "ETH/USD") ; "ETH/USDT" -> ("binance", "ETH/USDT").
    Prefixe de place comme sur TradingView, pour choisir la source des cours sans changer les signatures."""
    if ":" in symbol and symbol.split(":", 1)[0].isalpha():
        exchange, pair = symbol.split(":", 1)
        exchange = exchange.lower()
        return ("yfinance" if exchange == "yahoo" else exchange), pair   # EF-117 : YAHOO:^GSPC
    return default_exchange, symbol


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
    # EF-117 : indices et matieres premieres - Yahoo donne aussi de l'intrajournalier, sur une
    # profondeur limitee (1 h : 2 ans ; 30/15/5 min : 60 jours ; 1 min : 7 jours). Le debut est
    # ramene dans la fenetre permise plutot que de faire echouer la requete.
    if timeframe not in YF_DEPTH_DAYS:
        raise ValueError(f"unite '{timeframe}' indisponible chez Yahoo Finance (possibles : {', '.join(YF_DEPTH_DAYS)})")
    depth = YF_DEPTH_DAYS[timeframe]
    if depth is not None:
        floor_ms = int((datetime.now(tz=timezone.utc).timestamp() - depth * 86_400) * 1000)
        since_ms = max(since_ms or floor_ms, floor_ms)
    download = download_fn if download_fn is not None else yf.download
    start = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc) if since_ms is not None else None
    raw = download(symbol, start=start, interval=timeframe, auto_adjust=True, progress=False)
    if hasattr(raw.columns, "get_level_values"):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw.reset_index()
    raw.columns = [str(c).lower() for c in raw.columns]
    when = raw["date"] if "date" in raw.columns else raw["datetime"]   # intrajournalier : "Datetime" en UTC
    when = pd.to_datetime(when, utc=True).dt.tz_localize(None)
    return pd.DataFrame({
        "timestamp": when.astype("datetime64[ms]").astype("int64"),
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
        if exchange_id in SHORT_PAGE_EXCHANGES:
            all_rows = _fetch_until_now(exchange, symbol, timeframe, fetch_since_ms)
        while exchange_id not in SHORT_PAGE_EXCHANGES:
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
    if not cache_path.exists():
        return 0
    df = pd.read_parquet(cache_path)
    if df.empty:
        return 0
    if exchange_id == "yfinance":                             # EF-117 : Yahoo, completer aussi par la fin
        since = int(df["timestamp"].max()) + 1
        new = _fetch_yfinance_dataframe(symbol, timeframe, since)
        now = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        new = new[(new["timestamp"] >= since) & (new["timestamp"] + YF_STEP_MS.get(timeframe, 0) <= now)]
        if new.empty:
            return 0
        merged = pd.concat([df, new]).drop_duplicates("timestamp", keep="last").sort_values("timestamp")
        merged.reset_index(drop=True).to_parquet(cache_path)
        return len(merged) - len(df)
    if exchange is None:
        exchange = getattr(ccxt, exchange_id)()
    step = exchange.parse_timeframe(timeframe) * 1000
    now = exchange.milliseconds()
    rows: list[list[float]] = []
    since = int(df["timestamp"].max()) + 1
    if exchange_id in SHORT_PAGE_EXCHANGES:                     # EF-116 : pages de 300, trous sautes
        rows = [r for r in _fetch_until_now(exchange, symbol, timeframe, since) if r[0] + step <= now]
    while exchange_id not in SHORT_PAGE_EXCHANGES and since + step <= now:
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
