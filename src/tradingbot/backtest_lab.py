"""Outil de test de bot en backtest - un seul bot, une seule periode, un
rapport simple a la fin.

Remplace les scripts jetables du scratchpad (simulate_month.py,
optimize_dip_bounce_check.py, etc.) qui s'accumulaient au fil des demandes
avec des jeux de parametres improvises et non tracables. Ici : un seul point
d'entree, on choisit explicitement le type de bot, la devise, la periode et
les parametres, et on obtient un rapport de performance a la fin (console +
fichier).

Usage interactif (pose les questions une par une) :
    python -m tradingbot.backtest_lab

Usage scriptable (tout en arguments, pour rejouer un test exact) :
    python -m tradingbot.backtest_lab \\
        --strategy dip_bounce_hourly --symbol BTC/USDT --exchange binance \\
        --since 2025-04-01 --until 2025-04-30 --capital 1000 \\
        --param dip_threshold_pct=0.005 \\
        --risk profit_lock_arm_pct=0.01 --risk profit_lock_trigger_pct=0.007

    python -m tradingbot.backtest_lab --list-strategies
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import ccxt

from tradingbot.analysis.atr_sizer import AtrSizer
from tradingbot.analysis.price_level_sizer import PriceLevelSizer
from tradingbot.analysis.trend_filter import TrendFilter
from tradingbot.data_feed import fetch_historical_candles, filter_candles
from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.mm_engine import MarketMakingEngine
from tradingbot.portfolio import Portfolio
from tradingbot.profile_source import attach_preloaded
from tradingbot.reporting.stats import compute_buy_and_hold_return_pct, compute_report
from tradingbot.risk.risk_manager import MarketMakingConfig, RiskConfig, RiskManager
from tradingbot.run_backtest import STRATEGY_REGISTRY
from tradingbot.types import Candle

REPORT_DIR = Path("backtest_reports")

# Meme convention que control_server.py (dupliquee plutot que partagee : ce
# module ne doit rien importer de control_server, qui importe DE lui).
VALID_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h", "1d"}


@dataclass(frozen=True)
class ParamSpec:
    name: str
    label: str
    default: float
    kind: type  # int ou float
    unit: str = ""  # "%" affiche default*100 et divise la saisie par 100


@dataclass(frozen=True)
class StrategyPreset:
    key: str
    label: str
    strategy_type: str  # cle reelle dans STRATEGY_REGISTRY
    engine: str  # "standard" ou "market_making"
    timeframe: str | None  # force si != None, sinon demande a l'utilisateur
    param_specs: list[ParamSpec]
    risk_param_specs: list[ParamSpec]
    supports_stop_loss: bool
    # Valeur appliquee quand le champ stop-loss est laisse vide alors que
    # `supports_stop_loss` est True - 2% par defaut (comportement historique
    # de sma_cross/scalp_dip/mean_reversion), mais `None` pour dip_bounce
    # (stop-loss optionnel : vide = reste desactive, ne bascule pas sur 2%
    # dans le dos de l'utilisateur - voir 3.35 dans STC.md).
    default_stop_loss_pct: float | None = 0.02


PRESETS: dict[str, StrategyPreset] = {
    "sma_cross": StrategyPreset(
        key="sma_cross", label="SMA cross (croisement de moyennes mobiles)",
        strategy_type="sma_cross", engine="standard", timeframe=None,
        param_specs=[
            ParamSpec("short_window", "Fenetre courte (bougies)", 10, int),
            ParamSpec("long_window", "Fenetre longue (bougies)", 30, int),
        ],
        risk_param_specs=[], supports_stop_loss=True,
    ),
    "scalp_dip": StrategyPreset(
        key="scalp_dip", label="Scalp sur creux",
        strategy_type="scalp_dip", engine="standard", timeframe=None,
        param_specs=[
            ParamSpec("lookback", "Fenetre de reference (bougies)", 20, int),
            ParamSpec("dip_threshold_pct", "Seuil de creux", 0.003, float, unit="%"),
        ],
        risk_param_specs=[], supports_stop_loss=True,
    ),
    "mean_reversion": StrategyPreset(
        key="mean_reversion", label="Retour a la moyenne (bandes de Bollinger)",
        strategy_type="mean_reversion", engine="standard", timeframe=None,
        param_specs=[
            ParamSpec("window", "Fenetre (bougies)", 20, int),
            ParamSpec("num_std", "Largeur des bandes (ecarts-types)", 2.0, float),
        ],
        risk_param_specs=[], supports_stop_loss=True,
    ),
    "rsi_range": StrategyPreset(
        key="rsi_range", label="Range trading par oscillateur RSI",
        strategy_type="rsi_range", engine="standard", timeframe=None,
        param_specs=[
            ParamSpec("period", "Periode RSI (bougies)", 14, int),
            ParamSpec("oversold", "Seuil de survente", 30.0, float),
            ParamSpec("overbought", "Seuil de surachat", 70.0, float),
        ],
        risk_param_specs=[], supports_stop_loss=True,
    ),
    "mean_dip": StrategyPreset(
        key="mean_dip", label="Creux vs moyenne mobile (5 min, ~1h, stop-loss + trailing uniquement)",
        strategy_type="mean_dip", engine="standard", timeframe="5m",
        param_specs=[
            ParamSpec("window", "Fenetre (bougies)", 12, int),
            ParamSpec("num_std", "Largeur des bandes (ecarts-types)", 2.0, float),
        ],
        risk_param_specs=[], supports_stop_loss=True, default_stop_loss_pct=0.02,
    ),
    "slope_dip": StrategyPreset(
        key="slope_dip", label="Detecteur de pente (1 min, trailing stop uniquement)",
        strategy_type="slope_dip", engine="standard", timeframe="1m",
        param_specs=[
            ParamSpec("slope_threshold_pct", "Seuil de pente entre 2 bougies (%)", 0.005, float, unit="%"),
            ParamSpec("candles_window", "Nombre de bougies pour mesurer la pente", 2, int),
            ParamSpec("one_buy_per_slope", "Limiter a 1 achat par pente continue (0=non, 1=oui)", 0, int),
        ],
        risk_param_specs=[], supports_stop_loss=True, default_stop_loss_pct=None,
    ),
    "market_making": StrategyPreset(
        key="market_making", label="Market making (cotation bid/ask continue)",
        strategy_type="market_making", engine="market_making", timeframe=None,
        param_specs=[
            ParamSpec("spread_pct", "Ecart bid/ask", 0.004, float, unit="%"),
            ParamSpec("order_size_quote", "Taille d'ordre (en devise de cotation)", 100.0, float),
            ParamSpec("max_inventory_quote", "Inventaire max (en devise de cotation)", 500.0, float),
            ParamSpec("skew_factor", "Facteur d'asymetrie (skew)", 1.0, float),
        ],
        risk_param_specs=[], supports_stop_loss=False,
    ),
    "dip_bounce_hourly": StrategyPreset(
        key="dip_bounce_hourly", label="Rebond de creux - horaire (fenetre 24h, stop-loss optionnel)",
        strategy_type="dip_bounce", engine="standard", timeframe="1h",
        param_specs=[
            ParamSpec("dip_threshold_pct", "Seuil de proximite au creux", 0.005, float, unit="%"),
            ParamSpec("force_trade_after_hours", "Forcer un trade apres N heures sans achat (0 = desactive)", 0, float),
        ],
        risk_param_specs=[
            ParamSpec("profit_lock_arm_pct", "Armement du verrou de gain", 0.005, float, unit="%"),
            ParamSpec("profit_lock_trigger_pct", "Declenchement du verrou de gain", 0.0043, float, unit="%"),
        ],
        supports_stop_loss=True, default_stop_loss_pct=None,
    ),
    "dip_bounce_minute": StrategyPreset(
        key="dip_bounce_minute", label="Rebond de creux - minute (fenetre 1h, stop-loss optionnel)",
        strategy_type="dip_bounce", engine="standard", timeframe="1m",
        param_specs=[
            ParamSpec("dip_threshold_pct", "Seuil de proximite au creux", 0.005, float, unit="%"),
            ParamSpec("force_trade_after_hours", "Forcer un trade apres N heures sans achat (0 = desactive)", 0, float),
        ],
        risk_param_specs=[
            ParamSpec("profit_lock_arm_pct", "Armement du verrou de gain", 0.005, float, unit="%"),
            ParamSpec("profit_lock_trigger_pct", "Declenchement du verrou de gain", 0.0043, float, unit="%"),
        ],
        supports_stop_loss=True, default_stop_loss_pct=None,
    ),
    "trend_regime": StrategyPreset(
        key="trend_regime", label="Regime de tendance (investi en hausse, liquidites en baisse)",
        strategy_type="trend_regime", engine="standard", timeframe=None,
        param_specs=[
            ParamSpec("ema_period", "Fenetre de tendance (en bougies)", 500, int),
            ParamSpec("entry_buffer_pct", "Marge au-dessus de la tendance pour entrer", 0.03, float, unit="%"),
            ParamSpec("exit_buffer_pct", "Marge sous la tendance pour sortir", 0.0, float, unit="%"),
        ],
        risk_param_specs=[],
        supports_stop_loss=True, default_stop_loss_pct=None,
    ),
    "buy_and_hold": StrategyPreset(
        key="buy_and_hold", label="Buy & hold (achat unique, jamais revendu)",
        strategy_type="buy_and_hold", engine="standard", timeframe=None,
        param_specs=[], risk_param_specs=[], supports_stop_loss=False,
    ),
}

DIP_BOUNCE_TREND_MA_PERIOD = {"dip_bounce_hourly": 24, "dip_bounce_minute": 60}


def _iso_date_to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _parse_kv_list(pairs: list[str]) -> dict[str, str]:
    result = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"parametre invalide '{pair}', attendu cle=valeur")
        key, value = pair.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _resolve_params(specs: list[ParamSpec], overrides: dict[str, str]) -> dict[str, float | int]:
    valid_names = {spec.name for spec in specs}
    unknown = set(overrides) - valid_names
    if unknown:
        raise ValueError(f"parametre(s) inconnu(s) pour cette strategie : {sorted(unknown)} (attendus : {sorted(valid_names)})")
    resolved = {}
    for spec in specs:
        if spec.name in overrides:
            raw = float(overrides[spec.name])
            value = raw / 100 if spec.unit == "%" else raw
        else:
            value = spec.default
        resolved[spec.name] = spec.kind(value)
    return resolved


def _prompt(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    raw = input(f"{label}{suffix} : ").strip()
    return raw if raw else (default or "")


def _prompt_params_interactively(specs: list[ParamSpec]) -> dict[str, str]:
    overrides = {}
    for spec in specs:
        shown_default = spec.default * 100 if spec.unit == "%" else spec.default
        raw = _prompt(f"  {spec.label}{' (%)' if spec.unit == '%' else ''}", str(shown_default))
        overrides[spec.name] = raw
    return overrides


def run_interactive() -> argparse.Namespace:
    print("=== Laboratoire de backtest ===\n")
    print("Types de bot disponibles :")
    keys = list(PRESETS.keys())
    for i, key in enumerate(keys, start=1):
        print(f"  {i}. {PRESETS[key].label}")
    choice_idx = int(_prompt("Choix", "1")) - 1
    strategy_key = keys[choice_idx] if 0 <= choice_idx < len(keys) else keys[0]
    preset = PRESETS[strategy_key]

    symbol = _prompt("Devise / paire (ex: BTC/USDT)", "BTC/USDT")
    exchange = _prompt("Exchange", "binance")
    timeframe_raw = ""
    if preset.timeframe is None:
        timeframe_raw = _prompt("Timeframe (1m/5m/15m/1h/4h/1d)", "1h")
    since = _prompt("Debut de periode (AAAA-MM-JJ)", "2025-01-01")
    until = _prompt("Fin de periode (AAAA-MM-JJ, vide = maintenant)", "")
    capital = _prompt("Capital de depart", "1000")
    repeat = _prompt("Nombre de sous-periodes a tester (1 = un seul test, N = decoupe la periode en N et rejoue le test sur chacune)", "1")

    print(f"\nParametres de la strategie ({preset.label}) :")
    param_overrides = _prompt_params_interactively(preset.param_specs)

    risk_overrides = {}
    if preset.risk_param_specs:
        print("\nParametres de risque specifiques :")
        risk_overrides = _prompt_params_interactively(preset.risk_param_specs)

    stop_loss_raw = ""
    take_profit_raw = ""
    if preset.supports_stop_loss:
        stop_loss_raw = _prompt("Stop-loss (%)", "2")
        take_profit_raw = _prompt("Take-profit (%, vide = desactive)", "")
    max_concurrent_raw = ""
    max_position_size_raw = ""
    max_daily_loss_raw = ""
    trailing_stop_raw = ""
    fee_pct_raw = ""
    partial_take_profit_raw = ""
    partial_exit_fraction_raw = ""
    price_level_sizing = False
    price_level_min_raw = ""
    price_level_max_raw = ""
    trend_filter_enabled = False
    trend_filter_ema_period_raw = ""
    atr_sizing_enabled = False
    atr_period_raw = ""
    atr_baseline_period_raw = ""
    atr_min_multiplier_raw = ""
    if preset.engine != "market_making":
        max_concurrent_raw = _prompt("Positions simultanees max", "1")
        max_position_size_raw = _prompt("Taille position max (%)", "10")
        max_daily_loss_raw = _prompt("Perte max journaliere (%)", "5")
        trailing_stop_raw = _prompt("Trailing stop (%, vide = desactive)", "")
        fee_pct_raw = _prompt("Frais par ordre (%)", "0.1")
        partial_take_profit_raw = _prompt("Palier de sortie partielle (%, vide = desactive)", "")
        if partial_take_profit_raw:
            partial_exit_fraction_raw = _prompt("  Fraction vendue au palier (%)", "50")
        price_level_sizing = _prompt("Activer le sizing par niveau de prix (o/n)", "n").lower().startswith("o")
        if price_level_sizing:
            price_level_min_raw = _prompt("  Taille minimum (%)", "50")
            price_level_max_raw = _prompt("  Taille maximum (%)", "150")
        trend_filter_enabled = _prompt("Activer le filtre de tendance EMA (o/n)", "n").lower().startswith("o")
        if trend_filter_enabled:
            trend_filter_ema_period_raw = _prompt("  Periode de l'EMA (bougies)", "200")
        atr_sizing_enabled = _prompt("Activer le sizing par volatilite ATR (o/n)", "n").lower().startswith("o")
        if atr_sizing_enabled:
            atr_period_raw = _prompt("  Periode ATR (bougies)", "14")
            atr_baseline_period_raw = _prompt("  Periode de reference (bougies)", "100")
            atr_min_multiplier_raw = _prompt("  Taille minimum (% de la normale)", "20")

    exit_check_timeframe = ""
    if preset.engine != "market_making":
        exit_check_timeframe = _prompt("Verifier les sorties sur un timeframe plus fin (ex: 5m, vide = desactive)", "")

    args = argparse.Namespace(
        strategy=strategy_key, symbol=symbol, exchange=exchange, timeframe=timeframe_raw or None, since=since,
        until=until or None, capital=float(capital),
        param=[f"{k}={v}" for k, v in param_overrides.items() if v != ""],
        risk=[f"{k}={v}" for k, v in risk_overrides.items() if v != ""],
        stop_loss_pct=stop_loss_raw or None,
        take_profit_pct=take_profit_raw or None,
        max_concurrent_positions=int(max_concurrent_raw) if max_concurrent_raw else None,
        max_position_size_pct=max_position_size_raw or None,
        max_daily_loss_pct=max_daily_loss_raw or None,
        trailing_stop_pct=trailing_stop_raw or None,
        fee_pct=fee_pct_raw or None,
        partial_take_profit_pct=partial_take_profit_raw or None,
        partial_exit_fraction=partial_exit_fraction_raw or None,
        price_level_sizing=price_level_sizing,
        price_level_min_multiplier=float(price_level_min_raw) if price_level_min_raw else None,
        price_level_max_multiplier=float(price_level_max_raw) if price_level_max_raw else None,
        trend_filter_enabled=trend_filter_enabled,
        trend_filter_ema_period=trend_filter_ema_period_raw or None,
        atr_sizing_enabled=atr_sizing_enabled,
        atr_period=atr_period_raw or None,
        atr_baseline_period=atr_baseline_period_raw or None,
        atr_min_multiplier=atr_min_multiplier_raw or None,
        exit_check_timeframe=exit_check_timeframe or None,
        repeat=int(repeat or "1"),
        output_dir=str(REPORT_DIR),
        list_strategies=False,
    )
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest d'un bot unique sur une periode donnee, avec rapport final.")
    parser.add_argument("--strategy", choices=list(PRESETS.keys()), help="Type de bot a tester")
    parser.add_argument("--symbol", help="Paire, ex: BTC/USDT")
    parser.add_argument("--exchange", default="binance", help="Exchange ccxt (defaut: binance)")
    parser.add_argument("--timeframe", default=None, help="Timeframe (1m/5m/15m/1h/4h/1d) - ignore si la strategie en impose un (ex: dip_bounce). Defaut: 1h")
    parser.add_argument("--since", help="Debut de periode, AAAA-MM-JJ")
    parser.add_argument("--until", default=None, help="Fin de periode, AAAA-MM-JJ (defaut: maintenant)")
    parser.add_argument("--capital", type=float, default=1000.0, help="Capital de depart (defaut: 1000)")
    parser.add_argument("--param", action="append", default=[], metavar="CLE=VALEUR", help="Parametre de strategie (repetable). Les % s'expriment en unites, ex: dip_threshold_pct=0.5 pour 0.5%%")
    parser.add_argument("--risk", action="append", default=[], metavar="CLE=VALEUR", help="Parametre de risque specifique a la strategie (repetable)")
    parser.add_argument("--stop-loss-pct", dest="stop_loss_pct", default=None, help="Stop-loss en %% (ex: 2 pour 2%%), seulement si la strategie le supporte")
    parser.add_argument("--take-profit-pct", dest="take_profit_pct", default=None, help="Take-profit en %% (optionnel)")
    parser.add_argument("--max-concurrent-positions", dest="max_concurrent_positions", type=int, default=None, help="Nombre de positions ouvertes en parallele autorisees (defaut: 1 - une seule a la fois). Ignore pour market_making")
    parser.add_argument("--max-position-size-pct", dest="max_position_size_pct", default=None, help="Taille de position max en %% du capital (defaut: 10). Ignore pour market_making")
    parser.add_argument("--max-daily-loss-pct", dest="max_daily_loss_pct", default=None, help="Perte max journaliere en %% avant coupe-circuit (defaut: 5). Ignore pour market_making")
    parser.add_argument("--trailing-stop-pct", dest="trailing_stop_pct", default=None, help="Trailing stop en %% (optionnel, vide = desactive). Ignore pour market_making")
    parser.add_argument("--fee-pct", dest="fee_pct", default=None, help="Frais par ordre en %% (defaut: 0.1). Ignore pour market_making")
    parser.add_argument("--partial-take-profit-pct", dest="partial_take_profit_pct", default=None, help="Palier de sortie partielle en %% (optionnel, vide = desactive). Ignore pour market_making")
    parser.add_argument("--partial-exit-fraction", dest="partial_exit_fraction", default=None, help="Fraction du lot vendue au palier partiel, en %% (defaut: 50)")
    parser.add_argument("--price-level-sizing", dest="price_level_sizing", action="store_true", help="Active le sizing par niveau de prix (taille de position modulee selon l'ecart au prix moyen du mois calendaire). Ignore pour market_making")
    parser.add_argument("--price-level-min-multiplier", dest="price_level_min_multiplier", type=float, default=None, help="Taille minimum en %% de la normale (defaut: 50)")
    parser.add_argument("--price-level-max-multiplier", dest="price_level_max_multiplier", type=float, default=None, help="Taille maximum en %% de la normale (defaut: 150)")
    parser.add_argument("--trend-filter", dest="trend_filter_enabled", action="store_true", help="Active le filtre de tendance EMA (bloque un achat si le prix est sous l'EMA). Ignore pour market_making")
    parser.add_argument("--trend-filter-ema-period", dest="trend_filter_ema_period", default=None, help="Periode de l'EMA du filtre de tendance (defaut: 200)")
    parser.add_argument("--atr-sizing", dest="atr_sizing_enabled", action="store_true", help="Active le sizing par volatilite ATR (reduit la taille en periode agitee). Ignore pour market_making")
    parser.add_argument("--atr-period", dest="atr_period", default=None, help="Periode ATR en bougies (defaut: 14)")
    parser.add_argument("--atr-baseline-period", dest="atr_baseline_period", default=None, help="Periode de reference ATR en bougies (defaut: 100)")
    parser.add_argument("--atr-min-multiplier", dest="atr_min_multiplier", default=None, help="Taille minimum du sizing ATR en %% de la normale (defaut: 20)")
    parser.add_argument("--exit-check-timeframe", dest="exit_check_timeframe", default=None, help="Verifie les sorties (stop-loss/verrou de gain/...) sur ce timeframe plus fin (ex: 5m) au lieu d'une seule fois par bougie d'entree - les entrees de la strategie restent inchangees. Ignore pour market_making")
    parser.add_argument("--repeat", type=int, default=1, help="Rejoue le meme test sur N sous-periodes egales entre --since et --until (defaut: 1 = un seul test). Utile pour verifier qu'un bon resultat n'est pas du a une seule periode chanceuse")
    parser.add_argument("--output-dir", default=str(REPORT_DIR), help="Dossier de sortie du rapport")
    parser.add_argument("--list-strategies", action="store_true", help="Liste les types de bot disponibles et quitte")
    return parser


def build_strategy_instance(preset: StrategyPreset, params: dict):
    if preset.strategy_type == "dip_bounce":
        params = dict(params)
        params["trend_ma_period"] = DIP_BOUNCE_TREND_MA_PERIOD[preset.key]
        if params.get("force_trade_after_hours") == 0:
            params["force_trade_after_hours"] = None  # 0 = desactive, la strategie attend None
    strategy_cls = STRATEGY_REGISTRY[preset.strategy_type]
    return strategy_cls(**params)


def split_periods(since_ms: int, until_ms: int, n: int) -> list[tuple[int, int]]:
    """Decoupe [since_ms, until_ms] en n sous-periodes contigues de meme
    duree (pas glissantes/chevauchantes - un simple decoupage egal suffit
    pour voir si un resultat tient sur plusieurs sous-periodes ou repose sur
    une seule, comme le mois d'aout observe plus tot dans le projet)."""
    total = until_ms - since_ms
    step = total // n
    bounds = [since_ms + i * step for i in range(n)] + [until_ms]
    return [(bounds[i], bounds[i + 1]) for i in range(n)]


def _fmt_dt(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def compute_trade_stats(portfolio: Portfolio, last_close: float) -> dict:
    trades = portfolio.trade_history
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    stats = {
        "num_trades": len(trades),
        "win_rate_pct": (len(wins) / len(trades) * 100) if trades else None,
        "best_trade_pnl": max(pnls) if trades else None,
        "worst_trade_pnl": min(pnls) if trades else None,
        "avg_trade_pnl": (sum(pnls) / len(pnls)) if trades else None,
        "max_holding_hours": None,
        "still_open_positions": len(portfolio.positions),
        "open_positions_unrealized_pnl": sum(
            (last_close - p.avg_entry_price) * p.quantity for p in portfolio.positions
        ) if portfolio.positions else 0.0,
    }
    durations_ms = [t["timestamp"] - t["entry_timestamp"] for t in trades]
    if durations_ms:
        stats["max_holding_hours"] = max(durations_ms) / 3_600_000
    return stats


def format_report(*, preset: StrategyPreset, symbol: str, exchange: str, timeframe: str,
                   since: str, until: str, num_candles: int, params: dict, risk_summary: dict,
                   report, benchmark_pct: float | None, trade_stats: dict) -> str:
    lines = []
    lines.append("=== Rapport de backtest ===")
    lines.append(f"Genere le          : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Bot                : {preset.label}")
    lines.append(f"Devise             : {symbol} ({exchange})")
    lines.append(f"Timeframe          : {timeframe}")
    lines.append(f"Periode            : {since} -> {until} ({num_candles} bougies)")
    lines.append("")
    lines.append("Parametres de la strategie :")
    for name, value in params.items():
        lines.append(f"  - {name} = {value}")
    lines.append("")
    lines.append("Parametres de risque :")
    for name, value in risk_summary.items():
        lines.append(f"  - {name} = {value}")
    lines.append("")
    lines.append("--- Performance ---")
    lines.append(f"Capital de depart   : {report.starting_capital:.2f}")
    lines.append(f"Capital final       : {report.ending_equity:.2f}")
    lines.append(f"Rendement total     : {report.total_return_pct * 100:.2f} %")
    if benchmark_pct is not None:
        delta = report.total_return_pct * 100 - benchmark_pct * 100
        verdict = "bat" if delta > 0 else "perd contre"
        lines.append(f"Benchmark buy&hold  : {benchmark_pct * 100:.2f} %  (le bot {verdict} le buy&hold de {delta:+.2f} pt)")
    lines.append(f"Drawdown max        : {report.max_drawdown_pct * 100:.2f} %")
    lines.append(f"P&L realise         : {report.realized_pnl:.2f}")
    lines.append("")
    lines.append("--- Trades ---")
    lines.append(f"Nombre de trades    : {trade_stats['num_trades']}")
    if trade_stats["num_trades"]:
        lines.append(f"Taux de reussite    : {trade_stats['win_rate_pct']:.1f} %")
        lines.append(f"Meilleur trade      : {trade_stats['best_trade_pnl']:+.2f}")
        lines.append(f"Pire trade          : {trade_stats['worst_trade_pnl']:+.2f}")
        lines.append(f"Trade moyen         : {trade_stats['avg_trade_pnl']:+.2f}")
        if trade_stats["max_holding_hours"] is not None:
            lines.append(f"Detention max       : {trade_stats['max_holding_hours']:.1f} h")
    lines.append(f"Positions encore ouvertes en fin de periode : {trade_stats['still_open_positions']}")
    if trade_stats["still_open_positions"]:
        lines.append(f"  (P&L latent non realise : {trade_stats['open_positions_unrealized_pnl']:+.2f})")
    return "\n".join(lines)


def merge_dual_timeframe(
    entry_candles: list[Candle], exit_check_candles: list[Candle],
    entry_timeframe: str, exit_check_timeframe: str,
) -> list[tuple[Candle, bool]]:
    """Fusionne la serie de bougies "entree" (celle vue par la strategie,
    ex: 1h) et une serie plus fine "surveillance des sorties" (ex: 5 min,
    demande de l'utilisateur pour que le verrou de gain/stop-loss ne
    dependent plus d'une seule verification par heure) en une seule
    sequence chronologique.

    `candle.timestamp` est l'OUVERTURE de la bougie, pas le moment ou son
    `close` est connu - une bougie 1h ouverte a 06:00 n'est "close" (son
    prix de cloture connu) qu'a 07:00. Trier naivement par `timestamp` brut
    placerait donc cette bougie 1h AVANT les bougies 5 min de 06:00 a 06:55,
    alors que son prix de cloture reflete en realite un instant POSTERIEUR a
    toutes ces bougies fines (bug reel rencontre - un ecart de plusieurs
    points de pourcentage entre le close "1h" et le close "5m" au meme
    timestamp brut, alors qu'il s'agit en verite de deux instants differents
    a une heure d'ecart). On trie donc par le moment ou chaque bougie
    devient reellement connue : `timestamp + duree_de_la_bougie`.

    Chaque bougie fine est marquee `False` (prix seulement,
    `Engine.process_price_update`) SAUF si son instant de cloture coincide
    exactement avec celui d'une bougie d'entree, auquel cas c'est la bougie
    D'ENTREE (pas la fine) qui est utilisee et marquee `True` (bougie
    complete, `Engine.process_candle`) - la strategie continue de raisonner
    sur les memes donnees qu'en mode simple, seule la frequence des
    VERIFICATIONS DE SORTIE change."""
    entry_duration_ms = ccxt.Exchange.parse_timeframe(entry_timeframe) * 1000
    exit_duration_ms = ccxt.Exchange.parse_timeframe(exit_check_timeframe) * 1000
    timeline: dict[int, tuple[Candle, bool]] = {
        c.timestamp + exit_duration_ms: (c, False) for c in exit_check_candles
    }
    for c in entry_candles:
        timeline[c.timestamp + entry_duration_ms] = (c, True)
    return [timeline[key] for key in sorted(timeline)]


def build_chart_payload(candles: list[Candle], portfolio, max_candles: int = 1500) -> dict:
    """EF-60 : donnees pretes a tracer un graphique en chandelles avec les
    achats/ventes du backtest - onglet Test/Backtest du dashboard. Sous-
    echantillonne au-dela de `max_candles` (regroupe par paquets, en
    conservant open/high/low/close corrects du paquet) pour rester leger cote
    navigateur meme sur des mois de bougies 1 minute ; les horodatages des
    trades restent les vrais horodatages (pas des index), pour un alignement
    correct avec le regroupement cote client si besoin."""
    step = max(1, len(candles) // max_candles)
    bucketed = []
    for i in range(0, len(candles), step):
        chunk = candles[i:i + step]
        bucketed.append({
            "t": chunk[0].timestamp, "o": chunk[0].open,
            "h": max(c.high for c in chunk), "l": min(c.low for c in chunk),
            "c": chunk[-1].close,
        })
    closed_trades = [
        {
            "buy_t": t["entry_timestamp"], "buy_p": t["entry_price"],
            "sell_t": t["timestamp"], "sell_p": t["exit_price"],
            "pnl": t["pnl"], "reason": t["reason"],
        }
        for t in portfolio.trade_history
    ]
    open_positions = [
        {"buy_t": p.entry_timestamp, "buy_p": p.avg_entry_price}
        for p in portfolio.positions
    ]
    return {"candles": bucketed, "closed_trades": closed_trades, "open_positions": open_positions}


def run_one_period(
    preset: StrategyPreset, params: dict, risk_kwargs: dict, capital: float, candles: list[Candle],
    price_level_sizer_kwargs: dict | None = None, exit_check_candles: list[Candle] | None = None,
    entry_timeframe: str = "1h", exit_check_timeframe: str | None = None,
    trend_filter_kwargs: dict | None = None, atr_sizer_kwargs: dict | None = None,
    profile_loader=None,
):
    """Cree une strategie/un portefeuille/un moteur FRAIS et joue la periode
    donnee - indispensable en mode --repeat pour que chaque sous-periode
    reparte de zero (aucun etat ni capital reporte de l'une a l'autre) -
    y compris la moyenne mensuelle du sizing par niveau de prix (EF-51).
    `trend_filter`/`atr_sizer` demarrent FROIDS (comme le sizing par niveau
    de prix) : pas de bougies d'avant `candles` pour les rechauffer - leurs
    premieres bougies dans la periode testee sont donc en mode fail-open
    (voir analysis/trend_filter.py, analysis/atr_sizer.py), contrairement au
    mode paper qui les rechauffe via `warm_up_strategy` (run_paper.py).

    `exit_check_candles`/`exit_check_timeframe` (optionnel, EF-53) : bougies
    plus fines que `candles` pour verifier les sorties (stop-loss/verrou de
    gain/...) plus souvent que les entrees de la strategie - voir
    `merge_dual_timeframe` (les deux timeframes sont necessaires pour
    aligner correctement les instants de cloture, pas seulement les
    timestamps d'ouverture)."""
    strategy = build_strategy_instance(preset, params)
    if profile_loader is not None:   # EF-109 : profil de volume sur bougies fines, comme TradingView
        attach_preloaded(strategy, entry_timeframe, profile_loader)
    if preset.engine == "market_making":
        mm_config = MarketMakingConfig()
        portfolio = Portfolio(starting_capital=capital, fee_pct=mm_config.fee_pct)
        executor = BacktestExecutor(portfolio)
        engine = MarketMakingEngine(strategy, executor, portfolio)
        engine.run_backtest(candles)
    else:
        risk_manager = RiskManager(RiskConfig(**risk_kwargs))
        portfolio = Portfolio(starting_capital=capital, fee_pct=risk_manager.config.fee_pct)
        executor = BacktestExecutor(portfolio)
        price_level_sizer = PriceLevelSizer(**price_level_sizer_kwargs) if price_level_sizer_kwargs else None
        trend_filter = TrendFilter(**trend_filter_kwargs) if trend_filter_kwargs else None
        atr_sizer = AtrSizer(**atr_sizer_kwargs) if atr_sizer_kwargs else None
        engine = Engine(
            strategy, risk_manager, executor, portfolio,
            price_level_sizer=price_level_sizer, trend_filter=trend_filter, atr_sizer=atr_sizer,
        )

        if exit_check_candles:
            merged = merge_dual_timeframe(candles, exit_check_candles, entry_timeframe, exit_check_timeframe)
            for candle, is_entry_candle in merged:
                if is_entry_candle:
                    engine.process_candle(candle)
                else:
                    engine.process_price_update(candle)
        else:
            engine.run_backtest(candles)

    report = compute_report(portfolio)
    benchmark_pct = compute_buy_and_hold_return_pct(candles)
    trade_stats = compute_trade_stats(portfolio, candles[-1].close)
    return report, benchmark_pct, trade_stats, portfolio


def build_risk_kwargs_and_summary(preset: StrategyPreset, args: argparse.Namespace, risk_params: dict) -> tuple[dict, dict]:
    risk_summary: dict = {}
    if preset.engine == "market_making":
        mm_config = MarketMakingConfig()
        risk_summary["fee_pct"] = mm_config.fee_pct
        risk_summary["max_daily_loss_pct"] = mm_config.max_daily_loss_pct
        return {}, risk_summary

    stop_loss_pct = None
    if preset.supports_stop_loss:
        stop_loss_raw = getattr(args, "stop_loss_pct", None)
        stop_loss_pct = (float(stop_loss_raw) / 100) if stop_loss_raw else preset.default_stop_loss_pct
    risk_summary["stop_loss_pct"] = stop_loss_pct
    take_profit_raw = getattr(args, "take_profit_pct", None)
    take_profit_pct = (float(take_profit_raw) / 100) if take_profit_raw else None
    if take_profit_pct is not None:
        risk_summary["take_profit_pct"] = take_profit_pct

    max_concurrent_raw = getattr(args, "max_concurrent_positions", None)
    max_concurrent_positions = int(max_concurrent_raw) if max_concurrent_raw else 1
    if max_concurrent_positions < 1:
        raise ValueError("max_concurrent_positions doit etre >= 1")
    risk_summary["max_concurrent_positions"] = max_concurrent_positions

    risk_kwargs = {"stop_loss_pct": stop_loss_pct, "take_profit_pct": take_profit_pct, "max_concurrent_positions": max_concurrent_positions}

    # Reglages de risque generiques (memes noms/echelles que le formulaire de
    # creation de bot, control_server.py::build_config) - tous optionnels,
    # absents du payload = defaut RiskConfig inchange (comportement backtest
    # historique preserve pour les appelants existants, ex: CLI/tests).
    max_position_size_raw = getattr(args, "max_position_size_pct", None)
    if max_position_size_raw:
        max_position_size_pct = float(max_position_size_raw) / 100
        if not (0 < max_position_size_pct <= 1):
            raise ValueError("la taille de position max doit etre comprise entre 0 et 100 %")
        risk_kwargs["max_position_size_pct"] = max_position_size_pct
        risk_summary["max_position_size_pct"] = max_position_size_pct
    else:
        max_position_size_pct = RiskConfig().max_position_size_pct

    max_daily_loss_raw = getattr(args, "max_daily_loss_pct", None)
    if max_daily_loss_raw:
        max_daily_loss_pct = float(max_daily_loss_raw) / 100
        if not (0 < max_daily_loss_pct <= 1):
            raise ValueError("la perte max journaliere doit etre comprise entre 0 et 100 %")
        risk_kwargs["max_daily_loss_pct"] = max_daily_loss_pct
        risk_summary["max_daily_loss_pct"] = max_daily_loss_pct

    trailing_stop_raw = getattr(args, "trailing_stop_pct", None)
    if trailing_stop_raw:
        trailing_stop_pct = float(trailing_stop_raw) / 100
        if not (0 < trailing_stop_pct <= 1):
            raise ValueError("le trailing stop doit etre compris entre 0 et 100 %")
        risk_kwargs["trailing_stop_pct"] = trailing_stop_pct
        risk_summary["trailing_stop_pct"] = trailing_stop_pct

    fee_pct_raw = getattr(args, "fee_pct", None)
    if fee_pct_raw not in (None, ""):
        fee_pct = float(fee_pct_raw) / 100
        if not (0 <= fee_pct <= 1):
            raise ValueError("les frais par ordre doivent etre compris entre 0 et 100 %")
        risk_kwargs["fee_pct"] = fee_pct
        risk_summary["fee_pct"] = fee_pct

    partial_take_profit_raw = getattr(args, "partial_take_profit_pct", None)
    if partial_take_profit_raw:
        partial_take_profit_pct = float(partial_take_profit_raw) / 100
        if not (0 < partial_take_profit_pct <= 1):
            raise ValueError("le palier de sortie partielle doit etre compris entre 0 et 100 %")
        if take_profit_pct is not None and partial_take_profit_pct >= take_profit_pct:
            raise ValueError("le palier de sortie partielle doit etre strictement inferieur au take-profit complet")
        partial_exit_fraction_raw = getattr(args, "partial_exit_fraction", None)
        partial_exit_fraction = (float(partial_exit_fraction_raw) / 100) if partial_exit_fraction_raw else 0.5
        if not (0 < partial_exit_fraction <= 1):
            raise ValueError("la fraction de sortie partielle doit etre comprise entre 0 et 100 %")
        risk_kwargs["partial_take_profit_pct"] = partial_take_profit_pct
        risk_kwargs["partial_exit_fraction"] = partial_exit_fraction
        risk_summary["partial_take_profit_pct"] = partial_take_profit_pct
        risk_summary["partial_exit_fraction"] = partial_exit_fraction

    for name, value in risk_params.items():
        risk_kwargs[name] = value
        risk_summary[name] = value

    if max_concurrent_positions * max_position_size_pct > 1.0:
        raise ValueError(
            f"{max_concurrent_positions} positions x {max_position_size_pct:.0%} de taille chacune depasserait "
            f"100% du capital - reduis le nombre de positions ou la taille par position"
        )
    return risk_kwargs, risk_summary


def build_trend_filter_kwargs(preset: StrategyPreset, args: argparse.Namespace) -> tuple[dict | None, dict]:
    """Meme principe que `build_price_level_sizer_kwargs` mais pour le
    filtre de tendance EMA (engine.py::Engine accepte deja `trend_filter` en
    parametre, voir aussi run_paper.py) - desactive par defaut, ignore pour
    market_making (MarketMakingEngine ne l'accepte pas)."""
    if preset.engine == "market_making" or not getattr(args, "trend_filter_enabled", False):
        return None, {}
    ema_period_raw = getattr(args, "trend_filter_ema_period", None)
    ema_period = int(ema_period_raw) if ema_period_raw else 200
    if ema_period < 2:
        raise ValueError("la periode EMA du filtre de tendance doit etre >= 2")
    return {"ema_period": ema_period}, {"trend_filter_ema_period": ema_period}


def build_atr_sizer_kwargs(preset: StrategyPreset, args: argparse.Namespace) -> tuple[dict | None, dict]:
    """Idem pour le sizing par volatilite ATR - ignore pour market_making."""
    if preset.engine == "market_making" or not getattr(args, "atr_sizing_enabled", False):
        return None, {}
    atr_period_raw = getattr(args, "atr_period", None)
    baseline_period_raw = getattr(args, "atr_baseline_period", None)
    min_multiplier_raw = getattr(args, "atr_min_multiplier", None)
    atr_period = int(atr_period_raw) if atr_period_raw else 14
    baseline_period = int(baseline_period_raw) if baseline_period_raw else 100
    min_size_multiplier = (float(min_multiplier_raw) / 100) if min_multiplier_raw else 0.2
    if atr_period < 1:
        raise ValueError("la periode ATR doit etre >= 1")
    if baseline_period < 1:
        raise ValueError("la periode de reference ATR doit etre >= 1")
    if not (0.0 < min_size_multiplier <= 1.0):
        raise ValueError("la taille minimum du sizing ATR doit etre comprise entre 0 (exclu) et 100 %")
    kwargs = {"atr_period": atr_period, "baseline_period": baseline_period, "min_size_multiplier": min_size_multiplier}
    summary = {"atr_period": atr_period, "atr_baseline_period": baseline_period, "atr_min_multiplier": min_size_multiplier}
    return kwargs, summary


def build_price_level_sizer_kwargs(preset: StrategyPreset, args: argparse.Namespace) -> tuple[dict | None, dict]:
    """Idem `build_risk_kwargs_and_summary` mais pour le sizing par niveau de
    prix (EF-51) - independant de la RiskConfig (c'est un sizer, pas une
    regle de risque), desactive par defaut, ignore pour market_making."""
    if preset.engine == "market_making" or not getattr(args, "price_level_sizing", False):
        return None, {}
    min_raw = getattr(args, "price_level_min_multiplier", None)
    max_raw = getattr(args, "price_level_max_multiplier", None)
    min_multiplier = (float(min_raw) / 100) if min_raw else 0.5
    max_multiplier = (float(max_raw) / 100) if max_raw else 1.5
    if min_multiplier <= 0:
        raise ValueError("price_level_min_multiplier doit etre strictement positif")
    if max_multiplier < min_multiplier:
        raise ValueError("price_level_max_multiplier doit etre >= price_level_min_multiplier")
    kwargs = {"min_size_multiplier": min_multiplier, "max_size_multiplier": max_multiplier}
    summary = {"price_level_sizing_min": min_multiplier, "price_level_sizing_max": max_multiplier}
    return kwargs, summary


def format_repeat_report(*, preset: StrategyPreset, symbol: str, exchange: str, timeframe: str,
                          capital: float, params: dict, risk_summary: dict, periods: list[dict],
                          skipped: int) -> str:
    lines = []
    lines.append("=== Rapport de backtest (repete sur plusieurs sous-periodes) ===")
    lines.append(f"Genere le          : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Bot                : {preset.label}")
    lines.append(f"Devise             : {symbol} ({exchange})")
    lines.append(f"Timeframe          : {timeframe}")
    lines.append(f"Capital de depart (par sous-periode) : {capital:.2f}")
    lines.append(f"Nombre de sous-periodes jouees : {len(periods)}" + (f" ({skipped} ignoree(s), pas assez de bougies)" if skipped else ""))
    lines.append("")
    lines.append("Parametres de la strategie :")
    for name, value in params.items():
        lines.append(f"  - {name} = {value}")
    lines.append("")
    lines.append("Parametres de risque :")
    for name, value in risk_summary.items():
        lines.append(f"  - {name} = {value}")
    lines.append("")
    lines.append("--- Detail par sous-periode ---")
    for p in periods:
        beat = "bat" if p["return_pct"] > p["benchmark_pct"] else "perd contre"
        open_note = f", position ouverte a la fin" if p["still_open"] else ""
        lines.append(
            f"{p['start']} -> {p['end']} | rendement {p['return_pct'] * 100:+.2f} % "
            f"| buy&hold {p['benchmark_pct'] * 100:+.2f} % ({beat}) "
            f"| {p['num_trades']} trade(s), pire {p['worst_trade_pnl']:+.2f}{open_note}"
        )
    lines.append("")
    lines.append("--- Synthese ---")
    returns = [p["return_pct"] for p in periods]
    n = len(returns)
    avg_return = sum(returns) / n
    sorted_returns = sorted(returns)
    median_return = sorted_returns[n // 2] if n % 2 else (sorted_returns[n // 2 - 1] + sorted_returns[n // 2]) / 2
    positive_count = sum(1 for r in returns if r > 0)
    beat_count = sum(1 for p in periods if p["return_pct"] > p["benchmark_pct"])
    lines.append(f"Rendement moyen par sous-periode   : {avg_return * 100:+.2f} %")
    lines.append(f"Rendement median par sous-periode  : {median_return * 100:+.2f} %")
    lines.append(f"Meilleure sous-periode             : {max(returns) * 100:+.2f} %")
    lines.append(f"Pire sous-periode                  : {min(returns) * 100:+.2f} %")
    lines.append(f"Sous-periodes positives            : {positive_count}/{n}")
    lines.append(f"Sous-periodes qui battent le buy&hold : {beat_count}/{n}")
    if positive_count in (0, n):
        lines.append("Attention : resultat homogene sur toutes les sous-periodes testees (bon signe de stabilite, mais verifie que les sous-periodes ne se ressemblent pas trop entre elles - meme regime de marche).")
    return "\n".join(lines)


def _param_spec_to_dict(spec: ParamSpec) -> dict:
    return {"name": spec.name, "label": spec.label, "default": spec.default, "kind": spec.kind.__name__, "unit": spec.unit}


def presets_metadata() -> list[dict]:
    """Description JSON-serialisable des types de bot testables - consommee
    par le serveur de controle pour construire dynamiquement le formulaire de
    l'onglet Test/Backtest du dashboard (une seule source de verite : ces
    memes `PRESETS` alimentent aussi le CLI)."""
    return [
        {
            "key": p.key, "label": p.label, "timeframe": p.timeframe,
            "supports_stop_loss": p.supports_stop_loss,
            "default_stop_loss_pct": p.default_stop_loss_pct,
            "param_specs": [_param_spec_to_dict(s) for s in p.param_specs],
            "risk_param_specs": [_param_spec_to_dict(s) for s in p.risk_param_specs],
        }
        for p in PRESETS.values()
    ]


def build_namespace_from_payload(payload: dict) -> argparse.Namespace:
    """Equivalent du parsing argparse, a partir d'un JSON envoye par le
    dashboard (onglet Test/Backtest) plutot que de la ligne de commande."""
    return argparse.Namespace(
        strategy=payload.get("strategy"),
        symbol=(payload.get("symbol") or "").strip(),
        exchange=(payload.get("exchange") or "binance").strip(),
        timeframe=payload.get("timeframe") or None,
        since=payload.get("since") or None,
        until=payload.get("until") or None,
        capital=float(payload.get("capital") or 1000),
        param=list(payload.get("param") or []),
        risk=list(payload.get("risk") or []),
        stop_loss_pct=payload.get("stop_loss_pct") or None,
        take_profit_pct=payload.get("take_profit_pct") or None,
        max_concurrent_positions=int(payload["max_concurrent_positions"]) if payload.get("max_concurrent_positions") else None,
        max_position_size_pct=payload.get("max_position_size_pct") or None,
        max_daily_loss_pct=payload.get("max_daily_loss_pct") or None,
        trailing_stop_pct=payload.get("trailing_stop_pct") or None,
        fee_pct=payload.get("fee_pct") or None,
        partial_take_profit_pct=payload.get("partial_take_profit_pct") or None,
        partial_exit_fraction=payload.get("partial_exit_fraction") or None,
        price_level_sizing=bool(payload.get("price_level_sizing")),
        price_level_min_multiplier=float(payload["price_level_min_multiplier"]) if payload.get("price_level_min_multiplier") else None,
        price_level_max_multiplier=float(payload["price_level_max_multiplier"]) if payload.get("price_level_max_multiplier") else None,
        trend_filter_enabled=bool(payload.get("trend_filter_enabled")),
        trend_filter_ema_period=payload.get("trend_filter_ema_period") or None,
        atr_sizing_enabled=bool(payload.get("atr_sizing_enabled")),
        atr_period=payload.get("atr_period") or None,
        atr_baseline_period=payload.get("atr_baseline_period") or None,
        atr_min_multiplier=payload.get("atr_min_multiplier") or None,
        exit_check_timeframe=payload.get("exit_check_timeframe") or None,
        repeat=int(payload.get("repeat") or 1),
        output_dir=str(REPORT_DIR),
        list_strategies=False,
    )


def run_backtest_job(
    args: argparse.Namespace, progress_callback: Callable[[dict], None] | None = None,
    chart_data_out: dict | None = None,
) -> tuple[str, str]:
    """Coeur du test (validation, telechargement, execution, rapport) -
    reutilise a la fois par le CLI (`main`) et par le serveur de controle
    (dashboard, onglet Test/Backtest). Leve `ValueError` sur une entree
    invalide ; renvoie (texte du rapport, chemin du fichier enregistre).

    `progress_callback` (optionnel, EF-56 - barre de progression du
    dashboard) : appele a chaque etape notable avec un petit dict d'etat
    ({"stage": "download"|"running", ...}) - jamais requis par le CLI ni les
    tests existants (None par defaut, aucun effet).

    `chart_data_out` (optionnel, EF-60 - graphique en chandelles du dashboard) :
    dict mutable rempli en place avec {"candles": [...], "closed_trades": [...],
    "open_positions": [...]} pour tracer le prix et les achats/ventes - UNIQUEMENT
    en mode periode unique (`--repeat 1`, valeur par defaut) : avec plusieurs
    sous-periodes, il faudrait un graphique par sous-periode, hors perimetre de
    ce lot. Reste `None` (aucun effet) sinon, comme `progress_callback`."""

    def report(update: dict) -> None:
        if progress_callback is not None:
            progress_callback(update)

    if args.strategy not in PRESETS:
        raise ValueError(f"type de bot inconnu : {args.strategy!r} (attendus : {sorted(PRESETS)})")
    if not args.symbol:
        raise ValueError("symbole manquant")
    if not args.since:
        raise ValueError("date de debut manquante")

    preset = PRESETS[args.strategy]
    param_overrides = _parse_kv_list(args.param)
    risk_overrides = _parse_kv_list(args.risk)
    params = _resolve_params(preset.param_specs, param_overrides)
    risk_params = _resolve_params(preset.risk_param_specs, risk_overrides)

    if preset.timeframe is not None:
        timeframe = preset.timeframe  # force par le preset (ex: dip_bounce) - coherence non negociable, voir control_server.py
    else:
        timeframe = getattr(args, "timeframe", None) or "1h"
        if timeframe not in VALID_TIMEFRAMES:
            raise ValueError(f"timeframe invalide, doit etre l'un de : {', '.join(sorted(VALID_TIMEFRAMES))}")
    repeat = max(1, getattr(args, "repeat", 1) or 1)

    since_ms = _iso_date_to_ms(args.since)
    until_ms = _iso_date_to_ms(args.until) if args.until else None

    report({"stage": "download", "message": f"Telechargement des bougies ({timeframe})..."})
    all_candles = fetch_historical_candles(
        exchange_id=args.exchange, symbol=args.symbol, timeframe=timeframe,
        since_iso=f"{args.since}T00:00:00Z",  # ccxt.parse8601 renvoie None sur une date sans heure (bug reel rencontre)
    )
    risk_kwargs, risk_summary = build_risk_kwargs_and_summary(preset, args, risk_params)
    price_level_sizer_kwargs, price_level_summary = build_price_level_sizer_kwargs(preset, args)
    risk_summary.update(price_level_summary)
    trend_filter_kwargs, trend_filter_summary = build_trend_filter_kwargs(preset, args)
    risk_summary.update(trend_filter_summary)
    atr_sizer_kwargs, atr_sizer_summary = build_atr_sizer_kwargs(preset, args)
    risk_summary.update(atr_sizer_summary)

    exit_check_timeframe = getattr(args, "exit_check_timeframe", None)
    all_exit_check_candles = None
    if exit_check_timeframe and preset.engine != "market_making":
        if exit_check_timeframe == timeframe:
            raise ValueError("le timeframe de surveillance des sorties doit etre different (plus fin) du timeframe d'entree")
        report({"stage": "download", "message": f"Telechargement des bougies de surveillance ({exit_check_timeframe})..."})
        all_exit_check_candles = fetch_historical_candles(
            exchange_id=args.exchange, symbol=args.symbol, timeframe=exit_check_timeframe,
            since_iso=f"{args.since}T00:00:00Z",
        )
        risk_summary["exit_check_timeframe"] = exit_check_timeframe

    profile_cache: dict[str, list] = {}

    def profile_loader(tf: str) -> list:
        """EF-109 : bougies fines du profil de volume, telechargees une seule fois."""
        if tf not in profile_cache:
            report({"stage": "download", "message": f"Telechargement des bougies du profil de volume ({tf})..."})
            profile_cache[tf] = fetch_historical_candles(exchange_id=args.exchange, symbol=args.symbol, timeframe=tf,
                                                         since_iso=f"{args.since}T00:00:00Z")
        return profile_cache[tf]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_symbol = args.symbol.replace("/", "-")

    if repeat == 1:
        candles = filter_candles(all_candles, since_ms, until_ms)
        if len(candles) < 2:
            raise ValueError(f"pas assez de bougies pour {args.symbol} sur cette periode ({len(candles)} recuperees)")
        print(f"{len(candles)} bougies chargees pour {args.symbol} ({timeframe}), du {args.since} au {args.until or 'maintenant'}")
        exit_check_candles = None
        if all_exit_check_candles is not None:
            exit_check_candles = filter_candles(all_exit_check_candles, since_ms, until_ms)
            print(f"{len(exit_check_candles)} bougies de surveillance ({exit_check_timeframe}) chargees pour les sorties")

        report({"stage": "running", "current": 0, "total": 1, "message": "Simulation en cours..."})
        result, benchmark_pct, trade_stats, portfolio = run_one_period(
            preset, params, risk_kwargs, args.capital, candles, price_level_sizer_kwargs, exit_check_candles,
            timeframe, exit_check_timeframe, trend_filter_kwargs, atr_sizer_kwargs, profile_loader,
        )
        report({"stage": "running", "current": 1, "total": 1})

        text = format_report(
            preset=preset, symbol=args.symbol, exchange=args.exchange, timeframe=timeframe,
            since=args.since, until=args.until or "maintenant", num_candles=len(candles),
            params=params, risk_summary=risk_summary, report=result,
            benchmark_pct=benchmark_pct, trade_stats=trade_stats,
        )
        filename = f"{preset.key}_{safe_symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        if chart_data_out is not None and preset.engine != "market_making":
            chart_data_out.update(build_chart_payload(candles, portfolio))
    else:
        effective_until_ms = until_ms if until_ms is not None else int(datetime.now(tz=timezone.utc).timestamp() * 1000)
        windows = split_periods(since_ms, effective_until_ms, repeat)
        periods = []
        skipped = 0
        for i, (start_ms, end_ms) in enumerate(windows):
            report({"stage": "running", "current": i, "total": repeat, "message": f"Sous-periode {i + 1}/{repeat}..."})
            window_candles = filter_candles(all_candles, start_ms, end_ms)
            if len(window_candles) < 2:
                skipped += 1
                print(f"  {_fmt_dt(start_ms)} -> {_fmt_dt(end_ms)} : pas assez de bougies ({len(window_candles)}), ignoree")
                continue
            window_exit_check_candles = (
                filter_candles(all_exit_check_candles, start_ms, end_ms) if all_exit_check_candles is not None else None
            )
            result, benchmark_pct, trade_stats, _portfolio = run_one_period(
                preset, params, risk_kwargs, args.capital, window_candles, price_level_sizer_kwargs,
                window_exit_check_candles, timeframe, exit_check_timeframe, trend_filter_kwargs, atr_sizer_kwargs,
                profile_loader,
            )
            periods.append({
                "start": _fmt_dt(start_ms), "end": _fmt_dt(end_ms),
                "return_pct": result.total_return_pct,
                "benchmark_pct": benchmark_pct if benchmark_pct is not None else 0.0,
                "num_trades": trade_stats["num_trades"],
                "worst_trade_pnl": trade_stats["worst_trade_pnl"] if trade_stats["worst_trade_pnl"] is not None else 0.0,
                "still_open": trade_stats["still_open_positions"] > 0,
            })
            print(f"  {_fmt_dt(start_ms)} -> {_fmt_dt(end_ms)} : rendement {result.total_return_pct * 100:+.2f} %")
        report({"stage": "running", "current": repeat, "total": repeat})

        if not periods:
            raise ValueError("aucune sous-periode n'a assez de donnees")

        text = format_repeat_report(
            preset=preset, symbol=args.symbol, exchange=args.exchange, timeframe=timeframe,
            capital=args.capital, params=params, risk_summary=risk_summary,
            periods=periods, skipped=skipped,
        )
        filename = f"{preset.key}_{safe_symbol}_repeat{repeat}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    report_path = output_dir / filename
    report_path.write_text(text, encoding="utf-8")
    return text, str(report_path)


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_strategies:
        print("Types de bot disponibles :")
        for key, preset in PRESETS.items():
            print(f"  {key:20s} {preset.label}")
        return

    if args.strategy is None or args.symbol is None or args.since is None:
        args = run_interactive()

    try:
        text, report_path = run_backtest_job(args)
    except ValueError as exc:
        print(f"Erreur : {exc}")
        sys.exit(1)

    print("\n" + text)
    print(f"\nRapport enregistre : {report_path}")


if __name__ == "__main__":
    main(sys.argv[1:])
