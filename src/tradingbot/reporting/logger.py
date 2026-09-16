"""Persistance SQLite par instance (STC section 7, ENF-04 de la STB).

`closed_trades` (EF-25) et `equity_curve` sont relues au demarrage pour que
les statistiques (win rate, P&L, courbe de capital) survivent aux
redemarrages, au lieu de repartir a zero a chaque fois (voir STC section
3.13) - seule la memoire en cours (Portfolio.trade_history/equity_curve)
etait volatile jusqu'ici.

`open_positions` (EF-27) va plus loin : les positions ENCORE OUVERTES sont
elles aussi sauvegardees (a chaque bougie traitee), pour qu'une coupure
brutale (extinction du PC, crash) n'oblige plus a tout liquider au
redemarrage - le bot reprend exactement la ou il s'etait arrete.
"""

import sqlite3
import time
from pathlib import Path

from tradingbot.types import OrderResult, Position

DATA_DIR = Path("data")


class TradeLogger:
    def __init__(self, instance_name: str):
        DATA_DIR.mkdir(exist_ok=True)
        self.db_path = DATA_DIR / f"{instance_name}.db"
        self.conn = sqlite3.connect(self.db_path)
        self._create_tables()

    def _create_tables(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS equity_curve (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                equity REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS closed_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_timestamp INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                exit_timestamp INTEGER NOT NULL,
                exit_price REAL NOT NULL,
                quantity REAL NOT NULL,
                pnl REAL NOT NULL,
                reason TEXT NOT NULL,
                lot_id INTEGER,
                fees_paid REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS open_positions (
                lot_id INTEGER PRIMARY KEY,
                quantity REAL NOT NULL,
                avg_entry_price REAL NOT NULL,
                entry_timestamp INTEGER NOT NULL,
                entry_fee REAL NOT NULL DEFAULT 0,
                peak_price REAL NOT NULL DEFAULT 0
            );
            """
        )
        self.conn.commit()

    def log_order(self, order: OrderResult, mode: str) -> None:
        self.conn.execute(
            "INSERT INTO orders (timestamp, side, quantity, price, mode, status) VALUES (?, ?, ?, ?, ?, ?)",
            (order.timestamp, order.side.value, order.quantity, order.price, mode, order.status),
        )
        self.conn.commit()

    def log_equity(self, timestamp: int, equity: float) -> None:
        self.conn.execute(
            "INSERT INTO equity_curve (timestamp, equity) VALUES (?, ?)", (timestamp, equity)
        )
        self.conn.commit()

    def log_event(self, level: str, message: str) -> None:
        self.conn.execute(
            "INSERT INTO events (timestamp, level, message) VALUES (?, ?, ?)",
            (int(time.time() * 1000), level, message),
        )
        self.conn.commit()

    def log_closed_trade(self, trade: dict) -> None:
        self.conn.execute(
            """INSERT INTO closed_trades
               (entry_timestamp, entry_price, exit_timestamp, exit_price, quantity, pnl, reason, lot_id, fees_paid)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade["entry_timestamp"], trade["entry_price"], trade["timestamp"], trade["exit_price"],
                trade["quantity"], trade["pnl"], trade.get("reason", ""), trade.get("lot_id"),
                trade.get("fees_paid", 0.0),
            ),
        )
        self.conn.commit()

    def load_closed_trades(self) -> list[dict]:
        """Recharge l'historique des trades clotures des sessions
        precedentes, pour que le win rate/P&L affiches ne repartent pas a
        zero a chaque redemarrage du bot."""
        rows = self.conn.execute(
            """SELECT entry_timestamp, entry_price, exit_timestamp, exit_price, quantity, pnl, reason, lot_id, fees_paid
               FROM closed_trades ORDER BY id"""
        ).fetchall()
        return [
            {
                "entry_timestamp": r[0], "entry_price": r[1], "timestamp": r[2], "exit_price": r[3],
                "quantity": r[4], "pnl": r[5], "reason": r[6], "lot_id": r[7], "fees_paid": r[8],
            }
            for r in rows
        ]

    def load_equity_curve(self, limit: int = 500) -> list[tuple[int, float]]:
        """Recharge les derniers points de la courbe de capital, pour que le
        graphique du dashboard ne reparte pas d'une ligne vide a chaque
        redemarrage."""
        rows = self.conn.execute(
            "SELECT timestamp, equity FROM equity_curve ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [(r[0], r[1]) for r in reversed(rows)]

    def save_open_positions(self, positions: list[Position]) -> None:
        """Remplace l'etat des positions ouvertes par l'etat courant complet
        (pas un ajout) : appele a chaque bougie traitee, c'est toujours
        l'ensemble exact des lots encore ouverts a cet instant."""
        self.conn.execute("DELETE FROM open_positions")
        self.conn.executemany(
            """INSERT INTO open_positions
               (lot_id, quantity, avg_entry_price, entry_timestamp, entry_fee, peak_price)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (p.lot_id, p.quantity, p.avg_entry_price, p.entry_timestamp, p.entry_fee, p.peak_price)
                for p in positions
            ],
        )
        self.conn.commit()

    def load_open_positions(self) -> list[Position]:
        """Recharge les positions encore ouvertes a l'arret precedent, pour
        reprendre exactement ou le bot s'etait arrete (EF-27) plutot que de
        tout liquider au redemarrage."""
        rows = self.conn.execute(
            """SELECT lot_id, quantity, avg_entry_price, entry_timestamp, entry_fee, peak_price
               FROM open_positions ORDER BY lot_id"""
        ).fetchall()
        return [
            Position(
                quantity=r[1], avg_entry_price=r[2], entry_timestamp=r[3],
                lot_id=r[0], entry_fee=r[4], peak_price=r[5],
            )
            for r in rows
        ]

    def load_recent_buy_orders(self, limit: int = 20) -> list[dict]:
        """Derniers ordres d'achat REMPLIS de cette instance - utilise au
        demarrage pour reconcilier une reservation orpheline du panier
        commun (shared_pool.reconcile_orphaned_reservations) : si le cout
        d'un de ces ordres correspond au montant reserve, on peut regler la
        reservation plutot que la liberer a tort (l'achat a bien eu lieu
        avant un crash survenu juste apres)."""
        rows = self.conn.execute(
            "SELECT quantity, price FROM orders WHERE side = 'buy' AND status = 'filled' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{"quantity": r[0], "price": r[1]} for r in rows]

    def close(self) -> None:
        self.conn.close()
