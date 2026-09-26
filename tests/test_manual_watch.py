"""Ordres conditionnels et protections du panier manuel, executes sans bot
(EF-90). Vrai panier sur une base temporaire ; l'exchange est remplace par un
executeur factice qui remplit au cours demande."""
import pytest

from tradingbot.manual_trading import ManualBook
from tradingbot.manual_watch import (
    CANCELLED, EXECUTED, PENDING, REJECTED, ConditionalOrders, PositionRisk, protection_to_fire, watch_cycle,
)
from tradingbot.types import OrderResult


class FillAtPrice:
    def __init__(self, prices):
        self.prices = prices

    def place_order(self, side, quantity, price, timestamp, reason="", lot_id=None):
        return OrderResult(side=side, quantity=quantity, price=price, timestamp=timestamp, status="filled")


@pytest.fixture
def world(tmp_path):
    db = tmp_path / "manual.db"
    book, orders, risk = ManualBook(db), ConditionalOrders(db), PositionRisk(db)
    prices = {"ETH/USDT": 2500.0}
    executed = []

    def execute(payload):
        """Meme contrat que `execute_manual_order` : (code HTTP, corps)."""
        executed.append(payload)
        price = prices[payload["symbol"]]
        if payload["side"] == "buy":
            r = book.buy(payload["symbol"], payload["amount"], price, FillAtPrice(prices), reason=payload.get("reason", "manuel"))
        else:
            q = payload.get("quantity")
            r = book.sell(payload["symbol"], None if q in (None, "all") else q, price, FillAtPrice(prices),
                          reason=payload.get("reason", "manuel"))
        return 200, {"status": r.status, "symbol": r.symbol, "side": r.side, "quantity": r.quantity,
                     "price": r.price, "reason": r.reason}

    def cycle():
        return watch_cycle(book, orders, risk, lambda s: prices[s], execute)

    book.deposit(1000)
    return book, orders, risk, prices, executed, cycle


# --- ordres conditionnels ---------------------------------------------------------


def test_a_buy_below_waits_then_fires_once(world):
    book, orders, _, prices, executed, cycle = world
    oid = orders.add("ETH/USDT", "buy", "below", 2400, amount=100)

    cycle()
    assert executed == [] and orders.recent()[0]["status"] == PENDING

    prices["ETH/USDT"] = 2390
    cycle()
    assert orders.recent()[0]["status"] == EXECUTED
    assert book.positions()["ETH/USDT"][0] == pytest.approx(100 / 2390)

    cycle()
    assert len(executed) == 1, "un ordre ne se declenche qu'une fois"


def test_a_sell_above_takes_profit(world):
    book, orders, _, prices, _, cycle = world
    orders.add("ETH/USDT", "buy", "below", 2600, amount=100)
    cycle()                                   # achete a 2500
    orders.add("ETH/USDT", "sell", "above", 2700)
    prices["ETH/USDT"] = 2710
    cycle()
    assert "ETH/USDT" not in book.positions()
    assert book.summary({})["cash"] > 1000 - 0.5, "revendu plus cher qu'achete"


def test_a_sell_without_position_is_refused_and_says_why(world):
    _, orders, _, prices, _, cycle = world
    orders.add("ETH/USDT", "sell", "below", 2600)
    cycle()
    order = orders.recent()[0]
    assert order["status"] == REJECTED and "aucune position" in order["detail"]


def test_a_cancelled_order_never_fires(world):
    _, orders, _, prices, executed, cycle = world
    oid = orders.add("ETH/USDT", "buy", "below", 2600, amount=100)
    orders.cancel(oid)
    cycle()
    assert executed == [] and orders.recent()[0]["status"] == CANCELLED


def test_a_cancel_between_check_and_execution_wins(world):
    _, orders, _, _, _, _ = world
    oid = orders.add("ETH/USDT", "buy", "below", 2600, amount=100)
    orders.cancel(oid)
    assert orders.claim(oid) is False


@pytest.mark.parametrize("args", [
    ("ETHUSDT", "buy", "below", 2400, 100),          # paire mal formee
    ("ETH/USDT", "buy", "above", 2400, 100),         # achat au-dessus
    ("ETH/USDT", "buy", "below", 2400, None),        # achat sans montant
    ("ETH/USDT", "sell", "below", 0, None),          # seuil nul
    ("ETH/USDT", "sell", "sideways", 2400, None),    # sens inconnu
])
def test_invalid_orders_are_refused(tmp_path, args):
    with pytest.raises(ValueError):
        ConditionalOrders(tmp_path / "m.db").add(*args)


def test_an_unavailable_price_skips_only_that_pair(world):
    book, orders, _, prices, executed, _ = world
    orders.add("ETH/USDT", "buy", "below", 2600, amount=100)
    orders.add("BTC/USDT", "buy", "below", 99_999, amount=100)

    def price_of(symbol):
        if symbol == "BTC/USDT":
            raise TimeoutError("reseau")
        return prices[symbol]

    from tradingbot.manual_watch import watch_cycle as wc
    events = wc(book, orders, PositionRisk(orders.db_path), price_of, lambda p: (200, {"status": "rejected"}))
    assert any("BTC/USDT" in e and "indisponible" in e for e in events)
    statuses = {o["symbol"]: o["status"] for o in orders.recent()}
    assert statuses["BTC/USDT"] == PENDING, "reste en attente, sera reessaye"


# --- protections --------------------------------------------------------------------


def test_protection_priority_and_levels():
    s = {"stop_loss_pct": 0.05, "take_profit_pct": 0.10, "trailing_stop_pct": 0.08}
    assert protection_to_fire(100, 100, 94, s) == ("stop-loss", pytest.approx(95))
    assert protection_to_fire(100, 120, 110, s) == ("trailing stop", pytest.approx(110.4))
    assert protection_to_fire(100, 111, 111, s) == ("objectif", pytest.approx(110))
    assert protection_to_fire(100, 105, 103, s) is None
    assert protection_to_fire(100, 100, 50, {}) is None, "aucune protection : rien ne se declenche"


def test_a_stop_loss_sells_the_manual_position(world):
    book, orders, risk, prices, executed, cycle = world
    orders.add("ETH/USDT", "buy", "below", 2600, amount=100)
    cycle()                                                   # achat a 2500
    risk.set("ETH/USDT", {"stop_loss_pct": 0.05})
    prices["ETH/USDT"] = 2370                                 # -5,2 %
    events = cycle()
    assert "ETH/USDT" not in book.positions()
    assert any(e.startswith("stop-loss ETH/USDT") for e in events)
    assert book.fills("ETH/USDT")[-1]["reason"] == "stop-loss", "le motif reste lisible dans l'historique"


def test_the_trailing_stop_follows_the_highest_price_seen(world):
    book, orders, risk, prices, _, cycle = world
    orders.add("ETH/USDT", "buy", "below", 2600, amount=100)
    cycle()
    risk.set("ETH/USDT", {"trailing_stop_pct": 0.10})
    for p in (2600, 2800, 3000):
        prices["ETH/USDT"] = p
        cycle()
    assert risk.get("ETH/USDT")["peak_price"] == 3000
    prices["ETH/USDT"] = 2750                                 # > 2700 = 3000 - 10 %
    cycle()
    assert "ETH/USDT" in book.positions()
    prices["ETH/USDT"] = 2690
    cycle()
    assert "ETH/USDT" not in book.positions()


def test_the_peak_restarts_for_a_new_position(world):
    book, orders, risk, prices, _, cycle = world
    risk.set("ETH/USDT", {"trailing_stop_pct": 0.10})
    orders.add("ETH/USDT", "buy", "below", 2600, amount=100)
    cycle()
    prices["ETH/USDT"] = 3000
    cycle()
    orders.add("ETH/USDT", "sell", "above", 2900)
    cycle()                                                   # soldee a 3000
    cycle()
    assert risk.get("ETH/USDT")["peak_price"] is None, "plus haut remis a zero"
    assert risk.get("ETH/USDT")["trailing_stop_pct"] == 0.10, "le reglage, lui, reste pour la prochaine position"


def test_settings_can_be_switched_off(tmp_path):
    risk = PositionRisk(tmp_path / "m.db")
    risk.set("ETH/USDT", {"stop_loss_pct": 0.05, "trailing_stop_pct": 0.1})
    risk.set("ETH/USDT", {"stop_loss_pct": None})
    assert risk.get("ETH/USDT")["stop_loss_pct"] is None
    assert risk.get("ETH/USDT")["trailing_stop_pct"] == 0.1, "un seul reglage modifie a la fois"


# --- surveillant et routes du serveur -------------------------------------------

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from tradingbot import control_server


def test_the_watcher_survives_a_failing_cycle(monkeypatch, tmp_path):
    """Lecon d'EF-85 : une erreur d'un passage est journalisee, et le passage
    suivant a lieu quand meme - le surveillant ne meurt jamais en silence."""
    import tradingbot.manual_watch as mw
    calls = []

    def boom(*args):
        calls.append(1)
        raise RuntimeError("panne d'un passage")

    monkeypatch.setattr(mw, "watch_cycle", boom)
    monkeypatch.setattr(control_server, "WATCH_LOG_PATH", tmp_path / "watch.log")
    stop = threading.Event()
    thread = threading.Thread(target=control_server.manual_watcher_loop, args=(stop, 0.01), daemon=True)
    thread.start()
    time.sleep(0.2)
    stop.set(); thread.join(2)

    assert len(calls) >= 2, "le surveillant a continue apres l'erreur"
    assert "panne d'un passage" in control_server.WATCHER_STATUS["last_error"]
    assert "ERREUR" in (tmp_path / "watch.log").read_text(encoding="utf-8")


class _Prices:
    def fetch_ticker(self, symbol):
        return {"last": 2500.0}


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)   # la base du panier (data/manual_trading.db) est creee ici
    monkeypatch.setattr(control_server, "_public_exchange", _Prices())
    control_server._manual_price_cache.clear()
    srv = ThreadingHTTPServer(("localhost", 0), control_server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://localhost:{srv.server_address[1]}"
    srv.shutdown()


def call(base, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_place_list_and_cancel_a_conditional_order_over_http(server):
    status, placed = call(server, "/api/manual-conditional",
                          {"symbol": "eth/usdt", "side": "buy", "direction": "below", "price": 2400, "amount": 50})
    assert status == 200
    status, state = call(server, "/api/manual-state?symbol=ETH%2FUSDT")
    assert status == 200 and state["price"] == 2500.0
    assert state["orders"][0]["status"] == PENDING and state["orders"][0]["amount"] == 50
    assert call(server, "/api/manual-conditional-cancel", {"id": placed["id"]})[0] == 200
    assert call(server, "/api/manual-conditional-cancel", {"id": placed["id"]})[0] == 409


def test_a_conditional_buy_without_amount_is_refused_over_http(server):
    status, _ = call(server, "/api/manual-conditional",
                     {"symbol": "ETH/USDT", "side": "buy", "direction": "below", "price": 2400})
    assert status == 400


def test_protections_are_saved_and_bounded_over_http(server):
    status, body = call(server, "/api/manual-risk", {"symbol": "ETH/USDT", "stop_loss_pct": 0.05, "trailing_stop_pct": 0.1})
    assert status == 200 and body["risk"]["stop_loss_pct"] == 0.05
    status, _ = call(server, "/api/manual-risk", {"symbol": "ETH/USDT", "stop_loss_pct": 2})
    assert status == 400, "stop-loss de 200 % refuse"
    status, state = call(server, "/api/manual-state?symbol=ETH%2FUSDT")
    assert state["risk"]["stop_loss_pct"] == 0.05, "la valeur refusee n'a rien ecrase"


def test_a_malformed_pair_is_refused(server):
    assert call(server, "/api/manual-state?symbol=ETHUSDT")[0] == 400
