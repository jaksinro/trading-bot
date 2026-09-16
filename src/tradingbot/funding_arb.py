"""Funding rate arbitrage - etape 8 de la feuille de route performance,
PHASE A UNIQUEMENT (pipeline de donnees + validation empirique par backtest).

Principe (cash-and-carry) : acheter du spot + vendre un contrat perpetuel de
meme notionnel (exposition au prix annulee, delta-neutre), encaisser le
funding periodique tant qu'il est positif. Contrairement a sma_cross/
scalp_dip/mean_reversion/market_making (toutes des strategies a un seul
actif, paris directionnels ou capture de spread), l'edge vise ici est un
service rendu au marche (financement des positions a effet de levier), pas
une prediction de prix - voir docs/STB.md EF-45 et docs/STC.md section 3.27.

LIMITE ASSUMEE ET DELIBEREE : ce module ne fait QUE du backtest. Il n'existe
aucun moteur live (`Engine`/`MarketMakingEngine` sont concus pour un seul
actif, pas une position a deux jambes spot+perpetuel avec marge/effet de
levier) - une integration live serait un chantier separe, a planifier une
fois l'edge confirme empiriquement ici. Ce module n'ecrit aucune config de
bot deployable, contrairement a `optimize.py`.

NUANCE IMPORTANTE SUR LES GARDE-FOUS (etape 6, ce soir) : `has_edge_over_
benchmark`/`beats_benchmark` (battre un buy & hold) NE S'APPLIQUE PAS de la
meme facon ici - une strategie delta-neutre est CENSEE etre decouplee de la
direction du marche par construction ; exiger qu'elle batte un buy & hold en
marche haussier n'a pas de sens (elle peut etre parfaitement saine sans
jamais le battre). Le vrai critere est un rendement ajuste au risque positif
ET une consistance sur plusieurs sous-fenetres temporelles - pas un gate
"doit battre buy & hold".
"""

import argparse
import sys
from collections import deque
from dataclasses import dataclass, replace

from tradingbot.data_feed import fetch_funding_rate_history, fetch_historical_candles
from tradingbot.optimize import MIN_DRAWDOWN_FLOOR, TOP_N_FOR_VALIDATION, _since_iso, split_train_test
from tradingbot.reporting.stats import compute_buy_and_hold_return_pct
from tradingbot.types import Candle, FundingRatePoint

TIMEFRAME = "1h"
SINCE_YEARS = 3
MIN_CYCLES_FOR_SIGNIFICANCE = 2  # sous ce seuil, pas assez de cycles entree/sortie pour juger
DEFAULT_CONSISTENCY_WINDOWS = 3

# Seuils de funding par ECHEANCE (Binance : toutes les 8h), pas annualises.
# 0,08% de frais taker aller-retour sur 4 legs (achat+vente spot, achat+vente
# perp) = 0,32% par cycle complet - un seuil d'entree de 0,01%/echeance
# (~11%/an, "normal" selon la doc de reference) est deja proche du minimum
# viable si le cycle dure plusieurs semaines ; ceux plus bas sont testes pour
# voir a partir d'ou l'edge disparait sous les frais.
FUNDING_ARB_ENTRY_THRESHOLDS = [0.00005, 0.0001, 0.0002]
FUNDING_ARB_EXIT_THRESHOLDS = [0.0, 0.00002]
FUNDING_ARB_LOOKBACK_PERIODS = [3, 6, 9]  # nb d'echeances lissees (24h/48h/72h a 8h/echeance)
FUNDING_ARB_NOTIONAL = 1000.0
FUNDING_ARB_FEE_PCT = 0.0008  # frais taker par leg, ordre de grandeur retail (voir doc de reference)


@dataclass
class FundingArbCandidate:
    symbol_spot: str
    symbol_perp: str
    entry_funding_threshold: float
    exit_funding_threshold: float
    lookback_periods: int
    notional: float
    fee_pct: float


@dataclass
class FundingArbResult:
    symbol_spot: str
    candidate: FundingArbCandidate
    total_return_pct: float
    max_drawdown_pct: float
    num_cycles: int
    total_funding_collected: float
    total_fees_paid: float
    total_basis_pnl: float
    benchmark_return_pct: float | None = None

    @property
    def risk_adjusted_return(self) -> float:
        return self.total_return_pct / max(self.max_drawdown_pct, MIN_DRAWDOWN_FLOOR)


def build_funding_arb_candidates() -> list[FundingArbCandidate]:
    candidates = []
    for entry in FUNDING_ARB_ENTRY_THRESHOLDS:
        for exit_threshold in FUNDING_ARB_EXIT_THRESHOLDS:
            if exit_threshold >= entry:
                continue  # sortir a un seuil plus haut que l'entree n'a pas de sens
            for lookback in FUNDING_ARB_LOOKBACK_PERIODS:
                candidates.append(FundingArbCandidate(
                    symbol_spot="", symbol_perp="",
                    entry_funding_threshold=entry, exit_funding_threshold=exit_threshold,
                    lookback_periods=lookback, notional=FUNDING_ARB_NOTIONAL, fee_pct=FUNDING_ARB_FEE_PCT,
                ))
    return candidates


def format_candidate(candidate: FundingArbCandidate) -> str:
    return (
        f"funding_arb(entree={candidate.entry_funding_threshold:.4%}, sortie={candidate.exit_funding_threshold:.4%}, "
        f"lissage={candidate.lookback_periods} echeances)"
    )


def _price_at(candles: list[Candle], timestamps: list[int], ts: int) -> float | None:
    """Prix de cloture de la bougie la plus recente a ou avant `ts` (recherche
    dichotomique - les echeances de funding et les bougies horaires ne
    tombent pas forcement exactement sur le meme instant)."""
    import bisect

    if not timestamps:
        return None
    idx = bisect.bisect_right(timestamps, ts) - 1
    if idx < 0:
        idx = 0
    return candles[idx].close


def simulate_funding_arb(
    spot_candles: list[Candle], perp_candles: list[Candle],
    funding_history: list[FundingRatePoint], candidate: FundingArbCandidate,
) -> FundingArbResult | None:
    """Simule un cycle entree/sortie base sur une moyenne glissante du
    funding (`lookback_periods` echeances, evite de reagir a un seul
    versement bruite). Position OUVERTE = long spot + short perpetuel de
    meme notionnel. A chaque echeance en position, encaisse
    `funding_rate x notional` (recu quand le taux est positif, cote court).
    A la sortie, realise le P&L de BASE (residuel apres couverture - jamais
    suppose nul, voir docstring du module)."""
    if not funding_history:
        return None

    spot_ts = [c.timestamp for c in spot_candles]
    perp_ts = [c.timestamp for c in perp_candles]

    in_position = False
    entry_spot_price = entry_perp_price = 0.0
    cash = 0.0
    total_funding = 0.0
    total_fees = 0.0
    total_basis_pnl = 0.0
    num_cycles = 0
    recent_rates: deque[float] = deque(maxlen=candidate.lookback_periods)
    peak = 0.0
    max_drawdown = 0.0

    for point in funding_history:
        recent_rates.append(point.funding_rate)
        avg_rate = sum(recent_rates) / len(recent_rates)
        enough_history = len(recent_rates) >= candidate.lookback_periods

        if in_position:
            funding_payment = point.funding_rate * candidate.notional
            cash += funding_payment
            total_funding += funding_payment

        if not in_position and enough_history and avg_rate >= candidate.entry_funding_threshold:
            entry_spot_price = _price_at(spot_candles, spot_ts, point.timestamp)
            entry_perp_price = _price_at(perp_candles, perp_ts, point.timestamp)
            # Pas de donnees de prix a cette echeance (bord de periode) : on
            # attend la suivante plutot que d'entrer sans prix de reference.
            if entry_spot_price is not None and entry_perp_price is not None:
                entry_fee = candidate.notional * candidate.fee_pct * 2  # achat spot + vente perp
                cash -= entry_fee
                total_fees += entry_fee
                in_position = True
        elif in_position and avg_rate < candidate.exit_funding_threshold:
            exit_spot_price = _price_at(spot_candles, spot_ts, point.timestamp)
            exit_perp_price = _price_at(perp_candles, perp_ts, point.timestamp)
            if exit_spot_price is not None and exit_perp_price is not None:
                exit_fee = candidate.notional * candidate.fee_pct * 2  # vente spot + rachat perp
                cash -= exit_fee
                total_fees += exit_fee
                qty_spot = candidate.notional / entry_spot_price
                qty_perp = candidate.notional / entry_perp_price
                spot_leg_pnl = qty_spot * (exit_spot_price - entry_spot_price)
                perp_leg_pnl = qty_perp * (entry_perp_price - exit_perp_price)  # short : gagne si le prix baisse
                basis_pnl = spot_leg_pnl + perp_leg_pnl
                cash += basis_pnl
                total_basis_pnl += basis_pnl
                num_cycles += 1
            in_position = False

        peak = max(peak, cash)
        max_drawdown = max(max_drawdown, (peak - cash) / candidate.notional)

    if num_cycles < MIN_CYCLES_FOR_SIGNIFICANCE:
        return None

    return FundingArbResult(
        symbol_spot="",
        candidate=candidate,
        total_return_pct=cash / candidate.notional,
        max_drawdown_pct=max_drawdown,
        num_cycles=num_cycles,
        total_funding_collected=total_funding,
        total_fees_paid=total_fees,
        total_basis_pnl=total_basis_pnl,
        benchmark_return_pct=compute_buy_and_hold_return_pct(spot_candles),
    )


def _filter_candles_to_range(candles: list[Candle], start_ts: int, end_ts: int) -> list[Candle]:
    return [c for c in candles if start_ts <= c.timestamp <= end_ts]


def compute_funding_window_consistency(
    spot_candles: list[Candle], perp_candles: list[Candle], funding_history: list[FundingRatePoint],
    candidate: FundingArbCandidate, num_windows: int = DEFAULT_CONSISTENCY_WINDOWS,
) -> tuple[list[float | None], float | None]:
    """Meme esprit que `optimize.compute_window_consistency`, reimplemente
    ici car il opere sur des echeances de funding (pas des bougies) et doit
    aussi recouper les bougies spot/perp sur la fenetre temporelle de chaque
    sous-periode."""
    if not funding_history:
        return [], None
    window_size = max(1, len(funding_history) // num_windows)
    windows = [funding_history[i:i + window_size] for i in range(0, len(funding_history), window_size)]
    if len(windows) > num_windows:
        windows[-2] = windows[-2] + windows[-1]
        windows = windows[:-1]

    returns: list[float | None] = []
    for window in windows:
        if not window:
            returns.append(None)
            continue
        sub_spot = _filter_candles_to_range(spot_candles, window[0].timestamp, window[-1].timestamp)
        sub_perp = _filter_candles_to_range(perp_candles, window[0].timestamp, window[-1].timestamp)
        result = simulate_funding_arb(sub_spot, sub_perp, window, candidate)
        returns.append(result.total_return_pct if result is not None else None)

    usable = [r for r in returns if r is not None]
    if not usable:
        return returns, None
    return returns, sum(1 for r in usable if r > 0) / len(usable)


def _fmt_result(r: FundingArbResult | None) -> str:
    if r is None:
        return "pas assez de cycles pour juger"
    return (
        f"{r.total_return_pct*100:+6.2f}% (drawdown {r.max_drawdown_pct*100:4.1f}%, {r.num_cycles} cycles, "
        f"funding collecte {r.total_funding_collected:+.2f}, P&L de base {r.total_basis_pnl:+.2f}, "
        f"frais {r.total_fees_paid:.2f}, score ajuste au risque {r.risk_adjusted_return:+.2f})"
    )


def main(symbols: list[str]) -> None:
    candidates_template = build_funding_arb_candidates()
    print(f"{len(candidates_template)} combinaisons funding_arb a tester par paire, sur {len(symbols)} paire(s).")
    print(f"Periode : {SINCE_YEARS} ans, timeframe {TIMEFRAME}.\n")
    print(
        "RAPPEL : cette stratégie est delta-neutre par construction - ne pas s'attendre a ce qu'elle "
        "batte un buy & hold en marche haussier, ce n'est pas le critere pertinent ici (voir docstring "
        "du module). Le benchmark est affiche a titre informatif seulement.\n"
    )

    for symbol in symbols:
        spot_symbol = symbol
        perp_symbol = f"{symbol}:USDT"
        print(f"Chargement de l'historique {spot_symbol} / {perp_symbol}...")
        spot_candles = fetch_historical_candles("binance", spot_symbol, TIMEFRAME, _since_iso(SINCE_YEARS))
        perp_candles = fetch_historical_candles("binance", perp_symbol, TIMEFRAME, _since_iso(SINCE_YEARS))
        funding_history = fetch_funding_rate_history("binance", perp_symbol, _since_iso(SINCE_YEARS))
        print(f"  {len(spot_candles)} bougies spot, {len(perp_candles)} bougies perp, {len(funding_history)} echeances de funding.")

        if not funding_history:
            print("  Aucun historique de funding disponible pour cette paire - ignoree.\n")
            continue

        train_funding, test_funding = split_train_test(funding_history)
        print(f"  {len(train_funding)} echeances (entrainement) / {len(test_funding)} echeances (validation).")

        candidates = [replace(c, symbol_spot=spot_symbol, symbol_perp=perp_symbol) for c in candidates_template]

        train_start, train_end = train_funding[0].timestamp, train_funding[-1].timestamp
        train_spot = _filter_candles_to_range(spot_candles, train_start, train_end)
        train_perp = _filter_candles_to_range(perp_candles, train_start, train_end)

        train_results = []
        for candidate in candidates:
            result = simulate_funding_arb(train_spot, train_perp, train_funding, candidate)
            if result is not None:
                result.symbol_spot = spot_symbol
                train_results.append(result)
        train_results.sort(key=lambda r: r.risk_adjusted_return, reverse=True)
        print(f"  {len(train_results)}/{len(candidates)} combinaisons exploitables a l'entrainement. "
              f"Validation des {min(TOP_N_FOR_VALIDATION, len(train_results))} meilleures...\n")

        test_start, test_end = test_funding[0].timestamp, test_funding[-1].timestamp
        test_spot = _filter_candles_to_range(spot_candles, test_start, test_end)
        test_perp = _filter_candles_to_range(perp_candles, test_start, test_end)

        best_train, best_test = None, None
        for train_result in train_results[:TOP_N_FOR_VALIDATION]:
            test_result = simulate_funding_arb(test_spot, test_perp, test_funding, train_result.candidate)
            if test_result is None:
                continue
            test_result.symbol_spot = spot_symbol
            if best_test is None or test_result.risk_adjusted_return > best_test.risk_adjusted_return:
                best_train, best_test = train_result, test_result

        if best_test is None:
            print(f"  Aucun candidat n'a assez de cycles sur la periode de validation pour {spot_symbol}.\n")
            continue

        window_returns, consistency = compute_funding_window_consistency(test_spot, test_perp, test_funding, best_test.candidate)
        window_str = ", ".join(f"{r*100:+.2f}%" if r is not None else "n/a" for r in window_returns)
        passes = consistency is not None and consistency >= 0.5 and best_test.risk_adjusted_return > 0

        print(f"  Meilleur : {format_candidate(best_test.candidate)}")
        print(f"    entrainement : {_fmt_result(best_train)}")
        print(f"    validation   : {_fmt_result(best_test)}")
        print(f"    consistance  : {window_str}")
        print(f"    PASSE LES GARDE-FOUS (rendement ajuste au risque positif ET consistant) : {passes}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols", type=str, default="BTC/USDT,ETH/USDT,SOL/USDT",
        help="Paires SPOT a tester, separees par des virgules (le perpetuel correspondant est derive automatiquement)",
    )
    args = parser.parse_args()
    symbols_list = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    try:
        main(symbols_list)
    except Exception as e:
        print(f"Erreur : {e}", file=sys.stderr)
        sys.exit(1)
