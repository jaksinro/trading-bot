"""Interface Strategy (STC section 3.3).

Une strategie est une fonction pure : pas d'acces reseau ni a l'execution,
ce qui la rend testable unitairement (ENF-07 de la STB).
"""

from abc import ABC, abstractmethod

from tradingbot.types import Candle, Signal


class Strategy(ABC):
    @abstractmethod
    def on_candle(self, candle: Candle) -> Signal | None:
        """Appele a chaque nouvelle bougie. Retourne un signal ou None."""
        raise NotImplementedError
