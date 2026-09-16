from tradingbot.strategies.scalp_dip import ScalpDipStrategy
from tradingbot.types import Candle, Side


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_no_signal_before_lookback_is_filled():
    strategy = ScalpDipStrategy(lookback=5, dip_threshold_pct=0.01)
    for i, close in enumerate([100, 100, 100, 100]):
        assert strategy.on_candle(make_candle(i, close)) is None


def test_no_signal_on_stable_price():
    strategy = ScalpDipStrategy(lookback=5, dip_threshold_pct=0.01)
    signals = [strategy.on_candle(make_candle(i, 100)) for i in range(10)]
    assert all(s is None for s in signals)


def test_buy_signal_on_sufficient_dip():
    strategy = ScalpDipStrategy(lookback=5, dip_threshold_pct=0.01)
    closes = [100, 100, 100, 100, 100, 95]  # chute de 5%, superieure au seuil de 1%
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    assert signals[-1] is not None
    assert signals[-1].side == Side.BUY


def test_no_signal_when_dip_below_threshold():
    strategy = ScalpDipStrategy(lookback=5, dip_threshold_pct=0.10)
    closes = [100, 100, 100, 100, 100, 98]  # chute de 2%, sous le seuil de 10%
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    assert signals[-1] is None


def test_invalid_lookback_raises():
    try:
        ScalpDipStrategy(lookback=1)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass
