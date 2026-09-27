import pytest

from tradingbot import control_server
from tradingbot.control_server import build_config

FAKE_MARKETS = {"ETH/USDT": {}, "BTC/USDT": {}, "DOGE/USDT": {}, "ADA/USDT": {}}


@pytest.fixture(autouse=True)
def fake_binance_markets(monkeypatch):
    """Evite un vrai appel reseau a chaque test - build_config verifie que
    le symbole existe reellement sur Binance (voir get_binance_markets)."""
    monkeypatch.setattr(control_server, "get_binance_markets", lambda: FAKE_MARKETS)


@pytest.fixture(autouse=True)
def fresh_login_throttle():
    """Le compteur de mots de passe faux (EF-94) est global au serveur :
    chaque test repart d'un compteur vide."""
    control_server._login_throttle.reset()
    yield
    control_server._login_throttle.reset()


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


def test_builds_valid_ibkr_paper_config():
    """EF-65 : compte 'ibkr_paper' cree un bot actions (paper trading
    Interactive Brokers) - symbole en format ticker (pas BASE/QUOTE),
    timeframe force a 1 jour, exchange = 'ibkr_paper' dans la config."""
    payload = valid_sma_payload(
        account_type="ibkr_paper", symbol="rno.pa", timeframe="1h",  # timeframe soumis doit etre ignore/force
    )
    config = build_config(payload)
    assert config["exchange"] == "ibkr_paper"
    assert config["symbol"] == "RNO.PA"
    assert config["timeframe"] == "1d"  # force, malgre "1h" soumis


def test_ibkr_paper_rejects_empty_symbol():
    payload = valid_sma_payload(account_type="ibkr_paper", symbol="")
    with pytest.raises(ValueError):
        build_config(payload)


def test_ibkr_paper_does_not_require_base_quote_symbol_format():
    """Un ticker action ('RNO.PA') n'a pas de '/' - ne doit pas etre rejete
    comme un symbole crypto invalide, et ne doit pas etre valide contre les
    marches Binance (qui n'a aucun sens ici)."""
    payload = valid_sma_payload(account_type="ibkr_paper", symbol="RNO.PA")
    config = build_config(payload)
    assert config["symbol"] == "RNO.PA"


def test_ibkr_paper_rejects_a_strategy_that_forces_an_incompatible_timeframe():
    """mean_dip force 5m, slope_dip force 1m, dip_bounce_hourly/minute
    forcent 1h/1m - tous incompatibles avec le paper trading IBKR qui ne
    gere que des bougies journalieres (run_paper.py::ib_*)."""
    payload = valid_sma_payload(
        account_type="ibkr_paper", strategy_type="mean_dip", window="12", num_std="2.0", stop_loss_pct="0.02",
    )
    with pytest.raises(ValueError):
        build_config(payload)


def test_builds_valid_dip_bounce_daily_config():
    """EF-65 : nouveau preset dip_bounce pour les actions IBKR - contrairement
    a dip_bounce_hourly/minute, trend_ma_period est REGLABLE (la recherche
    empirique STC §3.47 montre qu'il varie fortement d'une action a
    l'autre) et il n'y a pas de verrou de gain."""
    payload = valid_sma_payload(
        account_type="ibkr_paper", strategy_type="dip_bounce_daily",
        trend_ma_period="10", dip_threshold_pct="0.05", stop_loss_pct="0.08",
    )
    config = build_config(payload)
    assert config["strategy"] == {
        "type": "dip_bounce", "trend_ma_period": 10, "dip_threshold_pct": 0.05, "force_trade_after_hours": None,
    }
    assert config["timeframe"] == "1d"
    assert config["risk"]["profit_lock_arm_pct"] is None
    assert config["risk"]["profit_lock_trigger_pct"] is None
    assert config["risk"]["stop_loss_pct"] == 0.08


def test_dip_bounce_daily_stop_loss_is_optional():
    payload = valid_sma_payload(
        account_type="ibkr_paper", strategy_type="dip_bounce_daily",
        trend_ma_period="10", dip_threshold_pct="0.05", stop_loss_pct="",
    )
    config = build_config(payload)
    assert config["risk"]["stop_loss_pct"] is None


def test_dip_bounce_daily_rejects_trend_ma_period_below_2():
    payload = valid_sma_payload(
        account_type="ibkr_paper", strategy_type="dip_bounce_daily",
        trend_ma_period="1", dip_threshold_pct="0.05", stop_loss_pct="",
    )
    with pytest.raises(ValueError):
        build_config(payload)


def test_builds_valid_mean_dip_config():
    """2026-09-16, idee proposee par l'utilisateur : creux detecte comme un
    ecart a la moyenne (pas une proximite a un plus bas glissant comme
    dip_bounce), granularite fine, stop-loss/trailing uniquement (pas de
    verrou de gain)."""
    payload = valid_sma_payload(
        strategy_type="mean_dip", timeframe="1h",  # timeframe soumis doit etre ignore/force
        window="12", num_std="2.0",
    )
    config = build_config(payload)
    assert config["strategy"] == {"type": "mean_dip", "window": 12, "num_std": 2.0}
    assert config["timeframe"] == "5m"  # force, malgre "1h" soumis
    assert config["risk"]["profit_lock_arm_pct"] is None
    assert config["risk"]["profit_lock_trigger_pct"] is None


def test_builds_valid_slope_dip_config():
    """2026-09-16, idee proposee par l'utilisateur : achete sur une chute
    brutale entre N bougies consecutives (pente), garde l'ordre, vend
    uniquement via le trailing stop (stop-loss optionnel en filet)."""
    payload = valid_sma_payload(
        strategy_type="slope_dip", timeframe="1h",  # timeframe soumis doit etre ignore/force
        slope_threshold_pct="0.005", candles_window="2", stop_loss_pct="",
    )
    config = build_config(payload)
    assert config["strategy"] == {
        "type": "slope_dip", "slope_threshold_pct": 0.005, "candles_window": 2, "one_buy_per_slope": False,
    }
    assert config["timeframe"] == "1m"  # force, malgre "1h" soumis
    assert config["risk"]["stop_loss_pct"] is None  # optionnel, vide reste desactive


def test_slope_dip_one_buy_per_slope_can_be_enabled():
    """2026-09-16, constat reel de l'utilisateur ("sa foire pendant les
    longues pentes") : limite a 1 achat par episode de pente continue."""
    payload = valid_sma_payload(
        strategy_type="slope_dip", slope_threshold_pct="0.005", candles_window="2",
        stop_loss_pct="", one_buy_per_slope=True,
    )
    config = build_config(payload)
    assert config["strategy"]["one_buy_per_slope"] is True


def test_slope_dip_one_buy_per_slope_disabled_by_default():
    payload = valid_sma_payload(strategy_type="slope_dip", slope_threshold_pct="0.005", candles_window="2", stop_loss_pct="")
    config = build_config(payload)
    assert config["strategy"]["one_buy_per_slope"] is False


def test_slope_dip_accepts_a_wider_candles_window():
    """2026-09-16, suite a l'observation du graphique reel d'une journee :
    mesurer la pente sur plus de 2 bougies (ex: 5) pour lisser le bruit."""
    payload = valid_sma_payload(strategy_type="slope_dip", slope_threshold_pct="0.005", candles_window="5", stop_loss_pct="")
    config = build_config(payload)
    assert config["strategy"]["candles_window"] == 5


def test_slope_dip_rejects_candles_window_below_2():
    payload = valid_sma_payload(strategy_type="slope_dip", slope_threshold_pct="0.005", candles_window="1", stop_loss_pct="")
    with pytest.raises(ValueError):
        build_config(payload)


def test_slope_dip_stop_loss_can_be_explicitly_enabled():
    payload = valid_sma_payload(strategy_type="slope_dip", slope_threshold_pct="0.005", candles_window="2", stop_loss_pct="0.1")
    config = build_config(payload)
    assert config["risk"]["stop_loss_pct"] == 0.1


def test_slope_dip_rejects_non_positive_slope_threshold():
    payload = valid_sma_payload(strategy_type="slope_dip", slope_threshold_pct="0", candles_window="2", stop_loss_pct="")
    with pytest.raises(ValueError):
        build_config(payload)


def test_mean_dip_stop_loss_is_required_not_optional():
    """Contrairement a dip_bounce : sans verrou de gain ni stop-loss, une
    position ne se fermerait jamais - le stop-loss reste donc obligatoire
    pour ce type, comme sma_cross/scalp_dip."""
    payload = valid_sma_payload(strategy_type="mean_dip", window="12", num_std="2.0", stop_loss_pct="")
    with pytest.raises(ValueError, match="(?i)stop-loss"):
        build_config(payload)


def test_mean_dip_rejects_window_below_two():
    payload = valid_sma_payload(strategy_type="mean_dip", window="1", num_std="2.0")
    with pytest.raises(ValueError):
        build_config(payload)


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


# --- EF-80 : les routes GET passent par le VRAI handler HTTP -----------------
#
# Le graphique des cryptos a casse sans qu'aucun test ne bronche : un import
# local ajoute dans `do_GET` pour une autre route avait fait de `parse_qs` une
# variable locale de toute la fonction, et la route /api/price-history mourait
# en UnboundLocalError - connexion coupee sans reponse. `fetch_price_history`
# fonctionnait parfaitement en direct : seul le passage par le handler
# revelait le defaut. D'ou un serveur reel, sur un port libre, et de vraies
# requetes HTTP.

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer


class _FakeExchange:
    def fetch_ohlcv(self, symbol, timeframe, limit):
        return [[1_700_000_000_000 + i * 60_000, 1, 1, 1, 100.0 + i, 1] for i in range(limit)]


@pytest.fixture
def live_server(monkeypatch):
    monkeypatch.setattr(control_server, "_public_exchange", _FakeExchange())
    control_server._price_history_cache.clear()
    errors = []

    server = ThreadingHTTPServer(("localhost", 0), control_server.Handler)
    # Une exception dans un thread de requete est normalement avalee par
    # socketserver : on la capture pour que le test ECHOUE dessus.
    server.handle_error = lambda request, addr: errors.append(True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    yield f"http://localhost:{port}", errors
    server.shutdown()


def _get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=10) as response:
        return response.status, json.loads(response.read())


def test_price_history_route_answers_through_the_real_handler(live_server):
    base, errors = live_server

    status, body = _get(base, "/api/price-history?symbol=ETH%2FUSDT&range=1j")

    assert errors == [], "le handler a leve une exception au lieu de repondre"
    assert status == 200
    assert body["points"], "des points de cours attendus"
    assert body["points"][0][1] == 100.0


def test_unknown_price_range_is_a_clean_400_not_a_dropped_connection(live_server):
    base, errors = live_server

    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(base, "/api/price-history?symbol=ETH%2FUSDT&range=1siecle")

    assert exc.value.code == 400
    assert errors == []


def test_every_get_route_either_answers_or_404s_but_never_drops(live_server):
    """Balaye les routes GET connues : chacune doit produire UNE reponse HTTP.
    Une connexion fermee sans reponse est le symptome exact du defaut EF-80."""
    base, errors = live_server
    routes = [
        "/api/list-configs", "/api/dca-bots", "/api/list-proposals",
        "/api/backtest-strategies", "/api/dca-price-history?name=inexistant&days=30",
        "/api/price-history?symbol=ETH%2FUSDT&range=1mois",
    ]
    for route in routes:
        try:
            _get(base, route)
        except urllib.error.HTTPError:
            pass  # un 4xx/5xx propre est acceptable ; l'absence de reponse ne l'est pas
    assert errors == [], "au moins une route a leve une exception non geree"


# --- EF-82 : acces depuis le reseau local, protege par mot de passe --------
#
# Un dashboard qui sait passer des ordres et arreter des bots ne doit jamais
# etre expose sur un reseau par simple oubli : sans mot de passe, un client
# non-local recoit un refus. Le client "distant" est simule en faisant mentir
# le handler sur l'adresse du client - tout le reste (serveur, requetes HTTP,
# en-tetes) est reel.

import base64


class _RemoteHandler(control_server.Handler):
    def _client_is_loopback(self):
        return False


@pytest.fixture
def remote_server(monkeypatch):
    monkeypatch.setattr(control_server, "_public_exchange", _FakeExchange())
    server = ThreadingHTTPServer(("localhost", 0), _RemoteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://localhost:{server.server_address[1]}"
    server.shutdown()


def _get_status(base: str, path: str, headers: dict | None = None):
    request = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def _basic(user: str, password: str) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_local_client_needs_no_password(live_server, monkeypatch):
    monkeypatch.delenv(control_server.PASSWORD_ENV, raising=False)
    base, _ = live_server
    status, _, _ = _get_status(base, "/api/list-configs")
    assert status == 200


def test_remote_client_is_refused_when_no_password_is_configured(remote_server, monkeypatch):
    """LE garde-fou : rien n'est servi sur le reseau tant que le mot de
    passe n'existe pas - ni l'API, ni la page elle-meme."""
    monkeypatch.delenv(control_server.PASSWORD_ENV, raising=False)
    for path in ("/api/list-configs", "/dashboard.html"):
        status, _, body = _get_status(remote_server, path)
        assert status == 403, path
        assert control_server.PASSWORD_ENV.encode() in body, "le refus doit dire quoi faire"


def test_remote_client_without_credentials_gets_a_browser_prompt(remote_server, monkeypatch):
    monkeypatch.setenv(control_server.PASSWORD_ENV, "secret")
    status, headers, _ = _get_status(remote_server, "/api/list-configs")
    assert status == 401
    assert headers.get("WWW-Authenticate", "").startswith("Basic"), "le navigateur doit pouvoir demander le mot de passe"


def test_remote_client_with_wrong_password_is_refused(remote_server, monkeypatch):
    monkeypatch.setenv(control_server.PASSWORD_ENV, "secret")
    status, _, _ = _get_status(remote_server, "/api/list-configs", _basic("trader", "faux"))
    assert status == 401


def test_remote_client_with_right_password_is_served(remote_server, monkeypatch):
    monkeypatch.setenv(control_server.PASSWORD_ENV, "secret")
    status, _, body = _get_status(remote_server, "/api/list-configs", _basic("trader", "secret"))
    assert status == 200
    assert b"configs" in body


def test_remote_post_is_protected_too(remote_server, monkeypatch):
    """Les ordres partent en POST : c'est la partie qu'il faut proteger avant tout."""
    monkeypatch.setenv(control_server.PASSWORD_ENV, "secret")
    request = urllib.request.Request(
        remote_server + "/api/manual-deposit", data=b'{"amount": 1}',
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=10)
    assert exc.value.code == 401


def test_the_user_name_is_configurable(remote_server, monkeypatch):
    monkeypatch.setenv(control_server.PASSWORD_ENV, "secret")
    monkeypatch.setenv(control_server.USER_ENV, "youenn")
    assert _get_status(remote_server, "/api/list-configs", _basic("trader", "secret"))[0] == 401
    assert _get_status(remote_server, "/api/list-configs", _basic("youenn", "secret"))[0] == 200


# --- EF-94 : limitation des tentatives de mot de passe ----------------------


def test_too_many_wrong_passwords_block_the_address_even_with_the_right_one(remote_server, monkeypatch):
    monkeypatch.setenv(control_server.PASSWORD_ENV, "secret")
    for _ in range(control_server.LOGIN_MAX_FAILURES - 1):
        assert _get_status(remote_server, "/api/list-configs", _basic("trader", "faux"))[0] == 401
    assert _get_status(remote_server, "/api/list-configs", _basic("trader", "faux"))[0] == 401
    status, headers, body = _get_status(remote_server, "/api/list-configs", _basic("trader", "secret"))
    assert status == 429, "sinon le blocage ne ralentit pas un essai systematique"
    assert int(headers["Retry-After"]) > 0
    assert "min".encode() in body


def test_requests_without_credentials_are_not_counted_as_failures(remote_server, monkeypatch):
    """Le navigateur envoie toujours une premiere requete sans identifiants
    avant d'afficher la fenetre de mot de passe : ce n'est pas un echec."""
    monkeypatch.setenv(control_server.PASSWORD_ENV, "secret")
    for _ in range(control_server.LOGIN_MAX_FAILURES + 2):
        assert _get_status(remote_server, "/api/list-configs")[0] == 401
    assert _get_status(remote_server, "/api/list-configs", _basic("trader", "secret"))[0] == 200


def test_malformed_authorization_header_counts_as_a_failure(remote_server, monkeypatch):
    monkeypatch.setenv(control_server.PASSWORD_ENV, "secret")
    for _ in range(control_server.LOGIN_MAX_FAILURES):
        assert _get_status(remote_server, "/api/list-configs", {"Authorization": "Bearer x"})[0] == 401
    assert _get_status(remote_server, "/api/list-configs", _basic("trader", "secret"))[0] == 429


def test_blocked_address_is_refused_on_post_too(remote_server, monkeypatch):
    monkeypatch.setenv(control_server.PASSWORD_ENV, "secret")
    for _ in range(control_server.LOGIN_MAX_FAILURES):
        _get_status(remote_server, "/api/list-configs", _basic("trader", "faux"))
    request = urllib.request.Request(
        remote_server + "/api/manual-deposit", data=b'{"amount": 1}',
        headers={"Content-Type": "application/json", **_basic("trader", "secret")}, method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=10)
    assert exc.value.code == 429


def test_local_client_is_never_blocked(live_server, monkeypatch):
    """Un blocage ne doit jamais empecher de reprendre la main depuis la
    machine elle-meme (ni le script de demarrage automatique)."""
    monkeypatch.setenv(control_server.PASSWORD_ENV, "secret")
    for _ in range(control_server.LOGIN_MAX_FAILURES + 1):
        control_server._login_throttle.record_failure("127.0.0.1")
    base, _ = live_server
    assert _get_status(base, "/api/list-configs")[0] == 200


class _FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_throttle_lifts_the_block_after_the_lockout():
    clock = _FakeClock()
    throttle = control_server.LoginThrottle(max_failures=3, window_s=60, lockout_s=300, clock=clock)
    for _ in range(3):
        throttle.record_failure("10.0.0.5")
    assert throttle.retry_after("10.0.0.5") == 300
    assert throttle.retry_after("10.0.0.6") == 0, "le blocage est propre a une adresse"
    clock.now += 299.5
    assert throttle.retry_after("10.0.0.5") == 1
    clock.now += 1
    assert throttle.retry_after("10.0.0.5") == 0


def test_throttle_forgets_failures_older_than_the_window():
    clock = _FakeClock()
    throttle = control_server.LoginThrottle(max_failures=3, window_s=60, lockout_s=300, clock=clock)
    throttle.record_failure("10.0.0.5")
    throttle.record_failure("10.0.0.5")
    clock.now += 61
    throttle.record_failure("10.0.0.5")
    assert throttle.retry_after("10.0.0.5") == 0, "des fautes de frappe espacees ne doivent pas bloquer"


def test_throttle_success_resets_the_failure_count():
    throttle = control_server.LoginThrottle(max_failures=3, clock=_FakeClock())
    throttle.record_failure("10.0.0.5")
    throttle.record_failure("10.0.0.5")
    throttle.record_success("10.0.0.5")
    throttle.record_failure("10.0.0.5")
    assert throttle.retry_after("10.0.0.5") == 0


def test_throttle_memory_is_bounded():
    throttle = control_server.LoginThrottle(max_failures=2, max_tracked=5, clock=_FakeClock())
    for i in range(50):
        throttle.record_failure(f"10.0.0.{i}")
        throttle.record_failure(f"10.0.1.{i}")
        throttle.record_failure(f"10.0.1.{i}")
    assert len(throttle._failures) <= 5
    assert len(throttle._blocked_until) <= 5


# --- EF-85 : le journal d'un bot survit a sa relance ------------------------
#
# Le journal etait ouvert en "w" : la trace d'un plantage etait EFFACEE au
# lancement suivant. Popen est remplace par un faux processus qui ecrit dans
# le fichier recu, comme le ferait un vrai bot.


class _FakeProcess:
    def __init__(self, exited: bool):
        self._exited = exited

    def poll(self):
        return 1 if self._exited else None


def _fake_popen(output: str, exited: bool):
    def popen(args, cwd, stdout, stderr, creationflags):
        stdout.write(output)
        stdout.flush()
        return _FakeProcess(exited)
    return popen


def test_a_previous_crash_trace_survives_a_relaunch(tmp_path, monkeypatch):
    monkeypatch.setattr(control_server, "LOG_DIR", tmp_path)
    monkeypatch.setattr(control_server, "CRASH_CHECK_DELAY_SECONDS", 0)
    (tmp_path / "ETH.log").write_text("ccxt.base.errors.NetworkError: coupure de 02h09\n", encoding="utf-8")

    monkeypatch.setattr(control_server.subprocess, "Popen", _fake_popen("Mode paper demarre\n", exited=False))
    ok, _ = control_server.launch_process(tmp_path / "ETH.yml", "ETH")

    text = (tmp_path / "ETH.log").read_text(encoding="utf-8")
    assert ok
    assert "NetworkError: coupure de 02h09" in text, "la trace du plantage precedent doit rester lisible"
    assert "===== lancement" in text
    assert text.index("coupure de 02h09") < text.index("Mode paper demarre")


def test_an_immediate_crash_reports_this_launch_not_an_old_one(tmp_path, monkeypatch):
    """Le message renvoye au formulaire doit venir de CE lancement : avec un
    journal en ajout, la derniere ligne du fichier ne suffit plus a le garantir
    si le nouveau lancement n'ecrit rien."""
    monkeypatch.setattr(control_server, "LOG_DIR", tmp_path)
    monkeypatch.setattr(control_server, "CRASH_CHECK_DELAY_SECONDS", 0)
    (tmp_path / "ETH.log").write_text("ancienne erreur sans rapport\n", encoding="utf-8")

    monkeypatch.setattr(control_server.subprocess, "Popen", _fake_popen("", exited=True))
    ok, message = control_server.launch_process(tmp_path / "ETH.yml", "ETH")

    assert not ok
    assert "ancienne erreur" not in message


def test_a_large_log_is_rotated_instead_of_growing_forever(tmp_path, monkeypatch):
    monkeypatch.setattr(control_server, "LOG_DIR", tmp_path)
    monkeypatch.setattr(control_server, "CRASH_CHECK_DELAY_SECONDS", 0)
    monkeypatch.setattr(control_server, "LOG_MAX_BYTES", 100)
    (tmp_path / "ETH.log").write_text("x" * 500, encoding="utf-8")

    monkeypatch.setattr(control_server.subprocess, "Popen", _fake_popen("demarre\n", exited=False))
    control_server.launch_process(tmp_path / "ETH.yml", "ETH")

    assert (tmp_path / "ETH.log.1").read_text(encoding="utf-8") == "x" * 500
    assert "x" * 500 not in (tmp_path / "ETH.log").read_text(encoding="utf-8")


# --- EF-86 : HTTPS optionnel pour l'acces reseau ----------------------------
#
# Sans HTTPS, le mot de passe HTTP Basic circule en clair sur le reseau. Le
# serveur chiffre desormais si un certificat est fourni. Certificat
# auto-signe genere a la volee (`cryptography`, deja tiree par ccxt) ; vrai
# serveur, vraie poignee de main TLS, vrai client urllib.

import datetime
import socket
import ssl


def _self_signed_cert(tmp_path):
    x509 = pytest.importorskip("cryptography.x509")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    import ipaddress

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    return cert_path, key_path


@pytest.fixture
def tls_remote_server(tmp_path, monkeypatch):
    monkeypatch.setattr(control_server, "_public_exchange", _FakeExchange())
    cert_path, key_path = _self_signed_cert(tmp_path)
    monkeypatch.setenv(control_server.TLS_CERT_ENV, str(cert_path))
    monkeypatch.setenv(control_server.TLS_KEY_ENV, str(key_path))
    context = control_server.tls_context_from_env()
    server = control_server.TLSThreadingHTTPServer(("127.0.0.1", 0), _RemoteHandler, context)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client_context = ssl.create_default_context(cafile=str(cert_path))
    yield server.server_address[1], client_context
    server.shutdown()


def _https_status(port, context, path, headers=None):
    request = urllib.request.Request(f"https://localhost:{port}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10, context=context) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_no_tls_variables_means_plain_http(monkeypatch):
    monkeypatch.delenv(control_server.TLS_CERT_ENV, raising=False)
    monkeypatch.delenv(control_server.TLS_KEY_ENV, raising=False)
    assert control_server.tls_context_from_env() is None


@pytest.mark.parametrize("present", ["cert", "key"])
def test_half_configured_tls_refuses_to_start_instead_of_falling_back(monkeypatch, present):
    """Un seul des deux renseigne = une erreur, jamais un HTTP en clair
    silencieux que l'utilisateur croirait chiffre."""
    monkeypatch.delenv(control_server.TLS_CERT_ENV, raising=False)
    monkeypatch.delenv(control_server.TLS_KEY_ENV, raising=False)
    env = control_server.TLS_CERT_ENV if present == "cert" else control_server.TLS_KEY_ENV
    monkeypatch.setenv(env, "certs/whatever.pem")
    with pytest.raises(ValueError, match="moitie"):
        control_server.tls_context_from_env()


def test_missing_certificate_file_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv(control_server.TLS_CERT_ENV, str(tmp_path / "absent.pem"))
    monkeypatch.setenv(control_server.TLS_KEY_ENV, str(tmp_path / "absent.key"))
    with pytest.raises(ValueError, match="generate_dashboard_cert"):
        control_server.tls_context_from_env()


def test_https_server_still_requires_the_password(tls_remote_server, monkeypatch):
    monkeypatch.setenv(control_server.PASSWORD_ENV, "s3cret")
    port, context = tls_remote_server
    assert _https_status(port, context, "/api/list-configs") == 401
    assert _https_status(port, context, "/api/list-configs", _basic("trader", "s3cret")) == 200


def test_a_plain_http_client_does_not_break_the_https_server(tls_remote_server, monkeypatch):
    """Un navigateur qui tape http:// par erreur echoue proprement, et le
    serveur continue de servir les clients HTTPS ensuite."""
    monkeypatch.setenv(control_server.PASSWORD_ENV, "s3cret")
    port, context = tls_remote_server
    with pytest.raises((urllib.error.URLError, ConnectionError, OSError)):
        urllib.request.urlopen(f"http://localhost:{port}/api/list-configs", timeout=5)
    assert _https_status(port, context, "/api/list-configs", _basic("trader", "s3cret")) == 200


def test_a_silent_client_does_not_block_other_clients(tls_remote_server, monkeypatch):
    """La poignee de main se fait dans le thread de la requete : un client
    qui se connecte sans rien dire n'immobilise pas le serveur."""
    monkeypatch.setenv(control_server.PASSWORD_ENV, "s3cret")
    port, context = tls_remote_server
    silent = socket.create_connection(("127.0.0.1", port))
    try:
        assert _https_status(port, context, "/api/list-configs", _basic("trader", "s3cret")) == 200
    finally:
        silent.close()
