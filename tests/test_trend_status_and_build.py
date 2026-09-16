from tradingbot.analysis.trend_filter import TrendFilter
from tradingbot.run_backtest import build_trend_filter
from tradingbot.run_paper import trend_status


def test_trend_status_none_when_no_filter():
    assert trend_status(None, current_price=100.0) is None


def test_trend_status_reports_ema_in_formation():
    trend_filter = TrendFilter(ema_period=50)
    status = trend_status(trend_filter, current_price=100.0)
    assert status == {"ema_period": 50, "ema": None, "is_bullish": None}


def test_trend_status_reports_bullish_once_ema_formed():
    trend_filter = TrendFilter(ema_period=5)
    trend_filter.update(100.0)
    status = trend_status(trend_filter, current_price=120.0)
    assert status["ema_period"] == 5
    assert status["ema"] == 100.0
    assert status["is_bullish"] is True


def test_build_trend_filter_absent_by_default():
    assert build_trend_filter({}) is None


def test_build_trend_filter_disabled_explicitly():
    assert build_trend_filter({"trend_filter": {"enabled": False}}) is None


def test_build_trend_filter_enabled_with_default_ema_period():
    trend_filter = build_trend_filter({"trend_filter": {"enabled": True}})
    assert trend_filter.ema_period == 200


def test_build_trend_filter_enabled_with_custom_ema_period():
    trend_filter = build_trend_filter({"trend_filter": {"enabled": True, "ema_period": 50}})
    assert trend_filter.ema_period == 50
