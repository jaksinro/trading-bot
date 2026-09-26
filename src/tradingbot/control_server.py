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
import base64
import hmac
import os
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import ccxt
import yaml
from dotenv import load_dotenv

from tradingbot.process_lock import _is_process_running, acquire_lock

PORT = 8765

# EF-82 : acces depuis les autres appareils de la maison (Raspberry Pi).
# Par defaut le serveur ecoute sur toutes les interfaces, MAIS il ne sert
# rien a un client non-local tant qu'aucun mot de passe n'est defini : un
# dashboard qui sait passer des ordres et arreter des bots ne doit jamais
# etre ouvert sur un reseau par simple oubli. Les connexions locales
# (127.0.0.1, ::1) restent libres, pour l'usage sur la machine elle-meme et
# pour le script de demarrage automatique.
BIND_HOST_ENV = "DASHBOARD_BIND"
PASSWORD_ENV = "DASHBOARD_PASSWORD"
USER_ENV = "DASHBOARD_USER"
DEFAULT_BIND_HOST = "0.0.0.0"
DEFAULT_USER = "trader"

# EF-86 : HTTPS optionnel. Sans lui, le mot de passe HTTP Basic et les
# ordres circulent en clair sur le reseau local. Les deux variables vont
# ensemble (certificat + cle privee, au format PEM) ; n'en renseigner qu'une
# est une erreur de demarrage, jamais un repli silencieux sur HTTP.
TLS_CERT_ENV = "DASHBOARD_TLS_CERT"
TLS_KEY_ENV = "DASHBOARD_TLS_KEY"
# Delai maximal pour qu'un client termine la poignee de main TLS : au-dela,
# la connexion est abandonnee plutot que d'immobiliser un thread.
TLS_HANDSHAKE_TIMEOUT_S = 10
ROOT = Path(__file__).resolve().parents[2]
CONTROL_SERVER_LOCK_PATH = ROOT / "control_server.lock"
CONFIG_DIR = ROOT / "config"
LOG_DIR = ROOT / "logs"
PROPOSALS_DIR = ROOT / "proposals"

VALID_STRATEGIES = {
    "sma_cross", "scalp_dip", "dip_bounce_hourly", "dip_bounce_minute",
    "mean_dip", "slope_dip", "dip_bounce_daily", "trend_regime", "buy_and_hold",
}
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


_manual_price_cache: dict[str, tuple[float, float]] = {}


def manual_last_price(symbol: str, exchange=None) -> float:
    """Dernier cours PUBLIC (aucune cle), mis en cache 5 s : le panier manuel
    rafraichit ses positions souvent, inutile de marteler l'exchange."""
    now = time.time()
    cached = _manual_price_cache.get(symbol)
    if cached is not None and now - cached[0] < 5:
        return cached[1]
    price = float((exchange or _public_exchange).fetch_ticker(symbol)["last"])
    _manual_price_cache[symbol] = (now, price)
    return price


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
    # [t, cloture, ouverture, haut, bas] : bougies completes pour le graphique
    # en chandeliers (EF-84) ; index 0/1 inchanges pour les lecteurs existants.
    points = [[int(row[0]), float(row[4]), float(row[1]), float(row[2]), float(row[3])] for row in ohlcv]
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


LOG_MAX_BYTES = 2_000_000  # au-dela, le journal d'un bot tourne vers {name}.log.1


def launch_process(config_path: Path, name: str) -> tuple[bool, str]:
    """Lance le bot en arriere-plan (pas de fenetre visible) avec sa sortie
    capturee dans logs/{name}.log, et verifie apres un court delai qu'il n'a
    pas plante immediatement - sinon la fenetre se fermait sans que
    l'utilisateur ne voie jamais l'erreur."""
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"{name}.log"
    # EF-85 : le journal etait ouvert en "w", donc EFFACE a chaque lancement -
    # la trace d'un plantage disparaissait au redemarrage suivant (celle du bot
    # ETH le 2026-09-25 n'a ete lue que parce qu'elle a ete consultee avant la
    # relance). On complete desormais le journal, avec un en-tete de session,
    # et on le fait tourner au-dela de LOG_MAX_BYTES pour ne pas le laisser
    # grossir sans fin sur un Raspberry Pi.
    if log_path.exists() and log_path.stat().st_size > LOG_MAX_BYTES:
        log_path.replace(log_path.with_suffix(".log.1"))
    log_file = open(log_path, "a", encoding="utf-8")
    log_file.write(f"\n===== lancement {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    log_file.flush()
    session_start = log_file.tell()

    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "tradingbot.run_paper", str(config_path)],  # -u : sortie non tamponnee, sinon le journal reste vide (EF-83)
        cwd=str(ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags,
    )

    time.sleep(CRASH_CHECK_DELAY_SECONDS)
    if process.poll() is not None:
        log_file.close()
        with open(log_path, encoding="utf-8", errors="replace") as f:
            f.seek(session_start)
            error_text = f.read().strip()  # uniquement la sortie de CE lancement
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
        # Les bots d'investissement regulier (EF-67) vivent dans config/dca/
        # et se reconnaissent a leur allocation `weights`. Ce filtre defensif
        # evite qu'une telle config deposee ici par erreur soit listee comme
        # un bot classique : Supervision proposerait de la lancer via
        # `run_paper.py`, qui planterait (ni `symbol` ni `strategy`).
        if cfg.get("weights") is not None:
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

    # EF-65 : "ibkr_paper" cree un bot actions (paper trading Interactive
    # Brokers) au lieu d'un bot crypto (testnet Binance) - symbole en format
    # ticker (ex: "RNO.PA"), pas BASE/QUOTE, et aucun sens a valider contre
    # les marches Binance.
    account_type = payload.get("account_type", "crypto")
    is_ibkr = account_type == "ibkr_paper"

    symbol = payload.get("symbol", "").strip().upper()
    if is_ibkr:
        if not symbol:
            raise ValueError("symbole invalide (ticker IBKR attendu, ex: RNO.PA)")
    else:
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
    if is_ibkr:
        # Bougies journalieres uniquement pour les actions IBKR (STC §3.46/
        # §3.48) - force independamment de ce que le formulaire a soumis,
        # meme logique que les presets a granularite fixe (mean_dip, etc.).
        timeframe = "1d"
    elif timeframe not in VALID_TIMEFRAMES:
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
    elif strategy_type == "mean_dip":
        # 2026-09-16, idee proposee par l'utilisateur : detecte un creux
        # comme un ECART a la moyenne recente (pas une proximite a un plus
        # bas glissant comme dip_bounce), sur une granularite fine pour
        # capter les pics descendants brefs invisibles a l'echelle 24h.
        # `timeframe` FORCE a 5 minutes, meme logique que dip_bounce_hourly/
        # minute : la coherence entre le preset et sa granularite ne doit
        # jamais dependre du champ timeframe libre du formulaire.
        window = _to_int(payload, "window", "Fenetre")
        if window < 2:
            raise ValueError("la fenetre doit etre >= 2")
        num_std = _require_positive(
            _to_float(payload, "num_std", "Largeur des bandes"), "la largeur des bandes"
        )
        timeframe = "5m"
        strategy = {"type": "mean_dip", "window": window, "num_std": num_std}
        warmup_minimum = window
    elif strategy_type == "slope_dip":
        # 2026-09-16, idee proposee par l'utilisateur : detecte une chute
        # BRUTALE entre 2 bougies consecutives (vitesse du mouvement, pas
        # une position par rapport a une moyenne/un plus bas) - parie qu'une
        # chute soudaine et prononcee a plus de chances de rebondir qu'une
        # derive lente. `timeframe` FORCE a 1 minute (meme logique que les
        # autres presets a granularite fixe).
        slope_threshold_pct = _require_positive(
            _to_float(payload, "slope_threshold_pct", "Seuil de pente"), "le seuil de pente"
        )
        candles_window = _to_int(payload, "candles_window", "Nombre de bougies")
        if candles_window < 2:
            raise ValueError("le nombre de bougies doit etre >= 2")
        one_buy_per_slope = bool(payload.get("one_buy_per_slope"))
        timeframe = "1m"
        strategy = {
            "type": "slope_dip", "slope_threshold_pct": slope_threshold_pct,
            "candles_window": candles_window, "one_buy_per_slope": one_buy_per_slope,
        }
        warmup_minimum = candles_window - 1
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
    elif strategy_type == "dip_bounce_daily":
        # Ajoute pour les actions IBKR (EF-65) - contrairement aux presets
        # horaire/minute (verrou de gain oblige, trend_ma_period fige), la
        # recherche empirique menee sur plusieurs actions (STC §3.47) a
        # montre que la fenetre de tendance optimale varie fortement d'une
        # action a l'autre (10 jours pour Renault, 40 pour Air France-KLM) -
        # laissee reglable ici. Verrou de gain volontairement absent : les
        # meilleurs reglages trouves n'en utilisaient aucun, seulement
        # stop-loss/trailing (deja optionnels via la branche generique plus
        # bas, comme dip_bounce_hourly/minute).
        trend_ma_period = _to_int(payload, "trend_ma_period", "Fenetre de tendance (jours)")
        if trend_ma_period < 2:
            raise ValueError("la fenetre de tendance doit etre >= 2 jours")
        dip_threshold_pct = _require_positive(
            _to_float(payload, "dip_threshold_pct", "Seuil de creux"), "le seuil de creux"
        )
        timeframe = "1d"
        strategy = {
            "type": "dip_bounce", "trend_ma_period": trend_ma_period, "dip_threshold_pct": dip_threshold_pct,
            "force_trade_after_hours": None,
        }
        warmup_minimum = trend_ma_period
    elif strategy_type == "trend_regime":
        # EF-68 : investi tant que la tendance est haussiere, TOUT en
        # liquidites des qu'elle casse. Contrairement au `trend_filter`
        # optionnel (qui bloque seulement les nouveaux achats), cette
        # strategie emet son propre signal de VENTE - c'est ce qui permet de
        # ne pas subir un marche baissier. Timeframe laisse libre : la
        # robustesse mesuree sur ETH tient de 3 semaines a 5,5 mois de
        # fenetre, donc a plusieurs granularites (voir STC).
        ema_period = _to_int(payload, "ema_period", "Fenetre de tendance (bougies)")
        if ema_period < 2:
            raise ValueError("la fenetre de tendance doit etre >= 2 bougies")
        entry_buffer_pct = _to_float(payload, "entry_buffer_pct", "Marge d'entree")
        exit_buffer_pct = _to_float(payload, "exit_buffer_pct", "Marge de sortie")
        if entry_buffer_pct < 0 or exit_buffer_pct < 0:
            raise ValueError("les marges d'entree et de sortie ne peuvent pas etre negatives")
        strategy = {
            "type": "trend_regime", "ema_period": ema_period,
            "entry_buffer_pct": entry_buffer_pct, "exit_buffer_pct": exit_buffer_pct,
        }
        warmup_minimum = ema_period
    else:  # buy_and_hold
        # Strategie passive (etape 9) : achete une fois, ne revend jamais -
        # aucun parametre, pas de sortie donc pas de fenetre a rechauffer.
        strategy = {"type": "buy_and_hold"}
        warmup_minimum = 0

    if is_ibkr and timeframe != "1d":
        # mean_dip/slope_dip/dip_bounce_hourly/dip_bounce_minute forcent
        # tous un timeframe incompatible avec le paper trading IBKR (qui ne
        # gere que des bougies journalieres, voir run_paper.py::ib_*) - un
        # bot cree avec l'une de ces strategies planterait au demarrage.
        raise ValueError(
            f"la strategie '{strategy_type}' impose le timeframe {timeframe}, incompatible avec les actions IBKR "
            "(bougies journalieres uniquement) - choisis 'dip_bounce_daily', 'trend_regime', 'sma_cross', "
            "'scalp_dip' ou 'buy_and_hold', qui laissent le timeframe libre ou imposent deja le journalier"
        )

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
    # strategies. slope_dip (2026-09-16) : meme logique - "on garde l'ordre,
    # seul le trailing vend" est la demande explicite, le stop-loss reste un
    # filet de securite optionnel, pas impose.
    if strategy_type == "buy_and_hold":
        stop_loss_pct = None
    else:
        stop_loss_raw = payload.get("stop_loss_pct")
        if strategy_type in ("dip_bounce_hourly", "dip_bounce_minute", "slope_dip", "dip_bounce_daily", "trend_regime") and stop_loss_raw in (None, ""):
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
        "exchange": "ibkr_paper" if is_ibkr else "binance",
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


class ManualOrderError(Exception):
    pass


def execute_manual_order(payload: dict) -> tuple[int, dict]:
    """Ordre au marche du panier manuel sur le testnet (EF-81), partage par
    l'onglet Manuel et par les alertes TradingView (EF-87) : un seul chemin,
    donc les memes garde-fous (cash du panier, solde testnet reel, vente
    plafonnee a la position). L'ordre part REELLEMENT via `PaperExecutor`, le
    meme code que les bots. Renvoie (code HTTP, corps)."""
    from dotenv import load_dotenv

    from tradingbot.execution.paper_executor import PaperExecutor
    from tradingbot.manual_trading import ManualBook

    symbol = str(payload.get("symbol", "")).upper().strip()
    side = str(payload.get("side", "")).lower()
    if "/" not in symbol or side not in ("buy", "sell"):
        return 400, {"error": "symbole (ex: ETH/USDT) et cote (buy/sell) requis"}

    load_dotenv()
    api_key = os.environ.get("BINANCE_TESTNET_API_KEY", "")
    api_secret = os.environ.get("BINANCE_TESTNET_API_SECRET", "")
    try:
        executor = PaperExecutor("binance", symbol, api_key, api_secret)
        price = float(executor.exchange.fetch_ticker(symbol)["last"])
    except Exception as e:
        return 400, {"error": f"testnet injoignable ou paire inconnue : {e}"}

    book = ManualBook()
    reason = str(payload.get("reason") or "manuel")[:80]   # EF-90 : stop-loss, conditionnel #n...
    try:
        if side == "buy":
            amount = float(payload.get("amount", 0) or 0)
            quote = symbol.split("/")[1]
            free = executor.exchange.fetch_balance().get(quote, {}).get("free")
            report = book.buy(symbol, amount, price, executor,
                              free_quote_on_exchange=float(free) if free is not None else None, reason=reason)
        else:
            raw_qty = payload.get("quantity")
            quantity = None if raw_qty in (None, "", "all") else float(raw_qty)
            report = book.sell(symbol, quantity, price, executor, reason=reason)
    except Exception as e:
        return 500, {"error": f"echec de l'ordre : {e}"}

    return 200, {
        "status": report.status, "symbol": report.symbol, "side": report.side,
        "quantity": report.quantity, "price": report.price, "fee": report.fee,
        "reason": report.reason, "cash_after": report.cash_after, "warnings": report.warnings,
    }


# ----------------------------------------------------------------------------
# Alertes TradingView (EF-87)
# ----------------------------------------------------------------------------
TV_SECRET_ENV = "TRADINGVIEW_WEBHOOK_SECRET"
TV_AUTO_ORDERS_ENV = "TRADINGVIEW_AUTO_ORDERS"
TV_MAX_ORDER_ENV = "TRADINGVIEW_MAX_ORDER_USDT"
TV_ALLOWED_IPS_ENV = "TRADINGVIEW_ALLOWED_IPS"
TV_DEFAULT_MAX_ORDER_USDT = 100.0


def tv_settings() -> dict:
    load_dotenv()
    try:
        max_order = float(os.environ.get(TV_MAX_ORDER_ENV, TV_DEFAULT_MAX_ORDER_USDT))
    except ValueError:
        max_order = TV_DEFAULT_MAX_ORDER_USDT
    allowed = [ip.strip() for ip in os.environ.get(TV_ALLOWED_IPS_ENV, "").split(",") if ip.strip()]
    return {
        "secret": os.environ.get(TV_SECRET_ENV, ""),
        "auto_orders": os.environ.get(TV_AUTO_ORDERS_ENV, "0").strip().lower() in ("1", "true", "oui", "yes"),
        "max_order_usdt": max_order,
        "allowed_ips": allowed,
    }


# ----------------------------------------------------------------------------
# Surveillant du panier manuel (EF-90)
# ----------------------------------------------------------------------------
WATCHER_STATUS = {"running": False, "last_cycle": None, "last_error": None, "events": []}
WATCH_LOG_PATH = ROOT / "logs" / "manual_watch.log"


def _watch_log(message: str) -> None:
    try:
        WATCH_LOG_PATH.parent.mkdir(exist_ok=True)
        with open(WATCH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def manual_watcher_loop(stop_event: threading.Event, interval: float | None = None) -> None:
    """Execute les ordres conditionnels et les protections du panier manuel,
    independamment de tout bot. Une erreur d'un passage est journalisee et le
    passage suivant a lieu quand meme : le surveillant ne doit jamais mourir en
    silence (lecon d'EF-85)."""
    from tradingbot.manual_trading import ManualBook
    from tradingbot.manual_watch import WATCH_INTERVAL_SECONDS, ConditionalOrders, PositionRisk, watch_cycle

    interval = interval or WATCH_INTERVAL_SECONDS
    WATCHER_STATUS["running"] = True
    _watch_log("surveillant du panier manuel demarre")
    while not stop_event.is_set():
        try:
            events = watch_cycle(ManualBook(), ConditionalOrders(), PositionRisk(),
                                 manual_last_price, execute_manual_order)
            WATCHER_STATUS["last_cycle"] = time.strftime("%Y-%m-%d %H:%M:%S")
            WATCHER_STATUS["last_error"] = None
            for event in events:
                _watch_log(event)
            if events:
                WATCHER_STATUS["events"] = (events + WATCHER_STATUS["events"])[:20]
        except Exception as e:
            WATCHER_STATUS["last_error"] = f"{type(e).__name__}: {e}"
            _watch_log(f"ERREUR du passage : {type(e).__name__}: {e}")
        stop_event.wait(interval)
    WATCHER_STATUS["running"] = False


def manual_symbol_state(symbol: str) -> dict:
    """Tout ce que l'Espace Trading affiche pour une paire du panier manuel."""
    from tradingbot.manual_trading import ManualBook
    from tradingbot.manual_watch import ConditionalOrders, PositionRisk

    book = ManualBook()
    held = book.positions().get(symbol)
    try:
        price = manual_last_price(symbol)
    except Exception:
        price = None
    summary = book.summary({symbol: price} if price else {})
    position = None
    if held:
        quantity, avg = held
        position = {"quantity": quantity, "avg_price": avg,
                    "value": quantity * price if price else None,
                    "pnl": (price - avg) * quantity if price else None}
    return {
        "symbol": symbol, "price": price, "cash": summary["cash"], "deposited": summary["deposited"],
        "position": position, "risk": PositionRisk().get(symbol),
        "orders": ConditionalOrders().recent(symbol, 30), "fills": book.fills(symbol),
        "watcher": {k: WATCHER_STATUS[k] for k in ("running", "last_cycle", "last_error")},
    }


# ----------------------------------------------------------------------------
# Page Trading (EF-89)
# ----------------------------------------------------------------------------
TRADING_PAGE_PATH = Path(__file__).resolve().parent / "reporting" / "static" / "trading.html"
CANDLE_TIMEFRAMES = ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w")
_candles_cache: dict[tuple, tuple[float, list]] = {}


def fetch_candles(symbol: str, timeframe: str, limit: int, exchange=None) -> list[list]:
    """Bougies [t, ouverture, haut, bas, cloture, volume] du marche PUBLIC (le
    testnet n'a que ~14 jours d'historique, EF-83). Unite de temps limitee a
    une liste connue ; cache de 5 s pour ne pas marteler l'exchange."""
    if timeframe not in CANDLE_TIMEFRAMES:
        raise ValueError(f"unite de temps inconnue : {timeframe}")
    limit = max(10, min(1000, int(limit)))
    key = (symbol, timeframe, limit)
    cached = _candles_cache.get(key)
    if cached is not None and time.time() - cached[0] < 5:
        return cached[1]
    rows = (exchange or _public_exchange).fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    candles = [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5] or 0)] for r in rows]
    _candles_cache[key] = (time.time(), candles)
    return candles


def read_bot_dashboard_data(name: str) -> dict:
    """Etat publie par le bot a chaque cycle (dashboard_data/{name}.js). Vide
    si le bot n'a encore jamais tourne."""
    path = ROOT / "dashboard_data" / f"{name}.js"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text.split("] = ", 1)[1].rstrip().rstrip(";"))
    except (IndexError, ValueError):
        return {}


def bot_state(name: str) -> dict | None:
    """Tout ce que la page Trading affiche pour un bot, ou None s'il n'existe pas."""
    path = get_config_path_for_name(name)
    if path is None:
        return None
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    published = read_bot_dashboard_data(name)
    return {
        "name": name,
        "symbol": config.get("symbol"),
        "timeframe": config.get("timeframe"),
        "strategy_type": (config.get("strategy") or {}).get("type"),
        "risk": config.get("risk") or {},
        "running": is_bot_running(name),
        "current_price": published.get("current_price"),
        "orders": published.get("orders") or [],
        "chart_levels": published.get("chart_levels") or [],
        "open_positions_count": published.get("open_positions_count"),
        "updated_at": published.get("updated_at"),
    }


def bot_trigger_store(name: str):
    """Registre des ordres declenches d'un bot EXISTANT, ou None. Le nom est
    verifie contre les configs connues : il sert a construire un chemin de
    fichier, il ne doit jamais pouvoir designer autre chose qu'une base de bot."""
    from tradingbot.manual_triggers import TriggerStore
    from tradingbot.reporting.logger import DATA_DIR

    if not name or get_config_path_for_name(name) is None:
        return None
    return TriggerStore(DATA_DIR / f"{name}.db")


def run_alert_order_in_background(store, alert_id: int, plan: dict) -> threading.Thread:
    """TradingView abandonne l'appel au-dela de 3 secondes, alors qu'un ordre
    testnet (cours, solde, ordre) peut les depasser : on a deja repondu,
    l'ordre part ici, et son resultat est rattache a l'alerte."""
    def work():
        try:
            status, body = execute_manual_order(plan)
            if status == 200 and body.get("status") == "filled":
                store.set_order_outcome(alert_id, "execute",
                                        f"{body['side']} {body['quantity']} {body['symbol']} a {body['price']}")
            else:
                store.set_order_outcome(alert_id, "refuse", body.get("reason") or body.get("error") or str(body))
        except Exception as e:  # jamais d'exception perdue en silence dans un thread
            store.set_order_outcome(alert_id, "erreur", f"{type(e).__name__}: {e}")
    thread = threading.Thread(target=work, daemon=True, name=f"tv-alert-{alert_id}")
    thread.start()
    return thread


def handle_tradingview_alert(body: bytes, url_token: str | None, source_ip: str | None,
                             settings: dict | None = None, store=None, background=True) -> tuple[int, dict]:
    """Traitement complet d'un appel de webhook, sans dependre du serveur HTTP
    (testable directement). Renvoie (code HTTP, corps) en quelques
    millisecondes : l'eventuel ordre part en arriere-plan."""
    from tradingbot.tv_alerts import AlertRejected, AlertStore, auto_order_plan, parse_alert

    settings = settings or tv_settings()
    if settings["allowed_ips"] and source_ip not in settings["allowed_ips"]:
        return 403, {"error": "adresse d'origine non autorisee"}
    try:
        alert = parse_alert(body, settings["secret"], url_token)
    except AlertRejected as e:
        return e.status, {"error": e.reason}

    store = store or AlertStore()
    alert_id = store.record(alert, source_ip)
    plan, why = auto_order_plan(alert, settings["auto_orders"], settings["max_order_usdt"])
    if plan is None:
        store.set_order_outcome(alert_id, "aucun", why)
        return 200, {"status": "recue", "id": alert_id, "order": None, "detail": why}
    store.set_order_outcome(alert_id, "en cours", why)
    if background:
        run_alert_order_in_background(store, alert_id, plan)
    return 200, {"status": "recue", "id": alert_id, "order": "en cours", "detail": why}


class Handler(BaseHTTPRequestHandler):
    # ------------------------------------------------------------------
    # Acces reseau (EF-82)
    # ------------------------------------------------------------------

    def _client_is_loopback(self) -> bool:
        host = self.client_address[0] if self.client_address else ""
        return host in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def _authorized(self) -> bool:
        """Vrai si la requete peut etre servie. Sinon la reponse (401/403)
        est deja envoyee. Toute route, statique ou API, passe par ici."""
        if self._client_is_loopback():
            return True
        password = os.environ.get(PASSWORD_ENV, "")
        if not password:
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "Acces reseau refuse : aucun mot de passe n'est defini. Ajoute "
                f"{PASSWORD_ENV}=... dans le fichier .env du serveur, puis relance-le.".encode("utf-8")
            )
            return False
        user = os.environ.get(USER_ENV, DEFAULT_USER)
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                given = base64.b64decode(header[6:].strip()).decode("utf-8")
            except Exception:
                given = ""
            if hmac.compare_digest(given.encode(), f"{user}:{password}".encode()):
                return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Trading Bot"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Identifiants requis.".encode("utf-8"))
        return False

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
        # EF-87 : TradingView ne peut envoyer ni en-tete ni identifiant HTTP
        # Basic - la route du webhook est donc la SEULE a passer avant
        # `_authorized`, et elle porte sa propre authentification (secret
        # dans le corps ou dans l'adresse, voir tv_alerts.parse_alert).
        if urlsplit(self.path).path == "/api/tv-webhook":
            length = min(int(self.headers.get("Content-Length", 0) or 0), 100_000)
            token = (parse_qs(urlsplit(self.path).query).get("token") or [None])[0]
            status, body = handle_tradingview_alert(
                self.rfile.read(length), token, self.client_address[0] if self.client_address else None,
            )
            self._send_json(status, body)
            return
        if not self._authorized():
            return
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
            "/api/dca-run": self._handle_dca_run,
            "/api/dca-save": self._handle_dca_save,
            "/api/dca-delete": self._handle_dca_delete,
            "/api/dca-sell": self._handle_dca_sell,
            "/api/dca-reset": self._handle_dca_reset,
            "/api/dca-contribution": self._handle_dca_contribution,
            "/api/manual-order": self._handle_manual_order,
            "/api/tv-test": self._handle_tv_test,
            "/api/bot-trigger": self._handle_bot_trigger,
            "/api/bot-trigger-cancel": self._handle_bot_trigger_cancel,
            "/api/bot-risk": self._handle_bot_risk,
            "/api/manual-conditional": self._handle_manual_conditional,
            "/api/manual-conditional-cancel": self._handle_manual_conditional_cancel,
            "/api/manual-risk": self._handle_manual_risk,
            "/api/manual-deposit": self._handle_manual_deposit,
            "/api/manual-reset": self._handle_manual_reset,
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

        chart_data: dict = {}
        try:
            args = build_namespace_from_payload(payload)
            text, report_path = run_backtest_job(
                args, progress_callback=report_progress if job_id else None, chart_data_out=chart_data,
            )
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
        response = {"report": text, "report_path": report_path}
        if chart_data:
            response["chart"] = chart_data
        self._send_json(200, response)

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

    def _dca_config_or_404(self, name: str):
        """Retrouve une config de bot d'investissement, ou repond 404 et
        renvoie None - les trois actions manuelles partagent ce prealable."""
        from tradingbot.run_dca import list_dca_configs

        config = next((c for c in list_dca_configs() if c.name == name), None)
        if config is None:
            self._send_json(404, {"error": f"bot d'investissement '{name}' introuvable"})
            return None
        return config

    def _handle_dca_sell(self, payload: dict) -> None:
        """Vente manuelle, hors du cycle mensuel (EF-78). Engage de vrais
        ordres sur le compte PAPER : il n'existe pas de variante simulation
        ici, contrairement au passage mensuel - vendre est une decision
        ponctuelle de l'utilisateur, pas une routine a previsualiser."""
        from tradingbot.run_dca import db_path_for, format_run_report, sell_lines

        config = self._dca_config_or_404(payload.get("name", ""))
        if config is None:
            return

        raw = payload.get("lines") or {}
        requests = {}
        for symbol, quantity in raw.items():
            if symbol not in config.weights:
                self._send_json(400, {"error": f"{symbol} ne fait pas partie de ce bot"})
                return
            try:
                requests[symbol] = float(quantity) if quantity not in (None, "", "all") else 0.0
            except (TypeError, ValueError):
                self._send_json(400, {"error": f"quantite invalide pour {symbol}"})
                return
        if not requests:
            self._send_json(400, {"error": "aucune ligne a vendre"})
            return

        try:
            from tradingbot.execution.ib_multi_symbol_executor import IBMultiSymbolExecutor

            executor = IBMultiSymbolExecutor(
                symbols=list(config.weights), host=config.ibkr_host,
                port=config.ibkr_port, client_id=config.ibkr_client_id,
            )
        except Exception as e:
            self._send_json(400, {"error": str(e)})
            return

        try:
            report = sell_lines(
                config, db_path_for(config.name), requests, executor,
                ignore_position_mismatch=bool(payload.get("ignore_position_mismatch")),
            )
        except Exception as e:
            self._send_json(500, {"error": f"echec de la vente : {e}"})
            return
        finally:
            executor.disconnect()

        self._send_json(200, {"status": "ok", "report": format_run_report(report, config)})

    def _handle_dca_reset(self, payload: dict) -> None:
        """Remet le registre du bot a zero. **Ne vend rien** : les titres
        restent chez le courtier, et la reconciliation bloquera donc le bot
        jusqu'a ce qu'ils soient vendus. L'historique est sauvegarde, jamais
        supprime."""
        from tradingbot.run_dca import db_path_for, reset_state

        config = self._dca_config_or_404(payload.get("name", ""))
        if config is None:
            return
        try:
            backup = reset_state(db_path_for(config.name))
        except Exception as e:
            self._send_json(500, {"error": f"echec de la remise a zero : {e}"})
            return
        if backup is None:
            self._send_json(200, {"status": "ok", "message": "Ce bot n'avait jamais tourne : rien a remettre a zero."})
            return
        self._send_json(200, {
            "status": "ok",
            "message": f"Registre remis a zero. Historique sauvegarde dans {backup.name}. "
                       "Les titres detenus chez le courtier n'ont PAS ete vendus : "
                       "vends-les, sinon le bot refusera de passer des ordres (ecart de positions).",
        })

    def _handle_dca_contribution(self, payload: dict) -> None:
        """Change le plafond de versement mensuel. Modifie uniquement ce
        champ du YAML, sans toucher au reste de la config."""
        from tradingbot.run_dca import DCA_CONFIG_DIR, set_monthly_contribution

        config = self._dca_config_or_404(payload.get("name", ""))
        if config is None:
            return
        config_path = DCA_CONFIG_DIR / f"{config.name}.yml"
        if not config_path.is_file():
            self._send_json(404, {"error": f"fichier de config introuvable pour '{config.name}'"})
            return
        try:
            amount = set_monthly_contribution(config_path, float(payload.get("monthly_contribution")))
        except (TypeError, ValueError) as e:
            self._send_json(400, {"error": f"montant invalide : {e}"})
            return
        except Exception as e:
            self._send_json(500, {"error": f"echec de l'enregistrement : {e}"})
            return
        self._send_json(200, {"status": "ok", "monthly_contribution": amount})

    # ------------------------------------------------------------------
    # Panier de trading manuel (EF-81) - testnet Binance, argent fictif
    # ------------------------------------------------------------------

    def _handle_manual_order(self, payload: dict) -> None:
        """Achat ou vente au marche sur le testnet, depuis l'onglet Manuel."""
        status, body = execute_manual_order(payload)
        self._send_json(status, body)

    def _handle_bot_trigger(self, payload: dict) -> None:
        """Pose un ordre "acheter si le cours descend sous X" sur un bot (EF-88).
        Le bot le verifie a chaque passage de sa boucle et l'execute lui-meme."""
        name = str(payload.get("name", ""))
        store = bot_trigger_store(name)
        if store is None:
            self._send_json(404, {"error": f"bot '{name}' introuvable"})
            return
        try:
            price = float(payload.get("price"))
            # EF-89 : ventes (au-dessus = prise de profit, en dessous = stop) en plus
            # de l'achat sous un prix ; par defaut, l'achat d'EF-88.
            side = str(payload.get("side") or "buy")
            direction = str(payload.get("direction") or "below")
            trigger_id = store.add(side, direction, price)
        except (TypeError, ValueError) as e:
            self._send_json(400, {"error": f"ordre invalide : {e}"})
            return
        self._send_json(200, {"status": "ok", "id": trigger_id, "price": price, "side": side, "direction": direction})

    def _handle_manual_conditional(self, payload: dict) -> None:
        """Ordre conditionnel du panier manuel (EF-90), execute par le surveillant."""
        from tradingbot.manual_watch import ConditionalOrders

        try:
            order_id = ConditionalOrders().add(
                payload.get("symbol", ""), str(payload.get("side") or ""), str(payload.get("direction") or ""),
                payload.get("price"), payload.get("amount"),
                None if payload.get("quantity") in (None, "", "all") else payload.get("quantity"),
            )
        except (TypeError, ValueError) as e:
            self._send_json(400, {"error": f"ordre invalide : {e}"})
            return
        self._send_json(200, {"status": "ok", "id": order_id})

    def _handle_manual_conditional_cancel(self, payload: dict) -> None:
        from tradingbot.manual_watch import ConditionalOrders

        try:
            cancelled = ConditionalOrders().cancel(int(payload.get("id")))
        except (TypeError, ValueError):
            self._send_json(400, {"error": "identifiant invalide"})
            return
        if not cancelled:
            self._send_json(409, {"error": "ordre deja execute, refuse ou annule : rien a annuler"})
            return
        self._send_json(200, {"status": "annule"})

    def _handle_manual_risk(self, payload: dict) -> None:
        """Protections de la position du panier manuel sur une paire (EF-90).
        Memes bornes que pour les bots (`validate_risk_updates`)."""
        from tradingbot.config_edit import validate_risk_updates
        from tradingbot.manual_watch import PositionRisk

        symbol = str(payload.get("symbol", "")).upper().strip()
        if "/" not in symbol:
            self._send_json(400, {"error": "paire attendue sous la forme ETH/USDT"})
            return
        raw = {k: payload.get(k) for k in PositionRisk.FIELDS if k in payload}
        try:
            clean = validate_risk_updates(raw)
        except (TypeError, ValueError) as e:
            self._send_json(400, {"error": str(e)})
            return
        self._send_json(200, {"status": "ok", "risk": PositionRisk().set(symbol, clean)})

    def _handle_bot_risk(self, payload: dict) -> None:
        """Change les reglages de risque d'un bot depuis la page Trading (EF-89).
        Seules les lignes concernees du bloc `risk:` sont reecrites
        (commentaires conserves), puis le bot est relance s'il tournait : il ne
        relit sa config qu'au demarrage. Ses positions ouvertes sont restaurees
        a la relance, pas vendues."""
        from tradingbot.config_edit import update_risk_block, validate_risk_updates

        name = str(payload.get("name", ""))
        path = get_config_path_for_name(name)
        if path is None:
            self._send_json(404, {"error": f"bot '{name}' introuvable"})
            return
        try:
            updates = validate_risk_updates(payload.get("risk") or {})
            if not updates:
                self._send_json(400, {"error": "aucun reglage a modifier"})
                return
            new_text = update_risk_block(path.read_text(encoding="utf-8"), updates)
            yaml.safe_load(new_text)  # jamais de config illisible ecrite sur le disque
        except (TypeError, ValueError, yaml.YAMLError) as e:
            self._send_json(400, {"error": str(e)})
            return

        was_running = is_bot_running(name)
        if was_running:
            self._kill_by_name(name)
            time.sleep(0.5)
        # Meme style de fin de ligne que le fichier d'origine. En mode texte,
        # Windows ecrit des fins de ligne CRLF : un fichier en fins de ligne
        # Unix serait converti EN ENTIER pour une modification d'une ligne.
        newline = "\r\n" if b"\r\n" in path.read_bytes() else "\n"
        path.write_text(new_text, encoding="utf-8", newline=newline)
        if was_running:
            ok, error = launch_process(path, name)
            if not ok:
                self._send_json(500, {"error": f"reglages enregistres, mais le bot a plante au redemarrage : {error}"})
                return
        self._send_json(200, {"status": "ok", "applied": updates, "restarted": was_running})

    def _handle_bot_trigger_cancel(self, payload: dict) -> None:
        store = bot_trigger_store(str(payload.get("name", "")))
        if store is None:
            self._send_json(404, {"error": "bot introuvable"})
            return
        try:
            cancelled = store.cancel(int(payload.get("id")))
        except (TypeError, ValueError):
            self._send_json(400, {"error": "identifiant invalide"})
            return
        if not cancelled:
            self._send_json(409, {"error": "ordre deja execute, refuse ou annule : rien a annuler"})
            return
        self._send_json(200, {"status": "annule"})

    def _handle_tv_test(self, payload: dict) -> None:
        """Simule une alerte depuis le dashboard (utilisateur deja authentifie),
        pour verifier la chaine sans compte TradingView. Passe par le meme
        traitement qu'une vraie alerte, secret compris."""
        settings = tv_settings()
        if not settings["secret"]:
            self._send_json(400, {"error": f"definis d'abord {TV_SECRET_ENV} dans .env, puis relance le serveur"})
            return
        body = json.dumps({
            "secret": settings["secret"],
            "ticker": payload.get("ticker") or "BINANCE:ETHUSDT",
            "action": payload.get("action") or "test",
            "price": payload.get("price"),
            "message": "Alerte de test envoyee depuis le dashboard",
        }).encode()
        status, result = handle_tradingview_alert(body, None, "dashboard")
        self._send_json(status, result)

    def _handle_manual_deposit(self, payload: dict) -> None:
        from tradingbot.manual_trading import ManualBook

        try:
            cash = ManualBook().deposit(float(payload.get("amount", 0)))
        except (TypeError, ValueError) as e:
            self._send_json(400, {"error": f"montant invalide : {e}"})
            return
        self._send_json(200, {"status": "ok", "cash": cash})

    def _handle_manual_reset(self, payload: dict) -> None:
        from tradingbot.manual_trading import ManualBook

        backup = ManualBook().reset()
        self._send_json(200, {
            "status": "ok",
            "message": "Le panier n'avait jamais servi : rien a remettre a zero." if backup is None else
                       f"Panier remis a zero, historique sauvegarde dans {backup.name}. "
                       "Les cryptos detenues n'ont PAS ete vendues sur le testnet.",
        })

    def _handle_dca_run(self, payload: dict) -> None:
        """Lance un bot d'investissement regulier. `execute=false` (defaut)
        = simulation : rien n'est envoye au courtier, rien n'ecrit en base.
        Passer de vrais ordres exige `execute=true` ET une connexion
        TWS/IB Gateway joignable en mode PAPER."""
        from tradingbot.run_dca import (
            DcaConfig,
            db_path_for,
            format_run_report,
            list_dca_configs,
            run_once,
        )

        name = payload.get("name", "")
        execute = bool(payload.get("execute"))
        config = next((c for c in list_dca_configs() if c.name == name), None)
        if config is None:
            self._send_json(404, {"error": f"bot d'investissement '{name}' introuvable"})
            return

        executor = None
        if execute:
            try:
                from tradingbot.execution.ib_multi_symbol_executor import IBMultiSymbolExecutor

                executor = IBMultiSymbolExecutor(
                    symbols=list(config.weights), host=config.ibkr_host,
                    port=config.ibkr_port, client_id=config.ibkr_client_id,
                )
            except Exception as e:
                self._send_json(400, {"error": str(e)})
                return
        try:
            report = run_once(
                config, db_path_for(config.name), executor=executor, dry_run=not execute,
                ignore_position_mismatch=bool(payload.get("ignore_position_mismatch")),
            )
        except Exception as e:
            self._send_json(500, {"error": f"echec du passage : {e}"})
            return
        finally:
            if executor is not None:
                executor.disconnect()

        self._send_json(200, {
            "report": format_run_report(report, config),
            "dry_run": report.dry_run,
            "orders": [
                {"symbol": o.symbol, "side": o.side, "quantity": o.quantity,
                 "price": o.reference_price, "reason": o.reason}
                for o in report.planned
            ],
            "contribution": report.contribution,
            "warnings": report.warnings,
        })

    def _handle_dca_save(self, payload: dict) -> None:
        from tradingbot.run_dca import DCA_CONFIG_DIR, DcaConfig

        name = str(payload.get("name", "")).strip()
        if not name or not all(c.isalnum() or c in "_-" for c in name):
            self._send_json(400, {"error": "nom invalide (lettres, chiffres, tiret et souligne uniquement)"})
            return
        try:
            weights = {
                str(symbol).strip().upper(): float(weight)
                for symbol, weight in (payload.get("weights") or {}).items()
                if str(symbol).strip() and float(weight) > 0
            }
        except (TypeError, ValueError):
            self._send_json(400, {"error": "poids invalides"})
            return
        if not weights:
            self._send_json(400, {"error": "il faut au moins une ligne avec un poids positif"})
            return

        config = {"name": name, "weights": weights}
        for key, caster in (
            ("monthly_contribution", float), ("rebalance_band_pct", float),
            ("min_rebalance_interval_days", int), ("min_order_value", float),
            ("fee_pct", float), ("fee_fixed", float),
            ("follow_drift_on_contribution", bool), ("ibkr_host", str),
            ("ibkr_port", int), ("ibkr_client_id", int),
        ):
            if payload.get(key) is not None:
                try:
                    config[key] = caster(payload[key])
                except (TypeError, ValueError):
                    self._send_json(400, {"error": f"valeur invalide pour {key}"})
                    return
        if config.get("ibkr_port") in (7496, 4001):
            self._send_json(400, {
                "error": "les ports 7496 et 4001 sont ceux du compte REEL chez Interactive Brokers - "
                         "ce bot n'est autorise qu'en mode paper (7497 TWS, 4002 IB Gateway)"
            })
            return

        try:
            DcaConfig.from_yaml_dict(config)
        except (ValueError, TypeError) as e:
            self._send_json(400, {"error": str(e)})
            return

        DCA_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        path = DCA_CONFIG_DIR / f"{name}.yml"
        path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self._send_json(200, {"status": "enregistre", "name": name})

    def _handle_dca_delete(self, payload: dict) -> None:
        """Supprime la config MAIS conserve la base d'historique : un
        versement deja effectue sur le compte paper ne disparait pas parce
        qu'on retire le bot de l'interface."""
        from tradingbot.run_dca import DCA_CONFIG_DIR, db_path_for

        name = str(payload.get("name", "")).strip()
        path = DCA_CONFIG_DIR / f"{name}.yml"
        if not name or not path.is_file():
            self._send_json(404, {"error": "bot d'investissement introuvable"})
            return
        path.unlink()
        self._send_json(200, {
            "status": "supprime", "name": name,
            "note": f"historique conserve dans {db_path_for(name)}",
        })

    def _kill_by_name(self, name: str) -> None:
        kill_by_name(name)

    def do_GET(self) -> None:
        if not self._authorized():
            return
        if self.path == "/api/list-configs":
            self._send_json(200, {"configs": list_known_configs()})
            return

        if self.path == "/api/dca-bots":
            from tradingbot.run_dca import db_path_for, list_dca_configs, read_state_summary

            bots = []
            for config in list_dca_configs():
                summary = read_state_summary(config, db_path_for(config.name))
                summary["config"] = {
                    "name": config.name,
                    "weights": config.weights,
                    "monthly_contribution": config.monthly_contribution,
                    "rebalance_band_pct": config.rebalance_band_pct,
                    "min_rebalance_interval_days": config.min_rebalance_interval_days,
                    "min_order_value": config.min_order_value,
                    "fee_pct": config.fee_pct,
                    "fee_fixed": config.fee_fixed,
                    "follow_drift_on_contribution": config.follow_drift_on_contribution,
                    "ibkr_host": config.ibkr_host,
                    "ibkr_port": config.ibkr_port,
                    "ibkr_client_id": config.ibkr_client_id,
                }
                bots.append(summary)
            self._send_json(200, {"bots": bots})
            return

        if self.path.startswith("/api/dca-price-history"):
            # PAS d'import local de `parse_qs` ici : un `from urllib.parse
            # import parse_qs` dans cette fonction en ferait une variable
            # LOCALE de tout `do_GET`, et la route /api/price-history plus
            # bas (qui ne passe pas par ce bloc) planterait en
            # UnboundLocalError sans repondre - c'est exactement ce qui a
            # casse le graphique des cryptos (EF-80). Le module importe deja
            # `parse_qs` et `urlsplit` en tete de fichier.
            from tradingbot.run_dca import db_path_for, list_dca_configs, read_price_history

            params = parse_qs(urlsplit(self.path).query)
            name = (params.get("name") or [""])[0]
            try:
                days = max(7, min(1825, int((params.get("days") or ["180"])[0])))
            except ValueError:
                days = 180
            config = next((c for c in list_dca_configs() if c.name == name), None)
            if config is None:
                self._send_json(404, {"error": f"bot d'investissement '{name}' introuvable"})
                return
            try:
                self._send_json(200, read_price_history(config, db_path_for(config.name), days=days))
            except Exception as e:
                self._send_json(500, {"error": f"historique indisponible : {e}"})
            return

        if urlsplit(self.path).path == "/trading.html":
            try:
                body = TRADING_PAGE_PATH.read_bytes()
            except OSError:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path.startswith("/api/candles"):
            query = parse_qs(urlsplit(self.path).query)
            symbol = unquote((query.get("symbol") or [""])[0]).upper()
            try:
                candles = fetch_candles(symbol, (query.get("timeframe") or ["1h"])[0],
                                        int((query.get("limit") or ["500"])[0]))
            except Exception as e:
                self._send_json(400, {"error": f"bougies indisponibles : {e}"})
                return
            self._send_json(200, {"symbol": symbol, "candles": candles})
            return

        if self.path.startswith("/api/manual-state"):
            symbol = unquote((parse_qs(urlsplit(self.path).query).get("symbol") or [""])[0]).upper()
            if "/" not in symbol:
                self._send_json(400, {"error": "paire attendue sous la forme ETH/USDT"})
                return
            self._send_json(200, manual_symbol_state(symbol))
            return

        if self.path.startswith("/api/bot-state"):
            name = unquote((parse_qs(urlsplit(self.path).query).get("name") or [""])[0])
            state = bot_state(name)
            if state is None:
                self._send_json(404, {"error": f"bot '{name}' introuvable"})
                return
            self._send_json(200, state)
            return

        if self.path.startswith("/api/bot-triggers"):
            name = unquote((parse_qs(urlsplit(self.path).query).get("name") or [""])[0])
            store = bot_trigger_store(name)
            if store is None:
                self._send_json(404, {"error": f"bot '{name}' introuvable"})
                return
            self._send_json(200, {"triggers": store.recent(20)})
            return

        if self.path == "/api/tv-alerts":
            from tradingbot.tv_alerts import AlertStore

            settings = tv_settings()
            self._send_json(200, {
                "enabled": bool(settings["secret"]),
                "auto_orders": settings["auto_orders"],
                "max_order_usdt": settings["max_order_usdt"],
                "ip_filter": bool(settings["allowed_ips"]),
                "alerts": AlertStore().recent(50),
            })
            return

        if self.path == "/api/manual-book":
            from tradingbot.manual_trading import ManualBook

            book = ManualBook()
            held = list(book.positions())
            prices = {}
            for symbol in held:
                try:
                    prices[symbol] = manual_last_price(symbol)
                except Exception:
                    pass  # une paire sans cours reste affichee, sans valorisation
            self._send_json(200, book.summary(prices))
            return

        if self.path.startswith("/api/manual-price"):
            query = parse_qs(urlsplit(self.path).query)
            symbol = unquote(query.get("symbol", [""])[0]).upper()
            try:
                self._send_json(200, {"symbol": symbol, "price": manual_last_price(symbol)})
            except Exception as e:
                self._send_json(400, {"error": f"cours indisponible pour {symbol} : {e}"})
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


def local_ip_addresses() -> list[str]:
    """Adresses IP locales non-loopback, pour afficher a l'utilisateur ou
    taper depuis son telephone. Meilleur effort : une machine sans reseau
    renvoie une liste vide, jamais une erreur."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except Exception:
        pass
    try:
        # L'adresse utilisee pour sortir vers le reseau, sans rien envoyer.
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("10.255.255.255", 1))
        ips.add(probe.getsockname()[0])
        probe.close()
    except Exception:
        pass
    return sorted(ips)


class TLSThreadingHTTPServer(ThreadingHTTPServer):
    """Serveur HTTPS (EF-86). La poignee de main TLS se fait dans le thread
    de la requete (`finish_request`) et non dans `accept()` : chiffrer la
    socket d'ecoute la ferait dans la boucle principale, ou un seul client
    lent ou un navigateur parlant HTTP en clair bloquerait tout le serveur."""

    def __init__(self, server_address, handler_class, ssl_context: ssl.SSLContext):
        self.ssl_context = ssl_context
        super().__init__(server_address, handler_class)

    def finish_request(self, request, client_address) -> None:
        request.settimeout(TLS_HANDSHAKE_TIMEOUT_S)
        try:
            tls_request = self.ssl_context.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError):
            # Client en HTTP clair, certificat refuse, delai depasse : rien a
            # servir, et surtout pas de trace d'erreur a chaque tentative.
            return
        try:
            tls_request.settimeout(None)
            super().finish_request(tls_request, client_address)
        finally:
            # `wrap_socket` detache la socket d'origine : c'est la socket TLS
            # qu'il faut fermer, `shutdown_request` ne la connait pas.
            try:
                tls_request.close()
            except OSError:
                pass


def tls_context_from_env() -> ssl.SSLContext | None:
    """Contexte TLS si DASHBOARD_TLS_CERT et DASHBOARD_TLS_KEY sont definis,
    None si aucun des deux ne l'est. Leve ValueError (message pret a
    afficher) sur une configuration incomplete ou illisible."""
    cert = os.environ.get(TLS_CERT_ENV, "").strip()
    key = os.environ.get(TLS_KEY_ENV, "").strip()
    if not cert and not key:
        return None
    if not cert or not key:
        missing = TLS_KEY_ENV if cert else TLS_CERT_ENV
        raise ValueError(
            f"HTTPS a moitie configure : {missing} est vide. Renseigne les deux "
            f"({TLS_CERT_ENV} et {TLS_KEY_ENV}) ou aucun."
        )
    cert_path, key_path = Path(cert), Path(key)
    if not cert_path.is_absolute():
        cert_path = ROOT / cert_path
    if not key_path.is_absolute():
        key_path = ROOT / key_path
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    except (OSError, ssl.SSLError) as exc:
        raise ValueError(
            f"certificat HTTPS illisible ({cert_path}, {key_path}) : {exc}. "
            "Genere-le avec scripts/generate_dashboard_cert.sh."
        ) from exc
    return context


def main() -> None:
    # CT-26 : deux instances de ce serveur ont deja tourne simultanement sur
    # le meme poste sans que rien ne le signale - `HTTPServer.allow_reuse_address`
    # (Windows) laisse une seconde instance capturer le port sans faire
    # echouer la premiere au demarrage, si bien que les requetes atterrissent
    # sur l'instance la plus recente meme si elle tourne du code perime.
    # Meme verrou atomique que les bots (`bot_{name}.lock`), applique ici a
    # ce process lui-meme plutot qu'a un bot nomme.
    acquire_lock(CONTROL_SERVER_LOCK_PATH)
    load_dotenv()
    bind_host = os.environ.get(BIND_HOST_ENV, DEFAULT_BIND_HOST)
    try:
        tls_context = tls_context_from_env()
    except ValueError as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        sys.exit(1)
    if tls_context is not None:
        server = TLSThreadingHTTPServer((bind_host, PORT), Handler, tls_context)
        scheme = "https"
    else:
        server = ThreadingHTTPServer((bind_host, PORT), Handler)
        scheme = "http"
    print(f"Serveur de controle demarre : {scheme}://localhost:{PORT}/dashboard.html")
    if bind_host not in ("localhost", "127.0.0.1", "::1"):
        for ip in local_ip_addresses():
            print(f"  depuis un autre appareil : {scheme}://{ip}:{PORT}/dashboard.html")
        if os.environ.get(PASSWORD_ENV, ""):
            print(f"  acces reseau protege par mot de passe (utilisateur '{os.environ.get(USER_ENV, DEFAULT_USER)}')")
            if tls_context is None:
                print(f"  note : sans HTTPS, ce mot de passe circule en clair sur le reseau ({TLS_CERT_ENV}/{TLS_KEY_ENV})")
        else:
            print(f"  ATTENTION : aucun {PASSWORD_ENV} dans .env - les autres appareils recevront un refus (403)")
    watcher_stop = threading.Event()
    threading.Thread(target=manual_watcher_loop, args=(watcher_stop,), daemon=True, name="manual-watcher").start()
    print("Surveillant du panier manuel actif (ordres conditionnels, stop-loss, trailing).")
    print("Ctrl+C pour arreter.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
