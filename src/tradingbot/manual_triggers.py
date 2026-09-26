"""Ordres declenches poses a la main sur un bot (EF-88).

"En cliquant sur le graphique des bots, je veux pouvoir mettre un ordre
d'achat : si le cours descend sous cette valeur, alors on achete."

Conception :
- l'ordre est STOCKE par le serveur de controle (dans la base du bot) et
  EXECUTE par le bot lui-meme, qui le surveille a chaque passage de sa
  boucle (toutes les minutes). Il passe donc par exactement les memes
  garde-fous qu'un achat de la strategie : gestionnaire de risque (nombre
  de positions, perte journaliere), panier commun, journal des ordres. Le
  lot achete devient une position ordinaire du bot, geree ensuite par ses
  sorties habituelles (signal de vente, stop-loss s'il y en a un) ;
- un ordre ne se declenche qu'UNE fois, puis passe a "execute" ou "refuse"
  avec le motif. Un ordre annule avant son declenchement ne part jamais ;
- le seuil est compare au cours releve a chaque passage : un creux plus
  court qu'une minute, entre deux releves, peut ne pas etre vu ;
- l'achat part au MARCHE une fois le seuil franchi : le prix d'execution
  peut etre un peu different du seuil.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS manual_triggers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        side TEXT NOT NULL,
        trigger_price REAL NOT NULL,
        status TEXT NOT NULL,
        resolved_at TEXT,
        detail TEXT
    );
"""

PENDING = "en attente"
EXECUTED = "execute"
REJECTED = "refuse"
CANCELLED = "annule"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TriggerStore:
    """Une connexion par operation : le serveur (plusieurs threads) et le bot
    (un autre processus) accedent a la meme base."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.executescript(_SCHEMA)
        return connection

    def add_buy_below(self, trigger_price: float) -> int:
        if not trigger_price or trigger_price <= 0:
            raise ValueError("le seuil de declenchement doit etre un prix strictement positif")
        connection = self._connect()
        try:
            cursor = connection.execute(
                "INSERT INTO manual_triggers (created_at, side, trigger_price, status) VALUES (?, 'buy', ?, ?)",
                (_now(), float(trigger_price), PENDING),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    def due(self, current_price: float) -> list[dict]:
        """Ordres en attente dont le seuil est atteint : cours AU NIVEAU ou
        SOUS le seuil ("si le cours descend sous cette valeur")."""
        if current_price is None:
            return []
        return [t for t in self.pending() if current_price <= t["trigger_price"]]

    def pending(self) -> list[dict]:
        return [t for t in self.recent(200) if t["status"] == PENDING]

    def resolve(self, trigger_id: int, status: str, detail: str) -> bool:
        """Passe un ordre en attente a son etat final. Ne touche jamais un
        ordre deja resolu ou annule (renvoie False) : c'est ce qui empeche un
        ordre annule pendant le passage du bot d'etre execute quand meme."""
        connection = self._connect()
        try:
            cursor = connection.execute(
                "UPDATE manual_triggers SET status = ?, resolved_at = ?, detail = ? WHERE id = ? AND status = ?",
                (status, _now(), detail[:500], trigger_id, PENDING),
            )
            connection.commit()
            return cursor.rowcount == 1
        finally:
            connection.close()

    def claim(self, trigger_id: int) -> bool:
        """Reserve un ordre juste AVANT de l'executer (passe a 'en cours').
        Si l'utilisateur l'a annule entre-temps, la reservation echoue et
        l'ordre ne part pas."""
        connection = self._connect()
        try:
            cursor = connection.execute(
                "UPDATE manual_triggers SET status = 'en cours' WHERE id = ? AND status = ?", (trigger_id, PENDING)
            )
            connection.commit()
            return cursor.rowcount == 1
        finally:
            connection.close()

    def finish(self, trigger_id: int, status: str, detail: str) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "UPDATE manual_triggers SET status = ?, resolved_at = ?, detail = ? WHERE id = ? AND status = 'en cours'",
                (status, _now(), detail[:500], trigger_id),
            )
            connection.commit()
        finally:
            connection.close()

    def cancel(self, trigger_id: int) -> bool:
        return self.resolve(trigger_id, CANCELLED, "annule par l'utilisateur")

    def recent(self, limit: int = 20) -> list[dict]:
        if not self.db_path.exists():
            return []
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT id, created_at, side, trigger_price, status, resolved_at, detail "
                "FROM manual_triggers ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        finally:
            connection.close()
        keys = ("id", "created_at", "side", "trigger_price", "status", "resolved_at", "detail")
        return [dict(zip(keys, r)) for r in rows]
