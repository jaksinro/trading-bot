"""Tests du bot d'investissement regulier (EF-67) - donnees synthetiques
uniquement, aucun appel reseau (comme toutes les suites existantes)."""
import tradingbot.dca_allocator as dca_module
from tradingbot.dca_allocator import (
    annualised_money_weighted_return_pct,
    parse_weights,
    run_backtest,
    simulate,
)
from tradingbot.types import Candle

DAY_MS = 86_400_000
# 2024-01-01 en ms UTC, pour que les cles de jour tombent sur des mois reels.
START_MS = 1_704_067_200_000


def make_candles(closes: list[float], start_ms: int = START_MS, step_ms: int = DAY_MS) -> list[Candle]:
    return [
        Candle(timestamp=start_ms + i * step_ms, open=c, high=c, low=c, close=c, volume=1.0)
        for i, c in enumerate(closes)
    ]


def test_parse_weights_equal_weighted_by_default():
    assert parse_weights("A,B,C,D") == {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}


def test_parse_weights_explicit_are_normalised_to_one():
    weights = parse_weights("A:30,B:70")
    assert weights == {"A": 0.3, "B": 0.7}


def test_parse_weights_normalises_even_when_sum_is_not_100():
    weights = parse_weights("A:1,B:3")
    assert weights == {"A": 0.25, "B": 0.75}


def test_money_weighted_return_on_a_single_known_cashflow():
    """100 investis qui valent 110 un an plus tard = +10 %/an."""
    rate = annualised_money_weighted_return_pct([(0, 100.0)], final_value=110.0, final_day_index=365)
    assert rate is not None
    assert abs(rate - 10.0) < 0.01


def test_money_weighted_return_ignores_money_that_had_no_time_to_work():
    """Deux versements de 100 : le premier place 2 ans, le seuxieme le
    dernier jour. Une valeur finale de 300 correspond donc a un gain de 100
    genere par 100 investis pendant 2 ans, pas a +50 % sur 200."""
    rate = annualised_money_weighted_return_pct(
        [(0, 100.0), (730, 100.0)], final_value=300.0, final_day_index=730,
    )
    assert rate is not None
    # 100 * (1+r)^2 + 100 = 300  ->  r = sqrt(2) - 1 = 41,42 %
    assert abs(rate - 41.42) < 0.05


def test_money_weighted_return_is_negative_when_losing_money():
    rate = annualised_money_weighted_return_pct([(0, 1000.0)], final_value=500.0, final_day_index=365)
    assert rate is not None
    assert abs(rate - (-50.0)) < 0.01


def test_contributions_happen_once_per_calendar_month():
    """Le versement tombe le premier jour OUVRE du mois : sur 70 jours
    consecutifs a partir du 1er janvier, on doit compter 3 versements
    (janvier, fevrier, mars), pas un par jour."""
    candles = make_candles([100.0] * 70)
    result = simulate(
        {"A": candles}, {"A": 1.0}, initial_capital=0.0, monthly_contribution=200.0,
        rebalance_band_pct=None, fee_pct=0.0,
    )
    assert len(result.contributions) == 3
    assert result.total_invested == 600.0
    months = [day[:7] for day, _ in result.contributions]
    assert months == ["2024-01", "2024-02", "2024-03"]


def test_only_whole_shares_are_bought_and_the_remainder_stays_in_cash():
    """Action a 150 avec 200 verses : 1 titre achete, 50 restent en
    liquidites (contrainte reelle du courtier, cf. IBPaperExecutor)."""
    candles = make_candles([150.0] * 20)
    result = simulate(
        {"A": candles}, {"A": 1.0}, initial_capital=0.0, monthly_contribution=200.0,
        rebalance_band_pct=None, fee_pct=0.0,
    )
    assert result.holdings == {"A": 1.0}
    assert abs(result.cash - 50.0) < 1e-9
    assert all(float(t.quantity).is_integer() for t in result.trades)


def test_no_stop_loss_a_crash_is_never_sold():
    """Garde-fou explicite sur le choix de conception : meme une chute de
    80 % ne doit declencher AUCUNE vente (c'est tout l'interet d'une
    approche achetee-et-gardee)."""
    candles = make_candles([100.0] * 10 + [20.0] * 30)
    result = simulate(
        {"A": candles}, {"A": 1.0}, initial_capital=1000.0, monthly_contribution=0.0,
        rebalance_band_pct=5.0, fee_pct=0.0,
    )
    assert [t for t in result.trades if t.side == "sell"] == []
    assert result.max_drawdown_pct > 70


def test_rebalancing_sells_the_winner_to_buy_the_laggard():
    """A double, B est stable : la ligne A depasse sa cible de 50 % et doit
    etre allegee au profit de B."""
    candles_a = make_candles([10.0] * 5 + [20.0] * 15)
    candles_b = make_candles([10.0] * 20)
    result = simulate(
        {"A": candles_a, "B": candles_b}, {"A": 0.5, "B": 0.5}, initial_capital=1000.0,
        monthly_contribution=0.0, rebalance_band_pct=5.0, fee_pct=0.0,
    )
    sells = [t for t in result.trades if t.side == "sell"]
    assert sells, "un rééquilibrage etait attendu apres le doublement de A"
    assert all(t.symbol == "A" for t in sells), "seule la ligne en excedent doit etre allegee"
    final_a = result.holdings["A"] * 20.0
    final_b = result.holdings["B"] * 10.0
    assert abs(final_a - final_b) / (final_a + final_b) < 0.1


def test_no_rebalance_band_lets_the_allocation_drift():
    candles_a = make_candles([10.0] * 5 + [20.0] * 15)
    candles_b = make_candles([10.0] * 20)
    result = simulate(
        {"A": candles_a, "B": candles_b}, {"A": 0.5, "B": 0.5}, initial_capital=1000.0,
        monthly_contribution=0.0, rebalance_band_pct=None, fee_pct=0.0,
    )
    assert [t for t in result.trades if t.side == "sell"] == []


def test_contributions_are_steered_to_the_laggard_when_following_drift():
    """Coeur du "rééquilibrage par les versements" : A a double, donc
    l'argent neuf doit aller vers B sans rien vendre."""
    candles_a = make_candles([10.0] * 5 + [20.0] * 40)
    candles_b = make_candles([10.0] * 45)
    result = simulate(
        {"A": candles_a, "B": candles_b}, {"A": 0.5, "B": 0.5}, initial_capital=200.0,
        monthly_contribution=100.0, rebalance_band_pct=None, fee_pct=0.0,
        follow_drift_on_contribution=True,
    )
    bought_after_the_jump = [t for t in result.trades if t.side == "buy" and t.day >= "2024-02"]
    assert bought_after_the_jump
    assert all(t.symbol == "B" for t in bought_after_the_jump)


def test_fees_are_charged_and_reported():
    candles = make_candles([100.0] * 20)
    result = simulate(
        {"A": candles}, {"A": 1.0}, initial_capital=1000.0, monthly_contribution=0.0,
        rebalance_band_pct=None, fee_pct=0.01,
    )
    # 9 titres a 100 achetables avec 1000 en payant 1 % de frais (9 * 101 = 909).
    assert result.holdings == {"A": 9.0}
    assert abs(result.total_fees - 9.0) < 1e-9


def test_rebalancing_frequency_is_capped_no_daily_churn():
    """Regression sur un bug REEL mesure (51 320 ordres, 19 % des versements
    partis en frais) : sur un petit portefeuille, la contrainte du titre
    entier rend la cible inatteignable, donc la bande reste depassee en
    permanence. Sans plafond de frequence, le bot rééquilibrait chaque jour."""
    # 11 lignes ciblees a ~9 % avec de petits versements : la cible exacte
    # est structurellement hors d'atteinte, la bande est donc toujours violee.
    symbols = [f"S{i}" for i in range(11)]
    candles = {s: make_candles([100.0 + i] * 400) for i, s in enumerate(symbols)}
    weights = {s: 1 / len(symbols) for s in symbols}

    result = simulate(
        candles, weights, initial_capital=0.0, monthly_contribution=200.0,
        rebalance_band_pct=5.0, fee_pct=0.001, min_rebalance_interval_days=90,
    )

    rebalance_days = {t.day for t in result.trades if t.reason == "rebalance"}
    # ~400 jours de bourse : au plus 5 fenetres trimestrielles.
    assert len(rebalance_days) <= 5, f"churn detecte : {len(rebalance_days)} jours de rééquilibrage"
    assert result.total_fees / result.total_invested < 0.02, "les frais doivent rester marginaux"


def test_micro_orders_are_skipped():
    """Un ecart de quelques euros ne doit pas declencher d'ordre : les frais
    mangeraient la correction."""
    candles_a = make_candles([100.0] * 5 + [101.0] * 200)
    candles_b = make_candles([100.0] * 205)
    result = simulate(
        {"A": candles_a, "B": candles_b}, {"A": 0.5, "B": 0.5}, initial_capital=1000.0,
        monthly_contribution=0.0, rebalance_band_pct=0.1, fee_pct=0.001, min_order_value=50.0,
    )
    assert [t for t in result.trades if t.side == "sell"] == []


def test_run_backtest_filters_candles_to_the_requested_period(monkeypatch):
    """Regression : `fetch_historical_candles` renvoie tout son cache des
    qu'il couvre la date demandee - sans recoupe par l'appelant, le backtest
    demarrait des annees trop tot et le rendement annualise etait faux
    (meme bug que celui corrige dans run_backtest.py)."""
    # Le cache "local" commence 2 ans avant la periode demandee.
    two_years_early = START_MS - 730 * DAY_MS
    cached = make_candles([100.0] * 900, start_ms=two_years_early)
    monkeypatch.setattr(
        dca_module, "fetch_historical_candles",
        lambda exchange_id, symbol, timeframe, since_iso, **kw: cached,
    )

    bot, _, _ = run_backtest(
        weights={"A": 1.0}, since_iso="2024-01-01T00:00:00Z", initial_capital=0.0,
        monthly_contribution=100.0, rebalance_band_pct=None, fee_pct=0.0,
    )

    assert bot.equity_curve[0][0] >= "2024-01-01"
    assert bot.years < 1.0, f"periode mal recoupee : {bot.years:.1f} ans"


def test_run_backtest_returns_three_scenarios_with_identical_cashflows(monkeypatch):
    """Les 3 scenarios ne sont comparables que s'ils partagent EXACTEMENT
    les memes flux de tresorerie - sinon on compare des montants investis
    differents et la comparaison ne dit rien."""
    candles_a = make_candles([10.0] * 5 + [30.0] * 60)
    candles_b = make_candles([10.0] * 65)
    monkeypatch.setattr(
        dca_module, "fetch_historical_candles",
        lambda exchange_id, symbol, timeframe, since_iso, **kw: {"A": candles_a, "B": candles_b}[symbol],
    )

    bot, with_rebalance, drift_no_rebalance = run_backtest(
        weights={"A": 0.5, "B": 0.5}, since_iso="2024-01-01T00:00:00Z", initial_capital=500.0,
        monthly_contribution=100.0, rebalance_band_pct=None, fee_pct=0.0,
    )

    assert bot.total_invested == with_rebalance.total_invested == drift_no_rebalance.total_invested
    # A triple : la variante avec bande doit alleger, celles sans bande jamais.
    assert any(t.side == "sell" for t in with_rebalance.trades)
    assert [t for t in drift_no_rebalance.trades if t.side == "sell"] == []
    assert [t for t in bot.trades if t.side == "sell"] == []


def test_order_fee_applies_a_minimum_per_order():
    """Un courtier reel facture un minimum par ordre : c'est ce plancher,
    pas le pourcentage, qui rend ruineux le fait de multiplier les petits
    ordres. Sans le modeliser, le backtest recommanderait un reglage qui ne
    survit pas au contact d'un vrai courtier."""
    from tradingbot.dca_allocator import _order_fee

    # Petit ordre : le minimum fixe s'applique (1,25 sur 20 EUR = 6,25 %).
    assert _order_fee(20.0, fee_pct=0.001, fee_fixed=1.25) == 1.25
    # Gros ordre : le pourcentage depasse le minimum et prend le relais.
    assert _order_fee(5000.0, fee_pct=0.001, fee_fixed=1.25) == 5.0


def test_splitting_small_contributions_across_all_lines_leaves_cash_idle():
    """Avec un versement modeste face au prix d'un titre, repartir sur
    toutes les lignes n'achete rien du tout (chaque part est sous le prix
    d'une action) et l'argent dort, alors que concentrer sur la ligne la
    plus en retard investit immediatement."""
    symbols = [f"S{i}" for i in range(6)]
    candles = {s: make_candles([90.0] * 300) for s in symbols}
    weights = {s: 1 / len(symbols) for s in symbols}
    common = dict(
        initial_capital=0.0, monthly_contribution=200.0, rebalance_band_pct=None,
        fee_pct=0.0, fee_fixed=1.25, min_order_value=0.0,
    )

    spread = simulate(candles, weights, follow_drift_on_contribution=False, **common)
    concentrated = simulate(candles, weights, follow_drift_on_contribution=True, **common)

    assert spread.cash > concentrated.cash * 3, (
        f"cash dormant attendu bien plus eleve en repartissant : {spread.cash:.2f} vs {concentrated.cash:.2f}"
    )
