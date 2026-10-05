"""Banc de mesure : regles de sortie du bot ETH_youenn (trend_regime, EMA 500 en
1h, entree +3 %), question de l'utilisateur du 2026-09-27 ("c'est genant
d'avoir le trailing stop sous le prix d'achat non ?").

Reproduit ce que fait le bot en paper :
- la strategie voit les bougies 1h, les sorties (stop-loss, trailing stop,
  verrou de gain) sont verifiees sur des bougies 5 min (`exit_check_timeframe:
  5m`) - meme moteur (`Engine`), meme fusion des deux series que le
  laboratoire de backtest (`merge_dual_timeframe`) ;
- frais 0,1 % par ordre ; strategie rechauffee sur les bougies 1h precedant
  chaque fenetre (comme `warm_up_strategy` en paper) ;
- une seule variable change d'une ligne a l'autre : les regles de sortie.

Mise en garde : taille de position a 99 % du capital (au lieu de 10 % en
config) pour que les rendements se lisent comme ceux d'une position ; le
CLASSEMENT des regles n'en depend pas, les montants si. Une fenetre par semestre de 2025-2026
(2023-2024 exclus a la demande de l'utilisateur, 2026-09-27) : une regle qui ne
gagne que sur une fenetre n'est pas une regle robuste.

Usage : python scripts/bench_exit_rules.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradingbot.backtest_lab import merge_dual_timeframe  # noqa: E402
from tradingbot.data_feed import fetch_historical_candles  # noqa: E402
from tradingbot.engine import Engine  # noqa: E402  (taille sur le cash depuis EF-99, dans le moteur)
from tradingbot.execution.backtest_executor import BacktestExecutor  # noqa: E402
from tradingbot.portfolio import Portfolio  # noqa: E402
from tradingbot.risk.risk_manager import RiskConfig, RiskManager  # noqa: E402
from tradingbot.strategies.trend_regime import TrendRegimeStrategy  # noqa: E402

CAPITAL = 1000.0
WARMUP = 600  # bougies 1h fournies a la strategie avant chaque fenetre (EMA 500)
# 2023-2024 exclus a la demande de l'utilisateur (2026-09-27) : 2025-2026 seulement,
# decoupes en semestres pour garder plusieurs fenetres.
WINDOWS = [
    ("S1 2025", "2025-01-01", "2025-07-01"),
    ("S2 2025", "2025-07-01", "2026-01-01"),
    ("S1 2026", "2026-01-01", "2026-07-01"),
    ("S2 2026*", "2026-07-01", "2027-01-01"),
]

# (libelle, stop_loss, trailing, verrou arme, verrou declenche[, mode du trailing, armement])
# Mode "gain" (EF-93, definition de l'utilisateur) : trailing = part du gain rendue ;
# achat 2000, plus haut 2100, 50 % -> vente a 2050. Armement None = frais aller-retour.
VARIANTS = [
    ("config actuelle : SL 2 %, trailing 1 %", 0.02, 0.01, None, None),
    ("SL 2 %, sans trailing", 0.02, None, None, None),
    ("SL 2 %, trailing 10 % (distance)", 0.02, 0.10, None, None),
    ("SL 2 %, verrou 2 %/0,5 % seul", 0.02, None, 0.02, 0.005),
    ("SL 2 %, gain rendu 30 %, arme 0,2 %", 0.02, 0.30, None, None, "gain", None),
    ("SL 2 %, gain rendu 50 %, arme 0,2 %", 0.02, 0.50, None, None, "gain", None),
    ("SL 2 %, gain rendu 70 %, arme 0,2 %", 0.02, 0.70, None, None, "gain", None),
    ("SL 2 %, gain rendu 50 %, arme 2 %", 0.02, 0.50, None, None, "gain", 0.02),
    ("SL 2 %, gain rendu 50 %, arme 5 %", 0.02, 0.50, None, None, "gain", 0.05),
    ("SL 2 %, gain rendu 30 %, arme 5 %", 0.02, 0.30, None, None, "gain", 0.05),
    ("SL 2 %, gain rendu 50 %, arme 10 %", 0.02, 0.50, None, None, "gain", 0.10),
    ("aucune sortie de risque (strategie seule)", None, None, None, None),
]


def ms(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)


def run(h1, m5, start, end, sl, trail, arm, trig, mode="distance", trail_arm=None):
    warm = [c for c in h1 if c.timestamp < start][-WARMUP:]
    entry = [c for c in h1 if start <= c.timestamp < end]
    fine = [c for c in m5 if start <= c.timestamp < end]
    if not entry or not fine:
        return None
    strategy = TrendRegimeStrategy(ema_period=500, entry_buffer_pct=0.03, exit_buffer_pct=0.0)
    for c in warm:
        strategy.on_candle(c)
    risk = RiskManager(RiskConfig(
        max_position_size_pct=0.99, stop_loss_pct=sl, take_profit_pct=None, max_daily_loss_pct=0.05,
        max_concurrent_positions=1, trailing_stop_pct=trail, fee_pct=0.001,
        profit_lock_arm_pct=arm, profit_lock_trigger_pct=trig, trailing_mode=mode, trailing_arm_pct=trail_arm,
    ))
    portfolio = Portfolio(starting_capital=CAPITAL, fee_pct=0.001)
    engine = Engine(strategy, risk, BacktestExecutor(portfolio), portfolio)
    equity_peak, max_dd = CAPITAL, 0.0
    for candle, is_entry in merge_dual_timeframe(entry, fine, "1h", "5m"):
        if is_entry:
            engine.process_candle(candle)
            equity = portfolio.equity(candle.close)
            equity_peak = max(equity_peak, equity)
            max_dd = max(max_dd, 1 - equity / equity_peak)
        else:
            engine.process_price_update(candle)
    last = entry[-1].close
    trades = portfolio.trade_history
    return {
        "ret": portfolio.equity(last) / CAPITAL - 1,
        "bh": last / entry[0].open - 1,
        "trades": len(trades),
        "win": sum(t["pnl"] > 0 for t in trades) / len(trades) if trades else 0.0,
        "fees": sum(t.get("fees_paid", 0.0) for t in trades) / CAPITAL,
        "dd": max_dd,
    }


def pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def main() -> None:
    h1 = fetch_historical_candles(exchange_id="binance", symbol="ETH/USDT", timeframe="1h", since_iso="2024-11-01T00:00:00Z")
    m5 = fetch_historical_candles(exchange_id="binance", symbol="ETH/USDT", timeframe="5m", since_iso="2025-01-01T00:00:00Z")
    end_5m = datetime.fromtimestamp(m5[-1].timestamp / 1000, timezone.utc).date()
    print(f"ETH/USDT - 1h : {len(h1)} bougies, 5m : {len(m5)} bougies (jusqu'au {end_5m})")
    print("* S2 2026 : fenetre partielle, jusqu'a la fin de l'historique 5m\n")

    results = {}
    for label, *rules in VARIANTS:
        results[label] = [run(h1, m5, ms(a), ms(b), *rules) for _, a, b in WINDOWS]

    bh = [r["bh"] for r in results[VARIANTS[0][0]]]
    head = f"{'regle de sortie':<44}" + "".join(f"{w:>9}" for w, _, _ in WINDOWS) + f"{'fenetres gagnees*':>19}"
    print("=== Rendement par semestre (buy & hold ETH en derniere ligne) ===")
    print(head)
    print("-" * len(head))
    reference = results[VARIANTS[0][0]]
    for label, *_ in VARIANTS:
        rows = results[label]
        better = sum(r["ret"] > ref["ret"] + 1e-9 for r, ref in zip(rows, reference))
        tail = "reference" if label == VARIANTS[0][0] else f"{better}/{len(rows)}"
        print(f"{label:<44}" + "".join(f"{pct(r['ret']):>9}" for r in rows) + f"{tail:>19}")
    print(f"{'buy & hold ETH':<44}" + "".join(f"{pct(x):>9}" for x in bh))
    print("* fenetres ou la regle fait mieux que la config actuelle\n")

    print("=== Detail : trades / % gagnants / frais payes (en % du capital) / baisse max ===")
    for label, *_ in VARIANTS:
        cells = [f"{r['trades']:>4} {r['win'] * 100:>3.0f}% {r['fees'] * 100:>5.1f}% {r['dd'] * 100:>4.0f}%"
                 for r in results[label]]
        print(f"{label:<44}" + " | ".join(cells))


if __name__ == "__main__":
    main()
