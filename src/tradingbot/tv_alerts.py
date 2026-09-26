"""Reception des alertes TradingView (EF-87).

TradingView ne fournit pas d'API pour recuperer ses analyses : l'analyse
s'ecrit en Pine Script, tourne sur ses serveurs, et declenche une ALERTE qui
peut appeler une adresse web (webhook). Ce module recoit cet appel, le
verifie, le range, et - seulement si l'utilisateur l'a explicitement active -
le transforme en ordre PAPER dans le panier manuel.

Contraintes imposees par TradingView (verifiees sur leur documentation le
2026-09-26), qui ont dicte la conception :
- aucun en-tete personnalise possible : le secret ne peut voyager que dans le
  CORPS du message (champ "secret") ou dans l'adresse (?token=...) ;
- reponse exigee en moins de 3 secondes, sinon l'appel est abandonne : un
  ordre testnet (plusieurs appels reseau) peut depasser ce delai, il est donc
  execute en ARRIERE-PLAN apres avoir repondu ;
- ports 80 et 443 uniquement, IPv4 uniquement, double authentification
  obligatoire sur le compte, et webhooks reserves aux abonnements payants
  superieurs.

Securite, par defaut ferme :
- sans TRADINGVIEW_WEBHOOK_SECRET dans .env, la route refuse tout (403) ;
- un secret faux ou absent est refuse (401), compare en temps constant ;
- les ordres automatiques sont DESACTIVES par defaut (TRADINGVIEW_AUTO_ORDERS)
  et plafonnes par alerte (TRADINGVIEW_MAX_ORDER_USDT) ; ils ne touchent que le
  panier manuel, jamais les bots ni le panier commun, et restent en paper.
"""

from __future__ import annotations

import hmac
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path("data/tv_alerts.db")
MAX_BODY_BYTES = 10_000
KNOWN_QUOTES = ("USDT", "USDC", "BUSD", "FDUSD", "EUR", "BTC", "ETH")

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        received_at TEXT NOT NULL,
        source_ip TEXT,
        ticker TEXT,
        action TEXT,
        price REAL,
        message TEXT,
        raw TEXT NOT NULL,
        order_status TEXT,
        order_detail TEXT
    );
"""


@dataclass
class Alert:
    ticker: str | None
    action: str | None
    price: float | None
    message: str | None
    amount: float | None
    quantity: float | str | None
    raw: str


class AlertRejected(Exception):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _to_float(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def parse_alert(body: bytes, secret: str, url_token: str | None = None) -> Alert:
    """Verifie et decode un appel de webhook. Leve `AlertRejected` avec le code
    HTTP a renvoyer. Accepte un corps JSON (recommande, porte le secret) ou du
    texte brut (le secret doit alors etre dans l'adresse, `?token=`)."""
    if not secret:
        raise AlertRejected(403, "reception des alertes TradingView desactivee : TRADINGVIEW_WEBHOOK_SECRET absent de .env")
    if len(body) > MAX_BODY_BYTES:
        raise AlertRejected(413, f"message trop long (> {MAX_BODY_BYTES} octets)")

    text = body.decode("utf-8", errors="replace").strip()
    data = None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            data = parsed
    except ValueError:
        pass

    given = (data or {}).get("secret") if data is not None else None
    if given is None:
        given = url_token
    if not isinstance(given, str) or not hmac.compare_digest(given.encode(), secret.encode()):
        raise AlertRejected(401, "secret absent ou invalide")

    if data is None:
        return Alert(ticker=None, action=None, price=None, message=text[:1000],
                     amount=None, quantity=None, raw=text)

    clean = {k: v for k, v in data.items() if k != "secret"}  # le secret n'est jamais stocke
    action = str(data.get("action", "")).strip().lower() or None
    return Alert(
        ticker=(str(data["ticker"]).strip() if data.get("ticker") else None),
        action=action,
        price=_to_float(data.get("price")),
        message=(str(data["message"])[:1000] if data.get("message") else None),
        amount=_to_float(data.get("amount")),
        quantity=(data.get("quantity") if str(data.get("quantity", "")).lower() == "all" else _to_float(data.get("quantity"))),
        raw=json.dumps(clean, ensure_ascii=False)[:MAX_BODY_BYTES],
    )


def tradingview_ticker_to_symbol(ticker: str | None) -> str | None:
    """"BINANCE:ETHUSDT" / "ETHUSDT" / "ETH/USDT" -> "ETH/USDT". None si la
    devise de cotation n'est pas reconnue : on prefere ne pas deviner une paire
    et passer un ordre sur le mauvais actif."""
    if not ticker:
        return None
    t = ticker.split(":")[-1].upper().strip()
    t = re.sub(r"\.P$|PERP$", "", t)  # contrats perpetuels : on vise le spot equivalent
    if "/" in t:
        base, quote = t.split("/", 1)
        return f"{base}/{quote}" if base and quote in KNOWN_QUOTES else None
    for quote in KNOWN_QUOTES:
        if t.endswith(quote) and len(t) > len(quote):
            return f"{t[: -len(quote)]}/{quote}"
    return None


class AlertStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.executescript(_SCHEMA)
        return connection

    def record(self, alert: Alert, source_ip: str | None) -> int:
        connection = self._connect()
        try:
            cursor = connection.execute(
                "INSERT INTO alerts (received_at, source_ip, ticker, action, price, message, raw) VALUES (?,?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), source_ip,
                 alert.ticker, alert.action, alert.price, alert.message, alert.raw),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    def set_order_outcome(self, alert_id: int, status: str, detail: str) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "UPDATE alerts SET order_status = ?, order_detail = ? WHERE id = ?", (status, detail[:500], alert_id)
            )
            connection.commit()
        finally:
            connection.close()

    def recent(self, limit: int = 50) -> list[dict]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT id, received_at, source_ip, ticker, action, price, message, order_status, order_detail "
                "FROM alerts ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        finally:
            connection.close()
        keys = ("id", "received_at", "source_ip", "ticker", "action", "price", "message", "order_status", "order_detail")
        return [dict(zip(keys, r)) for r in rows]


def auto_order_plan(alert: Alert, enabled: bool, max_order_usdt: float) -> tuple[dict | None, str]:
    """Decide si une alerte devient un ordre paper, et lequel. Pure (aucun
    appel reseau) : testable, et appelee AVANT de repondre a TradingView pour
    que la decision - et son motif - soient journalises meme si l'execution,
    faite ensuite en arriere-plan, echoue."""
    if not enabled:
        return None, "ordres automatiques desactives (TRADINGVIEW_AUTO_ORDERS)"
    if alert.action not in ("buy", "sell"):
        return None, f"action '{alert.action}' : ni buy ni sell, alerte seulement consignee"
    symbol = tradingview_ticker_to_symbol(alert.ticker)
    if symbol is None:
        return None, f"ticker '{alert.ticker}' non reconnu : aucun ordre (on ne devine pas une paire)"
    if alert.action == "buy":
        amount = alert.amount if alert.amount is not None else max_order_usdt
        if amount <= 0:
            return None, "montant d'achat invalide"
        if amount > max_order_usdt:
            return None, f"montant {amount:g} au-dessus du plafond par alerte ({max_order_usdt:g} USDT) : refuse"
        return {"symbol": symbol, "side": "buy", "amount": amount}, f"achat de {amount:g} USDT de {symbol}"
    quantity = alert.quantity if alert.quantity is not None else "all"
    return {"symbol": symbol, "side": "sell", "quantity": quantity}, f"vente de {quantity} {symbol}"
