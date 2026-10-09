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

    # 7 lignes recuperees (warmup_candles + 2) : la derniere (en cours) exclue, et la
    # derniere CLOSE laissee a la boucle du bot (decision au demarrage) -> 5 points.
    assert len(price_history) == 5
    # EF-84 : [t, cloture, ouverture, haut, bas] - t et cloture en tete.
    assert price_history[0] == [3000, 103.0, 103.0, 103.0, 103.0]
    assert price_history[-1][:2] == [7000, 107.0]


def test_warm_up_strategy_works_without_price_history():
    strategy = build_strategy({"strategy": {"type": "sma_cross", "short_window": 3, "long_window": 5}})
    exchange = FakeExchange(_rows(10))

    last_ts = warm_up_strategy(exchange, "ETH/USDT", "1h", strategy, warmup_candles=5)

    assert last_ts == 7000   # la bougie close de 8000 reste a traiter par le bot


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

    # limit demande = ema_period(15) + 2 = 17, dernier index disponible = 19 -> derniere bougie fermee a l'index 18,
    # laissee a la boucle du bot (decision au demarrage) : le rechauffage s'arrete a l'index 17.
    assert last_ts == 17000


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

    # limit demande = baseline_period(15) + 2 = 17, meme calcul que pour le filtre de tendance.
    assert last_ts == 17000


def test_last_closed_candle_is_decided_by_the_bot_at_startup():
    """Bug reel du 2026-10-09 : la derniere bougie close etait absorbee par le
    rechauffage et le bot attendait la suivante. Un bot en bougies jour relance
    chaque matin ne decidait jamais. Elle doit sortir du premier passage de la
    boucle (poll_new_closed_candle) comme une vraie decision."""
    from tradingbot.run_paper import poll_new_closed_candle

    rows = _rows(10)   # 0..9000 ; 9000 = bougie en cours
    exchange = FakeExchange(rows)
    strategy = build_strategy({"strategy": {"type": "sma_cross", "short_window": 3, "long_window": 5}})
    last_ts = warm_up_strategy(exchange, "ETH/USDT", "1h", strategy, warmup_candles=5)
    first = poll_new_closed_candle(exchange, "ETH/USDT", "1h", last_ts)
    assert first is not None and first.timestamp == 8000
    assert poll_new_closed_candle(exchange, "ETH/USDT", "1h", first.timestamp) is None
