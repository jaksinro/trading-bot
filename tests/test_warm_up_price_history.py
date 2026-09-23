from collections import deque

from tradingbot.analysis.atr_sizer import AtrSizer
from tradingbot.analysis.trend_filter import TrendFilter
from tradingbot.run_backtest import build_strategy
from tradingbot.run_paper import warm_up_strategy


class FakeExchange:
    def __init__(self, rows):
        self._rows = rows

    def fetch_ohlcv(self, symbol, timeframe, limit):
        return self._rows[-limit:]


def _rows(n):
    return [[i * 1000, 100.0 + i, 100.0 + i, 100.0 + i, 100.0 + i, 1.0] for i in range(n)]


def test_warm_up_strategy_seeds_price_history():
    strategy = build_strategy({"strategy": {"type": "sma_cross", "short_window": 3, "long_window": 5}})
    exchange = FakeExchange(_rows(10))
    price_history = deque(maxlen=200)

    warm_up_strategy(exchange, "ETH/USDT", "1h", strategy, warmup_candles=5, price_history=price_history)

    # 6 lignes recuperees (warmup_candles + 1), la derniere (en cours) exclue -> 5 points.
    assert len(price_history) == 5
    # EF-84 : [t, cloture, ouverture, haut, bas] - t et cloture en tete.
    assert price_history[0] == [4000, 104.0, 104.0, 104.0, 104.0]
    assert price_history[-1][:2] == [8000, 108.0]


def test_warm_up_strategy_works_without_price_history():
    strategy = build_strategy({"strategy": {"type": "sma_cross", "short_window": 3, "long_window": 5}})
    exchange = FakeExchange(_rows(10))

    last_ts = warm_up_strategy(exchange, "ETH/USDT", "1h", strategy, warmup_candles=5)

    assert last_ts == 8000


def test_warm_up_strategy_feeds_trend_filter():
    strategy = build_strategy({"strategy": {"type": "sma_cross", "short_window": 3, "long_window": 5}})
    exchange = FakeExchange(_rows(10))
    trend_filter = TrendFilter(ema_period=5)

    warm_up_strategy(exchange, "ETH/USDT", "1h", strategy, warmup_candles=5, trend_filter=trend_filter)

    assert trend_filter.ema is not None


def test_warm_up_strategy_extends_fetch_window_to_cover_ema_period():
    """Si l'EMA du filtre de tendance demande plus d'historique que le
    rechauffement de la strategie, on recupere assez de bougies pour que
    l'EMA ne soit pas 'a froid' au premier signal reel."""
    strategy = build_strategy({"strategy": {"type": "sma_cross", "short_window": 3, "long_window": 5}})
    exchange = FakeExchange(_rows(20))
    trend_filter = TrendFilter(ema_period=15)

    last_ts = warm_up_strategy(exchange, "ETH/USDT", "1h", strategy, warmup_candles=5, trend_filter=trend_filter)

    # limit demande = ema_period(15) + 1 = 16, dernier index disponible = 19 -> derniere bougie fermee a l'index 18.
    assert last_ts == 18000


def test_warm_up_strategy_feeds_atr_sizer():
    strategy = build_strategy({"strategy": {"type": "sma_cross", "short_window": 3, "long_window": 5}})
    exchange = FakeExchange(_rows(10))
    atr_sizer = AtrSizer(atr_period=5, baseline_period=8)

    warm_up_strategy(exchange, "ETH/USDT", "1h", strategy, warmup_candles=5, atr_sizer=atr_sizer)

    assert atr_sizer.atr is not None


def test_warm_up_strategy_extends_fetch_window_to_cover_atr_baseline_period():
    strategy = build_strategy({"strategy": {"type": "sma_cross", "short_window": 3, "long_window": 5}})
    exchange = FakeExchange(_rows(20))
    atr_sizer = AtrSizer(atr_period=5, baseline_period=15)

    last_ts = warm_up_strategy(exchange, "ETH/USDT", "1h", strategy, warmup_candles=5, atr_sizer=atr_sizer)

    # limit demande = baseline_period(15) + 1 = 16, meme calcul que pour le filtre de tendance.
    assert last_ts == 18000
