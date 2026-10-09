"""Volume Profile : stop et objectif verifies EN COURS DE BOUGIE, achats et
ventes a decouvert (mesure de l'EF-104).

Remarque de l'utilisateur (2026-10-09) : sur TradingView, stop-loss et
take-profit sont surveilles en continu ; s'ils l'etaient dans le backtest,
beaucoup de trades Volume Profile ressortiraient gagnants.

Le banc precedent (bench_volume_profile.py) verifiait stop et objectif sur les
CLOTURES 5 min et executait au cours de cloture : une meche qui touche
l'objectif puis redescend dans les 5 minutes n'etait pas comptee, alors qu'un
vrai ordre a cours limite l'aurait execute. Ici, comme de vrais ordres :
- surveillance sur bougies 1 MINUTE, contre leur PLUS BAS et leur PLUS HAUT ;
- execution AU NIVEAU (stop ou objectif), ou au cours d'ouverture si la
  minute s'ouvre deja au-dela (ecart) ;
- si stop ET objectif sont touches dans la meme minute, l'ordre reel est
  inconnu : hypothese PRUDENTE (stop d'abord), et le nombre de ces cas est
  affiche - avec aussi le resultat dans l'hypothese inverse, pour borner.

Entrees inchangees : bougies 15 min (construites depuis le 1 min), profil de
la veille, memes setups. 2025-2026 par semestre (consigne de l'utilisateur),
ETH / BTC / DOGE, sans commission (courtiers vises) puis avec un spread
illustratif de 0,1 % aller-retour.

EF-104 : les schemas de vente du document (`allow_short`) sont mesures a cote
des achats seuls. Pour une vente a decouvert le stop est AU-DESSUS (touche par
le plus haut) et l'objectif en dessous (touche par le plus bas). Colonnes
"ventes" : part des trades qui sont des ventes, et leur taux de reussite.

Usage : python scripts/bench_vp_intrabar.py
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bench_exit_rules import ms, pct  # noqa: E402

from tradingbot.backtest_lab import merge_dual_timeframe  # noqa: E402
from tradingbot.data_feed import fetch_historical_candles  # noqa: E402
from tradingbot.engine import Engine  # noqa: E402
from tradingbot.execution.backtest_executor import BacktestExecutor  # noqa: E402
from tradingbot.portfolio import Portfolio  # noqa: E402
from tradingbot.risk.risk_manager import RiskConfig, RiskManager  # noqa: E402
from tradingbot.strategies.volume_profile import VolumeProfileStrategy  # noqa: E402
from tradingbot.types import Candle  # noqa: E402

WINDOWS = [("S1 2025", "2025-01-01", "2025-07-01"), ("S2 2025", "2025-07-01", "2026-01-01"),
           ("S1 2026", "2026-01-01", "2026-07-01"), ("S2 2026*", "2026-07-01", "2026-09-15")]
MARKETS = ["ETH/USDT", "BTC/USDT", "DOGE/USDT"]
ALL = ["poc_rebound", "value_area_reentry", "breakout"]
SETUPS = [("1. rebond sur le POC", ["poc_rebound"]), ("2. retour dans la zone", ["value_area_reentry"]),
          ("3. cassure", ["breakout"]), ("les 3 ensemble", ALL)]


class IntrabarEngine(Engine):
    """Stop et objectif du trade traites comme de vrais ordres poses chez le
    courtier : touches par le plus bas / plus haut de la bougie, executes au
    niveau. `stop_first` : hypothese quand les deux sont touches dans la meme
    bougie (inconnaissable avec des bougies 1 min)."""

    def __init__(self, *a, stop_first: bool = True, **kw):
        super().__init__(*a, **kw)
        self.stop_first, self.ambiguous = stop_first, 0

    def check_lot_exits(self, candle: Candle) -> list[str]:
        messages = []
        for p in list(self.executor.get_positions()):
            if p.stop_price is None and p.target_price is None:
                continue
            short = p.direction == "short"
            hit_stop = p.stop_price is not None and (candle.high >= p.stop_price if short else candle.low <= p.stop_price)
            hit_target = p.target_price is not None and (candle.low <= p.target_price if short
                                                         else candle.high >= p.target_price)
            if hit_stop and hit_target:
                self.ambiguous += 1
                hit_stop, hit_target = (True, False) if self.stop_first else (False, True)
            # Ecart a l'ouverture : execute au cours d'ouverture, pire que le niveau pour un stop.
            worse, better = (max, min) if short else (min, max)
            if hit_stop:
                level, reason = worse(candle.open, p.stop_price), "stop_trade"
            elif hit_target:
                level, reason = better(candle.open, p.target_price), "objectif_trade"
            else:
                continue
            fill = Candle(timestamp=candle.timestamp, open=level, high=level, low=level, close=level, volume=0.0)
            self._close_position(p, fill, reason=reason)
            messages.append(reason)
        return messages + super().check_lot_exits(candle)


def aggregate(m1: list[Candle], minutes: int) -> list[Candle]:
    step, out, bucket = minutes * 60_000, [], []
    for c in m1:
        if bucket and c.timestamp // step != bucket[0].timestamp // step:
            if len(bucket) == minutes:
                out.append(_merge(bucket, step))
            bucket = []
        bucket.append(c)
    return out


def _merge(b, step):
    return Candle(timestamp=b[0].timestamp // step * step, open=b[0].open, high=max(x.high for x in b),
                  low=min(x.low for x in b), close=b[-1].close, volume=sum(x.volume for x in b))


def run(m1, m5, m15, start, end, setups, mode, cost, stop_first=True, allow_short=False):
    warm = [c for c in m15 if start - 2 * 86_400_000 <= c.timestamp < start]
    entry = [c for c in m15 if start <= c.timestamp < end]
    strategy = VolumeProfileStrategy(setups=setups, allow_short=allow_short)
    for c in warm:
        strategy.on_candle(c)
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=cost)
    config = RiskConfig(max_position_size_pct=1 / (1 + cost) - 1e-9, stop_loss_pct=None, take_profit_pct=None,
                        max_daily_loss_pct=1.0, max_concurrent_positions=1, fee_pct=cost)
    if mode == "intrabar":
        engine = IntrabarEngine(strategy, RiskManager(config), BacktestExecutor(portfolio), portfolio,
                                stop_first=stop_first)
        fine, ftf = [c for c in m1 if start <= c.timestamp < end], "1m"
    else:
        engine = Engine(strategy, RiskManager(config), BacktestExecutor(portfolio), portfolio)
        fine, ftf = [c for c in m5 if start <= c.timestamp < end], "5m"
    for candle, is_entry in merge_dual_timeframe(entry, fine, "15m", ftf):
        (engine.process_candle if is_entry else engine.process_price_update)(candle)
    trades = portfolio.trade_history
    return {"ret": portfolio.equity(entry[-1].close) / 1000.0 - 1, "trades": len(trades),
            "wins": sum(t["pnl"] > 0 for t in trades), "amb": getattr(engine, "ambiguous", 0),
            "shorts": sum(t.get("direction") == "short" for t in trades),
            "short_wins": sum(t.get("direction") == "short" and t["pnl"] > 0 for t in trades)}


def main() -> None:
    data = {}
    for m in MARKETS:
        m1 = [c for c in fetch_historical_candles(exchange_id="binance", symbol=m, timeframe="1m",
                                                  since_iso="2024-12-25T00:00:00Z") if c.timestamp >= ms("2024-12-25")]
        data[m] = (m1, aggregate(m1, 5), aggregate(m1, 15))
        print(f"{m} : {len(m1):,} bougies 1 min".replace(",", " "), flush=True)

    # Toutes les lignes en surveillance 1 minute (plus haut / plus bas), comme des ordres poses chez le courtier.
    rows = [("achats seuls, stop d'abord", 0.0, True, False),
            ("achats + ventes, stop d'abord", 0.0, True, True),
            ("achats + ventes, objectif d'abord", 0.0, False, True),
            ("achats + ventes, spread 0,1 %", 0.0005, True, True)]
    print(f"\n{'setup / variante':<58}{'fen. gagnantes':>15}{'mediane':>10}{'pire':>9}{'trades/sem.':>13}"
          f"{'% gagnants':>12}{'ventes':>8}{'% gagn. ventes':>16}{'ambigus':>9}")
    for name, setups in SETUPS:
        for label, cost, sf, short in rows:
            cells = [run(*data[m], ms(a), ms(b), setups, "intrabar", cost, sf, short)
                     for m in MARKETS for _, a, b in WINDOWS]
            rets = [x["ret"] for x in cells]
            n = sum(x["trades"] for x in cells)
            ns = sum(x["shorts"] for x in cells)
            short_cells = (f"{100 * ns / max(n, 1):>7.0f}%{100 * sum(x['short_wins'] for x in cells) / ns:>15.0f}%"
                           if ns else f"{'-':>8}{'-':>16}")
            print(f"{name + ' - ' + label:<58}{sum(r > 0 for r in rets):>12}/12{pct(statistics.median(rets)):>10}"
                  f"{pct(min(rets)):>9}{n / len(cells):>13.0f}{100 * sum(x['wins'] for x in cells) / max(n, 1):>11.0f}%"
                  f"{short_cells}{sum(x['amb'] for x in cells):>9}", flush=True)
        print()


if __name__ == "__main__":
    main()
