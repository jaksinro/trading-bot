"""Strategie "creux vs moyenne mobile" (2026-09-16, proposee par
l'utilisateur) - detecte un creux comme un ECART a la moyenne recente
(bandes de Bollinger, meme calcul que `MeanReversionStrategy`), sur une
granularite fine (5 minutes par defaut, fenetre ~1h = 12 bougies), pour
capter les pics descendants brefs visibles sur le graphique en direct que
`dip_bounce` (fenetre glissante de 24h) ne peut pas voir.

Different de `MeanReversionStrategy` sur 2 points essentiels :
1. AUCUN signal de vente emis par la strategie elle-meme - contrairement au
   "retour a la moyenne" de `MeanReversionStrategy`, ici la seule sortie
   voulue (demande explicite) est stop-loss/trailing stop, geres par
   `RiskManager`/`Engine`, jamais par la strategie.
2. AUCUN etat interne "en position" (`_in_position`). `MeanReversionStrategy`
   en a un pour eviter un double achat, mais ce flag ne serait jamais
   informe si une sortie EXTERNE (stop-loss/trailing) fermait la position -
   il resterait bloque a `True` pour toujours, empechant tout futur achat
   (piege deja identifie et evite dans `dip_bounce.py`, voir son docstring).
   L'anti-doublon est ici, comme pour `dip_bounce`, entierement delegue a
   `RiskManager.max_concurrent_positions` (positions REELLEMENT ouvertes,
   jamais desynchronise)."""

from collections import deque

from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class MeanDipStrategy(Strategy):
    def __init__(self, window: int = 12, num_std: float = 2.0):
        if window < 2:
            raise ValueError("window doit etre >= 2")
        if num_std <= 0:
            raise ValueError("num_std doit etre strictement positif")
        self.window = window
        self.num_std = num_std
        self._closes: deque[float] = deque(maxlen=window)

    def on_candle(self, candle: Candle) -> Signal | None:
        self._closes.append(candle.close)
        if len(self._closes) < self.window:
            return None

        closes = list(self._closes)
        middle = sum(closes) / len(closes)
        variance = sum((c - middle) ** 2 for c in closes) / len(closes)
        lower = middle - self.num_std * variance**0.5

        if candle.close <= lower:
            return Signal(side=Side.BUY, reason="mean_dip_oversold")
        return None
