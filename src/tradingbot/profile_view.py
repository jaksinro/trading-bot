"""Profil de volume d'une seance pour l'atelier de backtest (EF-115).

Demande de l'utilisateur (2026-10-13) : quand on clique un trade, voir le
Volume Profile comme sur TradingView - l'histogramme horizontal (volume
acheteur / vendeur par niveau de prix), le POC, le VAH et le VAL mis en avant.

`session_profile` rend l'histogramme de la seance que la strategie utilisait
au moment de l'entree : la seance PRECEDENTE (`profile_period: previous`), ou
la seance en cours jusqu'a l'entree (`developing`). Meme calcul que la
strategie (`profile_histogram`, methode TradingView) et memes bougies fines
(table TradingView, `profile_source`), lues dans le cache local sans charger
tout l'historique.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from tradingbot.data_feed import _cache_path, fetch_historical_candles
from tradingbot.profile_source import _minutes, aggregate, fetch_plan
from tradingbot.strategies.volume_profile import HOUR_MS, WEEK_OFFSET_MS, profile_histogram
from tradingbot.types import Candle


def _candles_between(symbol: str, timeframe: str, start: int, end: int) -> list[Candle]:
    """Bougies [start, end) du cache local ; telechargement seulement si le cache ne couvre pas."""
    path = _cache_path("binance", symbol, timeframe)
    if path.exists():
        df = pd.read_parquet(path, filters=[("timestamp", ">=", start), ("timestamp", "<", end)])
        if len(df):
            return [Candle(timestamp=int(r.timestamp), open=float(r.open), high=float(r.high), low=float(r.low),
                           close=float(r.close), volume=float(r.volume)) for r in df.itertuples(index=False)]
    since = datetime.fromtimestamp(start / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [c for c in fetch_historical_candles(exchange_id="binance", symbol=symbol, timeframe=timeframe,
                                                since_iso=since) if start <= c.timestamp < end]


def session_profile(payload: dict) -> dict:
    symbol = str(payload.get("symbol") or "ETH/USDT").upper()
    timeframe = str(payload.get("timeframe") or "15m")
    at = int(payload["time"])                                 # instant de l'entree (ms)
    session_hours = int(payload.get("session_hours") or 24)
    rows = int(payload.get("rows") or 24)
    value_area_pct = float(payload.get("value_area_pct") or 0.70)
    developing = payload.get("profile_period") == "developing"
    if session_hours < 1 or not 5 <= rows <= 500 or not 0 < value_area_pct < 1:
        raise ValueError("reglages du profil hors bornes")

    period = session_hours * HOUR_MS
    offset = WEEK_OFFSET_MS if session_hours % 168 == 0 else 0
    current = (at - offset) // period * period + offset        # debut de la seance de l'entree
    start, end = (current, at) if developing else (current - period, current)

    fetch_tf, group = fetch_plan(timeframe)
    candles = aggregate(_candles_between(symbol, fetch_tf, start, end), group, _minutes(fetch_tf))
    hist = profile_histogram(candles, rows, value_area_pct)
    if hist is None:
        raise ValueError("pas de bougies pour cette seance")
    return {**hist, "start": start, "end": end, "session_end": current + period,
            "candles": len(candles), "timeframe": fetch_tf if group == 1 else f"{group}x{fetch_tf}"}
