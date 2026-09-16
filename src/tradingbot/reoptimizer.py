"""Bot d'auto-reoptimisation periodique (feuille de route performance,
etape 5). Reutilise integralement `optimize.py` (grille de parametres +
validation out-of-sample) pour verifier, de temps en temps, si une instance
existante pourrait etre amelioree.

SEMI-AUTOMATIQUE PAR CONCEPTION (pas une option, un garde-fou) :
- Un nouveau candidat ne remplace l'ancien que s'il bat la config ACTUELLE
  sur la periode de validation out-of-sample - jamais juste "le meilleur du
  jour" (`is_better_out_of_sample`).
- Frequence d'AU PLUS une fois par semaine par instance (7 jours,
  `REOPTIMIZE_INTERVAL_DAYS`) pour laisser accumuler de vraies donnees live
  entre deux verifications (`is_due_for_reoptimization`).
- Ne reoptimise jamais une instance qui a une position ouverte
  (`has_open_position`), coherent avec CT-10 de la STB (le cash reconstruit
  au redemarrage deviendrait incoherent sinon).
- Chaque proposition est ecrite dans `proposals/{nom}_proposal.json` (+ une
  config YAML prete a l'emploi).

GROUPE A/B (test d'efficacite, feuille de route performance) : chaque bot
connu est assigne de facon stable a un groupe "auto" ou "control"
(`assign_groups`, repartition equilibree, jamais reassigne une fois choisi) :
- groupe "control" : la proposition est generee mais JAMAIS appliquee - sert
  de reference pour mesurer si la reoptimisation change reellement quelque
  chose.
- groupe "auto" : une proposition trouvee est appliquee IMMEDIATEMENT
  (`apply_proposal_files`), sans validation humaine - c'est le sens du test :
  mesurer l'effet reel de l'auto-reoptimisation sur la moitie des bots. Les
  memes garde-fous (out-of-sample, position ouverte) s'appliquent quand meme.

`run_all()` traite tous les bots connus en une fois (utilise par le bouton
dashboard "Lancer la reoptimisation de tous les bots" et par `--all`).

Usage:
    python -m tradingbot.reoptimizer --name mon_bot
    python -m tradingbot.reoptimizer --all
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from tradingbot.optimize import (
    SINCE_YEARS,
    STARTING_CAPITAL,
    TIMEFRAME,
    TOP_N_FOR_VALIDATION,
    BacktestResult,
    Candidate,
    _since_iso,
    build_mean_reversion_candidates,
    build_scalp_dip_candidates,
    build_sma_cross_candidates,
    compute_window_consistency,
    format_candidate,
    result_to_config_yaml,
    run_one_backtest,
    split_train_test,
)
from tradingbot.data_feed import fetch_historical_candles

REOPTIMIZE_INTERVAL_DAYS = 7  # au plus une fois par semaine par instance

# Etape 6 (feuille de route performance) : une simulation retrospective a
# montre que le garde-fou "candidat > actuel" acceptait des ecarts minuscules
# (parfois < 0,1 point de validation) qui n'etaient que du bruit statistique
# lie au deplacement de la fenetre glissante d'une semaine sur l'autre - un
# changement applique sur un tel ecart a degrade la performance forward reelle
# dans 3 cas sur 5 observes (voir docs/FEUILLE_DE_ROUTE_PERFORMANCE.md etape 6).
# Une marge minimale reduit ce "config-shopping" sans bloquer un vrai
# changement de regime (qui produit generalement un ecart plus large).
MIN_IMPROVEMENT_MARGIN = 0.005  # 0,5 point de pourcentage de rendement de validation

PROPOSALS_DIR = Path("proposals")
STATE_FILE = PROPOSALS_DIR / "reoptimize_state.json"
GROUPS_FILE = PROPOSALS_DIR / "ab_test_groups.json"


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict) -> None:
    PROPOSALS_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_groups() -> dict:
    if not GROUPS_FILE.exists():
        return {}
    try:
        return json.loads(GROUPS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_groups(groups: dict) -> None:
    PROPOSALS_DIR.mkdir(exist_ok=True)
    GROUPS_FILE.write_text(json.dumps(groups, indent=2, sort_keys=True), encoding="utf-8")


def assign_groups(names: list[str]) -> dict:
    """Assignation stable et equilibree : un bot deja assigne GARDE son
    groupe (sinon le test A/B n'a plus de sens - un bot changerait de
    groupe a chaque execution). Les nouveaux bots sont repartis en
    alternance pour equilibrer les deux groupes au fil des ajouts. Les
    bots supprimes sont retires de l'etat persiste."""
    groups = load_groups()
    groups = {name: group for name, group in groups.items() if name in names}

    unassigned = sorted(name for name in names if name not in groups)
    n_auto = sum(1 for g in groups.values() if g == "auto")
    n_control = sum(1 for g in groups.values() if g == "control")
    for name in unassigned:
        if n_auto <= n_control:
            groups[name] = "auto"
            n_auto += 1
        else:
            groups[name] = "control"
            n_control += 1

    save_groups(groups)
    return groups


def is_due_for_reoptimization(
    last_checked_iso: str | None, now: datetime, interval_days: int = REOPTIMIZE_INTERVAL_DAYS
) -> bool:
    """Jamais verifie -> toujours du. Sinon, seulement apres `interval_days`
    depuis la derniere verification (peu importe qu'elle ait produit une
    proposition ou non) - c'est le garde-fou anti-"config-shopping"."""
    if last_checked_iso is None:
        return True
    last_checked = datetime.fromisoformat(last_checked_iso)
    return (now - last_checked) >= timedelta(days=interval_days)


def has_open_position(instance_name: str) -> bool:
    """Ne reoptimise jamais une instance a position ouverte (CT-10 de la
    STB) - importe localement pour eviter un cycle d'import avec
    reporting.logger au chargement du module."""
    from tradingbot.reporting.logger import TradeLogger

    logger = TradeLogger(instance_name)
    try:
        return len(logger.load_open_positions()) > 0
    finally:
        logger.close()


def is_better_out_of_sample(
    current: BacktestResult | None, candidate: BacktestResult | None, min_margin: float = MIN_IMPROVEMENT_MARGIN
) -> bool:
    """Le coeur du garde-fou : un candidat ne devient une proposition QUE
    s'il bat la config actuelle sur la performance de VALIDATION (jamais vue
    pendant la recherche), jamais sur sa seule performance d'entrainement.
    `min_margin` (etape 6) exige un ecart minimal, pas juste "strictement
    superieur" - un candidat qui ne gagne que par bruit statistique ne doit
    pas declencher un changement reel."""
    if candidate is None:
        return False
    if current is None:
        return True  # la config actuelle n'a meme pas assez de trades pour etre evaluee equitablement
    return candidate.total_return_pct > current.total_return_pct + min_margin


MIN_WINDOW_CONSISTENCY = 0.5  # etape 6, piste 5 : au moins la moitie des sous-fenetres positives


def is_consistent_across_windows(
    test_candles: list, candidate: Candidate, min_consistency: float = MIN_WINDOW_CONSISTENCY
) -> bool:
    """Etape 6 (piste 5) : refuse un candidat dont la performance sur la
    periode de validation vient d'une seule sous-fenetre chanceuse plutot
    que d'un comportement consistant a travers plusieurs regimes de marche
    distincts. Permissif (True) si aucune sous-fenetre n'a assez de trades
    pour juger (donnee manquante, pas preuve negative)."""
    _, consistency = compute_window_consistency(test_candles, candidate)
    if consistency is None:
        return True
    return consistency >= min_consistency


def has_edge_over_benchmark(result: BacktestResult | None) -> bool:
    """Etape 6 : refuse un candidat qui ne bat la config actuelle que parce
    que le marche est monte, pas parce que la strategie a un edge reel -
    sans ce filtre, "le meilleur candidat" peut n'etre qu'un buy & hold
    deguise avec des frais de transaction en plus. Permissif (True) si le
    benchmark n'a pas pu etre mesure (periode trop courte) : on ne bloque
    pas sur une donnee manquante, seulement sur une preuve negative
    explicite (`beats_benchmark is False`)."""
    if result is None:
        return False
    if result.beats_benchmark is None:
        return True
    return result.beats_benchmark


def candidate_from_config(config: dict) -> Candidate:
    """Reconstruit un Candidate a partir d'une config YAML deployee, pour
    pouvoir la backtester avec exactement le meme decoupage train/test que
    les nouveaux candidats - comparaison equitable, pas un chiffre recycle
    d'un ancien rapport."""
    strategy = dict(config["strategy"])
    strategy_type = strategy.pop("type")
    risk = config.get("risk") or {}
    trend_filter_cfg = config.get("trend_filter") or {}
    trend_filter_ema_period = trend_filter_cfg.get("ema_period") if trend_filter_cfg.get("enabled") else None
    atr_sizing_cfg = config.get("atr_sizing") or {}
    atr_sizing_enabled = bool(atr_sizing_cfg.get("enabled"))
    return Candidate(
        strategy_type=strategy_type,
        params=strategy,
        risk={
            "max_position_size_pct": risk.get("max_position_size_pct", 0.10),
            "stop_loss_pct": risk.get("stop_loss_pct", 0.02),
            "take_profit_pct": risk.get("take_profit_pct"),
            "max_daily_loss_pct": risk.get("max_daily_loss_pct", 0.05),
        },
        trend_filter_ema_period=trend_filter_ema_period,
        atr_sizing_enabled=atr_sizing_enabled,
    )


def _search_best_out_of_sample(train_candles: list, test_candles: list, symbol: str) -> tuple[BacktestResult | None, BacktestResult | None]:
    """Reprend la methodologie de `optimize.py` (grille + validation
    out-of-sample) pour une seule paire, et retourne (train, test) du
    MEILLEUR candidat sur la performance de validation."""
    all_candidates = build_sma_cross_candidates() + build_scalp_dip_candidates() + build_mean_reversion_candidates()
    train_results = []
    for candidate in all_candidates:
        result = run_one_backtest(train_candles, candidate)
        if result is not None:
            result.symbol = symbol
            train_results.append(result)
    train_results.sort(key=lambda r: r.risk_adjusted_return, reverse=True)

    best_train, best_test = None, None
    for train_result in train_results[:TOP_N_FOR_VALIDATION]:
        test_result = run_one_backtest(test_candles, train_result.candidate)
        if test_result is None:
            continue
        test_result.symbol = symbol
        if best_test is None or test_result.risk_adjusted_return > best_test.risk_adjusted_return:
            best_train, best_test = train_result, test_result
    return best_train, best_test


def propose_reoptimization(config_path: Path, now: datetime | None = None) -> dict:
    """Point d'entree principal pour UNE instance. Retourne un dict
    `status` : 'skipped' (pas encore l'heure, ou position ouverte),
    'no_improvement' (rien de mieux trouve) ou 'proposed' (fichier de
    proposition ecrit)."""
    now = now or datetime.now(timezone.utc)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    name = config["name"]
    symbol = config["symbol"]

    state = load_state()
    last_checked_iso = state.get(name, {}).get("last_checked_at")
    if not is_due_for_reoptimization(last_checked_iso, now):
        return {"status": "skipped", "reason": "derniere verification trop recente", "name": name}

    if has_open_position(name):
        return {"status": "skipped", "reason": "position ouverte, nouvelle tentative au prochain cycle", "name": name}

    candles = fetch_historical_candles(
        exchange_id="binance", symbol=symbol, timeframe=TIMEFRAME, since_iso=_since_iso(SINCE_YEARS)
    )
    train_candles, test_candles = split_train_test(candles)

    current_candidate = candidate_from_config(config)
    current_test = run_one_backtest(test_candles, current_candidate)

    best_train, best_test = _search_best_out_of_sample(train_candles, test_candles, symbol)
    previously_pending = state.get(name, {}).get("pending_candidate")

    consistent = best_test is not None and is_consistent_across_windows(test_candles, best_test.candidate)
    if not is_better_out_of_sample(current_test, best_test) or not has_edge_over_benchmark(best_test) or not consistent:
        state[name] = {"last_checked_at": now.isoformat()}  # efface toute confirmation en attente
        save_state(state)
        return {
            "status": "no_improvement", "name": name,
            "current_test_return_pct": current_test.total_return_pct if current_test else None,
            "best_candidate_test_return_pct": best_test.total_return_pct if best_test else None,
        }

    # Etape 6 (piste 3) : une simulation retrospective a montre qu'un
    # candidat peut battre la config actuelle a un check donne sans que ce
    # signal survive a la semaine suivante (bruit lie au deplacement de la
    # fenetre glissante). On exige donc que LE MEME candidat gagne deux
    # verifications hebdomadaires CONSECUTIVES avant de le proposer/appliquer
    # - un vrai changement de regime persiste d'une semaine sur l'autre, un
    # artefact statistique ponctuel non.
    candidate_key = format_candidate(best_test.candidate)
    if previously_pending != candidate_key:
        state[name] = {"last_checked_at": now.isoformat(), "pending_candidate": candidate_key}
        save_state(state)
        return {
            "status": "pending_confirmation", "name": name, "candidate": candidate_key,
            "current_test_return_pct": current_test.total_return_pct if current_test else None,
            "best_candidate_test_return_pct": best_test.total_return_pct,
        }

    state[name] = {"last_checked_at": now.isoformat()}  # confirme : la prochaine amelioration repart de zero
    save_state(state)

    PROPOSALS_DIR.mkdir(exist_ok=True)
    proposed_config_yaml = result_to_config_yaml(best_test, name)
    proposal = {
        "name": name,
        "generated_at": now.isoformat(),
        "current": {
            "description": format_candidate(current_candidate),
            "test_return_pct": current_test.total_return_pct if current_test else None,
        },
        "proposed": {
            "description": format_candidate(best_test.candidate),
            "train_return_pct": best_train.total_return_pct if best_train else None,
            "test_return_pct": best_test.total_return_pct,
            "test_drawdown_pct": best_test.max_drawdown_pct,
            "test_num_trades": best_test.num_trades,
        },
    }
    (PROPOSALS_DIR / f"{name}_proposal.json").write_text(json.dumps(proposal, indent=2), encoding="utf-8")
    (PROPOSALS_DIR / f"{name}_proposed_config.yml").write_text(proposed_config_yaml, encoding="utf-8")

    return {"status": "proposed", "name": name, "proposal": proposal}



# `optimize.py` ne fait JAMAIS varier ces champs entre candidats (valeurs
# constantes du module : MAX_POSITION_SIZE_PCT, MAX_DAILY_LOSS_PCT) - ce ne
# sont pas des parametres de strategie "optimises", ce sont des decisions
# d'allocation de capital prises separement pour cette instance (voir STC
# section 3.5 revisee, panier commun). Une proposition ne doit donc jamais
# les ecraser, sous peine de defaire silencieusement un reglage de sizing
# choisi manuellement (bug reel constate le 2026-09-12 : une application
# automatique a fait retomber max_position_size_pct de 0.15 a 0.10 et a fait
# disparaitre max_concurrent_positions, qui n'existe meme pas dans la grille
# de recherche de optimize.py).
RISK_KEYS_FROM_PROPOSAL = {"stop_loss_pct", "take_profit_pct"}


def merge_proposal_into_config(original_config: dict, proposed_config: dict) -> dict:
    """Ne prend du fichier propose que la strategie, le filtre de tendance,
    le sizing ATR, et les seuils de sortie (`stop_loss_pct`/`take_profit_pct`)
    reellement varies par la grille de `optimize.py` - le capital alloue, le
    sizing de position (`max_position_size_pct`, `max_concurrent_positions`
    et tout autre champ de risque non liste dans RISK_KEYS_FROM_PROPOSAL), le
    rechauffement et flatten_on_start restent ceux DEJA choisis par
    l'utilisateur pour cette instance (une proposition ne doit jamais changer
    le budget alloue ni la maniere dont il est deploye)."""
    merged = dict(original_config)
    merged["strategy"] = proposed_config["strategy"]
    merged["risk"] = {
        **original_config.get("risk", {}),
        **{k: v for k, v in proposed_config["risk"].items() if k in RISK_KEYS_FROM_PROPOSAL},
    }
    for optional_key in ("trend_filter", "atr_sizing"):
        if optional_key in proposed_config:
            merged[optional_key] = proposed_config[optional_key]
        else:
            merged.pop(optional_key, None)
    return merged


def apply_proposal_files(name: str) -> dict:
    """Applique une proposition deja ecrite sur disque : fusionne dans la
    config existante, redemarre le bot s'il tournait, puis efface les
    fichiers de proposition. Reutilise par `control_server` (application
    manuelle via le dashboard) ET par `run_all` (application automatique du
    groupe "auto"). Revérifie l'absence de position ouverte au moment
    d'appliquer (CT-10) - l'etat a pu changer depuis que la proposition a
    ete generee."""
    from tradingbot.control_server import get_config_path_for_name, is_bot_running, kill_by_name, launch_process

    proposal_path = PROPOSALS_DIR / f"{name}_proposal.json"
    proposed_config_path = PROPOSALS_DIR / f"{name}_proposed_config.yml"
    if not proposal_path.is_file() or not proposed_config_path.is_file():
        return {"status": "error", "error": "proposition introuvable", "name": name}

    original_path = get_config_path_for_name(name)
    if original_path is None:
        return {"status": "error", "error": "bot introuvable", "name": name}

    if has_open_position(name):
        return {"status": "error", "error": "position ouverte", "name": name}

    original_config = yaml.safe_load(original_path.read_text(encoding="utf-8")) or {}
    proposed_config = yaml.safe_load(proposed_config_path.read_text(encoding="utf-8")) or {}
    merged_config = merge_proposal_into_config(original_config, proposed_config)

    was_running = is_bot_running(name)
    if was_running:
        kill_by_name(name)
        time.sleep(0.5)

    original_path.write_text(yaml.safe_dump(merged_config, allow_unicode=True, sort_keys=False), encoding="utf-8")

    if was_running:
        ok, error = launch_process(original_path, name)
        if not ok:
            return {"status": "error", "error": f"config appliquee, mais redemarrage echoue : {error}", "name": name}

    proposal_path.unlink(missing_ok=True)
    proposed_config_path.unlink(missing_ok=True)
    return {"status": "applied", "name": name, "relance": was_running}


def run_all(now: datetime | None = None) -> list[dict]:
    """Traite tous les bots connus en une fois : genere une proposition pour
    chacun (respecte les memes garde-fous que `propose_reoptimization`), et
    applique IMMEDIATEMENT celles du groupe "auto" (test A/B - voir
    docstring du module). Le groupe "control" recoit les memes propositions
    mais ne les applique jamais - sert de reference."""
    from tradingbot.control_server import get_config_path_for_name, list_known_configs

    configs = list_known_configs()
    names = [c["name"] for c in configs]
    groups = assign_groups(names)

    results = []
    for c in configs:
        name = c["name"]
        group = groups.get(name, "control")
        config_path = get_config_path_for_name(name)
        if config_path is None:
            continue

        result = propose_reoptimization(config_path, now=now)
        result["group"] = group

        if result["status"] == "proposed" and group == "auto":
            result["auto_applied"] = apply_proposal_files(name)

        results.append(result)

    return results


def main(name: str | None, run_all_bots: bool) -> None:
    if run_all_bots:
        results = run_all()
        for result in results:
            _print_result(result)
        return

    from tradingbot.control_server import get_config_path_for_name

    config_path = get_config_path_for_name(name)
    if config_path is None:
        print(f"Erreur : bot '{name}' introuvable.", file=sys.stderr)
        sys.exit(1)

    result = propose_reoptimization(config_path)
    _print_result(result)


def _print_result(result: dict) -> None:
    name = result["name"]
    status = result["status"]
    group_note = f" [groupe {result['group']}]" if "group" in result else ""
    if status == "skipped":
        print(f"{name}{group_note} : verification ignoree ({result['reason']}).")
    elif status == "no_improvement":
        print(
            f"{name}{group_note} : aucune amelioration trouvee (actuel={result['current_test_return_pct']}, "
            f"meilleur candidat={result['best_candidate_test_return_pct']})."
        )
    elif status == "pending_confirmation":
        print(
            f"{name}{group_note} : candidat {result['candidate']} en attente de confirmation "
            f"(devra encore gagner la prochaine verification hebdomadaire avant d'etre propose)."
        )
    else:
        p = result["proposal"]
        print(f"{name}{group_note} : proposition ecrite dans proposals/{name}_proposal.json")
        print(f"  Actuel   : {p['current']['description']} -> validation {p['current']['test_return_pct']}")
        print(f"  Propose  : {p['proposed']['description']} -> validation {p['proposed']['test_return_pct']}")
        if "auto_applied" in result:
            applied = result["auto_applied"]
            if applied["status"] == "applied":
                print("  -> Applique automatiquement (groupe auto).")
            else:
                print(f"  -> Echec de l'application automatique : {applied.get('error')}")
        else:
            print("  Rien n'est applique automatiquement - revoir et appliquer via le dashboard ou control_server.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", help="Nom de l'instance a verifier (champ `name` de sa config)")
    parser.add_argument("--all", action="store_true", dest="run_all_bots", help="Verifier tous les bots connus")
    args = parser.parse_args()
    if not args.run_all_bots and not args.name:
        parser.error("precise --name <bot> ou --all")
    main(args.name, args.run_all_bots)
