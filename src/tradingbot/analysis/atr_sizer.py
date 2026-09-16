"""AtrSizer (feuille de route performance, etape 2) - reduit la taille d'une
position quand la volatilite recente (ATR - Average True Range) est elevee
par rapport a son niveau habituel, pour prendre le meme risque EN VALEUR
plutot que la meme taille FIXE en marche calme et en marche agite.

Composant optionnel et independant du RiskManager, sur le meme principe que
TrendFilter/ProbabilityGate : il ne remplace aucune regle de risque
existante, il ajuste juste la taille avant l'achat. Ne fait JAMAIS
augmenter la taille au-dela du plafond configure (`max_position_size_pct`)
- seulement la reduire en periode agitee, jamais l'inverse.
"""

from tradingbot.types import Candle


class AtrSizer:
    def __init__(self, atr_period: int = 14, baseline_period: int = 100, min_size_multiplier: float = 0.2):
        if atr_period < 1:
            raise ValueError("atr_period doit etre >= 1")
        if baseline_period < 1:
            raise ValueError("baseline_period doit etre >= 1")
        if not (0.0 < min_size_multiplier <= 1.0):
            raise ValueError("min_size_multiplier doit etre compris entre 0 (exclu) et 1")

        self.atr_period = atr_period
        self.baseline_period = baseline_period
        self.min_size_multiplier = min_size_multiplier
        self._atr_alpha = 2.0 / (atr_period + 1)
        self._baseline_alpha = 2.0 / (baseline_period + 1)

        self._atr: float | None = None       # volatilite CourANTE (reactive)
        self._baseline: float | None = None  # niveau de volatilite "normal" (lisse sur baseline_period)
        self._prev_close: float | None = None

    @property
    def atr(self) -> float | None:
        return self._atr

    @property
    def baseline(self) -> float | None:
        return self._baseline

    def _true_range(self, candle: Candle) -> float:
        if self._prev_close is None:
            return candle.high - candle.low
        return max(
            candle.high - candle.low,
            abs(candle.high - self._prev_close),
            abs(candle.low - self._prev_close),
        )

    def update(self, candle: Candle) -> None:
        """A appeler a CHAQUE bougie pour que l'ATR et sa base line restent
        a jour independamment des decisions de la strategie."""
        true_range = self._true_range(candle)
        self._atr = true_range if self._atr is None else self._atr + self._atr_alpha * (true_range - self._atr)
        self._baseline = self._atr if self._baseline is None else self._baseline + self._baseline_alpha * (self._atr - self._baseline)
        self._prev_close = candle.close

    def size_multiplier(self) -> float:
        """Retourne un facteur dans ]0, 1] a appliquer a la taille de
        position normale. 1.0 tant que l'ATR n'est pas encore forme (fail-open,
        comme TrendFilter) ou quand la volatilite courante est sous son
        niveau habituel - ne fait jamais grossir la position au-dela du
        plafond configure, seulement la reduire quand l'ATR courant depasse
        sa baseline, jamais en dessous de `min_size_multiplier`."""
        if self._atr is None or self._baseline is None or self._atr <= 0 or self._baseline <= 0:
            return 1.0
        raw = self._baseline / self._atr
        return max(self.min_size_multiplier, min(1.0, raw))
