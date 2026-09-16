from tradingbot.execution.paper_executor import PaperExecutor
from tradingbot.reporting.logger import TradeLogger
from tradingbot.run_paper import flatten_existing_position


class FakeExchange:
    def __init__(self, quote_free: float = 1000.0, base_free: float = 0.0):
        self._quote_free = quote_free
        self._base_free = base_free
        self.orders_created: list[dict] = []

    def load_markets(self):
        pass

    def market(self, symbol):
        return {"limits": {"amount": {"min": 0.0}, "cost": {"min": 0.0}}}

    def amount_to_precision(self, symbol, amount):
        return str(amount)

    def fetch_balance(self):
        return {"USDT": {"free": self._quote_free}, "BTC": {"free": self._base_free}}

    def fetch_ticker(self, symbol):
        return {"last": 100.0}

    def create_order(self, symbol, order_type, side, quantity):
        self.orders_created.append({"side": side, "quantity": quantity})
        return {"filled": quantity, "average": 100.0, "status": "closed"}


def test_flattens_preexisting_position(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake = FakeExchange(quote_free=10000.0, base_free=1.0)
    executor = PaperExecutor("binance", "BTC/USDT", exchange=fake)
    logger = TradeLogger("test_flatten")

    assert executor.get_position().is_open is True
    flatten_existing_position(executor, "BTC/USDT", logger)

    assert executor.get_position().is_open is False
    assert len(fake.orders_created) == 1
    assert fake.orders_created[0]["side"] == "sell"
    logger.close()


def test_flatten_never_credits_cash_or_pnl(tmp_path, monkeypatch):
    """CT-27 : bug reel constate (BTC_SWING_V2/ETH_SWING_V2) - la position
    preexistante vient du solde REEL de l'exchange, jamais achetee via notre
    capital ; la vendre ne doit donc jamais gonfler notre cash/P&L, meme si
    l'ordre reussit reellement sur l'exchange."""
    monkeypatch.chdir(tmp_path)
    fake = FakeExchange(quote_free=10000.0, base_free=1.0)  # 1 BTC @ 100 = 100 de "profit" fictif si mal compte
    executor = PaperExecutor("binance", "BTC/USDT", exchange=fake)
    executor.portfolio.cash = 1000.0  # simule le reset fait par main() avant l'appel
    executor.portfolio.starting_capital = 1000.0
    logger = TradeLogger("test_flatten_no_credit")

    flatten_existing_position(executor, "BTC/USDT", logger)

    assert executor.portfolio.cash == 1000.0  # inchange, pas credite du produit de la vente
    assert executor.portfolio.realized_pnl == 0.0
    assert executor.portfolio.trade_history == []
    assert len(fake.orders_created) == 1  # l'ordre reel est quand meme passe sur l'exchange
    logger.close()


def test_flatten_ignores_position_locally_even_if_exchange_order_fails(tmp_path, monkeypatch):
    """Si l'exchange rejette l'ordre (ex: poussiere sous le minimum), la
    position ne doit pas rester bloquee localement - elle est ignoree quand
    meme, sans jamais impacter le cash."""
    monkeypatch.chdir(tmp_path)
    fake = FakeExchange(quote_free=10000.0, base_free=0.0000001)

    def failing_create_order(*args, **kwargs):
        raise Exception("quantite sous le minimum de l'exchange")

    fake.create_order = failing_create_order
    executor = PaperExecutor("binance", "BTC/USDT", exchange=fake)
    executor.portfolio.cash = 1000.0
    logger = TradeLogger("test_flatten_exchange_fail")

    flatten_existing_position(executor, "BTC/USDT", logger)

    assert executor.get_position().is_open is False
    assert executor.portfolio.cash == 1000.0
    logger.close()


def test_does_nothing_when_already_flat(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake = FakeExchange(quote_free=10000.0, base_free=0.0)
    executor = PaperExecutor("binance", "BTC/USDT", exchange=fake)
    logger = TradeLogger("test_flatten_flat")

    flatten_existing_position(executor, "BTC/USDT", logger)

    assert len(fake.orders_created) == 0
    logger.close()
