"""Tests de la reception des alertes TradingView (EF-87) - aucun appel reseau,
aucun ordre reel : l'execution d'ordre est toujours remplacee."""
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from tradingbot import control_server
from tradingbot.tv_alerts import (
    AlertRejected,
    AlertStore,
    auto_order_plan,
    parse_alert,
    tradingview_ticker_to_symbol,
)

SECRET = "s3cret-de-test"


def body(**fields) -> bytes:
    return json.dumps(fields).encode()


def settings(**overrides):
    base = {"secret": SECRET, "auto_orders": False, "max_order_usdt": 100.0, "allowed_ips": []}
    base.update(overrides)
    return base


# --- decodage et authentification -------------------------------------------


def test_reception_is_closed_when_no_secret_is_configured():
    """Ferme par defaut : sans secret dans .env, rien n'est accepte."""
    with pytest.raises(AlertRejected) as exc:
        parse_alert(body(secret="", ticker="BINANCE:ETHUSDT"), secret="")
    assert exc.value.status == 403


@pytest.mark.parametrize("payload", [
    body(ticker="BINANCE:ETHUSDT", action="buy"),              # secret absent
    body(secret="faux", ticker="BINANCE:ETHUSDT", action="buy"),  # secret faux
])
def test_a_missing_or_wrong_secret_is_refused(payload):
    with pytest.raises(AlertRejected) as exc:
        parse_alert(payload, SECRET)
    assert exc.value.status == 401


def test_a_valid_json_alert_is_decoded_and_the_secret_is_never_stored():
    alert = parse_alert(body(secret=SECRET, ticker="BINANCE:ETHUSDT", action="BUY", price="2750,5",
                             message="croisement EMA"), SECRET)
    assert alert.ticker == "BINANCE:ETHUSDT"
    assert alert.action == "buy"
    assert alert.price == 2750.5
    assert SECRET not in alert.raw, "le secret ne doit jamais finir en base"


def test_a_plain_text_alert_needs_the_token_in_the_url():
    """TradingView envoie du texte brut si le message n'est pas du JSON : le
    secret ne peut alors venir que de l'adresse (?token=...)."""
    with pytest.raises(AlertRejected):
        parse_alert(b"ETH franchit 2800", SECRET)
    alert = parse_alert(b"ETH franchit 2800", SECRET, url_token=SECRET)
    assert alert.message == "ETH franchit 2800" and alert.action is None


def test_an_oversized_body_is_refused():
    with pytest.raises(AlertRejected) as exc:
        parse_alert(b"x" * 20_000, SECRET, url_token=SECRET)
    assert exc.value.status == 413


# --- correspondance des tickers ---------------------------------------------


@pytest.mark.parametrize("ticker, expected", [
    ("BINANCE:ETHUSDT", "ETH/USDT"),
    ("ETHUSDT", "ETH/USDT"),
    ("eth/usdt", "ETH/USDT"),
    ("BINANCE:DOGEUSDT.P", "DOGE/USDT"),
    ("BINANCE:BTCUSDTPERP", "BTC/USDT"),
    ("NASDAQ:AAPL", None),          # pas de devise crypto reconnue : on ne devine pas
    ("", None),
    (None, None),
])
def test_tradingview_tickers_map_to_exchange_symbols(ticker, expected):
    assert tradingview_ticker_to_symbol(ticker) == expected


# --- decision d'ordre ---------------------------------------------------------


def _alert(**fields):
    return parse_alert(body(secret=SECRET, **fields), SECRET)


def test_no_order_unless_auto_orders_are_explicitly_enabled():
    plan, why = auto_order_plan(_alert(ticker="ETHUSDT", action="buy"), enabled=False, max_order_usdt=100)
    assert plan is None and "desactives" in why


def test_a_buy_uses_the_cap_when_no_amount_is_given():
    plan, _ = auto_order_plan(_alert(ticker="ETHUSDT", action="buy"), enabled=True, max_order_usdt=50)
    assert plan == {"symbol": "ETH/USDT", "side": "buy", "amount": 50}


def test_a_buy_above_the_cap_is_refused():
    plan, why = auto_order_plan(_alert(ticker="ETHUSDT", action="buy", amount=500), enabled=True, max_order_usdt=100)
    assert plan is None and "plafond" in why


def test_a_sell_defaults_to_the_whole_position():
    plan, _ = auto_order_plan(_alert(ticker="ETHUSDT", action="sell"), enabled=True, max_order_usdt=100)
    assert plan == {"symbol": "ETH/USDT", "side": "sell", "quantity": "all"}


def test_an_unknown_ticker_never_becomes_an_order():
    plan, why = auto_order_plan(_alert(ticker="NASDAQ:AAPL", action="buy"), enabled=True, max_order_usdt=100)
    assert plan is None and "non reconnu" in why


def test_an_informational_alert_is_only_logged():
    plan, _ = auto_order_plan(_alert(ticker="ETHUSDT", action="note"), enabled=True, max_order_usdt=100)
    assert plan is None


# --- traitement complet --------------------------------------------------------


def test_an_alert_is_stored_with_its_decision(tmp_path):
    store = AlertStore(tmp_path / "a.db")
    status, result = control_server.handle_tradingview_alert(
        body(secret=SECRET, ticker="BINANCE:ETHUSDT", action="buy"), None, "52.89.214.238",
        settings=settings(), store=store,
    )
    assert status == 200 and result["order"] is None
    row = store.recent()[0]
    assert row["ticker"] == "BINANCE:ETHUSDT" and row["order_status"] == "aucun"


def test_the_ip_filter_rejects_unknown_senders(tmp_path):
    status, _ = control_server.handle_tradingview_alert(
        body(secret=SECRET), None, "1.2.3.4",
        settings=settings(allowed_ips=["52.89.214.238"]), store=AlertStore(tmp_path / "a.db"),
    )
    assert status == 403


def test_an_auto_order_runs_in_the_background_and_its_outcome_is_recorded(tmp_path, monkeypatch):
    """TradingView abandonne au-dela de 3 s : la reponse doit partir AVANT
    l'ordre, dont le resultat est rattache a l'alerte ensuite."""
    started = threading.Event()
    release = threading.Event()

    def slow_order(plan):
        started.set()
        release.wait(5)
        return 200, {"status": "filled", "side": "buy", "quantity": 0.01, "symbol": plan["symbol"], "price": 2750.0}

    monkeypatch.setattr(control_server, "execute_manual_order", slow_order)
    store = AlertStore(tmp_path / "a.db")

    t0 = time.monotonic()
    status, result = control_server.handle_tradingview_alert(
        body(secret=SECRET, ticker="ETHUSDT", action="buy", amount=20), None, "x",
        settings=settings(auto_orders=True), store=store,
    )
    elapsed = time.monotonic() - t0

    assert status == 200 and result["order"] == "en cours"
    assert elapsed < 1.0, "la reponse ne doit pas attendre l'ordre"
    assert started.wait(2)
    release.set()
    for _ in range(50):
        if store.recent()[0]["order_status"] == "execute":
            break
        time.sleep(0.05)
    assert store.recent()[0]["order_status"] == "execute"


def test_a_failing_background_order_is_recorded_not_lost(tmp_path, monkeypatch):
    def broken(plan):
        raise RuntimeError("testnet injoignable")
    monkeypatch.setattr(control_server, "execute_manual_order", broken)
    store = AlertStore(tmp_path / "a.db")
    control_server.handle_tradingview_alert(
        body(secret=SECRET, ticker="ETHUSDT", action="sell"), None, "x",
        settings=settings(auto_orders=True), store=store,
    )
    for _ in range(50):
        if store.recent()[0]["order_status"] == "erreur":
            break
        time.sleep(0.05)
    assert store.recent()[0]["order_status"] == "erreur"
    assert "testnet injoignable" in store.recent()[0]["order_detail"]


# --- par le vrai serveur HTTP ----------------------------------------------------
#
# La route du webhook est la seule a passer AVANT l'authentification HTTP Basic
# du dashboard (TradingView ne peut pas l'envoyer) : on verifie qu'elle reste
# protegee par son secret, et que les autres routes, elles, restent fermees.


class _RemoteHandler(control_server.Handler):
    def _client_is_loopback(self):
        return False


@pytest.fixture
def remote_server(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # AlertStore() ecrit data/tv_alerts.db ici, pas dans le projet
    monkeypatch.setenv(control_server.TV_SECRET_ENV, SECRET)
    monkeypatch.setenv(control_server.TV_AUTO_ORDERS_ENV, "0")
    monkeypatch.setenv(control_server.PASSWORD_ENV, "motdepasse-dashboard")
    monkeypatch.setattr(control_server, "load_dotenv", lambda *a, **k: None)
    server = ThreadingHTTPServer(("localhost", 0), _RemoteHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://localhost:{server.server_address[1]}"
    server.shutdown()


def _post(url, data: bytes):
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None


def test_webhook_reaches_the_app_without_dashboard_credentials(remote_server):
    status, result = _post(remote_server + "/api/tv-webhook", body(secret=SECRET, ticker="BINANCE:ETHUSDT", action="buy"))
    assert status == 200 and result["status"] == "recue"


def test_webhook_with_a_wrong_secret_is_refused_over_http(remote_server):
    status, _ = _post(remote_server + "/api/tv-webhook", body(secret="faux", ticker="ETHUSDT"))
    assert status == 401


def test_the_webhook_exemption_does_not_open_the_other_routes(remote_server):
    """L'exception d'authentification est limitee a CETTE route : un appel au
    passage d'ordre manuel sans identifiant doit rester refuse."""
    status, _ = _post(remote_server + "/api/manual-order", body(symbol="ETH/USDT", side="buy", amount=10))
    assert status == 401
    status, _ = _post(remote_server + "/api/tv-webhook/../manual-order", body(symbol="ETH/USDT", side="buy"))
    assert status in (401, 404)
