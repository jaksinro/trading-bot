import os

from tradingbot import control_server


def test_is_bot_running_false_without_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(control_server, "ROOT", tmp_path)
    assert control_server.is_bot_running("nope") is False


def test_is_bot_running_true_for_current_process(tmp_path, monkeypatch):
    monkeypatch.setattr(control_server, "ROOT", tmp_path)
    (tmp_path / "bot_myBot.lock").write_text(str(os.getpid()))
    assert control_server.is_bot_running("myBot") is True


def test_is_bot_running_false_for_dead_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(control_server, "ROOT", tmp_path)
    (tmp_path / "bot_myBot.lock").write_text("999999999")
    assert control_server.is_bot_running("myBot") is False


def test_list_known_configs_reads_yaml_fields(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "a.yml").write_text(
        "name: bot_a\nsymbol: BTC/USDT\ntimeframe: 1h\ncapital_allocated: 500\n"
        "strategy:\n  type: sma_cross\n"
    )
    monkeypatch.setattr(control_server, "ROOT", tmp_path)
    monkeypatch.setattr(control_server, "CONFIG_DIR", config_dir)

    configs = control_server.list_known_configs()

    assert len(configs) == 1
    assert configs[0]["name"] == "bot_a"
    assert configs[0]["symbol"] == "BTC/USDT"
    assert configs[0]["strategy_type"] == "sma_cross"
    assert configs[0]["running"] is False


def test_list_known_configs_skips_invalid_yaml(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "broken.yml").write_text(": : not valid yaml : :")
    monkeypatch.setattr(control_server, "ROOT", tmp_path)
    monkeypatch.setattr(control_server, "CONFIG_DIR", config_dir)

    assert control_server.list_known_configs() == []


def test_get_config_path_for_name_finds_file_with_mismatched_filename(tmp_path, monkeypatch):
    """Reproduit le bug reel : un fichier nomme differemment de son champ
    `name` interne doit quand meme etre trouve par son nom, pas par son nom
    de fichier - sinon une modification cree un second fichier en double."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "doge_scalp.yml").write_text("name: doge_scalp_v1\nsymbol: DOGE/USDT\n")
    monkeypatch.setattr(control_server, "CONFIG_DIR", config_dir)

    path = control_server.get_config_path_for_name("doge_scalp_v1")

    assert path == config_dir / "doge_scalp.yml"


def test_get_config_path_for_name_returns_none_when_absent(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(control_server, "CONFIG_DIR", config_dir)

    assert control_server.get_config_path_for_name("does_not_exist") is None


def test_get_config_for_name_uses_real_path(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "weird_filename.yml").write_text("name: my_bot\nsymbol: ETH/USDT\n")
    monkeypatch.setattr(control_server, "CONFIG_DIR", config_dir)

    cfg = control_server.get_config_for_name("my_bot")

    assert cfg["symbol"] == "ETH/USDT"


def test_remove_from_dashboard_registry_cleans_up_state_and_data_file(tmp_path, monkeypatch):
    monkeypatch.setattr(control_server, "ROOT", tmp_path)
    dashboard_data = tmp_path / "dashboard_data"
    dashboard_data.mkdir()
    (dashboard_data / "bot_a.js").write_text("window.BOT_INSTANCES = {};")
    (dashboard_data / "registry.state").write_text("bot_a\nbot_b")
    (dashboard_data / "registry.js").write_text('window.BOT_REGISTRY = ["bot_a", "bot_b"];')

    control_server.remove_from_dashboard_registry("bot_a")

    assert not (dashboard_data / "bot_a.js").exists()
    assert "bot_a" not in (dashboard_data / "registry.state").read_text()
    assert "bot_a" not in (dashboard_data / "registry.js").read_text()
    assert "bot_b" in (dashboard_data / "registry.state").read_text()


def test_list_proposals_empty_when_directory_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(control_server, "PROPOSALS_DIR", tmp_path / "proposals")
    assert control_server.list_proposals() == []


def test_list_proposals_reads_proposal_files(tmp_path, monkeypatch):
    proposals_dir = tmp_path / "proposals"
    proposals_dir.mkdir()
    (proposals_dir / "bot_x_proposal.json").write_text('{"name": "bot_x", "status": "proposed"}', encoding="utf-8")
    monkeypatch.setattr(control_server, "PROPOSALS_DIR", proposals_dir)

    proposals = control_server.list_proposals()

    assert len(proposals) == 1
    assert proposals[0]["name"] == "bot_x"


def test_list_proposals_skips_invalid_json(tmp_path, monkeypatch):
    proposals_dir = tmp_path / "proposals"
    proposals_dir.mkdir()
    (proposals_dir / "broken_proposal.json").write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(control_server, "PROPOSALS_DIR", proposals_dir)

    assert control_server.list_proposals() == []


def test_launch_process_detects_immediate_crash(tmp_path, monkeypatch):
    """Un bot qui plante au demarrage (ici : fichier de config inexistant)
    doit etre detecte au lieu de laisser une fenetre se fermer en silence."""
    monkeypatch.setattr(control_server, "ROOT", tmp_path)
    monkeypatch.setattr(control_server, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(control_server, "CRASH_CHECK_DELAY_SECONDS", 4.0)

    ok, error = control_server.launch_process(tmp_path / "does_not_exist.yml", "crash_test_bot")

    assert ok is False
    assert error != ""
