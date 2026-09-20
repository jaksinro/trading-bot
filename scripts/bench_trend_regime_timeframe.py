"""Banc de mesure : `trend_regime` surveille en bougies 1h (deploye) contre
bougies 1d (question de l'utilisateur : "surveiller une seule fois par jour
et pas toutes les heures").

Protocole IDENTIQUE a celui qui a valide le modele (STC §3.51) :
- 70 % d'entrainement / 30 % de test, coupe a l'index ; l'EMA est chauffee en
  continu, le rendement de test est mesure de la coupe a la fin ;
- execution decalee d'UNE bougie (le signal se lit a la cloture, l'ordre part
  a l'ouverture suivante) - donc 1 h de retard en 1h, 24 h de retard en 1d :
  c'est le vrai cout de ne regarder qu'une fois par jour, et il est mesure,
  pas suppose ;
- frais 0,1 % par cote (taker Binance), pleinement investi sur l'equite
  COURANTE (jamais sur un capital fige, voir la note de §3.51) ;
- reglage choisi sur l'ENTRAINEMENT, test regarde une fois ; robustesse = la
  grille entiere (45 reglages) evaluee sur le test.

Le banc precedent vivait dans un fichier temporaire et a disparu : celui-ci
est commis pour que les chiffres restent reproductibles.

Usage : python scripts/bench_trend_regime_timeframe.py
"""
from __future__ import annotations

import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tradingbot.data_feed import fetch_historical_candles  # noqa: E402
from tradingbot.strategies.trend_regime import TrendRegimeStrategy  # noqa: E402
from tradingbot.types import Candle, Side  # noqa: E402

FEE = 0.001
SINCE = "2019-01-01T00:00:00Z"
TRAIN_SHARE = 0.70

# Reglage deploye par crypto (config/*_TREND_REGIME.yml), en bougies 1h.
DEPLOYED_EMA_1H = {"ETH/USDT": 500, "BTC/USDT": 1000, "DOGE/USDT": 2000}
BUFFERS = (0.0, 0.03, 0.06)
GRID_EMA = {"1h": (200, 500, 1000, 2000, 4000), "1d": (8, 21, 42, 83, 167)}


@dataclass
class Result:
    ret_test: float
    bh_test: float
    trades: int
    max_dd: float


def simulate(candles: list[Candle], ema: int, entry: float, exit_: float,
             split: int, delay: int = 1) -> Result:
    strategy = TrendRegimeStrategy(ema_period=ema, entry_buffer_pct=entry, exit_buffer_pct=exit_)
    cash, qty = 1000.0, 0.0
    pending: list[tuple[int, Side]] = []   # (index d'execution, cote)
    trades = 0
    equity_at_split = None
    peak, max_dd = 0.0, 0.0
    for i, c in enumerate(candles):
        # Execution des ordres arrives a echeance, a l'OUVERTURE de la bougie.
        due = [side for at, side in pending if at <= i]
        pending = [(at, side) for at, side in pending if at > i]
        for side in due:
            if side == Side.BUY and qty == 0:
                qty = cash * (1 - FEE) / c.open
                cash = 0.0
                if i >= split:      # trades comptes sur la fenetre de TEST seulement
                    trades += 1
            elif side == Side.SELL and qty > 0:
                cash = qty * c.open * (1 - FEE)
                qty = 0.0
        signal = strategy.on_candle(c)
        if signal is not None:
            if delay == 0:
                # Variante DIAGNOSTIQUE : execution a la cloture qui a produit
                # le signal - impossible en pratique, sert a isoler le cout du
                # retard. (Premiere version de ce banc : delay=0 tombait dans
                # la file et s'executait a la bougie suivante comme delay=1,
                # d'ou un ecart de 0,0 partout - bug repere, corrige ici.)
                if signal.side == Side.BUY and qty == 0:
                    qty = cash * (1 - FEE) / c.close
                    cash = 0.0
                    if i >= split:
                        trades += 1
                elif signal.side == Side.SELL and qty > 0:
                    cash = qty * c.close * (1 - FEE)
                    qty = 0.0
            else:
                pending.append((i + delay, signal.side))
        equity = cash + qty * c.close
        if i == split:
            equity_at_split = equity
            peak, max_dd = equity, 0.0
        if i >= split:
            peak = max(peak, equity)
            max_dd = max(max_dd, 1 - equity / peak)
    final = cash + qty * candles[-1].close
    return Result(
        ret_test=final / equity_at_split - 1,
        bh_test=candles[-1].close / candles[split].close - 1,
        trades=trades, max_dd=max_dd,
    )


def evaluate(symbol: str, timeframe: str) -> dict:
    candles = fetch_historical_candles(exchange_id="binance", symbol=symbol, timeframe=timeframe, since_iso=SINCE)
    split = int(len(candles) * TRAIN_SHARE)
    ema_deployed = DEPLOYED_EMA_1H[symbol] if timeframe == "1h" else round(DEPLOYED_EMA_1H[symbol] / 24)

    deployed = simulate(candles, ema_deployed, 0.03, 0.0, split)

    # Grille : choix sur l'entrainement (rendement de la coupe a la fin de
    # l'entrainement = on simule avec split=0 et on ne lit que... plus simple :
    # on rejoue avec la coupe placee A LA FIN de l'entrainement pour lire son
    # rendement, puis on evalue le retenu sur le test).
    grid_test = []
    best_train, best_params = None, None
    for ema in GRID_EMA[timeframe]:
        for entry in BUFFERS:
            for exit_ in BUFFERS:
                train = simulate(candles[:split], ema, entry, exit_, split=0)
                test = simulate(candles, ema, entry, exit_, split)
                grid_test.append(test)
                if best_train is None or train.ret_test > best_train:
                    best_train, best_params = train.ret_test, (ema, entry, exit_)
    chosen = simulate(candles, *best_params, split)
    beating = sum(1 for r in grid_test if r.ret_test > r.bh_test)
    return {
        "symbol": symbol, "tf": timeframe, "n": len(candles), "ema_deployed": ema_deployed,
        "deployed": deployed,
        "chosen_params": best_params, "chosen": chosen,
        "grid_median": statistics.median(r.ret_test for r in grid_test),
        "grid_beating": beating, "grid_size": len(grid_test),
    }


def pct(x: float) -> str:
    return f"{x * 100:+.1f} %"


def main() -> None:
    rows = []
    for symbol in DEPLOYED_EMA_1H:
        for tf in ("1h", "1d"):
            rows.append(evaluate(symbol, tf))

    print("=== trend_regime : surveillance 1h (deploye) contre 1d (question) ===")
    print("Test = 30 % finaux, execution decalee d'une bougie, frais 0,1 %/cote\n")
    hdr = f"{'crypto':<10}{'tf':<4}{'EMA':>5} {'bot (test)':>11} {'buy&hold':>10} {'trades':>7} {'baisse max':>11} | {'grille: mediane':>15} {'bat b&h':>8}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        d = r["deployed"]
        print(f"{r['symbol']:<10}{r['tf']:<4}{r['ema_deployed']:>5} {pct(d.ret_test):>11} {pct(d.bh_test):>10} "
              f"{d.trades:>7} {pct(-d.max_dd):>11} | {pct(r['grid_median']):>15} {r['grid_beating']:>5}/{r['grid_size']}")

    print()
    print("=== Robustesse : la coupe entrainement/test deplacee (reglage deploye) ===")
    print("Une seule fenetre peut mentir. Rendement du bot sur la tranche de test, pour trois coupes.")
    print(f"{'crypto':<10}{'tf':<4} {'coupe 60/40':>22} {'coupe 70/30':>22} {'coupe 80/20':>22}   (buy&hold entre parentheses)")
    for symbol in DEPLOYED_EMA_1H:
        for tf in ("1h", "1d"):
            candles = fetch_historical_candles(exchange_id="binance", symbol=symbol, timeframe=tf, since_iso=SINCE)
            ema = DEPLOYED_EMA_1H[symbol] if tf == "1h" else round(DEPLOYED_EMA_1H[symbol] / 24)
            cells = []
            for share in (0.60, 0.70, 0.80):
                r = simulate(candles, ema, 0.03, 0.0, int(len(candles) * share))
                cells.append(f"{pct(r.ret_test)} ({pct(r.bh_test)})")
            print(f"{symbol:<10}{tf:<4} " + " ".join(f"{c:>22}" for c in cells))

    print("\n=== Reglage choisi sur l'ENTRAINEMENT seul, puis test regarde une fois ===")
    print(f"{'crypto':<10}{'tf':<4} {'retenu (ema, entree, sortie)':<30} {'bot (test)':>11} {'buy&hold':>10} {'trades':>7}")
    for r in rows:
        ema, en, ex = r["chosen_params"]
        c = r["chosen"]
        print(f"{r['symbol']:<10}{r['tf']:<4} {f'({ema}, {en:.0%}, {ex:.0%})':<30} {pct(c.ret_test):>11} {pct(c.bh_test):>10} {c.trades:>7}")


if __name__ == "__main__":
    main()
