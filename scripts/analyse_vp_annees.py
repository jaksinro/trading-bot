"""Volume Profile : pourquoi 2026 est mauvais alors que 2024 et 2025 etaient bons.

Demande de l'utilisateur (2026-10-11). 2024 sert ici de point de comparaison
pour le DIAGNOSTIC seulement (il l'a cite) ; aucun reglage n'est choisi dessus
(consigne : mesures de strategies sur 2025 et apres).

Pour ETH/USDT, chaque annee : la strategie rejouee comme dans les bancs (entrees
15 min, profil de la veille calcule comme TradingView sur 1 min, sorties 1 min
au plus haut / plus bas), puis :
1. le resultat par annee, par setup, par contexte (tendance, volatilite, distance
   au stop, position de la cloture de la veille par rapport a la zone de valeur) ;
2. le comportement du MARCHE autour des niveaux de la veille, independamment de
   la strategie : quand le prix sort de la zone de valeur, y revient-il (ce que
   parient les setups "retour dans la zone" et "rebond") ou continue-t-il (ce que
   parie la "cassure") ?

Usage : python scripts/analyse_vp_annees.py   (depuis la racine du depot)
"""
from __future__ import annotations

import statistics
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bench_exit_rules import ms  # noqa: E402
from bench_vp_intrabar import IntrabarEngine, aggregate  # noqa: E402

from tradingbot.backtest_lab import merge_dual_timeframe  # noqa: E402
from tradingbot.data_feed import fetch_historical_candles  # noqa: E402
from tradingbot.execution.backtest_executor import BacktestExecutor  # noqa: E402
from tradingbot.portfolio import Portfolio  # noqa: E402
from tradingbot.profile_source import preloaded  # noqa: E402
from tradingbot.risk.risk_manager import RiskConfig, RiskManager  # noqa: E402
from tradingbot.strategies.volume_profile import VolumeProfileStrategy, volume_profile  # noqa: E402

DAY = 86_400_000
YEARS = [("2024 (reference)", "2024-01-01", "2025-01-01"), ("2025", "2025-01-01", "2026-01-01"),
         ("2026 (au 10/10)", "2026-01-01", "2026-10-11")]
SETTINGS = [("reglages du bot", {}),
            ("plafond 1,5 % + objectif >= 1,5 %", {"max_risk_pct": 0.015, "min_target_pct": 0.015})]
SPREADS = [0.0, 0.0006]
RISK_BUCKETS = ((0, 0.005), (0.005, 0.01), (0.01, 0.02), (0.02, 1.0))
VOL_BUCKETS = ((0, 0.03), (0.03, 0.045), (0.045, 1.0))


class Recorder:
    """Strategie enveloppee : garde le setup et le contexte de chaque signal."""

    def __init__(self, strategy):
        self.strategy, self.signals = strategy, {}

    def __getattr__(self, name):
        return getattr(self.strategy, name)

    def on_candle(self, candle):
        sig = self.strategy.on_candle(candle)
        if sig is not None:
            self.signals[candle.timestamp] = {"setup": sig.reason.replace("volume_profile_", ""),
                                              "stop": sig.stop_price, "target": sig.target_price,
                                              "profile": self.strategy.profile,
                                              "prev_close": self.strategy.previous_close}
        return sig


def daily(m15):
    days = defaultdict(list)
    for c in m15:
        days[c.timestamp // DAY].append(c)
    return {d: (cs[0].open, max(x.high for x in cs), min(x.low for x in cs), cs[-1].close) for d, cs in days.items()}


def context(day_bars, day):
    """Tendance (cloture de la veille vs moyenne 50 jours) et volatilite (amplitude moyenne 20 jours)."""
    closes = [day_bars[d][3] for d in range(day - 50, day) if d in day_bars]
    ranges = [(day_bars[d][1] - day_bars[d][2]) / day_bars[d][3] for d in range(day - 20, day) if d in day_bars]
    if len(closes) < 40:
        return None, None
    return ("haussiere" if closes[-1] > sum(closes) / len(closes) else "baissiere"), sum(ranges) / len(ranges)


def run(m1, m15, start, end, kw, cost):
    warm = [c for c in m15 if start - 2 * DAY <= c.timestamp < start]
    entry = [c for c in m15 if start <= c.timestamp < end]
    strategy = Recorder(VolumeProfileStrategy(**kw))
    strategy.set_profile_source(preloaded(m1, 60_000))
    for c in warm:
        strategy.on_candle(c)
    strategy.signals.clear()
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=cost)
    config = RiskConfig(max_position_size_pct=1 / (1 + cost) - 1e-9, stop_loss_pct=None, take_profit_pct=None,
                        max_daily_loss_pct=1.0, max_concurrent_positions=1, fee_pct=cost)
    engine = IntrabarEngine(strategy, RiskManager(config), BacktestExecutor(portfolio), portfolio)
    fine = [c for c in m1 if start <= c.timestamp < end]
    for candle, is_entry in merge_dual_timeframe(entry, fine, "15m", "1m"):
        (engine.process_candle if is_entry else engine.process_price_update)(candle)
    trades = []
    for t in portfolio.trade_history:
        info = strategy.signals.get(t["entry_timestamp"], {})
        trades.append({**info, "entry_t": t["entry_timestamp"], "exit_t": t["timestamp"], "entry": t["entry_price"],
                       "pnl_pct": t["pnl"] / (t["entry_price"] * t["quantity"]), "exit_reason": t.get("reason")})
    return portfolio.equity(entry[-1].close) / 1000.0 - 1, trades


def market_behaviour(m1, start, end):
    """Comportement du prix autour de la zone de valeur de la VEILLE, jour par jour."""
    by_day = defaultdict(list)
    for c in m1:
        if start - DAY <= c.timestamp < end:
            by_day[c.timestamp // DAY].append(c)
    stats = defaultdict(float)
    days = sorted(by_day)
    for prev, day in zip(days, days[1:]):
        if day < start // DAY or day != prev + 1:
            continue
        prof = volume_profile(by_day[prev])
        if prof is None:
            continue
        poc, vah, val = prof
        bars = by_day[day]
        low, high, close = min(b.low for b in bars), max(b.high for b in bars), bars[-1].close
        stats["jours"] += 1
        stats["largeur_zone"] += (vah - val) / poc
        if low < val:
            stats["sous_VAL"] += 1
            stats["sous_VAL_revient"] += close >= val
        if high > vah:
            stats["sur_VAH"] += 1
            stats["sur_VAH_revient"] += close <= vah
        stats["touche_POC"] += low <= poc <= high
    return stats


def year_job(year, since_iso):
    label, a, b = year
    m1 = [c for c in fetch_historical_candles(exchange_id="binance", symbol="ETH/USDT", timeframe="1m",
                                              since_iso=since_iso) if ms(a) - 60 * DAY <= c.timestamp < ms(b)]
    m15 = aggregate(m1, 15)
    day_bars = daily(m15)
    runs = {}
    for si, (_, kw) in enumerate(SETTINGS):
        for ci, spread in enumerate(SPREADS):
            ret, trades = run(m1, m15, ms(a), ms(b), kw, spread / 2)
            for t in trades:
                t["trend"], t["vol"] = context(day_bars, t["entry_t"] // DAY)
                prof, pc = t.get("profile"), t.get("prev_close")
                t["veille"] = ("?" if not prof or pc is None else "sur VAH" if pc > prof[1]
                               else "sous VAL" if pc < prof[2] else "dans la zone")
                t["risk"] = abs(t["entry"] - t["stop"]) / t["entry"] if t.get("stop") else None
            runs[(si, ci)] = (ret, trades)
    entry = [c for c in m15 if ms(a) <= c.timestamp < ms(b)]
    span = [d for d in day_bars if ms(a) // DAY <= d < ms(b) // DAY]
    trends = [context(day_bars, d)[0] for d in span]
    return label, {"runs": runs, "hold": entry[-1].close / entry[0].open - 1,
                   "vol": statistics.mean((day_bars[d][1] - day_bars[d][2]) / day_bars[d][3] for d in span),
                   "up_share": sum(t == "haussiere" for t in trends) / max(1, sum(t is not None for t in trends)),
                   "market": market_behaviour(m1, ms(a), ms(b))}


def pct(x):
    return "-" if x is None else f"{x * 100:+.1f} %"


def describe(trades):
    if not trades:
        return f"{'0 trade':<52}"
    wins = sum(t["pnl_pct"] > 0 for t in trades)
    total = sum(t["pnl_pct"] for t in trades)
    return (f"{len(trades):>4} tr. {wins / len(trades) * 100:>3.0f} % gagn. "
            f"{total / len(trades) * 100:+.2f} %/tr. somme {total * 100:+6.1f} %")


def breakdown(results, si, ci, title, key):
    print(f"  par {title} :")
    keys = sorted({key(t) for r in results.values() for t in r["runs"][(si, ci)][1]}, key=str)
    for k in keys:
        cells = [f"{label[:4]} {describe([t for t in r['runs'][(si, ci)][1] if key(t) == k])}"
                 for label, r in results.items()]
        print(f"    {str(k):<24} " + " | ".join(cells))


def bucket(value, buckets):
    if value is None:
        return "?"
    for lo, hi in buckets:
        if lo <= value < hi:
            return f"{lo * 100:.1f}-{min(hi, 0.99) * 100:.1f} %"
    return "?"


def main() -> None:
    with ProcessPoolExecutor(max_workers=len(YEARS)) as pool:
        results = dict(pool.map(partial(year_job, since_iso="2023-12-24T19:00:00Z"), YEARS))
    print("=== Marche ETH ===")
    for label, r in results.items():
        m = r["market"]
        n = m["jours"]
        print(f"{label:<18} garder l'actif {pct(r['hold']):>9} | amplitude journaliere moy. {r['vol'] * 100:.2f} % | "
              f"jours en tendance haussiere {r['up_share'] * 100:.0f} %")
        print(f"{'':<18} zone de la veille : largeur {m['largeur_zone'] / n * 100:.2f} % | sous le VAL {m['sous_VAL'] / n * 100:.0f} % "
              f"des jours (revient a la cloture {m['sous_VAL_revient'] / max(1, m['sous_VAL']) * 100:.0f} %) | sur le VAH "
              f"{m['sur_VAH'] / n * 100:.0f} % (revient {m['sur_VAH_revient'] / max(1, m['sur_VAH']) * 100:.0f} %) | "
              f"touche le POC {m['touche_POC'] / n * 100:.0f} %")
    for si, (sname, _) in enumerate(SETTINGS):
        for ci, spread in enumerate(SPREADS):
            print(f"\n=== {sname}, spread {spread * 100:.2f} % ===")
            for label, r in results.items():
                ret, trades = r["runs"][(si, ci)]
                print(f"{label:<18} rendement {pct(ret):>9} | {describe(trades)}")
            if ci == 1:
                continue
            breakdown(results, si, ci, "setup", lambda t: t.get("setup", "?"))
            breakdown(results, si, ci, "tendance a l'entree", lambda t: t["trend"] or "?")
            breakdown(results, si, ci, "cloture de la veille", lambda t: t["veille"])
            breakdown(results, si, ci, "distance au stop", lambda t: bucket(t["risk"], RISK_BUCKETS))
            breakdown(results, si, ci, "volatilite 20 j", lambda t: bucket(t["vol"], VOL_BUCKETS))
            breakdown(results, si, ci, "sortie", lambda t: t.get("exit_reason") or "?")


if __name__ == "__main__":
    main()
