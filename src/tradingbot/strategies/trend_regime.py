"""Strategie de regime de tendance (EF-68) - demande de l'utilisateur :
"un modele qui permettrait de faire de l'argent sur l'ETH, rentable en
haussier, et si possible aussi en baissier".

CONTRAINTE STRUCTURELLE A ASSUMER : ce projet est long-only (le spot Binance
ne permet pas de vendre a decouvert, et `Portfolio` ne modelise pas de
position courte). Gagner de l'argent PENDANT une baisse est donc hors de
portee - la seule protection possible est de ne pas etre investi. L'objectif
realiste, et ce que cette strategie vise, est donc : **capter la hausse,
rester en liquidites pendant la baisse** plutot que de la subir.

C'est exactement ce que `TrendFilter` (analysis/trend_filter.py) ne sait PAS
faire : il bloque les nouveaux achats sous l'EMA, mais ne ferme jamais une
position deja ouverte - on traverse donc tout le marche baissier en
portefeuille. D'ou une strategie qui emet elle-meme un signal de VENTE
quand le regime se retourne.

HYSTERESIS (`entry_buffer_pct`/`exit_buffer_pct`) : la faiblesse connue d'un
franchissement de moyenne unique est le va-et-vient (whipsaw) quand le prix
oscille autour de la ligne - chaque aller-retour coute des frais. On entre
donc au-DESSUS de l'EMA d'une marge, et on ne sort qu'en-DESSOUS d'une autre
marge : entre les deux, on ne fait rien.

Comme `dip_bounce`, aucun etat interne "en position" n'est suivi : la
strategie peut reemettre BUY ou SELL a chaque bougie, c'est au `RiskManager`
(`max_concurrent_positions`, et "rien a vendre si aucune position") de
filtrer - jamais desynchronise, contrairement a un drapeau propre.
"""

from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class TrendRegimeStrategy(Strategy):
    def __init__(
        self,
        ema_period: int = 500,
        entry_buffer_pct: float = 0.0,
        exit_buffer_pct: float = 0.0,
        warmup_candles: int | None = None,
    ):
        """`ema_period` est un nombre de BOUGIES, agnostique du timeframe
        (500 bougies 1h ~ 21 jours), meme convention que `trend_ma_period`
        de `dip_bounce`.

        `warmup_candles` : nombre de bougies avant d'autoriser le moindre
        signal. Par defaut `ema_period`, pour ne pas decider sur une EMA
        encore dominee par sa valeur d'initialisation - une EMA amorcee sur
        la premiere cloture met plusieurs periodes a devenir significative.
        """
        if ema_period < 2:
            raise ValueError("ema_period doit etre >= 2")
        if entry_buffer_pct < 0 or exit_buffer_pct < 0:
            raise ValueError("les marges d'hysteresis ne peuvent pas etre negatives")
        self.ema_period = ema_period
        self.entry_buffer_pct = entry_buffer_pct
        self.exit_buffer_pct = exit_buffer_pct
        self.warmup_candles = ema_period if warmup_candles is None else warmup_candles
        self._alpha = 2.0 / (ema_period + 1)
        self._ema: float | None = None
        self._seen = 0

    @property
    def ema(self) -> float | None:
        return self._ema

    def chart_levels(self) -> list[dict]:
        """Niveaux a tracer sur le graphique du bot (EF-88) : la tendance de
        fond, le seuil au-dessus duquel la strategie achete, et celui sous
        lequel elle vend. Vide tant que l'EMA n'existe pas."""
        if self._ema is None:
            return []
        levels = [{"price": self._ema, "label": f"tendance (EMA{self.ema_period})", "kind": "trend"}]
        entry = self._ema * (1 + self.entry_buffer_pct)
        exit_ = self._ema * (1 - self.exit_buffer_pct)
        levels.append({"price": entry, "label": f"achat au-dessus (+{self.entry_buffer_pct:.0%})", "kind": "entry"})
        if abs(exit_ - self._ema) > 1e-12:
            levels.append({"price": exit_, "label": f"sortie en dessous (-{self.exit_buffer_pct:.0%})", "kind": "exit"})
        else:
            levels[0]["label"] += " - sortie en dessous"
        return levels

    def on_candle(self, candle: Candle) -> Signal | None:
        self._ema = (
            candle.close if self._ema is None
            else self._ema + self._alpha * (candle.close - self._ema)
        )
        self._seen += 1
        if self._seen < self.warmup_candles or self._ema <= 0:
            return None

        if candle.close >= self._ema * (1 + self.entry_buffer_pct):
            return Signal(side=Side.BUY, reason="trend_regime_bullish")
        if candle.close <= self._ema * (1 - self.exit_buffer_pct):
            return Signal(side=Side.SELL, reason="trend_regime_bearish")
        return None
