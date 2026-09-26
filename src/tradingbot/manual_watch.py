"""Ordres conditionnels et protections du panier MANUEL, executes sans aucun
bot (EF-90).

"Je veux que la fenetre de trading soit independante du bot." L'Espace
Trading pilote donc le panier manuel (EF-81), pas un bot. Mais un ordre "vendre
si le cours monte a X" ou un stop-loss doit etre surveille par QUELQU'UN : ici,
un SURVEILLANT qui tourne dans le serveur de controle et releve les cours
publics toutes les `WATCH_INTERVAL_SECONDS`.

Chaque execution passe par `execute_manual_order` - exactement le chemin de
l'onglet Manuel : ordre reel sur le testnet via `PaperExecutor`, cash du panier
et solde testnet verifies, vente plafonnee a la position.

Limites, dites :
- le cours est releve toutes les 20 s : un mouvement plus bref peut passer
  entre deux releves, et l'ordre part AU MARCHE une fois le seuil franchi (prix
  d'execution possiblement different du seuil) ;
- le surveillant vit dans le serveur de controle : serveur arrete = ordres et
  protections NON surveilles. Ils reprennent a son redemarrage (tout est en
  base), sans rattraper ce qui s'est passe entre-temps ;
- trailing stop : le plus haut n'est suivi que sur les releves du surveillant.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from tradingbot.manual_trading import DEFAULT_DB_PATH

WATCH_INTERVAL_SECONDS = 20

PENDING = "en attente"
IN_PROGRESS = "en cours"
EXECUTED = "execute"
REJECTED = "refuse"
CANCELLED = "annule"

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS conditional_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        direction TEXT NOT NULL,
        trigger_price REAL NOT NULL,
        amount REAL,
        quantity REAL,
        status TEXT NOT NULL,
        resolved_at TEXT,
        detail TEXT
    );
    CREATE TABLE IF NOT EXISTS position_risk (
        symbol TEXT PRIMARY KEY,
        stop_loss_pct REAL,
        take_profit_pct REAL,
        trailing_stop_pct REAL,
        peak_price REAL
    );
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Store:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.executescript(_SCHEMA)
        return connection


class ConditionalOrders(_Store):
    """Ordres "si le cours atteint X, alors..." du panier manuel."""

    def add(self, symbol: str, side: str, direction: str, trigger_price, amount=None, quantity=None) -> int:
        symbol = str(symbol).upper().strip()
        if "/" not in symbol:
            raise ValueError("paire attendue sous la forme ETH/USDT")
        if side not in ("buy", "sell") or direction not in ("below", "above"):
            raise ValueError("ordre invalide : side buy/sell, direction below/above")
        if side == "buy" and direction != "below":
            raise ValueError("un achat se declenche sous un prix, pas au-dessus")
        if trigger_price is None or not float(trigger_price) > 0:
            raise ValueError("le seuil doit etre un prix strictement positif")
        if side == "buy" and (amount is None or not float(amount) > 0):
            raise ValueError("un achat conditionnel demande un montant en USDT")
        if quantity is not None and not float(quantity) > 0:
            raise ValueError("quantite invalide")
        connection = self._connect()
        try:
            cursor = connection.execute(
                "INSERT INTO conditional_orders (created_at, symbol, side, direction, trigger_price, amount, quantity, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (_now(), symbol, side, direction, float(trigger_price),
                 float(amount) if amount is not None else None,
                 float(quantity) if quantity is not None else None, PENDING),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    def recent(self, symbol: str | None = None, limit: int = 50) -> list[dict]:
        if not self.db_path.exists():
            return []
        connection = self._connect()
        try:
            sql = ("SELECT id, created_at, symbol, side, direction, trigger_price, amount, quantity, status, resolved_at, detail "
                   "FROM conditional_orders")
            args: tuple = ()
            if symbol:
                sql += " WHERE symbol = ?"
                args = (symbol,)
            rows = connection.execute(sql + " ORDER BY id DESC LIMIT ?", args + (limit,)).fetchall()
        finally:
            connection.close()
        keys = ("id", "created_at", "symbol", "side", "direction", "trigger_price", "amount", "quantity",
                "status", "resolved_at", "detail")
        return [dict(zip(keys, r)) for r in rows]

    def pending(self) -> list[dict]:
        return [o for o in self.recent(limit=500) if o["status"] == PENDING]

    @staticmethod
    def is_due(order: dict, price: float) -> bool:
        return price <= order["trigger_price"] if order["direction"] == "below" else price >= order["trigger_price"]

    def _transition(self, order_id: int, old: str, new: str, detail: str | None = None) -> bool:
        connection = self._connect()
        try:
            if detail is None:
                cursor = connection.execute(
                    "UPDATE conditional_orders SET status = ? WHERE id = ? AND status = ?", (new, order_id, old))
            else:
                cursor = connection.execute(
                    "UPDATE conditional_orders SET status = ?, resolved_at = ?, detail = ? WHERE id = ? AND status = ?",
                    (new, _now(), detail[:500], order_id, old))
            connection.commit()
            return cursor.rowcount == 1
        finally:
            connection.close()

    def claim(self, order_id: int) -> bool:
        """Reserve un ordre juste avant de l'executer ; echoue s'il a ete annule
        entre-temps - un ordre annule ne part jamais."""
        return self._transition(order_id, PENDING, IN_PROGRESS)

    def finish(self, order_id: int, status: str, detail: str) -> bool:
        return self._transition(order_id, IN_PROGRESS, status, detail)

    def cancel(self, order_id: int) -> bool:
        return self._transition(order_id, PENDING, CANCELLED, "annule par l'utilisateur")


class PositionRisk(_Store):
    """Protections de la position du panier manuel sur une paire : stop-loss,
    objectif, trailing stop (fractions ; None = desactive). Elles restent
    enregistrees quand la position est soldee et s'appliquent a la suivante."""

    FIELDS = ("stop_loss_pct", "take_profit_pct", "trailing_stop_pct")

    def get(self, symbol: str) -> dict:
        if not self.db_path.exists():
            return {f: None for f in self.FIELDS} | {"peak_price": None}
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT stop_loss_pct, take_profit_pct, trailing_stop_pct, peak_price FROM position_risk WHERE symbol = ?",
                (symbol,)).fetchone()
        finally:
            connection.close()
        keys = self.FIELDS + ("peak_price",)
        return dict(zip(keys, row)) if row else {k: None for k in keys}

    def set(self, symbol: str, settings: dict) -> dict:
        current = self.get(symbol)
        current.update({k: settings[k] for k in self.FIELDS if k in settings})
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO position_risk (symbol, stop_loss_pct, take_profit_pct, trailing_stop_pct, peak_price) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET stop_loss_pct = excluded.stop_loss_pct, "
                "take_profit_pct = excluded.take_profit_pct, trailing_stop_pct = excluded.trailing_stop_pct",
                (symbol, current["stop_loss_pct"], current["take_profit_pct"], current["trailing_stop_pct"],
                 current["peak_price"]))
            connection.commit()
        finally:
            connection.close()
        return self.get(symbol)

    def set_peak(self, symbol: str, peak: float | None) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO position_risk (symbol, peak_price) VALUES (?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET peak_price = excluded.peak_price", (symbol, peak))
            connection.commit()
        finally:
            connection.close()

    def symbols_with_protection(self) -> list[str]:
        if not self.db_path.exists():
            return []
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT symbol FROM position_risk WHERE stop_loss_pct IS NOT NULL OR take_profit_pct IS NOT NULL "
                "OR trailing_stop_pct IS NOT NULL").fetchall()
        finally:
            connection.close()
        return [r[0] for r in rows]


def protection_to_fire(avg_price: float, peak: float, price: float, settings: dict) -> tuple[str, float] | None:
    """Quelle protection se declenche a `price`, et a quel seuil. Pure.
    Ordre d'examen : stop-loss, trailing, objectif (une perte se coupe avant
    tout)."""
    sl, tp, tr = settings.get("stop_loss_pct"), settings.get("take_profit_pct"), settings.get("trailing_stop_pct")
    if sl and price <= avg_price * (1 - sl):
        return "stop-loss", avg_price * (1 - sl)
    if tr and price <= peak * (1 - tr):
        return "trailing stop", peak * (1 - tr)
    if tp and price >= avg_price * (1 + tp):
        return "objectif", avg_price * (1 + tp)
    return None


def watch_cycle(book, orders: ConditionalOrders, risk: PositionRisk, price_of, execute) -> list[str]:
    """Un passage du surveillant. `price_of(symbol)` renvoie le cours public ;
    `execute(payload)` passe l'ordre (`execute_manual_order`) et renvoie
    (code HTTP, corps). Renvoie ce qui s'est passe, pour le journal. Une paire
    sans cours est ignoree ce passage-ci, jamais une erreur pour les autres."""
    events: list[str] = []
    pending = orders.pending()
    held = book.positions()
    symbols = sorted({o["symbol"] for o in pending} | set(held) | set(risk.symbols_with_protection()))
    for symbol in symbols:
        try:
            price = float(price_of(symbol))
        except Exception as e:
            events.append(f"{symbol} : cours indisponible ({type(e).__name__}), passage ignore")
            continue

        for order in (o for o in pending if o["symbol"] == symbol):
            if not orders.is_due(order, price) or not orders.claim(order["id"]):
                continue
            verb = "achat" if order["side"] == "buy" else "vente"
            payload = {"symbol": symbol, "side": order["side"], "reason": f"conditionnel #{order['id']}"}
            if order["side"] == "buy":
                payload["amount"] = order["amount"]
            else:
                payload["quantity"] = order["quantity"] if order["quantity"] is not None else "all"
            try:
                status, body = execute(payload)
            except Exception as e:
                orders.finish(order["id"], REJECTED, f"erreur : {type(e).__name__}: {e}")
                events.append(f"ordre #{order['id']} ({verb} {symbol}) en erreur : {e}")
                continue
            ok = status == 200 and body.get("status") == "filled"
            detail = (f"cours {price} (seuil {order['trigger_price']}) : "
                      + (f"{verb} de {body['quantity']} a {body['price']}" if ok
                         else (body.get("reason") or body.get("error") or str(body))))
            orders.finish(order["id"], EXECUTED if ok else REJECTED, detail)
            events.append(f"ordre #{order['id']} : {detail}")

        position = book.positions().get(symbol)   # relu : un ordre vient peut-etre de la modifier
        settings = risk.get(symbol)
        if not position:
            if settings["peak_price"] is not None:
                risk.set_peak(symbol, None)       # position soldee : le prochain plus haut repart de zero
            continue
        quantity, avg_price = position
        peak = max(settings["peak_price"] or avg_price, avg_price, price)
        if peak != settings["peak_price"]:
            risk.set_peak(symbol, peak)
        fired = protection_to_fire(avg_price, peak, price, settings)
        if fired is None:
            continue
        label, level = fired
        status, body = execute({"symbol": symbol, "side": "sell", "quantity": "all", "reason": label})
        if status == 200 and body.get("status") == "filled":
            risk.set_peak(symbol, None)
            events.append(f"{label} {symbol} declenche a {price} (seuil {level:.6g}) : vente de {body['quantity']} a {body['price']}")
        else:
            events.append(f"{label} {symbol} declenche mais vente refusee : {body.get('reason') or body.get('error')}")
    return events
