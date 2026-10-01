"""Banc de mesure : deux indicateurs TradingView appliques au bot ETH_youenn,
question de l'utilisateur du 2026-09-28 ("y a t'il des indicateurs interessants
qu'on peut reprendre de TradingView ?").

- ADX (Wilder, 14) comme FILTRE D'ENTREE : l'achat de la strategie n'est
  accepte que si l'ADX depasse un seuil (tendance franche). Vise les faux
  departs, qui finissent en majorite au stop-loss (-2 %).
- Chandelier Exit comme TRAILING : vente si le cours passe sous
  plus haut depuis l'achat - k x ATR(22). La distance s'adapte a la
  volatilite. Variante : plus haut des CLOTURES (celui que le bot suit deja),
  pas des meches comme sur TradingView - un peu plus prudent.

Meme protocole que `bench_exit_rules.py` (moteur reel, sorties verifiees en
5 min, frais 0,1 %, 2025-2026 seulement par semestre - consigne de
l'utilisateur). Reference = la config actuelle d'ETH_youenn (stop-loss 2 %,
trailing "50 % du gain rendu, arme a 2 %"). Rien ici ne modifie les bots :
les indicateurs n'existent que dans ce banc tant qu'ils ne sont pas retenus.

Usage : python scripts/bench_indicators.py            (ETH_youenn, ADX et Chandelier)
        python scripts/bench_indicators.py --autres   (filtre ADX sur BTC, DOGE et
        ETH_TREND_REGIME tels que deployes : sans stop-loss ni trailing, seule la
        strategie vend - 12 fenetres de plus pour juger l'ADX)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bench_exit_rules import WARMUP, WINDOWS, ms, pct  # noqa: E402

from tradingbot.backtest_lab import merge_dual_timeframe  # noqa: E402
from tradingbot.data_feed import fetch_historical_candles  # noqa: E402
from bench_common import CashEngine as Engine  # noqa: E402  (taille sur le cash, voir bench_common)
from tradingbot.execution.backtest_executor import BacktestExecutor  # noqa: E402
from tradingbot.portfolio import Portfolio  # noqa: E402
from tradingbot.risk.risk_manager import RiskConfig, RiskManager  # noqa: E402
from tradingbot.strategies.trend_regime import TrendRegimeStrategy  # noqa: E402
from tradingbot.types import Side  # noqa: E402


class Indicators:
    """ADX(14) et ATR(n) de Wilder, mis a jour a chaque bougie 1h."""

    def __init__(self, adx_period: int = 14, atr_period: int = 22):
        self.n, self.m = adx_period, atr_period
        self.prev = None
        self.tr14 = self.pdm14 = self.mdm14 = None
        self.adx = None
        self.atr = None
        self._dx_seed: list[float] = []
        self._tr_seed: list[float] = []

    def update(self, c) -> None:
        if self.prev is None:
            self.prev = c
            return
        p = self.prev
        tr = max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
        up, down = c.high - p.high, p.low - c.low
        pdm = up if up > down and up > 0 else 0.0
        mdm = down if down > up and down > 0 else 0.0
        self.prev = c
        # ATR(m) pour le Chandelier
        if self.atr is None:
            self._tr_seed.append(tr)
            if len(self._tr_seed) == self.m:
                self.atr = sum(self._tr_seed) / self.m
        else:
            self.atr = (self.atr * (self.m - 1) + tr) / self.m
        # ADX(n)
        if self.tr14 is None:
            self.tr14, self.pdm14, self.mdm14 = tr, pdm, mdm
            return
        n = self.n
        self.tr14 = self.tr14 - self.tr14 / n + tr
        self.pdm14 = self.pdm14 - self.pdm14 / n + pdm
        self.mdm14 = self.mdm14 - self.mdm14 / n + mdm
        if self.tr14 <= 0:
            return
        pdi, mdi = 100 * self.pdm14 / self.tr14, 100 * self.mdm14 / self.tr14
        dx = 100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi > 0 else 0.0
        if self.adx is None:
            self._dx_seed.append(dx)
            if len(self._dx_seed) == n:
                self.adx = sum(self._dx_seed) / n
        else:
            self.adx = (self.adx * (n - 1) + dx) / n


class FilteredStrategy:
    """trend_regime + indicateurs ; refuse l'achat si l'ADX est sous le seuil."""

    def __init__(self, inner, ind: Indicators, adx_min: float | None):
        self.inner, self.ind, self.adx_min = inner, ind, adx_min

    def on_candle(self, c):
        self.ind.update(c)
        signal = self.inner.on_candle(c)
        if (signal is not None and signal.side == Side.BUY and self.adx_min is not None
                and (self.ind.adx is None or self.ind.adx < self.adx_min)):
            return None
        return signal


class ChandelierRisk(RiskManager):
    """Trailing = Chandelier Exit (plus haut - k x ATR) au lieu du trailing de la config."""

    def __init__(self, config: RiskConfig, ind: Indicators, k: float):
        super().__init__(config)
        self.ind, self.k = ind, k

    def should_trailing_stop(self, position, current_price):
        if not position.is_open or position.quantity <= 0 or self.ind.atr is None:
            return False
        peak = max(position.peak_price, position.avg_entry_price)
        return current_price <= peak - self.k * self.ind.atr


# (libelle, seuil ADX, k du Chandelier ou None = trailing de la config)
# ATR 1h median ~0,8 % du cours (2025-2026) : 3 x ATR ~ 2,4 % sous le plus haut ;
# 6 et 10 x ATR ajoutes pour ne pas comparer seulement des stops serres.
VARIANTS = [
    ("config actuelle (gain 50 %, arme 2 %)", None, None),
    ("+ filtre ADX > 20", 20, None),
    ("+ filtre ADX > 25", 25, None),
    ("+ filtre ADX > 30", 30, None),
    ("Chandelier 2 x ATR au lieu du trailing", None, 2.0),
    ("Chandelier 3 x ATR au lieu du trailing", None, 3.0),
    ("Chandelier 4 x ATR au lieu du trailing", None, 4.0),
    ("Chandelier 6 x ATR au lieu du trailing", None, 6.0),
    ("Chandelier 10 x ATR au lieu du trailing", None, 10.0),
    ("ADX > 25 + Chandelier 3 x ATR", 25, 3.0),
]


def run(h1, m5, start, end, adx_min, chandelier_k):
    warm = [c for c in h1 if c.timestamp < start][-WARMUP:]
    entry = [c for c in h1 if start <= c.timestamp < end]
    fine = [c for c in m5 if start <= c.timestamp < end]
    ind = Indicators()
    strategy = FilteredStrategy(TrendRegimeStrategy(ema_period=500, entry_buffer_pct=0.03, exit_buffer_pct=0.0), ind, adx_min)
    for c in warm:
        strategy.on_candle(c)   # rechauffe EMA, ADX et ATR ; signaux ignores
    config = RiskConfig(
        max_position_size_pct=0.99, stop_loss_pct=0.02, take_profit_pct=None, max_daily_loss_pct=0.05,
        max_concurrent_positions=1, fee_pct=0.001,
        trailing_stop_pct=0.5, trailing_mode="gain", trailing_arm_pct=0.02,
    )
    risk = ChandelierRisk(config, ind, chandelier_k) if chandelier_k else RiskManager(config)
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.001)
    engine = Engine(strategy, risk, BacktestExecutor(portfolio), portfolio)
    equity_peak, max_dd = 1000.0, 0.0
    for candle, is_entry in merge_dual_timeframe(entry, fine, "1h", "5m"):
        if is_entry:
            engine.process_candle(candle)
            equity = portfolio.equity(candle.close)
            equity_peak = max(equity_peak, equity)
            max_dd = max(max_dd, 1 - equity / equity_peak)
        else:
            engine.process_price_update(candle)
    trades = portfolio.trade_history
    stops = sum(1 for t in trades if t.get("reason") == "stop_loss")
    return {
        "ret": portfolio.equity(entry[-1].close) / 1000.0 - 1,
        "bh": entry[-1].close / entry[0].open - 1,
        "trades": len(trades), "stops": stops,
        "win": sum(t["pnl"] > 0 for t in trades) / len(trades) if trades else 0.0,
        "dd": max_dd,
    }


# Bots trend_regime deployes sans sortie de risque (config/*_TREND_REGIME.yml).
OTHER_BOTS = [("BTC_TREND_REGIME", "BTC/USDT", 1000), ("DOGE_TREND_REGIME", "DOGE/USDT", 2000),
              ("ETH_TREND_REGIME", "ETH/USDT", 500)]
ADX_LEVELS = [None, 20, 25, 30]


def run_strategy_only(h1, start, end, ema, adx_min):
    """Comme le bot deploye : pas de stop-loss ni de trailing, seule la strategie
    vend ; donc pas besoin des bougies 5 min. Rechauffe = `ema` + 100 bougies."""
    warm = [c for c in h1 if c.timestamp < start][-(ema + 100):]
    entry = [c for c in h1 if start <= c.timestamp < end]
    ind = Indicators()
    strategy = FilteredStrategy(TrendRegimeStrategy(ema_period=ema, entry_buffer_pct=0.03, exit_buffer_pct=0.0), ind, adx_min)
    for c in warm:
        strategy.on_candle(c)
    config = RiskConfig(max_position_size_pct=0.99, stop_loss_pct=None, take_profit_pct=None,
                        max_daily_loss_pct=1.0, max_concurrent_positions=1, fee_pct=0.001)
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.001)
    engine = Engine(strategy, RiskManager(config), BacktestExecutor(portfolio), portfolio)
    equity_peak, max_dd = 1000.0, 0.0
    for c in entry:
        engine.process_candle(c)
        equity = portfolio.equity(c.close)
        equity_peak = max(equity_peak, equity)
        max_dd = max(max_dd, 1 - equity / equity_peak)
    trades = portfolio.trade_history
    return {"ret": portfolio.equity(entry[-1].close) / 1000.0 - 1, "bh": entry[-1].close / entry[0].open - 1,
            "trades": len(trades), "win": sum(x["pnl"] > 0 for x in trades) / len(trades) if trades else 0.0,
            "dd": max_dd}


def main_others() -> None:
    wins = {level: 0 for level in ADX_LEVELS[1:]}
    total = 0
    for name, symbol, ema in OTHER_BOTS:
        # Donnees d'avant 2025 : seulement pour rechauffer l'EMA (jusqu'a 2100 bougies).
        h1 = fetch_historical_candles(exchange_id="binance", symbol=symbol, timeframe="1h", since_iso="2024-08-01T00:00:00Z")
        res = {lvl: [run_strategy_only(h1, ms(a), ms(b), ema, lvl) for _, a, b in WINDOWS] for lvl in ADX_LEVELS}
        print(f"=== {name} (EMA {ema}, sans stop-loss ni trailing) ===")
        print(f"{'regle':<28}" + "".join(f"{w:>10}" for w, _, _ in WINDOWS) + "   trades/semestre")
        for lvl in ADX_LEVELS:
            label = "tel que deploye" if lvl is None else f"+ filtre ADX > {lvl}"
            rows = res[lvl]
            print(f"{label:<28}" + "".join(f"{pct(r['ret']):>10}" for r in rows)
                  + "   " + " ".join(f"{r['trades']:>3}" for r in rows))
            if lvl is not None:
                wins[lvl] += sum(r["ret"] > b["ret"] + 1e-9 for r, b in zip(rows, res[None]))
        print(f"{'buy & hold':<28}" + "".join(f"{pct(r['bh']):>10}" for r in res[None]))
        print()
        total += len(WINDOWS)
    print("=== Bilan : fenetres ou le filtre ADX fait mieux que sans filtre ===")
    for lvl, n in wins.items():
        print(f"ADX > {lvl} : {n}/{total}")


def main() -> None:
    h1 = fetch_historical_candles(exchange_id="binance", symbol="ETH/USDT", timeframe="1h", since_iso="2024-11-01T00:00:00Z")
    m5 = fetch_historical_candles(exchange_id="binance", symbol="ETH/USDT", timeframe="5m", since_iso="2025-01-01T00:00:00Z")
    results = {label: [run(h1, m5, ms(a), ms(b), adx, k) for _, a, b in WINDOWS] for label, adx, k in VARIANTS}

    ref = results[VARIANTS[0][0]]
    head = f"{'regle':<42}" + "".join(f"{w:>10}" for w, _, _ in WINDOWS) + f"{'mieux que ref.':>16}"
    print("=== Rendement par semestre (2025-2026) ===")
    print(head)
    print("-" * len(head))
    for label, *_ in VARIANTS:
        rows = results[label]
        better = "reference" if rows is ref else f"{sum(r['ret'] > f['ret'] + 1e-9 for r, f in zip(rows, ref))}/{len(rows)}"
        print(f"{label:<42}" + "".join(f"{pct(r['ret']):>10}" for r in rows) + f"{better:>16}")
    print(f"{'buy & hold ETH':<42}" + "".join(f"{pct(r['bh']):>10}" for r in ref))
    print("\n=== Detail : trades (dont stop-loss) / % gagnants / baisse max ===")
    for label, *_ in VARIANTS:
        print(f"{label:<42}" + " | ".join(
            f"{r['trades']:>3} ({r['stops']:>2}) {r['win'] * 100:>3.0f}% {r['dd'] * 100:>3.0f}%" for r in results[label]))


if __name__ == "__main__":
    main_others() if "--autres" in sys.argv else main()
