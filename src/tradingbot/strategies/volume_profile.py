"""Strategie "Fixed Range Volume Profile" (EF-96), demande de l'utilisateur du
2026-10-01 : reprendre l'indicateur de TradingView et en faire un bot.

L'indicateur : sur une plage de temps choisie, l'histogramme du volume echange
a chaque niveau de prix. Trois niveaux en sortent (definitions de TradingView) :
- POC (Point of Control) : le niveau ou il s'est echange le plus de volume ;
- zone de valeur (Value Area) : les niveaux autour du POC qui totalisent 70 %
  du volume, bornes par VAH (haut) et VAL (bas). Construction : on part du
  POC et on ajoute a chaque pas le voisin (au-dessus ou en dessous) le plus
  charge, jusqu'a atteindre 70 % du volume.

Un bot ne peut pas tracer la plage a la souris : la "plage fixe" est ici la
PERIODE PRECEDENTE TERMINEE (jour ou semaine UTC, `range_hours` = 24 ou 168),
dont le profil sert de reference pendant toute la periode suivante - l'usage
le plus courant de l'indicateur (profil de la veille / de la semaine
precedente). Variante `anchor="rolling"` : les `range_hours` dernieres heures,
recalcule a chaque bougie.

Approximation assumee : le volume de chaque bougie est reparti uniformement
entre son plus bas et son plus haut (TradingView s'appuie sur des bougies plus
fines). Une bougie 1h d'ETH couvre ~0,8 % de prix : sur une semaine, l'erreur
reste petite devant la largeur de la zone de valeur.

Deux usages classiques, achat seulement (marche au comptant, pas de vente a
decouvert) :
- `mode="reversion"` ("regle des 80 %") : le cours passe SOUS le VAL, puis
  revient dans la zone de valeur et y clot `confirm_candles` bougies de suite
  -> achat ; objectif le VAH (`target="vah"`) ou le POC ; invalidation si une
  cloture repasse sous VAL x (1 - `stop_buffer_pct`).
- `mode="breakout"` : `confirm_candles` clotures de suite au-dessus du VAH ->
  achat (le marche "accepte" des prix plus hauts) ; sortie si une cloture
  revient sous VAH x (1 - `stop_buffer_pct`), c'est-a-dire dans l'ancienne zone.
  A chaque nouvelle plage, ce seuil REMONTE au VAL du nouveau profil s'il est
  plus haut (jamais ne redescend) : sans cela, la seule sortie etait sous le
  prix d'achat et tout trade clos etait perdant par construction (constate au
  premier banc, 0 % de trades gagnants).
En mode retour, l'objectif et l'invalidation sont FIGES a l'achat : un
nouveau profil en cours de position ne les deplace pas.

La strategie suit son etat "en position" a partir des signaux qu'elle emet,
et le moteur le resynchronise avant chaque bougie (`sync_position`) : apres le
rechauffage, une reprise de session avec position ouverte, un achat refuse
(cash) ou une vente par le stop-loss du moteur.
"""
from __future__ import annotations

from collections import deque

from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal

HOUR_MS = 3_600_000
# L'epoque Unix tombe un jeudi : sans ce decalage, une "semaine" irait du jeudi
# au mercredi. Decalage de 4 jours -> semaines du lundi 00:00 UTC au dimanche.
WEEK_OFFSET_MS = 4 * 24 * HOUR_MS
MODES = ("reversion", "breakout")
ANCHORS = ("period", "rolling")
TARGETS = ("vah", "poc")


def volume_profile(candles, rows: int = 50, value_area_pct: float = 0.70) -> tuple[float, float, float] | None:
    """(POC, VAH, VAL) des bougies donnees, ou None si le profil est vide."""
    candles = [c for c in candles if c.volume > 0]
    if not candles:
        return None
    lo = min(c.low for c in candles)
    hi = max(c.high for c in candles)
    if hi <= lo:
        return (lo, lo, lo)
    step = (hi - lo) / rows
    bins = [0.0] * rows
    for c in candles:
        if c.high <= c.low:
            bins[min(int((c.close - lo) / step), rows - 1)] += c.volume
            continue
        first = min(int((c.low - lo) / step), rows - 1)
        last = min(int((c.high - lo) / step), rows - 1)
        span = c.high - c.low
        for i in range(first, last + 1):
            overlap = min(c.high, lo + (i + 1) * step) - max(c.low, lo + i * step)
            if overlap > 0:
                bins[i] += c.volume * overlap / span
    poc_i = max(range(rows), key=lambda i: bins[i])
    target = sum(bins) * value_area_pct
    low_i = high_i = poc_i
    total = bins[poc_i]
    while total < target and (low_i > 0 or high_i < rows - 1):
        below = bins[low_i - 1] if low_i > 0 else -1.0
        above = bins[high_i + 1] if high_i < rows - 1 else -1.0
        if above >= below:
            high_i += 1
            total += above
        else:
            low_i -= 1
            total += below
    poc = lo + (poc_i + 0.5) * step
    return poc, lo + (high_i + 1) * step, lo + low_i * step


class VolumeProfileStrategy(Strategy):
    def __init__(self, mode: str = "reversion", anchor: str = "period", range_hours: int = 168,
                 rows: int = 50, value_area_pct: float = 0.70, confirm_candles: int = 2,
                 target: str = "vah", stop_buffer_pct: float = 0.01):
        if mode not in MODES:
            raise ValueError(f"mode inconnu : {mode!r} (attendu : {', '.join(MODES)})")
        if anchor not in ANCHORS:
            raise ValueError(f"ancrage inconnu : {anchor!r} (attendu : {', '.join(ANCHORS)})")
        if target not in TARGETS:
            raise ValueError(f"objectif inconnu : {target!r} (attendu : {', '.join(TARGETS)})")
        if range_hours < 1 or rows < 5 or not 0 < value_area_pct < 1 or confirm_candles < 1 or stop_buffer_pct < 0:
            raise ValueError("parametres hors bornes (range_hours >= 1, rows >= 5, 0 < value_area_pct < 1, "
                             "confirm_candles >= 1, stop_buffer_pct >= 0)")
        self.mode, self.anchor, self.range_hours = mode, anchor, range_hours
        self.rows, self.value_area_pct = rows, value_area_pct
        self.confirm_candles, self.target, self.stop_buffer_pct = confirm_candles, target, stop_buffer_pct
        self._period_ms = range_hours * HOUR_MS
        self._offset_ms = WEEK_OFFSET_MS if range_hours % 168 == 0 else 0
        self._current: list[Candle] = []
        self._current_period: int | None = None
        self._window: deque[Candle] = deque()
        self.profile: tuple[float, float, float] | None = None   # (POC, VAH, VAL) de reference
        self._was_below = False
        self._streak = 0
        self._in_position = False
        self._exit_target: float | None = None
        self._exit_stop: float | None = None

    # ------------------------------------------------------------------ profil
    def _update_profile(self, candle: Candle) -> bool:
        """Met a jour le profil de reference ; True s'il vient de changer de plage."""
        if self.anchor == "rolling":
            self._window.append(candle)
            while self._window and self._window[0].timestamp <= candle.timestamp - self._period_ms:
                self._window.popleft()
            # Profil des heures PRECEDENTES : la bougie courante est jugee contre lui.
            self.profile = volume_profile(list(self._window)[:-1], self.rows, self.value_area_pct)
            return False
        period = (candle.timestamp - self._offset_ms) // self._period_ms
        changed = False
        if self._current_period is not None and period != self._current_period:
            self.profile = volume_profile(self._current, self.rows, self.value_area_pct)
            self._current = []
            changed = True
        self._current_period = period
        self._current.append(candle)
        return changed

    # ------------------------------------------------------------------ signaux
    def on_candle(self, candle: Candle) -> Signal | None:
        if self._update_profile(candle):
            self._was_below, self._streak = False, 0   # nouvelle reference : nouveau scenario
            if self._in_position and self.mode == "breakout" and self.profile is not None:
                self._exit_stop = max(self._exit_stop, self.profile[2] * (1 - self.stop_buffer_pct))
        if self.profile is None:
            return None
        poc, vah, val = self.profile
        close = candle.close

        if self._in_position:
            if self._exit_target is not None and close >= self._exit_target:
                return self._sell("volume_profile_target")
            if close < self._exit_stop:
                return self._sell("volume_profile_invalidation")
            return None

        if self.mode == "reversion":
            if close < val:
                self._was_below, self._streak = True, 0
            elif self._was_below and close <= vah:
                self._streak += 1
                if self._streak >= self.confirm_candles:
                    self._exit_target = vah if self.target == "vah" else poc
                    self._exit_stop = val * (1 - self.stop_buffer_pct)
                    return self._buy("volume_profile_value_area_reentry")
            else:
                self._was_below, self._streak = False, 0
            return None

        # breakout
        self._streak = self._streak + 1 if close > vah else 0
        if self._streak >= self.confirm_candles:
            self._exit_target = None   # pas d'objectif : la sortie est le retour dans la zone
            self._exit_stop = vah * (1 - self.stop_buffer_pct)
            return self._buy("volume_profile_breakout")
        return None

    def sync_position(self, entry_price: float | None) -> None:
        """Etat reel transmis par le moteur avant chaque bougie. A plat alors
        qu'on se croyait en position : on oublie la position. En position
        alors qu'on se croyait a plat (reprise apres redemarrage, signal emis
        pendant le rechauffage) : on adopte la position avec les niveaux du
        profil COURANT - les niveaux figes a l'achat d'origine sont perdus."""
        if entry_price is None:
            if self._in_position:
                self._in_position, self._exit_target, self._exit_stop = False, None, None
            return
        if self._in_position or self.profile is None:
            return
        poc, vah, val = self.profile
        self._in_position = True
        if self.mode == "reversion":
            self._exit_target = vah if self.target == "vah" else poc
            self._exit_stop = val * (1 - self.stop_buffer_pct)
        else:
            self._exit_target = None
            self._exit_stop = min(vah, entry_price) * (1 - self.stop_buffer_pct)

    def _buy(self, reason: str) -> Signal:
        self._in_position, self._was_below, self._streak = True, False, 0
        return Signal(side=Side.BUY, reason=reason)

    def _sell(self, reason: str) -> Signal:
        self._in_position, self._exit_target, self._exit_stop = False, None, None
        return Signal(side=Side.SELL, reason=reason)

    # ------------------------------------------------------------------ graphique
    def chart_levels(self) -> list[dict]:
        """POC / VAH / VAL de la plage de reference, et en position l'objectif
        et l'invalidation figes a l'achat (graphique du bot, EF-88)."""
        if self.profile is None:
            return []
        poc, vah, val = self.profile
        levels = [
            {"price": poc, "label": "POC (volume max)", "kind": "trend"},
            {"price": vah, "label": "VAH (haut zone de valeur)", "kind": "entry" if self.mode == "breakout" else "level"},
            {"price": val, "label": "VAL (bas zone de valeur)", "kind": "level"},
        ]
        if self._in_position:
            if self._exit_target is not None:
                levels.append({"price": self._exit_target, "label": "objectif", "kind": "entry"})
            levels.append({"price": self._exit_stop, "label": "invalidation", "kind": "exit"})
        return levels
