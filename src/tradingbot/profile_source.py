"""Bougies fines pour les profils de volume, comme TradingView (EF-109).

TradingView ne calcule pas un profil de volume avec les bougies du graphique :
il charge des bougies plus fines du meme symbole, choisies selon l'unite de
temps du graphique (table officielle du "Session Volume Profile",
https://www.tradingview.com/support/solutions/43000703072-session-volume-profile/ ,
relevee le 2026-10-09). Exemple : graphique 15 min -> bougies 1 min.

Ce module fournit ces bougies a une strategie qui en a besoin
(`set_profile_source`) : une "source" est une fonction `(debut_ms, fin_ms) ->
list[Candle]`, tiree du cache local (backtests, atelier) ou de l'exchange (bots).
"""
from __future__ import annotations

import bisect
from typing import Callable

from tradingbot.types import Candle

MINUTE_MS = 60_000
# (minutes du graphique jusqu'a, unite fine en minutes) - table TradingView.
TV_LOWER_TIMEFRAME = [(4, 1), (15, 1), (30, 5), (60, 10), (120, 15), (240, 30)]
ABOVE_240 = 60
# Unites fines que Binance fournit ; les autres sont fusionnees (10 min = 2 x 5 min).
NATIVE = {1: "1m", 3: "3m", 5: "5m", 15: "15m", 30: "30m", 60: "1h"}

Source = Callable[[int, int], list]


def _minutes(timeframe: str) -> int:
    unit = timeframe[-1]
    value = int(timeframe[:-1])
    return value * {"m": 1, "h": 60, "d": 1440, "w": 10080}[unit]


def lower_minutes(timeframe: str) -> int:
    """Unite fine (minutes) utilisee par TradingView pour un graphique `timeframe`."""
    chart = _minutes(timeframe)
    for upto, lower in TV_LOWER_TIMEFRAME:
        if chart <= upto:
            return lower
    return ABOVE_240


def fetch_plan(timeframe: str) -> tuple[str, int]:
    """(unite a telecharger, nombre de bougies a fusionner) pour obtenir l'unite fine."""
    minutes = lower_minutes(timeframe)
    if minutes in NATIVE:
        return NATIVE[minutes], 1
    base = max(m for m in NATIVE if minutes % m == 0)
    return NATIVE[base], minutes // base


def aggregate(candles: list[Candle], group: int, base_minutes: int) -> list[Candle]:
    """Fusionne `group` bougies consecutives alignees sur leur periode (5 min x 2 -> 10 min).
    Une periode incomplete (donnees manquantes) est gardee telle quelle : son volume compte."""
    if group <= 1:
        return list(candles)
    step = group * base_minutes * MINUTE_MS
    out, bucket = [], []
    for c in candles:
        if bucket and c.timestamp // step != bucket[0].timestamp // step:
            out.append(_merge(bucket, step))
            bucket = []
        bucket.append(c)
    if bucket:
        out.append(_merge(bucket, step))
    return out


def _merge(bucket: list[Candle], step: int) -> Candle:
    return Candle(timestamp=bucket[0].timestamp // step * step, open=bucket[0].open,
                  high=max(c.high for c in bucket), low=min(c.low for c in bucket),
                  close=bucket[-1].close, volume=sum(c.volume for c in bucket))


def preloaded(candles: list[Candle], period_ms: int) -> Source:
    """Source sur des bougies deja chargees (backtests). Une bougie n'est rendue
    que si elle est CLOSE avant `fin_ms` : jamais d'information future."""
    candles = sorted(candles, key=lambda c: c.timestamp)
    stamps = [c.timestamp for c in candles]

    def source(start_ms: int, end_ms: int) -> list[Candle]:
        i = bisect.bisect_left(stamps, start_ms)
        j = bisect.bisect_right(stamps, end_ms - period_ms)
        return candles[i:j]
    return source


def from_exchange(exchange, symbol: str, timeframe: str, page: int = 1000) -> Source:
    """Source lue sur l'exchange (bots) : bougies fines closes entre deux instants,
    par pages. Leve l'erreur de l'exchange : la strategie retombe alors sur ses
    propres bougies (voir `VolumeProfileStrategy._session_profile`)."""
    fetch_tf, group = fetch_plan(timeframe)
    base = _minutes(fetch_tf) * MINUTE_MS
    period = base * group

    def source(start_ms: int, end_ms: int) -> list[Candle]:
        rows, since = [], start_ms
        while since < end_ms:
            batch = exchange.fetch_ohlcv(symbol, timeframe=fetch_tf, since=since, limit=page)
            if not batch:
                break
            rows += [r for r in batch if start_ms <= r[0] < end_ms]
            last = int(batch[-1][0])
            if last + base <= since:
                break
            since = last + base
            if len(batch) < page:
                break
        candles = [Candle(timestamp=int(r[0]), open=float(r[1]), high=float(r[2]), low=float(r[3]),
                          close=float(r[4]), volume=float(r[5])) for r in rows]
        merged = aggregate(candles, group, base // MINUTE_MS)
        return [c for c in merged if c.timestamp + period <= end_ms]
    return source


def wants_profile(strategy) -> bool:
    return callable(getattr(strategy, "set_profile_source", None)) and getattr(strategy, "lower_timeframe_profile", False)


def attach_preloaded(strategy, timeframe: str, load: Callable[[str], list[Candle]]) -> bool:
    """Branche une source tiree du cache local si la strategie la demande.
    `load(unite)` rend les bougies de cette unite (deja filtrees sur la periode)."""
    if not wants_profile(strategy):
        return False
    fetch_tf, group = fetch_plan(timeframe)
    candles = aggregate(load(fetch_tf), group, _minutes(fetch_tf))
    strategy.set_profile_source(preloaded(candles, lower_minutes(timeframe) * MINUTE_MS))
    return True
