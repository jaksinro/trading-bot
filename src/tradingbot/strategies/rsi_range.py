"""Strategie de range trading par oscillateur RSI - etape 6, piste 6 de la
feuille de route performance, suite complementaire a `MeanReversionStrategy`.

`MeanReversionStrategy` (bandes de Bollinger) n'a demontre aucun edge sur les
4 paires sans edge connu (voir docs/FEUILLE_DE_ROUTE_PERFORMANCE.md, etape 6).
Le plan identifie explicitement une piste non explorée : elargir la recherche
a d'autres familles de strategies, pas seulement les bandes de Bollinger pour
le retour a la moyenne. `RsiRangeStrategy` retient le meme pari directionnel
(le prix revient vers sa moyenne apres un exces) mais avec un indicateur de
nature differente : un oscillateur de MOMENTUM (RSI, rapport gains/pertes
moyens sur une fenetre) plutot qu'un ecart-type de PRIX. Les deux peuvent
diverger sur les memes donnees (le RSI peut rester neutre pendant une chute
lente et continue, ou signaler une survente que les bandes de Bollinger ne
voient pas encore) - assez distinct pour constituer un vrai test de
diversification, pas une simple reparametrisation du meme indicateur.
"""

from collections import deque

from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class RsiRangeStrategy(Strategy):
    def __init__(self, period: int = 14, oversold: float = 30.0, overbought: float = 70.0):
        if period < 2:
            raise ValueError("period doit etre >= 2")
        if not 0 < oversold < overbought < 100:
            raise ValueError("il faut 0 < oversold < overbought < 100")
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self._prev_close: float | None = None
        self._gains: deque[float] = deque(maxlen=period)
        self._losses: deque[float] = deque(maxlen=period)
        self._in_position = False

    def _rsi(self) -> float:
        avg_gain = sum(self._gains) / self.period
        avg_loss = sum(self._losses) / self.period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_candle(self, candle: Candle) -> Signal | None:
        if self._prev_close is None:
            self._prev_close = candle.close
            return None

        change = candle.close - self._prev_close
        self._prev_close = candle.close
        self._gains.append(max(change, 0.0))
        self._losses.append(max(-change, 0.0))

        if len(self._gains) < self.period:
            return None

        rsi = self._rsi()

        if not self._in_position and rsi <= self.oversold:
            self._in_position = True
            return Signal(side=Side.BUY, reason="rsi_range_oversold")

        if self._in_position and rsi >= self.overbought:
            self._in_position = False
            return Signal(side=Side.SELL, reason="rsi_range_overbought")

        return None
