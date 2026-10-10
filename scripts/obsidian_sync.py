"""Carte du trading bot dans Obsidian (EF-110).

Demande de l'utilisateur (2026-10-10) : retrouver plus facilement tout ce qui
concerne le trading bot dans Obsidian. Ce script ecrit dans le coffre Obsidian
(par defaut celui ouvert dans Obsidian, lu dans %APPDATA%/obsidian/obsidian.json)
un dossier "Trading bot" :
- "Trading bot.md" : la page d'accueil, carte de tout le projet ;
- Documents/ : copies de STB, STC, manuel, feuille de route, README et consignes,
  ou chaque "EF-xx" devient un lien ;
- Exigences/ : une note par exigence (besoin de la STB + conception de la STC) ;
- Bots/ : une note par configuration de bot (reglages, strategie, journal) ;
- Strategies/ : une note par strategie (role, reglages, bots qui l'utilisent) ;
- Mesures/ : une note par banc de mesure (son protocole) ;
- "Code source.md" et "Scripts.md" : chaque fichier avec son role.

Les notes generees portent une marque en premiere ligne : une mise a jour
remplace celles-la seulement, jamais une note ecrite dans Obsidian. Les
fichiers du depot ne sont jamais modifies. A relancer apres un changement :
    python scripts/obsidian_sync.py [--vault "chemin du coffre"]
"""
from __future__ import annotations

import argparse
import ast
import inspect
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FOLDER = "Trading bot"
MARK = "<!-- genere par scripts/obsidian_sync.py : ecrase a chaque mise a jour, ne pas modifier ici -->"
EF_RE = re.compile(r"\bEF-(\d+)\b")
DOCS = {"STB.md": "STB", "STC.md": "STC", "MANUEL_UTILISATEUR.md": "Manuel utilisateur",
        "FEUILLE_DE_ROUTE_PERFORMANCE.md": "Feuille de route performance"}


# ------------------------------------------------------------------ outils
def default_vault() -> Path | None:
    """Coffre ouvert dans Obsidian (sinon le plus recent)."""
    cfg = Path(os.environ.get("APPDATA", "")) / "obsidian" / "obsidian.json"
    try:
        vaults = json.loads(cfg.read_text(encoding="utf-8")).get("vaults", {}).values()
    except (OSError, ValueError):
        return None
    vaults = sorted(vaults, key=lambda v: (bool(v.get("open")), v.get("ts", 0)), reverse=True)
    return Path(vaults[0]["path"]) if vaults else None


def safe(name: str, limit: int = 90) -> str:
    """Nom de note valide pour Obsidian et Windows."""
    name = re.sub(r"[\\/:*?\"<>|#^\[\]`]", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > limit:                      # coupe sur un mot entier
        name = name[:limit].rsplit(" ", 1)[0]
    return name.rstrip(" .,-")


def file_link(path: Path) -> str:
    """Lien qui ouvre le fichier du depot dans l'application par defaut."""
    return f"[`{path.relative_to(ROOT).as_posix()}`]({path.resolve().as_uri()})"


def header(source: str) -> str:
    return (f"{MARK}\n> [!info] Genere le {date.today().isoformat()} depuis {source}. "
            "Mise a jour : `python scripts/obsidian_sync.py`.\n\n")


def link_efs(text: str, notes: dict[str, str]) -> str:
    """Transforme chaque EF-xx en lien vers sa note (hors titres et blocs de code)."""
    out, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if fenced or line.startswith("#"):
            out.append(line)
            continue
        bar = "\\|" if line.lstrip().startswith("|") else "|"   # dans un tableau, le | du lien s'echappe
        out.append(EF_RE.sub(lambda m: f"[[{notes[ef]}{bar}{ef}]]" if (ef := f"EF-{int(m.group(1)):02d}") in notes
                             else m.group(0), line))
    return "\n".join(out)


def first_paragraph(doc: str | None, limit: int = 400) -> str:
    if not doc:
        return ""
    para = re.sub(r"\s+", " ", doc.strip().split("\n\n")[0]).replace("|", "/")
    return para if len(para) <= limit else para[:limit].rsplit(" ", 1)[0] + "..."


# ------------------------------------------------------------------ exigences
def stc_sections(stc: str) -> list[tuple[str, str, str]]:
    """(numero, titre, corps) de chaque section "### 3.x" de la STC."""
    sections, current = [], None
    for line in stc.splitlines():
        m = re.match(r"### (3\.\d+[a-z]?) +(.*)", line)
        if m or line.startswith("## ") or line.startswith("### "):
            if current:
                sections.append(current)
            current = (m.group(1), m.group(2).strip(), []) if m else None
            continue
        if current:
            current[2].append(line)
    if current:
        sections.append(current)
    return [(num, title, "\n".join(body).strip()) for num, title, body in sections]


def requirements(stb: str, stc: str) -> dict[str, dict]:
    reqs = {}
    for line in stb.splitlines():
        if line.startswith("| EF-"):
            cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
            ef = f"EF-{int(cells[0][3:]):02d}"
            reqs[ef] = {"id": ef, "need": cells[1] if len(cells) > 1 else "",
                        "status": cells[2] if len(cells) > 2 else "", "sections": []}
    for num, title, body in stc_sections(stc):
        for raw in dict.fromkeys(EF_RE.findall(title)):
            ef = f"EF-{int(raw):02d}"
            if ef in reqs:
                reqs[ef]["sections"].append((num, title, body))
    for r in reqs.values():
        if r["sections"]:
            t = r["sections"][0][1]
            t = re.sub(r"^(EF-\d+[\s,/et]*)+:?\s*", "", t)          # "EF-109 : profil..." -> "profil..."
            t = re.sub(r"\s*\((EF-\d+[,\s]*)+\)", "", t)            # "(EF-18)" en fin de titre
        else:
            t = re.split(r"(?<=[a-z]) - |[.;(]", r["need"])[0]
            t = re.sub(r"^(Le syst[eè]me|Le bot|Chaque bot|L'utilisateur|Un bot) (doit|devrait|peut|ne doit)"
                       r"( pouvoir| permettre de| permettre d')? ?", "", t)
            t = t[:1].upper() + t[1:]
        r["title"] = safe(t, 70) or r["id"]
        r["note"] = safe(f"{r['id']} {r['title']}")
    return reqs


def status_short(status: str) -> str:
    return re.sub(r"\*\*", "", status).split(". ")[0][:60].replace("|", "/")


# ------------------------------------------------------------------ generation
def build(vault: Path) -> dict[str, int]:
    base = vault / FOLDER
    notes: dict[str, str] = {}                 # chemin relatif -> contenu
    counts = {}

    stb = (ROOT / "docs" / "STB.md").read_text(encoding="utf-8")
    stc = (ROOT / "docs" / "STC.md").read_text(encoding="utf-8")
    reqs = requirements(stb, stc)
    ef_notes = {ef: r["note"] for ef, r in reqs.items()}

    # Documents
    doc_names = {}
    for path in sorted((ROOT / "docs").glob("*.md")):
        name = DOCS.get(path.name, safe(path.stem.replace("_", " ").capitalize()))
        doc_names[path.name] = name
        notes[f"Documents/{name}.md"] = header(f"`docs/{path.name}`") + link_efs(path.read_text(encoding="utf-8"), ef_notes)
    for src, name in (("README.md", "README"), ("CLAUDE.md", "Consignes de collaboration")):
        if (ROOT / src).exists():
            doc_names[src] = name
            notes[f"Documents/{name}.md"] = header(f"`{src}`") + link_efs((ROOT / src).read_text(encoding="utf-8"), ef_notes)
    counts["documents"] = len(doc_names)

    # Exigences
    for r in reqs.values():
        body = [header("`docs/STB.md` et `docs/STC.md`"), f"# {r['id']} - {r['title']}\n",
                f"**Statut** : {r['status']}\n", "## Besoin (STB)\n", r["need"] + "\n"]
        for num, title, text in r["sections"]:
            body += [f"## Conception (STC §{num})\n", f"*{title}*\n", text + "\n"]
        if not r["sections"]:
            body.append("*Pas de section dediee dans la STC.*\n")
        body.append(f"\nVoir aussi : [[STB]] - [[STC]] - [[{FOLDER}|accueil]]\n")
        notes[f"Exigences/{r['note']}.md"] = link_efs("\n".join(body), ef_notes)
    counts["exigences"] = len(reqs)

    # Strategies et bots
    from tradingbot.backtest_view import STRATEGIES, strategy_params
    from tradingbot.run_backtest import STRATEGY_REGISTRY

    labels = {k: safe(v[0]) for k, v in STRATEGIES.items()}
    for key in STRATEGY_REGISTRY:
        labels.setdefault(key, safe(key.replace("_", " ").capitalize()))
    bots = []
    for path in sorted((ROOT / "config").rglob("*.yml")):
        try:
            cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            cfg = {}
        bots.append((path, cfg if isinstance(cfg, dict) else {}))
    for key, cls in STRATEGY_REGISTRY.items():
        label = labels.get(key, safe(key))
        module = inspect.getmodule(cls)
        mod_path = Path(module.__file__)
        users = [p.stem for p, cfg in bots if (cfg.get("strategy") or {}).get("type") == key]
        lines = [header(f"`{mod_path.relative_to(ROOT).as_posix()}`"), f"# {label}\n",
                 f"Type dans les configs : `{key}` - code : {file_link(mod_path)}\n",
                 (STRATEGIES[key][1] + "\n") if key in STRATEGIES else ""]
        if users:
            lines.append("**Bots qui l'utilisent** : " + ", ".join(f"[[{u}]]" for u in users) + "\n")
        try:
            params = strategy_params(key)
        except Exception:  # noqa: BLE001 - une strategie sans reglages introspectables reste listee
            params = []
        if params:
            lines += ["## Reglages\n", "| Reglage | Nom | Defaut |", "|---|---|---|"]
            lines += [f"| {p['label']} | `{p['name']}` | `{p['default']}` |" for p in params]
            lines.append("")
        if module.__doc__:
            lines += ["## Fonctionnement (documentation du code)\n", module.__doc__.strip() + "\n"]
        notes[f"Strategies/{label}.md"] = link_efs("\n".join(lines), ef_notes)
    counts["strategies"] = len(STRATEGY_REGISTRY)

    for path, cfg in bots:
        stype = (cfg.get("strategy") or {}).get("type")
        log = ROOT / "logs" / f"{cfg.get('name', path.stem)}.log"
        lines = [header(f"`{path.relative_to(ROOT).as_posix()}`"), f"# {path.stem}\n",
                 "| | |", "|---|---|",
                 f"| Marche | {cfg.get('symbol', '-')} ({cfg.get('exchange', '-')}) |",
                 f"| Unite de temps | {cfg.get('timeframe', '-')} |",
                 f"| Strategie | {'[[' + labels[stype] + ']]' if stype in labels else (stype or '-')} |",
                 f"| Capital alloue | {cfg.get('capital_allocated', '-')} |",
                 f"| Surveillance des sorties | {cfg.get('exit_check_timeframe') or 'non'} |",
                 f"| Configuration | {file_link(path)} |"]
        if log.exists():
            lines.append(f"| Journal | {file_link(log)} |")
        lines += ["", "Pilotage : [dashboard](http://localhost:8765/dashboard.html) - "
                  "[atelier de backtest](http://localhost:8765/backtest.html)\n",
                  "## Configuration complete\n", "```yaml", path.read_text(encoding="utf-8").rstrip(), "```"]
        notes[f"Bots/{path.stem}.md"] = header(f"`{path.relative_to(ROOT).as_posix()}`") + "\n".join(lines[1:]) + "\n"
    counts["bots"] = len(bots)

    # Mesures (bancs) et scripts
    script_rows = []
    for path in sorted((ROOT / "scripts").glob("*.*")):
        if path.suffix not in (".py", ".ps1", ".sh"):
            continue
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) if path.suffix == ".py" else None
        if path.name.startswith("bench_") and doc:
            notes[f"Mesures/{path.stem}.md"] = link_efs(
                header(f"`scripts/{path.name}`") + f"# {path.stem}\n\n{file_link(path)}\n\n{doc}\n", ef_notes)
            script_rows.append(f"| [[{path.stem}]] | {first_paragraph(doc, 200)} |")
        else:
            script_rows.append(f"| {file_link(path)} | {first_paragraph(doc, 200) or '-'} |")
    notes["Scripts.md"] = link_efs(header("`scripts/`") + "# Scripts et bancs de mesure\n\n| Fichier | Role |\n|---|---|\n"
                                   + "\n".join(script_rows) + "\n", ef_notes)
    counts["mesures"] = sum(1 for k in notes if k.startswith("Mesures/"))

    # Code source
    rows, current = [], None
    for path in sorted((ROOT / "src" / "tradingbot").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        package = path.parent.relative_to(ROOT / "src").as_posix()
        if package != current:
            rows += [f"\n## {package}\n", "| Fichier | Role |", "|---|---|"]
            current = package
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
        rows.append(f"| {file_link(path)} | {first_paragraph(doc, 300) or '-'} |")
    tests = len(list((ROOT / "tests").glob("test_*.py")))
    notes["Code source.md"] = link_efs(header("`src/tradingbot/`") + "# Code source\n\nChaque module et son role "
                                       f"(premier paragraphe de sa documentation). Tests : {tests} fichiers dans "
                                       f"`tests/`.\n" + "\n".join(rows) + "\n", ef_notes)

    # Accueil
    home = [header("tout le depot"), "# Trading bot\n",
            "Bot de trading crypto developpe en cycle en V. Cette page est la carte du projet.\n",
            "## Documents\n",
            "- [[STB]] : le besoin et les exigences", "- [[STC]] : la conception et les mesures",
            "- [[Manuel utilisateur]] : le dashboard et l'atelier, pour l'utilisateur",
            "- [[Feuille de route performance]]", "- [[README]] - [[Consignes de collaboration]]",
            "- Pilotage : [dashboard](http://localhost:8765/dashboard.html) - "
            "[atelier de backtest](http://localhost:8765/backtest.html)\n",
            "## Bots\n"]
    for path, cfg in bots:
        stype = (cfg.get("strategy") or {}).get("type")
        what = ("[[" + labels[stype] + "]]" if stype in labels else stype
                or ("investissement regulier (DCA)" if "dca" in path.parts else "configuration"))
        market = " ".join(str(x) for x in (cfg.get("symbol"), cfg.get("timeframe")) if x)
        home.append(f"- [[{path.stem}]] - {market + ', ' if market else ''}{what}")
    home += ["\n## Strategies\n"] + [f"- [[{labels.get(k, safe(k))}]] (`{k}`)" for k in STRATEGY_REGISTRY]
    home += ["\n## Mesures et outils\n", "- [[Scripts]] : scripts et bancs de mesure"]
    home += [f"- [[{k[8:-3]}]]" for k in sorted(notes) if k.startswith("Mesures/")]
    home += ["- [[Code source]] : chaque module et son role\n", "## Exigences\n",
             "| Exigence | Sujet | Statut |", "|---|---|---|"]
    for ef in sorted(reqs, key=lambda e: int(e[3:]), reverse=True):
        r = reqs[ef]
        home.append(f"| [[{r['note']}\\|{ef}]] | {r['title']} | {status_short(r['status'])} |")
    notes[f"{FOLDER}.md"] = "\n".join(home) + "\n"

    # Ecriture : seules les anciennes notes generees sont remplacees
    if base.exists():
        for old in base.rglob("*.md"):
            try:
                generated = old.read_text(encoding="utf-8").startswith(MARK)
            except (OSError, UnicodeDecodeError):
                generated = False
            if generated:
                old.unlink()
    for rel, content in notes.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content if content.startswith(MARK) else MARK + "\n" + content, encoding="utf-8")
    counts["notes"] = len(notes)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Carte du trading bot dans un coffre Obsidian")
    parser.add_argument("--vault", help="dossier du coffre Obsidian (defaut : celui ouvert dans Obsidian)")
    args = parser.parse_args()
    vault = Path(args.vault) if args.vault else default_vault()
    if vault is None or not vault.is_dir():
        sys.exit("Coffre Obsidian introuvable : ouvre Obsidian une fois, ou passe --vault \"chemin\".")
    counts = build(vault)
    print(f"{counts['notes']} notes ecrites dans {vault / FOLDER} : {counts['documents']} documents, "
          f"{counts['exigences']} exigences, {counts['bots']} bots, {counts['strategies']} strategies, "
          f"{counts['mesures']} bancs, code source et scripts.")


if __name__ == "__main__":
    main()
