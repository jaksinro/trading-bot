from tradingbot.execution.paper_executor import PaperExecutor
from tradingbot.types import Side


class FakeExchange:
    """Simule le sous-ensemble de l'API ccxt utilise par PaperExecutor.

    `amount_step` simule les marches qui n'acceptent que des quantites
    entieres (ex: DOGE sur Binance), `min_amount`/`min_cost` simulent les
    minimums d'ordre (ex: BTC/ETH/DOGE ont tous un montant minimum)."""

    def __init__(
        self,
        quote_free: float = 1000.0,
        base_free: float = 0.0,
        min_amount: float = 0.0,
        min_cost: float = 0.0,
        amount_step: float | None = None,
    ):
        self._quote_free = quote_free
        self._base_free = base_free
        self.min_amount = min_amount
        self.min_cost = min_cost
        self.amount_step = amount_step
        self.orders_created: list[dict] = []

    def load_markets(self):
        pass

    def market(self, symbol):
        return {"limits": {"amount": {"min": self.min_amount}, "cost": {"min": self.min_cost}}}

    def amount_to_precision(self, symbol, amount):
        if self.amount_step:
            return str((amount // self.amount_step) * self.amount_step)
        return str(amount)

    def fetch_balance(self):
        return {
            "USDT": {"free": self._quote_free},
            "BTC": {"free": self._base_free},
        }

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def create_order(self, symbol, order_type, side, quantity):
        self.orders_created.append({"symbol": symbol, "type": order_type, "side": side, "quantity": quantity})
        return {"filled": quantity, "average": 100.0, "status": "closed"}


def test_loads_portfolio_from_exchange_balance():
    fake = FakeExchange(quote_free=500.0, base_free=0.0)
    executor = PaperExecutor("binance", "BTC/USDT", exchange=fake)
    assert executor.get_balance() == 500.0
    assert executor.get_position().quantity == 0.0


def test_place_order_calls_exchange_and_updates_portfolio():
    fake = FakeExchange(quote_free=1000.0)
    executor = PaperExecutor("binance", "BTC/USDT", exchange=fake)

    result = executor.place_order(Side.BUY, quantity=1.0, price=99.0, timestamp=1)

    assert len(fake.orders_created) == 1
    assert fake.orders_created[0]["side"] == "buy"
    assert result.price == 100.0  # prix moyen renvoye par l'exchange, pas le prix demande
    assert executor.get_position().quantity == 1.0


def test_rejects_zero_quantity_without_calling_exchange():
    fake = FakeExchange()
    executor = PaperExecutor("binance", "BTC/USDT", exchange=fake)

    result = executor.place_order(Side.BUY, quantity=0.0, price=100.0, timestamp=1)

    assert result.status == "rejected"
    assert len(fake.orders_created) == 0


def test_missing_api_keys_without_injected_exchange_raises():
    try:
        PaperExecutor("binance", "BTC/USDT", api_key="", api_secret="")
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


def test_rejects_order_below_minimum_notional():
    fake = FakeExchange(quote_free=1000.0, min_cost=5.0)
    executor = PaperExecutor("binance", "BTC/USDT", exchange=fake)

    result = executor.place_order(Side.BUY, quantity=0.01, price=100.0, timestamp=1)  # cout = 1.0 < min 5.0

    assert result.status == "rejected"
    assert len(fake.orders_created) == 0


def test_rounds_quantity_to_whole_units_for_integer_only_markets():
    """Simule DOGE sur Binance : pas de fraction autorisee, l'ordre doit
    etre arrondi a l'unite entiere inferieure avant d'etre envoye."""
    fake = FakeExchange(quote_free=1000.0, amount_step=1.0, min_cost=1.0)
    executor = PaperExecutor("binance", "DOGE/USDT", exchange=fake)

    result = executor.place_order(Side.BUY, quantity=235.294117, price=0.08, timestamp=1)

    assert result.status == "filled"
    assert fake.orders_created[0]["quantity"] == 235.0


def test_rejects_when_rounding_makes_quantity_zero():
    fake = FakeExchange(quote_free=1000.0, amount_step=1.0)
    executor = PaperExecutor("binance", "DOGE/USDT", exchange=fake)

    result = executor.place_order(Side.BUY, quantity=0.4, price=0.08, timestamp=1)  # arrondi a 0

    assert result.status == "rejected"
    assert len(fake.orders_created) == 0
