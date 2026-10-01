"""Strategie "vote de momentum" (EF-98), retenue pour l'ETH par la recherche
de `scripts/research_eth.py` (demande de l'utilisateur du 2026-10-01 : "met
en place un algo rentable sur l'ETH").

Principe (momentum de serie temporelle, famille documentee en finance) : a
chaque cloture JOURNALIERE, on regarde si le cours est plus haut qu'il y a
N jours, pour plusieurs horizons (par defaut 7, 14, 30, 60 et 90 jours).
Chaque horizon "vote" ; si la majorite des horizons est en hausse, on detient
l'ETH, sinon on reste en liquidites. Plusieurs horizons plutot qu'un seul :
la decision ne depend pas d'une duree choisie au hasard.

Pourquoi ce reglage : famille la plus robuste sur 2025 (10 reglages testes,
10 positifs) ; reglage MEDIAN de la famille, pas le meilleur ; choix fige
avant de regarder 2026, puis 2026 teste une seule fois : +16,8 % apres frais,
baisse max -25,9 % (ETH garde : -8,7 %, baisse max -55 %). Voir STC §3.85.

Signal emis a chaque bougie (achat tant que la majorite est haussiere, vente
sinon), comme `TrendRegimeStrategy` : le moteur ignore un achat deja en
position ou une vente a plat.
"""
from __future__ import annotations

from collections import deque

from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class MomentumVoteStrategy(Strategy):
    def __init__(self, lookbacks=(7, 14, 30, 60, 90), threshold: float = 0.5):
        lookbacks = tuple(int(n) for n in lookbacks)
        if not lookbacks or min(lookbacks) < 1:
            raise ValueError("lookbacks doit contenir des horizons >= 1 bougie")
        if not 0 <= threshold < 1:
            raise ValueError("threshold doit etre dans [0, 1[")
        self.lookbacks, self.threshold = lookbacks, threshold
        self._closes: deque[float] = deque(maxlen=max(lookbacks) + 1)
        self.last_vote: float | None = None

    def on_candle(self, candle: Candle) -> Signal | None:
        self._closes.append(candle.close)
        if len(self._closes) <= max(self.lookbacks):
            return None   # rechauffage : il faut l'horizon le plus long
        now = self._closes[-1]
        self.last_vote = sum(now > self._closes[-1 - n] for n in self.lookbacks) / len(self.lookbacks)
        if self.last_vote > self.threshold:
            return Signal(side=Side.BUY, reason=f"momentum_vote_{self.last_vote:.0%}_haussier")
        return Signal(side=Side.SELL, reason=f"momentum_vote_{self.last_vote:.0%}_haussier")

    def chart_levels(self) -> list[dict]:
        """Prix de reference de chaque horizon : au-dessus, l'horizon vote pour la
        hausse. Le bot detient l'ETH si le cours est au-dessus de la majorite."""
        if len(self._closes) <= max(self.lookbacks):
            return []
        return [{"price": self._closes[-1 - n], "label": f"il y a {n} j", "kind": "level"} for n in self.lookbacks]
