"""Strategie passive "buy & hold" - etape 9 de la feuille de route
performance. Achete UNE SEULE FOIS (a la premiere bougie recue) puis ne
revend jamais - operationnalise en bot deployable le meme benchmark deja
utilise toute la soiree pour juger les autres strategies
(reporting/stats.py::compute_buy_and_hold_return_pct), suite a la question
de l'utilisateur sur le trading passif comme alternative au trading actif.

Aucun parametre : contrairement aux autres strategies, il n'y a rien a
optimiser (pas de fenetre, pas de seuil) - non integree a la grille de
`optimize.py` pour cette raison, uniquement au chemin de deploiement
(`run_backtest.py`/`run_paper.py`/`control_server.py`)."""

from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class BuyAndHoldStrategy(Strategy):
    def __init__(self):
        self._bought = False

    def align_position(self, entry_price: float | None) -> None:
        """Position reelle transmise par le moteur avant sa premiere decision
        (EF-102) : le rechauffage consommait l'unique achat (signal ignore) et
        le bot ne detenait jamais rien. Bot a plat : on achete ; position
        restauree au redemarrage : on n'achete pas une 2e fois."""
        self._bought = entry_price is not None

    def on_candle(self, candle: Candle) -> Signal | None:
        if self._bought:
            return None
        self._bought = True
        return Signal(side=Side.BUY, reason="buy_and_hold_entry")
