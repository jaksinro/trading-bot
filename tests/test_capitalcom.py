"""Connecteur Capital.com (EF-101) : faux serveur, aucun appel reseau."""
import pytest

from tradingbot.brokers.capitalcom import DEMO_URL, CapitalComClient, CapitalComError


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.content = b"x" if body is not None else b""

    def json(self):
        if self._body is None:
            raise ValueError("pas de JSON")
        return self._body


class FakeHttp:
    """Repond selon (methode, chemin) ; garde chaque requete pour verification."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        handler = self.routes[(method, url.replace(DEMO_URL, ""))]
        return handler(kw) if callable(handler) else handler


LOGIN = Resp(200, {}, {"CST": "cst-1", "X-SECURITY-TOKEN": "tok-1"})


def client(routes, clock=lambda: 0.0):
    http = FakeHttp({("POST", "/session"): LOGIN, **routes})
    return CapitalComClient("cle", "moi@example.com", "secret", http=http, clock=clock), http


def test_live_account_is_refused():
    with pytest.raises(CapitalComError, match="compte reel refuse"):
        CapitalComClient("cle", "id", "pw", demo=False)


def test_missing_credentials_give_a_clear_error(monkeypatch):
    for k in ("CAPITALCOM_API_KEY", "CAPITALCOM_IDENTIFIER", "CAPITALCOM_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(CapitalComError, match="manquants"):
        CapitalComClient.from_env()


def test_login_once_then_reuse_tokens():
    c, http = client({("GET", "/accounts"): Resp(200, {"accounts": [{"balance": {"available": 1000}}]})})
    c.accounts()
    c.accounts()
    assert [(m, u.replace(DEMO_URL, "")) for m, u, _ in http.calls] == [
        ("POST", "/session"), ("GET", "/accounts"), ("GET", "/accounts")]
    login_kw = http.calls[0][2]
    assert login_kw["headers"]["X-CAP-API-KEY"] == "cle"
    assert login_kw["json"] == {"identifier": "moi@example.com", "password": "secret", "encryptedPassword": False}
    assert http.calls[1][2]["headers"]["CST"] == "cst-1" and http.calls[1][2]["headers"]["X-SECURITY-TOKEN"] == "tok-1"


def test_relogin_after_401_and_after_idle():
    now = [0.0]
    answers = iter([Resp(401, {"errorCode": "error.invalid.session.token"}), Resp(200, {"positions": []}),
                    Resp(200, {"positions": []})])
    c, http = client({("GET", "/positions"): lambda kw: next(answers)}, clock=lambda: now[0])
    assert c.positions() == []                                   # 401 -> reconnexion -> succes
    assert sum(u.endswith("/session") for _, u, _ in http.calls) == 2
    now[0] = 10 * 60                                             # 10 min d'inactivite
    c.positions()
    assert sum(u.endswith("/session") for _, u, _ in http.calls) == 3


def test_login_error_never_leaks_the_password():
    http = FakeHttp({("POST", "/session"): Resp(401, {"errorCode": "error.invalid.details"})})
    c = CapitalComClient("cle", "id", "MonMotDePasse", http=http)
    with pytest.raises(CapitalComError) as e:
        c.accounts()
    assert "MonMotDePasse" not in str(e.value) and "error.invalid.details" in str(e.value)


def test_quote_and_spread():
    c, _ = client({("GET", "/markets/ETHUSD"): Resp(200, {"snapshot": {"bid": 2499.0, "offer": 2501.0}})})
    q = c.quote("ETHUSD")
    assert q.mid == 2500.0 and q.spread_pct == pytest.approx(0.0008)


def test_candles_are_mid_prices_in_utc():
    bar = {"snapshotTimeUTC": "2025-01-01T00:00:00", "lastTradedVolume": 5,
           "openPrice": {"bid": 99, "ask": 101}, "highPrice": {"bid": 104, "ask": 106},
           "lowPrice": {"bid": 94, "ask": 96}, "closePrice": {"bid": 101, "ask": 103}}
    c, http = client({("GET", "/prices/ETHUSD"): Resp(200, {"prices": [bar]})})
    (candle,) = c.candles("ETHUSD", "1h", 10)
    assert candle.timestamp == 1_735_689_600_000
    assert (candle.open, candle.high, candle.low, candle.close) == (100, 105, 95, 102)
    assert http.calls[-1][2]["params"] == {"resolution": "HOUR", "max": 10}


def test_open_position_sends_levels_then_confirms():
    c, http = client({("POST", "/positions"): Resp(200, {"dealReference": "o_123"}),
                      ("GET", "/confirms/o_123"): Resp(200, {"dealStatus": "ACCEPTED", "dealId": "d1"})})
    conf = c.open_position("ETHUSD", "BUY", 0.5, stop_level=2400, profit_level=2700)
    assert conf["dealStatus"] == "ACCEPTED"
    assert http.calls[1][2]["json"] == {"epic": "ETHUSD", "direction": "BUY", "size": 0.5,
                                        "stopLevel": 2400, "profitLevel": 2700}
    with pytest.raises(ValueError):
        c.open_position("ETHUSD", "HOLD", 1)
