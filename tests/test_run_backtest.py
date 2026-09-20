import yaml

import tradingbot.run_backtest as run_backtest_module
from tradingbot.run_backtest import main
from tradingbot.types import Candle

VALID_RISK = {
    "max_position_size_pct": 0.1, "stop_loss_pct": None, "take_profit_pct": None,
    "max_daily_loss_pct": 0.2, "max_concurrent_positions": 1, "trailing_stop_pct": None,
    "fee_pct": 0.001, "partial_take_profit_pct": None, "partial_exit_fraction": 0.5,
    "profit_lock_arm_pct": None, "profit_lock_trigger_pct": None,
}


def _write_config(tmp_path, since_iso):
    config = {
        "exchange": "binance", "symbol": "BTC/USDT", "timeframe": "1h",
        "warmup_candles": 0, "flatten_on_start": True, "capital_allocated": 1000.0,
        "strategy": {"type": "buy_and_hold"},
        "risk": VALID_RISK,
        "backtest": {"starting_capital": 1000, "since": since_iso},
    }
    config_path = tmp_path / "test_config.yml"
    config_path.write_text(yaml.dump(config))
    return config_path


def test_main_filters_candles_by_since_even_when_the_cache_returns_more(tmp_path, monkeypatch, capsys):
    """Bug reel corrige : `fetch_historical_candles` renvoie tout son cache
    local des qu'il couvre la date demandee (voir sa docstring) - possiblement
    PLUS que `since` si le cache a ete construit avec une periode plus large
    auparavant (ex: un sweep de parametres). Sans filtrage explicite ici, un
    backtest cense commencer a une date precise (ex: le debut d'une periode
    de test out-of-sample) rejouait silencieusement un historique plus long."""
    candles = [
        Candle(timestamp=i * 3_600_000, open=100, high=100, low=100, close=100, volume=1)
        for i in range(-10, 10)
    ]
    monkeypatch.setattr(run_backtest_module, "fetch_historical_candles", lambda **kwargs: candles)

    config_path = _write_config(tmp_path, "1970-01-01T00:00:00Z")  # since_ms = 0
    main(str(config_path))

    output = capsys.readouterr().out
    assert "10 bougies chargees" in output  # seulement timestamp >= 0 (10 sur les 20 fournies)


def test_main_keeps_all_candles_when_cache_matches_since_exactly(tmp_path, monkeypatch, capsys):
    candles = [
        Candle(timestamp=i * 3_600_000, open=100, high=100, low=100, close=100, volume=1)
        for i in range(5)
    ]
    monkeypatch.setattr(run_backtest_module, "fetch_historical_candles", lambda **kwargs: candles)

    config_path = _write_config(tmp_path, "1970-01-01T00:00:00Z")
    main(str(config_path))

    output = capsys.readouterr().out
    assert "5 bougies chargees" in output
