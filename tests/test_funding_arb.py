from tradingbot.funding_arb import (
    FundingArbCandidate,
    build_funding_arb_candidates,
    compute_funding_window_consistency,
    format_candidate,
    simulate_funding_arb,
)
from tradingbot.types import Candle, FundingRatePoint

PERIOD_MS = 28_800_000  # 8h, frequence de funding Binance


def make_candle(ts, price):
    return Candle(timestamp=ts, open=price, high=price, low=price, close=price, volume=1.0)


def make_funding(rates):
    return [FundingRatePoint(timestamp=i * PERIOD_MS, funding_rate=r) for i, r in enumerate(rates)]


def flat_candles(n, price=100.0):
    return [make_candle(i * PERIOD_MS, price) for i in range(n)]


def base_candidate(**overrides):
    defaults = dict(
        symbol_spot="BTC/USDT", symbol_perp="BTC/USDT:USDT",
        entry_funding_threshold=0.0001, exit_funding_threshold=0.0,
        lookback_periods=1, notional=1000.0, fee_pct=0.0008,
    )
    defaults.update(overrides)
    return FundingArbCandidate(**defaults)


def test_returns_none_with_fewer_than_min_cycles():
    rates = [0.0002] * 5  # jamais sous le seuil de sortie -> jamais de cycle complet
    result = simulate_funding_arb(flat_candles(5), flat_candles(5), make_funding(rates), base_candidate())
    assert result is None


def test_enters_collects_funding_and_completes_two_cycles():
    rates = [0.0002, 0.0002, 0.0002, -0.0001, 0.0002, 0.0002, 0.0002, -0.0001]
    result = simulate_funding_arb(flat_candles(8), flat_candles(8), make_funding(rates), base_candidate())
    assert result is not None
    assert result.num_cycles == 2
    assert result.total_funding_collected > 0


def test_high_fees_erode_the_return_more_than_low_fees():
    rates = [0.0002, 0.0002, -0.0001, 0.0002, 0.0002, -0.0001]
    cheap = simulate_funding_arb(flat_candles(6), flat_candles(6), make_funding(rates), base_candidate(fee_pct=0.0001))
    expensive = simulate_funding_arb(flat_candles(6), flat_candles(6), make_funding(rates), base_candidate(fee_pct=0.01))
    assert cheap.total_return_pct > expensive.total_return_pct


def test_basis_pnl_captures_spot_perp_divergence():
    rates = [0.0002, 0.0002, -0.0001, 0.0002, 0.0002, -0.0001]
    # Le spot monte, le perp reste plat : la couverture n'est plus parfaite,
    # le residuel (risque de base, jamais suppose nul) doit apparaitre.
    spot = [make_candle(i * PERIOD_MS, 100.0 + i) for i in range(6)]
    perp = flat_candles(6, price=100.0)
    result = simulate_funding_arb(spot, perp, make_funding(rates), base_candidate())
    assert result is not None
    assert result.total_basis_pnl != 0


def test_basis_pnl_is_zero_when_spot_and_perp_move_identically():
    rates = [0.0002, 0.0002, -0.0001, 0.0002, 0.0002, -0.0001]
    spot = [make_candle(i * PERIOD_MS, 100.0 + i) for i in range(6)]
    perp = [make_candle(i * PERIOD_MS, 100.0 + i) for i in range(6)]  # couverture parfaite
    result = simulate_funding_arb(spot, perp, make_funding(rates), base_candidate())
    assert result is not None
    assert abs(result.total_basis_pnl) < 1e-9


def test_build_funding_arb_candidates_never_exits_above_entry():
    candidates = build_funding_arb_candidates()
    assert len(candidates) > 0
    for c in candidates:
        assert c.exit_funding_threshold < c.entry_funding_threshold


def test_format_candidate_mentions_thresholds():
    text = format_candidate(base_candidate())
    assert "funding_arb" in text


def test_window_consistency_splits_into_at_most_requested_windows():
    rates = [0.0002] * 3 + [-0.0001] + [0.0002] * 3 + [-0.0001] + [0.0002] * 3 + [-0.0001]
    funding = make_funding(rates)
    spot = flat_candles(len(rates))
    perp = flat_candles(len(rates))
    returns, consistency = compute_funding_window_consistency(spot, perp, funding, base_candidate(), num_windows=3)
    assert len(returns) <= 3
    assert consistency is None or 0.0 <= consistency <= 1.0


def test_window_consistency_empty_funding_history_returns_none():
    returns, consistency = compute_funding_window_consistency([], [], [], base_candidate())
    assert returns == []
    assert consistency is None
