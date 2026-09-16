from tradingbot.analysis.atr_sizer import AtrSizer
from tradingbot.run_backtest import build_atr_sizer
from tradingbot.run_paper import atr_sizer_status
from tradingbot.types import Candle


def make_candle(i: int, high: float, low: float, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=high, low=low, close=close, volume=1.0)


def test_atr_sizer_status_none_when_no_sizer():
    assert atr_sizer_status(None) is None


def test_atr_sizer_status_reports_none_multiplier_before_formation():
    sizer = AtrSizer(atr_period=5, baseline_period=20)
    status = atr_sizer_status(sizer)
    assert status == {"atr_period": 5, "baseline_period": 20, "size_multiplier": None}


def test_atr_sizer_status_reports_multiplier_once_formed():
    sizer = AtrSizer(atr_period=5, baseline_period=20)
    sizer.update(make_candle(0, high=105.0, low=100.0, close=102.0))
    status = atr_sizer_status(sizer)
    assert status["atr_period"] == 5
    assert status["size_multiplier"] == 1.0


def test_build_atr_sizer_absent_by_default():
    assert build_atr_sizer({}) is None


def test_build_atr_sizer_disabled_explicitly():
    assert build_atr_sizer({"atr_sizing": {"enabled": False}}) is None


def test_build_atr_sizer_enabled_with_default_values():
    sizer = build_atr_sizer({"atr_sizing": {"enabled": True}})
    assert sizer.atr_period == 14
    assert sizer.baseline_period == 100
    assert sizer.min_size_multiplier == 0.2


def test_build_atr_sizer_enabled_with_custom_values():
    sizer = build_atr_sizer({
        "atr_sizing": {"enabled": True, "atr_period": 10, "baseline_period": 50, "min_size_multiplier": 0.3},
    })
    assert sizer.atr_period == 10
    assert sizer.baseline_period == 50
    assert sizer.min_size_multiplier == 0.3
