"""Diagnostic de la connexion Interactive Brokers (EF-72).

Verifie, dans l'ordre et en s'arretant au premier blocage, tout ce qui separe
une installation d'IB Gateway d'un bot qui fonctionne. Objectif : savoir en
UNE commande si le probleme vient du port, du mode paper, d'un ticker ou des
donnees de marche - plutot que de le decouvrir via un bot qui plante au
demarrage avec un message d'erreur d'API.

Aucune de ces verifications ne passe d'ordre, ni reel ni fictif : le
diagnostic lit, il n'ecrit jamais.

Les quatre points qui font echouer un premier branchement, par ordre de
frequence :

1. **Le port.** 7497 = TWS paper, 4002 = IB Gateway paper. 7496 et 4001 sont
   les ports du compte REEL : refuses ici, comme dans les executeurs.
2. **Le mode lecture seule.** L'option "Read-Only API" est ACTIVEE PAR
   DEFAUT dans TWS/IB Gateway. Avec elle, la connexion s'etablit, les prix
   arrivent, et tous les ordres sont rejetes - la panne la plus deroutante
   qui soit, puisque tout semble marcher. Le diagnostic ne peut pas la
   detecter sans tenter un ordre : il la rappelle donc explicitement.
3. **La traduction des tickers.** Les tickers Yahoo Finance des backtests
   (`TTE.PA`) ne sont pas les symboles IBKR : il faut le symbole nu plus une
   place de cotation (`TTE` sur SBF). C'est le point que le projet n'a jamais
   pu verifier faute de connexion, et le plus susceptible de demander un
   ajustement contrat par contrat.
4. **Les donnees de marche.** Un compte paper herite des abonnements du
   compte reel ; sans abonnement, les donnees sont differees ou absentes. En
   clotures journalieres cela suffit generalement, mais il faut le constater.
"""

import argparse
import sys
from dataclasses import dataclass, field

from tradingbot.execution.ib_multi_symbol_executor import to_ib_contract_spec

LIVE_PORTS = {7496: "TWS", 4001: "IB Gateway"}
PAPER_PORTS = {7497: "TWS", 4002: "IB Gateway"}
DEFAULT_SYMBOLS = ["TTE.PA", "ORA.PA", "GLE.PA", "RNO.PA", "AF.PA", "MT.AS"]


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class Diagnosis:
    checks: list[Check] = field(default_factory=list)
    blocked: bool = False

    def add(self, name: str, ok: bool, detail: str) -> Check:
        check = Check(name, ok, detail)
        self.checks.append(check)
        return check

    def block(self, name: str, detail: str) -> None:
        self.add(name, False, detail)
        self.blocked = True


def check_port(port: int, diagnosis: Diagnosis) -> bool:
    if port in LIVE_PORTS:
        diagnosis.block(
            "Port",
            f"{port} est le port du compte REEL ({LIVE_PORTS[port]}) - argent reel. "
            f"Utilise {', '.join(f'{p} ({n} paper)' for p, n in PAPER_PORTS.items())}.",
        )
        return False
    if port in PAPER_PORTS:
        diagnosis.add("Port", True, f"{port} = {PAPER_PORTS[port]} en mode paper (argent fictif)")
    else:
        diagnosis.add(
            "Port", True,
            f"{port} n'est ni un port paper ni un port reel connu - port personnalise, "
            "verifie qu'il correspond bien a une session PAPER",
        )
    return True


def check_accounts(ib, diagnosis: Diagnosis) -> None:
    """Les comptes paper IBKR sont prefixes `DU` (le compte reel, `U`). Si un
    compte non-`DU` apparait, la session n'est pas celle qu'on croit - c'est
    la verification qui evite de trader du reel en pensant etre en fictif."""
    try:
        accounts = list(ib.managedAccounts())
    except Exception as e:
        diagnosis.add("Comptes", False, f"impossible de lister les comptes : {e}")
        return
    if not accounts:
        diagnosis.add("Comptes", False, "aucun compte retourne par la session")
        return
    paper = [a for a in accounts if str(a).upper().startswith("DU")]
    live = [a for a in accounts if not str(a).upper().startswith("DU")]
    if live:
        diagnosis.block(
            "Comptes",
            f"compte(s) NON-paper detecte(s) : {', '.join(live)}. Un compte paper commence par "
            "'DU'. Deconnecte-toi et reconnecte TWS/IB Gateway en choisissant 'Paper Trading'.",
        )
        return
    diagnosis.add("Comptes", True, f"compte(s) paper : {', '.join(paper)}")


def check_symbols(ib, symbols: list[str], diagnosis: Diagnosis) -> list[str]:
    """Qualifie chaque ticker et renvoie ceux qui ont abouti. Affiche ce
    qu'IBKR a REELLEMENT retenu (symbole, place, devise) : c'est la seule
    facon de corriger la table de traduction sur des faits."""
    from ib_async import Stock

    qualified = []
    for symbol in symbols:
        ib_symbol, exchange, currency = to_ib_contract_spec(symbol)
        contract = Stock(ib_symbol, "SMART", currency)
        if exchange:
            contract.primaryExchange = exchange
        attempted = f"{ib_symbol} / {exchange or 'SMART'} / {currency}"
        try:
            results = ib.qualifyContracts(contract)
        except Exception as e:
            diagnosis.add(f"Ticker {symbol}", False, f"{attempted} -> erreur : {e}")
            continue
        if not results or not getattr(results[0], "conId", None):
            diagnosis.add(
                f"Ticker {symbol}", False,
                f"{attempted} -> aucun contrat trouve. A corriger dans "
                "YAHOO_SUFFIX_TO_IB_EXCHANGE (ib_multi_symbol_executor.py).",
            )
            continue
        got = results[0]
        diagnosis.add(
            f"Ticker {symbol}", True,
            f"{attempted} -> conId {got.conId}"
            + (f", place {got.primaryExchange}" if getattr(got, "primaryExchange", "") else ""),
        )
        qualified.append(symbol)
    return qualified


def check_market_data(ib, symbols: list[str], diagnosis: Diagnosis) -> None:
    """Recupere une bougie JOURNALIERE par symbole - la granularite sur
    laquelle tous les bots actions de ce projet fonctionnent."""
    from ib_async import Stock

    for symbol in symbols:
        ib_symbol, exchange, currency = to_ib_contract_spec(symbol)
        contract = Stock(ib_symbol, "SMART", currency)
        if exchange:
            contract.primaryExchange = exchange
        try:
            bars = ib.reqHistoricalData(
                contract, endDateTime="", durationStr="5 D", barSizeSetting="1 day",
                whatToShow="TRADES", useRTH=True,
            )
        except Exception as e:
            diagnosis.add(f"Donnees {symbol}", False, f"erreur : {e}")
            continue
        if not bars:
            diagnosis.add(
                f"Donnees {symbol}", False,
                "aucune bougie renvoyee - abonnement de donnees de marche probablement "
                "absent pour cette place (un compte paper herite des abonnements du compte reel)",
            )
            continue
        last = bars[-1]
        diagnosis.add(
            f"Donnees {symbol}", True,
            f"{len(bars)} bougies, derniere cloture {float(last.close)} le {last.date}",
        )


def diagnose(host: str, port: int, client_id: int, symbols: list[str], ib=None) -> Diagnosis:
    diagnosis = Diagnosis()
    if not check_port(port, diagnosis):
        return diagnosis

    own_connection = ib is None
    if own_connection:
        from ib_async import IB

        ib = IB()
        try:
            ib.connect(host, port, clientId=client_id, timeout=10)
        except Exception as e:
            diagnosis.block(
                "Connexion",
                f"{host}:{port} injoignable : {e}. Verifie que TWS ou IB Gateway est LANCE, "
                "connecte en mode PAPER, et que 'Enable ActiveX and Socket Clients' est coche "
                "dans Configuration globale > API > Parametres.",
            )
            return diagnosis
    diagnosis.add("Connexion", True, f"{host}:{port} joignable")

    try:
        check_accounts(ib, diagnosis)
        if diagnosis.blocked:
            return diagnosis
        qualified = check_symbols(ib, symbols, diagnosis)
        if qualified:
            check_market_data(ib, qualified, diagnosis)
    finally:
        if own_connection and hasattr(ib, "disconnect"):
            ib.disconnect()
    return diagnosis


def format_diagnosis(diagnosis: Diagnosis) -> str:
    lines = ["=== Diagnostic Interactive Brokers ===", ""]
    for check in diagnosis.checks:
        lines.append(f"  [{'OK ' if check.ok else 'ECHEC'}] {check.name:<18} {check.detail}")

    failures = [c for c in diagnosis.checks if not c.ok]
    lines.append("")
    if diagnosis.blocked:
        lines.append("BLOQUE : corrige le point ci-dessus avant d'aller plus loin.")
    elif failures:
        lines.append(f"{len(failures)} verification(s) en echec - la connexion fonctionne, "
                     "mais certains symboles ou donnees ne sont pas exploitables.")
    else:
        lines.append("Tout est vert.")

    lines += [
        "",
        "A VERIFIER A LA MAIN, non detectable ici : l'option 'Read-Only API' de",
        "Configuration globale > API > Parametres est ACTIVEE PAR DEFAUT. Avec elle,",
        "la connexion s'etablit et les prix arrivent, mais TOUS les ordres sont",
        "rejetes - la panne la plus deroutante, puisque ce diagnostic passera au vert.",
        "Decoche-la pour que les bots puissent passer des ordres (sur le compte paper,",
        "donc en argent fictif).",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verifie la connexion IBKR avant de lancer un bot (ne passe aucun ordre)"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4002,
                        help="4002 = IB Gateway paper (defaut), 7497 = TWS paper")
    parser.add_argument("--client-id", dest="client_id", type=int, default=99,
                        help="Identifiant de connexion, distinct de celui des bots (defaut: 99)")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS),
                        help="Tickers Yahoo a tester, separes par des virgules")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    diagnosis = diagnose(args.host, args.port, args.client_id, symbols)
    print(format_diagnosis(diagnosis))
    return 1 if diagnosis.blocked else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
