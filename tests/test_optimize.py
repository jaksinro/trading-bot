from pathlib import Path

import yaml

from tradingbot.optimize import (
    MIN_DRAWDOWN_FLOOR,
    BacktestResult,
    Candidate,
    build_dip_bounce_candidates,
    build_market_making_candidates,
    build_mean_reversion_candidates,
    build_scalp_dip_candidates,
    build_sma_cross_candidates,
    build_strategy,
    compute_window_consistency,
    format_candidate,
    result_to_config_yaml,
    run_one_backtest,
    split_into_windows,
    split_train_test,
    write_config_without_overwriting,
)
from tradingbot.strategies.dip_bounce import DipBounceStrategy
from tradingbot.strategies.market_making import MarketMakingStrategy
from tradingbot.strategies.mean_reversion import MeanReversionStrategy
from tradingbot.types import Candle


def make_oscillating_candles(n=300, amplitude=2.0, period=15):
    closes = []
    price = 100.0
    for i in range(n):
        price += amplitude if (i // period) % 2 == 0 else -amplitude
        closes.append(price)
    return [Candle(timestamp=i, open=c, high=c, low=c, close=c, volume=1.0) for i, c in enumerate(closes)]


def make_trending_candles(n=200, start=100.0, step=0.5):
    return [
        Candle(timestamp=i, open=start + i * step, high=start + i * step, low=start + i * step,
               close=start + i * step, volume=1.0)
        for i in range(n)
    ]


def test_build_sma_cross_candidates_only_valid_pairs():
    candidates = build_sma_cross_candidates()
    assert len(candidates) > 0
    for c in candidates:
        assert c.params["short_window"] < c.params["long_window"]
        assert c.strategy_type == "sma_cross"


def test_build_scalp_dip_candidates_shape():
    candidates = build_scalp_dip_candidates()
    assert len(candidates) > 0
    for c in candidates:
        assert c.strategy_type == "scalp_dip"
        assert "lookback" in c.params
        assert "dip_threshold_pct" in c.params
        assert c.risk["take_profit_pct"] is not None  # indispensable pour scalp_dip


def test_build_mean_reversion_candidates_shape():
    """Etape 6 (piste 6) : famille de strategie distincte de sma_cross/scalp_dip."""
    candidates = build_mean_reversion_candidates()
    assert len(candidates) > 0
    for c in candidates:
        assert c.strategy_type == "mean_reversion"
        assert "window" in c.params
        assert "num_std" in c.params
        assert c.trend_filter_ema_period is None  # incompatible avec le concept (voir docstring)
        assert c.atr_sizing_enabled is False


def test_build_strategy_dispatches_mean_reversion():
    candidate = Candidate(strategy_type="mean_reversion", params={"window": 15, "num_std": 2.0}, risk={})
    strategy = build_strategy(candidate)
    assert isinstance(strategy, MeanReversionStrategy)
    assert strategy.window == 15
    assert strategy.num_std == 2.0


def test_format_candidate_mean_reversion():
    candidate = Candidate(
        strategy_type="mean_reversion", params={"window": 20, "num_std": 2.0},
        risk={"stop_loss_pct": 0.05, "take_profit_pct": None, "max_position_size_pct": 0.1, "max_daily_loss_pct": 0.05},
    )
    text = format_candidate(candidate)
    assert "mean_reversion" in text
    assert "fenetre=20" in text


def test_build_market_making_candidates_shape():
    """Etape 7 (feuille de route performance) : edge structurel (capture de
    spread), pas directionnel comme les 3 familles precedentes."""
    candidates = build_market_making_candidates()
    assert len(candidates) > 0
    for c in candidates:
        assert c.strategy_type == "market_making"
        assert "spread_pct" in c.params
        assert "order_size_quote" in c.params
        assert "max_inventory_quote" in c.params
        assert "skew_factor" in c.params
        assert c.params["order_size_quote"] <= c.params["max_inventory_quote"]
        assert c.trend_filter_ema_period is None
        assert c.atr_sizing_enabled is False


def test_build_strategy_dispatches_market_making():
    candidate = Candidate(
        strategy_type="market_making",
        params={"spread_pct": 0.004, "order_size_quote": 50.0, "max_inventory_quote": 200.0, "skew_factor": 1.0},
        risk={"fee_pct": 0.001},
    )
    strategy = build_strategy(candidate)
    assert isinstance(strategy, MarketMakingStrategy)
    assert strategy.spread_pct == 0.004
    assert strategy.order_size_quote == 50.0


def test_format_candidate_market_making():
    candidate = Candidate(
        strategy_type="market_making",
        params={"spread_pct": 0.004, "order_size_quote": 50.0, "max_inventory_quote": 200.0, "skew_factor": 1.0},
        risk={"fee_pct": 0.001},
    )
    text = format_candidate(candidate)
    assert "market_making" in text
    assert "spread=" in text


def test_build_dip_bounce_candidates_shape():
    """EF-57 : grille etendue au stop-loss/trailing stop (optionnels depuis
    EF-55) et au filtre de tendance - plus fige a None/desactive comme avant
    l'extension du 2026-09-16."""
    candidates = build_dip_bounce_candidates()
    assert len(candidates) > 0
    for c in candidates:
        assert c.strategy_type == "dip_bounce"
        assert "trend_ma_period" in c.params
        assert "dip_threshold_pct" in c.params
        assert c.params["force_trade_after_hours"] is None
        assert c.risk["stop_loss_pct"] in (None, 0.10)
        assert c.risk["trailing_stop_pct"] in (None, 0.05, 0.08)
        assert c.risk["profit_lock_trigger_pct"] < c.risk["profit_lock_arm_pct"]
        assert c.atr_sizing_enabled is False


def test_build_dip_bounce_candidates_include_stop_loss_and_trailing_variants():
    candidates = build_dip_bounce_candidates()
    stop_losses = {c.risk["stop_loss_pct"] for c in candidates}
    trailing_stops = {c.risk["trailing_stop_pct"] for c in candidates}
    assert stop_losses == {None, 0.10}
    assert trailing_stops == {None, 0.05, 0.08}


def test_build_dip_bounce_candidates_include_trend_filter_variants():
    candidates = build_dip_bounce_candidates()
    ema_periods = {c.trend_filter_ema_period for c in candidates}
    assert ema_periods == {None, 50, 100, 200, 300}


def test_build_strategy_dispatches_dip_bounce():
    candidate = Candidate(
        strategy_type="dip_bounce",
        params={"trend_ma_period": 24, "dip_threshold_pct": 0.005},
        risk={"stop_loss_pct": None, "profit_lock_arm_pct": 0.005, "profit_lock_trigger_pct": 0.0043},
    )
    strategy = build_strategy(candidate)
    assert isinstance(strategy, DipBounceStrategy)
    assert strategy.trend_ma_period == 24
    assert strategy.dip_threshold_pct == 0.005


def test_format_candidate_dip_bounce():
    candidate = Candidate(
        strategy_type="dip_bounce",
        params={"trend_ma_period": 24, "dip_threshold_pct": 0.005},
        risk={"stop_loss_pct": None, "profit_lock_arm_pct": 0.005, "profit_lock_trigger_pct": 0.0043},
    )
    text = format_candidate(candidate)
    assert "dip_bounce" in text
    assert "stop_loss=aucun" in text


def test_format_candidate_dip_bounce_shows_stop_loss_and_trailing_when_enabled():
    candidate = Candidate(
        strategy_type="dip_bounce",
        params={"trend_ma_period": 24, "dip_threshold_pct": 0.005},
        risk={
            "stop_loss_pct": 0.10, "trailing_stop_pct": 0.08,
            "profit_lock_arm_pct": 0.15, "profit_lock_trigger_pct": 0.12,
        },
        trend_filter_ema_period=300,
    )
    text = format_candidate(candidate)
    assert "stop_loss=10%" in text
    assert "trailing=8%" in text
    assert "trend_ema=300" in text


def test_run_one_backtest_market_making_uses_mm_engine():
    """Verifie que la branche market_making de run_one_backtest produit un
    resultat exploitable (pas de crash lie a l'absence de RiskManager) sur
    des bougies suffisamment volatiles pour declencher des fills."""
    candles = make_oscillating_candles(n=300, amplitude=3.0, period=5)
    candidate = Candidate(
        strategy_type="market_making",
        params={"spread_pct": 0.01, "order_size_quote": 50.0, "max_inventory_quote": 200.0, "skew_factor": 1.0},
        risk={"fee_pct": 0.001},
    )
    result = run_one_backtest(candles, candidate)
    # Pas d'assertion sur le rendement (empirique, pas garanti) - seulement
    # que le pipeline complet (MarketMakingEngine + BacktestResult) fonctionne.
    if result is not None:
        assert result.candidate.strategy_type == "market_making"


def test_run_one_backtest_returns_none_when_too_few_trades():
    candles = make_trending_candles(n=20)  # trop court pour generer 5+ trades
    candidate = Candidate(
        strategy_type="sma_cross",
        params={"short_window": 10, "long_window": 30},
        risk={"max_position_size_pct": 0.1, "stop_loss_pct": 0.02, "take_profit_pct": None, "max_daily_loss_pct": 0.05},
    )
    assert run_one_backtest(candles, candidate) is None


def test_run_one_backtest_returns_result_with_enough_trades():
    # prix oscillant pour generer plusieurs croisements
    closes = []
    price = 100.0
    for i in range(300):
        price += 2.0 if (i // 15) % 2 == 0 else -2.0
        closes.append(price)
    candles = [Candle(timestamp=i, open=c, high=c, low=c, close=c, volume=1.0) for i, c in enumerate(closes)]

    candidate = Candidate(
        strategy_type="sma_cross",
        params={"short_window": 5, "long_window": 15},
        risk={"max_position_size_pct": 0.5, "stop_loss_pct": 0.5, "take_profit_pct": None, "max_daily_loss_pct": 0.5},
    )
    result = run_one_backtest(candles, candidate)

    assert result is not None
    assert result.num_trades >= 5
    assert 0.0 <= result.win_rate <= 1.0


def test_format_candidate_sma_cross():
    candidate = Candidate(
        strategy_type="sma_cross",
        params={"short_window": 10, "long_window": 30},
        risk={"stop_loss_pct": 0.02},
    )
    text = format_candidate(candidate)
    assert "sma_cross" in text
    assert "10" in text and "30" in text


def test_format_candidate_scalp_dip():
    candidate = Candidate(
        strategy_type="scalp_dip",
        params={"lookback": 20, "dip_threshold_pct": 0.003},
        risk={"stop_loss_pct": 0.01, "take_profit_pct": 0.005},
    )
    text = format_candidate(candidate)
    assert "scalp_dip" in text


def test_split_train_test_respects_ratio():
    candles = list(range(100))
    train, test = split_train_test(candles, train_ratio=0.7)
    assert len(train) == 70
    assert len(test) == 30


def test_split_train_test_is_chronological_not_shuffled():
    candles = list(range(10))
    train, test = split_train_test(candles, train_ratio=0.6)
    assert train == [0, 1, 2, 3, 4, 5]
    assert test == [6, 7, 8, 9]


def test_split_train_test_no_overlap():
    candles = list(range(50))
    train, test = split_train_test(candles, train_ratio=0.7)
    assert set(train).isdisjoint(set(test))
    assert len(train) + len(test) == len(candles)


def test_build_sma_cross_candidates_include_trend_filter_variants():
    candidates = build_sma_cross_candidates()
    ema_periods = {c.trend_filter_ema_period for c in candidates}
    assert None in ema_periods  # variante sans filtre toujours presente
    assert ema_periods == {None, 50, 100, 200, 300}


def test_build_scalp_dip_candidates_include_trend_filter_variants():
    candidates = build_scalp_dip_candidates()
    ema_periods = {c.trend_filter_ema_period for c in candidates}
    assert ema_periods == {None, 50, 100, 200, 300}


def test_build_sma_cross_candidates_include_atr_sizing_variants():
    candidates = build_sma_cross_candidates()
    atr_flags = {c.atr_sizing_enabled for c in candidates}
    assert atr_flags == {False, True}


def test_build_scalp_dip_candidates_include_atr_sizing_variants():
    candidates = build_scalp_dip_candidates()
    atr_flags = {c.atr_sizing_enabled for c in candidates}
    assert atr_flags == {False, True}


def test_build_sma_cross_candidates_cover_full_cross_product_of_trend_and_atr():
    """Chaque combinaison (filtre de tendance x sizing ATR) doit exister pour
    au moins un jeu de parametres - sinon la grille ne teste pas vraiment
    l'interaction des deux options (feuille de route, etapes 1 et 2)."""
    candidates = build_sma_cross_candidates()
    combos = {(c.trend_filter_ema_period, c.atr_sizing_enabled) for c in candidates}
    for ema in [None, 50, 100, 200, 300]:
        for atr in [False, True]:
            assert (ema, atr) in combos


def test_run_one_backtest_wires_trend_filter_into_the_engine(monkeypatch):
    """Verifie que `trend_filter_ema_period` sur le candidat aboutit bien a
    un TrendFilter transmis a l'Engine - le comportement du filtre lui-meme
    (bloquer un achat) est deja teste dans test_engine_trend_filter.py."""
    import tradingbot.optimize as optimize_module

    captured = {}
    original_engine = optimize_module.Engine

    def spy_engine(*args, **kwargs):
        captured["trend_filter"] = kwargs.get("trend_filter")
        return original_engine(*args, **kwargs)

    monkeypatch.setattr(optimize_module, "Engine", spy_engine)

    candles = make_trending_candles(n=20)
    candidate = Candidate(
        strategy_type="sma_cross",
        params={"short_window": 5, "long_window": 15},
        risk={"max_position_size_pct": 0.1, "stop_loss_pct": 0.5, "take_profit_pct": None, "max_daily_loss_pct": 0.5},
        trend_filter_ema_period=100,
    )
    run_one_backtest(candles, candidate)

    assert captured["trend_filter"] is not None
    assert captured["trend_filter"].ema_period == 100


def test_run_one_backtest_wires_atr_sizer_into_the_engine(monkeypatch):
    import tradingbot.optimize as optimize_module

    captured = {}
    original_engine = optimize_module.Engine

    def spy_engine(*args, **kwargs):
        captured["atr_sizer"] = kwargs.get("atr_sizer")
        return original_engine(*args, **kwargs)

    monkeypatch.setattr(optimize_module, "Engine", spy_engine)

    candles = make_trending_candles(n=20)
    candidate = Candidate(
        strategy_type="sma_cross",
        params={"short_window": 5, "long_window": 15},
        risk={"max_position_size_pct": 0.1, "stop_loss_pct": 0.5, "take_profit_pct": None, "max_daily_loss_pct": 0.5},
        atr_sizing_enabled=True,
    )
    run_one_backtest(candles, candidate)

    assert captured["atr_sizer"] is not None
    assert captured["atr_sizer"].atr_period == optimize_module.DEFAULT_ATR_PERIOD


def test_run_one_backtest_no_atr_sizer_when_disabled(monkeypatch):
    import tradingbot.optimize as optimize_module

    captured = {}
    original_engine = optimize_module.Engine

    def spy_engine(*args, **kwargs):
        captured["atr_sizer"] = kwargs.get("atr_sizer")
        return original_engine(*args, **kwargs)

    monkeypatch.setattr(optimize_module, "Engine", spy_engine)

    candles = make_trending_candles(n=20)
    candidate = Candidate(
        strategy_type="sma_cross",
        params={"short_window": 5, "long_window": 15},
        risk={"max_position_size_pct": 0.1, "stop_loss_pct": 0.5, "take_profit_pct": None, "max_daily_loss_pct": 0.5},
    )
    run_one_backtest(candles, candidate)

    assert captured["atr_sizer"] is None


def test_format_candidate_mentions_atr_sizing_when_enabled():
    candidate = Candidate(
        strategy_type="sma_cross",
        params={"short_window": 10, "long_window": 30},
        risk={"stop_loss_pct": 0.02},
        atr_sizing_enabled=True,
    )
    assert "atr_sizing=on" in format_candidate(candidate)


def test_format_candidate_omits_atr_sizing_when_disabled():
    candidate = Candidate(
        strategy_type="sma_cross",
        params={"short_window": 10, "long_window": 30},
        risk={"stop_loss_pct": 0.02},
    )
    assert "atr_sizing" not in format_candidate(candidate)


def test_result_to_config_yaml_includes_atr_sizing_when_enabled():
    candidate = Candidate(
        strategy_type="sma_cross",
        params={"short_window": 10, "long_window": 30},
        risk={"max_position_size_pct": 0.1, "stop_loss_pct": 0.02, "take_profit_pct": None, "max_daily_loss_pct": 0.05},
        atr_sizing_enabled=True,
    )
    result = BacktestResult(
        symbol="BTC/USDT", candidate=candidate, total_return_pct=0.1,
        max_drawdown_pct=0.05, num_trades=10, win_rate=0.6, realized_pnl=100.0,
    )
    config = yaml.safe_load(result_to_config_yaml(result, "test_config"))
    assert config["atr_sizing"] == {"enabled": True, "atr_period": 14, "baseline_period": 100, "min_size_multiplier": 0.2}


def test_result_to_config_yaml_omits_atr_sizing_when_disabled():
    candidate = Candidate(
        strategy_type="sma_cross",
        params={"short_window": 10, "long_window": 30},
        risk={"max_position_size_pct": 0.1, "stop_loss_pct": 0.02, "take_profit_pct": None, "max_daily_loss_pct": 0.05},
    )
    result = BacktestResult(
        symbol="BTC/USDT", candidate=candidate, total_return_pct=0.1,
        max_drawdown_pct=0.05, num_trades=10, win_rate=0.6, realized_pnl=100.0,
    )
    config = yaml.safe_load(result_to_config_yaml(result, "test_config"))
    assert "atr_sizing" not in config


def test_run_one_backtest_no_trend_filter_when_ema_period_is_none(monkeypatch):
    import tradingbot.optimize as optimize_module

    captured = {}
    original_engine = optimize_module.Engine

    def spy_engine(*args, **kwargs):
        captured["trend_filter"] = kwargs.get("trend_filter")
        return original_engine(*args, **kwargs)

    monkeypatch.setattr(optimize_module, "Engine", spy_engine)

    candles = make_trending_candles(n=20)
    candidate = Candidate(
        strategy_type="sma_cross",
        params={"short_window": 5, "long_window": 15},
        risk={"max_position_size_pct": 0.1, "stop_loss_pct": 0.5, "take_profit_pct": None, "max_daily_loss_pct": 0.5},
    )
    run_one_backtest(candles, candidate)

    assert captured["trend_filter"] is None


def test_format_candidate_mentions_trend_filter_when_enabled():
    candidate = Candidate(
        strategy_type="sma_cross",
        params={"short_window": 10, "long_window": 30},
        risk={"stop_loss_pct": 0.02},
        trend_filter_ema_period=100,
    )
    text = format_candidate(candidate)
    assert "trend_ema=100" in text


def test_format_candidate_omits_trend_filter_when_disabled():
    candidate = Candidate(
        strategy_type="sma_cross",
        params={"short_window": 10, "long_window": 30},
        risk={"stop_loss_pct": 0.02},
    )
    text = format_candidate(candidate)
    assert "trend_ema" not in text


def test_result_to_config_yaml_includes_trend_filter_when_enabled():
    candidate = Candidate(
        strategy_type="sma_cross",
        params={"short_window": 10, "long_window": 30},
        risk={"max_position_size_pct": 0.1, "stop_loss_pct": 0.02, "take_profit_pct": None, "max_daily_loss_pct": 0.05},
        trend_filter_ema_period=100,
    )
    result = BacktestResult(
        symbol="BTC/USDT", candidate=candidate, total_return_pct=0.1,
        max_drawdown_pct=0.05, num_trades=10, win_rate=0.6, realized_pnl=100.0,
    )
    config = yaml.safe_load(result_to_config_yaml(result, "test_config"))
    assert config["trend_filter"] == {"enabled": True, "ema_period": 100}
    assert config["warmup_candles"] >= 100


def test_result_to_config_yaml_omits_trend_filter_when_disabled():
    candidate = Candidate(
        strategy_type="sma_cross",
        params={"short_window": 10, "long_window": 30},
        risk={"max_position_size_pct": 0.1, "stop_loss_pct": 0.02, "take_profit_pct": None, "max_daily_loss_pct": 0.05},
    )
    result = BacktestResult(
        symbol="BTC/USDT", candidate=candidate, total_return_pct=0.1,
        max_drawdown_pct=0.05, num_trades=10, win_rate=0.6, realized_pnl=100.0,
    )
    config = yaml.safe_load(result_to_config_yaml(result, "test_config"))
    assert "trend_filter" not in config


def _make_result(total_return_pct, max_drawdown_pct):
    return BacktestResult(
        symbol="BTC/USDT",
        candidate=Candidate(strategy_type="sma_cross", params={"short_window": 10, "long_window": 30}, risk={}),
        total_return_pct=total_return_pct, max_drawdown_pct=max_drawdown_pct,
        num_trades=10, win_rate=0.5, realized_pnl=100.0,
    )


def test_risk_adjusted_return_divides_return_by_drawdown():
    result = _make_result(total_return_pct=0.20, max_drawdown_pct=0.10)
    assert result.risk_adjusted_return == 2.0


def test_risk_adjusted_return_applies_drawdown_floor():
    """Etape 6 (piste 4) : un drawdown quasi nul ne doit pas gonfler le score
    artificiellement - le plancher MIN_DRAWDOWN_FLOOR s'applique."""
    result = _make_result(total_return_pct=0.10, max_drawdown_pct=0.001)
    assert result.risk_adjusted_return == 0.10 / MIN_DRAWDOWN_FLOOR


def test_risk_adjusted_return_prefers_lower_drawdown_at_equal_return():
    steady = _make_result(total_return_pct=0.10, max_drawdown_pct=0.02)
    volatile = _make_result(total_return_pct=0.10, max_drawdown_pct=0.15)
    assert steady.risk_adjusted_return > volatile.risk_adjusted_return


def test_split_into_windows_splits_evenly():
    candles = make_trending_candles(300)
    windows = split_into_windows(candles, num_windows=3)
    assert len(windows) == 3
    assert sum(len(w) for w in windows) == 300


def test_split_into_windows_merges_remainder_into_last_window():
    candles = make_trending_candles(301)  # pas un multiple exact de 3
    windows = split_into_windows(candles, num_windows=3)
    assert len(windows) == 3
    assert sum(len(w) for w in windows) == 301


def test_split_into_windows_empty_list():
    assert split_into_windows([], num_windows=3) == []


def test_split_into_windows_single_window_returns_everything():
    candles = make_trending_candles(50)
    windows = split_into_windows(candles, num_windows=1)
    assert len(windows) == 1
    assert len(windows[0]) == 50


def test_compute_window_consistency_scores_across_multiple_windows():
    """Etape 6 (piste 5) : une strategie qui trade de facon comparable dans
    chaque sous-fenetre (memes oscillations repetees) doit obtenir une
    consistance elevee, pas juste un bon chiffre agrege sur toute la
    periode."""
    candles = make_oscillating_candles(n=600)
    candidate = Candidate(
        strategy_type="sma_cross", params={"short_window": 5, "long_window": 15},
        risk={"max_position_size_pct": 0.5, "stop_loss_pct": 0.5, "take_profit_pct": None, "max_daily_loss_pct": 0.5},
    )
    returns, consistency = compute_window_consistency(candles, candidate, num_windows=3)
    assert len(returns) == 3
    assert consistency is not None
    assert 0.0 <= consistency <= 1.0


def test_compute_window_consistency_none_when_no_window_has_enough_trades():
    candles = make_trending_candles(30)  # trop court, jamais assez de trades
    candidate = Candidate(
        strategy_type="sma_cross", params={"short_window": 5, "long_window": 15},
        risk={"max_position_size_pct": 0.1, "stop_loss_pct": 0.02, "take_profit_pct": None, "max_daily_loss_pct": 0.05},
    )
    returns, consistency = compute_window_consistency(candles, candidate, num_windows=3)
    assert consistency is None
    assert all(r is None for r in returns)


def test_write_config_without_overwriting_writes_normally_when_file_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()

    path, was_renamed = write_config_without_overwriting("optimized_btcusdt_sma_cross", "name: test\n")

    assert was_renamed is False
    assert path == Path("config/optimized_btcusdt_sma_cross.yml")
    assert path.read_text(encoding="utf-8") == "name: test\n"


def test_write_config_without_overwriting_renames_when_file_exists(tmp_path, monkeypatch):
    """CT-21 de la STB : ecraser en silence la config d'un bot deja deploye
    (meme nom auto-genere) a deja fait perdre un reglage tune manuellement -
    ce cas doit desormais ecrire a cote plutot que d'ecraser."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    existing = Path("config/optimized_dogeusdt_sma_cross.yml")
    existing.write_text("capital_allocated: 500\n", encoding="utf-8")

    path, was_renamed = write_config_without_overwriting("optimized_dogeusdt_sma_cross", "capital_allocated: 200\n")

    assert was_renamed is True
    assert path == Path("config/optimized_dogeusdt_sma_cross_candidate.yml")
    assert existing.read_text(encoding="utf-8") == "capital_allocated: 500\n"  # inchange
    assert path.read_text(encoding="utf-8") == "capital_allocated: 200\n"
