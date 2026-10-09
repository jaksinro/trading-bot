"""Volume Profile : stop du pattern, stop plafonne, trade ignore ou niveaux
fixes (EF-105).

Constat de l'utilisateur (2026-10-09) : plus le stop du pattern est loin, plus
l'objectif 2R l'est aussi ; un trade du 2026-09-28 (risque 1,9 %, objectif
+3,8 %) est reste 9 jours en position, bloquant toute autre entree. Pistes
demandees : ponderer stop et objectif, ou les rendre fixes (ex. -0,5 % / +1 %).

Memes conditions que bench_vp_intrabar.py : entrees 15 min, stop et objectif
surveilles sur bougies 1 MINUTE au plus haut / plus bas et executes au niveau
(stop d'abord si les deux dans la meme minute), achats seuls (comme le bot),
ETH / BTC / DOGE x 4 semestres 2025-2026 = 12 fenetres, 3 setups ensemble.
Trois spreads aller-retour : 0, 0,02 % et 0,1 %. Un processus par marche.

Usage : python scripts/bench_vp_stops.py
"""
from __future__ import annotations

import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bench_exit_rules import ms, pct  # noqa: E402
from bench_vp_intrabar import ALL, MARKETS, WINDOWS, IntrabarEngine, aggregate  # noqa: E402

from tradingbot.backtest_lab import merge_dual_timeframe  # noqa: E402
from tradingbot.data_feed import fetch_historical_candles  # noqa: E402
from tradingbot.execution.backtest_executor import BacktestExecutor  # noqa: E402
from tradingbot.portfolio import Portfolio  # noqa: E402
from tradingbot.profile_source import preloaded  # noqa: E402
from tradingbot.risk.risk_manager import RiskConfig, RiskManager  # noqa: E402
from tradingbot.strategies.volume_profile import VolumeProfileStrategy  # noqa: E402

VARIANTS = [
    ("stop du pattern, objectif 2R (actuel)", {}),
    ("stop plafonne a 0,5 %, objectif 2R", {"max_risk_pct": 0.005}),
    ("stop plafonne a 1 %, objectif 2R", {"max_risk_pct": 0.01}),
    ("stop plafonne a 1,5 %, objectif 2R", {"max_risk_pct": 0.015}),
    ("trade ignore si stop > 1 %", {"max_risk_pct": 0.01, "wide_stop": "skip"}),
    ("trade ignore si stop > 1,5 %", {"max_risk_pct": 0.015, "wide_stop": "skip"}),
    ("fixe -0,5 % / +1 %", {"fixed_stop_pct": 0.005, "fixed_target_pct": 0.01}),
    ("fixe -0,75 % / +1,5 %", {"fixed_stop_pct": 0.0075, "fixed_target_pct": 0.015}),
    ("fixe -1 % / +2 %", {"fixed_stop_pct": 0.01, "fixed_target_pct": 0.02}),
]
SPREADS = [0.0, 0.0002, 0.001]


def run_one(m1, m15, start, end, kw, cost):
    warm = [c for c in m15 if start - 2 * 86_400_000 <= c.timestamp < start]
    entry = [c for c in m15 if start <= c.timestamp < end]
    strategy = VolumeProfileStrategy(setups=ALL, **kw)
    # EF-109 : profil calcule comme TradingView, sur les bougies 1 min (graphique 15 min).
    strategy.set_profile_source(preloaded(m1, 60_000))
    for c in warm:
        strategy.on_candle(c)
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=cost)
    config = RiskConfig(max_position_size_pct=1 / (1 + cost) - 1e-9, stop_loss_pct=None, take_profit_pct=None,
                        max_daily_loss_pct=1.0, max_concurrent_positions=1, fee_pct=cost)
    engine = IntrabarEngine(strategy, RiskManager(config), BacktestExecutor(portfolio), portfolio)
    fine = [c for c in m1 if start <= c.timestamp < end]
    for candle, is_entry in merge_dual_timeframe(entry, fine, "15m", "1m"):
        (engine.process_candle if is_entry else engine.process_price_update)(candle)
    trades = portfolio.trade_history
    hours = [(t["timestamp"] - t["entry_timestamp"]) / 3.6e6 for t in trades]
    return {"ret": portfolio.equity(entry[-1].close) / 1000.0 - 1, "trades": len(trades),
            "wins": sum(t["pnl"] > 0 for t in trades), "hours": sum(hours), "max_hours": max(hours, default=0.0)}


def market_job(market):
    m1 = [c for c in fetch_historical_candles(exchange_id="binance", symbol=market, timeframe="1m",
                                              since_iso="2024-12-25T00:00:00Z") if c.timestamp >= ms("2024-12-25")]
    m15 = aggregate(m1, 15)
    return {(vi, si, wi): run_one(m1, m15, ms(a), ms(b), kw, spread / 2)
            for vi, (_, kw) in enumerate(VARIANTS) for si, spread in enumerate(SPREADS)
            for wi, (_, a, b) in enumerate(WINDOWS)}


def main() -> None:
    with ProcessPoolExecutor(max_workers=len(MARKETS)) as pool:
        results = dict(zip(MARKETS, pool.map(market_job, MARKETS)))
    for si, spread in enumerate(SPREADS):
        print(f"\nSpread aller-retour {spread * 100:.2f} %")
        print(f"{'variante':<40}{'fen. gagnantes':>15}{'mediane':>9}{'pire':>9}{'somme':>9}{'trades/sem.':>12}"
              f"{'% gagnants':>11}{'duree moy.':>11}{'plus long':>10}")
        for vi, (name, _) in enumerate(VARIANTS):
            cells = [results[m][(vi, si, wi)] for m in MARKETS for wi in range(len(WINDOWS))]
            rets = [x["ret"] for x in cells]
            n = sum(x["trades"] for x in cells)
            print(f"{name:<40}{sum(r > 0 for r in rets):>12}/12{pct(statistics.median(rets)):>9}{pct(min(rets)):>9}"
                  f"{pct(sum(rets)):>9}{n / len(cells):>12.0f}{100 * sum(x['wins'] for x in cells) / max(n, 1):>10.0f}%"
                  f"{sum(x['hours'] for x in cells) / max(n, 1):>10.1f}h{max(x['max_hours'] for x in cells) / 24:>9.1f}j")
    print("\nPar marche (spread 0), somme des 4 semestres :")
    for vi, (name, _) in enumerate(VARIANTS):
        print(f"  {name:<40}" + "  ".join(
            f"{m[:4]} {pct(sum(results[m][(vi, 0, wi)]['ret'] for wi in range(len(WINDOWS))))}" for m in MARKETS))


if __name__ == "__main__":
    main()
