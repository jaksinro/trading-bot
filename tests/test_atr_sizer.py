import pytest

from tradingbot.analysis.atr_sizer import AtrSizer
from tradingbot.types import Candle


def make_candle(i: int, high: float, low: float, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=high, low=low, close=close, volume=1.0)


def test_rejects_non_positive_atr_period():
    with pytest.raises(ValueError, match="atr_period"):
        AtrSizer(atr_period=0)


def test_rejects_non_positive_baseline_period():
    with pytest.raises(ValueError, match="baseline_period"):
        AtrSizer(baseline_period=0)


def test_rejects_min_size_multiplier_out_of_range():
    with pytest.raises(ValueError, match="min_size_multiplier"):
        AtrSizer(min_size_multiplier=0.0)
    with pytest.raises(ValueError, match="min_size_multiplier"):
        AtrSizer(min_size_multiplier=1.5)


def test_size_multiplier_is_one_before_any_update():
    sizer = AtrSizer()
    assert sizer.size_multiplier() == 1.0


def test_first_update_sets_atr_to_first_true_range():
    sizer = AtrSizer()
    sizer.update(make_candle(0, high=105.0, low=100.0, close=102.0))
    assert sizer.atr == 5.0  # high-low, pas de close precedent


def test_size_multiplier_stays_one_when_volatility_is_stable():
    sizer = AtrSizer(atr_period=5, baseline_period=20)
    for i in range(30):
        sizer.update(make_candle(i, high=102.0, low=100.0, close=101.0))  # amplitude constante
    assert sizer.size_multiplier() == pytest.approx(1.0, abs=0.01)


def test_size_multiplier_drops_when_volatility_spikes():
    sizer = AtrSizer(atr_period=5, baseline_period=20)
    for i in range(30):
        sizer.update(make_candle(i, high=102.0, low=100.0, close=101.0))  # amplitude calme -> baseline basse
    for i in range(30, 40):
        sizer.update(make_candle(i, high=130.0, low=100.0, close=115.0))  # pic de volatilite

    assert sizer.size_multiplier() < 1.0


def test_size_multiplier_never_exceeds_one():
    sizer = AtrSizer(atr_period=5, baseline_period=20)
    for i in range(30):
        sizer.update(make_candle(i, high=130.0, low=100.0, close=115.0))  # volatilite elevee d'abord
    for i in range(30, 40):
        sizer.update(make_candle(i, high=101.0, low=100.0, close=100.5))  # puis calme (ATR courant < baseline)

    assert sizer.size_multiplier() <= 1.0


def test_size_multiplier_never_goes_below_configured_minimum():
    sizer = AtrSizer(atr_period=5, baseline_period=20, min_size_multiplier=0.3)
    for i in range(30):
        sizer.update(make_candle(i, high=101.0, low=100.0, close=100.5))  # calme -> baseline tres basse
    sizer.update(make_candle(30, high=10_000.0, low=100.0, close=5000.0))  # volatilite extreme, un seul choc

    assert sizer.size_multiplier() == pytest.approx(0.3)
