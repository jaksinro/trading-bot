"""Atelier de backtest (EF-100) - moteur de la page `backtest.html`.

Demande de l'utilisateur du 2026-10-09 : "le probleme actuel c'est la non
visibilite des backtests. Je veux un outil a part entiere pour visualiser et
regler les strategies en backtest [...] visualiser chaque trade."

Ce module fait tourner une strategie sur l'historique avec le VRAI moteur des
bots (`Engine`, `RiskManager`, `BacktestExecutor` dimensionne sur le cash,
EF-99) et renvoie tout ce que la page affiche : bougies, trades (entree,
sortie, motif, stop et objectif du trade), courbe de capital, courbe "garder
l'actif", niveaux de la strategie bougie par bougie (EMA, POC/VAH/VAL...),
statistiques et resultats par semestre.

Le formulaire de la page est genere depuis la signature des strategies
(`catalog`) : un parametre ajoute a une strategie apparait sans toucher a la
page.

Couts : la page separe commission, spread et financement de nuit. Les
courtiers "sans commission" (CFD) se remunerent sur le spread et facturent le
maintien d'une position d'un jour sur l'autre : a zero, les resultats sont
optimistes. Le spread se modelise comme un cout de la moitie du spread a
chaque ordre (achat au-dessus du milieu, vente en dessous).
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone

import ccxt
import yaml

from tradingbot.backtest_lab import merge_dual_timeframe
from tradingbot.data_feed import extend_cache_to_now, fetch_historical_candles
from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import TRAILING_MODES, RiskConfig, RiskManager
from tradingbot.run_backtest import STRATEGY_REGISTRY

DAY_MS = 86_400_000
MAX_SWEEP_VALUES = 30
MAX_OVERLAYS = 8
SYMBOLS = ["ETH/USDT", "BTC/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT", "PAXG/USDT"]
TIMEFRAMES = ["5m", "15m", "1h", "4h", "1d"]

# Strategies proposees dans l'atelier (le market making a son propre moteur).
STRATEGIES = {
    "momentum_vote": ("Vote de momentum", "Detient si la majorite des horizons (en bougies) est en hausse."),
    "trend_regime": ("Regime de tendance (EMA)", "Achete au-dessus de l'EMA + marge, revend sous l'EMA - marge."),
    "volume_profile": ("Volume Profile", "Profil de la seance precedente : rebond POC, retour zone, cassure ; stop et objectif par trade."),
    "rsi_range": ("RSI survente / surachat", "Achete sous le seuil de survente, revend au-dessus du surachat."),
    "sma_cross": ("Croisement de moyennes", "Achete quand la moyenne courte passe au-dessus de la longue."),
    "mean_reversion": ("Bandes de Bollinger", "Achete sous la bande basse, revend au retour a la moyenne."),
    "mean_dip": ("Creux sous la moyenne", "Achete un creux marque sous la moyenne."),
    "dip_bounce": ("Rebond de creux", "Achete un repli en tendance haussiere."),
    "slope_dip": ("Pente de repli", "Achete apres une pente baissiere rapide."),
    "scalp_dip": ("Scalp sur repli", "Achete un repli court."),
    "buy_and_hold": ("Achat unique (reference)", "Achete au debut, ne revend jamais."),
}
PARAM_LABELS = {
    "lookbacks": "Horizons (bougies, separes par des virgules)", "threshold": "Part des horizons en hausse requise",
    "ema_period": "Periode de l'EMA (bougies)", "entry_buffer_pct": "Marge d'entree au-dessus de l'EMA",
    "exit_buffer_pct": "Marge de sortie sous l'EMA", "setups": "Setups (poc_rebound, value_area_reentry, breakout)",
    "session_hours": "Plage du profil (heures)", "rows": "Niveaux de prix du profil", "value_area_pct": "Zone de valeur",
    "reward_risk": "Objectif (multiple du risque)", "max_signal_age": "Confirmation max (bougies)",
    "pullback_max_depth": "Repli max dans la zone (part de sa largeur)", "stop_buffer_pct": "Marge sous le stop",
    "min_risk_pct": "Risque minimum", "period": "Periode du RSI", "oversold": "Seuil de survente",
    "overbought": "Seuil de surachat", "short_window": "Moyenne courte (bougies)", "long_window": "Moyenne longue (bougies)",
    "window": "Fenetre (bougies)", "num_std": "Ecarts-types", "trend_ma_period": "Moyenne de tendance (bougies)",
    "dip_threshold_pct": "Profondeur du creux", "force_trade_after_hours": "Forcer un trade apres (heures, vide = jamais)",
    "slope_threshold_pct": "Pente minimale", "candles_window": "Fenetre de pente (bougies)",
    "one_buy_per_slope": "Un seul achat par pente", "lookback": "Fenetre (bougies)",
    "allow_short": "Ventes a decouvert (schemas de vente)",
    "max_risk_pct": "Stop au plus loin a (0 = stop du pattern)",
    "wide_stop": "Stop plus loin : cap (rapproche) ou skip (trade ignore)",
    "fixed_stop_pct": "Stop fixe (0 = stop du pattern)", "fixed_target_pct": "Objectif fixe (0 = multiple du risque)",
}
HIDDEN_PARAMS = {"warmup_candles"}

# Reglages de risque et de couts du formulaire : (nom, libelle, type, defaut).
# "pct" : fraction affichee en %. "optional_pct" : vide = desactive.
RISK_FIELDS = [
    ("max_position_size_pct", "Taille de position (part du cash)", "pct", 1.0),
    ("stop_loss_pct", "Stop-loss (ecart au prix d'entree)", "optional_pct", None),
    ("take_profit_pct", "Objectif (ecart au prix d'entree)", "optional_pct", None),
    ("trailing_stop_pct", "Trailing stop", "optional_pct", None),
    ("trailing_mode", "Sens du trailing", "choice:" + ",".join(TRAILING_MODES), "distance"),
    ("trailing_arm_pct", "Armement du trailing (mode gain)", "optional_pct", None),
    ("profit_lock_arm_pct", "Verrou de gain : armement", "optional_pct", None),
    ("profit_lock_trigger_pct", "Verrou de gain : vente si le gain retombe a", "optional_pct", None),
    ("partial_take_profit_pct", "Sortie partielle a", "optional_pct", None),
    ("partial_exit_fraction", "Part vendue a la sortie partielle", "pct", 0.5),
    ("max_daily_loss_pct", "Perte max par jour (bloque les achats)", "pct", 0.05),
    ("max_concurrent_positions", "Positions simultanees", "int", 1),
]
COST_FIELDS = [
    ("fee_pct", "Commission par ordre", "pct", 0.0),
    ("spread_pct", "Spread (ecart achat/vente)", "pct", 0.0),
    ("overnight_pct", "Financement par nuit (CFD), position acheteuse", "pct", 0.0),
    # EF-104 : une vente a decouvert a son propre taux, qui peut etre un credit (negatif).
    ("overnight_short_pct", "Financement par nuit, vente a decouvert (negatif = recu)", "pct", 0.0),
]


# ------------------------------------------------------------------ catalogue
def _kind(default) -> str:
    if isinstance(default, bool):
        return "bool"
    if isinstance(default, int):
        return "int"
    if isinstance(default, float):
        return "float"
    if isinstance(default, (tuple, list)):
        return "list_int" if all(isinstance(x, int) for x in default) else "list_text"
    if default is None:
        return "optional_float"
    return "text"


def strategy_params(strategy_type: str) -> list[dict]:
    sig = inspect.signature(STRATEGY_REGISTRY[strategy_type].__init__)
    out = []
    for name, p in sig.parameters.items():
        if name == "self" or name in HIDDEN_PARAMS or p.kind in (p.VAR_KEYWORD, p.VAR_POSITIONAL):
            continue
        default = None if p.default is inspect.Parameter.empty else p.default
        kind = _kind(default)
        out.append({"name": name, "label": PARAM_LABELS.get(name, name.replace("_", " ")), "kind": kind,
                    "pct": name.endswith("_pct") and kind in ("float", "optional_float"),
                    "default": list(default) if isinstance(default, tuple) else default})
    return out


def bot_configs(config_dir) -> list[dict]:
    """Configs des bots (config/*.yml) chargeables dans l'atelier."""
    out = []
    for path in sorted(config_dir.glob("*.yml")):
        try:
            cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        strategy = dict(cfg.get("strategy") or {})
        if strategy.get("type") not in STRATEGIES:
            continue
        out.append({"name": cfg.get("name", path.stem), "symbol": cfg.get("symbol"), "timeframe": cfg.get("timeframe"),
                    "strategy": strategy, "risk": cfg.get("risk") or {},
                    "exit_check_timeframe": cfg.get("exit_check_timeframe")})
    return out


def catalog(config_dir) -> dict:
    return {
        "strategies": [{"type": k, "label": v[0], "description": v[1], "params": strategy_params(k)}
                       for k, v in STRATEGIES.items()],
        "risk_fields": [dict(zip(("name", "label", "kind", "default"), f)) for f in RISK_FIELDS],
        "cost_fields": [dict(zip(("name", "label", "kind", "default"), f)) for f in COST_FIELDS],
        "symbols": SYMBOLS, "timeframes": TIMEFRAMES, "bots": bot_configs(config_dir),
        "default_start": "2025-01-01",
    }


# ------------------------------------------------------------------ lecture du formulaire
def _coerce(spec: dict, value):
    kind, name = spec["kind"], spec["name"]
    if value is None or value == "":
        if kind.startswith("optional"):
            return None
        return spec["default"] if kind not in ("list_int", "list_text") else tuple(spec["default"])
    try:
        if kind == "bool":
            return bool(value) if not isinstance(value, str) else value.lower() in ("1", "true", "oui", "on")
        if kind == "int":
            return int(float(value))
        if kind in ("float", "optional_float"):
            return float(value)
        if kind in ("list_int", "list_text"):
            items = value if isinstance(value, (list, tuple)) else str(value).replace(";", ",").split(",")
            items = [str(x).strip() for x in items if str(x).strip()]
            if not items:
                raise ValueError("liste vide")
            return tuple(int(float(x)) for x in items) if kind == "list_int" else tuple(items)
        return str(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"parametre '{name}' invalide ({value!r}) : {e}") from None


def _date_ms(day: str, label: str) -> int:
    try:
        return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    except (TypeError, ValueError):
        raise ValueError(f"{label} : date attendue au format AAAA-MM-JJ") from None


def parse(payload: dict) -> dict:
    """Valide le formulaire ; leve ValueError avec un message lisible."""
    stype = payload.get("strategy_type")
    if stype not in STRATEGIES:
        raise ValueError(f"strategie inconnue : {stype!r}")
    raw = payload.get("params") or {}
    params = {s["name"]: _coerce(s, raw.get(s["name"])) for s in strategy_params(stype)}
    try:
        STRATEGY_REGISTRY[stype](**params)
    except (TypeError, ValueError) as e:
        raise ValueError(f"reglages de la strategie refuses : {e}") from None

    risk_raw = payload.get("risk") or {}
    risk = {}
    for name, label, kind, default in RISK_FIELDS:
        value = risk_raw.get(name)
        if kind == "int":
            risk[name] = _coerce({"name": name, "kind": "int", "default": default}, value)
        elif kind.startswith("choice:"):
            risk[name] = value or default
            if risk[name] not in kind[7:].split(","):
                raise ValueError(f"{label} : valeur inconnue {value!r}")
        else:
            risk[name] = _coerce({"name": name, "kind": "optional_float" if kind == "optional_pct" else "float",
                                  "default": default}, value)
    if not 0 < risk["max_position_size_pct"] <= 1:
        raise ValueError("taille de position entre 0 et 100 % du cash")
    costs_raw = payload.get("costs") or {}
    costs = {name: _coerce({"name": name, "kind": "float", "default": default}, costs_raw.get(name))
             for name, _, _, default in COST_FIELDS}
    if (any(v < 0 for k, v in costs.items() if k != "overnight_short_pct") or costs["spread_pct"] >= 0.2
            or costs["fee_pct"] >= 0.1 or abs(costs["overnight_short_pct"]) >= 0.05):
        raise ValueError("couts hors bornes (positifs sauf le credit de nuit des ventes, commission < 10 %, "
                         "spread < 20 %)")

    symbol = str(payload.get("symbol") or "ETH/USDT").upper()
    timeframe = payload.get("timeframe") or "1h"
    exit_tf = payload.get("exit_check_timeframe") or None
    for tf in filter(None, (timeframe, exit_tf)):
        if tf not in TIMEFRAMES:
            raise ValueError(f"unite de temps inconnue : {tf}")
    if exit_tf and ccxt.Exchange.parse_timeframe(exit_tf) >= ccxt.Exchange.parse_timeframe(timeframe):
        raise ValueError("la surveillance des sorties doit etre plus fine que l'unite de temps")
    start = _date_ms(payload.get("start") or "2025-01-01", "debut")
    end = (_date_ms(payload["end"], "fin") + DAY_MS if payload.get("end")
           else int(datetime.now(timezone.utc).timestamp() * 1000))
    if end <= start:
        raise ValueError("la fin doit etre apres le debut")
    capital = _coerce({"name": "capital", "kind": "float", "default": 1000.0}, payload.get("capital"))
    warmup = _coerce({"name": "warmup_bars", "kind": "int", "default": 500}, payload.get("warmup_bars"))
    if capital <= 0 or not 0 <= warmup <= 5000:
        raise ValueError("capital > 0 et bougies de chauffe entre 0 et 5000")
    return {"strategy_type": stype, "params": params, "risk": risk, "costs": costs, "symbol": symbol,
            "timeframe": timeframe, "exit_check_timeframe": exit_tf, "start": start, "end": end,
            "capital": capital, "warmup_bars": warmup}


# ------------------------------------------------------------------ donnees
def _fresh(symbol: str, timeframe: str, since_iso: str) -> list:
    """Bougies du cache, completees jusqu'a la derniere bougie close (le cache
    seul s'arretait au jour de son premier telechargement). Hors ligne : on
    garde le cache tel quel plutot que d'echouer."""
    candles = fetch_historical_candles(exchange_id="binance", symbol=symbol, timeframe=timeframe, since_iso=since_iso)
    try:
        if extend_cache_to_now("binance", symbol, timeframe):
            candles = fetch_historical_candles(exchange_id="binance", symbol=symbol, timeframe=timeframe,
                                               since_iso=since_iso)
    except Exception:  # noqa: BLE001 - reseau indisponible : le cache suffit
        pass
    return candles


def load_candles(spec: dict) -> tuple[list, list]:
    tf_ms = ccxt.Exchange.parse_timeframe(spec["timeframe"]) * 1000
    since = datetime.fromtimestamp((spec["start"] - spec["warmup_bars"] * tf_ms) / 1000, timezone.utc)
    candles = _fresh(spec["symbol"], spec["timeframe"], since.strftime("%Y-%m-%dT%H:%M:%SZ"))
    candles = [c for c in candles if c.timestamp < spec["end"]]
    fine = []
    if spec["exit_check_timeframe"]:
        start_iso = datetime.fromtimestamp(spec["start"] / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fine = [c for c in _fresh(spec["symbol"], spec["exit_check_timeframe"], start_iso)
                if spec["start"] <= c.timestamp < spec["end"]]
    return candles, fine


# ------------------------------------------------------------------ simulation
def simulate(spec: dict, candles: list, fine: list, light: bool = False) -> dict:
    """Backtest complet. `light` : statistiques seulement (balayage)."""
    warm = [c for c in candles if c.timestamp < spec["start"]][-spec["warmup_bars"]:] if spec["warmup_bars"] else []
    entry = [c for c in candles if spec["start"] <= c.timestamp < spec["end"]]
    if len(entry) < 2:
        raise ValueError("pas assez de bougies sur la periode choisie")
    strategy = STRATEGY_REGISTRY[spec["strategy_type"]](**spec["params"])
    for c in warm:
        # Chauffe des indicateurs, signaux ignores (comme run_paper). Une strategie
        # qui retient son etat "en position" est alignee par le moteur avant sa
        # premiere decision (`align_position`, EF-102) : le backtest commence a plat.
        strategy.on_candle(c)

    costs = spec["costs"]
    cost = costs["fee_pct"] + costs["spread_pct"] / 2   # cout par ordre
    risk = dict(spec["risk"])
    # Un achat "100 % du cash" + son cout depasserait le cash (refuse, EF-99).
    risk["max_position_size_pct"] = min(risk["max_position_size_pct"], 1 / (1 + cost) - 1e-9)
    portfolio = Portfolio(starting_capital=spec["capital"], fee_pct=cost)
    engine = Engine(strategy, RiskManager(RiskConfig(fee_pct=cost, **risk)), BacktestExecutor(portfolio), portfolio)

    levels: dict[int, dict] = {}       # lot_id -> stop/objectif propres au trade
    financing: dict[int, float] = {}   # lot_id -> financement de nuit cumule
    equity, overlays = [], {}
    last_day = entry[0].timestamp // DAY_MS
    timeline = (merge_dual_timeframe(entry, fine, spec["timeframe"], spec["exit_check_timeframe"])
                if fine else [(c, True) for c in entry])
    for candle, is_entry in timeline:
        day = candle.timestamp // DAY_MS
        if day > last_day and portfolio.positions and (costs["overnight_pct"] or costs["overnight_short_pct"]):
            for p in portfolio.positions:
                rate = costs["overnight_short_pct"] if p.direction == "short" else costs["overnight_pct"]
                charge = p.quantity * candle.open * rate * (day - last_day)
                portfolio.cash -= charge
                financing[p.lot_id] = financing.get(p.lot_id, 0.0) + charge
        last_day = max(last_day, day)
        if is_entry:
            engine.process_candle(candle)
        else:
            engine.process_price_update(candle)
        for p in portfolio.positions:
            if p.lot_id not in levels:
                levels[p.lot_id] = {"stop": p.stop_price, "target": p.target_price}
        if not is_entry:
            continue
        equity.append((candle.timestamp, portfolio.equity(candle.close)))
        if not light and hasattr(strategy, "chart_levels"):
            for lv in strategy.chart_levels() or []:
                key = lv.get("label", "")
                if key in overlays or len(overlays) < MAX_OVERLAYS:
                    overlays.setdefault(key, {"kind": lv.get("kind", "level"), "points": []})["points"].append(
                        [candle.timestamp, round(float(lv["price"]), 8)])

    trades = []
    for t in portfolio.trade_history:
        lot = t.get("lot_id")
        # Le financement d'un lot est impute a sa vente finale (pas a une sortie partielle).
        fin = 0.0 if t.get("partial") else financing.pop(lot, 0.0)
        cost_basis = t["entry_price"] * t["quantity"]
        net = t["pnl"] - fin
        trades.append({
            "direction": t.get("direction", "long"), "entry_t": t["entry_timestamp"], "entry_p": t["entry_price"], "exit_t": t["timestamp"],
            "exit_p": t["exit_price"], "qty": t["quantity"], "pnl": net,
            "pnl_pct": net / cost_basis if cost_basis else 0.0, "fees": t.get("fees_paid", 0.0),
            "financing": fin, "reason": t.get("reason") or "signal", "partial": bool(t.get("partial")),
            "stop": (levels.get(lot) or {}).get("stop"), "target": (levels.get(lot) or {}).get("target"),
        })
    last = entry[-1]
    open_positions = [{"direction": p.direction, "entry_t": p.entry_timestamp, "entry_p": p.avg_entry_price,
                       "qty": p.quantity,
                       "pnl": (p.quantity * (last.close - p.avg_entry_price) * (-1 if p.direction == "short" else 1)
                               - p.entry_fee - financing.get(p.lot_id, 0.0)),
                       "stop": p.stop_price, "target": p.target_price} for p in portfolio.positions]
    financing_total = sum(t["financing"] for t in trades) + sum(financing.get(p.lot_id, 0.0) for p in portfolio.positions)
    result = {"stats": _stats(spec, entry, equity, trades, open_positions, financing_total),
              "semesters": _semesters(entry, equity, spec["capital"])}
    if not light:
        result.update({
            "candles": [[c.timestamp, c.open, c.high, c.low, c.close] for c in entry],
            "equity": [[t, round(v, 4)] for t, v in equity],
            "hold": [[c.timestamp, round(spec["capital"] * (1 - cost) * c.close / entry[0].open, 4)] for c in entry],
            "trades": trades, "open_positions": open_positions,
            "overlays": [{"label": k, **v} for k, v in overlays.items()],
            "warnings": _warnings(spec, warm),
        })
    return result


def _stats(spec, entry, equity, trades, open_positions, financing_total) -> dict:
    capital = spec["capital"]
    values = [v for _, v in equity]
    peak, max_dd = capital, 0.0
    for v in values:
        peak = max(peak, v)
        max_dd = max(max_dd, 1 - v / peak if peak > 0 else 0.0)
    closed = [t for t in trades if not t["partial"]]
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gross_win, gross_loss = sum(t["pnl"] for t in wins), -sum(t["pnl"] for t in losses)
    durations = [(t["exit_t"] - t["entry_t"]) / 3_600_000 for t in closed]
    in_pos = sum(max(0, t["exit_t"] - t["entry_t"]) for t in closed)
    in_pos += sum(max(0, entry[-1].timestamp - p["entry_t"]) for p in open_positions)
    span = max(1, entry[-1].timestamp - entry[0].timestamp)
    return {
        "return": values[-1] / capital - 1, "final_equity": values[-1],
        "hold_return": entry[-1].close / entry[0].open - 1, "max_drawdown": max_dd,
        "trades": len(closed), "win_rate": len(wins) / len(trades) if trades else None,
        "avg_win_pct": sum(t["pnl_pct"] for t in wins) / len(wins) if wins else None,
        "avg_loss_pct": sum(t["pnl_pct"] for t in losses) / len(losses) if losses else None,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else None,
        "best_pct": max((t["pnl_pct"] for t in trades), default=None),
        "worst_pct": min((t["pnl_pct"] for t in trades), default=None),
        "avg_hours": sum(durations) / len(durations) if durations else None,
        "exposure": min(1.0, in_pos / span), "costs_paid": sum(t["fees"] for t in trades),
        "financing_paid": financing_total, "open_positions": len(open_positions),
        # EF-104 : achats et ventes a decouvert separes, pour voir lequel des deux sens gagne.
        "by_direction": {d: {"trades": len([t for t in closed if t["direction"] == d]),
                             "pnl": sum(t["pnl"] for t in trades if t["direction"] == d),
                             "wins": len([t for t in trades if t["direction"] == d and t["pnl"] > 0])}
                         for d in ("long", "short")},
    }


def _semesters(entry, equity, capital: float) -> list[dict]:
    """Rendement par semestre civil : un reglage qui ne gagne que sur une
    fenetre n'est pas robuste (meme discipline que les bancs de mesure)."""
    out, eq = [], dict(equity)
    first = datetime.fromtimestamp(entry[0].timestamp / 1000, timezone.utc)
    last = datetime.fromtimestamp(entry[-1].timestamp / 1000, timezone.utc)
    year, half = first.year, 0 if first.month <= 6 else 1
    while (year, half) <= (last.year, 0 if last.month <= 6 else 1):
        a = int(datetime(year, 1 + 6 * half, 1, tzinfo=timezone.utc).timestamp() * 1000)
        b = int(datetime(year + half, 7 if half == 0 else 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        inside = [c for c in entry if a <= c.timestamp < b]
        if len(inside) >= 2:
            before = [v for t, v in equity if t < a]
            start_eq = before[-1] if before else capital
            out.append({"label": f"S{half + 1} {year}" + ("*" if b > entry[-1].timestamp + DAY_MS else ""),
                        "return": eq[inside[-1].timestamp] / start_eq - 1,
                        "hold": inside[-1].close / inside[0].open - 1})
        year, half = (year, 1) if half == 0 else (year + 1, 0)
    return out


def _warnings(spec, warm) -> list[str]:
    out = []
    if spec["warmup_bars"] and len(warm) < spec["warmup_bars"]:
        out.append(f"Chauffe incomplete : {len(warm)} bougies avant le debut au lieu de {spec['warmup_bars']}.")
    costs = spec["costs"]
    if not costs["spread_pct"] and not costs["fee_pct"]:
        out.append("Aucun cout de transaction : resultats optimistes. Renseigne le spread de ton courtier.")
    if spec["params"].get("allow_short"):
        out.append("Ventes a decouvert : possibles en backtest et chez un courtier CFD (Capital.com), "
                   "refusees par un compte au comptant comme Binance.")
    if datetime.fromtimestamp(spec["start"] / 1000, timezone.utc).year < 2025:
        out.append("Periode avant 2025 : tu as demande de ne pas juger les strategies sur 2023-2024.")
    return out


def run(payload: dict) -> dict:
    spec = parse(payload)
    candles, fine = load_candles(spec)
    return simulate(spec, candles, fine)


def sweep(payload: dict) -> dict:
    """Balaye UN parametre (strategie, risque ou cout) sur une liste de valeurs :
    memes bougies, un backtest par valeur, statistiques et semestres."""
    target = str(payload.get("target") or "")
    values = payload.get("values") or []
    if not isinstance(values, list) or not 2 <= len(values) <= MAX_SWEEP_VALUES:
        raise ValueError(f"entre 2 et {MAX_SWEEP_VALUES} valeurs a tester")
    section, _, name = target.partition(".")
    if section not in ("params", "risk", "costs") or not name:
        raise ValueError("parametre a balayer invalide")
    base = parse(payload)
    if name not in base[section]:
        raise ValueError(f"parametre inconnu : {target}")
    candles, fine = load_candles(base)
    rows = []
    for value in values:
        trial = dict(payload)
        trial[section] = {**(payload.get(section) or {}), name: value}
        rows.append({"value": value, **simulate(parse(trial), candles, fine, light=True)})
    return {"target": target, "rows": rows}
