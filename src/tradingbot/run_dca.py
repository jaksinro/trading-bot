"""Execution du bot d'investissement regulier (EF-67) - PAPER TRADING
Interactive Brokers, argent fictif uniquement.

Ce bot est pilote par un CALENDRIER, pas par un flux de prix : il n'a rien a
faire 29 jours sur 30. Il est donc concu pour etre lance UNE FOIS puis
ressortir (a planifier quotidiennement, cf. `scripts/autostart_bots.ps1`),
et non pour tourner en boucle comme `run_paper.py`. Un processus qui dort un
mois serait fragile pour aucun benefice.

Deux garde-fous structurants :

1. **Dry-run par defaut.** Aucun ordre ne part sans `--execute`. En dry-run,
   les prix viennent de Yahoo Finance et la base n'est PAS modifiee : on peut
   voir ce que le bot ferait sans meme avoir installe TWS.
2. **Idempotence garantie par la base.** Le versement mensuel est une ligne
   dont la cle primaire est le mois : relancer le bot deux fois le meme mois
   ne peut pas verser deux fois, meme en cas de plantage au milieu. C'est la
   propriete la plus importante ici - un double versement fausserait
   silencieusement tout le suivi de performance.

Les DECISIONS ne sont pas reimplementees ici : elles viennent de
`dca_allocator.plan_buy_orders`/`plan_rebalance_sells`, exactement les
fonctions mesurees en backtest sur 11 ans. Ce module ne fait que fournir
l'etat (registre local), executer, et enregistrer les fills reels.
"""

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from tradingbot.dca_allocator import (
    PlannedOrder,
    _max_drawdown_pct,
    _order_fee,
    _portfolio_value,
    annualised_money_weighted_return_pct,
    parse_weights,
    plan_buy_orders,
    plan_rebalance_sells,
)
from tradingbot.data_feed import fetch_historical_candles, filter_candles

DEFAULT_DB_DIR = Path("data")


def db_path_for(name: str) -> Path:
    return DEFAULT_DB_DIR / f"{name}_dca.db"


@dataclass
class DcaConfig:
    name: str
    weights: dict[str, float]
    monthly_contribution: float = 200.0
    rebalance_band_pct: float | None = 5.0
    min_rebalance_interval_days: int = 90
    min_order_value: float = 50.0
    fee_pct: float = 0.001
    fee_fixed: float = 3.0  # mesure chez IBKR le 2026-09-18 (EF-74), pas une estimation
    follow_drift_on_contribution: bool = False
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497
    ibkr_client_id: int = 30

    @classmethod
    def from_yaml(cls, path: Path) -> "DcaConfig":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.from_yaml_dict(raw, default_name=path.stem)

    @classmethod
    def from_yaml_dict(cls, raw: dict, default_name: str = "dca") -> "DcaConfig":
        """Valide une config deja chargee. Le formulaire du dashboard passe
        par ici, exactement comme la lecture d'un fichier : une seule
        validation, donc pas de config acceptee par l'interface mais refusee
        au lancement."""
        weights = raw.get("weights")
        if isinstance(weights, str):
            weights = parse_weights(weights)
        elif isinstance(weights, dict):
            total = sum(weights.values())
            weights = {s.upper(): w / total for s, w in weights.items()}
        else:
            raise ValueError("La config doit contenir 'weights' (chaine 'A:40,B:60' ou dictionnaire)")
        known = {f for f in cls.__dataclass_fields__ if f not in ("name", "weights")}
        return cls(
            name=raw.get("name") or default_name,
            weights=weights,
            **{k: v for k, v in raw.items() if k in known},
        )


@dataclass
class RunReport:
    day: str
    dry_run: bool
    cash_before: float
    contribution: float = 0.0
    holdings_before: dict[str, float] = field(default_factory=dict)
    prices: dict[str, float] = field(default_factory=dict)
    planned: list[PlannedOrder] = field(default_factory=list)
    executed: list = field(default_factory=list)
    cash_after: float = 0.0
    warnings: list[str] = field(default_factory=list)
    rebalanced: bool = False


def _connect(db_path: Path, in_memory: bool = False) -> sqlite3.Connection:
    """`in_memory` ouvre une base JETABLE au lieu du fichier du bot : une
    simulation ne doit laisser aucune trace sur le disque (EF-78)."""
    if in_memory:
        connection = sqlite3.connect(":memory:")
        connection.executescript(_SCHEMA)
        return connection
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.executescript(_SCHEMA)
    return connection


_SCHEMA = """
        CREATE TABLE IF NOT EXISTS ledger (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS holdings (symbol TEXT PRIMARY KEY, quantity REAL NOT NULL);
        -- cle primaire sur le mois : c'est CE qui rend le versement idempotent.
        CREATE TABLE IF NOT EXISTS contributions (
            month TEXT PRIMARY KEY, day TEXT NOT NULL, amount REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, symbol TEXT NOT NULL,
            side TEXT NOT NULL, quantity REAL NOT NULL, price REAL NOT NULL,
            fee REAL NOT NULL, status TEXT NOT NULL, reason TEXT
        );
        CREATE TABLE IF NOT EXISTS equity_curve (day TEXT PRIMARY KEY, equity REAL NOT NULL);
        -- Derniers prix connus, ecrits a chaque passage reel. Permet au
        -- dashboard d'afficher une valorisation sans refaire un appel reseau
        -- a chaque rafraichissement (ce bot ne bouge qu'une fois par mois,
        -- un prix du dernier passage suffit pour un resume).
        CREATE TABLE IF NOT EXISTS prices (
            symbol TEXT PRIMARY KEY, price REAL NOT NULL, day TEXT NOT NULL
        );
        """


def _read_ledger(connection: sqlite3.Connection, key: str, default: str) -> str:
    row = connection.execute("SELECT value FROM ledger WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def _write_ledger(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO ledger (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def _read_holdings(connection: sqlite3.Connection) -> dict[str, float]:
    return {
        symbol: quantity
        for symbol, quantity in connection.execute("SELECT symbol, quantity FROM holdings")
        if quantity
    }


DCA_CONFIG_DIR = Path("config/dca")


def list_dca_configs(config_dir: Path | None = None) -> list[DcaConfig]:
    """Les bots d'investissement regulier vivent dans leur PROPRE repertoire
    (`config/dca/`) : mele aux configs de `config/`, un tel fichier serait
    liste comme un bot classique et la Supervision proposerait de le lancer
    via `run_paper.py`, qui planterait (ni `symbol` ni `strategy`)."""
    directory = config_dir or DCA_CONFIG_DIR
    if not directory.is_dir():
        return []
    configs = []
    for path in sorted(directory.glob("*.yml")):
        try:
            configs.append(DcaConfig.from_yaml(path))
        except (ValueError, TypeError, KeyError):
            continue
    return configs


def read_state_summary(config: DcaConfig, db_path: Path) -> dict:
    """Resume de l'etat d'un bot, lu UNIQUEMENT depuis sa base - aucun appel
    reseau, pour que le dashboard puisse rafraichir sans latence. La
    valorisation utilise donc les derniers prix connus (dernier passage du
    bot), ce que l'interface doit indiquer clairement."""
    if not db_path.exists():
        # EF-78 : `lines` etait une liste VIDE ici, ce qui privait l'interface
        # de toute matiere avant le premier passage - alors que c'est
        # justement le moment ou l'on veut voir ce que contient le panier et
        # le cours de ses lignes. On renvoie donc les lignes de la config,
        # a zero titre : l'allocation cible existe des la creation du bot.
        return {
            "name": config.name, "exists": False, "total_invested": 0.0, "value": 0.0,
            "cash": 0.0, "contributions": 0, "orders": 0,
            "lines": [
                {"symbol": symbol, "quantity": 0.0, "price": None, "value": 0.0,
                 "target_pct": target * 100, "actual_pct": 0.0}
                for symbol, target in sorted(config.weights.items(), key=lambda kv: -kv[1])
            ],
            "money_weighted_return_pct": None, "max_drawdown_pct": 0.0,
            "last_run_day": None, "prices_as_of": None, "total_fees": 0.0,
        }
    connection = sqlite3.connect(db_path)
    try:
        total_invested = connection.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM contributions"
        ).fetchone()[0]
        contribution_rows = connection.execute(
            "SELECT day, amount FROM contributions ORDER BY month"
        ).fetchall()
        holdings = {s: q for s, q in connection.execute("SELECT symbol, quantity FROM holdings") if q}
        prices = {s: p for s, p, _ in connection.execute("SELECT symbol, price, day FROM prices")}
        prices_as_of = connection.execute("SELECT MAX(day) FROM prices").fetchone()[0]
        cash = float(_read_ledger(connection, "cash", "0"))
        equity_curve = connection.execute(
            "SELECT day, equity FROM equity_curve ORDER BY day"
        ).fetchall()
        order_count = connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        total_fees = connection.execute("SELECT COALESCE(SUM(fee), 0) FROM orders").fetchone()[0]
        last_rebalance = _read_ledger(connection, "last_rebalance_day", "")
    finally:
        connection.close()

    held_value = _portfolio_value(holdings, prices)
    value = held_value + cash
    total_target = held_value + cash
    lines = []
    for symbol, target in sorted(config.weights.items(), key=lambda kv: -kv[1]):
        quantity = holdings.get(symbol, 0.0)
        line_value = quantity * prices.get(symbol, 0.0)
        lines.append({
            "symbol": symbol, "quantity": quantity, "price": prices.get(symbol),
            "value": line_value, "target_pct": target * 100,
            "actual_pct": (line_value / total_target * 100) if total_target else 0.0,
        })

    money_weighted = None
    if contribution_rows and equity_curve:
        first_day = date.fromisoformat(contribution_rows[0][0])
        last_day = date.fromisoformat(equity_curve[-1][0])
        cashflows = [
            ((date.fromisoformat(day) - first_day).days, amount)
            for day, amount in contribution_rows
        ]
        money_weighted = annualised_money_weighted_return_pct(
            cashflows, value, (last_day - first_day).days,
        )

    return {
        "name": config.name, "exists": True, "total_invested": total_invested,
        "value": value, "cash": cash, "lines": lines,
        "contributions": len(contribution_rows), "orders": order_count,
        "money_weighted_return_pct": money_weighted,
        "max_drawdown_pct": _max_drawdown_pct([(d, e) for d, e in equity_curve]),
        "last_run_day": equity_curve[-1][0] if equity_curve else None,
        "prices_as_of": prices_as_of, "total_fees": total_fees,
        "last_rebalance_day": last_rebalance or None,
        "equity_curve": [{"day": d, "equity": e} for d, e in equity_curve],
    }


def latest_prices_from_yfinance(symbols: list[str]) -> dict[str, float]:
    """Prix pour le dry-run : permet de voir ce que le bot ferait sans avoir
    installe TWS. Meme source que le backtest (bougies journalieres)."""
    since_iso = (datetime.now(tz=timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT00:00:00Z")
    prices = {}
    for symbol in symbols:
        candles = fetch_historical_candles(
            exchange_id="yfinance", symbol=symbol, timeframe="1d", since_iso=since_iso,
        )
        if candles:
            prices[symbol] = candles[-1].close
    return prices


def plan_today(
    config: DcaConfig, cash: float, holdings: dict[str, float], prices: dict[str, float],
    already_funded_this_month: bool, days_since_rebalance: int | None,
) -> tuple[float, list[PlannedOrder], bool, list[str]]:
    """Decide l'action du jour. Ne touche ni la base, ni le courtier.

    Renvoie (cash apres versement, ordres planifies, un rééquilibrage
    a-t-il ete declenche, avertissements)."""
    warnings = []
    missing = [s for s in config.weights if s not in prices]
    if missing:
        warnings.append(
            f"Pas de prix du jour pour {', '.join(missing)} - ces lignes sont ignoreEs "
            "aujourd'hui (jour non ouvre sur leur place, ou donnee indisponible)."
        )

    contribution = 0.0 if already_funded_this_month else config.monthly_contribution
    cash += contribution

    rebalanced = False
    orders: list[PlannedOrder] = []
    interval_elapsed = (
        days_since_rebalance is None or days_since_rebalance >= config.min_rebalance_interval_days
    )
    if config.rebalance_band_pct is not None and interval_elapsed and holdings:
        total_value = _portfolio_value(holdings, prices) + cash
        if total_value > 0:
            worst_drift_pct = max(
                abs(holdings.get(s, 0.0) * prices.get(s, 0.0) / total_value - w) * 100
                for s, w in config.weights.items()
            )
            if worst_drift_pct > config.rebalance_band_pct:
                orders = plan_rebalance_sells(
                    cash, holdings, prices, config.weights, config.min_order_value,
                )
                rebalanced = bool(orders)

    # Les achats issus d'un rééquilibrage attendent d'avoir encaisse le
    # produit REEL des ventes : ils sont planifies au second tour
    # (`plan_reinvestment`), jamais devines a partir d'un prix theorique.
    if not rebalanced:
        orders = plan_buy_orders(
            cash, holdings, prices, config.weights, config.fee_pct, config.fee_fixed,
            config.min_order_value, config.follow_drift_on_contribution,
            "contribution" if contribution else "reliquat",
        )
    return cash, orders, rebalanced, warnings


def plan_reinvestment(
    config: DcaConfig, cash: float, holdings: dict[str, float], prices: dict[str, float],
) -> list[PlannedOrder]:
    return plan_buy_orders(
        cash, holdings, prices, config.weights, config.fee_pct, config.fee_fixed,
        config.min_order_value, follow_drift=True, reason="rebalance",
    )


def run_once(
    config: DcaConfig, db_path: Path, executor=None, dry_run: bool = True,
    price_source=None, ignore_position_mismatch: bool = False, today: str | None = None,
) -> RunReport:
    if not dry_run and executor is None:
        raise ValueError("Passer de vrais ordres exige un executor - aucun ordre ne part 'a vide'.")
    # EF-78 : une simulation sur un bot qui n'a jamais tourne CREAIT son
    # fichier de base, vide. Le bot passait alors pour "a deja tourne" dans
    # le dashboard, qui n'affichait plus son message de premier demarrage.
    # Une simulation ne doit rien laisser derriere elle, pas meme un fichier
    # vide : on travaille en memoire dans ce cas.
    connection = _connect(db_path, in_memory=dry_run and not db_path.exists())
    try:
        day = today or date.today().isoformat()
        month = day[:7]
        cash = float(_read_ledger(connection, "cash", "0"))
        holdings = _read_holdings(connection)
        already_funded = connection.execute(
            "SELECT 1 FROM contributions WHERE month = ?", (month,)
        ).fetchone() is not None

        last_rebalance = _read_ledger(connection, "last_rebalance_day", "")
        days_since_rebalance = (
            (date.fromisoformat(day) - date.fromisoformat(last_rebalance)).days
            if last_rebalance else None
        )

        report = RunReport(
            day=day, dry_run=dry_run, cash_before=cash, holdings_before=dict(holdings),
        )

        if price_source is not None:
            prices = price_source()
        elif executor is not None:
            prices = executor.latest_prices()
        else:
            prices = latest_prices_from_yfinance(list(config.weights))
        report.prices = prices
        if not prices:
            report.warnings.append("Aucun prix disponible - rien n'est fait aujourd'hui.")
            report.cash_after = cash
            return report

        if executor is not None:
            broker_holdings = executor.positions()
            mismatch = {
                s for s in set(broker_holdings) | set(holdings)
                if abs(broker_holdings.get(s, 0.0) - holdings.get(s, 0.0)) > 1e-6
            }
            if mismatch:
                detail = ", ".join(
                    f"{s} (courtier {broker_holdings.get(s, 0.0):.0f} / registre {holdings.get(s, 0.0):.0f})"
                    for s in sorted(mismatch)
                )
                message = f"Ecart entre les positions du courtier et le registre local : {detail}."
                if not ignore_position_mismatch:
                    report.warnings.append(
                        message + " AUCUN ordre passe : corrige l'ecart ou relance avec "
                        "--ignore-position-mismatch si l'ecart est attendu."
                    )
                    report.cash_after = cash
                    return report
                report.warnings.append(message + " Ignore sur demande explicite.")

        cash_after_contribution, orders, rebalanced, warnings = plan_today(
            config, cash, holdings, prices, already_funded, days_since_rebalance,
        )
        report.contribution = cash_after_contribution - cash
        report.planned = list(orders)
        report.rebalanced = rebalanced
        report.warnings.extend(warnings)
        cash = cash_after_contribution

        if dry_run:
            # Le dry-run ne doit RIEN consommer : ni le versement du mois, ni
            # l'intervalle de rééquilibrage. Aucune ecriture, aucun commit.
            # Les liquidites affichees sont donc PROJETEES (ce qu'il resterait
            # si les ordres prevus partaient), sinon le rapport semblerait
            # s'auto-contredire en annoncant des achats sans baisse du cash.
            for order in orders:
                value = order.quantity * order.reference_price
                fee = _order_fee(value, config.fee_pct, config.fee_fixed)
                cash += (value - fee) if order.side == "sell" else -(value + fee)
            report.cash_after = cash
            return report

        if report.contribution:
            connection.execute(
                "INSERT OR IGNORE INTO contributions (month, day, amount) VALUES (?, ?, ?)",
                (month, day, report.contribution),
            )

        cash = _execute_orders(connection, config, orders, cash, holdings, day, report, executor)

        if rebalanced:
            reinvestment = plan_reinvestment(config, cash, holdings, prices)
            report.planned.extend(reinvestment)
            cash = _execute_orders(
                connection, config, reinvestment, cash, holdings, day, report, executor,
            )
            _write_ledger(connection, "last_rebalance_day", day)

        _write_ledger(connection, "cash", cash)
        for symbol, quantity in holdings.items():
            connection.execute(
                "INSERT INTO holdings (symbol, quantity) VALUES (?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET quantity = excluded.quantity",
                (symbol, quantity),
            )
        equity = _portfolio_value(holdings, prices) + cash
        connection.execute(
            "INSERT INTO equity_curve (day, equity) VALUES (?, ?) "
            "ON CONFLICT(day) DO UPDATE SET equity = excluded.equity",
            (day, equity),
        )
        for symbol, price in prices.items():
            connection.execute(
                "INSERT INTO prices (symbol, price, day) VALUES (?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET price = excluded.price, day = excluded.day",
                (symbol, price, day),
            )
        connection.commit()
        report.cash_after = cash
        return report
    finally:
        connection.close()


def _execute_orders(
    connection: sqlite3.Connection, config: DcaConfig, orders: list[PlannedOrder],
    cash: float, holdings: dict[str, float], day: str, report: RunReport, executor,
) -> float:
    """Envoie les ordres et enregistre les fills REELS (prix et quantite
    effectivement executes), jamais les valeurs planifiees : un ordre au
    marche ne s'execute presque jamais exactement au dernier cours connu."""
    for order in orders:
        fill = executor.place_order(order.symbol, order.side, order.quantity, order.reason)
        report.executed.append(fill)
        if not fill.is_filled or fill.quantity <= 0:
            report.warnings.append(
                f"Ordre non execute : {order.side} {order.quantity} {order.symbol} ({fill.status})."
            )
            connection.execute(
                "INSERT INTO orders (day, symbol, side, quantity, price, fee, status, reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (day, order.symbol, order.side, order.quantity, order.reference_price, 0.0,
                 fill.status, order.reason),
            )
            continue
        value = fill.quantity * fill.price
        fee = _order_fee(value, config.fee_pct, config.fee_fixed)
        if fill.side == "buy":
            cash -= value + fee
            holdings[fill.symbol] = holdings.get(fill.symbol, 0.0) + fill.quantity
        else:
            cash += value - fee
            holdings[fill.symbol] = holdings.get(fill.symbol, 0.0) - fill.quantity
        connection.execute(
            "INSERT INTO orders (day, symbol, side, quantity, price, fee, status, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (day, fill.symbol, fill.side, fill.quantity, fill.price, fee, fill.status, order.reason),
        )
    return cash


def format_run_report(report: RunReport, config: DcaConfig) -> str:
    mode = "SIMULATION (aucun ordre envoye, base non modifiee)" if report.dry_run else "EXECUTION REELLE (compte paper IBKR)"
    lines = [
        f"=== Bot d'investissement regulier '{config.name}' - {report.day} ===",
        f"Mode : {mode}",
        f"Liquidites avant : {report.cash_before:.2f}"
        + (f" | versement du mois : +{report.contribution:.2f}" if report.contribution else " | versement du mois : deja effectue"),
    ]
    if report.holdings_before:
        held_value = _portfolio_value(report.holdings_before, report.prices)
        lines.append(f"Portefeuille avant : {held_value:.2f} sur {len(report.holdings_before)} ligne(s)")
        total = held_value + report.cash_before + report.contribution
        lines.append("Allocation actuelle vs cible :")
        for symbol, target in sorted(config.weights.items(), key=lambda kv: -kv[1]):
            value = report.holdings_before.get(symbol, 0.0) * report.prices.get(symbol, 0.0)
            actual_pct = value / total * 100 if total else 0.0
            lines.append(f"  {symbol:<9} {actual_pct:5.1f} % (cible {target * 100:4.1f} %) | valeur {value:9.2f}")
    else:
        lines.append("Portefeuille avant : vide (premiere execution)")

    if report.rebalanced:
        lines.append("\nDerive hors bande : un rééquilibrage est declenche.")

    lines.append("")
    if report.planned:
        lines.append(f"--- Ordres {'prevus' if report.dry_run else 'passes'} ({len(report.planned)}) ---")
        for order in report.planned:
            lines.append(
                f"  {order.side.upper():<4} {order.quantity:4d} {order.symbol:<9} "
                f"@ ~{order.reference_price:8.2f} = {order.quantity * order.reference_price:9.2f} ({order.reason})"
            )
    else:
        lines.append("--- Aucun ordre aujourd'hui ---")
        lines.append("  (liquidites insuffisantes pour un ordre depassant le plancher, ou allocation dans la bande)")

    if report.executed:
        lines.append("")
        lines.append("--- Executions reelles ---")
        for fill in report.executed:
            lines.append(
                f"  {fill.side.upper():<4} {fill.quantity:4d} {fill.symbol:<9} @ {fill.price:8.2f} [{fill.status}]"
            )

    lines.append("")
    label = "Liquidites restantes (projetees)" if report.dry_run else "Liquidites restantes"
    lines.append(f"{label} : {report.cash_after:.2f} - reportees sur le mois suivant")
    for warning in report.warnings:
        lines.append(f"ATTENTION : {warning}")
    if report.dry_run:
        lines.append("")
        lines.append("Rien n'a ete envoye ni enregistre. Ajoute --execute pour passer les ordres")
        lines.append("sur le compte PAPER (argent fictif) une fois TWS/IB Gateway connecte.")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute le bot d'investissement regulier (paper trading IBKR, argent fictif) - simulation par defaut"
    )
    parser.add_argument("--config", required=True, help="Fichier YAML de configuration du bot")
    parser.add_argument("--execute", action="store_true", help="Passe reellement les ordres sur le compte PAPER IBKR (sans ce drapeau : simulation seule, rien n'est envoye ni enregistre)")
    parser.add_argument("--ignore-position-mismatch", dest="ignore_position_mismatch", action="store_true", help="Passe les ordres malgre un ecart entre les positions du courtier et le registre local")
    parser.add_argument("--db", default=None, help="Chemin de la base d'etat (defaut: data/{nom}_dca.db)")
    parser.add_argument("--today", default=None, help="Force la date du jour (AAAA-MM-JJ), pour tester")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    config = DcaConfig.from_yaml(Path(args.config))
    db_path = Path(args.db) if args.db else db_path_for(config.name)

    executor = None
    if args.execute:
        from tradingbot.execution.ib_multi_symbol_executor import IBMultiSymbolExecutor

        executor = IBMultiSymbolExecutor(
            symbols=list(config.weights), host=config.ibkr_host, port=config.ibkr_port,
            client_id=config.ibkr_client_id,
        )
    try:
        report = run_once(
            config, db_path, executor=executor, dry_run=not args.execute,
            ignore_position_mismatch=args.ignore_position_mismatch, today=args.today,
        )
        print(format_run_report(report, config))
    finally:
        if executor is not None:
            executor.disconnect()


if __name__ == "__main__":
    main(sys.argv[1:])


# ---------------------------------------------------------------------------
# Actions manuelles depuis le dashboard (EF-78)
# ---------------------------------------------------------------------------
# Ce bot est concu pour n'agir qu'une fois par mois, sans stop-loss : c'est
# assume, pas un oubli. Mais l'utilisateur doit garder la main - "des boutons
# pour vendre plus tot, reset le panier, augmenter le plafond". Ces trois
# operations passent par le MEME chemin d'execution et de persistance que le
# passage mensuel (`_execute_orders`), pour qu'un ordre manuel soit
# enregistre, reconcilie et facture exactement comme un ordre automatique.


def sell_lines(
    config: DcaConfig, db_path: Path, requests: dict[str, float], executor,
    today: str | None = None, ignore_position_mismatch: bool = False,
) -> RunReport:
    """Vend tout ou partie d'une ou plusieurs lignes, hors du cycle mensuel.

    `requests` associe un symbole a une quantite ; une quantite <= 0 ou
    superieure a la position signifie "tout vendre" (plafonnee a ce qui est
    reellement detenu - on ne vend jamais a decouvert par erreur de saisie).

    Ne touche PAS a la table des versements : vendre n'annule pas le
    versement du mois, et ne doit pas rendre un versement deja consomme a
    nouveau disponible."""
    if executor is None:
        raise ValueError("Vendre exige un executor - aucun ordre ne part 'a vide'.")

    connection = _connect(db_path)
    try:
        day = today or date.today().isoformat()
        cash = float(_read_ledger(connection, "cash", "0"))
        holdings = _read_holdings(connection)
        report = RunReport(
            day=day, dry_run=False, cash_before=cash, holdings_before=dict(holdings),
        )

        prices = executor.latest_prices()
        report.prices = prices

        # Meme garde-fou que le passage mensuel, et pour la meme raison : un
        # ecart avec le courtier signifie qu'on ne sait pas ce qu'on detient,
        # et il ne faut alors rien engager. Voir STC §3.60 - cet ecart s'est
        # deja produit en production.
        broker_holdings = executor.positions()
        mismatch = {
            s for s in set(broker_holdings) | set(holdings)
            if abs(broker_holdings.get(s, 0.0) - holdings.get(s, 0.0)) > 1e-6
        }
        if mismatch and not ignore_position_mismatch:
            detail = ", ".join(
                f"{s} (courtier {broker_holdings.get(s, 0.0):.0f} / registre {holdings.get(s, 0.0):.0f})"
                for s in sorted(mismatch)
            )
            report.warnings.append(
                f"Ecart entre les positions du courtier et le registre local : {detail}. "
                "AUCUNE vente passee : corrige l'ecart d'abord."
            )
            report.cash_after = cash
            return report

        orders = []
        for symbol, requested in requests.items():
            held = holdings.get(symbol, 0.0)
            if held <= 0:
                report.warnings.append(f"{symbol} : aucune position detenue, rien a vendre.")
                continue
            quantity = int(held) if requested is None or requested <= 0 else int(min(requested, held))
            if quantity <= 0:
                report.warnings.append(f"{symbol} : quantite demandee trop faible (moins d'une action).")
                continue
            price = prices.get(symbol)
            if price is None:
                report.warnings.append(f"{symbol} : aucun cours disponible, vente non tentee.")
                continue
            orders.append(PlannedOrder(
                symbol=symbol, side="sell", quantity=quantity,
                reference_price=price, reason="vente_manuelle",
            ))

        report.planned.extend(orders)
        if orders:
            cash = _execute_orders(connection, config, orders, cash, holdings, day, report, executor)

        _write_ledger(connection, "cash", cash)
        for symbol, quantity in holdings.items():
            connection.execute(
                "INSERT INTO holdings (symbol, quantity) VALUES (?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET quantity = excluded.quantity",
                (symbol, quantity),
            )
        equity = _portfolio_value(holdings, prices) + cash
        connection.execute(
            "INSERT INTO equity_curve (day, equity) VALUES (?, ?) "
            "ON CONFLICT(day) DO UPDATE SET equity = excluded.equity",
            (day, equity),
        )
        for symbol, price in prices.items():
            connection.execute(
                "INSERT INTO prices (symbol, price, day) VALUES (?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET price = excluded.price, day = excluded.day",
                (symbol, price, day),
            )
        connection.commit()
        report.cash_after = cash
        return report
    finally:
        connection.close()


def reset_state(db_path: Path) -> Path | None:
    """Remet le bot a zero : plus aucune position, aucun versement consomme.
    **Ne vend rien** - les titres restent chez le courtier, et la
    reconciliation bloquera donc le bot jusqu'a ce qu'ils soient vendus.
    C'est voulu : effacer un registre ne doit jamais faire croire que des
    positions ont disparu.

    L'historique est SAUVEGARDE et non supprime : c'est la seule operation
    de ce module qui detruit des donnees, et l'annuler doit rester possible.
    Renvoie le chemin de la sauvegarde, ou None si le bot n'avait jamais
    tourne."""
    if not db_path.exists():
        return None
    backup = db_path.with_name(f"{db_path.name}.bak-{date.today().isoformat()}")
    suffix = 1
    while backup.exists():
        suffix += 1
        backup = db_path.with_name(f"{db_path.name}.bak-{date.today().isoformat()}-{suffix}")
    db_path.replace(backup)
    return backup


def set_monthly_contribution(config_path: Path, amount: float) -> float:
    """Change le plafond de versement mensuel, en ne touchant QUE cette
    ligne du fichier. Renvoie le montant reellement ecrit.

    Le remplacement se fait ligne a ligne et non par un aller-retour
    `safe_load`/`safe_dump` : celui-ci reecrit le fichier depuis la structure
    et **efface tous les commentaires**. Constate en testant ce bouton - la
    note expliquant pourquoi le reequilibrage est desactive avait disparu.
    Ces commentaires portent le pourquoi des reglages, ils valent autant que
    les valeurs."""
    if amount <= 0:
        raise ValueError("Le versement mensuel doit etre strictement positif.")
    value = round(float(amount), 2)

    lines = config_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.split(":", 1)[0].strip() == "monthly_contribution":
            lines[i] = f"monthly_contribution: {value}"
            break
    else:
        # Champ absent (config ecrite a la main) : on l'ajoute plutot que d'echouer.
        lines.append(f"monthly_contribution: {value}")
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return value


def read_price_history(config: DcaConfig, db_path: Path, days: int = 180) -> dict:
    """Series de cours journaliers par ligne, plus le PRIX DE REVIENT reel de
    chaque ligne - c'est la comparaison qui interesse l'utilisateur ("le
    cours des actions"), pas la courbe nue : un cours de 79 EUR ne dit rien
    sans savoir qu'on a paye 82.

    Le prix de revient vient des ordres REELLEMENT executes (moyenne ponderee
    des achats, frais inclus), et non des prix planifies - meme principe que
    partout ailleurs dans ce module.
    """
    since_date = date.today() - timedelta(days=days)
    since = since_date.isoformat()
    # `fetch_historical_candles` sert un cache disque et renvoie TOUT
    # l'historique connu, sans egard pour `since_iso` : sans ce filtrage
    # explicite on expedierait ~3000 points par ligne au navigateur au lieu
    # des 90 demandes. Meme piege deja corrige dans `run_backtest.py` et lors
    # de l'ajout du backtest DCA - il se represente a chaque nouvel appelant.
    since_ms = int(
        datetime.combine(since_date, datetime.min.time(), tzinfo=timezone.utc).timestamp() * 1000
    )
    series = {}
    for symbol in sorted(config.weights):
        try:
            candles = filter_candles(
                fetch_historical_candles(
                    exchange_id="yfinance", symbol=symbol, timeframe="1d", since_iso=since,
                ),
                since_ms, None,
            )
        except Exception as e:  # une place indisponible ne doit pas vider tout le graphique
            series[symbol] = {"error": str(e), "points": []}
            continue
        series[symbol] = {
            "points": [
                {"t": c.timestamp, "close": c.close} for c in candles
            ],
        }

    cost_basis = {}
    if db_path.exists():
        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                "SELECT symbol, side, quantity, price, fee FROM orders WHERE status = 'filled'"
            ).fetchall()
            holdings = _read_holdings(connection)
        finally:
            connection.close()
        bought = {}
        for symbol, side, quantity, price, fee in rows:
            if side != "buy":
                continue
            spent, qty = bought.get(symbol, (0.0, 0.0))
            bought[symbol] = (spent + quantity * price + (fee or 0.0), qty + quantity)
        for symbol, (spent, qty) in bought.items():
            if qty:
                cost_basis[symbol] = {"avg_price": spent / qty, "quantity": holdings.get(symbol, 0.0)}

    return {"series": series, "cost_basis": cost_basis, "days": days}
