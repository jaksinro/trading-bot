"""Strategie vote de momentum (EF-98)."""
import pytest

from tradingbot.strategies.momentum_vote import MomentumVoteStrategy
from tradingbot.types import Candle, Side

D = 86_400_000


def day(i, close):
    return Candle(timestamp=i * D, open=close, high=close, low=close, close=close, volume=1.0)


def run(strategy, closes):
    return [strategy.on_candle(day(i, x)) for i, x in enumerate(closes)]


def test_silent_until_the_longest_horizon_is_available():
    s = MomentumVoteStrategy(lookbacks=(2, 5))
    out = run(s, [100, 101, 102, 103, 104])
    assert out == [None] * 5
    assert s.on_candle(day(5, 105)).side == Side.BUY


def test_holds_when_most_horizons_are_up():
    s = MomentumVoteStrategy(lookbacks=(1, 3, 5))
    # 5 jours avant : 100 ; 3 jours avant : 110 ; la veille : 108 ; aujourd'hui 109
    out = run(s, [100, 104, 110, 109, 108, 109])
    assert s.last_vote == pytest.approx(2 / 3)       # en hausse sur 5 j et 1 j, en baisse sur 3 j
    assert out[-1].side == Side.BUY


def test_goes_to_cash_when_most_horizons_are_down():
    s = MomentumVoteStrategy(lookbacks=(1, 3, 5))
    out = run(s, [100, 104, 110, 109, 108, 99])
    assert s.last_vote == 0.0
    assert out[-1].side == Side.SELL


def test_a_tie_is_not_a_majority():
    s = MomentumVoteStrategy(lookbacks=(1, 2))
    out = run(s, [100, 102, 101])                    # 101 > 100 (2 j) mais 101 < 102 (1 j) : 1 vote sur 2
    assert s.last_vote == 0.5 and out[-1].side == Side.SELL


def test_matches_the_research_rule():
    """Meme decision que la regle mesuree par scripts/research_eth.py (vote majoritaire)."""
    import numpy as np

    closes = [100 * (1 + 0.02 * np.sin(i / 5)) + i * 0.3 for i in range(200)]
    s = MomentumVoteStrategy()
    out = run(s, closes)
    for i in range(91, 200):
        votes = np.mean([closes[i] > closes[i - n] for n in (7, 14, 30, 60, 90)])
        assert (out[i].side == Side.BUY) == (votes > 0.5)


@pytest.mark.parametrize("kwargs", [{"lookbacks": ()}, {"lookbacks": (0, 5)}, {"threshold": 1.0}])
def test_invalid_parameters(kwargs):
    with pytest.raises(ValueError):
        MomentumVoteStrategy(**kwargs)


def test_registered_and_chart_levels():
    from tradingbot.run_backtest import build_strategy

    s = build_strategy({"strategy": {"type": "momentum_vote", "lookbacks": [2, 3]}})
    assert isinstance(s, MomentumVoteStrategy) and s.lookbacks == (2, 3)
    assert s.chart_levels() == []
    run(s, [10, 11, 12, 13])
    assert [lv["price"] for lv in s.chart_levels()] == [11, 10]
