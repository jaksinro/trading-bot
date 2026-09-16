from tradingbot.strategies.sma_cross import SmaCrossStrategy
from tradingbot.types import Candle, Side


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_no_signal_before_long_window_is_filled():
    strategy = SmaCrossStrategy(short_window=2, long_window=4)
    for i, close in enumerate([100, 100, 100]):
        assert strategy.on_candle(make_candle(i, close)) is None


def test_buy_signal_on_upward_cross():
    strategy = SmaCrossStrategy(short_window=2, long_window=4)
    closes = [100, 100, 100, 100, 110, 120]  # la moyenne courte finit par depasser la longue
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    assert len(buy_signals) >= 1


def test_invalid_windows_raise():
    try:
        SmaCrossStrategy(short_window=10, long_window=5)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass
