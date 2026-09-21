"""Recherche du meilleur algo/parametres par backtest sur 3 ans d'historique
(STC ext.). Teste une grille de combinaisons pour les deux strategies
disponibles (sma_cross, scalp_dip) sur plusieurs paires, et classe les
resultats par rendement.

VALIDATION OUT-OF-SAMPLE (EF-26) : l'historique est decoupe en deux
periodes chronologiques - une periode d'ENTRAINEMENT (les premiers
TRAIN_RATIO%) sur laquelle la grille de parametres est cherchee, et une
periode de VALIDATION (le reste, jamais vue pendant la recherche) sur
laquelle les meilleurs candidats sont re-testes. Un candidat qui performe
bien a l'entrainement mais mal en validation est un signe classique de
surapprentissage (overfitting) - le candidat final est choisi sur sa
performance de VALIDATION, pas d'entrainement.

Ca ne supprime pas le risque de surapprentissage (voir STB CT-07), mais ca
permet de le MESURER au lieu de se fier a un avertissement generique.

Usage:
    python -m tradingbot.optimize
    python -m tradingbot.optimize --symbols BTC/USDT,ETH/USDT
"""

import argparse
import sys
from pathlib import Path
from dataclasses import dataclass

import yaml

from tradingbot.analysis.atr_sizer import AtrSizer
from tradingbot.analysis.trend_filter import TrendFilter
from tradingbot.data_feed import fetch_historical_candles
from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.mm_engine import MarketMakingEngine
from tradingbot.portfolio import Portfolio
from tradingbot.reporting.stats import compute_buy_and_hold_return_pct, compute_report
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.dip_bounce import DipBounceStrategy
from tradingbot.strategies.market_making import MarketMakingStrategy
from tradingbot.strategies.mean_reversion import MeanReversionStrategy
from tradingbot.strategies.scalp_dip import ScalpDipStrategy
from tradingbot.strategies.sma_cross import SmaCrossStrategy

DEFAULT_SYMBOLS = ["BTC/USDT", "ETH/USDT", "DOGE/USDT"]
TIMEFRAME = "1h"
SINCE_YEARS = 3
STARTING_CAPITAL = 1000.0
MIN_TRADES_FOR_SIGNIFICANCE = 5  # sous ce seuil, le resultat n'est pas statistiquement exploitable

TRAIN_RATIO = 0.7  # 70% entrainement (recherche des parametres) / 30% validation (jamais vue)
TOP_N_FOR_VALIDATION = 15  # nombre de meilleurs candidats (sur l'entrainement) re-testes en validation

SMA_SHORT_WINDOWS = [5, 8, 10, 15, 20]
SMA_LONG_WINDOWS = [20, 30, 50, 75, 100]
SMA_STOP_LOSS_OPTIONS = [0.02, 0.05]

SCALP_LOOKBACKS = [10, 20, 30]
SCALP_DIP_THRESHOLDS = [0.002, 0.003, 0.005, 0.01]
SCALP_STOP_LOSS_OPTIONS = [0.01, 0.02]
SCALP_TAKE_PROFIT_OPTIONS = [0.005, 0.01, 0.02]

# Etape 6 (piste 6, feuille de route performance) : famille de strategie
# DIFFERENTE de sma_cross/scalp_dip (toutes deux suivi de tendance) - retour
# a la moyenne, pour diversifier l'edge de la flotte sur les regimes de
# marche sans tendance nette ou sma_cross echoue typiquement (ex: S1 2025).
MEAN_REVERSION_WINDOWS = [10, 20, 30]
MEAN_REVERSION_NUM_STD = [1.5, 2.0, 2.5]
MEAN_REVERSION_STOP_LOSS_OPTIONS = [0.02, 0.05]

# Etape 7 (feuille de route performance) : market making - edge structurel
# (capture de spread), pas directionnel comme les 3 familles precedentes.
# order_size_quote/max_inventory_quote exprimes en devise de cotation
# (STARTING_CAPITAL=1000) pour generaliser entre symboles (voir
# strategies/market_making.py). fee_pct standard Binance taker (0.1%) : le
# spread doit au moins couvrir l'aller-retour de frais (2x fee_pct) pour
# esperer un edge, d'ou des valeurs de spread_pct au-dessus de 0.2%.
MARKET_MAKING_SPREAD_PCT = [0.002, 0.004, 0.008]
MARKET_MAKING_ORDER_SIZE_QUOTE = [50.0, 100.0]
MARKET_MAKING_MAX_INVENTORY_QUOTE = [200.0, 400.0]
MARKET_MAKING_SKEW_FACTOR = [0.5, 1.0, 2.0]
MARKET_MAKING_FEE_PCT = 0.001

# Etape 7 piste 2 (feuille de route performance) : elargissement du spread en
# periode de forte volatilite (ATR), pour reduire le risque de selection
# adverse en marche trending - jamais teste jusqu'ici. Simple on/off (meme
# logique qu'ATR_SIZING_OPTIONS) avec les memes periodes ATR par defaut, pas
# de grille dediee sur ses propres hyperparametres pour ne pas faire exploser
# le nombre de combinaisons avant d'avoir un premier signal empirique.
MARKET_MAKING_VOLATILITY_ADAPTIVE_SPREAD_OPTIONS: list[bool] = [False, True]
MARKET_MAKING_MAX_SPREAD_MULTIPLIER = 3.0

# Etape 9 (feuille de route performance) : rebond de creux en tendance
# haussiere, proposee par l'utilisateur - regime (moyenne), creux (min) et
# objectif de sortie (max) tous derives de la MEME fenetre glissante
# `trend_ma_period`, coherent avec l'enonce "sur 24h" applique uniformement.
# PAS de stop-loss (stop_loss_pct=None explicite dans chaque candidat) -
# decision assumee, voir docs/STB.md pour la limite documentee. Le verrou de
# gain (profit_lock_trigger_pct doit toujours etre < profit_lock_arm_pct,
# sinon la combinaison est ignoree par build_dip_bounce_candidates).
DIP_BOUNCE_TREND_MA_PERIODS = [24, 48]
DIP_BOUNCE_DIP_THRESHOLDS = [0.003, 0.005, 0.01]
DIP_BOUNCE_PROFIT_LOCK_ARM = [0.005, 0.01]
DIP_BOUNCE_PROFIT_LOCK_GIVEBACK = [0.0007, 0.002]  # ecart sous le seuil d'armement avant de vendre

# EF-57 (2026-09-16) : stop-loss et trailing stop ajoutes a la grille - le
# stop-loss est devenu optionnel pour dip_bounce (EF-55, plus tot ce soir) et
# n'avait donc jamais ete teste en recherche ; le trailing stop est le levier
# qui a permis de laisser courir les grosses tendances (BTC) sans etre
# plafonne par le seul verrou de gain, decouvert en testant a la main avant
# d'automatiser la recherche ici. None = desactive dans les deux cas.
DIP_BOUNCE_STOP_LOSS_OPTIONS: list[float | None] = [None, 0.10]
DIP_BOUNCE_TRAILING_STOP_OPTIONS: list[float | None] = [None, 0.05, 0.08]

MAX_POSITION_SIZE_PCT = 0.10
MAX_DAILY_LOSS_PCT = 0.05
MIN_DRAWDOWN_FLOOR = 0.01  # plancher pour BacktestResult.risk_adjusted_return (etape 6, piste 4)

# Feuille de route performance, etape 1 (voir docs/FEUILLE_DE_ROUTE_PERFORMANCE.md) :
# None = filtre de tendance desactive, sinon la periode de l'EMA testee.
# 300 ajoute le 2026-09-16 suite a un constat empirique sur ETH/dip_bounce
# (EMA300 plus regulier et moins de drawdown que 200 sur 3 fenetres testees a
# la main) - beneficie aussi a sma_cross/scalp_dip qui partagent cette liste.
TREND_FILTER_EMA_OPTIONS: list[int | None] = [None, 50, 100, 200, 300]

# Feuille de route performance, etape 2 : False = sizing ATR desactive, True =
# active avec les parametres par defaut (memes que le formulaire dashboard).
# Un simple on/off (pas une grille de periodes ATR) pour ne pas faire exploser
# le nombre de combinaisons - le resultat de l'etape 2 etait deja mitige, pas
# la peine d'explorer finement ses propres hyperparametres pour l'instant.
ATR_SIZING_OPTIONS: list[bool] = [False, True]
DEFAULT_ATR_PERIOD = 14
DEFAULT_ATR_BASELINE_PERIOD = 100
DEFAULT_ATR_MIN_MULTIPLIER = 0.2


@dataclass
class Candidate:
    strategy_type: str
    params: dict
    risk: dict
    trend_filter_ema_period: int | None = None
    atr_sizing_enabled: bool = False


@dataclass
class BacktestResult:
    symbol: str
    candidate: Candidate
    total_return_pct: float
    max_drawdown_pct: float
    num_trades: int
    win_rate: float | None
    realized_pnl: float
    benchmark_return_pct: float | None = None  # buy & hold sur la meme periode (etape 6, feuille de route performance)

    @property
    def beats_benchmark(self) -> bool | None:
        """None si le benchmark n'a pas pu etre calcule (periode trop
        courte) - dans ce cas on ne peut ni confirmer ni infirmer un edge."""
        if self.benchmark_return_pct is None:
            return None
        return self.total_return_pct > self.benchmark_return_pct

    @property
    def risk_adjusted_return(self) -> float:
        """Etape 6 (piste 4, feuille de route performance) : rendement
        rapporte au drawdown subi (proche d'un ratio de Calmar), pas le
        rendement brut seul - classer sur `total_return_pct` favorise des
        candidats qui gagnent gros avec un drawdown enorme, fragiles des que
        le marche change de regime. `MIN_DRAWDOWN_FLOOR` evite qu'un
        drawdown quasi nul (quelques trades chanceux) gonfle artificiellement
        le score - un candidat avec 0.1% de drawdown n'est pas 100x "mieux"
        qu'un candidat a 10% de drawdown pour un rendement egal, c'est
        probablement un echantillon trop petit pour juger."""
        return self.total_return_pct / max(self.max_drawdown_pct, MIN_DRAWDOWN_FLOOR)


@dataclass
class ValidatedResult:
    symbol: str
    candidate: Candidate
    train: BacktestResult
    test: BacktestResult | None  # None si pas assez de trades sur la periode de validation


DEFAULT_CONSISTENCY_WINDOWS = 3  # etape 6, piste 5 : nombre de sous-fenetres de validation


def split_into_windows(candles: list, num_windows: int = DEFAULT_CONSISTENCY_WINDOWS) -> list[list]:
    """Decoupe une periode (typiquement la periode de VALIDATION) en
    plusieurs sous-fenetres contigues de taille egale (etape 6, piste 5) -
    une seule periode de validation peut masquer une config qui ne marche
    que dans le regime de marche qu'elle contient par hasard ; regarder
    plusieurs sous-fenetres distinctes revele si la performance est
    consistante ou si elle vient d'une seule d'entre elles."""
    if num_windows < 1 or not candles:
        return [candles] if candles else []
    window_size = max(1, len(candles) // num_windows)
    windows = [candles[i : i + window_size] for i in range(0, len(candles), window_size)]
    # La derniere fenetre peut deborder si len(candles) n'est pas un multiple
    # exact - fusionnee dans l'avant-derniere plutot que laissee trop courte.
    if len(windows) > num_windows:
        windows[-2] = windows[-2] + windows[-1]
        windows = windows[:-1]
    return windows


def compute_window_consistency(
    candles: list, candidate: Candidate, num_windows: int = DEFAULT_CONSISTENCY_WINDOWS
) -> tuple[list[float | None], float | None]:
    """Rejoue `candidate` independamment sur chaque sous-fenetre et retourne
    (rendements par fenetre, score de consistance). Le score est la
    fraction de fenetres EXPLOITABLES (assez de trades) qui sont positives -
    None si aucune fenetre n'a assez de trades pour juger. Une fenetre sans
    assez de trades est ignoree du calcul (ni comptee positive ni negative),
    plutot que de faire echouer toute la mesure."""
    windows = split_into_windows(candles, num_windows)
    returns: list[float | None] = []
    for window in windows:
        result = run_one_backtest(window, candidate)
        returns.append(result.total_return_pct if result is not None else None)

    usable = [r for r in returns if r is not None]
    if not usable:
        return returns, None
    return returns, sum(1 for r in usable if r > 0) / len(usable)


def _since_iso(years: int) -> str:
    import datetime

    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=years * 365)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def split_train_test(candles: list, train_ratio: float = TRAIN_RATIO) -> tuple[list, list]:
    """Decoupe chronologiquement (jamais aleatoirement - on ne doit jamais
    entrainer sur des bougies qui viennent APRES la periode de validation,
    ce serait une fuite d'information/look-ahead bias)."""
    split_idx = int(len(candles) * train_ratio)
    return candles[:split_idx], candles[split_idx:]


def build_sma_cross_candidates() -> list[Candidate]:
    candidates = []
    for short in SMA_SHORT_WINDOWS:
        for long in SMA_LONG_WINDOWS:
            if short >= long:
                continue
            for stop_loss in SMA_STOP_LOSS_OPTIONS:
                for trend_ema in TREND_FILTER_EMA_OPTIONS:
                    for atr_sizing in ATR_SIZING_OPTIONS:
                        candidates.append(Candidate(
                            strategy_type="sma_cross",
                            params={"short_window": short, "long_window": long},
                            risk={
                                "max_position_size_pct": MAX_POSITION_SIZE_PCT,
                                "stop_loss_pct": stop_loss,
                                "take_profit_pct": None,
                                "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
                            },
                            trend_filter_ema_period=trend_ema,
                            atr_sizing_enabled=atr_sizing,
                        ))
    return candidates


def build_scalp_dip_candidates() -> list[Candidate]:
    candidates = []
    for lookback in SCALP_LOOKBACKS:
        for dip_threshold in SCALP_DIP_THRESHOLDS:
            for stop_loss in SCALP_STOP_LOSS_OPTIONS:
                for take_profit in SCALP_TAKE_PROFIT_OPTIONS:
                    for trend_ema in TREND_FILTER_EMA_OPTIONS:
                        for atr_sizing in ATR_SIZING_OPTIONS:
                            candidates.append(Candidate(
                                strategy_type="scalp_dip",
                                params={"lookback": lookback, "dip_threshold_pct": dip_threshold},
                                risk={
                                    "max_position_size_pct": MAX_POSITION_SIZE_PCT,
                                    "stop_loss_pct": stop_loss,
                                    "take_profit_pct": take_profit,
                                    "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
                                },
                                trend_filter_ema_period=trend_ema,
                                atr_sizing_enabled=atr_sizing,
                            ))
    return candidates


def build_mean_reversion_candidates() -> list[Candidate]:
    """Pas de filtre de tendance/sizing ATR croise ici (contrairement aux 2
    autres familles) : un filtre de tendance bloquerait precisement les
    achats en survente que cette strategie cherche a faire - les deux
    concepts sont contradictoires, pas juste une dimension de recherche en
    plus."""
    candidates = []
    for window in MEAN_REVERSION_WINDOWS:
        for num_std in MEAN_REVERSION_NUM_STD:
            for stop_loss in MEAN_REVERSION_STOP_LOSS_OPTIONS:
                candidates.append(Candidate(
                    strategy_type="mean_reversion",
                    params={"window": window, "num_std": num_std},
                    risk={
                        "max_position_size_pct": MAX_POSITION_SIZE_PCT,
                        "stop_loss_pct": stop_loss,
                        "take_profit_pct": None,
                        "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
                    },
                ))
    return candidates


def build_market_making_candidates() -> list[Candidate]:
    candidates = []
    for spread in MARKET_MAKING_SPREAD_PCT:
        for order_size in MARKET_MAKING_ORDER_SIZE_QUOTE:
            for max_inventory in MARKET_MAKING_MAX_INVENTORY_QUOTE:
                if order_size > max_inventory:
                    continue  # un seul ordre ne peut pas depasser le plafond d'inventaire
                for skew in MARKET_MAKING_SKEW_FACTOR:
                    for vol_adaptive in MARKET_MAKING_VOLATILITY_ADAPTIVE_SPREAD_OPTIONS:
                        candidates.append(Candidate(
                            strategy_type="market_making",
                            params={
                                "spread_pct": spread,
                                "order_size_quote": order_size,
                                "max_inventory_quote": max_inventory,
                                "skew_factor": skew,
                                "volatility_adaptive_spread": vol_adaptive,
                                "max_spread_multiplier": MARKET_MAKING_MAX_SPREAD_MULTIPLIER,
                            },
                            risk={"fee_pct": MARKET_MAKING_FEE_PCT},
                        ))
    return candidates


def build_dip_bounce_candidates() -> list[Candidate]:
    """EF-57 (2026-09-16) : grille etendue suite a la recherche manuelle de
    ce soir - stop_loss/trailing_stop (optionnels depuis EF-55) et filtre de
    tendance EMA croises en plus des 4 dimensions d'origine. `force_trade_after_hours`
    fixe a None (jamais varie - aucune preuve empirique a ce jour qu'il faille
    l'activer par defaut, pas la peine de multiplier la grille sur une
    dimension non validee). Pas de croisement ATR (idem, aucune preuve pour
    cette strategie precise)."""
    candidates = []
    for trend_period in DIP_BOUNCE_TREND_MA_PERIODS:
        for dip in DIP_BOUNCE_DIP_THRESHOLDS:
            for arm in DIP_BOUNCE_PROFIT_LOCK_ARM:
                for giveback in DIP_BOUNCE_PROFIT_LOCK_GIVEBACK:
                    trigger = arm - giveback
                    if trigger <= 0:
                        continue
                    for stop_loss in DIP_BOUNCE_STOP_LOSS_OPTIONS:
                        for trailing_stop in DIP_BOUNCE_TRAILING_STOP_OPTIONS:
                            for trend_ema in TREND_FILTER_EMA_OPTIONS:
                                candidates.append(Candidate(
                                    strategy_type="dip_bounce",
                                    params={
                                        "trend_ma_period": trend_period,
                                        "dip_threshold_pct": dip,
                                        "force_trade_after_hours": None,
                                    },
                                    risk={
                                        "max_position_size_pct": MAX_POSITION_SIZE_PCT,
                                        "stop_loss_pct": stop_loss,
                                        "take_profit_pct": None,
                                        "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
                                        "trailing_stop_pct": trailing_stop,
                                        "profit_lock_arm_pct": arm,
                                        "profit_lock_trigger_pct": trigger,
                                    },
                                    trend_filter_ema_period=trend_ema,
                                ))
    return candidates


def build_strategy(candidate: Candidate):
    if candidate.strategy_type == "sma_cross":
        return SmaCrossStrategy(**candidate.params)
    if candidate.strategy_type == "mean_reversion":
        return MeanReversionStrategy(**candidate.params)
    if candidate.strategy_type == "market_making":
        return MarketMakingStrategy(**candidate.params)
    if candidate.strategy_type == "dip_bounce":
        return DipBounceStrategy(**candidate.params)
    return ScalpDipStrategy(**candidate.params)


def run_one_backtest(candles, candidate: Candidate) -> BacktestResult | None:
    strategy = build_strategy(candidate)

    if candidate.strategy_type == "market_making":
        # Pas de RiskManager/trend_filter/atr_sizer externe : ces concepts
        # (sizing en % de capital, stop-loss, filtre de tendance) sont
        # specifiques aux strategies directionnelles et n'ont pas de sens
        # pour du market making (voir mm_engine.py). L'ATR reste pertinent
        # ici sous une forme differente : pas pour dimensionner une position,
        # mais pour elargir le spread cote - gere en interne par
        # MarketMakingStrategy elle-meme (volatility_adaptive_spread), pas
        # par un AtrSizer externe passe a l'engine.
        portfolio = Portfolio(starting_capital=STARTING_CAPITAL, fee_pct=candidate.risk.get("fee_pct", MARKET_MAKING_FEE_PCT))
        executor = BacktestExecutor(portfolio)
        engine = MarketMakingEngine(strategy, executor, portfolio)
        engine.run_backtest(candles)
    else:
        risk_manager = RiskManager(RiskConfig(**candidate.risk))
        portfolio = Portfolio(starting_capital=STARTING_CAPITAL, fee_pct=risk_manager.config.fee_pct)
        executor = BacktestExecutor(portfolio)
        trend_filter = TrendFilter(ema_period=candidate.trend_filter_ema_period) if candidate.trend_filter_ema_period else None
        atr_sizer = (
            AtrSizer(
                atr_period=DEFAULT_ATR_PERIOD,
                baseline_period=DEFAULT_ATR_BASELINE_PERIOD,
                min_size_multiplier=DEFAULT_ATR_MIN_MULTIPLIER,
            )
            if candidate.atr_sizing_enabled
            else None
        )
        engine = Engine(strategy, risk_manager, executor, portfolio, trend_filter=trend_filter, atr_sizer=atr_sizer)
        engine.run_backtest(candles)

    if len(portfolio.trade_history) < MIN_TRADES_FOR_SIGNIFICANCE:
        return None

    report = compute_report(portfolio)
    wins = [t for t in portfolio.trade_history if t["pnl"] > 0]
    return BacktestResult(
        symbol="",  # rempli par l'appelant
        candidate=candidate,
        total_return_pct=report.total_return_pct,
        max_drawdown_pct=report.max_drawdown_pct,
        num_trades=len(portfolio.trade_history),
        win_rate=len(wins) / len(portfolio.trade_history),
        realized_pnl=report.realized_pnl,
        benchmark_return_pct=compute_buy_and_hold_return_pct(candles),
    )


def _format_trend_filter(candidate: Candidate) -> str:
    return f", trend_ema={candidate.trend_filter_ema_period}" if candidate.trend_filter_ema_period else ""


def _format_atr_sizing(candidate: Candidate) -> str:
    return ", atr_sizing=on" if candidate.atr_sizing_enabled else ""


def _format_vol_adaptive_spread(candidate: Candidate) -> str:
    return ", spread_adaptatif=on" if candidate.params.get("volatility_adaptive_spread") else ""


def _format_stop_loss(risk: dict) -> str:
    return f"{risk['stop_loss_pct']:.0%}" if risk.get("stop_loss_pct") is not None else "aucun"


def _format_trailing_stop(risk: dict) -> str:
    return f", trailing={risk['trailing_stop_pct']:.0%}" if risk.get("trailing_stop_pct") else ""


def format_candidate(candidate: Candidate) -> str:
    p = candidate.params
    r = candidate.risk
    if candidate.strategy_type == "sma_cross":
        return (
            f"sma_cross(court={p['short_window']}, long={p['long_window']}, "
            f"stop_loss={r['stop_loss_pct']:.0%}{_format_trend_filter(candidate)}{_format_atr_sizing(candidate)})"
        )
    if candidate.strategy_type == "mean_reversion":
        return f"mean_reversion(fenetre={p['window']}, ecart_type={p['num_std']}, stop_loss={r['stop_loss_pct']:.0%})"
    if candidate.strategy_type == "market_making":
        return (
            f"market_making(spread={p['spread_pct']:.2%}, ordre={p['order_size_quote']:.0f}, "
            f"inventaire_max={p['max_inventory_quote']:.0f}, skew={p['skew_factor']}"
            f"{_format_vol_adaptive_spread(candidate)})"
        )
    if candidate.strategy_type == "dip_bounce":
        return (
            f"dip_bounce(fenetre={p['trend_ma_period']}, seuil_creux={p['dip_threshold_pct']:.2%}, "
            f"verrou_armement={r['profit_lock_arm_pct']:.2%}, verrou_declenchement={r['profit_lock_trigger_pct']:.2%}, "
            f"stop_loss={_format_stop_loss(r)}{_format_trailing_stop(r)}{_format_trend_filter(candidate)})"
        )
    return (
        f"scalp_dip(lookback={p['lookback']}, seuil={p['dip_threshold_pct']:.1%}, "
        f"stop_loss={r['stop_loss_pct']:.0%}, take_profit={r['take_profit_pct']:.1%}"
        f"{_format_trend_filter(candidate)}{_format_atr_sizing(candidate)})"
    )


def result_to_config_yaml(result: BacktestResult, name: str) -> str:
    warmup_candles = max(
        result.candidate.params.get("long_window", 0),
        result.candidate.params.get("lookback", 0),
        result.candidate.params.get("window", 0),
        result.candidate.params.get("trend_ma_period", 0),
        result.candidate.trend_filter_ema_period or 0,
        DEFAULT_ATR_BASELINE_PERIOD if result.candidate.atr_sizing_enabled else 0,
        DEFAULT_ATR_BASELINE_PERIOD if result.candidate.params.get("volatility_adaptive_spread") else 0,
        30,
    )
    config = {
        "name": name,
        "exchange": "binance",
        "symbol": result.symbol,
        "timeframe": TIMEFRAME,
        "warmup_candles": warmup_candles,
        "flatten_on_start": True,
        "capital_allocated": 200,
        "strategy": {"type": result.candidate.strategy_type, **result.candidate.params},
        "risk": result.candidate.risk,
        "backtest": {"starting_capital": 1000, "since": _since_iso(SINCE_YEARS)},
    }
    if result.candidate.trend_filter_ema_period:
        config["trend_filter"] = {"enabled": True, "ema_period": result.candidate.trend_filter_ema_period}
    if result.candidate.atr_sizing_enabled:
        config["atr_sizing"] = {
            "enabled": True,
            "atr_period": DEFAULT_ATR_PERIOD,
            "baseline_period": DEFAULT_ATR_BASELINE_PERIOD,
            "min_size_multiplier": DEFAULT_ATR_MIN_MULTIPLIER,
        }
    return yaml.safe_dump(config, allow_unicode=True, sort_keys=False)


def write_config_without_overwriting(config_name: str, yaml_content: str) -> tuple[Path, bool]:
    """Ecrit `config/{config_name}.yml`, sauf si ce fichier existe deja - ce
    nom est derive du symbole/de la strategie et peut donc coincider EXACTEMENT
    avec la config d'un bot DEJA DEPLOYE, cree par un run precedent de cet
    outil (CT-21 de la STB : ecraser en silence a deja fait perdre un reglage
    de capital/sizing tune manuellement). Dans ce cas, ecrit a cote dans
    `config/{config_name}_candidate.yml` et retourne `was_renamed=True` pour
    que l'appelant puisse avertir l'utilisateur. Retourne (chemin ecrit,
    a-t-il ete renomme)."""
    config_path = Path(f"config/{config_name}.yml")
    was_renamed = config_path.exists()
    if was_renamed:
        config_path = Path(f"config/{config_name}_candidate.yml")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(yaml_content)
    return config_path, was_renamed


def _fmt_result(r: BacktestResult | None) -> str:
    if r is None:
        return "pas assez de trades"
    benchmark = ""
    if r.benchmark_return_pct is not None:
        flag = "bat" if r.beats_benchmark else "perd contre"
        benchmark = f", {flag} buy&hold {r.benchmark_return_pct*100:+.2f}%"
    return (
        f"{r.total_return_pct*100:+6.2f}% (drawdown {r.max_drawdown_pct*100:4.1f}%, {r.num_trades:>3} trades, "
        f"win {r.win_rate*100:4.1f}%, score ajuste au risque {r.risk_adjusted_return:+.2f}{benchmark})"
    )


def main(symbols: list[str]) -> None:
    all_candidates = (
        build_sma_cross_candidates() + build_scalp_dip_candidates()
        + build_mean_reversion_candidates() + build_market_making_candidates()
        + build_dip_bounce_candidates()
    )
    print(f"{len(all_candidates)} combinaisons de parametres a tester par paire, sur {len(symbols)} paire(s).")
    print(f"Periode : {SINCE_YEARS} ans, timeframe {TIMEFRAME}.")
    print(f"Decoupage : {TRAIN_RATIO*100:.0f}% entrainement / {(1-TRAIN_RATIO)*100:.0f}% validation (jamais vue pendant la recherche).\n")

    validated: list[ValidatedResult] = []
    test_candles_by_symbol: dict[str, list] = {}
    for symbol in symbols:
        print(f"Chargement de l'historique {symbol}...")
        candles = fetch_historical_candles(
            exchange_id="binance", symbol=symbol, timeframe=TIMEFRAME, since_iso=_since_iso(SINCE_YEARS)
        )
        train_candles, test_candles = split_train_test(candles)
        test_candles_by_symbol[symbol] = test_candles
        print(f"  {len(train_candles)} bougies (entrainement) / {len(test_candles)} bougies (validation).")

        train_results = []
        for candidate in all_candidates:
            result = run_one_backtest(train_candles, candidate)
            if result is not None:
                result.symbol = symbol
                train_results.append(result)
        train_results.sort(key=lambda r: r.risk_adjusted_return, reverse=True)
        print(f"  {len(train_results)}/{len(all_candidates)} combinaisons exploitables a l'entrainement. "
              f"Validation des {min(TOP_N_FOR_VALIDATION, len(train_results))} meilleures...\n")

        for train_result in train_results[:TOP_N_FOR_VALIDATION]:
            test_result = run_one_backtest(test_candles, train_result.candidate)
            if test_result is not None:
                test_result.symbol = symbol
            validated.append(ValidatedResult(
                symbol=symbol, candidate=train_result.candidate, train=train_result, test=test_result
            ))

    if not validated:
        print("Aucune combinaison n'a genere assez de trades pour etre exploitable. Essaie une periode plus longue ou des seuils plus sensibles.")
        return

    # Classe par performance de VALIDATION (out-of-sample), pas d'entrainement -
    # c'est le point entier de cette methode : un candidat qui a l'air genial
    # a l'entrainement mais s'effondre en validation est ecarte naturellement.
    # Classe sur le rendement AJUSTE AU RISQUE (etape 6, piste 4), pas le
    # rendement brut - un candidat qui gagne gros avec un drawdown enorme
    # n'est pas "meilleur" qu'un candidat plus regulier a rendement egal.
    validated.sort(key=lambda v: v.test.risk_adjusted_return if v.test else float("-inf"), reverse=True)

    print("=" * 100)
    print("TOP 10 (classes par performance de VALIDATION, jamais vue pendant la recherche) :")
    print("=" * 100)
    for i, v in enumerate(validated[:10], 1):
        print(f"{i:>2}. {v.symbol:<10} {format_candidate(v.candidate)}")
        print(f"      entrainement : {_fmt_result(v.train)}")
        print(f"      validation   : {_fmt_result(v.test)}")

    candidates_with_test = [v for v in validated if v.test is not None]
    if not candidates_with_test:
        print("\nAucun candidat n'a assez de trades sur la periode de validation - resultats non exploitables en confiance.")
        return

    best = candidates_with_test[0]
    print("\n" + "=" * 100)
    print(f"MEILLEUR RESULTAT (sur validation) : {best.symbol} - {format_candidate(best.candidate)}")
    print("=" * 100)
    print(f"Entrainement : {_fmt_result(best.train)}")
    print(f"Validation   : {_fmt_result(best.test)}")

    # Etape 6 (piste 5) : la periode de validation est decoupee en
    # sous-fenetres pour verifier que la performance n'est pas concentree
    # sur un seul regime de marche cache dans cette periode.
    window_returns, consistency = compute_window_consistency(test_candles_by_symbol[best.symbol], best.candidate)
    window_str = ", ".join(f"{r*100:+.2f}%" if r is not None else "n/a" for r in window_returns)
    print(f"Consistance  : {window_str} ({len(window_returns)} sous-fenetres)")
    if consistency is not None and consistency < 0.5:
        print(
            f"\nATTENTION : ce candidat n'est positif que sur {consistency*100:.0f}% des sous-fenetres de validation "
            "- sa performance globale est peut-etre concentree sur un seul regime de marche plutot qu'un edge "
            "consistant. A tester en paper trading avec prudence."
        )

    if best.test.total_return_pct < best.train.total_return_pct / 2:
        print(
            "\nATTENTION : la performance de validation est nettement plus faible qu'a l'entrainement "
            "- signe classique de surapprentissage. A tester en paper trading avec prudence."
        )

    if best.test.beats_benchmark is False:
        print(
            f"\nATTENTION : ce candidat perd contre un simple achat-conservation (buy & hold) sur la meme "
            f"periode de validation ({best.test.total_return_pct*100:+.2f}% vs {best.test.benchmark_return_pct*100:+.2f}%) "
            "- son edge reel est donc discutable, la performance vient peut-etre juste d'un marche haussier."
        )

    config_name = f"optimized_{best.symbol.replace('/', '').lower()}_{best.candidate.strategy_type}"
    config_path, was_renamed = write_config_without_overwriting(config_name, result_to_config_yaml(best, config_name))
    if was_renamed:
        print(
            f"\nATTENTION : config/{config_name}.yml existe deja (bot probablement deja deploye) - "
            f"le nouveau resultat est ecrit a cote dans {config_path} plutot que d'ecraser l'existant."
        )
    print(f"\nConfig prete a l'emploi ecrite dans {config_path} (PAS lancee automatiquement).")

    print(
        "\nRAPPEL : meme valide sur une periode jamais vue, ce resultat reste un backtest sur "
        "donnees passees. Il ne garantit pas une performance future - valide toujours en mode "
        "paper pendant plusieurs jours avant de considerer ce resultat comme fiable."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols", type=str, default=",".join(DEFAULT_SYMBOLS),
        help="Paires a tester, separees par des virgules (defaut: BTC/USDT,ETH/USDT,DOGE/USDT)",
    )
    args = parser.parse_args()
    symbols_list = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    try:
        main(symbols_list)
    except Exception as e:
        print(f"Erreur : {e}", file=sys.stderr)
        sys.exit(1)
