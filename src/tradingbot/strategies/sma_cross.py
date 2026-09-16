"""Strategie de croisement de moyennes mobiles (PO-2 de la STC).

Signal d'achat quand la moyenne mobile courte croise au-dessus de la longue,
signal de vente quand elle croise en dessous. Sert de "hello world" pour
valider tout le pipeline avant d'investir dans une strategie plus poussee.
"""

from collections import deque

from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class SmaCrossStrategy(Strategy):
    def __init__(self, short_window: int = 10, long_window: int = 30):
        if short_window >= long_window:
            raise ValueError("short_window doit etre strictement inferieur a long_window")
        self.short_window = short_window
        self.long_window = long_window
        self._closes: deque[float] = deque(maxlen=long_window)
        self._prev_short_above_long: bool | None = None

    def on_candle(self, candle: Candle) -> Signal | None:
        self._closes.append(candle.close)
        if len(self._closes) < self.long_window:
            return None

        short_sma = sum(list(self._closes)[-self.short_window :]) / self.short_window
        long_sma = sum(self._closes) / self.long_window
        short_above_long = short_sma > long_sma

        signal = None
        if self._prev_short_above_long is not None:
            if short_above_long and not self._prev_short_above_long:
                signal = Signal(side=Side.BUY, reason="sma_cross_up")
            elif not short_above_long and self._prev_short_above_long:
                signal = Signal(side=Side.SELL, reason="sma_cross_down")

        self._prev_short_above_long = short_above_long
        return signal
