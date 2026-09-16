"""PriceLevelSizer (idee proposee par l'utilisateur) - ajuste la taille d'une
position selon le prix ACTUEL par rapport a la moyenne du mois calendaire en
cours : plus le prix est bas par rapport a cette moyenne, plus la position
est grande (on "charge" plus sur un creux relatif du mois) ; plus il est
haut, plus elle est petite.

Composant optionnel et independant du RiskManager, sur le meme principe que
TrendFilter/AtrSizer : il ne remplace aucune regle de risque existante, il
ajuste juste la taille avant l'achat. Contrairement a AtrSizer (qui ne fait
que REDUIRE la taille, jamais l'augmenter), celui-ci peut aussi bien
l'augmenter (prix bas) que la reduire (prix haut) - les deux bornes
(`min_size_multiplier`/`max_size_multiplier`) sont donc configurables.

La moyenne se reinitialise au 1er de chaque mois calendaire (heure du
timestamp de la bougie, en UTC comme le reste du projet) - decision assumee
de l'utilisateur : en debut de mois, la moyenne est basee sur peu de
donnees et donc plus bruitee, jusqu'a se stabiliser au fil du mois.
"""

from datetime import datetime, timezone

from tradingbot.types import Candle


class PriceLevelSizer:
    def __init__(self, min_size_multiplier: float = 0.5, max_size_multiplier: float = 1.5):
        if min_size_multiplier <= 0:
            raise ValueError("min_size_multiplier doit etre strictement positif")
        if max_size_multiplier < min_size_multiplier:
            raise ValueError("max_size_multiplier doit etre >= min_size_multiplier")
        self.min_size_multiplier = min_size_multiplier
        self.max_size_multiplier = max_size_multiplier

        self._current_month_key: tuple[int, int] | None = None
        self._month_sum = 0.0
        self._month_count = 0

    @staticmethod
    def _month_key(timestamp_ms: int) -> tuple[int, int]:
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        return dt.year, dt.month

    @property
    def month_average(self) -> float | None:
        return (self._month_sum / self._month_count) if self._month_count else None

    def update(self, candle: Candle) -> None:
        """A appeler a CHAQUE bougie pour que la moyenne du mois reste a
        jour independamment des decisions de la strategie."""
        key = self._month_key(candle.timestamp)
        if key != self._current_month_key:
            self._current_month_key = key
            self._month_sum = 0.0
            self._month_count = 0
        self._month_sum += candle.close
        self._month_count += 1

    def size_multiplier(self, current_price: float) -> float:
        """Retourne un facteur a appliquer a la taille de position normale :
        > 1 si le prix actuel est SOUS la moyenne du mois (on met plus),
        < 1 s'il est AU-DESSUS (on met moins), 1.0 tant que la moyenne n'est
        pas encore formee (fail-open, comme AtrSizer/TrendFilter) ou si le
        prix est nul/invalide."""
        avg = self.month_average
        if avg is None or current_price <= 0:
            return 1.0
        raw = avg / current_price
        return max(self.min_size_multiplier, min(self.max_size_multiplier, raw))
