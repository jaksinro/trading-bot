from tradingbot.strategies.buy_and_hold import BuyAndHoldStrategy
from tradingbot.types import Candle, Side


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_buys_once_on_first_candle():
    strategy = BuyAndHoldStrategy()
    signal = strategy.on_candle(make_candle(0, 100.0))
    assert signal is not None
    assert signal.side == Side.BUY
    assert signal.reason == "buy_and_hold_entry"


def test_never_sells_and_never_buys_again():
    strategy = BuyAndHoldStrategy()
    signals = [strategy.on_candle(make_candle(i, 100.0 + i)) for i in range(20)]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    sell_signals = [s for s in signals if s is not None and s.side == Side.SELL]
    assert len(buy_signals) == 1
    assert sell_signals == []
    assert signals[1:] == [None] * 19
