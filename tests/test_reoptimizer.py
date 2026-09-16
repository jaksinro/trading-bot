import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from tradingbot import reoptimizer
from tradingbot.optimize import BacktestResult, Candidate
from tradingbot.reporting.logger import TradeLogger
from tradingbot.types import Candle, Position


def test_is_due_when_never_checked():
    assert reoptimizer.is_due_for_reoptimization(None, datetime.now(timezone.utc)) is True


def test_is_not_due_when_checked_recently():
    now = datetime.now(timezone.utc)
    last_checked = (now - timedelta(days=5)).isoformat()
    assert reoptimizer.is_due_for_reoptimization(last_checked, now, interval_days=30) is False


def test_is_due_once_interval_elapsed():
    now = datetime.now(timezone.utc)
    last_checked = (now - timedelta(days=31)).isoformat()
    assert reoptimizer.is_due_for_reoptimization(last_checked, now, interval_days=30) is True


def test_default_interval_is_one_week():
    assert reoptimizer.REOPTIMIZE_INTERVAL_DAYS == 7


def test_is_due_uses_weekly_default():
    now = datetime.now(timezone.utc)
    assert reoptimizer.is_due_for_reoptimization((now - timedelta(days=5)).isoformat(), now) is False
    assert reoptimizer.is_due_for_reoptimization((now - timedelta(days=8)).isoformat(), now) is True


def test_has_open_position_false_when_none_saved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("reopt_test_bot")
    logger.close()
    assert reoptimizer.has_open_position("reopt_test_bot") is False


def test_has_open_position_true_when_positions_saved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("reopt_test_bot_2")
    logger.save_open_positions([Position(quantity=1.0, avg_entry_price=100.0, lot_id=1)])
    logger.close()
    assert reoptimizer.has_open_position("reopt_test_bot_2") is True


def _fake_result(total_return_pct):
    return BacktestResult(
        symbol="BTC/USDT",
        candidate=Candidate(strategy_type="sma_cross", params={"short_window": 10, "long_window": 30}, risk={}),
        total_return_pct=total_return_pct, max_drawdown_pct=0.05, num_trades=10, win_rate=0.5, realized_pnl=100.0,
    )


def test_is_better_out_of_sample_false_when_candidate_none():
    assert reoptimizer.is_better_out_of_sample(_fake_result(0.05), None) is False


def test_is_better_out_of_sample_true_when_current_none():
    assert reoptimizer.is_better_out_of_sample(None, _fake_result(0.01)) is True


def test_is_better_out_of_sample_compares_returns():
    assert reoptimizer.is_better_out_of_sample(_fake_result(0.05), _fake_result(0.10)) is True
    assert reoptimizer.is_better_out_of_sample(_fake_result(0.05), _fake_result(0.03)) is False
    assert reoptimizer.is_better_out_of_sample(_fake_result(0.05), _fake_result(0.05)) is False  # egal n'est pas "mieux"


def test_is_better_out_of_sample_rejects_improvement_below_minimum_margin():
    """Etape 6 : un ecart de bruit (bien en dessous de MIN_IMPROVEMENT_MARGIN)
    ne doit pas declencher un changement - c'est exactement le config-shopping
    observe en simulation retrospective."""
    tiny_improvement = reoptimizer.MIN_IMPROVEMENT_MARGIN / 2
    assert reoptimizer.is_better_out_of_sample(_fake_result(0.05), _fake_result(0.05 + tiny_improvement)) is False


def test_is_better_out_of_sample_accepts_improvement_above_minimum_margin():
    comfortable_improvement = reoptimizer.MIN_IMPROVEMENT_MARGIN * 2
    assert reoptimizer.is_better_out_of_sample(_fake_result(0.05), _fake_result(0.05 + comfortable_improvement)) is True


def test_is_better_out_of_sample_custom_margin_overrides_default():
    assert reoptimizer.is_better_out_of_sample(_fake_result(0.05), _fake_result(0.06), min_margin=0.02) is False
    assert reoptimizer.is_better_out_of_sample(_fake_result(0.05), _fake_result(0.08), min_margin=0.02) is True


def _fake_result_with_benchmark(total_return_pct, benchmark_return_pct):
    result = _fake_result(total_return_pct)
    result.benchmark_return_pct = benchmark_return_pct
    return result


def test_has_edge_over_benchmark_false_when_result_none():
    assert reoptimizer.has_edge_over_benchmark(None) is False


def test_has_edge_over_benchmark_permissive_when_benchmark_unmeasured():
    assert reoptimizer.has_edge_over_benchmark(_fake_result(0.05)) is True  # benchmark_return_pct=None par defaut


def test_has_edge_over_benchmark_true_when_beats_buy_and_hold():
    assert reoptimizer.has_edge_over_benchmark(_fake_result_with_benchmark(0.10, 0.05)) is True


def test_has_edge_over_benchmark_false_when_loses_to_buy_and_hold():
    """Etape 6 : un candidat qui 'gagne' juste parce que le marche est monte
    plus vite que la strategie ne doit pas etre propose."""
    assert reoptimizer.has_edge_over_benchmark(_fake_result_with_benchmark(0.05, 0.20)) is False


def _oscillating_candles_for_consistency(n=600):
    closes = []
    price = 100.0
    for i in range(n):
        price += 2.0 if (i // 15) % 2 == 0 else -2.0
        closes.append(price)
    return [Candle(timestamp=i, open=c, high=c, low=c, close=c, volume=1.0) for i, c in enumerate(closes)]


def test_is_consistent_across_windows_true_above_threshold(monkeypatch):
    monkeypatch.setattr(reoptimizer, "compute_window_consistency", lambda candles, candidate: ([0.1, 0.1, -0.02], 0.67))
    candidate = Candidate(strategy_type="sma_cross", params={"short_window": 5, "long_window": 15}, risk={})
    assert reoptimizer.is_consistent_across_windows([], candidate) is True


def test_is_consistent_across_windows_false_below_threshold(monkeypatch):
    """Etape 6 (piste 5) : un candidat positif sur une seule sous-fenetre
    sur trois ne doit pas etre considere consistant."""
    monkeypatch.setattr(reoptimizer, "compute_window_consistency", lambda candles, candidate: ([0.1, -0.05, -0.03], 0.33))
    candidate = Candidate(strategy_type="sma_cross", params={"short_window": 5, "long_window": 15}, risk={})
    assert reoptimizer.is_consistent_across_windows([], candidate) is False


def test_is_consistent_across_windows_permissive_when_unmeasured(monkeypatch):
    monkeypatch.setattr(reoptimizer, "compute_window_consistency", lambda candles, candidate: ([None, None, None], None))
    candidate = Candidate(strategy_type="sma_cross", params={"short_window": 5, "long_window": 15}, risk={})
    assert reoptimizer.is_consistent_across_windows([], candidate) is True


def test_is_consistent_across_windows_real_backtest_returns_a_bool():
    """Verification d'integration (pas de mock) : la fonction s'appuie
    reellement sur compute_window_consistency de optimize.py."""
    candidate = Candidate(
        strategy_type="sma_cross", params={"short_window": 5, "long_window": 15},
        risk={"max_position_size_pct": 0.5, "stop_loss_pct": 0.5, "take_profit_pct": None, "max_daily_loss_pct": 0.5},
    )
    result = reoptimizer.is_consistent_across_windows(_oscillating_candles_for_consistency(), candidate)
    assert isinstance(result, bool)


def test_candidate_from_config_extracts_strategy_and_risk():
    config = {
        "strategy": {"type": "sma_cross", "short_window": 10, "long_window": 30},
        "risk": {"max_position_size_pct": 0.15, "stop_loss_pct": 0.03, "take_profit_pct": None, "max_daily_loss_pct": 0.05},
    }
    candidate = reoptimizer.candidate_from_config(config)
    assert candidate.strategy_type == "sma_cross"
    assert candidate.params == {"short_window": 10, "long_window": 30}
    assert candidate.risk["max_position_size_pct"] == 0.15
    assert candidate.trend_filter_ema_period is None


def test_candidate_from_config_extracts_enabled_trend_filter():
    config = {
        "strategy": {"type": "sma_cross", "short_window": 10, "long_window": 30},
        "risk": {},
        "trend_filter": {"enabled": True, "ema_period": 100},
    }
    candidate = reoptimizer.candidate_from_config(config)
    assert candidate.trend_filter_ema_period == 100


def test_candidate_from_config_ignores_disabled_trend_filter():
    config = {
        "strategy": {"type": "sma_cross", "short_window": 10, "long_window": 30},
        "risk": {},
        "trend_filter": {"enabled": False, "ema_period": 100},
    }
    candidate = reoptimizer.candidate_from_config(config)
    assert candidate.trend_filter_ema_period is None


def test_candidate_from_config_extracts_enabled_atr_sizing():
    config = {
        "strategy": {"type": "sma_cross", "short_window": 10, "long_window": 30},
        "risk": {},
        "atr_sizing": {"enabled": True, "atr_period": 14, "baseline_period": 100, "min_size_multiplier": 0.2},
    }
    candidate = reoptimizer.candidate_from_config(config)
    assert candidate.atr_sizing_enabled is True


def test_candidate_from_config_ignores_disabled_atr_sizing():
    config = {
        "strategy": {"type": "sma_cross", "short_window": 10, "long_window": 30},
        "risk": {},
        "atr_sizing": {"enabled": False},
    }
    candidate = reoptimizer.candidate_from_config(config)
    assert candidate.atr_sizing_enabled is False


def test_candidate_from_config_defaults_atr_sizing_to_disabled():
    config = {"strategy": {"type": "sma_cross", "short_window": 10, "long_window": 30}, "risk": {}}
    candidate = reoptimizer.candidate_from_config(config)
    assert candidate.atr_sizing_enabled is False


@pytest.fixture
def isolated_proposals_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(reoptimizer, "PROPOSALS_DIR", tmp_path / "proposals")
    monkeypatch.setattr(reoptimizer, "STATE_FILE", tmp_path / "proposals" / "reoptimize_state.json")
    monkeypatch.setattr(reoptimizer, "GROUPS_FILE", tmp_path / "proposals" / "ab_test_groups.json")
    return tmp_path / "proposals"


def test_assign_groups_is_balanced(isolated_proposals_dir):
    groups = reoptimizer.assign_groups([f"bot_{i}" for i in range(10)])
    n_auto = sum(1 for g in groups.values() if g == "auto")
    n_control = sum(1 for g in groups.values() if g == "control")
    assert n_auto == 5
    assert n_control == 5


def test_assign_groups_is_stable_across_calls(isolated_proposals_dir):
    """Un bot deja assigne ne doit jamais changer de groupe - sinon le test
    A/B n'a plus de sens."""
    first = reoptimizer.assign_groups(["bot_a", "bot_b", "bot_c"])
    second = reoptimizer.assign_groups(["bot_a", "bot_b", "bot_c", "bot_d"])
    assert second["bot_a"] == first["bot_a"]
    assert second["bot_b"] == first["bot_b"]
    assert second["bot_c"] == first["bot_c"]
    assert "bot_d" in second


def test_assign_groups_drops_removed_bots(isolated_proposals_dir):
    reoptimizer.assign_groups(["bot_a", "bot_b"])
    groups = reoptimizer.assign_groups(["bot_a"])
    assert "bot_b" not in groups
    assert "bot_a" in groups


def test_merge_proposal_keeps_original_capital_and_flatten_on_start():
    original = {
        "name": "bot_x", "capital_allocated": 500, "flatten_on_start": True, "warmup_candles": 50,
        "strategy": {"type": "scalp_dip", "lookback": 20, "dip_threshold_pct": 0.003},
        "risk": {"stop_loss_pct": 0.01},
    }
    proposed = {
        "strategy": {"type": "sma_cross", "short_window": 10, "long_window": 30},
        "risk": {"stop_loss_pct": 0.02},
        "trend_filter": {"enabled": True, "ema_period": 100},
    }
    merged = reoptimizer.merge_proposal_into_config(original, proposed)
    assert merged["capital_allocated"] == 500
    assert merged["flatten_on_start"] is True
    assert merged["warmup_candles"] == 50
    assert merged["strategy"] == proposed["strategy"]
    assert merged["risk"] == proposed["risk"]
    assert merged["trend_filter"] == proposed["trend_filter"]


def test_merge_proposal_preserves_custom_position_sizing():
    """Bug reel constate le 2026-09-12 : optimize.py genere toujours ses
    propositions avec max_position_size_pct=0.10 (constante du module, jamais
    variee entre candidats) et ne connait pas max_concurrent_positions (pas
    dans sa grille de recherche). Appliquer une proposition qui remplacerait
    tout le bloc `risk` ecrasait donc silencieusement un sizing choisi
    manuellement (ex: 0.45/3 positions releve pour mieux utiliser le panier
    commun) en le ramenant a 0.10/1 position par defaut."""
    original = {
        "name": "bot_x", "capital_allocated": 500,
        "strategy": {"type": "sma_cross", "short_window": 20, "long_window": 75},
        "risk": {
            "max_position_size_pct": 0.45, "stop_loss_pct": 0.05,
            "take_profit_pct": None, "max_daily_loss_pct": 0.05, "max_concurrent_positions": 3,
        },
    }
    proposed = {
        "strategy": {"type": "sma_cross", "short_window": 15, "long_window": 100},
        "risk": {"max_position_size_pct": 0.10, "stop_loss_pct": 0.02, "take_profit_pct": None, "max_daily_loss_pct": 0.05},
    }
    merged = reoptimizer.merge_proposal_into_config(original, proposed)
    assert merged["risk"]["max_position_size_pct"] == 0.45  # pas ecrase par le 0.10 de la proposition
    assert merged["risk"]["max_concurrent_positions"] == 3  # pas perdu (absent de la proposition)
    assert merged["risk"]["stop_loss_pct"] == 0.02  # ceci, en revanche, vient bien de la proposition


def test_merge_proposal_removes_trend_filter_and_atr_sizing_when_absent_from_proposal():
    original = {
        "name": "bot_x", "capital_allocated": 500,
        "strategy": {"type": "sma_cross", "short_window": 5, "long_window": 15},
        "risk": {},
        "trend_filter": {"enabled": True, "ema_period": 200},
        "atr_sizing": {"enabled": True, "atr_period": 14, "baseline_period": 100, "min_size_multiplier": 0.2},
    }
    proposed = {"strategy": {"type": "sma_cross", "short_window": 10, "long_window": 30}, "risk": {}}
    merged = reoptimizer.merge_proposal_into_config(original, proposed)
    assert "trend_filter" not in merged
    assert "atr_sizing" not in merged


def test_apply_proposal_files_errors_when_proposal_missing(isolated_proposals_dir):
    result = reoptimizer.apply_proposal_files("nonexistent_bot")
    assert result["status"] == "error"
    assert "introuvable" in result["error"]


def test_apply_proposal_files_errors_when_position_open(isolated_proposals_dir, monkeypatch, tmp_path):
    isolated_proposals_dir.mkdir(parents=True, exist_ok=True)
    (isolated_proposals_dir / "bot_x_proposal.json").write_text("{}", encoding="utf-8")
    (isolated_proposals_dir / "bot_x_proposed_config.yml").write_text(
        "strategy:\n  type: sma_cross\n  short_window: 10\n  long_window: 30\nrisk: {}\n", encoding="utf-8",
    )
    original_config_path = tmp_path / "bot_x.yml"
    original_config_path.write_text("name: bot_x\nstrategy:\n  type: sma_cross\nrisk: {}\n", encoding="utf-8")

    import tradingbot.control_server as control_server
    monkeypatch.setattr(control_server, "get_config_path_for_name", lambda name: original_config_path)
    monkeypatch.setattr(reoptimizer, "has_open_position", lambda name: True)

    result = reoptimizer.apply_proposal_files("bot_x")

    assert result["status"] == "error"
    assert "position" in result["error"]


def test_apply_proposal_files_merges_and_preserves_capital(isolated_proposals_dir, monkeypatch, tmp_path):
    isolated_proposals_dir.mkdir(parents=True, exist_ok=True)
    (isolated_proposals_dir / "bot_x_proposal.json").write_text("{}", encoding="utf-8")
    (isolated_proposals_dir / "bot_x_proposed_config.yml").write_text(
        "strategy:\n  type: sma_cross\n  short_window: 15\n  long_window: 100\n"
        "risk:\n  max_position_size_pct: 0.1\n  stop_loss_pct: 0.02\n  take_profit_pct: null\n  max_daily_loss_pct: 0.05\n"
        "trend_filter:\n  enabled: true\n  ema_period: 200\n",
        encoding="utf-8",
    )
    original_config_path = tmp_path / "bot_x.yml"
    original_config_path.write_text(
        "name: bot_x\ncapital_allocated: 500\nflatten_on_start: true\nwarmup_candles: 50\n"
        "strategy:\n  type: sma_cross\n  short_window: 10\n  long_window: 30\n"
        "risk:\n  max_position_size_pct: 0.1\n  stop_loss_pct: 0.02\n  take_profit_pct: null\n  max_daily_loss_pct: 0.05\n",
        encoding="utf-8",
    )

    import tradingbot.control_server as control_server
    monkeypatch.setattr(reoptimizer, "has_open_position", lambda name: False)
    monkeypatch.setattr(control_server, "get_config_path_for_name", lambda name: original_config_path)
    monkeypatch.setattr(control_server, "is_bot_running", lambda name: False)

    result = reoptimizer.apply_proposal_files("bot_x")

    assert result["status"] == "applied"
    assert result["relance"] is False
    merged = yaml.safe_load(original_config_path.read_text(encoding="utf-8"))
    assert merged["strategy"]["short_window"] == 15
    assert merged["capital_allocated"] == 500
    assert merged["trend_filter"] == {"enabled": True, "ema_period": 200}
    assert not (isolated_proposals_dir / "bot_x_proposal.json").exists()
    assert not (isolated_proposals_dir / "bot_x_proposed_config.yml").exists()


def test_apply_proposal_files_restarts_bot_if_it_was_running(isolated_proposals_dir, monkeypatch, tmp_path):
    isolated_proposals_dir.mkdir(parents=True, exist_ok=True)
    (isolated_proposals_dir / "bot_x_proposal.json").write_text("{}", encoding="utf-8")
    (isolated_proposals_dir / "bot_x_proposed_config.yml").write_text(
        "strategy:\n  type: sma_cross\n  short_window: 15\n  long_window: 100\nrisk: {}\n", encoding="utf-8",
    )
    original_config_path = tmp_path / "bot_x.yml"
    original_config_path.write_text(
        "name: bot_x\ncapital_allocated: 500\nstrategy:\n  type: sma_cross\n  short_window: 10\n  long_window: 30\nrisk: {}\n",
        encoding="utf-8",
    )

    import tradingbot.control_server as control_server
    kill_calls, launch_calls = [], []
    monkeypatch.setattr(reoptimizer, "has_open_position", lambda name: False)
    monkeypatch.setattr(control_server, "get_config_path_for_name", lambda name: original_config_path)
    monkeypatch.setattr(control_server, "is_bot_running", lambda name: True)
    monkeypatch.setattr(control_server, "kill_by_name", lambda name: kill_calls.append(name))
    monkeypatch.setattr(control_server, "launch_process", lambda path, name: launch_calls.append(name) or (True, ""))

    result = reoptimizer.apply_proposal_files("bot_x")

    assert result["status"] == "applied"
    assert result["relance"] is True
    assert kill_calls == ["bot_x"]
    assert launch_calls == ["bot_x"]


def test_run_all_applies_for_auto_group_and_leaves_control_group_alone(isolated_proposals_dir, monkeypatch, tmp_path):
    import tradingbot.control_server as control_server

    configs = [{"name": "bot_a"}, {"name": "bot_b"}]
    monkeypatch.setattr(control_server, "list_known_configs", lambda: configs)
    monkeypatch.setattr(control_server, "get_config_path_for_name", lambda name: tmp_path / f"{name}.yml")

    def fake_propose(config_path, now=None):
        return {"status": "proposed", "name": config_path.stem, "proposal": {}}

    applied = []

    def fake_apply(name):
        applied.append(name)
        return {"status": "applied", "name": name}

    monkeypatch.setattr(reoptimizer, "propose_reoptimization", fake_propose)
    monkeypatch.setattr(reoptimizer, "apply_proposal_files", fake_apply)
    reoptimizer.save_groups({"bot_a": "auto", "bot_b": "control"})

    results = reoptimizer.run_all()

    assert applied == ["bot_a"]
    groups_by_name = {r["name"]: r["group"] for r in results}
    assert groups_by_name == {"bot_a": "auto", "bot_b": "control"}
    control_result = next(r for r in results if r["name"] == "bot_b")
    assert "auto_applied" not in control_result


def test_run_all_skips_bots_with_unresolvable_config_path(isolated_proposals_dir, monkeypatch):
    import tradingbot.control_server as control_server

    configs = [{"name": "bot_missing"}]
    monkeypatch.setattr(control_server, "list_known_configs", lambda: configs)
    monkeypatch.setattr(control_server, "get_config_path_for_name", lambda name: None)

    results = reoptimizer.run_all()

    assert results == []


def _oscillating_candles(n=1000):
    closes = []
    price = 100.0
    for i in range(n):
        price += 2.0 if (i // 15) % 2 == 0 else -2.0
        closes.append(price)
    return [Candle(timestamp=i, open=c, high=c, low=c, close=c, volume=1.0) for i, c in enumerate(closes)]


@pytest.fixture
def isolated_proposals_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(reoptimizer, "PROPOSALS_DIR", tmp_path / "proposals")
    monkeypatch.setattr(reoptimizer, "STATE_FILE", tmp_path / "proposals" / "reoptimize_state.json")
    monkeypatch.setattr(reoptimizer, "GROUPS_FILE", tmp_path / "proposals" / "ab_test_groups.json")
    return tmp_path / "proposals"


def test_propose_reoptimization_skips_when_position_open(isolated_proposals_dir, monkeypatch):
    monkeypatch.setattr(reoptimizer, "has_open_position", lambda name: True)
    monkeypatch.setattr(reoptimizer, "fetch_historical_candles", lambda **kw: _oscillating_candles())
    config_path = isolated_proposals_dir.parent / "bot.yml"
    config_path.write_text(
        "name: bot_x\nsymbol: BTC/USDT\nstrategy:\n  type: sma_cross\n  short_window: 100\n  long_window: 200\nrisk: {}\n",
        encoding="utf-8",
    )

    result = reoptimizer.propose_reoptimization(config_path)

    assert result["status"] == "skipped"
    assert "position" in result["reason"]


def test_propose_reoptimization_skips_when_not_due(isolated_proposals_dir, monkeypatch):
    monkeypatch.setattr(reoptimizer, "has_open_position", lambda name: False)
    now = datetime.now(timezone.utc)
    reoptimizer.save_state({"bot_x": {"last_checked_at": now.isoformat()}})
    config_path = isolated_proposals_dir.parent / "bot.yml"
    config_path.write_text(
        "name: bot_x\nsymbol: BTC/USDT\nstrategy:\n  type: sma_cross\n  short_window: 100\n  long_window: 200\nrisk: {}\n",
        encoding="utf-8",
    )

    result = reoptimizer.propose_reoptimization(config_path, now=now)

    assert result["status"] == "skipped"
    assert "recente" in result["reason"]


def test_propose_reoptimization_requires_confirmation_before_writing_proposal(isolated_proposals_dir, monkeypatch):
    """Etape 6 (piste 3) : le meme candidat doit gagner 2 verifications
    hebdomadaires consecutives avant d'etre propose/applique - la premiere
    fois, il est seulement mis en attente de confirmation."""
    monkeypatch.setattr(reoptimizer, "has_open_position", lambda name: False)
    monkeypatch.setattr(reoptimizer, "fetch_historical_candles", lambda **kw: _oscillating_candles())
    config_path = isolated_proposals_dir.parent / "bot.yml"
    # Config actuelle deliberement absurde (fenetres enormes) : ne genere jamais assez de trades -> current_test = None.
    config_path.write_text(
        "name: bot_x\nsymbol: BTC/USDT\n"
        "strategy:\n  type: sma_cross\n  short_window: 900\n  long_window: 999\n"
        "risk: {max_position_size_pct: 0.1, stop_loss_pct: 0.02, take_profit_pct: null, max_daily_loss_pct: 0.05}\n",
        encoding="utf-8",
    )

    first_check = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = reoptimizer.propose_reoptimization(config_path, now=first_check)

    assert result["status"] == "pending_confirmation"
    assert not (isolated_proposals_dir / "bot_x_proposal.json").exists()
    state = reoptimizer.load_state()
    assert state["bot_x"]["pending_candidate"] == result["candidate"]

    second_check = first_check + timedelta(days=reoptimizer.REOPTIMIZE_INTERVAL_DAYS)
    result = reoptimizer.propose_reoptimization(config_path, now=second_check)

    assert result["status"] == "proposed"
    assert (isolated_proposals_dir / "bot_x_proposal.json").exists()
    assert (isolated_proposals_dir / "bot_x_proposed_config.yml").exists()
    proposal = json.loads((isolated_proposals_dir / "bot_x_proposal.json").read_text(encoding="utf-8"))
    assert proposal["current"]["test_return_pct"] is None
    assert proposal["proposed"]["test_return_pct"] is not None
    # Confirme : plus de confirmation en attente pour la prochaine amelioration.
    assert "pending_candidate" not in reoptimizer.load_state()["bot_x"]


def test_propose_reoptimization_clears_pending_confirmation_on_no_improvement(isolated_proposals_dir, monkeypatch):
    """Un candidat en attente de confirmation qui ne gagne plus la semaine
    suivante (ex: current config elle-meme reoptimisee entre-temps) ne doit
    pas rester bloque en attente indefiniment."""
    monkeypatch.setattr(reoptimizer, "has_open_position", lambda name: False)
    monkeypatch.setattr(reoptimizer, "fetch_historical_candles", lambda **kw: _oscillating_candles())
    config_path = isolated_proposals_dir.parent / "bot.yml"
    config_path.write_text(
        "name: bot_x\nsymbol: BTC/USDT\n"
        "strategy:\n  type: sma_cross\n  short_window: 900\n  long_window: 999\n"
        "risk: {max_position_size_pct: 0.1, stop_loss_pct: 0.02, take_profit_pct: null, max_daily_loss_pct: 0.05}\n",
        encoding="utf-8",
    )
    first_check = datetime(2026, 1, 1, tzinfo=timezone.utc)
    reoptimizer.propose_reoptimization(config_path, now=first_check)
    assert "pending_candidate" in reoptimizer.load_state()["bot_x"]

    # A partir de maintenant, plus aucun candidat ne bat la config actuelle.
    monkeypatch.setattr(reoptimizer, "is_better_out_of_sample", lambda current, candidate, min_margin=0.0: False)
    second_check = first_check + timedelta(days=reoptimizer.REOPTIMIZE_INTERVAL_DAYS)
    result = reoptimizer.propose_reoptimization(config_path, now=second_check)

    assert result["status"] == "no_improvement"
    assert "pending_candidate" not in reoptimizer.load_state()["bot_x"]


def test_propose_reoptimization_updates_state_even_when_no_improvement(isolated_proposals_dir, monkeypatch):
    """Le compteur de 'derniere verification' doit avancer meme si rien de
    mieux n'est trouve - sinon le garde-fou de frequence ne sert a rien (on
    re-testerait a chaque appel)."""
    monkeypatch.setattr(reoptimizer, "has_open_position", lambda name: False)
    monkeypatch.setattr(reoptimizer, "fetch_historical_candles", lambda **kw: _oscillating_candles())
    config_path = isolated_proposals_dir.parent / "bot.yml"
    config_path.write_text(
        "name: bot_x\nsymbol: BTC/USDT\nstrategy:\n  type: sma_cross\n  short_window: 100\n  long_window: 200\nrisk: {}\n",
        encoding="utf-8",
    )

    reoptimizer.propose_reoptimization(config_path)

    state = reoptimizer.load_state()
    assert "bot_x" in state
    assert state["bot_x"]["last_checked_at"] is not None


@pytest.mark.parametrize("status", ["skipped", "no_improvement", "pending_confirmation", "proposed"])
def test_print_result_handles_every_status_without_crashing(status, capsys):
    """Bug reel constate en ajoutant le statut 'pending_confirmation'
    (etape 6, piste 3) : _print_result supposait que seuls 'proposed' et
    'skipped'/'no_improvement' existaient, un statut non gere tombait dans
    le else et plantait sur result['proposal'] manquant."""
    result = {
        "name": "bot_x", "status": status, "reason": "test", "candidate": "sma_cross(court=10, long=30)",
        "current_test_return_pct": 0.01, "best_candidate_test_return_pct": 0.02,
        "proposal": {
            "current": {"description": "actuel", "test_return_pct": 0.01},
            "proposed": {"description": "propose", "test_return_pct": 0.02},
        },
    }
    reoptimizer._print_result(result)  # ne doit lever aucune exception
    assert capsys.readouterr().out.strip() != ""
