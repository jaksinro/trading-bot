"""Strategie de retour a la moyenne (bandes de Bollinger) - etape 6, piste
6 de la feuille de route performance.

Famille de strategie DIFFERENTE de `sma_cross`/`scalp_dip`, qui sont toutes
deux des strategies de suivi de tendance/momentum (elles achetent quand le
prix va dans un sens et parient qu'il continue). `MeanReversionStrategy`
parie l'inverse : un prix qui s'est trop ecarte de sa moyenne recente a
tendance a y revenir - achat quand le prix casse sous la bande basse
(survente), vente quand il revient a la moyenne (bande du milieu). Sert a
diversifier l'edge de la flotte : quand le suivi de tendance echoue (marche
sans tendance nette, en range), un retour a la moyenne peut compenser.
"""

from collections import deque

from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class MeanReversionStrategy(Strategy):
    def __init__(self, window: int = 20, num_std: float = 2.0):
        if window < 2:
            raise ValueError("window doit etre >= 2")
        if num_std <= 0:
            raise ValueError("num_std doit etre strictement positif")
        self.window = window
        self.num_std = num_std
        self._closes: deque[float] = deque(maxlen=window)
        self._in_position = False

    def _bands(self) -> tuple[float, float, float]:
        closes = list(self._closes)
        middle = sum(closes) / len(closes)
        variance = sum((c - middle) ** 2 for c in closes) / len(closes)
        std = variance**0.5
        lower = middle - self.num_std * std
        upper = middle + self.num_std * std
        return lower, middle, upper

    def on_candle(self, candle: Candle) -> Signal | None:
        self._closes.append(candle.close)
        if len(self._closes) < self.window:
            return None

        lower, middle, _upper = self._bands()

        if not self._in_position and candle.close <= lower:
            self._in_position = True
            return Signal(side=Side.BUY, reason="mean_reversion_oversold")

        if self._in_position and candle.close >= middle:
            self._in_position = False
            return Signal(side=Side.SELL, reason="mean_reversion_reverted")

        return None
