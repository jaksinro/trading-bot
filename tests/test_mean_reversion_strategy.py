from tradingbot.strategies.mean_reversion import MeanReversionStrategy
from tradingbot.types import Candle, Side


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_no_signal_before_window_is_filled():
    strategy = MeanReversionStrategy(window=5, num_std=2.0)
    for i in range(4):
        assert strategy.on_candle(make_candle(i, 100.0)) is None


def test_buy_signal_when_price_drops_below_lower_band():
    strategy = MeanReversionStrategy(window=5, num_std=1.0)
    closes = [100, 100, 100, 100, 100, 80]  # chute brutale sous la bande basse
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    assert len(buy_signals) == 1
    assert buy_signals[0].reason == "mean_reversion_oversold"


def test_sell_signal_when_price_reverts_to_middle_band():
    strategy = MeanReversionStrategy(window=5, num_std=1.0)
    closes = [100, 100, 100, 100, 100, 80, 85, 90, 100]  # chute puis retour vers la moyenne
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    sell_signals = [s for s in signals if s is not None and s.side == Side.SELL]
    assert len(sell_signals) == 1
    assert sell_signals[0].reason == "mean_reversion_reverted"


def test_no_new_buy_signal_while_already_in_position():
    strategy = MeanReversionStrategy(window=5, num_std=1.0)
    closes = [100, 100, 100, 100, 100, 80, 70, 60]  # reste sous la bande basse plusieurs bougies
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    assert len(buy_signals) == 1  # un seul signal d'achat malgre plusieurs bougies sous la bande


def test_no_signal_when_price_stays_within_bands():
    strategy = MeanReversionStrategy(window=5, num_std=2.0)
    closes = [100, 101, 99, 100, 101, 100, 99, 100]
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    assert all(s is None for s in signals)


def test_invalid_window_raises():
    try:
        MeanReversionStrategy(window=1, num_std=2.0)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


def test_invalid_num_std_raises():
    try:
        MeanReversionStrategy(window=10, num_std=0)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass
