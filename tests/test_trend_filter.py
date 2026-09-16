import pytest

from tradingbot.analysis.trend_filter import TrendFilter


def test_rejects_non_positive_ema_period():
    with pytest.raises(ValueError, match="ema_period"):
        TrendFilter(ema_period=0)


def test_is_bullish_before_any_update_fails_open():
    trend_filter = TrendFilter(ema_period=10)
    assert trend_filter.is_bullish(current_price=50.0) is True


def test_first_update_sets_ema_to_that_price():
    trend_filter = TrendFilter(ema_period=10)
    trend_filter.update(100.0)
    assert trend_filter.ema == 100.0


def test_ema_moves_toward_new_prices():
    trend_filter = TrendFilter(ema_period=10)
    trend_filter.update(100.0)
    trend_filter.update(200.0)
    assert 100.0 < trend_filter.ema < 200.0


def test_is_bullish_when_price_above_ema():
    trend_filter = TrendFilter(ema_period=10)
    for _ in range(20):
        trend_filter.update(100.0)
    assert trend_filter.is_bullish(current_price=110.0) is True


def test_is_bearish_when_price_below_ema():
    trend_filter = TrendFilter(ema_period=10)
    for _ in range(20):
        trend_filter.update(100.0)
    assert trend_filter.is_bullish(current_price=90.0) is False


def test_longer_ema_period_reacts_slower_to_a_price_jump():
    fast = TrendFilter(ema_period=5)
    slow = TrendFilter(ema_period=50)
    for _ in range(30):
        fast.update(100.0)
        slow.update(100.0)
    fast.update(200.0)
    slow.update(200.0)
    assert fast.ema > slow.ema
