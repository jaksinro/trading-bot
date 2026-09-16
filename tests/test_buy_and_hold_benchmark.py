from tradingbot.reporting.stats import compute_buy_and_hold_return_pct
from tradingbot.types import Candle


def make_candle(price: float, timestamp: int = 0) -> Candle:
    return Candle(timestamp=timestamp, open=price, high=price, low=price, close=price, volume=1.0)


def test_buy_and_hold_positive_return():
    candles = [make_candle(100, 0), make_candle(150, 1)]
    assert compute_buy_and_hold_return_pct(candles) == 0.5


def test_buy_and_hold_negative_return():
    candles = [make_candle(100, 0), make_candle(80, 1)]
    assert compute_buy_and_hold_return_pct(candles) == -0.2


def test_buy_and_hold_uses_first_and_last_only():
    candles = [make_candle(100, 0), make_candle(500, 1), make_candle(10, 2), make_candle(110, 3)]
    assert compute_buy_and_hold_return_pct(candles) == 0.1


def test_buy_and_hold_none_when_too_few_candles():
    assert compute_buy_and_hold_return_pct([]) is None
    assert compute_buy_and_hold_return_pct([make_candle(100, 0)]) is None


def test_buy_and_hold_none_when_first_price_is_zero():
    candles = [make_candle(0, 0), make_candle(100, 1)]
    assert compute_buy_and_hold_return_pct(candles) is None
