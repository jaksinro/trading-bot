"""Panier de trading MANUEL (EF-81) - "une interface de trade manuel, bouton
achat, vente, avec un panier a part", en paper.

Ce que "a part" veut dire ici, et pourquoi :
- Le compte testnet Binance est PARTAGE par tous les bots (memes cles API).
  Un panier manuel ne peut donc pas etre "un autre compte" : c'est un
  REGISTRE LOCAL avec son propre capital, exactement comme chaque bot tient
  le sien dans le panier commun (`shared_pool.py`).
- Il ne pioche PAS dans le panier commun des bots : son capital est verse
  explicitement par l'utilisateur (`deposit`), et un ordre manuel n'ampute
  jamais le plafond d'un bot. Revers assume : rien ne reserve le solde
  testnet entre ce panier et les bots. Avant chaque achat on verifie donc
  que le solde LIBRE du testnet couvre l'ordre, et on refuse sinon - c'est
  la seule protection possible sans partager le panier.

Les ordres partent REELLEMENT sur le testnet (argent fictif, prix reels),
via `PaperExecutor` - le meme code que les bots, avec ses arrondis de
quantite et ses limites de paire. Le prix de revient et le gain latent sont
calcules sur les executions reelles, jamais sur le prix demande.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from tradingbot.types import OrderResult, Side

DEFAULT_DB_PATH = Path("data/manual_trading.db")
FEE_PCT = 0.001  # taker Binance spot, meme hypothese que les bots (EF-22)

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS ledger (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS positions (
        symbol TEXT PRIMARY KEY, quantity REAL NOT NULL, avg_price REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, symbol TEXT NOT NULL,
        side TEXT NOT NULL, quantity REAL NOT NULL, price REAL NOT NULL, fee REAL NOT NULL,
        status TEXT NOT NULL, reason TEXT
    );
"""


@dataclass
class ManualOrderReport:
    symbol: str
    side: str
    status: str
    quantity: float = 0.0
    price: float = 0.0
    fee: float = 0.0
    reason: str = ""
    cash_after: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def is_filled(self) -> bool:
        return self.status == "filled"


class ManualBook:
    """Registre du panier manuel. Chaque methode ouvre/ferme sa connexion :
    le dashboard et les tests l'appellent depuis des threads differents, et
    sqlite n'aime pas partager une connexion entre threads."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.executescript(_SCHEMA)
        return connection

    @staticmethod
    def _read(connection, key: str, default: str) -> str:
        row = connection.execute("SELECT value FROM ledger WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    @staticmethod
    def _write(connection, key: str, value) -> None:
        connection.execute(
            "INSERT INTO ledger (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    # ------------------------------------------------------------------ capital

    def deposit(self, amount: float) -> float:
        """Verse du capital fictif dans le panier. Renvoie le cash apres."""
        if amount <= 0:
            raise ValueError("Le versement doit etre strictement positif.")
        connection = self._connect()
        try:
            cash = float(self._read(connection, "cash", "0")) + amount
            deposited = float(self._read(connection, "deposited", "0")) + amount
            self._write(connection, "cash", cash)
            self._write(connection, "deposited", deposited)
            connection.commit()
            return cash
        finally:
            connection.close()

    def reset(self) -> Path | None:
        """Remet le panier a zero en SAUVEGARDANT l'historique (meme regle
        que le bot d'investissement : la seule operation destructrice doit
        rester annulable). **Ne vend rien** sur le testnet."""
        if not self.db_path.exists():
            return None
        backup = self.db_path.with_name(f"{self.db_path.name}.bak-{date.today().isoformat()}")
        n = 1
        while backup.exists():
            n += 1
            backup = self.db_path.with_name(f"{self.db_path.name}.bak-{date.today().isoformat()}-{n}")
        self.db_path.replace(backup)
        return backup

    # ------------------------------------------------------------------ lecture

    def fills(self, symbol: str, limit: int = 200) -> list[dict]:
        """Executions d'une paire, les plus anciennes d'abord (marqueurs du
        graphique de l'Espace Trading, EF-90)."""
        if not self.db_path.exists():
            return []
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT ts, side, quantity, price, reason FROM orders WHERE symbol = ? AND status = 'filled' "
                "ORDER BY id DESC LIMIT ?", (symbol, limit)
            ).fetchall()
        finally:
            connection.close()
        return [{"ts": ts, "side": s, "quantity": q, "price": p, "reason": r} for ts, s, q, p, r in reversed(rows)]

    def positions(self) -> dict[str, tuple[float, float]]:
        connection = self._connect()
        try:
            return {
                s: (q, p) for s, q, p in connection.execute(
                    "SELECT symbol, quantity, avg_price FROM positions WHERE quantity > 0"
                )
            }
        finally:
            connection.close()

    def summary(self, prices: dict[str, float]) -> dict:
        """Photo du panier valorisee aux `prices` fournis (le dashboard les
        prend en direct sur l'exchange public ; les tests les injectent)."""
        connection = self._connect()
        try:
            cash = float(self._read(connection, "cash", "0"))
            deposited = float(self._read(connection, "deposited", "0"))
            rows = connection.execute(
                "SELECT symbol, quantity, avg_price FROM positions WHERE quantity > 0 ORDER BY symbol"
            ).fetchall()
            orders = connection.execute(
                "SELECT ts, symbol, side, quantity, price, fee, status, reason FROM orders "
                "ORDER BY id DESC LIMIT 50"
            ).fetchall()
            fees = connection.execute("SELECT COALESCE(SUM(fee), 0) FROM orders").fetchone()[0]
        finally:
            connection.close()

        lines, invested = [], 0.0
        for symbol, quantity, avg_price in rows:
            price = prices.get(symbol)
            value = quantity * price if price else None
            cost = quantity * avg_price
            invested += value if value is not None else cost
            lines.append({
                "symbol": symbol, "quantity": quantity, "avg_price": avg_price, "price": price,
                "value": value, "cost": cost,
                "pnl": (value - cost) if value is not None else None,
                "pnl_pct": ((price / avg_price - 1) * 100) if price and avg_price else None,
            })
        value_total = cash + invested
        return {
            "exists": self.db_path.exists(),
            "cash": cash, "deposited": deposited, "invested": invested, "value": value_total,
            "pnl": value_total - deposited, "pnl_pct": ((value_total / deposited - 1) * 100) if deposited else None,
            "fees": fees, "positions": lines,
            "orders": [
                {"ts": ts, "symbol": s, "side": sd, "quantity": q, "price": p, "fee": f, "status": st, "reason": r}
                for ts, s, sd, q, p, f, st, r in orders
            ],
        }

    # ------------------------------------------------------------------ ordres

    def buy(self, symbol: str, quote_amount: float, price: float, executor,
            free_quote_on_exchange: float | None = None, reason: str = "manuel") -> ManualOrderReport:
        """Achete pour `quote_amount` USDT de `symbol` au marche.

        `free_quote_on_exchange` : solde libre du testnet, si connu. Le
        testnet etant partage avec les bots, un ordre que le registre local
        peut se permettre peut quand meme echouer faute de solde reel - on
        prefere le refuser AVANT, avec un message clair."""
        report = ManualOrderReport(symbol=symbol, side="buy", status="rejected", reason=reason)
        connection = self._connect()
        try:
            cash = float(self._read(connection, "cash", "0"))
            report.cash_after = cash
            if quote_amount <= 0:
                report.reason = "montant invalide"
                return report
            needed = quote_amount * (1 + FEE_PCT)
            if needed > cash + 1e-9:
                report.reason = f"cash insuffisant dans le panier : {cash:.2f} disponible, {needed:.2f} necessaire (frais compris)"
                return report
            if free_quote_on_exchange is not None and quote_amount > free_quote_on_exchange:
                report.reason = (f"solde testnet insuffisant : {free_quote_on_exchange:.2f} USDT libres sur le compte "
                                 "(partage avec les bots), impossible d'acheter pour "
                                 f"{quote_amount:.2f}")
                return report
            if price <= 0:
                report.reason = "prix indisponible"
                return report

            quantity = quote_amount / price
            result: OrderResult = executor.place_order(
                side=Side.BUY, quantity=quantity, price=price,
                timestamp=int(datetime.now(timezone.utc).timestamp() * 1000), reason="manuel",
            )
            return self._record(connection, report, result, cash)
        finally:
            connection.close()

    def sell(self, symbol: str, quantity: float | None, price: float, executor,
             reason: str = "manuel") -> ManualOrderReport:
        """Vend `quantity` (ou TOUT si None/<=0). Plafonne a la position
        detenue : une faute de frappe ne doit jamais ouvrir une vente a
        decouvert."""
        report = ManualOrderReport(symbol=symbol, side="sell", status="rejected", reason=reason)
        connection = self._connect()
        try:
            cash = float(self._read(connection, "cash", "0"))
            report.cash_after = cash
            row = connection.execute(
                "SELECT quantity FROM positions WHERE symbol = ?", (symbol,)
            ).fetchone()
            held = float(row[0]) if row else 0.0
            if held <= 0:
                report.reason = "aucune position sur ce symbole"
                return report
            to_sell = held if quantity is None or quantity <= 0 else min(quantity, held)
            if quantity is not None and quantity > held:
                report.warnings.append(f"quantite plafonnee a la position detenue ({held:g})")
            result: OrderResult = executor.place_order(
                side=Side.SELL, quantity=to_sell, price=price,
                timestamp=int(datetime.now(timezone.utc).timestamp() * 1000), reason="manuel",
            )
            return self._record(connection, report, result, cash)
        finally:
            connection.close()

    def _record(self, connection, report: ManualOrderReport, result: OrderResult, cash: float) -> ManualOrderReport:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        report.origin = report.reason or "manuel"   # motif d'ORIGINE (EF-90), avant qu'un refus ne l'ecrase
        if result.status != "filled" or result.quantity <= 0:
            report.status = result.status
            # L'executeur renvoie en `reason` le libelle qu'on lui a passe ("manuel") :
            # ce n'est pas un motif de refus. On l'ecarte au profit du statut.
            given = result.reason if result.reason and result.reason not in ("manuel", report.origin) else ""
            report.reason = given or f"ordre non execute par l'exchange ({result.status})"
            connection.execute(
                "INSERT INTO orders (ts, symbol, side, quantity, price, fee, status, reason) VALUES (?,?,?,?,?,?,?,?)",
                (ts, report.symbol, report.side, result.quantity, result.price, 0.0, result.status, report.reason),
            )
            connection.commit()
            return report

        value = result.quantity * result.price
        fee = value * FEE_PCT
        row = connection.execute(
            "SELECT quantity, avg_price FROM positions WHERE symbol = ?", (report.symbol,)
        ).fetchone()
        held, avg = (float(row[0]), float(row[1])) if row else (0.0, 0.0)
        if report.side == "buy":
            cash -= value + fee
            new_qty = held + result.quantity
            # Prix de revient FRAIS INCLUS, pondere par les quantites.
            new_avg = (held * avg + value + fee) / new_qty
        else:
            cash += value - fee
            new_qty = held - result.quantity
            new_avg = avg if new_qty > 1e-12 else 0.0
            if new_qty <= 1e-12:
                new_qty = 0.0
        connection.execute(
            "INSERT INTO positions (symbol, quantity, avg_price) VALUES (?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET quantity = excluded.quantity, avg_price = excluded.avg_price",
            (report.symbol, new_qty, new_avg),
        )
        self._write(connection, "cash", cash)
        connection.execute(
            "INSERT INTO orders (ts, symbol, side, quantity, price, fee, status, reason) VALUES (?,?,?,?,?,?,?,?)",
            (ts, report.symbol, report.side, result.quantity, result.price, fee, "filled", report.origin),
        )
        connection.commit()
        report.status, report.quantity, report.price, report.fee, report.cash_after = "filled", result.quantity, result.price, fee, cash
        return report
