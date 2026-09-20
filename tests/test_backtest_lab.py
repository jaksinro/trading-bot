import pytest

import tradingbot.backtest_lab as backtest_lab_module
from tradingbot.backtest_lab import (
    PRESETS,
    build_atr_sizer_kwargs,
    build_chart_payload,
    build_namespace_from_payload,
    build_price_level_sizer_kwargs,
    build_risk_kwargs_and_summary,
    build_strategy_instance,
    build_trend_filter_kwargs,
    merge_dual_timeframe,
    presets_metadata,
    run_backtest_job,
    run_one_period,
    split_periods,
)
from tradingbot.portfolio import Portfolio
from tradingbot.strategies.mean_dip import MeanDipStrategy
from tradingbot.strategies.slope_dip import SlopeDipStrategy
from tradingbot.types import Candle


def make_candles(n: int, start_ts: int = 0, step_ms: int = 3_600_000, start_price: float = 100.0) -> list[Candle]:
    candles = []
    price = start_price
    for i in range(n):
        candles.append(Candle(timestamp=start_ts + i * step_ms, open=price, high=price, low=price, close=price, volume=1.0))
        price *= 1.001
    return candles


def test_split_periods_covers_the_whole_range_without_gaps():
    windows = split_periods(0, 1000, 4)
    assert windows[0][0] == 0
    assert windows[-1][1] == 1000
    for i in range(len(windows) - 1):
        assert windows[i][1] == windows[i + 1][0]


def test_presets_metadata_lists_every_preset_with_expected_shape():
    metadata = presets_metadata()
    assert len(metadata) == len(PRESETS)
    dip_bounce_hourly = next(m for m in metadata if m["key"] == "dip_bounce_hourly")
    assert dip_bounce_hourly["timeframe"] == "1h"
    assert dip_bounce_hourly["supports_stop_loss"] is True  # stop-loss optionnel (2026-09-15), reste desactive par defaut
    assert dip_bounce_hourly["default_stop_loss_pct"] is None
    assert any(p["name"] == "dip_threshold_pct" for p in dip_bounce_hourly["param_specs"])
    assert any(p["name"] == "profit_lock_arm_pct" for p in dip_bounce_hourly["risk_param_specs"])


def test_presets_metadata_includes_mean_dip_with_required_stop_loss():
    """2026-09-16 : contrairement a dip_bounce, mean_dip n'a pas de verrou de
    gain - le stop-loss est donc actif par defaut (pas optionnel/desactive)."""
    metadata = presets_metadata()
    mean_dip = next(m for m in metadata if m["key"] == "mean_dip")
    assert mean_dip["timeframe"] == "5m"
    assert mean_dip["supports_stop_loss"] is True
    assert mean_dip["default_stop_loss_pct"] == 0.02
    assert {p["name"] for p in mean_dip["param_specs"]} == {"window", "num_std"}
    assert mean_dip["risk_param_specs"] == []


def test_build_strategy_instance_dispatches_mean_dip():
    preset = PRESETS["mean_dip"]
    strategy = build_strategy_instance(preset, {"window": 12, "num_std": 2.0})
    assert isinstance(strategy, MeanDipStrategy)
    assert strategy.window == 12


def test_presets_metadata_includes_slope_dip_with_optional_stop_loss():
    """2026-09-16 : le trailing stop est la sortie principale (demande
    explicite de l'utilisateur : 'on vend sur le trailing a 5%'), le
    stop-loss reste un filet de securite optionnel, comme dip_bounce."""
    metadata = presets_metadata()
    slope_dip = next(m for m in metadata if m["key"] == "slope_dip")
    assert slope_dip["timeframe"] == "1m"
    assert slope_dip["supports_stop_loss"] is True
    assert slope_dip["default_stop_loss_pct"] is None
    assert {p["name"] for p in slope_dip["param_specs"]} == {"slope_threshold_pct", "candles_window", "one_buy_per_slope"}
    assert slope_dip["risk_param_specs"] == []


def test_build_strategy_instance_dispatches_slope_dip():
    preset = PRESETS["slope_dip"]
    strategy = build_strategy_instance(preset, {"slope_threshold_pct": 0.005, "candles_window": 5})
    assert isinstance(strategy, SlopeDipStrategy)
    assert strategy.slope_threshold_pct == 0.005
    assert strategy.candles_window == 5


def test_build_namespace_from_payload_applies_defaults():
    args = build_namespace_from_payload({"strategy": "buy_and_hold", "symbol": "BTC/USDT", "since": "2025-01-01"})
    assert args.exchange == "binance"
    assert args.capital == 1000.0
    assert args.repeat == 1
    assert args.until is None
    assert args.param == []


def test_run_backtest_job_rejects_unknown_strategy():
    args = build_namespace_from_payload({"strategy": "not_a_strategy", "symbol": "BTC/USDT", "since": "2025-01-01"})
    with pytest.raises(ValueError):
        run_backtest_job(args)


def test_run_backtest_job_rejects_missing_symbol():
    args = build_namespace_from_payload({"strategy": "buy_and_hold", "symbol": "", "since": "2025-01-01"})
    with pytest.raises(ValueError):
        run_backtest_job(args)


def test_run_backtest_job_rejects_unknown_param(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_lab_module, "fetch_historical_candles", lambda **kwargs: make_candles(50))
    args = build_namespace_from_payload({
        "strategy": "dip_bounce_hourly", "symbol": "BTC/USDT", "since": "2025-01-01",
        "param": ["not_a_param=1"],
    })
    with pytest.raises(ValueError):
        run_backtest_job(args)


def test_run_backtest_job_runs_end_to_end_with_fake_candles(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_lab_module, "fetch_historical_candles", lambda **kwargs: make_candles(50))
    monkeypatch.chdir(tmp_path)
    args = build_namespace_from_payload({
        "strategy": "buy_and_hold", "symbol": "BTC/USDT", "since": "1970-01-01", "capital": 500,
    })
    text, report_path = run_backtest_job(args)
    assert "Rapport de backtest" in text
    assert "Buy & hold" in text
    from pathlib import Path
    assert Path(report_path).exists()


def test_build_chart_payload_downsamples_and_preserves_ohlc_extremes():
    """EF-60 : au-dela de max_candles, regroupe par paquets en conservant le
    plus haut/plus bas reel du paquet (pas juste un point sur N, qui masquerait
    des meches)."""
    candles = [
        Candle(timestamp=i * 60_000, open=100 + i, high=100 + i + 5, low=100 + i - 5, close=100 + i, volume=1)
        for i in range(10)
    ]
    portfolio = Portfolio(starting_capital=1000.0)
    payload = build_chart_payload(candles, portfolio, max_candles=2)
    assert len(payload["candles"]) == 2
    first_bucket = payload["candles"][0]
    assert first_bucket["h"] == max(c.high for c in candles[:5])
    assert first_bucket["l"] == min(c.low for c in candles[:5])
    assert first_bucket["o"] == candles[0].open
    assert first_bucket["c"] == candles[4].close
    assert payload["closed_trades"] == []
    assert payload["open_positions"] == []


def test_run_backtest_job_populates_chart_data_out_for_single_period(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_lab_module, "fetch_historical_candles", lambda **kwargs: make_candles(50))
    monkeypatch.chdir(tmp_path)
    args = build_namespace_from_payload({
        "strategy": "buy_and_hold", "symbol": "BTC/USDT", "since": "1970-01-01", "capital": 500,
    })
    chart_data: dict = {}
    run_backtest_job(args, chart_data_out=chart_data)
    assert len(chart_data["candles"]) > 0
    assert len(chart_data["open_positions"]) == 1  # buy_and_hold n'achete qu'une fois, jamais de vente


def test_run_backtest_job_leaves_chart_data_out_empty_for_multiple_periods(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_lab_module, "fetch_historical_candles", lambda **kwargs: make_candles(50))
    monkeypatch.chdir(tmp_path)
    args = build_namespace_from_payload({
        "strategy": "buy_and_hold", "symbol": "BTC/USDT", "since": "1970-01-01", "capital": 500, "repeat": 2,
    })
    chart_data: dict = {}
    run_backtest_job(args, chart_data_out=chart_data)
    assert chart_data == {}  # pas encore de graphique par sous-periode, hors perimetre


def test_merge_dual_timeframe_orders_by_close_time_not_open_time():
    """Bug reel rencontre : une bougie 1h ouverte a T=0 n'est connue (son
    close disponible) qu'a T=3_600_000 (une heure plus tard) - trier par
    timestamp D'OUVERTURE la placerait AVANT les bougies 5 min de cette
    meme heure, alors qu'elle doit apparaitre APRES toutes (son prix de
    cloture reflete un instant plus tardif)."""
    entry = [Candle(timestamp=0, open=100, high=100, low=100, close=999, volume=1)]  # 1h, connue a t=3_600_000
    fine = [
        Candle(timestamp=0, open=100, high=100, low=100, close=1, volume=1),          # 5m, connue a t=300_000
        Candle(timestamp=3_300_000, open=100, high=100, low=100, close=2, volume=1),  # 5m, connue a t=3_600_000
    ]
    merged = merge_dual_timeframe(entry, fine, "1h", "5m")
    closes_in_order = [c.close for c, _ in merged]
    # la bougie fine a 3_600_000 partage l'instant de cloture de la bougie 1h -> l'entree la remplace (999, pas 2)
    assert closes_in_order == [1, 999]
    assert [is_entry for _, is_entry in merged] == [False, True]


def test_merge_dual_timeframe_entry_replaces_coincident_fine_candle():
    entry = [Candle(timestamp=0, open=100, high=100, low=100, close=999, volume=1)]
    fine = [Candle(timestamp=3_300_000, open=100, high=100, low=100, close=1, volume=1)]  # meme instant de cloture (1h)
    merged = merge_dual_timeframe(entry, fine, "1h", "5m")
    assert len(merged) == 1
    assert merged[0][0].close == 999
    assert merged[0][1] is True


def test_run_one_period_exit_checked_at_fine_granularity_does_not_undershoot_the_trigger():
    """Reproduction du bug reel : sans la correction d'ordre, un gain arme
    a l'interieur d'une heure puis retombe brutalement pouvait se vendre
    tres loin sous le seuil de declenchement, faute d'etre verifie avant la
    cloture de l'heure entiere. Avec le merge corrige, la vente doit se
    produire des que le gain (verifie en 5 min) retombe sous le seuil -
    jamais un decrochage de plusieurs %."""
    preset = PRESETS["dip_bounce_hourly"]
    # 1h d'entree : creux plat puis achat, une seule bougie suffit a tester la sortie.
    entry_candles = [
        Candle(timestamp=i * 3_600_000, open=100, high=100, low=100, close=100, volume=1) for i in range(24)
    ] + [Candle(timestamp=24 * 3_600_000, open=100, high=100, low=100, close=100, volume=1)]  # declenche l'achat
    # bougies 5 min de l'heure suivante : le prix grimpe a +2% (arme le verrou a 1%) puis
    # retombe a +0.3% (sous le seuil de declenchement 0.7%) des la bougie fine suivante.
    hour_start = 25 * 3_600_000
    fine_prices = [102.0, 100.3] + [100.3] * 10
    exit_check_candles = [
        Candle(timestamp=hour_start + i * 300_000, open=p, high=p, low=p, close=p, volume=1)
        for i, p in enumerate(fine_prices)
    ]
    risk_kwargs = {
        "stop_loss_pct": None, "take_profit_pct": None, "max_concurrent_positions": 1,
        "profit_lock_arm_pct": 0.01, "profit_lock_trigger_pct": 0.007,
    }
    report, benchmark_pct, trade_stats, _portfolio = run_one_period(
        preset, {"dip_threshold_pct": 0.01, "force_trade_after_hours": 0}, risk_kwargs, 1000.0,
        entry_candles, None, exit_check_candles, "1h", "5m",
    )
    assert trade_stats["num_trades"] == 1
    worst_pct = trade_stats["worst_trade_pnl"]
    assert worst_pct > -5.0  # ne doit surtout pas decrocher loin sous le seuil de 0.7%


def test_build_risk_kwargs_defaults_max_concurrent_positions_to_one():
    preset = PRESETS["sma_cross"]
    args = build_namespace_from_payload({"strategy": "sma_cross", "symbol": "BTC/USDT", "since": "2025-01-01"})
    risk_kwargs, risk_summary = build_risk_kwargs_and_summary(preset, args, {})
    assert risk_kwargs["max_concurrent_positions"] == 1
    assert risk_summary["max_concurrent_positions"] == 1


def test_build_risk_kwargs_respects_custom_max_concurrent_positions():
    preset = PRESETS["sma_cross"]
    args = build_namespace_from_payload({
        "strategy": "sma_cross", "symbol": "BTC/USDT", "since": "2025-01-01", "max_concurrent_positions": 5,
    })
    risk_kwargs, risk_summary = build_risk_kwargs_and_summary(preset, args, {})
    assert risk_kwargs["max_concurrent_positions"] == 5
    assert risk_summary["max_concurrent_positions"] == 5


def test_build_risk_kwargs_rejects_invalid_max_concurrent_positions():
    preset = PRESETS["sma_cross"]
    args = build_namespace_from_payload({
        "strategy": "sma_cross", "symbol": "BTC/USDT", "since": "2025-01-01", "max_concurrent_positions": -1,
    })
    with pytest.raises(ValueError):
        build_risk_kwargs_and_summary(preset, args, {})


def test_build_price_level_sizer_kwargs_disabled_by_default():
    preset = PRESETS["sma_cross"]
    args = build_namespace_from_payload({"strategy": "sma_cross", "symbol": "BTC/USDT", "since": "2025-01-01"})
    kwargs, summary = build_price_level_sizer_kwargs(preset, args)
    assert kwargs is None
    assert summary == {}


def test_build_price_level_sizer_kwargs_enabled_with_custom_bounds():
    preset = PRESETS["sma_cross"]
    args = build_namespace_from_payload({
        "strategy": "sma_cross", "symbol": "BTC/USDT", "since": "2025-01-01",
        "price_level_sizing": True, "price_level_min_multiplier": 60, "price_level_max_multiplier": 140,
    })
    kwargs, summary = build_price_level_sizer_kwargs(preset, args)
    assert kwargs == {"min_size_multiplier": 0.6, "max_size_multiplier": 1.4}
    assert summary["price_level_sizing_min"] == 0.6
    assert summary["price_level_sizing_max"] == 1.4


def test_build_price_level_sizer_kwargs_ignored_for_market_making():
    preset = PRESETS["market_making"]
    args = build_namespace_from_payload({
        "strategy": "market_making", "symbol": "BTC/USDT", "since": "2025-01-01", "price_level_sizing": True,
    })
    kwargs, summary = build_price_level_sizer_kwargs(preset, args)
    assert kwargs is None
    assert summary == {}


def test_run_backtest_job_with_price_level_sizing_enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_lab_module, "fetch_historical_candles", lambda **kwargs: make_candles(200))
    monkeypatch.chdir(tmp_path)
    args = build_namespace_from_payload({
        "strategy": "buy_and_hold", "symbol": "BTC/USDT", "since": "1970-01-01", "capital": 500,
        "price_level_sizing": True, "price_level_min_multiplier": 50, "price_level_max_multiplier": 150,
    })
    text, report_path = run_backtest_job(args)
    assert "price_level_sizing_min" in text
    assert "Rapport de backtest" in text


def test_build_risk_kwargs_applies_generic_risk_overrides():
    """Parite avec le formulaire de creation de bot (control_server.py) :
    max_position_size_pct/max_daily_loss_pct/trailing_stop_pct/fee_pct/
    sortie partielle doivent etre reglables en backtest, pas seulement en
    paper trading reel - demande explicite de l'utilisateur."""
    preset = PRESETS["sma_cross"]
    args = build_namespace_from_payload({
        "strategy": "sma_cross", "symbol": "BTC/USDT", "since": "2025-01-01",
        "max_position_size_pct": 20, "max_daily_loss_pct": 8, "trailing_stop_pct": 1.5,
        "fee_pct": 0.05, "take_profit_pct": 5, "partial_take_profit_pct": 2, "partial_exit_fraction": 40,
    })
    risk_kwargs, risk_summary = build_risk_kwargs_and_summary(preset, args, {})
    assert risk_kwargs["max_position_size_pct"] == pytest.approx(0.20)
    assert risk_kwargs["max_daily_loss_pct"] == pytest.approx(0.08)
    assert risk_kwargs["trailing_stop_pct"] == pytest.approx(0.015)
    assert risk_kwargs["fee_pct"] == pytest.approx(0.0005)
    assert risk_kwargs["partial_take_profit_pct"] == pytest.approx(0.02)
    assert risk_kwargs["partial_exit_fraction"] == pytest.approx(0.40)
    assert risk_summary["max_position_size_pct"] == pytest.approx(0.20)


def test_build_risk_kwargs_rejects_partial_take_profit_above_take_profit():
    preset = PRESETS["sma_cross"]
    args = build_namespace_from_payload({
        "strategy": "sma_cross", "symbol": "BTC/USDT", "since": "2025-01-01",
        "take_profit_pct": 2, "partial_take_profit_pct": 3,
    })
    with pytest.raises(ValueError):
        build_risk_kwargs_and_summary(preset, args, {})


def test_build_risk_kwargs_rejects_position_size_x_concurrency_over_100_pct():
    preset = PRESETS["sma_cross"]
    args = build_namespace_from_payload({
        "strategy": "sma_cross", "symbol": "BTC/USDT", "since": "2025-01-01",
        "max_position_size_pct": 60, "max_concurrent_positions": 2,
    })
    with pytest.raises(ValueError):
        build_risk_kwargs_and_summary(preset, args, {})


def test_build_trend_filter_kwargs_disabled_by_default():
    preset = PRESETS["sma_cross"]
    args = build_namespace_from_payload({"strategy": "sma_cross", "symbol": "BTC/USDT", "since": "2025-01-01"})
    kwargs, summary = build_trend_filter_kwargs(preset, args)
    assert kwargs is None
    assert summary == {}


def test_build_trend_filter_kwargs_enabled_with_custom_period():
    preset = PRESETS["sma_cross"]
    args = build_namespace_from_payload({
        "strategy": "sma_cross", "symbol": "BTC/USDT", "since": "2025-01-01",
        "trend_filter_enabled": True, "trend_filter_ema_period": 50,
    })
    kwargs, summary = build_trend_filter_kwargs(preset, args)
    assert kwargs == {"ema_period": 50}
    assert summary == {"trend_filter_ema_period": 50}


def test_build_trend_filter_kwargs_ignored_for_market_making():
    preset = PRESETS["market_making"]
    args = build_namespace_from_payload({
        "strategy": "market_making", "symbol": "BTC/USDT", "since": "2025-01-01", "trend_filter_enabled": True,
    })
    kwargs, summary = build_trend_filter_kwargs(preset, args)
    assert kwargs is None
    assert summary == {}


def test_build_atr_sizer_kwargs_enabled_with_custom_values():
    preset = PRESETS["sma_cross"]
    args = build_namespace_from_payload({
        "strategy": "sma_cross", "symbol": "BTC/USDT", "since": "2025-01-01",
        "atr_sizing_enabled": True, "atr_period": 7, "atr_baseline_period": 50, "atr_min_multiplier": 30,
    })
    kwargs, summary = build_atr_sizer_kwargs(preset, args)
    assert kwargs == {"atr_period": 7, "baseline_period": 50, "min_size_multiplier": pytest.approx(0.3)}


def test_run_backtest_job_rejects_invalid_timeframe(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_lab_module, "fetch_historical_candles", lambda **kwargs: make_candles(50))
    args = build_namespace_from_payload({
        "strategy": "sma_cross", "symbol": "BTC/USDT", "since": "2025-01-01", "timeframe": "3h",
    })
    with pytest.raises(ValueError):
        run_backtest_job(args)


def test_run_backtest_job_uses_requested_timeframe_when_preset_allows_it(monkeypatch, tmp_path):
    seen_timeframes = []

    def fake_fetch(**kwargs):
        seen_timeframes.append(kwargs["timeframe"])
        return make_candles(50)

    monkeypatch.setattr(backtest_lab_module, "fetch_historical_candles", fake_fetch)
    monkeypatch.chdir(tmp_path)
    args = build_namespace_from_payload({
        "strategy": "sma_cross", "symbol": "BTC/USDT", "since": "1970-01-01", "timeframe": "15m",
    })
    run_backtest_job(args)
    assert seen_timeframes == ["15m"]


def test_run_backtest_job_ignores_timeframe_override_for_forced_preset(monkeypatch, tmp_path):
    """dip_bounce_hourly force 1h - un timeframe soumis par erreur ne doit
    jamais le remplacer (meme garantie que control_server.py cote bot reel)."""
    seen_timeframes = []

    def fake_fetch(**kwargs):
        seen_timeframes.append(kwargs["timeframe"])
        return make_candles(50)

    monkeypatch.setattr(backtest_lab_module, "fetch_historical_candles", fake_fetch)
    monkeypatch.chdir(tmp_path)
    args = build_namespace_from_payload({
        "strategy": "dip_bounce_hourly", "symbol": "BTC/USDT", "since": "1970-01-01", "timeframe": "5m",
    })
    run_backtest_job(args)
    assert seen_timeframes == ["1h"]


def test_run_backtest_job_with_trend_filter_and_atr_sizing_enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_lab_module, "fetch_historical_candles", lambda **kwargs: make_candles(200))
    monkeypatch.chdir(tmp_path)
    args = build_namespace_from_payload({
        "strategy": "sma_cross", "symbol": "BTC/USDT", "since": "1970-01-01", "capital": 500,
        "trend_filter_enabled": True, "trend_filter_ema_period": 20,
        "atr_sizing_enabled": True, "atr_period": 5, "atr_baseline_period": 20, "atr_min_multiplier": 30,
    })
    text, report_path = run_backtest_job(args)
    assert "trend_filter_ema_period" in text
    assert "atr_period" in text
    assert "Rapport de backtest" in text


def test_run_backtest_job_reports_progress_single_period(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_lab_module, "fetch_historical_candles", lambda **kwargs: make_candles(50))
    monkeypatch.chdir(tmp_path)
    updates = []
    args = build_namespace_from_payload({
        "strategy": "buy_and_hold", "symbol": "BTC/USDT", "since": "1970-01-01", "capital": 500,
    })
    run_backtest_job(args, progress_callback=updates.append)
    stages = [u["stage"] for u in updates]
    assert stages[0] == "download"
    assert stages[-1] == "running"
    assert updates[-1] == {"stage": "running", "current": 1, "total": 1}


def test_run_backtest_job_reports_progress_per_sub_period(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_lab_module, "fetch_historical_candles", lambda **kwargs: make_candles(200))
    monkeypatch.chdir(tmp_path)
    updates = []
    args = build_namespace_from_payload({
        "strategy": "buy_and_hold", "symbol": "BTC/USDT", "since": "1970-01-01",
        "until": "1970-01-09", "capital": 500, "repeat": 4,
    })
    run_backtest_job(args, progress_callback=updates.append)
    running_updates = [u for u in updates if u["stage"] == "running"]
    assert [u["current"] for u in running_updates] == [0, 1, 2, 3, 4]
    assert all(u["total"] == 4 for u in running_updates)


def test_run_backtest_job_works_without_progress_callback(monkeypatch, tmp_path):
    """Le callback est optionnel - ne doit rien casser pour le CLI/les
    appelants existants qui n'en passent pas (comportement par defaut)."""
    monkeypatch.setattr(backtest_lab_module, "fetch_historical_candles", lambda **kwargs: make_candles(50))
    monkeypatch.chdir(tmp_path)
    args = build_namespace_from_payload({
        "strategy": "buy_and_hold", "symbol": "BTC/USDT", "since": "1970-01-01", "capital": 500,
    })
    text, _ = run_backtest_job(args)
    assert "Rapport de backtest" in text


def test_run_backtest_job_repeat_splits_into_sub_periods(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_lab_module, "fetch_historical_candles", lambda **kwargs: make_candles(200))
    monkeypatch.chdir(tmp_path)
    args = build_namespace_from_payload({
        "strategy": "buy_and_hold", "symbol": "BTC/USDT", "since": "1970-01-01",
        "until": "1970-01-09", "capital": 500, "repeat": 4,
    })
    text, report_path = run_backtest_job(args)
    assert "sous-periodes" in text.lower()
    assert "Synthese" in text
