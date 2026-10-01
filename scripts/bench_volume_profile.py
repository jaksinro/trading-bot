"""Banc de mesure de la strategie Volume Profile refaite d'apres le document de
l'utilisateur (EF-97) : 3 setups, entree a la cloture de la bougie qui valide,
stop propre au trade, objectif 2R.

Protocole (consignes de l'utilisateur : 2025-2026 seulement, plusieurs fenetres) :
- bougies 15 min pour les entrees (comme les exemples du document : BTC en
  15 min, profil de la veille), construites a partir des bougies 5 min ;
  stop et objectif verifies sur les clotures 5 min (moteur reel) ;
- ETH, BTC, DOGE x 4 semestres de 2025-2026 (le dernier partiel) ;
- frais 0,1 % par ordre, taille 99 % du cash disponible (`CashEngine`) ;
- achat seulement (marche au comptant).

Usage : python scripts/bench_volume_profile.py
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bench_common import CashEngine as Engine  # noqa: E402  (taille sur le cash, voir bench_common)
from bench_exit_rules import ms, pct  # noqa: E402

from tradingbot.backtest_lab import merge_dual_timeframe  # noqa: E402
from tradingbot.data_feed import fetch_historical_candles  # noqa: E402
from tradingbot.execution.backtest_executor import BacktestExecutor  # noqa: E402
from tradingbot.portfolio import Portfolio  # noqa: E402
from tradingbot.risk.risk_manager import RiskConfig, RiskManager  # noqa: E402
from tradingbot.strategies.volume_profile import VolumeProfileStrategy  # noqa: E402
from tradingbot.types import Candle  # noqa: E402

WINDOWS = [("S1 2025", "2025-01-01", "2025-07-01"), ("S2 2025", "2025-07-01", "2026-01-01"),
           ("S1 2026", "2026-01-01", "2026-07-01"), ("S2 2026*", "2026-07-01", "2027-01-01")]
MARKETS = ["ETH/USDT", "BTC/USDT", "DOGE/USDT"]
ALL = ["poc_rebound", "value_area_reentry", "breakout"]
VARIANTS = [
    ("1. rebond sur le POC", {"setups": ["poc_rebound"]}),
    ("2. retour dans la zone de valeur", {"setups": ["value_area_reentry"]}),
    ("3. cassure", {"setups": ["breakout"]}),
    ("les 3 ensemble (document)", {"setups": ALL}),
    ("les 3, objectif 1,5R", {"setups": ALL, "reward_risk": 1.5}),
    ("les 3, objectif 3R", {"setups": ALL, "reward_risk": 3.0}),
    ("les 3, risque mini 0,5 %", {"setups": ALL, "min_risk_pct": 0.005}),
]


def to_15m(m5: list[Candle]) -> list[Candle]:
    out, bucket = [], []
    for c in m5:
        if bucket and c.timestamp // 900_000 != bucket[0].timestamp // 900_000:
            out.append(_merge(bucket))
            bucket = []
        bucket.append(c)
    if bucket and len(bucket) == 3:
        out.append(_merge(bucket))
    return out


def _merge(b: list[Candle]) -> Candle:
    return Candle(timestamp=b[0].timestamp // 900_000 * 900_000, open=b[0].open, high=max(x.high for x in b),
                  low=min(x.low for x in b), close=b[-1].close, volume=sum(x.volume for x in b))


def run(m15, m5, start, end, params):
    warm = [c for c in m15 if start - 2 * 86_400_000 <= c.timestamp < start]   # la veille + marge
    entry = [c for c in m15 if start <= c.timestamp < end]
    fine = [c for c in m5 if start <= c.timestamp < end]
    strategy = VolumeProfileStrategy(**params)
    for c in warm:
        strategy.on_candle(c)
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.001)
    config = RiskConfig(max_position_size_pct=0.99, stop_loss_pct=None, take_profit_pct=None,
                        max_daily_loss_pct=1.0, max_concurrent_positions=1, fee_pct=0.001)
    engine = Engine(strategy, RiskManager(config), BacktestExecutor(portfolio), portfolio)
    peak, dd = 1000.0, 0.0
    for candle, is_entry in merge_dual_timeframe(entry, fine, "15m", "5m"):
        if is_entry:
            engine.process_candle(candle)
        else:
            engine.process_price_update(candle)
        equity = portfolio.equity(candle.close)
        peak, dd = max(peak, equity), max(dd, 1 - equity / max(peak, equity))
    trades = portfolio.trade_history
    return {"ret": portfolio.equity(entry[-1].close) / 1000.0 - 1, "bh": entry[-1].close / entry[0].open - 1,
            "trades": len(trades), "wins": sum(t["pnl"] > 0 for t in trades),
            "fees": sum(t.get("fees_paid", 0.0) for t in trades) / 1000.0, "dd": dd}


def main() -> None:
    data = {}
    for m in MARKETS:
        m5 = fetch_historical_candles(exchange_id="binance", symbol=m, timeframe="5m", since_iso="2024-12-25T00:00:00Z")
        m5 = [c for c in m5 if c.timestamp >= ms("2024-12-25")]
        data[m] = (to_15m(m5), m5)
    print("Fin de l'historique 5 min : " + ", ".join(
        f"{m.split('/')[0]} {Path('x').name and __import__('datetime').datetime.utcfromtimestamp(d[1][-1].timestamp / 1000).date()}"
        for m, d in data.items()))

    print("\n=== 3 marches x 4 semestres = 12 fenetres par reglage (2025-2026, 15 min, frais 0,1 %) ===")
    print(f"{'reglage':<34}{'fen. gagnantes':>15}{'mediane':>10}{'pire':>9}{'meilleure':>11}"
          f"{'trades/sem.':>13}{'% gagnants':>12}{'frais/sem.':>12}")
    rows = []
    for name, params in VARIANTS:
        cells = [run(*data[m], ms(a), ms(b), params) for m in MARKETS for _, a, b in WINDOWS]
        rows.append((name, cells))
        rets = [x["ret"] for x in cells]
        n = sum(x["trades"] for x in cells)
        print(f"{name:<34}{sum(r > 0 for r in rets):>12}/12{pct(statistics.median(rets)):>10}{pct(min(rets)):>9}"
              f"{pct(max(rets)):>11}{n / len(cells):>13.0f}{100 * sum(x['wins'] for x in cells) / max(n, 1):>11.0f}%"
              f"{pct(statistics.mean(x['fees'] for x in cells)):>12}")
    print("\nSeuil de rentabilite d'un objectif a 2R : ~34 % de trades gagnants avant frais.")

    print("\n=== Detail (rendement par marche et semestre) ===")
    print(f"{'reglage':<34}" + "".join(f"{m.split('/')[0] + ' ' + w[:7]:>14}" for m in MARKETS for w, _, _ in WINDOWS))
    for name, cells in rows:
        print(f"{name:<34}" + "".join(f"{pct(x['ret']):>14}" for x in cells))
    print(f"{'garder sans rien faire':<34}" + "".join(f"{pct(x['bh']):>14}" for x in rows[0][1]))


if __name__ == "__main__":
    main()
