import pytest

from tradingbot import control_server
from tradingbot.control_server import build_config

FAKE_MARKETS = {"ETH/USDT": {}, "BTC/USDT": {}, "DOGE/USDT": {}, "ADA/USDT": {}}


@pytest.fixture(autouse=True)
def fake_binance_markets(monkeypatch):
    """Evite un vrai appel reseau a chaque test - build_config verifie que
    le symbole existe reellement sur Binance (voir get_binance_markets)."""
    monkeypatch.setattr(control_server, "get_binance_markets", lambda: FAKE_MARKETS)


def valid_sma_payload(**overrides):
    payload = {
        "name": "eth_custom_v1",
        "symbol": "eth/usdt",
        "timeframe": "1h",
        "strategy_type": "sma_cross",
        "short_window": "10",
        "long_window": "30",
        "capital_allocated": "300",
        "max_position_size_pct": "0.1",
        "stop_loss_pct": "0.02",
        "take_profit_pct": "",
        "max_daily_loss_pct": "0.05",
    }
    payload.update(overrides)
    return payload


def test_builds_valid_sma_cross_config():
    config = build_config(valid_sma_payload())
    assert config["name"] == "eth_custom_v1"
    assert config["symbol"] == "ETH/USDT"
    assert config["strategy"] == {"type": "sma_cross", "short_window": 10, "long_window": 30}
    assert config["capital_allocated"] == 300.0
    assert config["risk"]["take_profit_pct"] is None


def test_builds_valid_scalp_dip_config():
    payload = valid_sma_payload(strategy_type="scalp_dip", lookback="20", dip_threshold_pct="0.003")
    config = build_config(payload)
    assert config["strategy"] == {"type": "scalp_dip", "lookback": 20, "dip_threshold_pct": 0.003}


def test_builds_valid_dip_bounce_hourly_config():
    payload = valid_sma_payload(
        strategy_type="dip_bounce_hourly", timeframe="4h",  # timeframe soumis doit etre ignore/force
        stop_loss_pct="",  # optionnel pour dip_bounce (voir tests dedies plus bas) - vide reste desactive par defaut
        dip_threshold_pct="0.005", profit_lock_arm_pct="0.005", profit_lock_trigger_pct="0.0043",
    )
    config = build_config(payload)
    assert config["strategy"] == {
        "type": "dip_bounce", "trend_ma_period": 24, "dip_threshold_pct": 0.005, "force_trade_after_hours": None,
    }
    assert config["timeframe"] == "1h"  # force, malgre "4h" soumis
    assert config["risk"]["stop_loss_pct"] is None
    assert config["risk"]["profit_lock_arm_pct"] == 0.005
    assert config["risk"]["profit_lock_trigger_pct"] == 0.0043


def test_dip_bounce_stop_loss_is_optional_and_disabled_when_empty():
    """Reintegration demandee par l'utilisateur (2026-09-15) : le stop-loss
    de 'Rebond de creux' redevient reglable, mais reste desactive par defaut
    (vide) - decision historique inchangee tant qu'il n'est pas explicitement
    active, voir strategies/dip_bounce.py et STC.md section 3.35."""
    payload = valid_sma_payload(
        strategy_type="dip_bounce_hourly", stop_loss_pct="",
        dip_threshold_pct="0.005", profit_lock_arm_pct="0.005", profit_lock_trigger_pct="0.0043",
    )
    config = build_config(payload)
    assert config["risk"]["stop_loss_pct"] is None


def test_dip_bounce_stop_loss_can_be_explicitly_enabled():
    payload = valid_sma_payload(
        strategy_type="dip_bounce_hourly", stop_loss_pct="0.15",
        dip_threshold_pct="0.005", profit_lock_arm_pct="0.005", profit_lock_trigger_pct="0.0043",
    )
    config = build_config(payload)
    assert config["risk"]["stop_loss_pct"] == 0.15


def test_builds_valid_dip_bounce_minute_config():
    payload = valid_sma_payload(
        strategy_type="dip_bounce_minute", stop_loss_pct="",
        dip_threshold_pct="0.005", profit_lock_arm_pct="0.005", profit_lock_trigger_pct="0.0043",
    )
    config = build_config(payload)
    assert config["strategy"] == {
        "type": "dip_bounce", "trend_ma_period": 60, "dip_threshold_pct": 0.005, "force_trade_after_hours": None,
    }
    assert config["timeframe"] == "1m"
    assert config["risk"]["stop_loss_pct"] is None


def test_dip_bounce_accepts_force_trade_after_hours():
    payload = valid_sma_payload(
        strategy_type="dip_bounce_hourly",
        dip_threshold_pct="0.005", profit_lock_arm_pct="0.005", profit_lock_trigger_pct="0.0043",
        force_trade_after_hours="24",
    )
    config = build_config(payload)
    assert config["strategy"]["force_trade_after_hours"] == 24.0


def test_dip_bounce_zero_force_trade_after_hours_means_disabled():
    payload = valid_sma_payload(
        strategy_type="dip_bounce_hourly",
        dip_threshold_pct="0.005", profit_lock_arm_pct="0.005", profit_lock_trigger_pct="0.0043",
        force_trade_after_hours="0",
    )
    config = build_config(payload)
    assert config["strategy"]["force_trade_after_hours"] is None


def test_dip_bounce_rejects_trigger_above_or_equal_to_arm():
    payload = valid_sma_payload(
        strategy_type="dip_bounce_hourly",
        dip_threshold_pct="0.005", profit_lock_arm_pct="0.005", profit_lock_trigger_pct="0.005",
    )
    with pytest.raises(ValueError, match="strictement inferieur"):
        build_config(payload)


def test_builds_valid_buy_and_hold_config():
    payload = valid_sma_payload(strategy_type="buy_and_hold", warmup_candles="50")
    config = build_config(payload)
    assert config["strategy"] == {"type": "buy_and_hold"}
    assert config["warmup_candles"] == 0  # force, ignore le "50" soumis
    assert config["risk"]["stop_loss_pct"] is None


def test_take_profit_pct_parsed_when_provided():
    config = build_config(valid_sma_payload(take_profit_pct="0.01"))
    assert config["risk"]["take_profit_pct"] == 0.01


def test_rejects_invalid_name():
    with pytest.raises(ValueError, match="nom invalide"):
        build_config(valid_sma_payload(name="bad name!"))


def test_rejects_symbol_without_slash():
    with pytest.raises(ValueError, match="symbole invalide"):
        build_config(valid_sma_payload(symbol="ETHUSDT"))


def test_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="strategie inconnue"):
        build_config(valid_sma_payload(strategy_type="does_not_exist"))


def test_rejects_short_window_not_below_long_window():
    with pytest.raises(ValueError, match="moyenne courte"):
        build_config(valid_sma_payload(short_window="30", long_window="30"))


def test_rejects_short_window_greater_than_long_window():
    with pytest.raises(ValueError, match="moyenne courte"):
        build_config(valid_sma_payload(short_window="40", long_window="10"))


def test_rejects_non_positive_capital():
    with pytest.raises(ValueError, match="plafond de mise"):
        build_config(valid_sma_payload(capital_allocated="0"))


def test_rejects_negative_capital():
    with pytest.raises(ValueError, match="plafond de mise"):
        build_config(valid_sma_payload(capital_allocated="-100"))


def test_rejects_invalid_timeframe():
    with pytest.raises(ValueError, match="timeframe"):
        build_config(valid_sma_payload(timeframe="3h"))


def test_exit_check_timeframe_absent_by_default():
    config = build_config(valid_sma_payload())
    assert config["exit_check_timeframe"] is None


def test_accepts_a_finer_exit_check_timeframe():
    config = build_config(valid_sma_payload(timeframe="1h", exit_check_timeframe="5m"))
    assert config["exit_check_timeframe"] == "5m"


def test_rejects_invalid_exit_check_timeframe():
    with pytest.raises(ValueError, match="surveillance des sorties"):
        build_config(valid_sma_payload(timeframe="1h", exit_check_timeframe="3h"))


def test_rejects_exit_check_timeframe_not_finer_than_bot_timeframe():
    with pytest.raises(ValueError, match="plus fin"):
        build_config(valid_sma_payload(timeframe="1h", exit_check_timeframe="1h"))
    with pytest.raises(ValueError, match="plus fin"):
        build_config(valid_sma_payload(timeframe="5m", exit_check_timeframe="1h"))


def test_rejects_max_position_size_pct_over_100_percent():
    with pytest.raises(ValueError, match="taille de position"):
        build_config(valid_sma_payload(max_position_size_pct="1.5"))


def test_rejects_zero_stop_loss():
    with pytest.raises(ValueError, match="stop-loss"):
        build_config(valid_sma_payload(stop_loss_pct="0"))


def test_rejects_missing_required_field():
    payload = valid_sma_payload()
    del payload["stop_loss_pct"]
    with pytest.raises(ValueError, match="requis"):
        build_config(payload)


def test_rejects_non_numeric_field():
    with pytest.raises(ValueError, match="nombre"):
        build_config(valid_sma_payload(capital_allocated="pas un nombre"))


def test_rejects_lookback_too_small_for_scalp_dip():
    with pytest.raises(ValueError, match="lookback"):
        build_config(valid_sma_payload(strategy_type="scalp_dip", lookback="1", dip_threshold_pct="0.003"))


def test_warmup_candles_defaults_to_strategy_minimum_when_omitted():
    config = build_config(valid_sma_payload(short_window="10", long_window="30"))
    assert config["warmup_candles"] == 30


def test_rejects_warmup_candles_below_strategy_minimum():
    with pytest.raises(ValueError, match="rechauffement"):
        build_config(valid_sma_payload(short_window="10", long_window="30", warmup_candles="5"))


def test_rejects_symbol_not_listed_on_binance_with_suggestion():
    with pytest.raises(ValueError, match=r"introuvable.*DOGE/USDT"):
        build_config(valid_sma_payload(symbol="DODGE/USDT"))


def test_rejects_symbol_not_listed_without_suggestion_if_no_close_match():
    with pytest.raises(ValueError, match="introuvable"):
        build_config(valid_sma_payload(symbol="ZZZZZ/USDT"))


def test_accepts_symbol_when_markets_unavailable(monkeypatch):
    """Si l'API Binance est injoignable, on ne bloque pas la creation pour
    autant : seul le format du symbole est verifie."""
    monkeypatch.setattr(control_server, "get_binance_markets", lambda: None)
    config = build_config(valid_sma_payload(symbol="ETH/USDT"))
    assert config["symbol"] == "ETH/USDT"


def test_max_concurrent_positions_defaults_to_one():
    config = build_config(valid_sma_payload())
    assert config["risk"]["max_concurrent_positions"] == 1


def test_accepts_multiple_concurrent_positions():
    config = build_config(valid_sma_payload(max_concurrent_positions="3", max_position_size_pct="0.1"))
    assert config["risk"]["max_concurrent_positions"] == 3


def test_rejects_zero_concurrent_positions():
    with pytest.raises(ValueError, match="simultanees"):
        build_config(valid_sma_payload(max_concurrent_positions="0"))


def test_rejects_concurrent_positions_exceeding_100_percent_exposure():
    with pytest.raises(ValueError, match="depasserait"):
        build_config(valid_sma_payload(max_concurrent_positions="5", max_position_size_pct="0.3"))


def test_fee_pct_defaults_to_realistic_value():
    config = build_config(valid_sma_payload())
    assert config["risk"]["fee_pct"] == 0.001


def test_accepts_custom_fee_pct():
    config = build_config(valid_sma_payload(fee_pct="0.002"))
    assert config["risk"]["fee_pct"] == 0.002


def test_trailing_stop_pct_defaults_to_none():
    config = build_config(valid_sma_payload())
    assert config["risk"]["trailing_stop_pct"] is None


def test_accepts_trailing_stop_pct():
    config = build_config(valid_sma_payload(trailing_stop_pct="0.05"))
    assert config["risk"]["trailing_stop_pct"] == 0.05


def test_rejects_trailing_stop_pct_out_of_range():
    with pytest.raises(ValueError, match="trailing stop"):
        build_config(valid_sma_payload(trailing_stop_pct="1.5"))


def test_trend_filter_absent_by_default():
    config = build_config(valid_sma_payload())
    assert "trend_filter" not in config


def test_accepts_trend_filter_enabled_with_custom_ema_period():
    config = build_config(valid_sma_payload(trend_filter_enabled=True, trend_filter_ema_period="100"))
    assert config["trend_filter"] == {"enabled": True, "ema_period": 100}


def test_rejects_trend_filter_ema_period_below_two():
    with pytest.raises(ValueError, match="EMA"):
        build_config(valid_sma_payload(trend_filter_enabled=True, trend_filter_ema_period="1"))


def test_rejects_trend_filter_enabled_without_ema_period():
    with pytest.raises(ValueError, match="requis"):
        build_config(valid_sma_payload(trend_filter_enabled=True))


def test_atr_sizing_absent_by_default():
    config = build_config(valid_sma_payload())
    assert "atr_sizing" not in config


def test_accepts_atr_sizing_enabled_with_custom_values():
    config = build_config(valid_sma_payload(
        atr_sizing_enabled=True, atr_period="10", atr_baseline_period="50", atr_min_multiplier="0.3",
    ))
    assert config["atr_sizing"] == {
        "enabled": True, "atr_period": 10, "baseline_period": 50, "min_size_multiplier": 0.3,
    }


def test_rejects_atr_sizing_enabled_without_required_fields():
    with pytest.raises(ValueError, match="requis"):
        build_config(valid_sma_payload(atr_sizing_enabled=True))


def test_rejects_atr_min_multiplier_out_of_range():
    with pytest.raises(ValueError, match="minimum"):
        build_config(valid_sma_payload(
            atr_sizing_enabled=True, atr_period="10", atr_baseline_period="50", atr_min_multiplier="1.5",
        ))


def test_price_level_sizing_absent_by_default():
    config = build_config(valid_sma_payload())
    assert "price_level_sizing" not in config


def test_accepts_price_level_sizing_enabled_with_custom_values():
    config = build_config(valid_sma_payload(
        price_level_sizing_enabled=True, price_level_min_multiplier="0.5", price_level_max_multiplier="1.5",
    ))
    assert config["price_level_sizing"] == {
        "enabled": True, "min_size_multiplier": 0.5, "max_size_multiplier": 1.5,
    }


def test_rejects_price_level_sizing_enabled_without_required_fields():
    with pytest.raises(ValueError, match="requis"):
        build_config(valid_sma_payload(price_level_sizing_enabled=True))


def test_rejects_price_level_max_multiplier_below_min():
    with pytest.raises(ValueError, match="maximum"):
        build_config(valid_sma_payload(
            price_level_sizing_enabled=True, price_level_min_multiplier="1.5", price_level_max_multiplier="0.5",
        ))


def test_partial_take_profit_absent_by_default():
    config = build_config(valid_sma_payload())
    assert config["risk"]["partial_take_profit_pct"] is None
    assert config["risk"]["partial_exit_fraction"] == 0.5


def test_accepts_partial_take_profit_with_custom_fraction():
    config = build_config(valid_sma_payload(partial_take_profit_pct="0.01", partial_exit_fraction="0.3"))
    assert config["risk"]["partial_take_profit_pct"] == 0.01
    assert config["risk"]["partial_exit_fraction"] == 0.3


def test_rejects_partial_take_profit_greater_or_equal_to_full_take_profit():
    with pytest.raises(ValueError, match="inferieur au take-profit"):
        build_config(valid_sma_payload(take_profit_pct="0.01", partial_take_profit_pct="0.02", partial_exit_fraction="0.5"))


def test_rejects_partial_take_profit_without_fraction():
    with pytest.raises(ValueError, match="requis"):
        build_config(valid_sma_payload(partial_take_profit_pct="0.01"))
