"""Strategie Volume Profile (EF-96, refaite en EF-97 d'apres le document de
l'utilisateur "Volume Profile : quand entrer, en images", 2026-10-01).

L'indicateur (definitions TradingView) : sur une plage de temps, le volume
echange a chaque niveau de prix. POC = niveau le plus charge ; zone de valeur
= les niveaux autour du POC qui totalisent 70 % du volume, bornes VAH (haut)
et VAL (bas). Ici la plage est la SEANCE PRECEDENTE (jour UTC par defaut,
`session_hours`) : son profil sert de reference toute la seance suivante,
comme dans les exemples du document (BTC en 15 minutes, profil de la veille).
Approximation assumee : le volume d'une bougie est reparti uniformement entre
son plus bas et son plus haut (TradingView utilise des bougies plus fines).

Regle generale du document : on n'entre qu'a la CLOTURE de la bougie qui
valide la derniere condition, jamais avant ; stop et objectif a 2 fois le
risque (2R) sont propres au trade (`Signal.stop_price/target_price`, surveilles
par le moteur). Achat seulement : le bot trade au comptant, sans vente a
decouvert - les schemas "vente" du document ne sont pas transposables.

Trois setups (`setups`), evalues a chaque cloture :
1. `poc_rebound` - la veille a fini AU-DESSUS du VAH. Le prix redescend au POC
   et le rejette : meche sous le POC avec cloture au-dessus, puis bougie verte
   qui confirme (cloture au-dessus de celle de la meche) dans les
   `max_signal_age` bougies ; ou avalement haussier forme SUR le POC. Stop
   juste sous la meche (plus bas du pattern).
2. `value_area_reentry` - la veille a fini DANS la zone de valeur. Une bougie
   clot sous le VAL, puis une bougie verte CLOT de nouveau dans la zone :
   entree. Stop sous le plus bas atteint dehors. Peut se reproduire dans la
   seance. Une simple meche dans la zone (cloture dehors) ne compte pas.
3. `breakout` - n'importe quel jour. Cloture au-dessus du VAH (sortie nette),
   impulsion jusqu'a un plus haut, repli qui tient, puis cloture au-dessus de
   cet ancien plus haut : entree. Stop juste sous le niveau casse. Setup
   annule si le repli clot "loin dans la zone" (plus de `pullback_max_depth`
   de sa largeur sous le VAH).
"""
from __future__ import annotations

from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal

HOUR_MS = 3_600_000
# L'epoque Unix tombe un jeudi : decalage de 4 jours pour des semaines du lundi
# (seances de 168 h). Sans effet pour des seances d'un jour.
WEEK_OFFSET_MS = 4 * 24 * HOUR_MS
SETUPS = ("poc_rebound", "value_area_reentry", "breakout")


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
    def __init__(self, setups=SETUPS, session_hours: int = 24, rows: int = 50, value_area_pct: float = 0.70,
                 reward_risk: float = 2.0, max_signal_age: int = 3, pullback_max_depth: float = 0.25,
                 stop_buffer_pct: float = 0.0005, min_risk_pct: float = 0.0):
        setups = tuple(setups)
        unknown = [s for s in setups if s not in SETUPS]
        if not setups or unknown:
            raise ValueError(f"setups inconnus ou vides : {unknown} (attendus : {', '.join(SETUPS)})")
        if (session_hours < 1 or rows < 5 or not 0 < value_area_pct < 1 or reward_risk <= 0
                or max_signal_age < 1 or pullback_max_depth < 0 or stop_buffer_pct < 0 or min_risk_pct < 0):
            raise ValueError("parametres hors bornes")
        self.setups, self.session_hours, self.rows, self.value_area_pct = setups, session_hours, rows, value_area_pct
        self.reward_risk, self.max_signal_age = reward_risk, max_signal_age
        self.pullback_max_depth, self.stop_buffer_pct, self.min_risk_pct = pullback_max_depth, stop_buffer_pct, min_risk_pct
        self._period_ms = session_hours * HOUR_MS
        self._offset_ms = WEEK_OFFSET_MS if session_hours % 168 == 0 else 0
        self._session: list[Candle] = []
        self._session_id: int | None = None
        self.profile: tuple[float, float, float] | None = None   # (POC, VAH, VAL) de la seance precedente
        self.previous_close: float | None = None                 # cloture de la seance precedente
        self._prev: Candle | None = None
        self._in_position = False
        self._reset_session_state()

    def _reset_session_state(self) -> None:
        self._wick: dict | None = None        # setup 1 : meche de rejet en attente de confirmation
        self._outside_low: float | None = None  # setup 2 : plus bas depuis la cloture sous le VAL
        self._bo_phase = 0                    # setup 3 : 0 attente, 1 impulsion, 2 repli
        self._bo_high = 0.0

    # ------------------------------------------------------------------ seances
    def _roll_session(self, candle: Candle) -> None:
        session = (candle.timestamp - self._offset_ms) // self._period_ms
        if self._session_id is not None and session != self._session_id and self._session:
            self.profile = volume_profile(self._session, self.rows, self.value_area_pct)
            self.previous_close = self._session[-1].close
            self._session = []
            self._reset_session_state()
        self._session_id = session
        self._session.append(candle)

    def sync_position(self, entry_price: float | None) -> None:
        """Etat reel transmis par le moteur : pas de nouvelle entree en position.
        Les sorties sont le stop et l'objectif du trade, surveilles par le moteur."""
        self._in_position = entry_price is not None

    # ------------------------------------------------------------------ signaux
    def on_candle(self, candle: Candle) -> Signal | None:
        self._roll_session(candle)
        signal = None
        if self.profile is not None:
            poc, vah, val = self.profile
            # Chaque setup met a jour son etat a chaque bougie ; le premier valide l'emporte.
            found = [self._poc_rebound(candle, poc, vah) if "poc_rebound" in self.setups else None,
                     self._reentry(candle, vah, val) if "value_area_reentry" in self.setups else None,
                     self._breakout(candle, vah, val) if "breakout" in self.setups else None]
            found = [f for f in found if f is not None]
            if found and not self._in_position:
                signal = self._signal(candle, *found[0])
        self._prev = candle
        return signal

    def _poc_rebound(self, c: Candle, poc: float, vah: float):
        if self.previous_close is None or self.previous_close <= vah:
            self._wick = None
            return None
        prev = self._prev
        # Avalement haussier forme SUR le POC : corps vert qui recouvre tout le corps rouge d'avant.
        if (prev is not None and prev.close < prev.open and c.close > c.open
                and c.open <= prev.close and c.close >= prev.open
                and min(prev.low, c.low) <= poc <= max(prev.high, c.high) and c.close > poc):
            self._wick = None
            return ("poc_rebound_engulfing", min(prev.low, c.low))
        if self._wick is not None:
            self._wick["age"] += 1
            if c.close < poc or self._wick["age"] > self.max_signal_age:
                self._wick = None            # rejet rate, ou signal trop vieux : on ne court pas apres
            elif c.close > c.open and c.close > self._wick["close"]:
                low = min(self._wick["low"], c.low)
                self._wick = None
                return ("poc_rebound_wick", low)
        # Meche de rejet haussiere : meche sous le POC, cloture au-dessus.
        if c.low < poc < c.close and min(c.open, c.close) > poc:
            self._wick = {"low": c.low, "close": c.close, "age": 0}
        return None

    def _reentry(self, c: Candle, vah: float, val: float):
        if self.previous_close is None or not val <= self.previous_close <= vah:
            self._outside_low = None
            return None
        if c.close < val:
            self._outside_low = c.low if self._outside_low is None else min(self._outside_low, c.low)
            return None
        if self._outside_low is not None:
            low = min(self._outside_low, c.low)
            if c.close > c.open and c.close <= vah:
                self._outside_low = None
                return ("value_area_reentry", low)
            self._outside_low = low
        return None

    def _breakout(self, c: Candle, vah: float, val: float):
        floor = vah - self.pullback_max_depth * (vah - val)
        if self._bo_phase == 0:
            if c.close > vah:
                self._bo_phase, self._bo_high = 1, c.high
            return None
        if c.close < floor:                      # repli trop profond : la cassure a echoue
            self._bo_phase = 0
            return None
        if self._bo_phase == 1:
            if c.high > self._bo_high:
                self._bo_high = c.high           # l'impulsion continue
            else:
                self._bo_phase = 2               # premiere bougie sans nouveau plus haut : le repli
            return None
        if c.close > self._bo_high:              # cloture au-dessus de l'ancien plus haut
            level = self._bo_high
            self._bo_phase = 0
            return ("breakout", level)
        return None

    def _signal(self, c: Candle, reason: str, stop_level: float) -> Signal | None:
        entry = c.close
        stop = stop_level * (1 - self.stop_buffer_pct)
        if self.min_risk_pct and (entry - stop) / entry < self.min_risk_pct:
            stop = entry * (1 - self.min_risk_pct)
        risk = entry - stop
        if risk <= 0:
            return None
        return Signal(side=Side.BUY, reason=f"volume_profile_{reason}" if not reason.startswith("volume") else reason,
                      stop_price=stop, target_price=entry + self.reward_risk * risk)

    # ------------------------------------------------------------------ graphique
    def chart_levels(self) -> list[dict]:
        """POC / VAH / VAL de la seance precedente (graphique du bot, EF-88).
        Le stop et l'objectif de chaque trade s'affichent avec la position."""
        if self.profile is None:
            return []
        poc, vah, val = self.profile
        return [
            {"price": poc, "label": "POC veille (volume max)", "kind": "trend"},
            {"price": vah, "label": "VAH veille (haut zone de valeur)", "kind": "level"},
            {"price": val, "label": "VAL veille (bas zone de valeur)", "kind": "level"},
        ]
