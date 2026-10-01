"""Banc de mesure de la strategie Fixed Range Volume Profile (EF-96).

Protocole (consignes de l'utilisateur : 2025-2026 seulement, plusieurs fenetres) :
- 4 marches : ETH, BTC, DOGE, PAXG (or) ; bougies 1h ; 4 semestres de 2025-2026
  (le dernier partiel) = 16 fenetres par reglage ;
- moteur reel (`Engine`), frais 0,1 % par ordre, position a 99 % du capital,
  sorties par la strategie seule (objectif / invalidation), pas de stop-loss
  du moteur - pour juger la strategie, pas un garde-fou ;
- GRILLE ENTIERE affichee (mode x plage x confirmation), pas seulement le
  meilleur reglage : choisir le meilleur apres coup sur les memes fenetres
  serait de l'optimisation sur le passe.

Usage : python scripts/bench_volume_profile.py
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bench_exit_rules import ms, pct  # noqa: E402

from tradingbot.data_feed import fetch_historical_candles  # noqa: E402
from bench_common import CashEngine as Engine  # noqa: E402  (taille sur le cash, voir bench_common)
from tradingbot.execution.backtest_executor import BacktestExecutor  # noqa: E402
from tradingbot.portfolio import Portfolio  # noqa: E402
from tradingbot.risk.risk_manager import RiskConfig, RiskManager  # noqa: E402
from tradingbot.strategies.volume_profile import VolumeProfileStrategy  # noqa: E402

WINDOWS = [("S1 2025", "2025-01-01", "2025-07-01"), ("S2 2025", "2025-07-01", "2026-01-01"),
           ("S1 2026", "2026-01-01", "2026-07-01"), ("S2 2026*", "2026-07-01", "2027-01-01")]
MARKETS = ["ETH/USDT", "BTC/USDT", "DOGE/USDT", "PAXG/USDT"]
GRID = [(mode, target, hours, confirm)
        for mode, target in (("reversion", "vah"), ("reversion", "poc"), ("breakout", "vah"))
        for hours in (24, 168) for confirm in (1, 2)]


def label(mode, target, hours, confirm):
    kind = {"reversion": f"retour -> {target.upper()}", "breakout": "cassure"}[mode]
    return f"{kind}, plage {'jour' if hours == 24 else 'semaine'}, confirm. {confirm}"


def run(h1, start, end, mode, target, hours, confirm):
    warm = [c for c in h1 if c.timestamp < start][-400:]   # au moins une plage complete avant
    entry = [c for c in h1 if start <= c.timestamp < end]
    strategy = VolumeProfileStrategy(mode=mode, anchor="period", range_hours=hours, confirm_candles=confirm,
                                     target=target, stop_buffer_pct=0.01)
    for c in warm:
        strategy.on_candle(c)
    if strategy._in_position:                # signal emis pendant le rechauffage : on repart a plat
        strategy._sell("rechauffage")
    config = RiskConfig(max_position_size_pct=0.99, stop_loss_pct=None, take_profit_pct=None,
                        max_daily_loss_pct=1.0, max_concurrent_positions=1, fee_pct=0.001)
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.001)
    engine = Engine(strategy, RiskManager(config), BacktestExecutor(portfolio), portfolio)
    peak, dd = 1000.0, 0.0
    for c in entry:
        engine.process_candle(c)
        equity = portfolio.equity(c.close)
        peak = max(peak, equity)
        dd = max(dd, 1 - equity / peak)
    trades = portfolio.trade_history
    return {"ret": portfolio.equity(entry[-1].close) / 1000.0 - 1, "bh": entry[-1].close / entry[0].open - 1,
            "trades": len(trades), "win": sum(t["pnl"] > 0 for t in trades) / len(trades) if trades else 0.0,
            "dd": dd}


def main() -> None:
    data = {m: fetch_historical_candles(exchange_id="binance", symbol=m, timeframe="1h",
                                        since_iso="2024-11-01T00:00:00Z") for m in MARKETS}
    summary = []
    for params in GRID:
        cells = [run(data[m], ms(a), ms(b), *params) for m in MARKETS for _, a, b in WINDOWS]
        summary.append((params, cells))

    print("=== Grille entiere : 4 marches x 4 semestres = 16 fenetres par reglage ===")
    print(f"{'reglage':<44}{'fen. gagnantes':>15}{'bat garder':>12}{'mediane':>10}{'pire':>9}{'trades/fen.':>13}{'% gagnants':>12}")
    for params, cells in summary:
        rets = [x["ret"] for x in cells]
        trades = [x for x in cells if x["trades"]]
        win = statistics.mean(x["win"] for x in trades) if trades else 0.0
        print(f"{label(*params):<44}{sum(r > 0 for r in rets):>12}/16{sum(x['ret'] > x['bh'] for x in cells):>9}/16"
              f"{pct(statistics.median(rets)):>10}{pct(min(rets)):>9}{statistics.mean(x['trades'] for x in cells):>13.0f}"
              f"{win * 100:>11.0f}%")

    print("\n=== Detail par marche et semestre (rendement) ===")
    print(f"{'reglage':<44}" + "".join(f"{m.split('/')[0] + ' ' + w[:7]:>15}" for m in MARKETS for w, _, _ in WINDOWS))
    for params, cells in summary:
        print(f"{label(*params):<44}" + "".join(f"{pct(x['ret']):>15}" for x in cells))
    bh = summary[0][1]
    print(f"{'garder sans rien faire':<44}" + "".join(f"{pct(x['bh']):>15}" for x in bh))


if __name__ == "__main__":
    main()
