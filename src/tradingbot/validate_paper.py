"""Mode de validation (EF-70) : confronte ce qu'un bot a REELLEMENT fait a ce
que le backtest prevoyait.

C'est ce qui manquait pour que la phase de paper trading serve a quelque
chose. Sans cet outil, "le bot tourne" ne dit rien : il peut avoir rate des
signaux (plantage, erreur reseau, fonds insuffisants), execute a des prix
sensiblement differents de ceux du backtest, ou agi avec du retard. Les trois
se voient ici, chiffres.

TROIS QUESTIONS, TROIS REPONSES :

1. **Signaux manques** - la strategie a produit un signal, aucun ordre
   correspondant n'existe. C'est le defaut le plus grave et le plus
   silencieux : le bot semble en bonne sante, mais il n'a pas agi.
2. **Ordres inattendus** - un ordre existe sans signal correspondant. Signe
   d'un decalage de configuration entre le bot et ce qu'on rejoue, ou d'une
   intervention manuelle sur le compte.
3. **Glissement de prix (slippage)** - ecart entre le prix REELLEMENT obtenu
   et la cloture de la bougie qui a declenche le signal. C'est le cout que le
   backtest ne modelise pas, et le chiffre qui dira si les +34,8 % mesures sur
   ETH survivent au monde reel.

METHODE. Le bot decide sur une bougie CLOTUREE puis passe un ordre au marche
immediatement : le prix de reference d'un signal est donc la cloture de sa
bougie. On rejoue la strategie sur les memes bougies, sur la periode couverte
par le journal du bot uniquement, et on apparie chaque ordre au signal le plus
proche dans le temps (dans une tolerance d'une bougie). Le glissement est
signe selon le sens : payer plus cher a l'achat ou recevoir moins a la vente
sont tous deux comptes NEGATIVEMENT, pour qu'un total negatif signifie
toujours "le reel a coute par rapport au backtest".
"""

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from tradingbot.data_feed import fetch_historical_candles, filter_candles
from tradingbot.run_backtest import build_strategy
from tradingbot.types import Candle, Side


@dataclass
class RealOrder:
    timestamp: int
    side: str
    quantity: float
    price: float
    status: str


@dataclass
class ExpectedSignal:
    timestamp: int
    side: str
    reference_price: float


@dataclass
class Match:
    order: RealOrder
    signal: ExpectedSignal
    lag_ms: int

    @property
    def slippage_pct(self) -> float:
        """Signe de sorte qu'un chiffre NEGATIF signifie toujours "le reel a
        coute" : payer plus cher a l'achat, ou recevoir moins a la vente."""
        drift = (self.order.price - self.signal.reference_price) / self.signal.reference_price * 100
        return -drift if self.order.side == "buy" else drift


@dataclass
class ValidationReport:
    name: str
    symbol: str
    orders: list[RealOrder] = field(default_factory=list)
    signals: list[ExpectedSignal] = field(default_factory=list)
    matches: list[Match] = field(default_factory=list)
    missed_signals: list[ExpectedSignal] = field(default_factory=list)
    unexpected_orders: list[RealOrder] = field(default_factory=list)
    period: tuple[int, int] | None = None

    @property
    def mean_slippage_pct(self) -> float | None:
        if not self.matches:
            return None
        return sum(m.slippage_pct for m in self.matches) / len(self.matches)

    @property
    def mean_lag_minutes(self) -> float | None:
        if not self.matches:
            return None
        return sum(m.lag_ms for m in self.matches) / len(self.matches) / 60_000


def read_orders(db_path: Path) -> list[RealOrder]:
    """Seuls les ordres EXECUTES comptent : un ordre rejete n'a pas modifie le
    portefeuille et ne doit pas etre compte comme une divergence."""
    if not db_path.exists():
        return []
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT timestamp, side, quantity, price, status FROM orders ORDER BY timestamp"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        connection.close()
    return [
        RealOrder(timestamp=t, side=str(s).lower(), quantity=q, price=p, status=str(st))
        for t, s, q, p, st in rows
        if str(st).lower() in ("filled", "closed", "")
    ]


def replay_signals(config: dict, candles: list[Candle]) -> list[ExpectedSignal]:
    """Rejoue la strategie et ne retient que les signaux ACTIONNABLES : un
    achat quand on est a plat, une vente quand on detient.

    Ce filtre est indispensable, et son absence rendait l'outil inutilisable.
    Les strategies de ce projet ne suivent aucun etat interne "en position"
    (anti-doublon delegue au RiskManager) : `trend_regime` reemet SELL a
    CHAQUE bougie baissiere, et le bot les ignore a juste titre quand il n'a
    rien a vendre. Sans ce filtre, on rapporterait des centaines de faux
    "signaux manques" - defaut reel trouve en ecrivant les tests.

    LIMITE ASSUMEE : l'etat rejoue suppose que le bot a bien agi. Apres un
    vrai signal manque, l'etat simule et l'etat reel divergent, et les
    comparaisons suivantes deviennent peu fiables. L'outil detecte donc
    surtout la PREMIERE divergence - ce qui suffit pour investiguer."""
    strategy = build_strategy(config)
    max_positions = int((config.get("risk") or {}).get("max_concurrent_positions", 1) or 1)
    signals = []
    open_positions = 0
    for candle in candles:
        signal = strategy.on_candle(candle)
        if signal is None:
            continue
        side = signal.side.value if isinstance(signal.side, Side) else str(signal.side)
        if side == "buy" and open_positions < max_positions:
            open_positions += 1
        elif side == "sell" and open_positions > 0:
            open_positions = 0  # le moteur solde TOUTES les positions sur un signal de vente
        else:
            continue  # signal que le RiskManager aurait refuse : le bot n'a rien manque
        signals.append(ExpectedSignal(
            timestamp=candle.timestamp, side=side, reference_price=candle.close,
        ))
    return signals


def pair_orders_with_signals(
    orders: list[RealOrder], signals: list[ExpectedSignal], tolerance_ms: int,
) -> tuple[list[Match], list[ExpectedSignal], list[RealOrder]]:
    """Apparie chaque ordre au signal de MEME SENS le plus proche dans le
    temps, dans la tolerance donnee. Un signal deja apparie ne peut pas
    resservir : la strategie peut reemettre le meme signal a chaque bougie
    (anti-doublon delegue au RiskManager), donc plusieurs signaux consecutifs
    correspondent legitimement a UN SEUL ordre - sans cette regle, on
    compterait a tort des dizaines de "signaux manques"."""
    remaining = list(signals)
    matches: list[Match] = []
    unexpected: list[RealOrder] = []

    for order in orders:
        candidates = [
            s for s in remaining
            if s.side == order.side and abs(s.timestamp - order.timestamp) <= tolerance_ms
        ]
        if not candidates:
            unexpected.append(order)
            continue
        best = min(candidates, key=lambda s: abs(s.timestamp - order.timestamp))
        remaining.remove(best)
        matches.append(Match(order=order, signal=best, lag_ms=order.timestamp - best.timestamp))

    # Un signal non apparie ne compte comme "manque" que si AUCUN ordre du
    # meme sens n'a eu lieu dans sa fenetre : sinon c'est une simple
    # repetition du signal deja honore par cet ordre.
    honoured_windows = [(m.signal.timestamp, m.order.side) for m in matches]
    missed = [
        s for s in remaining
        if not any(
            side == s.side and abs(ts - s.timestamp) <= tolerance_ms * 4
            for ts, side in honoured_windows
        )
    ]
    return matches, missed, unexpected


def _timeframe_ms(timeframe: str) -> int:
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
    unit = timeframe[-1]
    if unit not in units:
        raise ValueError(f"timeframe non reconnu : {timeframe}")
    return int(timeframe[:-1]) * units[unit]


def validate(
    config: dict, db_path: Path, candles: list[Candle] | None = None,
) -> ValidationReport:
    symbol = config["symbol"]
    report = ValidationReport(name=config.get("name", db_path.stem), symbol=symbol)
    report.orders = read_orders(db_path)

    equity_period = _read_activity_period(db_path)
    if equity_period is None:
        return report
    start, end = equity_period
    report.period = (start, end)

    if candles is None:
        candles = fetch_historical_candles(
            exchange_id=config.get("exchange", "binance"), symbol=symbol,
            timeframe=config.get("timeframe", "1h"),
            since_iso=_iso(start),
        )
    # Le rechauffement a besoin des bougies d'AVANT la periode d'activite :
    # rejouer uniquement la fenetre d'activite donnerait une strategie froide
    # et donc des signaux differents de ceux qu'a vus le bot (qui, lui, est
    # rechauffe par `warmup_candles`).
    warmup = int(config.get("warmup_candles") or 0)
    step = _timeframe_ms(config.get("timeframe", "1h"))
    replay_from = start - warmup * step
    replayed = filter_candles(candles, replay_from, end)
    all_signals = replay_signals(config, replayed)
    report.signals = [s for s in all_signals if s.timestamp >= start]

    report.matches, report.missed_signals, report.unexpected_orders = pair_orders_with_signals(
        report.orders, report.signals, tolerance_ms=step,
    )
    return report


def _read_activity_period(db_path: Path) -> tuple[int, int] | None:
    """Periode reellement couverte par le bot, lue sur sa courbe d'equite :
    plus fiable que les ordres (un bot peut tourner des semaines sans en
    passer un seul, ce qui est le comportement NORMAL de `trend_regime`)."""
    if not db_path.exists():
        return None
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute("SELECT MIN(timestamp), MAX(timestamp) FROM equity_curve").fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        connection.close()
    if not row or row[0] is None:
        return None
    return int(row[0]), int(row[1])


def _iso(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def format_report(report: ValidationReport) -> str:
    lines = [
        f"=== Validation de '{report.name}' ({report.symbol}) ===",
    ]
    if report.period is None:
        lines.append("Aucune donnee : ce bot n'a encore rien enregistre.")
        return "\n".join(lines)

    start, end = report.period
    hours = (end - start) / 3_600_000
    lines.append(f"Periode couverte : {_fmt(start)} -> {_fmt(end)} ({hours:.1f} h)")
    lines.append("")
    lines.append(f"Ordres reellement executes : {len(report.orders)}")
    lines.append(f"Signaux attendus (rejoues) : {len(report.signals)}")
    lines.append(f"Apparies                   : {len(report.matches)}")
    lines.append(f"Signaux MANQUES            : {len(report.missed_signals)}")
    lines.append(f"Ordres INATTENDUS          : {len(report.unexpected_orders)}")

    if not report.orders and not report.signals:
        lines.append("")
        lines.append("Aucun ordre et aucun signal sur la periode : c'est le comportement")
        lines.append("NORMAL de 'trend_regime' tant que le cours reste hors de sa zone")
        lines.append("d'entree - il reste en liquidites environ 60 % du temps.")
        return "\n".join(lines)

    if report.matches:
        lines += ["", "--- Glissement de prix (negatif = le reel a coute) ---"]
        lines.append(f"Moyenne : {report.mean_slippage_pct:+.4f} %")
        worst = min(report.matches, key=lambda m: m.slippage_pct)
        lines.append(f"Pire    : {worst.slippage_pct:+.4f} % ({worst.order.side} le {_fmt(worst.order.timestamp)})")
        lines.append(f"Retard moyen a l'execution : {report.mean_lag_minutes:+.1f} min")
        lines += ["", "--- Detail ---",
                  f"{'date':<17} {'sens':<5} {'prix reel':>12} {'attendu':>12} {'glissement':>11} {'retard':>8}"]
        for m in report.matches:
            lines.append(
                f"{_fmt(m.order.timestamp):<17} {m.order.side:<5} {m.order.price:>12.4f} "
                f"{m.signal.reference_price:>12.4f} {m.slippage_pct:>+10.4f}% {m.lag_ms/60000:>+7.1f}m"
            )

    if report.missed_signals:
        lines += ["", "--- Signaux MANQUES (le bot n'a pas agi) ---"]
        for s in report.missed_signals:
            lines.append(f"  {_fmt(s.timestamp)} {s.side} attendu vers {s.reference_price:.4f}")
        lines.append("  A investiguer : plantage, erreur reseau, ou fonds insuffisants.")

    if report.unexpected_orders:
        lines += ["", "--- Ordres INATTENDUS (aucun signal correspondant) ---"]
        for o in report.unexpected_orders:
            lines.append(f"  {_fmt(o.timestamp)} {o.side} {o.quantity:.6f} a {o.price:.4f}")
        lines.append("  A investiguer : config du bot differente de celle rejouee,")
        lines.append("  ou intervention manuelle sur le compte.")

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Confronte ce qu'un bot a reellement fait a ce que le backtest prevoyait"
    )
    parser.add_argument("configs", nargs="+", help="Fichiers YAML des bots a valider")
    parser.add_argument("--db-dir", default="data", help="Repertoire des bases de bots (defaut: data)")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    for config_path in args.configs:
        config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        db_path = Path(args.db_dir) / f"{config['name']}.db"
        print(format_report(validate(config, db_path)))
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
