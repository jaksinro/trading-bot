from tradingbot.strategies.rsi_range import RsiRangeStrategy
from tradingbot.types import Candle, Side


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_no_signal_before_period_is_filled():
    strategy = RsiRangeStrategy(period=5, oversold=30.0, overbought=70.0)
    closes = [100, 99, 98, 97, 96]  # 1er close ne compte pas (pas de variation), puis 4 baisses < period=5
    for i, c in enumerate(closes):
        assert strategy.on_candle(make_candle(i, c)) is None


def test_buy_signal_when_rsi_drops_into_oversold():
    strategy = RsiRangeStrategy(period=5, oversold=30.0, overbought=70.0)
    closes = [100, 99, 98, 97, 96, 95, 94]  # baisses continues -> RSI proche de 0
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    assert len(buy_signals) == 1
    assert buy_signals[0].reason == "rsi_range_oversold"


def test_sell_signal_when_rsi_recovers_into_overbought():
    strategy = RsiRangeStrategy(period=5, oversold=30.0, overbought=70.0)
    closes = [100, 99, 98, 97, 96, 95, 94, 96, 98, 100, 102, 104, 106]  # baisse puis forte hausse
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    sell_signals = [s for s in signals if s is not None and s.side == Side.SELL]
    assert len(buy_signals) == 1
    assert len(sell_signals) == 1
    assert sell_signals[0].reason == "rsi_range_overbought"


def test_no_new_buy_signal_while_already_in_position():
    strategy = RsiRangeStrategy(period=5, oversold=30.0, overbought=70.0)
    closes = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91]  # reste en survente plusieurs bougies
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    assert len(buy_signals) == 1


def test_no_signal_when_price_stays_flat():
    strategy = RsiRangeStrategy(period=5, oversold=30.0, overbought=70.0)
    closes = [100, 100, 100, 100, 100, 100, 100, 100]
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    assert all(s is None for s in signals)


def test_invalid_period_raises():
    try:
        RsiRangeStrategy(period=1)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


def test_invalid_thresholds_raise():
    try:
        RsiRangeStrategy(period=14, oversold=70.0, overbought=30.0)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass
