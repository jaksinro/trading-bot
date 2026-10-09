"""Strategie Volume Profile (EF-96, refaite en EF-97 d'apres le document de
l'utilisateur) et niveaux de sortie propres a chaque trade."""
import sqlite3

import pytest

from tradingbot.strategies.volume_profile import WEEK_OFFSET_MS, VolumeProfileStrategy, volume_profile
from tradingbot.types import Candle, Position, Side, Signal

H = 3_600_000
DAY0 = 1_789_948_800_000  # lundi 2026-09-21 00:00 UTC
DAY1 = DAY0 + 24 * H


def c(t, low, high, close=None, open_=None, volume=100.0):
    close = (low + high) / 2 if close is None else close
    open_ = close if open_ is None else open_
    return Candle(timestamp=t, open=open_, high=high, low=low, close=close, volume=volume)


# ---------------------------------------------------------------- profil
def test_poc_is_where_most_volume_traded():
    poc, vah, val = volume_profile([c(0, 100, 101, volume=10), c(1, 105, 106, volume=500), c(2, 109, 110, volume=10)], rows=10)
    assert 105 <= poc <= 106


def test_value_area_computed_by_hand():
    # Total 232, cible 162,4. POC = rang 4 (80). Voisins 40/40 -> haut (120) ; 20 au-dessus
    # contre 40 en dessous -> bas (160) ; 20/20 -> haut (180). Zone = 103 -> 107.
    candles = [c(i, 100 + i, 101 + i, volume=v) for i, v in enumerate([5, 10, 20, 40, 80, 40, 20, 10, 5, 2])]
    poc, vah, val = volume_profile(candles, rows=10)
    assert (val, vah) == pytest.approx((103, 107))


def test_empty_or_flat_profile():
    assert volume_profile([]) is None
    assert volume_profile([c(0, 5, 5, volume=1)]) == (5, 5, 5)


def test_weeks_start_on_monday_utc():
    assert (DAY0 - WEEK_OFFSET_MS) % (168 * H) == 0


# ---------------------------------------------------------------- outils
def yesterday(strategy, last_close):
    """Seance de la veille : cours 100-110, volume concentre vers 104-106, derniere
    cloture `last_close`. Puis la 1re bougie du jour, neutre, qui rend le profil
    de la veille disponible (il n'existe qu'une fois la seance terminee)."""
    for i in range(23):
        heavy = i % 4 == 0
        strategy.on_candle(c(DAY0 + i * H, 104 if heavy else 100, 106 if heavy else 110, volume=1000 if heavy else 50))
    strategy.on_candle(c(DAY0 + 23 * H, last_close - 0.2, last_close + 0.2, close=last_close, volume=10))
    strategy.on_candle(c(DAY1, 105, 105.5, close=105.2, volume=10))
    return strategy.profile


def feed(strategy, candles):
    return [strategy.on_candle(x) for x in candles]


def at(n):
    return DAY1 + n * H


def test_profile_and_previous_close_come_from_yesterday():
    s = VolumeProfileStrategy()
    poc, vah, val = yesterday(s, last_close=109.5)
    assert 100 <= val < poc < vah <= 110 and 104 <= poc <= 106
    assert s.previous_close == 109.5


# ---------------------------------------------------------------- 1. rebond sur le POC
def test_poc_rebound_wick_then_confirmation_buys_with_stop_under_wick_and_2r_target():
    s = VolumeProfileStrategy(setups=["poc_rebound"], stop_buffer_pct=0.0)
    poc, vah, val = yesterday(s, last_close=109.5)
    assert s.previous_close > vah
    out = feed(s, [
        c(at(1), poc - 1.0, poc + 1.2, close=poc + 1.0, open_=poc + 0.9),    # meche sous le POC, cloture dessus
        c(at(2), poc + 0.8, poc + 2.0, close=poc + 1.8, open_=poc + 1.0),    # verte qui confirme
    ])
    assert out[0] is None
    sig = out[1]
    assert sig.side == Side.BUY and sig.reason == "volume_profile_poc_rebound_wick"
    entry = poc + 1.8
    assert sig.stop_price == pytest.approx(poc - 1.0)
    assert sig.target_price == pytest.approx(entry + 2 * (entry - (poc - 1.0)))


def test_poc_rebound_requires_previous_day_closed_above_vah():
    s = VolumeProfileStrategy(setups=["poc_rebound"])
    poc, vah, val = yesterday(s, last_close=105)                            # veille finie DANS la zone
    out = feed(s, [c(at(1), poc - 1, poc + 1.2, close=poc + 1, open_=poc + 0.9),
                   c(at(2), poc + 0.8, poc + 2, close=poc + 1.8, open_=poc + 1)])
    assert out == [None, None]


def test_poc_rebound_confirmation_too_late_is_ignored():
    """'Signal trop vieux' : plus de 3 bougies apres la meche, on ne court pas apres."""
    s = VolumeProfileStrategy(setups=["poc_rebound"], max_signal_age=3)
    poc, vah, val = yesterday(s, last_close=109.5)
    reds = [c(at(i), poc + 0.6, poc + 0.9, close=poc + 0.7, open_=poc + 0.8) for i in range(2, 6)]
    out = feed(s, [c(at(1), poc - 1, poc + 1.2, close=poc + 1, open_=poc + 0.9)] + reds
               + [c(at(6), poc + 0.7, poc + 2.5, close=poc + 2.2, open_=poc + 0.8)])
    assert all(x is None for x in out)


def test_poc_rebound_bullish_engulfing_on_the_poc():
    s = VolumeProfileStrategy(setups=["poc_rebound"], stop_buffer_pct=0.0)
    poc, vah, val = yesterday(s, last_close=109.5)
    out = feed(s, [c(at(1), poc - 0.4, poc + 0.6, close=poc - 0.2, open_=poc + 0.5),     # rouge sur le POC
                   c(at(2), poc - 0.5, poc + 1.4, close=poc + 1.2, open_=poc - 0.3)])    # verte qui l'avale
    assert out[1].reason == "volume_profile_poc_rebound_engulfing"
    assert out[1].stop_price == pytest.approx(poc - 0.5)


# ---------------------------------------------------------------- 2. retour dans la zone
def test_value_area_reentry_buys_on_green_close_back_inside():
    s = VolumeProfileStrategy(setups=["value_area_reentry"], stop_buffer_pct=0.0)
    poc, vah, val = yesterday(s, last_close=105)                            # veille finie dans la zone
    out = feed(s, [c(at(1), val - 1.5, val - 0.2, close=val - 1.0, open_=val - 0.3),    # cloture sous le VAL
                   c(at(2), val - 2.0, val - 0.8, close=val - 1.2, open_=val - 1.0),    # plus bas : val - 2
                   c(at(3), val - 1.1, val + 0.6, close=val + 0.4, open_=val - 1.0)])   # verte qui rentre
    assert out[:2] == [None, None]
    assert out[2].reason == "volume_profile_value_area_reentry"
    assert out[2].stop_price == pytest.approx(val - 2.0)


def test_wick_into_the_zone_with_close_outside_is_not_an_entry():
    """'Simple meche dans la zone' : la meche entre, la cloture reste dehors."""
    s = VolumeProfileStrategy(setups=["value_area_reentry"])
    poc, vah, val = yesterday(s, last_close=105)
    out = feed(s, [c(at(1), val - 1.5, val - 0.2, close=val - 1.0, open_=val - 0.3),
                   c(at(2), val - 1.2, val + 0.8, close=val - 0.3, open_=val - 1.0)])   # verte, mais dehors
    assert out == [None, None]


def test_value_area_reentry_needs_previous_day_inside():
    s = VolumeProfileStrategy(setups=["value_area_reentry"])
    poc, vah, val = yesterday(s, last_close=109.5)                          # veille finie au-dessus
    out = feed(s, [c(at(1), val - 1.5, val - 0.2, close=val - 1.0, open_=val - 0.3),
                   c(at(2), val - 1.1, val + 0.6, close=val + 0.4, open_=val - 1.0)])
    assert out == [None, None]


# ---------------------------------------------------------------- 3. cassure
def _breakout_until_pullback(s, vah):
    return feed(s, [c(at(1), vah - 0.5, vah + 1.0, close=vah + 0.8, open_=vah - 0.3),   # sortie nette
                    c(at(2), vah + 0.7, vah + 2.0, close=vah + 1.9, open_=vah + 0.8),   # impulsion
                    c(at(3), vah + 1.0, vah + 1.8, close=vah + 1.2, open_=vah + 1.7)])  # repli


def test_breakout_enters_on_close_above_the_old_high_with_stop_under_it():
    s = VolumeProfileStrategy(setups=["breakout"], stop_buffer_pct=0.0)
    poc, vah, val = yesterday(s, last_close=105)
    assert _breakout_until_pullback(s, vah) == [None, None, None]
    sig = s.on_candle(c(at(4), vah + 1.1, vah + 2.4, close=vah + 2.3, open_=vah + 1.2))
    assert sig.reason == "volume_profile_breakout"
    assert sig.stop_price == pytest.approx(vah + 2.0)                     # l'ancien plus haut
    assert sig.target_price == pytest.approx(vah + 2.3 + 2 * 0.3)


def test_breakout_cancelled_when_pullback_closes_deep_in_the_zone():
    s = VolumeProfileStrategy(setups=["breakout"], pullback_max_depth=0.25)
    poc, vah, val = yesterday(s, last_close=105)
    _breakout_until_pullback(s, vah)
    deep = vah - 0.5 * (vah - val)
    assert s.on_candle(c(at(4), deep - 0.2, vah + 1.0, close=deep, open_=vah + 1.0)) is None
    assert s.on_candle(c(at(5), deep, vah + 2.5, close=vah + 2.3, open_=deep)) is None    # setup annule


def test_min_risk_widens_a_too_tight_stop():
    s = VolumeProfileStrategy(setups=["breakout"], stop_buffer_pct=0.0, min_risk_pct=0.01)
    poc, vah, val = yesterday(s, last_close=105)
    _breakout_until_pullback(s, vah)
    sig = s.on_candle(c(at(4), vah + 1.1, vah + 2.4, close=vah + 2.3, open_=vah + 1.2))
    assert sig.stop_price == pytest.approx((vah + 2.3) * 0.99)


# ---------------------------------------------------------------- etat et divers
def test_no_new_entry_while_in_position():
    s = VolumeProfileStrategy(setups=["value_area_reentry"])
    poc, vah, val = yesterday(s, last_close=105)
    s.sync_position(100.0)
    out = feed(s, [c(at(1), val - 1.5, val - 0.2, close=val - 1.0, open_=val - 0.3),
                   c(at(2), val - 1.1, val + 0.6, close=val + 0.4, open_=val - 1.0)])
    assert out == [None, None]


def test_chart_levels_show_yesterdays_profile():
    s = VolumeProfileStrategy()
    assert s.chart_levels() == []
    yesterday(s, last_close=105)
    assert [lv["label"].split()[0] for lv in s.chart_levels()] == ["POC", "VAH", "VAL"]


@pytest.mark.parametrize("kwargs", [{"setups": ["short"]}, {"setups": []}, {"rows": 2}, {"value_area_pct": 1.5},
                                    {"reward_risk": 0}, {"max_signal_age": 0}])
def test_invalid_parameters_are_refused(kwargs):
    with pytest.raises(ValueError):
        VolumeProfileStrategy(**kwargs)


def test_strategy_is_registered_for_bots():
    from tradingbot.run_backtest import build_strategy

    s = build_strategy({"strategy": {"type": "volume_profile", "setups": ["breakout"], "session_hours": 24}})
    assert isinstance(s, VolumeProfileStrategy) and s.setups == ("breakout",)


# ---------------------------------------------------------------- niveaux propres au trade (moteur)
def _engine():
    from tradingbot.engine import Engine
    from tradingbot.execution.backtest_executor import BacktestExecutor
    from tradingbot.portfolio import Portfolio
    from tradingbot.risk.risk_manager import RiskConfig, RiskManager

    class OneShot:
        def __init__(self):
            self.next = None

        def on_candle(self, candle):
            sig, self.next = self.next, None
            return sig

    strategy = OneShot()
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.001)
    engine = Engine(strategy, RiskManager(RiskConfig(stop_loss_pct=None)), BacktestExecutor(portfolio), portfolio)
    return engine, strategy, portfolio


@pytest.mark.parametrize("price,reason", [(97.9, "stop_trade"), (104.1, "objectif_trade")])
def test_engine_sells_at_the_trade_stop_or_target(price, reason):
    engine, strategy, portfolio = _engine()
    strategy.next = Signal(side=Side.BUY, reason="test", stop_price=98.0, target_price=104.0)
    engine.process_candle(c(DAY0, 99, 101, close=100))
    lot = portfolio.positions[0]
    assert (lot.stop_price, lot.target_price) == (98.0, 104.0)
    engine.process_price_update(c(DAY0 + H, 99, 101, close=100.5))
    assert portfolio.positions                                           # entre les deux : on garde
    engine.process_price_update(c(DAY0 + 2 * H, price, price, close=price))
    assert not portfolio.positions and portfolio.trade_history[-1]["reason"] == reason


def test_trade_levels_survive_a_restart(tmp_path, monkeypatch):
    from tradingbot.reporting import logger as logger_module
    from tradingbot.reporting.logger import TradeLogger

    monkeypatch.setattr(logger_module, "DATA_DIR", tmp_path)
    log = TradeLogger("VP")
    log.save_open_positions([Position(quantity=1, avg_entry_price=100, entry_timestamp=0, lot_id=1,
                                      stop_price=98.0, target_price=104.0)])
    log.close()
    restored = TradeLogger("VP").load_open_positions()[0]
    assert (restored.stop_price, restored.target_price) == (98.0, 104.0)


def test_existing_bot_database_gets_the_new_columns(tmp_path, monkeypatch):
    """Les bots deja en service ont une table open_positions sans ces colonnes."""
    from tradingbot.reporting import logger as logger_module
    from tradingbot.reporting.logger import TradeLogger

    monkeypatch.setattr(logger_module, "DATA_DIR", tmp_path)
    old = sqlite3.connect(tmp_path / "OLD.db")
    old.execute("""CREATE TABLE open_positions (lot_id INTEGER PRIMARY KEY, quantity REAL NOT NULL,
                   avg_entry_price REAL NOT NULL, entry_timestamp INTEGER NOT NULL,
                   entry_fee REAL NOT NULL DEFAULT 0, peak_price REAL NOT NULL DEFAULT 0)""")
    old.execute("INSERT INTO open_positions VALUES (1, 0.5, 2000, 0, 1, 2010)")
    old.commit()
    old.close()
    restored = TradeLogger("OLD").load_open_positions()[0]
    assert restored.peak_price == 2010 and restored.stop_price is None


def test_chart_shows_the_trade_levels():
    from types import SimpleNamespace

    from tradingbot.reporting.stats import build_orders_table
    from tradingbot.risk.risk_manager import RiskConfig

    lot = Position(quantity=1, avg_entry_price=100, entry_timestamp=0, lot_id=1, stop_price=98.0, target_price=104.0)
    rows = build_orders_table(SimpleNamespace(trade_history=[], positions=[lot]), RiskConfig(stop_loss_pct=0.02))
    assert (rows[0]["target_stop_loss"], rows[0]["target_take_profit"]) == (98.0, 104.0)


# ---------------------------------------------------------------- EF-104 : schemas de vente
def test_short_setups_are_off_by_default():
    s = VolumeProfileStrategy(setups=["value_area_reentry"])
    poc, vah, val = yesterday(s, last_close=105)
    out = feed(s, [c(at(1), vah + 0.2, vah + 1.5, close=vah + 1.0, open_=vah + 0.3),
                   c(at(2), vah - 0.6, vah + 1.1, close=vah - 0.4, open_=vah + 1.0)])
    assert out == [None, None]


def test_short_poc_rejection_from_below_sells_with_stop_above_wick():
    s = VolumeProfileStrategy(setups=["poc_rebound"], stop_buffer_pct=0.0, allow_short=True)
    poc, vah, val = yesterday(s, last_close=100.5)
    assert s.previous_close < val                                           # veille finie SOUS la zone
    out = feed(s, [
        c(at(1), poc - 1.2, poc + 1.0, close=poc - 1.0, open_=poc - 0.9),    # meche au-dessus du POC, cloture dessous
        c(at(2), poc - 2.0, poc - 0.8, close=poc - 1.8, open_=poc - 1.0),    # rouge qui confirme
    ])
    assert out[0] is None
    sig = out[1]
    assert (sig.side, sig.position_side, sig.reason) == (Side.SELL, "short", "volume_profile_short_poc_rebound_wick")
    entry = poc - 1.8
    assert sig.stop_price == pytest.approx(poc + 1.0)
    assert sig.target_price == pytest.approx(entry - 2 * (poc + 1.0 - entry))


def test_short_value_area_reentry_from_above():
    s = VolumeProfileStrategy(setups=["value_area_reentry"], stop_buffer_pct=0.0, allow_short=True)
    poc, vah, val = yesterday(s, last_close=105)
    out = feed(s, [c(at(1), vah + 0.2, vah + 1.5, close=vah + 1.0, open_=vah + 0.3),    # cloture au-dessus du VAH
                   c(at(2), vah + 0.8, vah + 2.0, close=vah + 1.2, open_=vah + 1.0),    # plus haut : vah + 2
                   c(at(3), vah - 0.6, vah + 1.1, close=vah - 0.4, open_=vah + 1.0)])   # rouge qui rentre
    assert out[:2] == [None, None]
    assert out[2].reason == "volume_profile_short_value_area_reentry" and out[2].side == Side.SELL
    assert out[2].stop_price == pytest.approx(vah + 2.0) and out[2].target_price < out[2].stop_price


def test_short_breakdown_below_val_then_close_under_the_old_low():
    s = VolumeProfileStrategy(setups=["breakout"], stop_buffer_pct=0.0, allow_short=True)
    poc, vah, val = yesterday(s, last_close=105)
    out = feed(s, [c(at(1), val - 1.0, val - 0.2, close=val - 0.8, open_=val - 0.3),    # cloture sous le VAL
                   c(at(2), val - 1.6, val - 0.7, close=val - 1.4, open_=val - 0.8),    # impulsion : plus bas val - 1.6
                   c(at(3), val - 1.3, val - 0.6, close=val - 0.8, open_=val - 1.3),    # repli sans nouveau plus bas
                   c(at(4), val - 1.9, val - 0.8, close=val - 1.7, open_=val - 0.9)])   # cloture sous l'ancien plus bas
    assert out[:3] == [None, None, None]
    assert out[3].reason == "volume_profile_short_breakdown" and out[3].position_side == "short"
    assert out[3].stop_price == pytest.approx(val - 1.6)


def test_no_short_while_a_position_is_open():
    s = VolumeProfileStrategy(setups=["value_area_reentry"], allow_short=True)
    poc, vah, val = yesterday(s, last_close=105)
    s.sync_position(100.0)
    out = feed(s, [c(at(1), vah + 0.2, vah + 1.5, close=vah + 1.0, open_=vah + 0.3),
                   c(at(2), vah - 0.6, vah + 1.1, close=vah - 0.4, open_=vah + 1.0)])
    assert out == [None, None]


# ---------------------------------------------------------------- EF-105 : stop trop loin
def far_stop_reentry(**kw):
    """Retour dans la zone dont le plus bas dehors est ~3 sous le VAL : stop tres loin."""
    s = VolumeProfileStrategy(setups=["value_area_reentry"], stop_buffer_pct=0.0, **kw)
    poc, vah, val = yesterday(s, last_close=105)
    out = feed(s, [c(at(1), val - 3.0, val - 0.2, close=val - 1.0, open_=val - 0.3),
                   c(at(2), val - 1.1, val + 0.6, close=val + 0.4, open_=val - 1.0)])
    return out[1], val + 0.4, val - 3.0


def test_pattern_stop_is_kept_by_default():
    sig, entry, low = far_stop_reentry()
    assert sig.stop_price == pytest.approx(low)
    assert sig.target_price == pytest.approx(entry + 2 * (entry - low))


def test_far_stop_is_capped_and_target_follows():
    sig, entry, low = far_stop_reentry(max_risk_pct=0.01)
    assert (entry - low) / entry > 0.01
    assert sig.stop_price == pytest.approx(entry * 0.99)
    assert sig.target_price == pytest.approx(entry * 1.02)


def test_far_stop_can_skip_the_trade_and_close_stop_is_untouched():
    sig, _, _ = far_stop_reentry(max_risk_pct=0.01, wide_stop="skip")
    assert sig is None
    sig, entry, low = far_stop_reentry(max_risk_pct=0.2, wide_stop="skip")
    assert sig.stop_price == pytest.approx(low)


def test_fixed_stop_and_target_in_percent():
    sig, entry, _ = far_stop_reentry(fixed_stop_pct=0.005, fixed_target_pct=0.01)
    assert sig.stop_price == pytest.approx(entry * 0.995)
    assert sig.target_price == pytest.approx(entry * 1.01)
    sig, entry, _ = far_stop_reentry(fixed_stop_pct=0.005)
    assert sig.target_price == pytest.approx(entry * 1.01)               # objectif vide = 2 fois le stop


def test_fixed_levels_are_mirrored_for_short_sells():
    s = VolumeProfileStrategy(setups=["value_area_reentry"], allow_short=True, fixed_stop_pct=0.005,
                              fixed_target_pct=0.01)
    poc, vah, val = yesterday(s, last_close=105)
    out = feed(s, [c(at(1), vah + 0.2, vah + 1.5, close=vah + 1.0, open_=vah + 0.3),
                   c(at(2), vah - 0.6, vah + 1.1, close=vah - 0.4, open_=vah + 1.0)])
    entry = vah - 0.4
    assert out[1].stop_price == pytest.approx(entry * 1.005)
    assert out[1].target_price == pytest.approx(entry * 0.99)


def test_unknown_wide_stop_action_is_refused():
    with pytest.raises(ValueError):
        VolumeProfileStrategy(wide_stop="ignore")
