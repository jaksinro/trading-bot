"""Tests des garde-fous du mode ARGENT REEL (EF-69).

Aucun test ne touche le vrai marche : l'exchange est toujours factice. Chaque
garde-fou est teste SEUL, pour verifier qu'il refuse par lui-meme et ne
depend pas d'un autre.
"""
import pytest

from tradingbot.execution.live_executor import (
    LIVE_FLAG_ENV,
    LIVE_FLAG_EXPECTED,
    LiveExecutor,
    LiveTradingRefused,
)
from tradingbot.types import Side

GOOD_ENV = {LIVE_FLAG_ENV: LIVE_FLAG_EXPECTED}


class FakeExchange:
    """Exchange factice. Par defaut : cle sans retrait, trading spot autorise."""

    def __init__(self, *, can_withdraw=False, can_trade=True, restrictions_raise=False,
                 quote_free=1000.0, base_free=0.0, no_restrictions_endpoint=False):
        self._can_withdraw = can_withdraw
        self._can_trade = can_trade
        self._restrictions_raise = restrictions_raise
        self.quote_free = quote_free
        self.base_free = base_free
        self.orders = []
        if no_restrictions_endpoint:
            # Simule un exchange qui n'expose pas cet endpoint : masque la
            # methode de classe par un attribut d'instance a None, ce que
            # `getattr(..., None)` cote executeur detecte.
            self.sapiGetAccountApiRestrictions = None

    def sapiGetAccountApiRestrictions(self):
        if self._restrictions_raise:
            raise RuntimeError("reseau indisponible")
        return {"enableWithdrawals": self._can_withdraw,
                "enableSpotAndMarginTrading": self._can_trade}

    def load_markets(self):
        return {}

    def market(self, symbol):
        return {"limits": {"amount": {"min": 0.0001}, "cost": {"min": 5.0}}}

    def fetch_balance(self):
        return {"USDT": {"free": self.quote_free}, "ETH": {"free": self.base_free}}

    def fetch_ticker(self, symbol):
        return {"last": 2000.0}

    def amount_to_precision(self, symbol, quantity):
        return round(quantity, 6)

    def create_order(self, symbol, order_type, side, quantity):
        self.orders.append((symbol, order_type, side, quantity))
        return {"filled": quantity, "average": 2000.0, "status": "closed"}


def build(**overrides):
    kwargs = dict(
        exchange_id="binance", symbol="ETH/USDT", max_order_notional=100.0,
        max_daily_loss=20.0, exchange=FakeExchange(), env=dict(GOOD_ENV),
        stop_file=None,
    )
    kwargs.update(overrides)
    if kwargs["stop_file"] is None:
        # Un chemin inexistant : l'interrupteur d'arret est donc absent.
        import pathlib
        kwargs["stop_file"] = pathlib.Path("aucun_fichier_d_arret_ici")
    return LiveExecutor(**kwargs)


# --- 1. drapeau d'activation explicite ---


def test_refuses_without_the_activation_flag():
    with pytest.raises(LiveTradingRefused, match=LIVE_FLAG_ENV):
        build(env={})


@pytest.mark.parametrize("value", ["1", "true", "True", "yes", "oui", "OUI-JE-VEUX", ""])
def test_refuses_any_approximate_flag_value(value):
    """Le drapeau doit valoir EXACTEMENT la phrase attendue : ni 1, ni true,
    ni une variante de casse - rien qu'on puisse poser par accident ou
    heriter d'un .env copie d'ailleurs."""
    with pytest.raises(LiveTradingRefused):
        build(env={LIVE_FLAG_ENV: value})


def test_accepts_the_exact_flag():
    executor = build()
    assert executor.max_order_notional == 100.0


# --- 2. cle API sans droit de retrait ---


def test_refuses_a_key_that_can_withdraw():
    """Le garde-fou le plus important : une cle avec retrait qui fuite vide
    le compte, et c'est le seul risque irreparable apres coup."""
    with pytest.raises(LiveTradingRefused, match="RETRAITS"):
        build(exchange=FakeExchange(can_withdraw=True))


def test_refuses_a_key_without_spot_trading():
    with pytest.raises(LiveTradingRefused, match="trading spot"):
        build(exchange=FakeExchange(can_trade=False))


def test_refuses_when_the_permission_check_itself_fails():
    """On ne suppose jamais que tout va bien faute d'information."""
    with pytest.raises(LiveTradingRefused, match="impossible"):
        build(exchange=FakeExchange(restrictions_raise=True))


def test_refuses_when_the_exchange_cannot_report_permissions():
    with pytest.raises(LiveTradingRefused, match="apiRestrictions"):
        build(exchange=FakeExchange(no_restrictions_endpoint=True))


# --- 3. plafond par ordre, obligatoire ---


@pytest.mark.parametrize("bad", [0, -1, None])
def test_refuses_without_a_positive_order_cap(bad):
    with pytest.raises(LiveTradingRefused, match="max_order_notional"):
        build(max_order_notional=bad)


@pytest.mark.parametrize("bad", [0, -1, None])
def test_refuses_without_a_positive_daily_loss_limit(bad):
    with pytest.raises(LiveTradingRefused, match="max_daily_loss"):
        build(max_daily_loss=bad)


def test_a_buy_above_the_cap_is_rejected_and_no_order_is_sent():
    exchange = FakeExchange()
    executor = build(exchange=exchange, max_order_notional=100.0)

    # 0,1 ETH a 2000 = 200 USDT, au-dela du plafond de 100.
    result = executor.place_order(Side.BUY, 0.1, 2000.0, timestamp=0)

    assert result.status == "rejected"
    assert "plafond" in result.reason
    assert exchange.orders == [], "aucun ordre ne doit partir vers l'exchange"


def test_a_buy_within_the_cap_goes_through():
    exchange = FakeExchange()
    executor = build(exchange=exchange, max_order_notional=100.0)

    result = executor.place_order(Side.BUY, 0.02, 2000.0, timestamp=0)

    assert result.status == "filled"
    assert len(exchange.orders) == 1


# --- 4. interrupteur d'arret ---


def test_refuses_to_start_when_the_stop_file_exists(tmp_path):
    stop = tmp_path / "STOP_LIVE_TRADING"
    stop.write_text("stop", encoding="utf-8")
    with pytest.raises(LiveTradingRefused, match="arret"):
        build(stop_file=stop)


def test_stop_file_created_while_running_blocks_further_orders(tmp_path):
    """Un fichier plutot qu'un reglage : on doit pouvoir arreter le bot sans
    dashboard, sans API et sans redemarrage."""
    stop = tmp_path / "STOP_LIVE_TRADING"
    exchange = FakeExchange()
    executor = build(exchange=exchange, stop_file=stop)

    assert executor.place_order(Side.BUY, 0.02, 2000.0, timestamp=0).status == "filled"
    stop.write_text("stop", encoding="utf-8")
    blocked = executor.place_order(Side.BUY, 0.02, 2000.0, timestamp=1)

    assert blocked.status == "rejected"
    assert "arret" in blocked.reason
    assert len(exchange.orders) == 1


def test_the_stop_file_also_blocks_sells(tmp_path):
    """Choix explicite et documente : l'interrupteur bloque TOUT, y compris
    les sorties. C'est le seul garde-fou dans ce cas."""
    stop = tmp_path / "STOP_LIVE_TRADING"
    exchange = FakeExchange(base_free=0.05)
    executor = build(exchange=exchange, stop_file=stop)
    orders_before = len(exchange.orders)
    stop.write_text("stop", encoding="utf-8")

    result = executor.place_order(Side.SELL, 0.05, 2000.0, timestamp=0)

    assert result.status == "rejected"
    assert len(exchange.orders) == orders_before


# --- 5. coupe-circuit de perte journaliere ---


def test_the_daily_loss_circuit_breaker_stops_buying():
    exchange = FakeExchange()
    executor = build(exchange=exchange, max_daily_loss=20.0)
    executor._realised_loss_today = 25.0  # perte du jour deja au-dela

    result = executor.place_order(Side.BUY, 0.02, 2000.0, timestamp=0)

    assert result.status == "rejected"
    assert "coupe-circuit" in result.reason
    assert exchange.orders == []


def test_the_circuit_breaker_never_blocks_a_sell():
    """Empecher de sortir d'une position serait un garde-fou qui AGGRAVE le
    risque - la vente doit toujours passer."""
    exchange = FakeExchange(base_free=0.05)
    executor = build(exchange=exchange, max_daily_loss=20.0)
    executor._realised_loss_today = 999.0

    result = executor.place_order(Side.SELL, 0.05, 2000.0, timestamp=0)

    assert result.status == "filled"


def test_realised_losses_accumulate_and_reset_on_a_new_day():
    exchange = FakeExchange(base_free=0.05)
    executor = build(exchange=exchange)
    executor._realised_loss_today = 12.0

    assert executor.realised_loss_today == 12.0
    executor._day = "1999-01-01"  # simule un changement de journee
    assert executor.realised_loss_today == 0.0


# --- comportements herites, a ne pas casser ---


def test_orders_below_exchange_limits_are_rejected():
    exchange = FakeExchange()
    executor = build(exchange=exchange)

    # 0,001 ETH a 2000 = 2 USDT, sous le minimum de 5 de l'exchange.
    result = executor.place_order(Side.BUY, 0.001, 2000.0, timestamp=0)

    assert result.status == "rejected"
    assert exchange.orders == []


def test_an_existing_balance_is_loaded_as_an_open_position():
    executor = build(exchange=FakeExchange(base_free=0.3))

    positions = executor.get_positions()
    assert len(positions) == 1
    assert positions[0].quantity == 0.3


def test_zero_quantity_is_rejected_without_calling_the_exchange():
    exchange = FakeExchange()
    executor = build(exchange=exchange)

    assert executor.place_order(Side.BUY, 0.0, 2000.0, timestamp=0).status == "rejected"
    assert exchange.orders == []
