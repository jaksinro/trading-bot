"""Strategie de rebond de creux - etape 9 de la feuille de route
performance, proposee par l'utilisateur.

Achat des que le prix est au plus bas (ou tres proche) des `trend_ma_period`
dernieres bougies - AUCUNE condition de regime/tendance requise en plus
(retiree le 2026-09-14 a la demande de l'utilisateur : la version initiale
exigeait aussi que le prix soit au-dessus de sa propre moyenne glissante,
ce qui rendait l'entree beaucoup plus rare qu'un simple "on est au plus
bas"). Elle n'emet JAMAIS de signal de vente elle-meme : la seule sortie
est le verrou de gain (`RiskManager.should_profit_lock`, gere par
`engine.py`) - achete puis HOLD jusqu'a etre rentable, ne vend que si un
gain deja arme retombe sous le seuil de declenchement. PAS de stop-loss non
plus : decision assumee par l'utilisateur, voir docs/STB.md pour la limite
documentee (une position peut rester ouverte tres longtemps en perte
latente si elle n'atteint jamais le seuil d'armement).

Consequence architecturale (deja vraie depuis le retrait de la sortie sur
nouveau plus haut, inchangee ici) : la strategie ne suit aucun etat interne
"en position" - eviter un double achat est entierement le role de
`RiskManager.max_concurrent_positions` (1 par defaut), base sur les
positions REELLEMENT ouvertes (`Engine.executor.get_positions()`), jamais
desynchronise contrairement a un flag propre a la strategie (qui ne serait
jamais informee d'une fermeture externe par le verrou de gain).

`trend_ma_period` est la fenetre (en nombre de bougies) sur laquelle le
plus bas recent est calcule - agnostique du timeframe : `trend_ma_period=24`
sur des bougies 1h ("le plus bas des dernieres 24h") ou `=60` sur des
bougies 1m ("le plus bas de la derniere heure") expriment la MEME regle a
deux granularites differentes (voir STC.md section dediee, "2 presets" du
formulaire dashboard). Le nom du parametre est conserve tel quel pour ne
pas casser les configs/presets existants, meme s'il ne porte plus de notion
de tendance.

`force_trade_after_hours` (optionnel, idee proposee par l'utilisateur) :
si aucun achat n'a eu lieu depuis ce nombre d'heures (temps REEL, base sur
`candle.timestamp` - pas un nombre de bougies, pour rester coherent quel
que soit le timeframe), le seuil de proximite au creux est PROGRESSIVEMENT
assoupli (double a chaque periode entiere supplementaire ecoulee sans achat)
jusqu'a finir par matcher sur une bougie - jamais un achat instantane "a
tout prix", juste un seuil de moins en moins strict tant que rien ne s'est
produit. Desactive par defaut (`None`) : comportement inchange pour les
bots/configs existants.
"""

from collections import deque

from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal

HOUR_MS = 3_600_000


class DipBounceStrategy(Strategy):
    def __init__(
        self, trend_ma_period: int = 24, dip_threshold_pct: float = 0.005,
        force_trade_after_hours: float | None = None,
    ):
        if trend_ma_period < 2:
            raise ValueError("trend_ma_period doit etre >= 2")
        if dip_threshold_pct <= 0:
            raise ValueError("dip_threshold_pct doit etre strictement positif")
        if force_trade_after_hours is not None and force_trade_after_hours <= 0:
            raise ValueError("force_trade_after_hours doit etre strictement positif")
        self.trend_ma_period = trend_ma_period
        self.dip_threshold_pct = dip_threshold_pct
        self.force_trade_after_hours = force_trade_after_hours
        self._closes: deque[float] = deque(maxlen=trend_ma_period)
        self._last_buy_ts: int | None = None

    def _effective_threshold(self, candle: Candle) -> float:
        if self.force_trade_after_hours is None:
            return self.dip_threshold_pct
        if self._last_buy_ts is None:
            self._last_buy_ts = candle.timestamp
        hours_since_last_buy = (candle.timestamp - self._last_buy_ts) / HOUR_MS
        overdue_periods = int(hours_since_last_buy // self.force_trade_after_hours)
        if overdue_periods <= 0:
            return self.dip_threshold_pct
        return self.dip_threshold_pct * (2**overdue_periods)

    def on_candle(self, candle: Candle) -> Signal | None:
        self._closes.append(candle.close)
        if len(self._closes) < self.trend_ma_period:
            return None

        rolling_min = min(self._closes)
        effective_threshold = self._effective_threshold(candle)
        near_the_dip = candle.close <= rolling_min * (1 + effective_threshold)

        if near_the_dip:
            self._last_buy_ts = candle.timestamp
            return Signal(side=Side.BUY, reason="dip_bounce_entry")

        return None
