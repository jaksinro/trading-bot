"""Volume Profile : objectif repousse selon les couts, filtre des stops trop
proches des couts (EF-107).

Constat de l'utilisateur (2026-10-09, atelier) : +20 % sans frais, -0,8 % au
mieux avec spread et commission. Pistes : repousser l'objectif pour garder 2R
NET de couts (`cost_cover`), ignorer les trades dont le stop est a moins de N
fois le cout aller-retour (`min_risk_cost_ratio`), seuls ou avec le plafond de
stop d'EF-105.

Memes conditions que bench_vp_stops.py (entrees 15 min, sorties 1 MINUTE au
plus haut / plus bas, achats seuls comme le bot, ETH / BTC / DOGE x 4 semestres
2025-2026 = 12 fenetres). Spreads aller-retour : 0,06 % (Capital.com, estime
pour ETH depuis le spread publie du Bitcoin) et 0,1 %. Commission 0.

Usage : python scripts/bench_vp_costs.py
"""
from __future__ import annotations

import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bench_exit_rules import ms, pct  # noqa: E402
from bench_vp_intrabar import MARKETS, WINDOWS, aggregate  # noqa: E402
from bench_vp_stops import run_one  # noqa: E402

from tradingbot.data_feed import fetch_historical_candles  # noqa: E402

CAP = {"max_risk_pct": 0.015}
VARIANTS = [
    ("actuel (2R brut)", {}),
    ("objectif couvre les couts", {"cost_cover": True}),
    ("stop >= 5 x couts", {"min_risk_cost_ratio": 5}),
    ("stop >= 10 x couts", {"min_risk_cost_ratio": 10}),
    ("couvre + stop >= 5 x couts", {"cost_cover": True, "min_risk_cost_ratio": 5}),
    ("couvre + stop >= 10 x couts", {"cost_cover": True, "min_risk_cost_ratio": 10}),
    ("plafond 1,5 %", CAP),
    ("plafond 1,5 % + couvre", {**CAP, "cost_cover": True}),
    ("plafond 1,5 % + stop >= 10 x couts", {**CAP, "min_risk_cost_ratio": 10}),
    ("plafond 1,5 % + couvre + stop >= 10 x", {**CAP, "cost_cover": True, "min_risk_cost_ratio": 10}),
]
SPREADS = [0.0006, 0.001]


def market_job(market, variants, spreads):
    # Variantes passees en argument : sous Windows, chaque processus reimporte ce module.
    m1 = [c for c in fetch_historical_candles(exchange_id="binance", symbol=market, timeframe="1m",
                                              since_iso="2024-12-25T00:00:00Z") if c.timestamp >= ms("2024-12-25")]
    m15 = aggregate(m1, 15)
    return {(vi, si, wi): run_one(m1, m15, ms(a), ms(b), kw, spread / 2)
            for vi, (_, kw) in enumerate(variants) for si, spread in enumerate(spreads)
            for wi, (_, a, b) in enumerate(WINDOWS)}


def main(variants=VARIANTS, spreads=SPREADS) -> None:
    with ProcessPoolExecutor(max_workers=len(MARKETS)) as pool:
        results = dict(zip(MARKETS, pool.map(partial(market_job, variants=variants, spreads=spreads), MARKETS)))
    for si, spread in enumerate(spreads):
        print(f"\nSpread aller-retour {spread * 100:.2f} %")
        print(f"{'variante':<40}{'fen. gagnantes':>15}{'mediane':>9}{'pire':>9}{'somme':>9}{'trades/sem.':>12}"
              f"{'% gagnants':>11}{'  ETH / BTC / DOGE (somme)'}")
        for vi, (name, _) in enumerate(variants):
            cells = [results[m][(vi, si, wi)] for m in MARKETS for wi in range(len(WINDOWS))]
            rets = [x["ret"] for x in cells]
            n = sum(x["trades"] for x in cells)
            per = " / ".join(pct(sum(results[m][(vi, si, wi)]["ret"] for wi in range(len(WINDOWS)))) for m in MARKETS)
            print(f"{name:<40}{sum(r > 0 for r in rets):>12}/12{pct(statistics.median(rets)):>9}{pct(min(rets)):>9}"
                  f"{pct(sum(rets)):>9}{n / len(cells):>12.0f}{100 * sum(x['wins'] for x in cells) / max(n, 1):>10.0f}%"
                  f"  {per}")


if __name__ == "__main__":
    main()
