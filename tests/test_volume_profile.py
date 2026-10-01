"""Strategie Fixed Range Volume Profile (EF-96)."""
import pytest

from tradingbot.strategies.volume_profile import WEEK_OFFSET_MS, VolumeProfileStrategy, volume_profile
from tradingbot.types import Candle, Side

H = 3_600_000
DAY0 = 1_789_948_800_000  # lundi 2026-09-21 00:00 UTC


def c(t, low, high, close=None, volume=100.0):
    close = (low + high) / 2 if close is None else close
    return Candle(timestamp=t, open=close, high=high, low=low, close=close, volume=volume)


# ---------------------------------------------------------------- profil
def test_poc_is_where_most_volume_traded():
    candles = [c(0, 100, 101, volume=10), c(1, 105, 106, volume=500), c(2, 109, 110, volume=10)]
    poc, vah, val = volume_profile(candles, rows=10)
    assert 105 <= poc <= 106


def test_value_area_holds_about_70_percent_and_contains_the_poc():
    candles = [c(i, 100 + i, 101 + i, volume=v) for i, v in enumerate([5, 10, 20, 40, 80, 40, 20, 10, 5, 2])]
    poc, vah, val = volume_profile(candles, rows=10, value_area_pct=0.70)
    assert val <= poc <= vah
    inside = sum(x.volume for x in candles if x.low >= val - 1e-9 and x.high <= vah + 1e-9)
    assert inside / sum(x.volume for x in candles) >= 0.70
    # A la main : total 232, cible 162,4. POC = rang 4 (80). Voisins 40/40 -> haut (120) ;
    # 20 au-dessus contre 40 en dessous -> bas (160) ; 20/20 -> haut (180 >= 162,4).
    # Zone = rangs 3 a 6, soit 103 -> 107 (77,6 % du volume).
    assert (val, vah) == pytest.approx((103, 107))


def test_volume_is_spread_over_the_candle_range():
    # Une seule bougie 100-110 : 10 par rang. Egalite partout : le POC est le rang le plus bas,
    # la zone s'etend vers le haut (egalite -> haut) jusqu'a 70 : rangs 0 a 6.
    poc, vah, val = volume_profile([c(0, 100, 110, volume=100)], rows=10)
    assert poc == pytest.approx(100.5)
    assert (val, vah) == pytest.approx((100, 107))


def test_empty_or_flat_profile():
    assert volume_profile([]) is None
    assert volume_profile([c(0, 5, 5, volume=1)]) == (5, 5, 5)


# ---------------------------------------------------------------- periodes
def test_weekly_range_starts_on_monday_utc():
    assert (DAY0 - WEEK_OFFSET_MS) % (168 * H) == 0


def _week_profile_then(strategy, closes_next_week, low=100, high=110):
    """Une semaine de reference (cours entre low et high, volume concentre au
    milieu), puis les clotures donnees en debut de semaine suivante."""
    signals = []
    for i in range(168):
        mid = (low + high) / 2
        vol = 1000 if abs(i % 10 - 5) <= 1 else 10
        strategy.on_candle(c(DAY0 + i * H, mid - 1 if vol == 1000 else low, mid + 1 if vol == 1000 else high, volume=vol))
    # Le profil d'une semaine n'existe qu'une fois terminee : a la 1re bougie de la
    # suivante (lundi 00:00, neutre, au milieu de la plage). Les clotures suivent.
    strategy.on_candle(c(DAY0 + 168 * H, (low + high) / 2 - 0.1, (low + high) / 2 + 0.1))
    for j, close in enumerate(closes_next_week):
        signals.append(strategy.on_candle(c(DAY0 + (169 + j) * H, close - 0.1, close + 0.1, close=close)))
    return signals


def test_profile_of_the_previous_week_is_the_reference():
    s = VolumeProfileStrategy(range_hours=168)
    _week_profile_then(s, [105])
    poc, vah, val = s.profile
    assert 100 <= val < poc < vah <= 110


# ---------------------------------------------------------------- retour dans la zone (80 %)
def test_reversion_buys_after_reentry_confirmed_and_sells_at_vah():
    s = VolumeProfileStrategy(mode="reversion", confirm_candles=2, target="vah", stop_buffer_pct=0.01)
    _week_profile_then(s, [])
    poc, vah, val = s.profile
    sig = [s.on_candle(c(DAY0 + (169 + j) * H, x - 0.1, x + 0.1, close=x))
           for j, x in enumerate([val - 2, val + 0.5, val + 0.6, vah + 0.5])]
    assert sig[0] is None and sig[1] is None           # sous le VAL, puis 1re cloture dedans
    assert sig[2].side == Side.BUY                     # 2e cloture dedans : confirme
    assert sig[3].side == Side.SELL and sig[3].reason == "volume_profile_target"


def test_reversion_needs_price_to_have_been_below_val_first():
    s = VolumeProfileStrategy(mode="reversion", confirm_candles=1)
    signals = _week_profile_then(s, [105, 105, 104])
    assert all(x is None for x in signals)


def test_reversion_invalidation_below_val():
    s = VolumeProfileStrategy(mode="reversion", confirm_candles=1, stop_buffer_pct=0.01)
    _week_profile_then(s, [])
    poc, vah, val = s.profile
    t = DAY0 + 169 * H
    s.on_candle(c(t, 0, 0, close=val - 1))
    assert s.on_candle(c(t + H, 0, 0, close=val + 0.1)).side == Side.BUY
    assert s.on_candle(c(t + 2 * H, 0, 0, close=val * 0.995)) is None          # dans la marge de 1 %
    sell = s.on_candle(c(t + 3 * H, 0, 0, close=val * 0.98))
    assert sell.side == Side.SELL and sell.reason == "volume_profile_invalidation"


def test_exit_levels_are_frozen_at_entry():
    s = VolumeProfileStrategy(mode="reversion", confirm_candles=1, target="poc")
    _week_profile_then(s, [])
    poc, vah, val = s.profile
    t = DAY0 + 169 * H
    s.on_candle(c(t, 0, 0, close=val - 1))
    s.on_candle(c(t + H, 0, 0, close=val + 0.1))
    s.profile = (poc + 50, vah + 50, val + 50)        # nouveau profil en cours de position
    assert s.on_candle(c(t + 2 * H, 0, 0, close=poc + 0.01)).reason == "volume_profile_target"


# ---------------------------------------------------------------- cassure
def test_breakout_buys_after_confirmed_closes_above_vah_and_exits_back_inside():
    s = VolumeProfileStrategy(mode="breakout", confirm_candles=2, stop_buffer_pct=0.0)
    _week_profile_then(s, [])
    poc, vah, val = s.profile
    t = DAY0 + 169 * H
    assert s.on_candle(c(t, 0, 0, close=vah + 1)) is None
    assert s.on_candle(c(t + H, 0, 0, close=vah + 2)).side == Side.BUY
    assert s.on_candle(c(t + 2 * H, 0, 0, close=vah + 5)) is None              # pas d'objectif fixe
    assert s.on_candle(c(t + 3 * H, 0, 0, close=vah - 0.5)).side == Side.SELL


# ---------------------------------------------------------------- divers
def test_chart_levels():
    s = VolumeProfileStrategy()
    assert s.chart_levels() == []
    _week_profile_then(s, [])
    labels = [lv["label"] for lv in s.chart_levels()]
    assert labels[0].startswith("POC") and labels[1].startswith("VAH") and labels[2].startswith("VAL")


@pytest.mark.parametrize("kwargs", [{"mode": "short"}, {"anchor": "x"}, {"target": "x"}, {"rows": 2},
                                    {"value_area_pct": 1.5}, {"confirm_candles": 0}])
def test_invalid_parameters_are_refused(kwargs):
    with pytest.raises(ValueError):
        VolumeProfileStrategy(**kwargs)


def test_rolling_anchor_judges_the_current_candle_against_previous_hours():
    s = VolumeProfileStrategy(anchor="rolling", range_hours=24)
    for i in range(30):
        s.on_candle(c(DAY0 + i * H, 100, 110, volume=100))
    assert s.profile is not None
    s.on_candle(c(DAY0 + 30 * H, 500, 510, volume=10_000))   # bougie extreme : absente de son propre profil
    assert s.profile[1] <= 110


def test_strategy_is_registered_for_bots():
    from tradingbot.run_backtest import build_strategy

    s = build_strategy({"strategy": {"type": "volume_profile", "mode": "breakout", "range_hours": 24}})
    assert isinstance(s, VolumeProfileStrategy) and s.mode == "breakout"


def test_breakout_exit_ratchets_up_with_each_new_range():
    """Sans cela, la seule sortie de la cassure etait sous le prix d'achat :
    tout trade clos etait perdant (0 % de gagnants au premier banc)."""
    s = VolumeProfileStrategy(mode="breakout", range_hours=24, confirm_candles=1, stop_buffer_pct=0.0)
    for i in range(24):                                   # jour 1 : 100-110
        s.on_candle(c(DAY0 + i * H, 100, 110, volume=100))
    s.on_candle(c(DAY0 + 24 * H, 104, 106))               # jour 2 : profil du jour 1 dispo
    vah1 = s.profile[1]
    assert s.on_candle(c(DAY0 + 25 * H, vah1 + 1, vah1 + 3, close=vah1 + 2)).side == Side.BUY
    for i in range(26, 48):                               # le reste du jour 2 : 130-140
        assert s.on_candle(c(DAY0 + i * H, 130, 140, volume=100)) is None
    s.on_candle(c(DAY0 + 48 * H, 134, 136))               # jour 3 : nouveau profil, seuil remonte
    assert s._exit_stop > vah1 + 2                        # au-dessus du prix d'achat
    sell = s.on_candle(c(DAY0 + 49 * H, 120, 121, close=120))
    assert sell.side == Side.SELL and 120 > vah1 + 2      # sortie en gain


def test_sync_forgets_a_position_the_bot_does_not_have():
    """Achat refuse (cash) ou vente par le stop-loss du moteur : la strategie
    ne doit pas rester bloquee 'en position' sans jamais racheter."""
    s = VolumeProfileStrategy(mode="reversion", confirm_candles=1)
    _week_profile_then(s, [])
    poc, vah, val = s.profile
    t = DAY0 + 169 * H
    s.on_candle(c(t, 0, 0, close=val - 1))
    assert s.on_candle(c(t + H, 0, 0, close=val + 0.1)).side == Side.BUY
    s.sync_position(None)                                  # le moteur n'a pas de position
    s.on_candle(c(t + 2 * H, 0, 0, close=val - 1))
    assert s.on_candle(c(t + 3 * H, 0, 0, close=val + 0.1)).side == Side.BUY   # peut racheter


def test_sync_adopts_a_position_restored_after_restart():
    """Reprise de session avec une position ouverte : sans cela, ni objectif ni
    invalidation ne pourraient jamais la vendre."""
    s = VolumeProfileStrategy(mode="reversion", target="poc", stop_buffer_pct=0.01)
    _week_profile_then(s, [])
    poc, vah, val = s.profile
    s.sync_position(val + 0.5)
    sell = s.on_candle(c(DAY0 + 170 * H, 0, 0, close=val * 0.98))
    assert sell.side == Side.SELL and sell.reason == "volume_profile_invalidation"


def test_engine_tells_the_strategy_its_real_position():
    from tradingbot.engine import Engine
    from tradingbot.execution.backtest_executor import BacktestExecutor
    from tradingbot.portfolio import Portfolio
    from tradingbot.risk.risk_manager import RiskConfig, RiskManager

    seen = []

    class Spy:
        def sync_position(self, entry):
            seen.append(entry)

        def on_candle(self, candle):
            return None

    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.001)
    engine = Engine(Spy(), RiskManager(RiskConfig(stop_loss_pct=None)), BacktestExecutor(portfolio), portfolio)
    engine.process_candle(c(DAY0, 99, 101))
    assert seen == [None]
