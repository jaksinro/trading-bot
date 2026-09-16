"""Panier de capital commun a tous les bots (STC section 3.5 revisee).

Toutes les instances envoient deja leurs ordres reels sur LE MEME compte
testnet Binance (memes cles API) - seule la comptabilite virtuelle etait
isolee par bot jusqu'ici (`capital_allocated`). Ce module remplace cette
isolation par un panier commun : chaque bot reserve/regle/credite ce panier
avant/apres chaque ordre, au lieu de raisonner sur un budget qui lui serait
exclusivement reserve.

Chaque bot tourne dans son propre PROCESSUS OS (control_server.launch_process)
: la coordination doit donc etre inter-processus, pas juste inter-thread.
On utilise SQLite (deja la techno de confiance du projet, voir
reporting/logger.py) en mode WAL avec des transactions `BEGIN IMMEDIATE`,
qui serialisent les ecritures concurrentes entre bots sans jamais laisser
deux bots depenser en meme temps un argent qui n'existe qu'une fois.

Flux d'achat (deux temps, car on doit choisir une quantite AVANT de
connaitre le prix/frais exact du fill reel) :
  1. `reserve()` - bloque une estimation (avec marge) AVANT l'ordre reel.
  2. `settle()` - ajuste au centime pres APRES le fill reel.
  3. `release()` - si l'ordre est rejete par l'exchange, rend l'argent reserve.

Flux de vente (un seul temps, la quantite/le produit sont deja connus une
fois le fill obtenu) :
  - `credit()` - reverse directement le produit net de la vente au panier.

Allocation dynamique (feuille de route performance) : la part du panier
qu'un bot peut viser (`effective_cap`) n'est pas fixe. Elle part du plafond
de base (`capital_allocated` de la config) et est ajustee de +/-5% a chaque
trade cloture, des que le bot a atteint 10 trades clotures en live, selon
que son score (taux de reussite x rendement moyen par trade, sur les 20
derniers trades) s'ameliore ou se degrade par rapport a sa derniere mesure.
Bornee a [50%, 150%] du plafond de base pour qu'aucun bot ne soit ni
totalement asphyxie ni en mesure de monopoliser le panier apres une seule
serie.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path

DATA_DIR = Path("data")
DEFAULT_DB_PATH = DATA_DIR / "shared_pool.db"

MIN_TRADES_FOR_DYNAMIC_ALLOCATION = 10
ALLOCATION_SCORE_WINDOW = 20
ALLOCATION_STEP_UP = 1.05
ALLOCATION_STEP_DOWN = 0.95
ALLOCATION_MULTIPLIER_MIN = 0.5
ALLOCATION_MULTIPLIER_MAX = 1.5
RESERVATION_SLIPPAGE_BUFFER = 1.01  # marge de 1% contre le slippage du market order


class InsufficientFunds(Exception):
    """Leve par `reserve()` quand le panier commun n'a pas assez de cash
    disponible pour couvrir le montant demande. A traiter comme un rejet
    d'achat classique (signal ignore ce cycle), jamais comme une erreur
    fatale pour le bot."""


class SharedPool:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self._create_tables()

    def _create_tables(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS pool (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                total_cash REAL NOT NULL,
                reserved_cash REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS reservations (
                reservation_id TEXT PRIMARY KEY,
                instance_name TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at INTEGER NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                instance_name TEXT NOT NULL,
                op TEXT NOT NULL,
                amount REAL NOT NULL,
                pool_balance_after REAL NOT NULL,
                reservation_id TEXT,
                note TEXT
            );
            CREATE TABLE IF NOT EXISTS bot_allocation (
                instance_name TEXT PRIMARY KEY,
                base_cap REAL NOT NULL,
                multiplier REAL NOT NULL DEFAULT 1.0,
                last_score REAL,
                trade_count INTEGER NOT NULL DEFAULT 0,
                last_updated INTEGER
            );
            """
        )
        self.conn.commit()

    def seed_if_empty(self, total_cash: float) -> None:
        """Initialise la ligne unique de `pool` si elle n'existe pas encore
        (premier demarrage sur une base vide). Sans effet si le panier a
        deja ete initialise (par la migration ou un demarrage precedent)."""
        row = self.conn.execute("SELECT total_cash FROM pool WHERE id = 1").fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO pool (id, total_cash, reserved_cash) VALUES (1, ?, 0)", (total_cash,)
            )
            self.conn.commit()

    def available_cash(self) -> float:
        row = self.conn.execute("SELECT total_cash FROM pool WHERE id = 1").fetchone()
        return row[0] if row else 0.0

    def reserve(self, instance_name: str, amount: float) -> str:
        """Achat, etape 1 : reserve `amount` AVANT l'ordre reel. Leve
        `InsufficientFunds` si le panier n'a pas assez de cash disponible -
        l'appelant doit alors simplement renoncer a cet achat ce cycle."""
        reservation_id = f"{instance_name}:{uuid.uuid4().hex}"
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute("SELECT total_cash, reserved_cash FROM pool WHERE id = 1").fetchone()
            total_cash, reserved_cash = row if row else (0.0, 0.0)
            if total_cash < amount:
                self.conn.rollback()
                raise InsufficientFunds(
                    f"panier commun insuffisant : {total_cash:.2f} disponible, {amount:.2f} demande par {instance_name}"
                )
            new_total = total_cash - amount
            self.conn.execute(
                "UPDATE pool SET total_cash = ?, reserved_cash = ? WHERE id = 1",
                (new_total, reserved_cash + amount),
            )
            self.conn.execute(
                "INSERT INTO reservations (reservation_id, instance_name, amount, created_at, status) "
                "VALUES (?, ?, ?, ?, 'open')",
                (reservation_id, instance_name, amount, int(time.time() * 1000)),
            )
            self._insert_ledger(instance_name, "reserve", -amount, new_total, reservation_id)
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise
        return reservation_id

    def settle(self, reservation_id: str, actual_amount: float) -> None:
        """Achat, etape 2 : ajuste le panier du delta entre le montant
        reserve (estimation) et le cout reel du fill. Idempotent : un
        `reservation_id` deja regle (ou libere) est ignore silencieusement,
        pour qu'une reconciliation retentee apres coupure ne credite/debite
        jamais deux fois."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT instance_name, amount, status FROM reservations WHERE reservation_id = ?", (reservation_id,)
            ).fetchone()
            if row is None or row[2] != "open":
                self.conn.rollback()
                return
            instance_name, reserved_amount, _ = row
            delta = reserved_amount - actual_amount  # positif si on a reserve plus que necessaire
            pool_row = self.conn.execute("SELECT total_cash, reserved_cash FROM pool WHERE id = 1").fetchone()
            total_cash, reserved_cash = pool_row
            new_total = total_cash + delta
            new_reserved = reserved_cash - reserved_amount
            self.conn.execute(
                "UPDATE pool SET total_cash = ?, reserved_cash = ? WHERE id = 1", (new_total, new_reserved)
            )
            self.conn.execute("UPDATE reservations SET status = 'settled' WHERE reservation_id = ?", (reservation_id,))
            note = None if abs(delta) < 1e-9 else f"ecart reserve vs reel : {delta:+.4f}"
            self._insert_ledger(instance_name, "settle", delta, new_total, reservation_id, note)
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise

    def release(self, reservation_id: str) -> None:
        """Achat annule (ordre rejete par l'exchange, ou reservation orpheline
        sans fill correspondant) : rend integralement le montant reserve.
        Idempotent, comme `settle()`."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT instance_name, amount, status FROM reservations WHERE reservation_id = ?", (reservation_id,)
            ).fetchone()
            if row is None or row[2] != "open":
                self.conn.rollback()
                return
            instance_name, amount, _ = row
            pool_row = self.conn.execute("SELECT total_cash, reserved_cash FROM pool WHERE id = 1").fetchone()
            total_cash, reserved_cash = pool_row
            new_total = total_cash + amount
            new_reserved = reserved_cash - amount
            self.conn.execute(
                "UPDATE pool SET total_cash = ?, reserved_cash = ? WHERE id = 1", (new_total, new_reserved)
            )
            self.conn.execute("UPDATE reservations SET status = 'released' WHERE reservation_id = ?", (reservation_id,))
            self._insert_ledger(instance_name, "release", amount, new_total, reservation_id)
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise

    def credit(self, instance_name: str, amount: float) -> None:
        """Vente : reverse directement le produit net au panier commun,
        aucune reservation prealable necessaire (quantite/prix deja connus
        au moment de l'appel, contrairement a l'achat)."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute("SELECT total_cash FROM pool WHERE id = 1").fetchone()
            total_cash = row[0] if row else 0.0
            new_total = total_cash + amount
            self.conn.execute("UPDATE pool SET total_cash = ? WHERE id = 1", (new_total,))
            self._insert_ledger(instance_name, "credit", amount, new_total, None)
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise

    def _insert_ledger(
        self, instance_name: str, op: str, amount: float, pool_balance_after: float,
        reservation_id: str | None, note: str | None = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO ledger (timestamp, instance_name, op, amount, pool_balance_after, reservation_id, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (int(time.time() * 1000), instance_name, op, amount, pool_balance_after, reservation_id, note),
        )

    def reconcile_orphaned_reservations(
        self, instance_name: str, known_order_costs: list[float] | None = None, max_age_seconds: int = 3600,
    ) -> None:
        """A appeler une fois au demarrage de chaque bot : libere les
        reservations `'open'` de CETTE instance trop anciennes pour etre
        encore en cours (le bot a du crasher entre `reserve()` et
        `settle()`/`release()`). `known_order_costs` (couts reels des
        derniers ordres d'achat de ce bot, tires de son propre log SQLite)
        permet, si l'un d'eux correspond au montant reserve (a la marge de
        slippage pres), de regler la reservation avec ce cout reel plutot
        que de la liberer a tort - un ordre a bien pu passer avant le crash,
        auquel cas liberer integralement crediterait le panier a tort."""
        known_order_costs = known_order_costs or []
        cutoff = int(time.time() * 1000) - max_age_seconds * 1000
        rows = self.conn.execute(
            "SELECT reservation_id, amount, created_at FROM reservations "
            "WHERE instance_name = ? AND status = 'open' AND created_at < ?",
            (instance_name, cutoff),
        ).fetchall()
        for reservation_id, amount, _ in rows:
            matching_cost = next(
                (cost for cost in known_order_costs if cost <= amount and cost >= amount / RESERVATION_SLIPPAGE_BUFFER / 1.05),
                None,
            )
            if matching_cost is not None:
                self.settle(reservation_id, matching_cost)
            else:
                self.release(reservation_id)

    def effective_cap(self, instance_name: str, base_cap: float) -> float:
        """Plafond de mise effectif de ce bot pour le prochain achat :
        `base_cap` (capital_allocated de la config) module par son
        multiplicateur de performance courant (1.0 tant que le bot n'a pas
        atteint le nombre minimal de trades live)."""
        row = self.conn.execute("SELECT multiplier FROM bot_allocation WHERE instance_name = ?", (instance_name,)).fetchone()
        multiplier = row[0] if row else 1.0
        return base_cap * multiplier

    def update_allocation_after_trade(self, instance_name: str, trade_history: list[dict], base_cap: float) -> None:
        """A appeler apres chaque trade cloture (vente totale ou partielle).
        Ne fait rien tant que le bot n'a pas atteint
        `MIN_TRADES_FOR_DYNAMIC_ALLOCATION` trades clotures en live - avant
        ce seuil, le multiplicateur reste 1.0 (comportement historique)."""
        trade_count = len(trade_history)
        if trade_count < MIN_TRADES_FOR_DYNAMIC_ALLOCATION:
            return

        recent = trade_history[-ALLOCATION_SCORE_WINDOW:]
        wins = sum(1 for t in recent if t.get("pnl", 0.0) > 0)
        win_rate = wins / len(recent)
        avg_return_per_trade = sum(t.get("pnl", 0.0) for t in recent) / len(recent)
        score = win_rate * avg_return_per_trade

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT multiplier, last_score FROM bot_allocation WHERE instance_name = ?", (instance_name,)
            ).fetchone()
            multiplier, last_score = row if row else (1.0, None)

            if last_score is not None:
                if score > last_score:
                    multiplier *= ALLOCATION_STEP_UP
                elif score < last_score:
                    multiplier *= ALLOCATION_STEP_DOWN
                multiplier = min(max(multiplier, ALLOCATION_MULTIPLIER_MIN), ALLOCATION_MULTIPLIER_MAX)

            self.conn.execute(
                """INSERT INTO bot_allocation (instance_name, base_cap, multiplier, last_score, trade_count, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(instance_name) DO UPDATE SET
                       base_cap = excluded.base_cap, multiplier = excluded.multiplier,
                       last_score = excluded.last_score, trade_count = excluded.trade_count,
                       last_updated = excluded.last_updated""",
                (instance_name, base_cap, multiplier, score, trade_count, int(time.time() * 1000)),
            )
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise

    def seed_migration(self, per_bot: list[dict]) -> float:
        """Initialisation UNIQUE du panier lors de la migration depuis
        l'ancien modele isole (voir migrate_to_shared_pool.py) : `per_bot`
        est une liste de {instance_name, cash, base_cap, trade_count}, un
        par bot existant. Le panier est seede a la somme des `cash`
        individuels (pas a la somme des `capital_allocated` nominaux : ce
        qui est deja immobilise dans des positions ouvertes n'est PAS
        disponible et reintegrera le panier naturellement a la revente), et
        une ligne de ledger 'admin_adjust' par bot rend l'origine du total
        entierement tracable. Leve une erreur si le panier a deja ete seede,
        pour ne jamais ecraser un panier deja en service par erreur."""
        row = self.conn.execute("SELECT total_cash FROM pool WHERE id = 1").fetchone()
        if row is not None:
            raise RuntimeError("le panier commun est deja initialise - la migration ne peut se faire qu'une fois")

        total_cash = sum(b["cash"] for b in per_bot)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute("INSERT INTO pool (id, total_cash, reserved_cash) VALUES (1, ?, 0)", (total_cash,))
            for bot in per_bot:
                self._insert_ledger(
                    bot["instance_name"], "admin_adjust", bot["cash"], total_cash, None,
                    note=f"migration seed depuis l'ancien modele isole (base_cap={bot['base_cap']:.2f})",
                )
                self.conn.execute(
                    """INSERT INTO bot_allocation (instance_name, base_cap, multiplier, last_score, trade_count, last_updated)
                       VALUES (?, ?, 1.0, NULL, ?, ?)""",
                    (bot["instance_name"], bot["base_cap"], bot["trade_count"], int(time.time() * 1000)),
                )
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise
        return total_cash

    def close(self) -> None:
        self.conn.close()


def reserve_for_buy(pool: SharedPool, instance_name: str, quantity: float, price: float, fee_pct: float) -> str:
    """Flux d'achat, etape 1 - factorise pour etre partage entre `Engine`
    (achat directionnel) et `MarketMakingEngine` (fill du bid), qui suivent
    tous deux le meme protocole reserve/settle/release. Leve
    `InsufficientFunds` (voir `SharedPool.reserve`) si le panier n'a pas
    assez de cash - a l'appelant de traiter ca comme un achat ignore ce cycle."""
    reserve_amount = quantity * price * (1 + fee_pct) * RESERVATION_SLIPPAGE_BUFFER
    return pool.reserve(instance_name, reserve_amount)


def settle_or_release_buy(pool: SharedPool, reservation_id: str, order, fee_pct: float) -> None:
    """Flux d'achat, etape 2 - regle la reservation au cout reel du fill, ou
    la libere si l'ordre a ete rejete par l'exchange. Partage entre `Engine`
    et `MarketMakingEngine`."""
    if order.status == "rejected":
        pool.release(reservation_id)
        return
    actual_cost = order.quantity * order.price * (1 + fee_pct)
    pool.settle(reservation_id, actual_cost)


def credit_for_sell(
    pool: SharedPool, instance_name: str, order, fee_pct: float, trade_history: list[dict], base_cap: float
) -> None:
    """Flux de vente - reverse le produit net au panier et met a jour
    l'allocation dynamique du bot. Partage entre `Engine` et
    `MarketMakingEngine`. Sans effet si l'ordre n'est pas rempli."""
    if order.status != "filled":
        return
    gross = order.quantity * order.price
    fee = gross * fee_pct
    pool.credit(instance_name, gross - fee)
    pool.update_allocation_after_trade(instance_name, trade_history, base_cap)
