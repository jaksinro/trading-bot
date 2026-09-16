"""TrendFilter (feuille de route performance, etape 1) - filtre optionnel
qui bloque un achat quand le prix est sous une moyenne mobile exponentielle
longue periode (regime baissier), pour eviter de trader a contre-courant
d'une tendance de fond :
- `sma_cross` peut whipsaw (achats/ventes repetes sans gain) en marche plat,
- `scalp_dip` peut acheter des creux pendant une chute continue.

Composant optionnel et independant du RiskManager, sur le meme principe que
ProbabilityGate : il ne remplace aucune regle de risque existante, il ajoute
un filtre supplementaire avant l'achat. Desactive par defaut.
"""


class TrendFilter:
    def __init__(self, ema_period: int = 200):
        if ema_period < 1:
            raise ValueError("ema_period doit etre >= 1")
        self.ema_period = ema_period
        self._alpha = 2.0 / (ema_period + 1)
        self._ema: float | None = None

    @property
    def ema(self) -> float | None:
        return self._ema

    def update(self, price: float) -> None:
        """A appeler a CHAQUE bougie (achat, vente ou aucun signal) pour que
        l'EMA reste a jour independamment des decisions de la strategie."""
        self._ema = price if self._ema is None else self._ema + self._alpha * (price - self._ema)

    def is_bullish(self, current_price: float) -> bool:
        """Vrai si le prix est au-dessus de l'EMA (regime haussier). Avant
        d'avoir recu la moindre bougie, l'EMA n'existe pas encore : on
        n'autorise/bloque rien par defaut (fail-open), pour ne pas bloquer
        tous les achats au tout premier demarrage d'une instance."""
        if self._ema is None:
            return True
        return current_price >= self._ema
