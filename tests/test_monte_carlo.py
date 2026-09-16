import numpy as np
import pytest

from tradingbot.analysis.monte_carlo import compute_daily_log_returns, simulate_probability_up


def test_compute_daily_log_returns_basic():
    closes = [100.0, 110.0, 99.0]
    returns = compute_daily_log_returns(closes)
    assert len(returns) == 2
    assert returns[0] == pytest.approx(np.log(110.0 / 100.0))
    assert returns[1] == pytest.approx(np.log(99.0 / 110.0))


def test_compute_daily_log_returns_empty_for_insufficient_data():
    assert compute_daily_log_returns([100.0]).size == 0
    assert compute_daily_log_returns([]).size == 0


def test_simulate_probability_up_all_positive_returns_gives_probability_one():
    returns = np.full(100, 0.01)
    probability = simulate_probability_up(returns, n_simulations=1000, seed=42)
    assert probability == 1.0


def test_simulate_probability_up_all_negative_returns_gives_probability_zero():
    returns = np.full(100, -0.01)
    probability = simulate_probability_up(returns, n_simulations=1000, seed=42)
    assert probability == 0.0


def test_simulate_probability_up_mixed_returns_is_between_zero_and_one():
    rng = np.random.default_rng(1)
    returns = rng.normal(0, 0.02, size=500)
    probability = simulate_probability_up(returns, n_simulations=50_000, seed=7)
    assert 0.0 <= probability <= 1.0


def test_simulate_probability_up_deterministic_with_seed():
    rng = np.random.default_rng(1)
    returns = rng.normal(0.001, 0.02, size=500)
    p1 = simulate_probability_up(returns, n_simulations=10_000, seed=123)
    p2 = simulate_probability_up(returns, n_simulations=10_000, seed=123)
    assert p1 == p2


def test_simulate_probability_up_rejects_insufficient_history():
    with pytest.raises(ValueError, match="insuffisant"):
        simulate_probability_up(np.array([0.01, -0.01]), n_simulations=1000)
