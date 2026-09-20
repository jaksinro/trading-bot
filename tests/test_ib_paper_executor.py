from tradingbot.execution.ib_paper_executor import IBPaperExecutor
from tradingbot.types import Side


class FakeOrderStatus:
    def __init__(self, filled, avg_fill_price, status):
        self.filled = filled
        self.avgFillPrice = avg_fill_price
        self.status = status


class FakeTrade:
    def __init__(self, filled, avg_fill_price, status="Filled"):
        self.orderStatus = FakeOrderStatus(filled, avg_fill_price, status)

    def isDone(self):
        return True


class FakeIB:
    """Simule le sous-ensemble de l'API `ib_async.IB` utilise par
    IBPaperExecutor - `fill_price`/`fill_status` controlent la reponse
    simulee au prochain ordre, comme `FakeExchange` pour ccxt."""

    def __init__(self, fill_price: float = 100.0, fill_status: str = "Filled"):
        self.fill_price = fill_price
        self.fill_status = fill_status
        self.orders_placed: list[dict] = []

    def qualifyContracts(self, contract):
        pass

    def placeOrder(self, contract, order):
        self.orders_placed.append({"symbol": contract.symbol, "action": order.action, "quantity": order.totalQuantity})
        return FakeTrade(filled=order.totalQuantity, avg_fill_price=self.fill_price, status=self.fill_status)

    def waitOnUpdate(self, timeout=None):
        pass


def test_place_order_calls_ib_and_updates_portfolio():
    fake = FakeIB(fill_price=99.5)
    executor = IBPaperExecutor("RNO.PA", ib_client=fake)

    result = executor.place_order(Side.BUY, quantity=3.0, price=100.0, timestamp=1)

    assert len(fake.orders_placed) == 1
    assert fake.orders_placed[0]["action"] == "BUY"
    assert fake.orders_placed[0]["quantity"] == 3
    assert result.status == "filled"
    assert result.price == 99.5
    assert executor.get_position().quantity == 3.0


def test_rounds_quantity_to_whole_shares():
    """Actions IBKR : pas de fraction, contrairement a la crypto - une
    quantite calculee comme 12.7 doit s'arrondir a 12 avant l'envoi."""
    fake = FakeIB()
    executor = IBPaperExecutor("RNO.PA", ib_client=fake)

    result = executor.place_order(Side.BUY, quantity=12.7, price=50.0, timestamp=1)

    assert fake.orders_placed[0]["quantity"] == 12
    assert result.quantity == 12.0


def test_rejects_zero_quantity_without_calling_ib():
    fake = FakeIB()
    executor = IBPaperExecutor("RNO.PA", ib_client=fake)

    result = executor.place_order(Side.BUY, quantity=0.4, price=50.0, timestamp=1)  # arrondi a 0

    assert result.status == "rejected"
    assert fake.orders_placed == []


def test_rejects_negative_or_zero_quantity_directly():
    fake = FakeIB()
    executor = IBPaperExecutor("RNO.PA", ib_client=fake)

    result = executor.place_order(Side.BUY, quantity=0.0, price=50.0, timestamp=1)

    assert result.status == "rejected"
    assert fake.orders_placed == []


def test_order_not_filled_by_ib_is_rejected_and_not_applied_to_portfolio():
    fake = FakeIB(fill_status="Cancelled")
    executor = IBPaperExecutor("RNO.PA", ib_client=fake)

    result = executor.place_order(Side.BUY, quantity=5.0, price=50.0, timestamp=1)

    assert result.status == "rejected"
    assert executor.get_position().quantity == 0.0


def test_portfolio_starts_empty_not_read_from_a_shared_account():
    """Contrairement a PaperExecutor (Binance, solde reel du testnet partage
    entre bots), le compte paper IBKR n'est pas concu pour etre partage
    ainsi - le portefeuille local demarre vide, run_paper.py lui affecte
    ensuite le plafond du panier commun IBKR (separe du panier crypto)."""
    fake = FakeIB()
    executor = IBPaperExecutor("RNO.PA", ib_client=fake)

    assert executor.get_balance() == 0.0
    assert executor.get_positions() == []


def test_sell_uses_lot_id_like_other_executors():
    fake = FakeIB(fill_price=60.0)
    executor = IBPaperExecutor("RNO.PA", ib_client=fake)
    executor.place_order(Side.BUY, quantity=10.0, price=50.0, timestamp=1)
    lot_id = executor.get_position().lot_id

    result = executor.place_order(Side.SELL, quantity=10.0, price=60.0, timestamp=2, lot_id=lot_id)

    assert result.status == "filled"
    assert executor.get_position().quantity == 0.0


# --- EF-76 : defauts constates en passant de vrais ordres paper ---
#
# Noms prefixes `Cycle` : les classes `FakeTrade`/`FakeOrderStatus` du haut de
# ce fichier sont deja prises, et les redefinir les ecraserait pour TOUS les
# tests du module (erreur commise et corrigee en ecrivant ces tests).


class CycleExecution:
    def __init__(self, shares, price):
        self.shares = shares
        self.price = price


class CycleFill:
    def __init__(self, shares, price):
        self.execution = CycleExecution(shares, price)


class CycleLogEntry:
    def __init__(self, message):
        self.message = message


class CycleStatus:
    def __init__(self, status, filled=0.0, avg_fill_price=0.0):
        self.status = status
        self.filled = filled
        self.avgFillPrice = avg_fill_price


class CycleTrade:
    def __init__(self, status, fills=(), log=()):
        self.orderStatus = CycleStatus(status)
        self.fills = list(fills)
        self.log = [CycleLogEntry(m) for m in log]

    def isDone(self):
        return self.orderStatus.status in ("Filled", "Cancelled", "ApiCancelled", "Inactive")


class CycleIB:
    def __init__(self, trade):
        self.trade = trade
        self.cancelled = []
        self.placed_order = None

    def qualifyContracts(self, contract):
        pass

    def placeOrder(self, contract, order):
        self.placed_order = order
        return self.trade

    def waitOnUpdate(self, timeout=None):
        pass

    def cancelOrder(self, order):
        self.cancelled.append(order)
        self.trade.orderStatus.status = "Cancelled"


def _executor_with(trade):
    executor = IBPaperExecutor("AAPL", ib_client=CycleIB(trade))
    executor.ib = CycleIB(trade)
    return executor


def test_a_fill_reported_as_cancelled_is_still_treated_as_a_fill():
    """LE defaut a ne jamais laisser passer, OBSERVE EN REEL le 2026-09-18 :
    IBKR a annonce 'Cancelled, filled=0' pour un ordre AAPL que son propre
    journal montre execute 0,5 s plus tard. Croire le statut laisserait le
    portefeuille local se croire plat alors que le courtier detient la
    position - que le stop-loss ne protegerait donc jamais."""
    trade = CycleTrade("Cancelled", fills=[CycleFill(1.0, 335.13)],
                       log=["Error 10349: Order TIF was set to DAY based on order preset"])
    executor = _executor_with(trade)

    result = executor.place_order(Side.BUY, quantity=1, price=330.0, timestamp=1)

    assert result.status == "filled", "une execution reelle doit primer sur le statut annonce"
    assert result.quantity == 1.0
    assert result.price == 335.13
    assert "ATTENTION" in result.reason
    assert executor.get_position().quantity == 1.0


def test_the_average_price_comes_from_the_fills_when_there_are_several():
    trade = CycleTrade("Filled", fills=[CycleFill(2.0, 100.0), CycleFill(1.0, 130.0)])
    executor = _executor_with(trade)

    result = executor.place_order(Side.BUY, quantity=3, price=99.0, timestamp=1)

    assert result.quantity == 3.0
    assert result.price == 110.0  # (2*100 + 1*130) / 3


def test_a_genuinely_rejected_order_surfaces_the_ibkr_reason():
    """Un rejet sans explication est indebuggable : la raison d'IBKR etait
    presente dans le journal du trade, et jetee."""
    trade = CycleTrade("Cancelled", log=["Error 10349: Order TIF was set to DAY based on order preset"])
    executor = _executor_with(trade)

    result = executor.place_order(Side.BUY, quantity=1, price=330.0, timestamp=1)

    assert result.status == "rejected"
    assert "10349" in result.reason
    assert executor.get_position().quantity == 0.0


def test_an_order_that_never_completes_is_cancelled_instead_of_hanging():
    """L'attente etait une boucle SANS BORNE : un ordre laisse en attente
    (marche ferme) faisait tourner le bot indefiniment en gardant son
    verrou. On borne, et on ANNULE - laisser l'ordre vivant chez le courtier
    creerait exactement la position fantome que ce module cherche a eviter."""
    trade = CycleTrade("PreSubmitted")
    executor = _executor_with(trade)
    executor.order_timeout_seconds = 0.05

    result = executor.place_order(Side.BUY, quantity=1, price=330.0, timestamp=1)

    assert result.status == "rejected"
    assert executor.ib.cancelled, "l'ordre doit etre annule chez le courtier"
    assert "marche probablement ferme" in result.reason
    assert executor.get_position().quantity == 0.0


def test_an_order_neither_filled_nor_cancellable_raises_loudly():
    """Le pire cas : ni execute, ni annulable. Un ordre vivant dont le bot
    ignore l'existence ne doit JAMAIS passer en silence."""
    import pytest

    trade = CycleTrade("PreSubmitted")
    executor = _executor_with(trade)
    executor.ib.cancelOrder = lambda order: executor.ib.cancelled.append(order)  # annulation sans effet
    executor.order_timeout_seconds = 0.05

    with pytest.raises(RuntimeError, match="TOUJOURS ACTIF"):
        executor.place_order(Side.BUY, quantity=1, price=330.0, timestamp=1)


def test_the_time_in_force_is_set_explicitly():
    """Sans TIF explicite, le prereglage d'IB Gateway modifie l'ordre et
    l'annule par precaution (code 10349) : AUCUN ordre ne passait, marche
    ouvert comme ferme. Verifie en reel sur Euronext ET sur le NASDAQ."""
    trade = CycleTrade("Filled", fills=[CycleFill(1.0, 335.0)])
    executor = _executor_with(trade)

    executor.place_order(Side.BUY, quantity=1, price=335.0, timestamp=1)

    assert executor.ib.placed_order.tif == "DAY"
