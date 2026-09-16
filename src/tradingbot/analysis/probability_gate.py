"""ProbabilityGate (STC ext.) - filtre optionnel qui bloque un achat si la
probabilite estimee de hausse du prix a 24h (Monte Carlo sur 3 ans
d'historique, voir monte_carlo.py) est sous un seuil configure.

Composant optionnel et separe du RiskManager : il ne remplace aucune regle
de risque existante (stop-loss, take-profit...), il ajoute juste un filtre
supplementaire avant l'achat. Desactive par defaut (backward-compatible).
"""

import datetime
import time

from tradingbot.analysis.monte_carlo import compute_daily_log_returns, simulate_probability_up
from tradingbot.data_feed import fetch_historical_candles


def _years_ago_iso(years: float) -> str:
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=int(years * 365))
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class ProbabilityGate:
    def __init__(
        self,
        exchange_id: str,
        symbol: str,
        min_probability: float = 0.55,
        lookback_years: float = 3.0,
        n_simulations: int = 200_000,
        cache_ttl_seconds: int = 6 * 3600,
    ):
        self.exchange_id = exchange_id
        self.symbol = symbol
        self.min_probability = min_probability
        self.lookback_years = lookback_years
        self.n_simulations = n_simulations
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cached_probability: float | None = None
        self._cached_at: float = 0.0

    def current_probability(self) -> float:
        """Recalcule la probabilite si le cache a expire (evite de re-tirer
        3 ans d'historique et de relancer une simulation a chaque bougie -
        inutile car la distribution des rendements journaliers ne change
        pas significativement d'une minute a l'autre)."""
        now = time.time()
        if self._cached_probability is None or (now - self._cached_at) > self.cache_ttl_seconds:
            candles = fetch_historical_candles(
                exchange_id=self.exchange_id,
                symbol=self.symbol,
                timeframe="1d",
                since_iso=_years_ago_iso(self.lookback_years),
            )
            closes = [c.close for c in candles]
            returns = compute_daily_log_returns(closes)
            self._cached_probability = simulate_probability_up(returns, n_simulations=self.n_simulations)
            self._cached_at = now
        return self._cached_probability

    def allows_buy(self) -> tuple[bool, float]:
        """Retourne (autorise, probabilite). En cas d'echec du calcul
        (ex: API indisponible), on choisit de NE PAS bloquer le trading -
        ce filtre est une securite supplementaire, pas une regle de risque
        critique comme le stop-loss ; un blocage indefini sur panne reseau
        serait pire que l'absence ponctuelle du filtre."""
        try:
            probability = self.current_probability()
        except Exception:
            return True, -1.0
        return probability >= self.min_probability, probability
