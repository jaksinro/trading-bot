"""Strategie "detecteur de pente" (2026-09-16, proposee par l'utilisateur) -
mesure la PENTE entre 2 bougies consecutives (variation de cloture en %),
sur une granularite tres fine (1 minute), et achete des qu'une chute brutale
est detectee (pente negative au-dela d'un seuil) - parie qu'une chute
soudaine et prononcee a plus de chances de rebondir qu'une derive lente.

`candles_window` (2026-09-16, suite a l'observation du graphique reel d'une
journee) : le nombre de bougies sur lesquelles la pente est mesuree - 2 par
defaut (comparaison a la bougie precedente immediate, comportement d'origine),
reglable pour comparer sur une fenetre plus large (ex: 5 bougies) et lisser le
bruit d'une seule minute. Voir STC pour la comparaison empirique 2 vs 5.

`one_buy_per_slope` (2026-09-16, suite a un autre constat reel de
l'utilisateur : "sa foire pendant les longues pentes") : sur une DERIVE
BAISSIERE CONTINUE (pas une seule chute isolee), la condition de pente reste
vraie a chaque bougie tant que le prix continue de descendre - sans garde-fou,
la strategie rachete a CHAQUE bougie qualifiante, empilant des positions
perdantes sur la meme tendance au lieu d'une seule. Active (`True`), la
strategie n'emet plus qu'UN SEUL signal par "episode" de pente : une fois
declenchee, elle se desarme et n'emettra plus de signal tant que la condition
de pente reste vraie bougie apres bougie - elle se rearme des qu'une bougie NE
declenche PAS la condition (le prix a cesse de descendre au rythme du seuil,
meme brievement), prete pour le prochain episode. Desactive par defaut
(`False`, comportement d'origine) - voir STC pour la comparaison empirique.

Different de `mean_dip`/`dip_bounce` sur le signal d'entree (vitesse du
mouvement sur N bougies, pas un ecart a une moyenne ni une proximite a un
plus bas glissant), mais MEME philosophie de sortie que les 2 autres :
- AUCUN signal de vente emis par la strategie elle-meme - "on garde l'ordre"
  (demande explicite de l'utilisateur), seul le trailing stop (et un
  stop-loss optionnel, en filet de securite) ferment une position.
- AUCUN etat interne "en position" - meme raisonnement deja documente dans
  `dip_bounce.py`/`mean_dip.py` : un flag interne ne serait jamais informe
  d'une sortie EXTERNE (trailing/stop-loss), restant bloque pour toujours.
  L'anti-doublon est delegue entierement a `RiskManager.max_concurrent_positions`.
  Le "desarmement" de `one_buy_per_slope` ne fait PAS exception a cette regle :
  il ne suit pas l'etat d'une position, seulement la condition de PRIX (la
  pente elle-meme), qui se met a jour independamment a chaque bougie - il ne
  peut donc pas rester bloque suite a une sortie externe non vue.
"""

from collections import deque

from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class SlopeDipStrategy(Strategy):
    def __init__(
        self, slope_threshold_pct: float = 0.005, candles_window: int = 2,
        one_buy_per_slope: bool = False,
    ):
        if slope_threshold_pct <= 0:
            raise ValueError("slope_threshold_pct doit etre strictement positif")
        if candles_window < 2:
            raise ValueError("candles_window doit etre au moins 2 (comparaison a une bougie precedente)")
        self.slope_threshold_pct = slope_threshold_pct
        self.candles_window = candles_window
        self.one_buy_per_slope = bool(one_buy_per_slope)
        self._prior_closes: deque[float] = deque(maxlen=candles_window - 1)
        self._armed = True

    def on_candle(self, candle: Candle) -> Signal | None:
        reference = self._prior_closes[0] if len(self._prior_closes) == self._prior_closes.maxlen else None
        self._prior_closes.append(candle.close)
        if reference is None:
            return None

        slope_pct = (candle.close - reference) / reference
        triggered = slope_pct <= -self.slope_threshold_pct

        if not self.one_buy_per_slope:
            return Signal(side=Side.BUY, reason="slope_dip_sharp_drop") if triggered else None

        if not triggered:
            self._armed = True
            return None
        if not self._armed:
            return None
        self._armed = False
        return Signal(side=Side.BUY, reason="slope_dip_sharp_drop")
