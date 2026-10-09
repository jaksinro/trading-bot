"""IBPaperExecutor (EF-65) - envoie de vrais ordres, mais sur le compte
PAPER d'Interactive Brokers (argent fictif, donnees de marche reelles) :
aucun argent reel n'est engage. Meme interface que BacktestExecutor/
PaperExecutor : Strategy et RiskManager fonctionnent sans modification
(STC section 3.4).

Necessite TWS ou IB Gateway installe et connecte en mode PAPER (port 7497
pour TWS, 4002 pour IB Gateway) - voir .env.example et le manuel
utilisateur. Ports 7496/4001 sont les ports LIVE (argent reel) : ne jamais
les utiliser tant que le passage en reel n'est pas explicitement voulu.

Contrairement a PaperExecutor (Binance), qui lit le solde REEL du testnet au
demarrage (panier partage entre bots crypto, voir shared_pool.py), le
compte paper IBKR n'est pas concu pour etre partage ainsi entre plusieurs
bots - le portefeuille local demarre vide ; `run_paper.py` lui affecte
ensuite le plafond du panier commun IBKR (fichier SEPARE du panier crypto)."""

import time

from ib_async import IB, MarketOrder, Stock

from tradingbot.execution.base import ExecutionAdapter
from tradingbot.execution.ib_multi_symbol_executor import to_ib_contract_spec
from tradingbot.portfolio import Portfolio
from tradingbot.types import OrderResult, Position, Side


class IBPaperExecutor(ExecutionAdapter):
    def __init__(
        self, symbol: str, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1, ib_client=None,
        order_timeout_seconds: float = 60.0,
    ):
        """`ib_client` permet d'injecter un client factice (tests) ; sinon
        une vraie connexion `ib_async.IB()` est etablie - echoue tout de
        suite (pas d'attente silencieuse) si TWS/IB Gateway n'est pas
        joignable, meme esprit que le `ValueError` de `PaperExecutor` sur
        des cles API manquantes."""
        self.symbol = symbol
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

        # VERIFIE contre une vraie session le 2026-09-18 (EF-75), ce que le
        # commentaire precedent reclamait depuis EF-65 : le routage "SMART"
        # seul NE SUFFIT PAS. Passer le ticker Yahoo brut ("TTE.PA", devise
        # figee a EUR) ne qualifie AUCUN contrat - IBKR repond "Aucune
        # definition de titre trouvee". Il faut la meme traduction que
        # `IBMultiSymbolExecutor` utilisait deja : symbole nu, place
        # principale forcee, devise deduite du suffixe.
        ib_symbol, exchange, currency = to_ib_contract_spec(symbol)
        self.contract = Stock(ib_symbol, "SMART", currency)
        if exchange:
            self.contract.primaryExchange = exchange
        if ib_client is None:
            # L'echec de qualification etait AVALE silencieusement : le bot
            # demarrait, se "rechauffait" sur zero bougie, puis echouait plus
            # loin sur un message sans rapport avec la cause. Mieux vaut
            # echouer ici, avec le ticker fautif sous les yeux.
            qualified = self.ib.qualifyContracts(self.contract)
            if not qualified or not getattr(qualified[0], "conId", None):
                raise ValueError(
                    f"IBKR ne reconnait aucun contrat pour {symbol} (essaye : {ib_symbol} / "
                    f"{exchange or 'SMART'} / {currency}). Verifie la traduction dans "
                    "YAHOO_SUFFIX_TO_IB_EXCHANGE / YAHOO_TICKER_TO_IB_SYMBOL "
                    "(ib_multi_symbol_executor.py), ou lance "
                    "`python -m tradingbot.diagnose_ibkr --symbols " + symbol + "`."
                )

        self.portfolio = Portfolio(starting_capital=0.0)

    def place_order(
        self, side: Side, quantity: float, price: float, timestamp: int, reason: str = "", lot_id: int | None = None,
        position_side: str = "long",
    ) -> OrderResult:
        if position_side == "short":
            # EF-104 : compte au comptant (spot / actions) - pas de vente a decouvert ici.
            return OrderResult(side=side, quantity=quantity, price=price, timestamp=timestamp, status="rejected",
                               reason="vente a decouvert impossible sur ce compte (comptant)", position_side="short")
        # Actions IBKR : quantite ENTIERE obligatoire (arrondi a l'entier
        # inferieur), contrairement a la crypto qui accepte des fractions.
        rounded_quantity = int(quantity)
        if rounded_quantity <= 0:
            return OrderResult(side=side, quantity=quantity, price=price, timestamp=timestamp, status="rejected", reason=reason)

        order = MarketOrder(side.value.upper(), rounded_quantity)
        # EF-76 : sans TIF explicite, IB Gateway applique son "prereglage
        # d'ordre", constate qu'il MODIFIE l'ordre recu par l'API, et
        # l'annule par precaution avec le code 10349 ("Order TIF was set to
        # DAY based on order preset"). Verifie sur deux places et marche
        # ouvert comme ferme : AUCUN ordre ne passait. Le declarer nous-memes
        # ne laisse plus rien a modifier au prereglage.
        order.tif = "DAY"
        trade = self.ib.placeOrder(self.contract, order)

        # EF-76 : cette attente etait une boucle SANS BORNE. Un ordre au
        # marche passe hors seance reste "PreSubmitted" jusqu'a l'ouverture
        # suivante : le bot tournait donc indefiniment, en gardant son
        # verrou, sans rien journaliser. Or ce cas est la NORME et non
        # l'exception ici - le bot travaille en bougies journalieres et
        # demarre avec le PC, donc souvent marche ferme.
        deadline = time.monotonic() + self.order_timeout_seconds
        while not trade.isDone() and time.monotonic() < deadline:
            self.ib.waitOnUpdate(timeout=1)

        if not trade.isDone():
            # On ANNULE avant de rendre la main. Rendre "rejected" en
            # laissant l'ordre vivant chez IBKR serait le pire des deux
            # mondes : le portefeuille local l'ignore, le courtier l'execute
            # a l'ouverture suivante, et le bot se retrouve avec une
            # position fantome qu'il ne sait pas gerer.
            self.ib.cancelOrder(order)
            cancel_deadline = time.monotonic() + 10
            while not trade.isDone() and time.monotonic() < cancel_deadline:
                self.ib.waitOnUpdate(timeout=1)
            state = trade.orderStatus.status
            if not trade.isDone():
                # Echec d'annulation : il FAUT le dire. Un ordre vivant dont
                # le bot ignore l'existence est le scenario a ne jamais
                # laisser passer en silence.
                raise RuntimeError(
                    f"Ordre {side.value} {rounded_quantity} {self.symbol} ni execute ni annule apres "
                    f"{self.order_timeout_seconds}s (etat IBKR : {state}). Un ordre est peut-etre TOUJOURS "
                    "ACTIF chez le courtier - verifie dans TWS/IB Gateway avant de relancer le bot."
                )
            return OrderResult(
                side=side, quantity=quantity, price=price, timestamp=timestamp, status="rejected",
                reason=f"{reason} [non execute dans le delai, ordre annule - marche probablement ferme]".strip(),
            )

        # EF-76 - LE DEFAUT LE PLUS DANGEREUX DU SYSTEME, observe en reel le
        # 2026-09-18 : un ordre AAPL a ete rapporte "Cancelled, filled=0.0"
        # par l'API, et le journal du courtier montre qu'il a ETE EXECUTE
        # 0,5 s plus tard (1 action a 335,13). L'avertissement 10349 sur le
        # prereglage d'ordre avait fait passer le `Trade` local en "annule"
        # alors que l'ordre etait deja parti.
        #
        # Consequence si on croit l'API : le portefeuille local se croit plat
        # tandis que le courtier detient la position. Le stop-loss et tout le
        # risk manager ne protegeraient JAMAIS cette position, puisque le bot
        # ignore qu'elle existe. C'est pire qu'un ordre perdu.
        #
        # On ne fait donc pas confiance au statut seul : on laisse arriver les
        # derniers evenements, puis on croit les EXECUTIONS, qui sont des
        # faits, plutot que le statut, qui est une interpretation.
        if trade.orderStatus.status != "Filled":
            self.ib.waitOnUpdate(timeout=2)
        actually_filled = sum(float(f.execution.shares) for f in getattr(trade, "fills", []))

        if actually_filled > 0:
            weighted = sum(
                float(f.execution.shares) * float(f.execution.price) for f in trade.fills
            )
            filled_qty = actually_filled
            avg_price = weighted / actually_filled
            status = "filled"
            if trade.orderStatus.status != "Filled":
                reason = (f"{reason} [ATTENTION : IBKR annoncait "
                          f"'{trade.orderStatus.status}' mais {actually_filled:g} action(s) ont bien "
                          "ete executees - execution retenue]").strip()
        else:
            filled_qty = float(trade.orderStatus.filled or rounded_quantity)
            avg_price = float(trade.orderStatus.avgFillPrice or price)
            status = "filled" if trade.orderStatus.status == "Filled" else "rejected"

        if status == "rejected":
            # EF-76 : un ordre rejete rendait un `reason` INCHANGE, donc
            # aucune trace du pourquoi. Constate sur le premier ordre reel :
            # IBKR l'avait annule avec le code 10349 (ordre DAY hors seance),
            # information presente dans `trade.log` mais jetee. On la
            # remonte : un rejet sans explication est indebuggable.
            detail = trade.orderStatus.status
            messages = [entry.message for entry in getattr(trade, "log", []) if getattr(entry, "message", "")]
            if messages:
                detail += " - " + messages[-1]
            reason = f"{reason} [IBKR : {detail}]".strip()

        result = OrderResult(side=side, quantity=filled_qty, price=avg_price, timestamp=timestamp, status=status, reason=reason)
        if status == "filled":
            self.portfolio.apply_fill(result, lot_id=lot_id)
        return result

    def get_position(self) -> Position:
        return self.portfolio.position

    def get_positions(self) -> list[Position]:
        return list(self.portfolio.positions)

    def get_balance(self) -> float:
        return self.portfolio.cash
