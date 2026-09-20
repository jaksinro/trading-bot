"""Tests du panier de trading manuel (EF-81) - executor factice, aucun appel
reseau, aucune cle API."""
import pytest

from tradingbot.manual_trading import FEE_PCT, ManualBook
from tradingbot.types import OrderResult, Side


class FakeExecutor:
    """Remplit au prix demande plus un decalage optionnel (un ordre au marche
    ne s'execute jamais exactement au dernier cours), ou rejette tout."""

    def __init__(self, slippage=0.0, reject=False):
        self.slippage = slippage
        self.reject = reject
        self.orders = []

    def place_order(self, side, quantity, price, timestamp, reason="", lot_id=None):
        self.orders.append((side, quantity))
        if self.reject:
            return OrderResult(side=side, quantity=0.0, price=0.0, timestamp=timestamp, status="rejected", reason="testnet: refuse")
        return OrderResult(side=side, quantity=quantity, price=price + self.slippage, timestamp=timestamp, status="filled")


@pytest.fixture
def book(tmp_path):
    return ManualBook(tmp_path / "manual.db")


def test_a_fresh_book_has_nothing(book):
    s = book.summary({})
    assert s["cash"] == 0.0 and s["positions"] == [] and s["deposited"] == 0.0


def test_deposit_adds_cash_and_is_tracked(book):
    assert book.deposit(500) == 500.0
    assert book.deposit(250) == 750.0
    s = book.summary({})
    assert s["deposited"] == 750.0


def test_deposit_must_be_positive(book):
    with pytest.raises(ValueError):
        book.deposit(0)


def test_buy_spends_cash_including_fee_and_opens_a_position(book):
    book.deposit(1000)
    r = book.buy("ETH/USDT", 200, price=2000.0, executor=FakeExecutor())

    assert r.is_filled
    assert r.quantity == pytest.approx(0.1)
    assert r.cash_after == pytest.approx(1000 - 200 - 200 * FEE_PCT)
    pos = book.positions()["ETH/USDT"]
    assert pos[0] == pytest.approx(0.1)


def test_cost_basis_includes_fees_and_is_quantity_weighted(book):
    """Un cours de 79 ne dit rien tant qu'on ignore ce qu'on a paye : le prix
    de revient inclut les frais, et se pondere sur plusieurs achats."""
    book.deposit(10_000)
    book.buy("ETH/USDT", 1000, price=1000.0, executor=FakeExecutor())   # 1 ETH
    book.buy("ETH/USDT", 3000, price=3000.0, executor=FakeExecutor())   # 1 ETH
    qty, avg = book.positions()["ETH/USDT"]

    assert qty == pytest.approx(2.0)
    # (1000 + 1 + 3000 + 3) / 2 = 2002
    assert avg == pytest.approx(2002.0)


def test_buy_beyond_basket_cash_is_refused_before_any_order(book):
    book.deposit(100)
    ex = FakeExecutor()
    r = book.buy("ETH/USDT", 100, price=2000.0, executor=ex)   # 100 + frais > 100

    assert not r.is_filled
    assert "cash insuffisant" in r.reason
    assert ex.orders == [], "aucun ordre ne doit partir"


def test_buy_beyond_exchange_free_balance_is_refused(book):
    """Le testnet est PARTAGE avec les bots : le registre local peut se
    permettre un achat que le compte reel ne couvre pas."""
    book.deposit(1000)
    ex = FakeExecutor()
    r = book.buy("ETH/USDT", 500, price=2000.0, executor=ex, free_quote_on_exchange=120.0)

    assert not r.is_filled
    assert "solde testnet insuffisant" in r.reason
    assert ex.orders == []


def test_real_fill_price_is_recorded_not_the_requested_one(book):
    book.deposit(1000)
    r = book.buy("ETH/USDT", 200, price=2000.0, executor=FakeExecutor(slippage=5.0))

    assert r.price == 2005.0
    assert book.summary({})["orders"][0]["price"] == 2005.0


def test_rejected_order_changes_nothing_but_is_logged(book):
    book.deposit(1000)
    r = book.buy("ETH/USDT", 200, price=2000.0, executor=FakeExecutor(reject=True))

    assert not r.is_filled
    assert book.summary({})["cash"] == 1000.0
    assert book.positions() == {}
    assert book.summary({})["orders"][0]["status"] == "rejected"


def test_sell_everything_by_default(book):
    book.deposit(1000)
    book.buy("ETH/USDT", 200, price=2000.0, executor=FakeExecutor())
    r = book.sell("ETH/USDT", None, price=2200.0, executor=FakeExecutor())

    assert r.is_filled
    assert book.positions() == {}
    assert r.cash_after > 1000 - 200 - 200 * FEE_PCT  # vendu plus cher qu'achete


def test_sell_is_capped_to_the_position(book):
    """Une faute de frappe ne doit jamais ouvrir une vente a decouvert."""
    book.deposit(1000)
    book.buy("ETH/USDT", 200, price=2000.0, executor=FakeExecutor())
    ex = FakeExecutor()
    r = book.sell("ETH/USDT", 999, price=2000.0, executor=ex)

    assert ex.orders[0][1] == pytest.approx(0.1)
    assert any("plafonnee" in w for w in r.warnings)
    assert book.positions() == {}


def test_partial_sell_keeps_the_cost_basis(book):
    book.deposit(1000)
    book.buy("ETH/USDT", 200, price=2000.0, executor=FakeExecutor())
    _, avg_before = book.positions()["ETH/USDT"]
    book.sell("ETH/USDT", 0.04, price=2100.0, executor=FakeExecutor())
    qty, avg_after = book.positions()["ETH/USDT"]

    assert qty == pytest.approx(0.06)
    assert avg_after == pytest.approx(avg_before)


def test_selling_without_a_position_is_refused(book):
    ex = FakeExecutor()
    r = book.sell("ETH/USDT", None, price=2000.0, executor=ex)
    assert not r.is_filled and "aucune position" in r.reason and ex.orders == []


def test_summary_values_positions_at_live_prices(book):
    book.deposit(1000)
    book.buy("ETH/USDT", 200, price=2000.0, executor=FakeExecutor())
    s = book.summary({"ETH/USDT": 2500.0})
    line = s["positions"][0]

    assert line["value"] == pytest.approx(0.1 * 2500)
    assert line["pnl"] > 0
    assert s["value"] == pytest.approx(s["cash"] + 0.1 * 2500)
    assert s["pnl"] == pytest.approx(s["value"] - 1000)


def test_reset_backs_up_instead_of_deleting(book):
    book.deposit(100)
    backup = book.reset()
    assert backup is not None and backup.exists()
    assert not book.db_path.exists()
    assert book.summary({})["cash"] == 0.0


def test_reset_on_a_never_used_book_is_harmless(book):
    assert book.reset() is None
