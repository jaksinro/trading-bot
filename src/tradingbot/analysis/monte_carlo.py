"""Estimation de probabilite de hausse/baisse par simulation Monte Carlo,
basee sur un bootstrap des rendements journaliers historiques (3 ans par
defaut).

Note honnete sur le GPU : un benchmark reel (RTX 3060, CuPy/CUDA) a ete
effectue sur ce projet. Pour la taille de simulation necessaire ici
(quelques centaines de milliers de tirages, suffisant pour une estimation
statistiquement stable), le CPU (numpy) s'est revele PLUS RAPIDE que le GPU
(~22ms vs plusieurs centaines de ms) : le cout de lancement des kernels CUDA
depasse le gain de parallelisme a cette echelle. Le calcul reste donc
volontairement en CPU.

Methode : bootstrap avec remise sur les rendements logarithmiques journaliers
observes, PAS un modele parametrique (ex. mouvement brownien geometrique) -
ca capture la vraie distribution empirique (asymetrie, queues epaisses) sans
supposer une loi normale. C'est une extrapolation statistique de la
volatilite et de la tendance passees, PAS une prediction fiable du marche :
un cours peut toujours partir dans une direction jamais observee dans les
3 dernieres annees.
"""

import numpy as np

MIN_HISTORY_DAYS = 30


def compute_daily_log_returns(closes: list[float]) -> np.ndarray:
    """Rendements log journaliers a partir d'une serie de prix de cloture."""
    prices = np.asarray(closes, dtype=np.float64)
    if len(prices) < 2:
        return np.array([])
    return np.diff(np.log(prices))


def simulate_probability_up(
    daily_returns: np.ndarray,
    n_simulations: int = 200_000,
    seed: int | None = None,
) -> float:
    """Tire aleatoirement (avec remise) parmi les rendements journaliers
    historiques pour simuler `n_simulations` scenarios de prix a horizon
    24h, et retourne la proportion de scenarios ou le prix simule est
    superieur au prix actuel (equivalent a un rendement tire > 0)."""
    if len(daily_returns) < MIN_HISTORY_DAYS:
        raise ValueError(
            f"historique insuffisant pour une simulation fiable "
            f"({len(daily_returns)} jours, {MIN_HISTORY_DAYS} minimum)"
        )
    rng = np.random.default_rng(seed)
    sampled_returns = rng.choice(daily_returns, size=n_simulations, replace=True)
    return float((sampled_returns > 0).mean())
