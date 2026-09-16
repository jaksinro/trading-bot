import pytest

from tradingbot.analysis.price_level_sizer import PriceLevelSizer
from tradingbot.types import Candle


def make_candle(ts_ms: int, close: float) -> Candle:
    return Candle(timestamp=ts_ms, open=close, high=close, low=close, close=close, volume=1.0)


def ts(year: int, month: int, day: int) -> int:
    from datetime import datetime, timezone
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


def test_size_multiplier_is_one_before_any_update():
    sizer = PriceLevelSizer()
    assert sizer.size_multiplier(100.0) == 1.0


def test_size_multiplier_above_one_when_price_below_month_average():
    sizer = PriceLevelSizer(min_size_multiplier=0.5, max_size_multiplier=1.5)
    sizer.update(make_candle(ts(2026, 6, 1), 100.0))
    sizer.update(make_candle(ts(2026, 6, 2), 100.0))
    assert sizer.month_average == 100.0
    assert sizer.size_multiplier(90.0) > 1.0


def test_size_multiplier_below_one_when_price_above_month_average():
    sizer = PriceLevelSizer(min_size_multiplier=0.5, max_size_multiplier=1.5)
    sizer.update(make_candle(ts(2026, 6, 1), 100.0))
    assert sizer.size_multiplier(110.0) < 1.0


def test_size_multiplier_never_exceeds_max():
    sizer = PriceLevelSizer(min_size_multiplier=0.5, max_size_multiplier=1.5)
    sizer.update(make_candle(ts(2026, 6, 1), 100.0))
    assert sizer.size_multiplier(1.0) == 1.5  # ratio enorme, plafonne


def test_size_multiplier_never_goes_below_min():
    sizer = PriceLevelSizer(min_size_multiplier=0.5, max_size_multiplier=1.5)
    sizer.update(make_candle(ts(2026, 6, 1), 100.0))
    assert sizer.size_multiplier(10_000.0) == 0.5  # ratio minuscule, plancher


def test_month_average_resets_on_calendar_month_change():
    sizer = PriceLevelSizer()
    sizer.update(make_candle(ts(2026, 6, 30), 100.0))
    assert sizer.month_average == 100.0
    sizer.update(make_candle(ts(2026, 7, 1), 200.0))
    assert sizer.month_average == 200.0  # repart de zero, l'ancien mois ne pese plus


def test_invalid_bounds_raise():
    with pytest.raises(ValueError):
        PriceLevelSizer(min_size_multiplier=0)
    with pytest.raises(ValueError):
        PriceLevelSizer(min_size_multiplier=1.0, max_size_multiplier=0.5)
