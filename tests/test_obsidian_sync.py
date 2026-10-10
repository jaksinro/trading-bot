"""Carte du trading bot dans Obsidian (EF-110)."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("obsidian_sync", ROOT / "scripts" / "obsidian_sync.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def test_builds_the_map_and_keeps_the_user_notes(tmp_path):
    base = tmp_path / sync.FOLDER
    base.mkdir()
    (base / "Mes idees.md").write_text("ma note", encoding="utf-8")
    counts = sync.build(tmp_path)
    assert counts["exigences"] >= 100 and counts["bots"] >= 1 and counts["strategies"] >= 10
    home = (base / f"{sync.FOLDER}.md").read_text(encoding="utf-8")
    assert "[[STB]]" in home and "[[Volume Profile]]" in home
    ef = next((base / "Exigences").glob("EF-109 *.md")).read_text(encoding="utf-8")
    assert "TradingView" in ef and "Conception (STC §3.96)" in ef
    stc = (base / "Documents" / "STC.md").read_text(encoding="utf-8")
    assert r"\|EF-20]]" in stc                      # lien dans un tableau : | echappe
    assert (base / "Mes idees.md").read_text(encoding="utf-8") == "ma note"
    again = sync.build(tmp_path)                       # mise a jour : memes notes, la note perso reste
    assert again["notes"] == counts["notes"] and (base / "Mes idees.md").exists()
    assert sum(1 for _ in base.rglob("*.md")) == counts["notes"] + 1


def test_note_names_are_valid_and_cut_on_whole_words():
    assert sync.safe("EF-1 : a/b *c* <d> | e") == "EF-1 a b c d e"
    assert sync.safe("un deux trois quatre", limit=12) == "un deux"


def test_links_requirements_outside_titles_and_code():
    notes = {"EF-07": "EF-07 Test"}
    text = "# Titre EF-07\nvoir EF-7 et EF-07\n```\nEF-07\n```\n| a | EF-07 |"
    out = sync.link_efs(text, notes).splitlines()
    assert out[0] == "# Titre EF-07" and out[3] == "EF-07"
    assert out[1] == "voir [[EF-07 Test|EF-07]] et [[EF-07 Test|EF-07]]"
    assert out[5] == r"| a | [[EF-07 Test\|EF-07]] |"


def test_default_vault_is_the_one_open_in_obsidian(tmp_path, monkeypatch):
    cfg = tmp_path / "obsidian"
    cfg.mkdir()
    (cfg / "obsidian.json").write_text(json.dumps({"vaults": {
        "a": {"path": "C:/coffre-ancien", "ts": 2}, "b": {"path": "C:/coffre-ouvert", "ts": 1, "open": True}}}))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert sync.default_vault() == Path("C:/coffre-ouvert")
