"""Trailing stop en part du gain (EF-93), definition de l'utilisateur : "achat a
2000, prix max 2100, trailing stop a 50 % -> on vendrait a 2050"."""
import pytest

from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.types import Position


def _pos(entry, peak):
    return Position(quantity=1.0, avg_entry_price=entry, entry_timestamp=0, lot_id=1, peak_price=peak)


def _rm(**kw):
    return RiskManager(RiskConfig(stop_loss_pct=None, **kw))


def test_users_example_sells_at_2050():
    config = RiskConfig(trailing_stop_pct=0.5, trailing_mode="gain")
    assert config.trailing_stop_price(2000, 2100) == pytest.approx(2050)
    rm = RiskManager(config)
    assert not rm.should_trailing_stop(_pos(2000, 2100), 2051)
    assert rm.should_trailing_stop(_pos(2000, 2100), 2050)


def test_threshold_follows_the_peak_and_never_goes_below_the_entry():
    config = RiskConfig(trailing_stop_pct=0.3, trailing_mode="gain")
    assert config.trailing_stop_price(2000, 2200) == pytest.approx(2140)   # garde 70 % de +200
    assert config.trailing_stop_price(2000, 2400) == pytest.approx(2280)   # remonte avec le plus haut
    assert config.trailing_stop_price(2000, 2001) is None                  # pas encore arme


def test_not_armed_right_after_buying():
    """Plus haut = prix d'achat : un seuil au prix d'achat ferait vendre au
    moindre recul, en perte une fois les frais payes."""
    rm = _rm(trailing_stop_pct=0.5, trailing_mode="gain")
    assert not rm.should_trailing_stop(_pos(2000, 2000), 1990)


def test_default_arming_covers_round_trip_fees():
    config = RiskConfig(trailing_stop_pct=0.5, trailing_mode="gain", fee_pct=0.001)
    assert config.trailing_stop_price(2000, 2003.9) is None        # +0,195 % < 0,2 %
    assert config.trailing_stop_price(2000, 2004.1) is not None    # +0,205 %


def test_explicit_arming_threshold():
    config = RiskConfig(trailing_stop_pct=0.5, trailing_mode="gain", trailing_arm_pct=0.02)
    assert config.trailing_stop_price(2000, 2030) is None          # +1,5 % : pas arme
    assert config.trailing_stop_price(2000, 2040) == pytest.approx(2020)


def test_distance_mode_unchanged():
    """Le sens historique (X % sous le plus haut) reste le defaut."""
    config = RiskConfig(trailing_stop_pct=0.01)
    assert config.trailing_mode == "distance"
    assert config.trailing_stop_price(2691.53, 2709.68) == pytest.approx(2709.68 * 0.99)
    assert RiskManager(config).should_trailing_stop(_pos(2000, 2100), 2079)


def test_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        RiskConfig(trailing_stop_pct=0.5, trailing_mode="pourcentage")


def test_chart_line_uses_the_same_threshold():
    from types import SimpleNamespace

    from tradingbot.reporting.stats import build_orders_table

    config = RiskConfig(stop_loss_pct=None, trailing_stop_pct=0.5, trailing_mode="gain")
    portfolio = SimpleNamespace(trade_history=[], positions=[_pos(2000, 2100)])
    rows = build_orders_table(portfolio, config)
    assert rows[0]["target_trailing_stop"] == pytest.approx(2050)


def test_dashboard_form_keeps_the_gain_mode_when_saving():
    """Le formulaire du dashboard reconstruit toute la config : sans ces champs,
    un 50 % "part du gain" redevenait "50 % sous le plus haut" a l'enregistrement."""
    from tests.test_control_server import valid_sma_payload
    from tradingbot.control_server import build_config

    payload = valid_sma_payload() | {"trailing_stop_pct": 0.5, "trailing_mode": "gain", "trailing_arm_pct": 0.02}
    risk = build_config(payload)["risk"]
    assert (risk["trailing_mode"], risk["trailing_arm_pct"]) == ("gain", 0.02)
    RiskConfig(**risk)  # la config enregistree est bien lisible par le bot

    assert build_config(valid_sma_payload())["risk"]["trailing_mode"] == "distance"
    with pytest.raises(ValueError):
        build_config(valid_sma_payload() | {"trailing_mode": "n'importe quoi"})
