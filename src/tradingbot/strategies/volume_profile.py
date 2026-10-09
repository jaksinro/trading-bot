"""Strategie Volume Profile (EF-96, refaite en EF-97 d'apres le document de
l'utilisateur "Volume Profile : quand entrer, en images", 2026-10-01).

L'indicateur (definitions TradingView) : sur une plage de temps, le volume
echange a chaque niveau de prix. POC = niveau le plus charge ; zone de valeur
= les niveaux autour du POC qui totalisent 70 % du volume, bornes VAH (haut)
et VAL (bas). Ici la plage est la SEANCE PRECEDENTE (jour UTC par defaut,
`session_hours`) : son profil sert de reference toute la seance suivante,
comme dans les exemples du document (BTC en 15 minutes, profil de la veille).

EF-109 : calcul identique a TradingView (voir `volume_profile`) - 24 lignes par
defaut, hauteur en pas de cotation entiers, zone de valeur construite ligne a
ligne sans depasser 70 %, et bougies FINES (1 min pour un graphique 15 min,
table officielle, `tradingbot.profile_source`) fournies par le lanceur via
`set_profile_source`. Sans source (ou en cas d'erreur), les bougies de la
strategie servent. `profile_period="developing"` : profil de la seance EN COURS,
recalcule a chaque cloture avec les seules donnees deja connues (le profil
"en developpement" de TradingView) - un profil trace apres coup sur une plage
qui contient le mouvement (ex. plage du 08/10 au 09/10) inclut des volumes
futurs et n'est pas tradable tel quel.

Regle generale du document : on n'entre qu'a la CLOTURE de la bougie qui
valide la derniere condition, jamais avant ; stop et objectif a 2 fois le
risque (2R) sont propres au trade (`Signal.stop_price/target_price`, surveilles
par le moteur).

EF-104 : `allow_short` (desactive par defaut) ajoute les schemas "vente" du
document, miroirs exacts des trois setups d'achat : rejet du POC par le haut
quand la veille a fini sous le VAL, retour dans la zone depuis le dessus (bougie
rouge qui reclot sous le VAH), cassure du VAL puis cloture sous l'ancien plus
bas. Le stop est alors au-dessus du pattern et l'objectif en dessous. Le miroir
est calcule en inversant les prix (plus haut <-> plus bas), ce qui garantit des
regles identiques dans les deux sens. Ne s'execute qu'en backtest ou chez un
courtier qui autorise la vente a decouvert (CFD) : un compte au comptant refuse.

EF-105 : un stop de pattern tres loin donne un objectif 2R inatteignable qui
bloque le bot des jours (constate le 2026-09-28 : risque 1,9 %, objectif +3,8 %,
9 jours en position). Reglages, tous desactives par defaut :
- `max_risk_pct` : distance maximale au stop. Au-dela, `wide_stop="cap"` rapproche
  le stop a cette distance (objectif = `reward_risk` fois celle-ci), `"skip"`
  ignore le trade.
- `fixed_stop_pct` / `fixed_target_pct` : stop et objectif fixes en % du prix
  d'entree, quel que soit le pattern (objectif vide = `reward_risk` fois le stop).

EF-107 : avec spread et commission, un objectif a 2R brut ne fait plus 2R net
(+20 % sans frais, -0,8 % au mieux avec, constate par l'utilisateur dans
l'atelier). Le moteur transmet le cout aller-retour (`set_round_trip_cost`) :
- `cost_cover` : l'objectif est repousse pour que le gain NET reste 2 fois la
  perte NETTE (couts payes dans les deux cas).
- `min_risk_cost_ratio` : trade ignore si le stop est a moins de N fois le cout
  aller-retour (les couts y pesent trop).

EF-108 : `min_target_pct` - trade ignore si l'objectif est a moins de ce % du
prix d'entree (objectifs de 0,2 - 0,3 % releves par l'utilisateur : intradables).
Seuil absolu, actif meme quand les couts ne sont pas renseignes (bots a 0 frais).

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

import math

import numpy as np

from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal

HOUR_MS = 3_600_000
# L'epoque Unix tombe un jeudi : decalage de 4 jours pour des semaines du lundi
# (seances de 168 h). Sans effet pour des seances d'un jour.
WEEK_OFFSET_MS = 4 * 24 * HOUR_MS
SETUPS = ("poc_rebound", "value_area_reentry", "breakout")
WIDE_STOP_ACTIONS = ("cap", "skip")   # stop plus loin que `max_risk_pct` : rapproche, ou trade ignore
# EF-109 : profil de la seance precedente (document de l'utilisateur), ou de la seance en cours
# calcule jusqu'a la bougie qui vient de clore (profil "en developpement" de TradingView, sans futur).
PROFILE_PERIODS = ("previous", "developing")


def price_tick(candles, sample: int = 400) -> float:
    """Pas de cotation deduit des prix (2501.37 -> 0,01 ; 0.20123 -> 0,00001)."""
    stride = max(1, len(candles) // sample)
    decimals = 0
    for c in candles[::stride]:
        for v in (c.open, c.high, c.low, c.close):
            for d in range(decimals, 9):
                if abs(v - round(v, d)) <= 1e-9 * max(1.0, abs(v)):
                    decimals = d
                    break
            else:
                decimals = 8
    return 10.0 ** -decimals


def _ticks_per_row(span_ticks: int, rows: int) -> int:
    """TradingView : hauteur de ligne en nombre ENTIER de pas, arrondie vers le bas ou
    vers le haut selon ce qui donne le nombre de lignes le plus proche de `rows`."""
    exact = span_ticks / rows
    options = {max(1, math.floor(exact)), max(1, math.ceil(exact))}
    return min(options, key=lambda t: (abs(-(-span_ticks // t) - rows), -t))


def volume_profile(candles, rows: int = 24, value_area_pct: float = 0.70,
                   tick: float | None = None) -> tuple[float, float, float] | None:
    """(POC, VAH, VAL) des bougies donnees, calcules comme TradingView (EF-109), ou
    None si le profil est vide. Methode officielle ("Volume profile indicators:
    basic concepts", relevee le 2026-10-09) :
    - lignes de `ticks_per_row` pas de cotation, du plus bas au plus haut du profil ;
    - zone de valeur : on part du POC, on compare la ligne suivante au-dessus et
      au-dessous, on ajoute la plus chargee SI elle ne fait pas depasser la cible
      (70 % du volume), sinon on s'arrete ; a egalite, la plus proche du POC, puis
      celle du dessus ; VAH = haut de la ligne la plus haute, VAL = bas de la plus basse.
    Non publie par TradingView : la repartition du volume d'une bougie entre les
    lignes qu'elle traverse. Ici, au prorata de la hauteur couverte - avec des
    bougies d'1 minute, une bougie touche rarement plus de 2 lignes."""
    candles = [c for c in candles if c.volume > 0]
    if not candles:
        return None
    lows = np.array([c.low for c in candles], dtype=float)
    highs = np.array([c.high for c in candles], dtype=float)
    vols = np.array([c.volume for c in candles], dtype=float)
    lo, hi = float(lows.min()), float(highs.max())
    if hi <= lo:
        return (lo, lo, lo)
    tick = tick or price_tick(candles)
    span_ticks = max(1, round((hi - lo) / tick))
    per_row = _ticks_per_row(span_ticks, rows)
    n = -(-span_ticks // per_row)
    step = per_row * tick
    edges = lo + step * np.arange(n + 1)
    flat = highs <= lows
    height = np.where(flat, 1.0, highs - lows)
    overlap = np.clip(np.minimum(highs[:, None], edges[None, 1:]) - np.maximum(lows[:, None], edges[None, :-1]),
                      0.0, None)
    bins = (overlap / height[:, None] * vols[:, None]).sum(axis=0)
    if flat.any():                       # bougie sans amplitude : tout son volume dans sa ligne
        idx = np.minimum(((lows[flat] - lo) / step).astype(int), n - 1)
        np.add.at(bins, idx, vols[flat])
    poc_i = int(bins.argmax())
    remaining = bins.sum() * value_area_pct - bins[poc_i]
    low_i = high_i = poc_i
    while True:
        up = high_i + 1 if high_i + 1 < n else None
        down = low_i - 1 if low_i - 1 >= 0 else None
        if up is None and down is None:
            break
        if down is None or (up is not None and (bins[up] > bins[down] or (
                bins[up] == bins[down] and up - poc_i <= poc_i - down))):
            if bins[up] > remaining:
                break
            remaining -= bins[up]
            high_i = up
        else:
            if bins[down] > remaining:
                break
            remaining -= bins[down]
            low_i = down
    return float(lo + (poc_i + 0.5) * step), float(edges[high_i + 1]), float(edges[low_i])


def _mirror(c: Candle | None) -> Candle | None:
    """Bougie vue dans un miroir de prix : une baisse devient une hausse."""
    if c is None:
        return None
    return Candle(timestamp=c.timestamp, open=-c.open, high=-c.low, low=-c.high, close=-c.close, volume=c.volume)


class VolumeProfileStrategy(Strategy):
    def __init__(self, setups=SETUPS, session_hours: int = 24, rows: int = 24, value_area_pct: float = 0.70,
                 reward_risk: float = 2.0, max_signal_age: int = 3, pullback_max_depth: float = 0.25,
                 stop_buffer_pct: float = 0.0005, min_risk_pct: float = 0.0, allow_short: bool = False,
                 max_risk_pct: float = 0.0, wide_stop: str = "cap", fixed_stop_pct: float = 0.0,
                 fixed_target_pct: float = 0.0, cost_cover: bool = False, min_risk_cost_ratio: float = 0.0,
                 min_target_pct: float = 0.0, lower_timeframe_profile: bool = True,
                 profile_period: str = "previous"):
        setups = tuple(setups)
        unknown = [s for s in setups if s not in SETUPS]
        if not setups or unknown:
            raise ValueError(f"setups inconnus ou vides : {unknown} (attendus : {', '.join(SETUPS)})")
        if (session_hours < 1 or rows < 5 or not 0 < value_area_pct < 1 or reward_risk <= 0
                or max_signal_age < 1 or pullback_max_depth < 0 or stop_buffer_pct < 0 or min_risk_pct < 0
                or not 0 <= max_risk_pct < 1 or not 0 <= fixed_stop_pct < 1 or not 0 <= fixed_target_pct < 1
                or min_risk_cost_ratio < 0 or not 0 <= min_target_pct < 1):
            raise ValueError("parametres hors bornes")
        if profile_period not in PROFILE_PERIODS:
            raise ValueError(f"profile_period : {profile_period!r} inconnu (attendus : {', '.join(PROFILE_PERIODS)})")
        if wide_stop not in WIDE_STOP_ACTIONS:
            raise ValueError(f"wide_stop : {wide_stop!r} inconnu (attendus : {', '.join(WIDE_STOP_ACTIONS)})")
        self.setups, self.session_hours, self.rows, self.value_area_pct = setups, session_hours, rows, value_area_pct
        self.reward_risk, self.max_signal_age = reward_risk, max_signal_age
        self.pullback_max_depth, self.stop_buffer_pct, self.min_risk_pct = pullback_max_depth, stop_buffer_pct, min_risk_pct
        self.allow_short = bool(allow_short)
        # EF-105 : stop trop loin -> objectif 2R inatteignable qui bloque le bot des jours.
        self.max_risk_pct, self.wide_stop = max_risk_pct, wide_stop
        self.fixed_stop_pct, self.fixed_target_pct = fixed_stop_pct, fixed_target_pct
        # EF-107 : objectifs et filtre selon les couts reels, transmis par le moteur.
        self.cost_cover, self.min_risk_cost_ratio = bool(cost_cover), min_risk_cost_ratio
        self.round_trip_cost = 0.0
        self.min_target_pct = min_target_pct   # EF-108 : objectif minimal en % du prix d'entree
        # EF-109 : profil calcule sur bougies fines comme TradingView, quand le lanceur fournit une source.
        self.lower_timeframe_profile, self.profile_period = bool(lower_timeframe_profile), profile_period
        self._profile_source = None
        self.profile_source_errors = 0
        self._bar_ms: int | None = None
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
        # Un etat par sens : les setups de vente suivent leurs propres meches et impulsions.
        self._state = {direction: {"wick": None,       # setup 1 : meche de rejet en attente de confirmation
                                   "outside": None,    # setup 2 : extreme atteint depuis la sortie de zone
                                   "bo_phase": 0,      # setup 3 : 0 attente, 1 impulsion, 2 repli
                                   "bo_high": 0.0}
                       for direction in ("long", "short")}

    # ------------------------------------------------------------------ seances
    def set_profile_source(self, source) -> None:
        """EF-109 : `source(debut_ms, fin_ms)` rend les bougies fines CLOSES de l'intervalle
        (voir `tradingbot.profile_source`). Sans source : bougies de la strategie."""
        self._profile_source = source

    def _profile_of(self, start_ms: int, end_ms: int, own: list[Candle]):
        candles = None
        if self._profile_source is not None and self.lower_timeframe_profile:
            try:
                candles = self._profile_source(start_ms, end_ms)
            except Exception:  # noqa: BLE001 - exchange injoignable : profil sur les bougies de la strategie
                self.profile_source_errors += 1
        return volume_profile(candles or own, self.rows, self.value_area_pct)

    def _session_start(self, session: int) -> int:
        return session * self._period_ms + self._offset_ms

    def _roll_session(self, candle: Candle) -> None:
        if self._prev is not None and candle.timestamp > self._prev.timestamp:
            gap = candle.timestamp - self._prev.timestamp
            self._bar_ms = gap if self._bar_ms is None else min(self._bar_ms, gap)
        session = (candle.timestamp - self._offset_ms) // self._period_ms
        if self._session_id is not None and session != self._session_id and self._session:
            if self.profile_period == "previous":
                start = self._session_start(self._session_id)
                self.profile = self._profile_of(start, start + self._period_ms, self._session)
            self.previous_close = self._session[-1].close
            self._session = []
            self._reset_session_state()
        self._session_id = session
        self._session.append(candle)
        if self.profile_period == "developing" and self.previous_close is not None:
            # Seance en cours jusqu'a la cloture de cette bougie : jamais de donnee future.
            end = candle.timestamp + (self._bar_ms or 0)
            self.profile = self._profile_of(self._session_start(session), end, self._session)

    def set_round_trip_cost(self, pct: float) -> None:
        """Cout aller-retour en fraction du prix (commission x 2 + spread), donne par le moteur."""
        self.round_trip_cost = max(0.0, float(pct))

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
            # Vente = memes regles appliquees aux prix inverses (VAH et VAL echangent leur role).
            views = [("long", candle, self._prev, poc, vah, val, self.previous_close)]
            if self.allow_short:
                views.append(("short", _mirror(candle), _mirror(self._prev), -poc, -val, -vah,
                              None if self.previous_close is None else -self.previous_close))
            found = []
            for direction, c, prev, p, hi, lo, prev_close in views:
                st = self._state[direction]
                # Chaque setup met a jour son etat a chaque bougie ; le premier valide l'emporte.
                hits = [self._poc_rebound(st, c, prev, prev_close, p, hi) if "poc_rebound" in self.setups else None,
                        self._reentry(st, c, prev_close, hi, lo) if "value_area_reentry" in self.setups else None,
                        self._breakout(st, c, hi, lo) if "breakout" in self.setups else None]
                found += [(direction, *h) for h in hits if h is not None]
            if found and not self._in_position:
                signal = self._signal(candle, *found[0])
        self._prev = candle
        return signal

    def _poc_rebound(self, st: dict, c: Candle, prev: Candle | None, prev_close: float | None, poc: float, vah: float):
        if prev_close is None or prev_close <= vah:
            st["wick"] = None
            return None
        # Avalement haussier forme SUR le POC : corps vert qui recouvre tout le corps rouge d'avant.
        if (prev is not None and prev.close < prev.open and c.close > c.open
                and c.open <= prev.close and c.close >= prev.open
                and min(prev.low, c.low) <= poc <= max(prev.high, c.high) and c.close > poc):
            st["wick"] = None
            return ("poc_rebound_engulfing", min(prev.low, c.low))
        wick = st["wick"]
        if wick is not None:
            wick["age"] += 1
            if c.close < poc or wick["age"] > self.max_signal_age:
                st["wick"] = None            # rejet rate, ou signal trop vieux : on ne court pas apres
            elif c.close > c.open and c.close > wick["close"]:
                st["wick"] = None
                return ("poc_rebound_wick", min(wick["low"], c.low))
        # Meche de rejet haussiere : meche sous le POC, cloture au-dessus.
        if c.low < poc < c.close and min(c.open, c.close) > poc:
            st["wick"] = {"low": c.low, "close": c.close, "age": 0}
        return None

    def _reentry(self, st: dict, c: Candle, prev_close: float | None, vah: float, val: float):
        if prev_close is None or not val <= prev_close <= vah:
            st["outside"] = None
            return None
        if c.close < val:
            st["outside"] = c.low if st["outside"] is None else min(st["outside"], c.low)
            return None
        if st["outside"] is not None:
            low = min(st["outside"], c.low)
            if c.close > c.open and c.close <= vah:
                st["outside"] = None
                return ("value_area_reentry", low)
            st["outside"] = low
        return None

    def _breakout(self, st: dict, c: Candle, vah: float, val: float):
        floor = vah - self.pullback_max_depth * (vah - val)
        if st["bo_phase"] == 0:
            if c.close > vah:
                st["bo_phase"], st["bo_high"] = 1, c.high
            return None
        if c.close < floor:                      # repli trop profond : la cassure a echoue
            st["bo_phase"] = 0
            return None
        if st["bo_phase"] == 1:
            if c.high > st["bo_high"]:
                st["bo_high"] = c.high           # l'impulsion continue
            else:
                st["bo_phase"] = 2               # premiere bougie sans nouveau plus haut : le repli
            return None
        if c.close > st["bo_high"]:              # cloture au-dessus de l'ancien plus haut
            st["bo_phase"] = 0
            return ("breakout", st["bo_high"])
        return None

    def _signal(self, c: Candle, direction: str, reason: str, stop_level: float) -> Signal | None:
        entry = c.close
        short = direction == "short"
        # Distance au stop du pattern. Vente : niveau revenu du miroir, stop AU-DESSUS.
        risk = (-stop_level * (1 + self.stop_buffer_pct) - entry if short
                else entry - stop_level * (1 - self.stop_buffer_pct))
        if self.min_risk_pct and risk / entry < self.min_risk_pct:
            risk = entry * self.min_risk_pct
        if risk <= 0:
            return None
        reward = self.reward_risk * risk
        # EF-105 : niveaux fixes en % du prix, ou stop du pattern plafonne / trade ignore
        # quand il est trop loin (objectif 2R inatteignable qui bloque le bot des jours).
        if self.fixed_stop_pct:
            risk = entry * self.fixed_stop_pct
            reward = entry * self.fixed_target_pct if self.fixed_target_pct else self.reward_risk * risk
        elif self.max_risk_pct and risk > entry * self.max_risk_pct:
            if self.wide_stop == "skip":
                return None
            risk = entry * self.max_risk_pct
            reward = self.reward_risk * risk
        # EF-107 : couts aller-retour (commission + spread) fournis par le moteur.
        cost = entry * self.round_trip_cost
        if cost and self.min_risk_cost_ratio and risk < self.min_risk_cost_ratio * cost:
            return None                  # stop si proche que les couts mangeraient le trade
        if cost and self.cost_cover:
            # Objectif repousse pour que, NET des couts, le gain reste `reward / risk` fois la perte :
            # (R' - c) / (r + c) = R / r  =>  R' = R + c x (1 + R / r).
            reward += cost * (1 + reward / risk)
        # EF-108 : objectif trop proche (0,2 - 0,3 %) : trade non tradable, couts et bruit l'emportent.
        if self.min_target_pct and reward < entry * self.min_target_pct:
            return None
        if short:
            if entry - reward <= 0:
                return None
            name = "breakdown" if reason == "breakout" else reason
            return Signal(side=Side.SELL, reason=f"volume_profile_short_{name}", stop_price=entry + risk,
                          target_price=entry - reward, position_side="short")
        return Signal(side=Side.BUY, reason=f"volume_profile_{reason}" if not reason.startswith("volume") else reason,
                      stop_price=entry - risk, target_price=entry + reward)

    # ------------------------------------------------------------------ graphique
    def chart_levels(self) -> list[dict]:
        """POC / VAH / VAL de la seance precedente (graphique du bot, EF-88).
        Le stop et l'objectif de chaque trade s'affichent avec la position."""
        if self.profile is None:
            return []
        poc, vah, val = self.profile
        when = "du jour (en cours)" if self.profile_period == "developing" else "veille"
        return [
            {"price": poc, "label": f"POC {when} (volume max)", "kind": "trend"},
            {"price": vah, "label": f"VAH {when} (haut zone de valeur)", "kind": "level"},
            {"price": val, "label": f"VAL {when} (bas zone de valeur)", "kind": "level"},
        ]
