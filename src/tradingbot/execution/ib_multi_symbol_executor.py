"""Executor IBKR MULTI-SYMBOLE (EF-67) - envoie de vrais ordres sur le
compte PAPER d'Interactive Brokers (argent fictif, donnees de marche
reelles). Aucun argent reel n'est engage.

POURQUOI UNE NOUVELLE CLASSE plutot qu'etendre `IBPaperExecutor` :
`ExecutionAdapter` (et donc `IBPaperExecutor`/`PaperExecutor`/
`BacktestExecutor`) fixe le symbole A LA CONSTRUCTION - `place_order` ne
recoit jamais de symbole. Cette interface est structurellement mono-
instrument, et `IBPaperExecutor` est utilise par les bots actions existants.
La modifier pour du multi-symbole risquerait une regression sur eux pour
aucun benefice. Cette classe n'implemente donc PAS `ExecutionAdapter` : elle
expose `place_order(symbol, ...)` et une seule connexion TWS partagee entre
tous les symboles (une connexion par symbole gaspillerait des `clientId` et
se heurterait a la limite de connexions simultanees de TWS).

Necessite TWS ou IB Gateway connecte en mode PAPER (port 7497 TWS, 4002 IB
Gateway). Les ports 7496/4001 sont les ports LIVE (argent reel) : jamais
utilises ici.
"""

import time
from dataclasses import dataclass

from ib_async import IB, MarketOrder, Stock

# Les tickers Yahoo Finance (utilises par le backtest, ex. "TTE.PA") ne sont
# PAS les tickers IBKR : IBKR attend le symbole nu plus une place de
# cotation principale. Sans cette traduction, tous les contrats echoueraient
# a la qualification. A verifier empiriquement des qu'une vraie connexion
# est disponible (comme le routage "SMART" de `IBPaperExecutor`).
YAHOO_SUFFIX_TO_IB_EXCHANGE = {
    ".PA": ("SBF", "EUR"),      # Euronext Paris
    ".AS": ("AEB", "EUR"),      # Euronext Amsterdam
    ".BR": ("ENEXT.BE", "EUR"),  # Euronext Bruxelles
    ".DE": ("IBIS", "EUR"),     # Xetra
    ".MI": ("BVME", "EUR"),     # Borsa Italiana
    ".MC": ("BM", "EUR"),       # Bolsa de Madrid
    ".L": ("LSE", "GBP"),       # London Stock Exchange
}

# Retirer le suffixe ne suffit PAS toujours : pour certaines valeurs, le
# symbole IBKR lui-meme differe de la racine Yahoo. Table etablie en
# interrogeant une vraie session paper (`reqMatchingSymbols`), jamais par
# supposition - chaque entree correspond a un echec de qualification
# constate, puis au symbole qu'IBKR a effectivement renvoye.
#
# DANGER que cette table evite, verifie empiriquement (EF-73) : le symbole
# "SAN" nu existe bien chez IBKR, mais c'est **Banco Santander** (Madrid,
# conId 30314144), pas Sanofi (Paris, `SAN1`, conId 29612249). Ici la
# qualification echoue proprement parce que la place principale `SBF` est
# toujours forcee pour un suffixe connu ; c'est precisement ce forcage qui
# transforme une confusion d'entreprise en simple erreur. Ne jamais
# "reparer" un ticker en retirant la place principale.
YAHOO_TICKER_TO_IB_SYMBOL = {
    "SAN.PA": "SAN1",   # Sanofi - "SAN" seul = Banco Santander
}


@dataclass
class Fill:
    symbol: str
    side: str
    quantity: int
    price: float
    status: str
    reason: str = ""

    @property
    def is_filled(self) -> bool:
        return self.status == "filled"


def to_ib_contract_spec(yahoo_symbol: str) -> tuple[str, str | None, str]:
    """Traduit un ticker Yahoo en (symbole IBKR, place principale, devise).
    Un ticker sans suffixe connu est laisse tel quel en USD (actions US),
    place principale non forcee.

    `YAHOO_TICKER_TO_IB_SYMBOL` est consultee EN PREMIER : pour les valeurs
    dont le symbole IBKR differe de la racine Yahoo, aucune regle de suffixe
    ne peut deviner le bon symbole."""
    upper = yahoo_symbol.upper()
    for suffix, (exchange, currency) in YAHOO_SUFFIX_TO_IB_EXCHANGE.items():
        if upper.endswith(suffix):
            ib_symbol = YAHOO_TICKER_TO_IB_SYMBOL.get(upper, yahoo_symbol[: -len(suffix)])
            return ib_symbol, exchange, currency
    return YAHOO_TICKER_TO_IB_SYMBOL.get(upper, yahoo_symbol), None, "USD"


class IBMultiSymbolExecutor:
    def __init__(
        self, symbols: list[str], host: str = "127.0.0.1", port: int = 7497,
        client_id: int = 1, ib_client=None, order_timeout_seconds: float = 60.0,
    ):
        """`ib_client` permet d'injecter un client factice (tests) ; sinon
        une vraie connexion est etablie, qui echoue tout de suite avec un
        message explicite si TWS/IB Gateway n'est pas joignable - meme
        esprit que `IBPaperExecutor`, pas d'attente silencieuse."""
        if port in (7496, 4001):
            raise ValueError(
                f"Port {port} = compte LIVE (argent reel) chez Interactive Brokers. "
                "Ce bot n'est autorise qu'en mode PAPER (7497 pour TWS, 4002 pour IB Gateway)."
            )
        self.symbols = list(symbols)
        self.order_timeout_seconds = order_timeout_seconds
        if ib_client is not None:
            self.ib = ib_client
        else:
            self.ib = IB()
            try:
                self.ib.connect(host, port, clientId=client_id, timeout=10)
            except Exception as e:
                raise ValueError(
                    f"Impossible de se connecter a TWS/IB Gateway sur {host}:{port} (client_id={client_id}) : {e} - "
                    "verifie qu'il est installe, lance, connecte en mode PAPER, et que l'API est activee "
                    "(Configuration globale > API > Parametres)."
                ) from e

        self.contracts = {}
        for symbol in self.symbols:
            ib_symbol, primary_exchange, currency = to_ib_contract_spec(symbol)
            contract = Stock(ib_symbol, "SMART", currency)
            if primary_exchange:
                contract.primaryExchange = primary_exchange
            self.contracts[symbol] = contract
        if ib_client is None:
            self.ib.qualifyContracts(*self.contracts.values())

    def latest_prices(self) -> dict[str, float]:
        """Derniere cloture JOURNALIERE de chaque symbole - la meme donnee
        que celle sur laquelle le backtest a ete mesure (bougies 1 jour),
        pour que les decisions live reposent sur la meme base."""
        prices = {}
        for symbol, contract in self.contracts.items():
            bars = self.ib.reqHistoricalData(
                contract, endDateTime="", durationStr="5 D", barSizeSetting="1 day",
                whatToShow="TRADES", useRTH=True,
            )
            if bars:
                prices[symbol] = float(bars[-1].close)
        return prices

    def positions(self) -> dict[str, float]:
        """Positions telles que le COURTIER les connait, reindexees sur les
        tickers Yahoo du bot. Sert a reconcilier avec le registre local."""
        ib_symbol_to_yahoo = {to_ib_contract_spec(s)[0]: s for s in self.symbols}
        held = {}
        for position in self.ib.positions():
            ib_symbol = getattr(position.contract, "symbol", None)
            yahoo_symbol = ib_symbol_to_yahoo.get(ib_symbol)
            if yahoo_symbol is not None and position.position:
                held[yahoo_symbol] = float(position.position)
        return held

    def place_order(self, symbol: str, side: str, quantity: int, reason: str = "") -> Fill:
        # Actions : quantite ENTIERE obligatoire (pas de fraction d'action).
        quantity = int(quantity)
        if quantity <= 0:
            return Fill(symbol, side, 0, 0.0, "rejected", reason)

        order = MarketOrder(side.upper(), quantity)
        # EF-77 : sans `tif` explicite, le prereglage d'ordre d'IB Gateway
        # modifie l'ordre venu de l'API et l'annule par precaution (code
        # 10349). Meme correctif que `IBPaperExecutor` (§3.59).
        order.tif = "DAY"
        trade = self.ib.placeOrder(self.contracts[symbol], order)

        # EF-77 : cette attente etait une boucle SANS BORNE - un ordre laisse
        # en attente (marche ferme) figeait le bot indefiniment.
        deadline = time.monotonic() + self.order_timeout_seconds
        while not trade.isDone() and time.monotonic() < deadline:
            self.ib.waitOnUpdate(timeout=1)

        if not trade.isDone():
            self.ib.cancelOrder(order)
            cancel_deadline = time.monotonic() + 10
            while not trade.isDone() and time.monotonic() < cancel_deadline:
                self.ib.waitOnUpdate(timeout=1)
            if not trade.isDone():
                raise RuntimeError(
                    f"Ordre {side} {quantity} {symbol} ni execute ni annule apres "
                    f"{self.order_timeout_seconds}s (etat IBKR : {trade.orderStatus.status}). Un ordre est "
                    "peut-etre TOUJOURS ACTIF chez le courtier - verifie dans TWS/IB Gateway."
                )

        # EF-77 - CE DEFAUT S'EST DEJA PRODUIT SUR LE VRAI BOT, le
        # 2026-09-18 : deux ordres (TTE, GLE) ont ete enregistres "rejected"
        # avec un portefeuille local reste VIDE, alors que le journal
        # d'executions du courtier montre les deux achats effectues. Le bot
        # se croyait donc avec 200 EUR de liquidites et aucune position,
        # tandis qu'il detenait 2 actions payees ~158 EUR - et comme le
        # versement du mois etait marque comme fait, il n'allait jamais le
        # remarquer. On croit les EXECUTIONS, qui sont des faits, plutot que
        # le statut, qui est une interpretation.
        executed = sum(int(f.execution.shares) for f in getattr(trade, "fills", []))
        if executed > 0:
            weighted = sum(
                float(f.execution.shares) * float(f.execution.price) for f in trade.fills
            )
            if trade.orderStatus.status != "Filled":
                reason = (f"{reason} [ATTENTION : IBKR annoncait "
                          f"'{trade.orderStatus.status}' mais {executed} action(s) ont bien ete "
                          "executees - execution retenue]").strip()
            return Fill(symbol, side, executed, weighted / executed, "filled", reason)

        detail = trade.orderStatus.status
        messages = [e.message for e in getattr(trade, "log", []) if getattr(e, "message", "")]
        if messages:
            detail += " - " + messages[-1]
        return Fill(symbol, side, 0, 0.0, "rejected", f"{reason} [IBKR : {detail}]".strip())

    def disconnect(self) -> None:
        if hasattr(self.ib, "disconnect"):
            self.ib.disconnect()
