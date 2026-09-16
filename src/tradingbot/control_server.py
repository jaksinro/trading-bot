"""Serveur de controle local (STC ext. section 5) : permet de creer, lancer,
arreter, modifier et supprimer des instances de bot depuis le dashboard, sans
toucher a un fichier YAML ni a un terminal. Local uniquement (localhost),
jamais expose au reseau.

Usage:
    python -m tradingbot.control_server
Puis ouvrir http://localhost:8765/dashboard.html (fonctionne aussi si le
dashboard est ouvert directement en fichier local, tant que ce serveur tourne).
"""

import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import ccxt
import yaml

from tradingbot.process_lock import _is_process_running, acquire_lock

PORT = 8765
ROOT = Path(__file__).resolve().parents[2]
CONTROL_SERVER_LOCK_PATH = ROOT / "control_server.lock"
CONFIG_DIR = ROOT / "config"
LOG_DIR = ROOT / "logs"
PROPOSALS_DIR = ROOT / "proposals"

VALID_STRATEGIES = {"sma_cross", "scalp_dip", "dip_bounce_hourly", "dip_bounce_minute", "buy_and_hold"}
VALID_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h", "1d"}

# EF-56 : barre de progression du backtest (onglet Test/Backtest du dashboard).
# `ThreadingHTTPServer` traite chaque requete dans son propre thread - la
# requete POST /api/run-backtest (bloquante, peut prendre du temps) et le
# polling GET /api/backtest-progress du navigateur s'executent donc bien EN
# PARALLELE. Etat partage minimal, protege par un verrou simple (pas besoin
# de plus pour un usage local mono-utilisateur) ; cle = job_id genere cote
# client, jamais reutilise, retire des que le test se termine (succes,
# erreur ou exception) - pas de nettoyage periodique necessaire a cette echelle.
_backtest_progress_lock = threading.Lock()
_backtest_progress: dict[str, dict] = {}

# Vues du graphique de cours (EF-29) : chaque niveau de zoom correspond a un
# timeframe/nombre de bougies choisi pour couvrir approximativement la
# periode demandee. Les donnees viennent du marche SPOT reel (pas du
# testnet, dont l'historique est trop court pour "5 ans"/"10 ans") : c'est
# une info de contexte visuel, independante du compte utilise pour trader.
PRICE_HISTORY_RANGES: dict[str, tuple[str, int]] = {
    "1h": ("1m", 60),
    "1j": ("15m", 96),
    "1mois": ("4h", 180),
    "1an": ("1d", 365),
    "5ans": ("1w", 260),
    "10ans": ("1w", 520),
}

PRICE_HISTORY_CACHE_TTL_SECONDS = 60.0
_price_history_cache: dict[tuple[str, str], tuple[float, list]] = {}
_public_exchange = ccxt.binance()


def fetch_price_history(symbol: str, range_key: str, exchange=None) -> list[list]:
    """Recupere les points [timestamp, close] pour une periode nommee
    (voir PRICE_HISTORY_RANGES). Mis en cache quelques secondes pour eviter
    de re-interroger l'exchange a chaque clic si plusieurs onglets sont
    ouverts sur le meme symbole."""
    if range_key not in PRICE_HISTORY_RANGES:
        raise ValueError(f"periode inconnue : {range_key}")

    cache_key = (symbol, range_key)
    now = time.time()
    cached = _price_history_cache.get(cache_key)
    if cached is not None and (now - cached[0]) < PRICE_HISTORY_CACHE_TTL_SECONDS:
        return cached[1]

    timeframe, limit = PRICE_HISTORY_RANGES[range_key]
    ohlcv = (exchange or _public_exchange).fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    points = [[int(row[0]), float(row[4])] for row in ohlcv]
    _price_history_cache[cache_key] = (now, points)
    return points

# Delai apres lancement pour detecter un crash immediat (mauvaise config,
# strategie qui leve une exception, etc.) avant de repondre au formulaire.
CRASH_CHECK_DELAY_SECONDS = 3.0

MARKETS_CACHE_TTL_SECONDS = 3600
_markets_cache: dict | None = None
_markets_cache_at: float = 0.0


def get_binance_markets() -> dict | None:
    """Recupere (et met en cache) la liste des paires Binance, pour detecter
    une faute de frappe dans le symbole (ex: DODGE au lieu de DOGE) avant de
    lancer le bot. Retourne None si l'API est injoignable (on ne bloque pas
    la creation pour autant, seulement le format est alors verifie)."""
    global _markets_cache, _markets_cache_at
    now = time.time()
    if _markets_cache is None or (now - _markets_cache_at) > MARKETS_CACHE_TTL_SECONDS:
        try:
            _markets_cache = ccxt.binance().load_markets()
            _markets_cache_at = now
        except Exception:
            return _markets_cache
    return _markets_cache


def list_proposals() -> list[dict]:
    """Liste les propositions de reoptimisation en attente (feuille de route
    performance, etape 5) - ecrites par `python -m tradingbot.reoptimizer`,
    jamais appliquees automatiquement."""
    if not PROPOSALS_DIR.is_dir():
        return []
    proposals = []
    for path in sorted(PROPOSALS_DIR.glob("*_proposal.json")):
        try:
            proposals.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return proposals


def is_bot_running(name: str) -> bool:
    lock_path = ROOT / f"bot_{name}.lock"
    if not lock_path.exists():
        return False
    try:
        pid = int(lock_path.read_text().strip())
    except ValueError:
        return False
    return _is_process_running(pid)


def launch_process(config_path: Path, name: str) -> tuple[bool, str]:
    """Lance le bot en arriere-plan (pas de fenetre visible) avec sa sortie
    capturee dans logs/{name}.log, et verifie apres un court delai qu'il n'a
    pas plante immediatement - sinon la fenetre se fermait sans que
    l'utilisateur ne voie jamais l'erreur."""
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"{name}.log"
    log_file = open(log_path, "w", encoding="utf-8")

    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(
        [sys.executable, "-m", "tradingbot.run_paper", str(config_path)],
        cwd=str(ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags,
    )

    time.sleep(CRASH_CHECK_DELAY_SECONDS)
    if process.poll() is not None:
        log_file.close()
        error_text = log_path.read_text(encoding="utf-8", errors="replace").strip()
        last_line = error_text.splitlines()[-1] if error_text else "erreur inconnue (log vide)"
        return False, last_line

    return True, ""


def list_known_configs() -> list[dict]:
    """Scanne config/*.yml pour lister tous les bots connus, meme ceux qui
    n'ont jamais encore ete lances (donc absents du registre du dashboard)."""
    configs = []
    for path in sorted(CONFIG_DIR.glob("*.yml")):
        try:
            cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        name = cfg.get("name", path.stem)
        configs.append({
            "name": name,
            "config_path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "symbol": cfg.get("symbol"),
            "timeframe": cfg.get("timeframe"),
            "strategy_type": (cfg.get("strategy") or {}).get("type"),
            "capital_allocated": cfg.get("capital_allocated"),
            "running": is_bot_running(name),
        })
    return configs


def get_config_path_for_name(name: str) -> Path | None:
    """Trouve le VRAI fichier YAML portant ce nom interne (`name:` dans le
    fichier), sans supposer que le nom du fichier correspond au nom de
    l'instance - plusieurs configs de ce projet (doge_scalp.yml, etc.) ont
    un nom de fichier different de leur champ `name`. Assumer le contraire
    a cause une duplication de config lors d'une modification (bug corrige)."""
    for path in CONFIG_DIR.glob("*.yml"):
        try:
            cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if cfg.get("name", path.stem) == name:
            return path
    return None


def get_config_for_name(name: str) -> dict | None:
    path = get_config_path_for_name(name)
    if path is None:
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def remove_from_dashboard_registry(name: str) -> None:
    """Retire une instance du registre du dashboard et supprime ses
    donnees affichees - a appeler quand un bot est supprime OU renomme
    (sinon l'ancien nom reste affiche comme un onglet fantome)."""
    (ROOT / "dashboard_data" / f"{name}.js").unlink(missing_ok=True)

    registry_state = ROOT / "dashboard_data" / "registry.state"
    if registry_state.exists():
        names = [n for n in registry_state.read_text(encoding="utf-8").splitlines() if n and n != name]
        registry_state.write_text("\n".join(names), encoding="utf-8")
        registry_js = ROOT / "dashboard_data" / "registry.js"
        registry_js.write_text("window.BOT_REGISTRY = " + json.dumps(names) + ";\n", encoding="utf-8")


def _require_positive(value: float, field: str) -> float:
    if value <= 0:
        raise ValueError(f"{field} doit etre strictement positif")
    return value


def _require_fraction(value: float, field: str) -> float:
    """Valide un pourcentage exprime en fraction (0 < value <= 1)."""
    if not (0 < value <= 1):
        raise ValueError(f"{field} doit etre compris entre 0 et 100 %")
    return value


def _to_float(payload: dict, field: str, label: str) -> float:
    raw = payload.get(field)
    if raw in (None, ""):
        raise ValueError(f"{label} est requis")
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{label} doit etre un nombre valide")


def _to_int(payload: dict, field: str, label: str) -> int:
    raw = payload.get(field)
    if raw in (None, ""):
        raise ValueError(f"{label} est requis")
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        raise ValueError(f"{label} doit etre un nombre entier valide")


def build_config(payload: dict) -> dict:
    """Traduit le formulaire (JSON) en config YAML valide pour run_paper.py.
    Fonction pure, testable independamment du serveur HTTP. Toutes les
    valeurs sont verifiees pour eviter qu'un bot plante au demarrage a cause
    d'un parametre incoherent (ex: moyenne courte >= moyenne longue)."""
    name = payload.get("name", "").strip()
    if not name or not all(c.isalnum() or c == "_" for c in name):
        raise ValueError("nom invalide (lettres, chiffres, underscore uniquement)")

    symbol = payload.get("symbol", "").strip().upper()
    if "/" not in symbol or len(symbol.split("/")) != 2 or "" in symbol.split("/"):
        raise ValueError("symbole invalide (format attendu: BASE/QUOTE, ex: ETH/USDT)")

    markets = get_binance_markets()
    if markets is not None and symbol not in markets:
        import difflib
        base, quote = symbol.split("/")
        same_quote_bases = [m.split("/")[0] for m in markets if m.endswith(f"/{quote}")]
        suggestions = difflib.get_close_matches(base, same_quote_bases, n=1)
        hint = f" (peut-etre {suggestions[0]}/{quote} ?)" if suggestions else ""
        raise ValueError(f"symbole '{symbol}' introuvable sur Binance{hint} - verifie l'orthographe")

    timeframe = payload.get("timeframe", "1h")
    if timeframe not in VALID_TIMEFRAMES:
        raise ValueError(f"timeframe invalide, doit etre l'un de : {', '.join(sorted(VALID_TIMEFRAMES))}")

    strategy_type = payload.get("strategy_type")
    if strategy_type not in VALID_STRATEGIES:
        raise ValueError(f"strategie inconnue: {strategy_type}")

    profit_lock_arm_pct = None
    profit_lock_trigger_pct = None

    if strategy_type == "sma_cross":
        short_window = _to_int(payload, "short_window", "Moyenne courte")
        long_window = _to_int(payload, "long_window", "Moyenne longue")
        if short_window < 1:
            raise ValueError("la moyenne courte doit etre >= 1")
        if short_window >= long_window:
            raise ValueError("la moyenne courte doit etre strictement inferieure a la moyenne longue")
        strategy = {"type": "sma_cross", "short_window": short_window, "long_window": long_window}
        warmup_minimum = long_window
    elif strategy_type == "scalp_dip":
        lookback = _to_int(payload, "lookback", "Lookback")
        if lookback < 2:
            raise ValueError("le lookback doit etre >= 2")
        dip_threshold_pct = _require_positive(
            _to_float(payload, "dip_threshold_pct", "Seuil de creux") , "le seuil de creux"
        )
        strategy = {"type": "scalp_dip", "lookback": lookback, "dip_threshold_pct": dip_threshold_pct}
        warmup_minimum = lookback
    elif strategy_type in ("dip_bounce_hourly", "dip_bounce_minute"):
        # Etape 9 (feuille de route performance) : 2 PRESETS du meme
        # `strategy.type = "dip_bounce"` (voir strategies/dip_bounce.py,
        # agnostique du timeframe) - seule la granularite (bougies 1h/fenetre
        # 24 vs bougies 1m/fenetre 60) differe. `timeframe` est FORCE plus
        # bas, independamment de ce que le formulaire a soumis : la coherence
        # entre le preset et sa granularite ne doit jamais dependre du champ
        # timeframe libre.
        dip_threshold_pct = _require_positive(
            _to_float(payload, "dip_threshold_pct", "Seuil de creux"), "le seuil de creux"
        )
        profit_lock_arm_pct = _require_positive(
            _to_float(payload, "profit_lock_arm_pct", "Armement du verrou de gain"), "l'armement du verrou de gain"
        )
        profit_lock_trigger_pct = _require_positive(
            _to_float(payload, "profit_lock_trigger_pct", "Declenchement du verrou de gain"),
            "le declenchement du verrou de gain",
        )
        if profit_lock_trigger_pct >= profit_lock_arm_pct:
            raise ValueError(
                "le seuil de declenchement du verrou de gain doit etre strictement inferieur au seuil d'armement"
            )
        force_trade_after_hours = None
        force_trade_raw = payload.get("force_trade_after_hours")
        if force_trade_raw not in (None, "", 0, "0"):
            force_trade_after_hours = _require_positive(
                _to_float(payload, "force_trade_after_hours", "Forcer un trade apres N heures"),
                "le nombre d'heures avant de forcer un trade",
            )
        trend_ma_period = 24 if strategy_type == "dip_bounce_hourly" else 60
        timeframe = "1h" if strategy_type == "dip_bounce_hourly" else "1m"
        strategy = {
            "type": "dip_bounce", "trend_ma_period": trend_ma_period, "dip_threshold_pct": dip_threshold_pct,
            "force_trade_after_hours": force_trade_after_hours,
        }
        warmup_minimum = trend_ma_period
    else:  # buy_and_hold
        # Strategie passive (etape 9) : achete une fois, ne revend jamais -
        # aucun parametre, pas de sortie donc pas de fenetre a rechauffer.
        strategy = {"type": "buy_and_hold"}
        warmup_minimum = 0

    if strategy_type == "buy_and_hold":
        # Force a 0, jamais deduit du formulaire : `warm_up_strategy`
        # (run_paper.py) appelle `strategy.on_candle()` sur l'historique
        # pendant le "rechauffement" (etat interne prime, signal jete) - pour
        # une strategie qui n'achete qu'UNE fois dans sa vie, le moindre
        # rechauffement non nul declencherait cet achat unique pour de faux,
        # et elle n'acheterait plus jamais reellement au demarrage live.
        warmup_candles = 0
    else:
        warmup_candles = (
            _to_int(payload, "warmup_candles", "Bougies de rechauffement")
            if payload.get("warmup_candles") not in (None, "")
            else warmup_minimum
        )
    if warmup_candles < warmup_minimum:
        raise ValueError(
            f"les bougies de rechauffement ({warmup_candles}) doivent etre >= {warmup_minimum} "
            f"pour que la strategie choisie puisse produire un signal"
        )

    # Depuis le passage au panier de capital commun (STC section 3.5 revisee),
    # ce champ n'est plus un budget isole : c'est le plafond de mise de base
    # de ce bot dans le panier partage (module dynamiquement selon sa
    # performance, voir shared_pool.py).
    capital_allocated = _require_positive(
        _to_float(payload, "capital_allocated", "Plafond de mise"), "le plafond de mise"
    )
    max_position_size_pct = _require_fraction(
        _to_float(payload, "max_position_size_pct", "Taille position max"), "la taille de position max"
    )
    # Etape 9 : buy_and_hold n'a pas de stop-loss - decision assumee (achat
    # unique jamais revendu, voir strategies/buy_and_hold.py), pas un champ
    # oublie. Le champ formulaire est ignore pour ce type plutot que de
    # forcer une valeur artificielle.
    # dip_bounce (les 2 presets) : stop-loss reintegre en OPTIONNEL (demande
    # explicite de l'utilisateur, 2026-09-15) - vide reste desactive (defaut
    # historique inchange), une valeur saisie l'active comme pour les autres
    # strategies.
    if strategy_type == "buy_and_hold":
        stop_loss_pct = None
    else:
        stop_loss_raw = payload.get("stop_loss_pct")
        if strategy_type in ("dip_bounce_hourly", "dip_bounce_minute") and stop_loss_raw in (None, ""):
            stop_loss_pct = None
        else:
            stop_loss_pct = _require_fraction(_to_float(payload, "stop_loss_pct", "Stop-loss"), "le stop-loss")
    max_daily_loss_pct = _require_fraction(
        _to_float(payload, "max_daily_loss_pct", "Perte max journaliere"), "la perte max journaliere"
    )

    take_profit_raw = payload.get("take_profit_pct")
    if take_profit_raw in (None, ""):
        take_profit_pct = None
    else:
        take_profit_pct = _require_fraction(
            _to_float(payload, "take_profit_pct", "Take-profit"), "le take-profit"
        )

    max_concurrent_positions = (
        _to_int(payload, "max_concurrent_positions", "Positions simultanees max")
        if payload.get("max_concurrent_positions") not in (None, "")
        else 1
    )
    if max_concurrent_positions < 1:
        raise ValueError("le nombre de positions simultanees doit etre >= 1")
    if max_concurrent_positions * max_position_size_pct > 1.0:
        raise ValueError(
            f"{max_concurrent_positions} positions x {max_position_size_pct:.0%} de taille chacune depasserait "
            f"100% du capital - reduis le nombre de positions ou la taille par position"
        )

    exit_check_timeframe = payload.get("exit_check_timeframe") or None
    if exit_check_timeframe is not None:
        if exit_check_timeframe not in VALID_TIMEFRAMES:
            raise ValueError(f"timeframe de surveillance des sorties invalide, doit etre l'un de : {', '.join(sorted(VALID_TIMEFRAMES))}")
        if ccxt.Exchange.parse_timeframe(exit_check_timeframe) >= ccxt.Exchange.parse_timeframe(timeframe):
            raise ValueError("le timeframe de surveillance des sorties doit etre plus fin (plus court) que le timeframe du bot")

    trailing_stop_raw = payload.get("trailing_stop_pct")
    if trailing_stop_raw in (None, ""):
        trailing_stop_pct = None
    else:
        trailing_stop_pct = _require_fraction(
            _to_float(payload, "trailing_stop_pct", "Trailing stop"), "le trailing stop"
        )

    fee_pct = (
        _require_fraction(_to_float(payload, "fee_pct", "Frais"), "les frais")
        if payload.get("fee_pct") not in (None, "")
        else 0.001
    )

    partial_take_profit_raw = payload.get("partial_take_profit_pct")
    if partial_take_profit_raw in (None, ""):
        partial_take_profit_pct = None
        partial_exit_fraction = 0.5
    else:
        partial_take_profit_pct = _require_fraction(
            _to_float(payload, "partial_take_profit_pct", "Palier de sortie partielle"), "le palier de sortie partielle"
        )
        partial_exit_fraction = _require_fraction(
            _to_float(payload, "partial_exit_fraction", "Fraction de sortie partielle"), "la fraction de sortie partielle"
        )
        if take_profit_pct is not None and partial_take_profit_pct >= take_profit_pct:
            raise ValueError("le palier de sortie partielle doit etre strictement inferieur au take-profit complet")

    config = {
        "name": name,
        "exchange": "binance",
        "symbol": symbol,
        "timeframe": timeframe,
        "warmup_candles": warmup_candles,
        "flatten_on_start": bool(payload.get("flatten_on_start", True)),
        "capital_allocated": capital_allocated,
        "strategy": strategy,
        "risk": {
            "max_position_size_pct": max_position_size_pct,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "max_daily_loss_pct": max_daily_loss_pct,
            "max_concurrent_positions": max_concurrent_positions,
            "trailing_stop_pct": trailing_stop_pct,
            "fee_pct": fee_pct,
            "partial_take_profit_pct": partial_take_profit_pct,
            "partial_exit_fraction": partial_exit_fraction,
            "profit_lock_arm_pct": profit_lock_arm_pct,
            "profit_lock_trigger_pct": profit_lock_trigger_pct,
        },
        "exit_check_timeframe": exit_check_timeframe,
        "backtest": {"starting_capital": 1000, "since": "2024-01-01T00:00:00Z"},
    }

    if payload.get("probability_filter_enabled"):
        min_probability = _require_fraction(
            _to_float(payload, "min_probability", "Seuil de probabilite"), "le seuil de probabilite"
        )
        config["probability_filter"] = {
            "enabled": True,
            "min_probability": min_probability,
            "lookback_years": 3.0,
            "n_simulations": 200_000,
        }

    if payload.get("trend_filter_enabled"):
        ema_period = _to_int(payload, "trend_filter_ema_period", "Periode EMA du filtre de tendance")
        if ema_period < 2:
            raise ValueError("la periode EMA du filtre de tendance doit etre >= 2")
        config["trend_filter"] = {"enabled": True, "ema_period": ema_period}

    if payload.get("atr_sizing_enabled"):
        atr_period = _to_int(payload, "atr_period", "Periode ATR")
        baseline_period = _to_int(payload, "atr_baseline_period", "Periode de reference ATR")
        min_multiplier = _require_fraction(
            _to_float(payload, "atr_min_multiplier", "Taille minimum ATR"), "la taille minimum du sizing ATR"
        )
        if atr_period < 1:
            raise ValueError("la periode ATR doit etre >= 1")
        if baseline_period < 1:
            raise ValueError("la periode de reference ATR doit etre >= 1")
        config["atr_sizing"] = {
            "enabled": True,
            "atr_period": atr_period,
            "baseline_period": baseline_period,
            "min_size_multiplier": min_multiplier,
        }

    if payload.get("price_level_sizing_enabled"):
        price_level_min = _require_positive(
            _to_float(payload, "price_level_min_multiplier", "Taille minimum (niveau de prix)"),
            "la taille minimum du sizing par niveau de prix",
        )
        price_level_max = _require_positive(
            _to_float(payload, "price_level_max_multiplier", "Taille maximum (niveau de prix)"),
            "la taille maximum du sizing par niveau de prix",
        )
        if price_level_max < price_level_min:
            raise ValueError("la taille maximum du sizing par niveau de prix doit etre >= a la taille minimum")
        config["price_level_sizing"] = {
            "enabled": True,
            "min_size_multiplier": price_level_min,
            "max_size_multiplier": price_level_max,
        }

    return config


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length))
        except Exception:
            self._send_json(400, {"error": "JSON invalide"})
            return

        routes = {
            "/api/launch-bot": self._handle_launch,
            "/api/stop-bot": self._handle_stop,
            "/api/start-bot": self._handle_start_existing,
            "/api/update-bot": self._handle_update,
            "/api/delete-bot": self._handle_delete,
            "/api/apply-proposal": self._handle_apply_proposal,
            "/api/dismiss-proposal": self._handle_dismiss_proposal,
            "/api/reoptimize-all": self._handle_reoptimize_all,
            "/api/run-backtest": self._handle_run_backtest,
            "/api/restart-all-bots": self._handle_restart_all,
        }
        handler = routes.get(self.path)
        if handler is None:
            self._send_json(404, {"error": "route inconnue"})
            return
        handler(payload)

    def _handle_launch(self, payload: dict) -> None:
        try:
            config = build_config(payload)
        except (KeyError, ValueError, TypeError) as e:
            self._send_json(400, {"error": str(e)})
            return

        if get_config_path_for_name(config["name"]) is not None:
            self._send_json(409, {"error": f"un bot nomme '{config['name']}' existe deja - utilise Modifier plutot que Creer"})
            return

        config_path = CONFIG_DIR / f"{config['name']}.yml"
        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")

        ok, error = launch_process(config_path, config["name"])
        if not ok:
            self._send_json(500, {"error": f"le bot a plante au demarrage : {error}"})
            return
        self._send_json(200, {"status": "lance", "name": config["name"]})

    def _handle_start_existing(self, payload: dict) -> None:
        config_path_str = payload.get("config_path", "")
        config_path = (ROOT / config_path_str).resolve()
        if ROOT not in config_path.parents or not config_path.is_file():
            self._send_json(400, {"error": "config introuvable"})
            return

        try:
            cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            name = cfg["name"]
        except (yaml.YAMLError, KeyError) as e:
            self._send_json(400, {"error": f"config invalide : {e}"})
            return

        if is_bot_running(name):
            self._send_json(409, {"error": f"{name} tourne deja"})
            return

        ok, error = launch_process(config_path, name)
        if not ok:
            self._send_json(500, {"error": f"le bot a plante au demarrage : {error}"})
            return
        self._send_json(200, {"status": "lance", "name": name})

    def _handle_update(self, payload: dict) -> None:
        """Modifie un bot existant. S'il tournait, il est arrete puis relance
        avec les nouveaux parametres ; sinon la config est juste mise a jour.

        Reecrit toujours le VRAI fichier d'origine (trouve par son champ
        `name`, pas en recalculant un chemin a partir du nom) - sinon un bot
        dont le nom de fichier ne correspond pas a son champ `name` (ex:
        doge_scalp.yml -> name: doge_scalp_v1) se retrouve duplique en un
        second fichier au lieu d'etre mis a jour (bug corrige)."""
        original_name = payload.get("original_name", "").strip()
        original_path = get_config_path_for_name(original_name)
        if not original_name or original_path is None:
            self._send_json(404, {"error": "bot introuvable"})
            return

        try:
            config = build_config(payload)
        except (KeyError, ValueError, TypeError) as e:
            self._send_json(400, {"error": str(e)})
            return

        is_rename = config["name"] != original_name
        if is_rename and get_config_path_for_name(config["name"]) is not None:
            self._send_json(409, {"error": f"un bot nomme '{config['name']}' existe deja"})
            return

        was_running = is_bot_running(original_name)
        if was_running:
            self._kill_by_name(original_name)
            time.sleep(0.5)

        if is_rename:
            original_path.unlink()
            remove_from_dashboard_registry(original_name)  # sinon l'ancien nom reste affiche (onglet fantome)
            config_path = CONFIG_DIR / f"{config['name']}.yml"
        else:
            config_path = original_path  # reecrit le fichier d'origine, quel que soit son nom

        config_path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")

        if was_running:
            ok, error = launch_process(config_path, config["name"])
            if not ok:
                self._send_json(500, {"error": f"config enregistree, mais le bot a plante au redemarrage : {error}"})
                return

        self._send_json(200, {"status": "modifie", "name": config["name"], "relance": was_running})

    def _handle_delete(self, payload: dict) -> None:
        name = payload.get("name", "").strip()
        if is_bot_running(name):
            self._send_json(409, {"error": "arrete le bot avant de le supprimer"})
            return

        cfg = get_config_for_name(name)
        if cfg is None:
            self._send_json(404, {"error": "bot introuvable"})
            return

        for path in CONFIG_DIR.glob("*.yml"):
            try:
                if (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("name", path.stem) == name:
                    path.unlink()
            except yaml.YAMLError:
                continue

        (ROOT / f"bot_{name}.lock").unlink(missing_ok=True)
        remove_from_dashboard_registry(name)

        self._send_json(200, {"status": "supprime", "name": name})

    def _handle_apply_proposal(self, payload: dict) -> None:
        """Applique une proposition de reoptimisation (etape 5) - logique
        partagee avec l'application automatique du groupe "auto"
        (`reoptimizer.apply_proposal_files`), pour eviter que les deux
        chemins divergent."""
        from tradingbot.reoptimizer import apply_proposal_files

        name = payload.get("name", "").strip()
        result = apply_proposal_files(name)
        if result["status"] == "error":
            error = result.get("error", "erreur inconnue")
            status_code = 404 if "introuvable" in error else 409 if "position" in error else 500
            self._send_json(status_code, {"error": error})
            return
        self._send_json(200, {"status": "applique", "name": name, "relance": result.get("relance", False)})

    def _handle_dismiss_proposal(self, payload: dict) -> None:
        name = payload.get("name", "").strip()
        (PROPOSALS_DIR / f"{name}_proposal.json").unlink(missing_ok=True)
        (PROPOSALS_DIR / f"{name}_proposed_config.yml").unlink(missing_ok=True)
        self._send_json(200, {"status": "rejete", "name": name})

    def _handle_reoptimize_all(self, payload: dict) -> None:
        """Lance la reoptimisation de TOUS les bots connus en arriere-plan
        (peut prendre plusieurs minutes - grille de ~960 combinaisons par
        paire) et repond immediatement. Les resultats apparaissent au fil
        de l'eau dans /api/list-proposals (groupe "auto" applique tout
        seul, groupe "control" laisse la proposition en attente - voir
        reoptimizer.py pour le test A/B)."""
        from tradingbot.reoptimizer import run_all

        threading.Thread(target=run_all, daemon=True).start()
        self._send_json(200, {"status": "lance"})

    def _handle_run_backtest(self, payload: dict) -> None:
        """Onglet Test/Backtest du dashboard - execute un backtest unique via
        `backtest_lab.py` (meme code que le CLI, voir STC section 3.29) et
        renvoie le rapport texte. Peut prendre du temps la premiere fois pour
        un symbole/timeframe jamais telecharge (pas de cache local encore).

        EF-56 : si le payload porte un `job_id` (genere cote client), publie
        la progression dans `_backtest_progress` au fil de l'execution - le
        dashboard la lit en parallele via GET /api/backtest-progress pour
        animer une barre de progression pendant que cette requete (bloquante)
        tourne encore."""
        from tradingbot.backtest_lab import build_namespace_from_payload, run_backtest_job

        job_id = payload.get("job_id") or ""

        def report_progress(update: dict) -> None:
            with _backtest_progress_lock:
                _backtest_progress[job_id] = update

        try:
            args = build_namespace_from_payload(payload)
            text, report_path = run_backtest_job(args, progress_callback=report_progress if job_id else None)
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
            return
        except Exception as e:
            self._send_json(500, {"error": f"echec du backtest : {e}"})
            return
        finally:
            if job_id:
                with _backtest_progress_lock:
                    _backtest_progress.pop(job_id, None)
        self._send_json(200, {"report": text, "report_path": report_path})

    def _handle_restart_all(self, payload: dict) -> None:
        """Redemarre (stop puis relance depuis la config sur disque) tous les
        bots ACTUELLEMENT en cours - utile apres une mise a jour du logiciel :
        un process Python deja lance ne recharge jamais son propre code tout
        seul, et chaque bot regenere `dashboard.html` a chaque cycle avec le
        template qu'il a en memoire (voir STC section 3.6). Les positions
        ouvertes sont restaurees a l'identique au redemarrage (EF-27) - rien
        n'est vendu, ce n'est pas une liquidation."""
        results = []
        for cfg in list_known_configs():
            if not cfg["running"]:
                continue
            name = cfg["name"]
            config_path = ROOT / cfg["config_path"]
            self._kill_by_name(name)
            time.sleep(0.5)
            ok, error = launch_process(config_path, name)
            results.append({"name": name, "ok": ok, "error": error})
        self._send_json(200, {"status": "termine", "results": results})

    def _handle_stop(self, payload: dict) -> None:
        name = payload.get("name", "").strip()
        if not is_bot_running(name):
            self._send_json(404, {"error": "pas de bot actif trouve avec ce nom"})
            return
        self._kill_by_name(name)
        self._send_json(200, {"status": "arrete", "name": name})

    def _kill_by_name(self, name: str) -> None:
        kill_by_name(name)

    def do_GET(self) -> None:
        if self.path == "/api/list-configs":
            self._send_json(200, {"configs": list_known_configs()})
            return

        if self.path == "/api/list-proposals":
            self._send_json(200, {"proposals": list_proposals()})
            return

        if self.path == "/api/backtest-strategies":
            from tradingbot.backtest_lab import presets_metadata

            self._send_json(200, {"strategies": presets_metadata()})
            return

        if self.path.startswith("/api/backtest-progress"):
            query = parse_qs(urlsplit(self.path).query)
            job_id = query.get("job_id", [""])[0]
            with _backtest_progress_lock:
                progress = _backtest_progress.get(job_id)
            self._send_json(200, {"progress": progress})
            return

        if self.path.startswith("/api/config"):
            name = self.path.split("?name=")[-1] if "?name=" in self.path else ""
            cfg = get_config_for_name(name)
            if cfg is None:
                self._send_json(404, {"error": "bot introuvable"})
            else:
                self._send_json(200, {"config": cfg})
            return

        if self.path.startswith("/api/price-history"):
            query = parse_qs(urlsplit(self.path).query)
            symbol = unquote(query.get("symbol", [""])[0])
            range_key = query.get("range", ["1j"])[0]
            try:
                points = fetch_price_history(symbol, range_key)
            except Exception as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, {"points": points})
            return

        rel_path = self.path.lstrip("/").split("?")[0] or "dashboard.html"
        file_path = (ROOT / rel_path).resolve()
        if ROOT not in file_path.parents and file_path != ROOT or not file_path.is_file():
            self.send_response(404)
            self.end_headers()
            return

        content_type = {
            ".html": "text/html",
            ".js": "application/javascript",
        }.get(file_path.suffix, "application/octet-stream")

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def log_message(self, format: str, *args) -> None:
        pass  # silence par defaut


def kill_by_name(name: str) -> None:
    lock_path = ROOT / f"bot_{name}.lock"
    try:
        pid = int(lock_path.read_text().strip())
    except (ValueError, FileNotFoundError):
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    else:
        subprocess.run(["kill", "-9", str(pid)], capture_output=True)


def main() -> None:
    # CT-26 : deux instances de ce serveur ont deja tourne simultanement sur
    # le meme poste sans que rien ne le signale - `HTTPServer.allow_reuse_address`
    # (Windows) laisse une seconde instance capturer le port sans faire
    # echouer la premiere au demarrage, si bien que les requetes atterrissent
    # sur l'instance la plus recente meme si elle tourne du code perime.
    # Meme verrou atomique que les bots (`bot_{name}.lock`), applique ici a
    # ce process lui-meme plutot qu'a un bot nomme.
    acquire_lock(CONTROL_SERVER_LOCK_PATH)
    server = ThreadingHTTPServer(("localhost", PORT), Handler)
    print(f"Serveur de controle demarre : http://localhost:{PORT}/dashboard.html")
    print("Ctrl+C pour arreter.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
