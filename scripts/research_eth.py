"""Recherche d'un algorithme ETH/USDT (EF-98), demande de l'utilisateur du
2026-10-01 : "met en place un algo rentable sur l'ETH et seulement lui".

Discipline (fixee AVANT de regarder les resultats) :
- donnees 2025-2026 seulement (consigne de l'utilisateur) ; fin 2024 sert
  uniquement a initialiser les indicateurs ;
- ENTRAINEMENT = 2025 (semestres S1 et S2) : seule periode utilisee pour
  chercher et regler ;
- TEST = 2026-01-01 -> fin des donnees, regarde UNE fois, apres avoir fige le
  choix dans `research_eth_choix.json` (mode --test) ;
- frais 0,1 % par ordre (proportionnels au changement d'exposition) ;
- long ou a plat seulement (comptant, pas de levier ni de vente a decouvert) ;
- signal calcule a la cloture d'une bougie, execute a l'ouverture de la
  bougie 1h suivante ; un indicateur 4h ou jour n'est utilise qu'une fois sa
  bougie close (pas de regard dans le futur).

Criteres de selection (fixes a l'avance) : gagnant sur CHACUN des deux
semestres 2025 apres frais ; classement sur la mediane du ratio de Sharpe
de la regle ET de ses reglages voisins (un plateau, pas un pic isole).

Usage : python scripts/research_eth.py            (recherche sur 2025)
        python scripts/research_eth.py --test     (evaluation unique sur 2026)
"""
from __future__ import annotations

import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tradingbot.data_feed import fetch_historical_candles  # noqa: E402

FEE = 0.001
H_PER_YEAR = 24 * 365
TRAIN = [("S1 2025", "2025-01-01", "2025-07-01"), ("S2 2025", "2025-07-01", "2026-01-01")]
TRAIN_ALL = ("2025", "2025-01-01", "2026-01-01")
TEST = [("S1 2026", "2026-01-01", "2026-07-01"), ("S2 2026*", "2026-07-01", "2027-01-01")]
TEST_ALL = ("2026*", "2026-01-01", "2027-01-01")
CHOICE_PATH = Path(__file__).with_name("research_eth_choix.json")
TF_HOURS = {"1h": 1, "4h": 4, "1d": 24}


# ------------------------------------------------------------------ donnees
def load() -> pd.DataFrame:
    raw = fetch_historical_candles(exchange_id="binance", symbol="ETH/USDT", timeframe="1h",
                                   since_iso="2024-09-01T00:00:00Z")
    df = pd.DataFrame([(c.timestamp, c.open, c.high, c.low, c.close, c.volume) for c in raw],
                      columns=["ts", "open", "high", "low", "close", "volume"])
    df = df[df.ts >= ms("2024-09-01")].drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    return df


def ms(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1000)


def resample(h1: pd.DataFrame, tf: str) -> pd.DataFrame:
    if tf == "1h":
        return h1
    step = TF_HOURS[tf] * 3_600_000
    g = h1.assign(b=h1.ts // step * step).groupby("b")
    out = pd.DataFrame({"ts": g.ts.first().index, "open": g.open.first().values, "high": g.high.max().values,
                        "low": g.low.min().values, "close": g.close.last().values,
                        "volume": g.volume.sum().values, "n": g.size().values})
    return out[out.n == TF_HOURS[tf]].drop(columns="n").reset_index(drop=True)   # bougies completes


def to_hourly(h1: pd.DataFrame, htf: pd.DataFrame, tf: str, exposure: np.ndarray) -> np.ndarray:
    """Exposition decidee a la cloture de chaque bougie `tf`, appliquee a partir
    de la bougie 1h qui OUVRE a cette cloture (aucun regard dans le futur)."""
    known_at = htf.ts.values + TF_HOURS[tf] * 3_600_000
    idx = np.searchsorted(known_at, h1.ts.values, side="right") - 1
    out = np.zeros(len(h1))
    ok = idx >= 0
    out[ok] = exposure[idx[ok]]
    return out


# ------------------------------------------------------------------ indicateurs
def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def sma(x, n):
    return pd.Series(x).rolling(n).mean().values


def rsi(close, n):
    d = np.diff(close, prepend=close[0])
    up = pd.Series(np.clip(d, 0, None)).ewm(alpha=1 / n, adjust=False).mean()
    dn = pd.Series(np.clip(-d, 0, None)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50).values


def hysteresis(enter: np.ndarray, leave: np.ndarray) -> np.ndarray:
    """1 a partir d'une condition d'entree, jusqu'a la condition de sortie."""
    out = np.zeros(len(enter))
    state = 0.0
    for i in range(len(enter)):
        if state == 0 and enter[i]:
            state = 1.0
        elif state == 1 and leave[i]:
            state = 0.0
        out[i] = state
    return out


# ------------------------------------------------------------------ familles de regles
def fam_ema_trend(d, n, buf):
    e = ema(d.close.values, n)
    return hysteresis(d.close.values > e * (1 + buf), d.close.values < e)


def fam_ema_cross(d, fast, slow):
    return (ema(d.close.values, fast) > ema(d.close.values, slow)).astype(float)


def fam_donchian(d, n_in, n_out):
    hi = d.high.rolling(n_in).max().shift(1).values
    lo = d.low.rolling(n_out).min().shift(1).values
    return hysteresis(d.close.values > hi, d.close.values < lo)


def fam_momentum_vote(d, lookbacks, mode):
    c = d.close.values
    votes = np.mean([np.concatenate([np.full(n, np.nan), c[n:] / c[:-n] - 1]) > 0 for n in lookbacks], axis=0)
    return votes if mode == "graduel" else (votes > 0.5).astype(float)


def fam_rsi2(d, entry, trend_n, exit_n):
    c = d.close.values
    r = rsi(c, 2)
    trend = sma(c, trend_n)
    return hysteresis((r < entry) & (c > trend), (c > sma(c, exit_n)) | (c < trend * 0.97))


def vol_target(h1: pd.DataFrame, exposure: np.ndarray, target: float) -> np.ndarray:
    """Exposition reduite quand la volatilite realisee (30 jours, connue a la
    cloture precedente) depasse la cible annualisee. Jamais au-dela de 1."""
    r = np.log(h1.close).diff()
    vol = (r.rolling(24 * 30).std() * np.sqrt(H_PER_YEAR)).shift(1).values
    scale = np.where(np.isfinite(vol) & (vol > 0), np.minimum(1.0, target / np.where(vol > 0, vol, 1)), 1.0)
    return exposure * scale


GRID = []
for tf, ns in (("1h", (200, 500, 1000, 2000)), ("4h", (50, 125, 250, 500)), ("1d", (20, 50, 100, 200))):
    for n, buf in itertools.product(ns, (0.0, 0.01, 0.03, 0.05)):
        GRID.append(("ema_trend", tf, (n, buf)))
for tf, pairs in (("1h", ((20, 100), (50, 200), (100, 500), (200, 1000))),
                  ("4h", ((10, 50), (20, 100), (50, 200), (100, 300))),
                  ("1d", ((5, 20), (10, 50), (20, 100), (50, 200)))):
    for p in pairs:
        GRID.append(("ema_cross", tf, p))
for tf, ins, outs in (("4h", (20, 55, 120, 240), (10, 20, 55)), ("1d", (10, 20, 55, 100), (5, 10, 20))):
    for a, b in itertools.product(ins, outs):
        if b < a:
            GRID.append(("donchian", tf, (a, b)))
for lbs in ((7, 14, 30), (14, 30, 60), (30, 60, 90), (7, 14, 30, 60, 90), (14, 30, 60, 90, 120)):
    for mode in ("graduel", "majorite"):
        GRID.append(("momentum_vote", "1d", (lbs, mode)))
for tf in ("1h", "4h", "1d"):
    for entry, trend_n, exit_n in itertools.product((5, 10, 20), (100, 200), (5, 10)):
        GRID.append(("rsi2", tf, (entry, trend_n, exit_n)))
FAMILIES = {"ema_trend": fam_ema_trend, "ema_cross": fam_ema_cross, "donchian": fam_donchian,
            "momentum_vote": fam_momentum_vote, "rsi2": fam_rsi2}
VOL_TARGETS = (None, 0.6, 0.4)


def label(rule) -> str:
    fam, tf, p, vt = rule
    return f"{fam} {tf} {p}" + (f" + vol {int(vt * 100)}%" if vt else "")


# ------------------------------------------------------------------ simulation
def exposure_of(h1, cache, rule):
    fam, tf, params, vt = rule
    key = (fam, tf, params)
    if key not in cache:
        d = cache.setdefault(("bars", tf), resample(h1, tf)) if tf != "1h" else h1
        cache[key] = to_hourly(h1, d, tf, FAMILIES[fam](d, *params))
    e = cache[key]
    return vol_target(h1, e, vt) if vt else e


def simulate(h1: pd.DataFrame, exposure: np.ndarray, start: str, end: str) -> dict:
    """Bougie i : exposition `exposure[i]` tenue de son ouverture a l'ouverture
    suivante ; frais sur chaque changement d'exposition."""
    o = h1.open.values
    ret = np.append(o[1:] / o[:-1] - 1, 0.0)
    prev = np.concatenate([[0.0], exposure[:-1]])
    pnl = exposure * ret - FEE * np.abs(exposure - prev)
    m = (h1.ts.values >= ms(start)) & (h1.ts.values < ms(end))
    r = pnl[m]
    if len(r) == 0:
        return {"ret": 0.0, "sharpe": 0.0, "dd": 0.0, "trades": 0, "expo": 0.0, "bh": 0.0}
    eq = np.cumprod(1 + r)
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    entries = int(np.sum((exposure[m] > 0) & (prev[m] == 0)))
    sd = r.std()
    return {"ret": eq[-1] - 1, "sharpe": (r.mean() / sd * np.sqrt(H_PER_YEAR)) if sd > 0 else 0.0,
            "dd": float(np.max(1 - eq / peak)), "trades": entries, "expo": float(np.mean(exposure[m])),
            "bh": o[m][-1] / o[m][0] - 1}


def neighbours(rule, rules):
    """Reglages voisins : meme famille, unite de temps et cible de volatilite,
    un seul parametre change d'un cran dans la grille."""
    fam, tf, p, vt = rule
    same = [r for r in rules if r[0] == fam and r[1] == tf and r[3] == vt and r != rule]
    if not isinstance(p, tuple) or fam == "momentum_vote":
        return same[:0]
    out = []
    for r in same:
        diff = [i for i in range(len(p)) if r[2][i] != p[i]]
        if len(diff) == 1:
            i = diff[0]
            values = sorted({x[2][i] for x in same + [rule] if all(x[2][j] == p[j] for j in range(len(p)) if j != i)})
            if abs(values.index(r[2][i]) - values.index(p[i])) == 1:
                out.append(r)
    return out


def pct(x):
    return f"{x * 100:+.1f}%"


def research() -> None:
    h1 = load()
    rules = [(f, tf, p, vt) for f, tf, p in GRID for vt in VOL_TARGETS]
    cache, res = {}, {}
    for rule in rules:
        e = exposure_of(h1, cache, rule)
        res[rule] = {"all": simulate(h1, e, *TRAIN_ALL[1:]), **{w: simulate(h1, e, a, b) for w, a, b in TRAIN}}
    bh = res[rules[0]]
    print(f"Regles testees : {len(rules)} ({len(GRID)} reglages x {len(VOL_TARGETS)} options de volatilite)")
    print(f"ETH garde sans rien faire : 2025 {pct(bh['all']['bh'])} (S1 {pct(bh['S1 2025']['bh'])}, S2 {pct(bh['S2 2025']['bh'])})")
    for rule in rules:
        nb = neighbours(rule, rules)
        res[rule]["robust"] = float(np.median([res[r]["all"]["sharpe"] for r in [rule] + nb]))
        res[rule]["n_nb"] = len(nb)
    ok = [r for r in rules if all(res[r][w]["ret"] > 0 for w, _, _ in TRAIN)]
    print(f"Regles gagnantes sur les 2 semestres 2025 : {len(ok)}/{len(rules)}\n")
    ranked = sorted(ok, key=lambda r: -res[r]["robust"])
    print(f"{'regle (classee par Sharpe median avec ses voisines)':<58}{'robuste':>8}{'Sharpe':>8}{'2025':>9}{'S1':>8}{'S2':>8}{'baisse max':>11}{'trades':>8}{'expo':>6}")
    for r in ranked[:30]:
        x = res[r]
        print(f"{label(r):<58}{x['robust']:>8.2f}{x['all']['sharpe']:>8.2f}{pct(x['all']['ret']):>9}{pct(x['S1 2025']['ret']):>8}"
              f"{pct(x['S2 2025']['ret']):>8}{pct(-x['all']['dd']):>11}{x['all']['trades']:>8}{x['all']['expo']:>6.0%}")
    print("\nMeilleure regle de chaque famille (memes criteres) :")
    for fam in FAMILIES:
        best = next((r for r in ranked if r[0] == fam), None)
        print(f"  {fam:<15}" + (f"{label(best):<50} robuste {res[best]['robust']:.2f}, 2025 {pct(res[best]['all']['ret'])}"
                                  if best else "aucune regle gagnante sur les 2 semestres"))
    json.dump({"rules": [[r[0], r[1], list(r[2]) if not isinstance(r[2][0], tuple) else [list(r[2][0]), r[2][1]], r[3]]
                         for r in ranked[:30]]}, open(Path(__file__).with_name("research_eth_classement.json"), "w"), indent=1)


def test() -> None:
    choice = json.load(open(CHOICE_PATH))
    h1 = load()
    cache = {}
    print(f"Choix fige le {choice['fige_le']} : {choice['pourquoi']}\n")
    print(f"{'regle':<58}{'S1 2026':>10}{'S2 2026*':>10}{'2026*':>9}{'Sharpe':>8}{'baisse max':>11}{'trades':>8}")
    for raw in choice["rules"]:
        fam, tf, p, vt = raw
        p = (tuple(p[0]), p[1]) if fam == "momentum_vote" else tuple(p)
        rule = (fam, tf, p, vt)
        e = exposure_of(h1, cache, rule)
        a = simulate(h1, e, *TEST_ALL[1:])
        ws = [simulate(h1, e, x, y) for _, x, y in TEST]
        print(f"{label(rule):<58}{pct(ws[0]['ret']):>10}{pct(ws[1]['ret']):>10}{pct(a['ret']):>9}{a['sharpe']:>8.2f}{pct(-a['dd']):>11}{a['trades']:>8}")
    a = simulate(h1, np.ones(len(h1)), *TEST_ALL[1:])
    ws = [simulate(h1, np.ones(len(h1)), x, y) for _, x, y in TEST]
    print(f"{'ETH garde sans rien faire':<58}{pct(ws[0]['ret']):>10}{pct(ws[1]['ret']):>10}{pct(a['ret']):>9}{a['sharpe']:>8.2f}{pct(-a['dd']):>11}")


if __name__ == "__main__":
    test() if "--test" in sys.argv else research()
