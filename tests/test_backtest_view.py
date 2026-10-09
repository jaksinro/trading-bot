"""Atelier de backtest (EF-100) : moteur, couts, balayage, cache, routes."""
import json
import math
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pandas as pd
import pytest

from tradingbot import backtest_view as bv
from tradingbot.types import Candle, Side, Signal

H = 3_600_000
T0 = 1_735_689_600_000  # 2025-01-01 00:00 UTC


def series(n=24 * 60, start=T0, step=H):
    """Cours synthetique : tendance + oscillation, pour avoir des trades des deux cotes."""
    out = []
    for i in range(n):
        mid = 100 * (1 + 0.15 * math.sin(i * step / H / 90)) + i * step / H * 0.01
        out.append(Candle(timestamp=start + i * step, open=mid, high=mid * 1.004, low=mid * 0.996, close=mid * 1.001, volume=10.0))
    return out


@pytest.fixture
def market(monkeypatch):
    calls = []
    data = {"1h": series(), "5m": series(n=24 * 60 * 12, step=H // 12)}

    def fake_fetch(exchange_id, symbol, timeframe, since_iso, **kw):
        calls.append(timeframe)
        return data[timeframe]

    monkeypatch.setattr(bv, "fetch_historical_candles", fake_fetch)
    monkeypatch.setattr(bv, "extend_cache_to_now", lambda *a, **k: 0)
    return calls


def base(**kw):
    p = {"strategy_type": "trend_regime", "params": {"ema_period": 50, "entry_buffer_pct": 0.01},
         "symbol": "ETH/USDT", "timeframe": "1h", "start": "2025-01-05", "end": "2025-02-28",
         "warmup_bars": 60, "capital": 1000}
    p.update(kw)
    return p


# ---------------------------------------------------------------- catalogue et formulaire
def test_catalog_is_generated_from_the_strategies(tmp_path):
    (tmp_path / "A.yml").write_text("name: A\nsymbol: ETH/USDT\ntimeframe: 1d\nstrategy: {type: momentum_vote}\nrisk: {fee_pct: 0.0}\n")
    (tmp_path / "MM.yml").write_text("name: MM\nsymbol: ETH/USDT\ntimeframe: 1m\nstrategy: {type: market_making}\n")
    c = bv.catalog(tmp_path)
    mv = next(s for s in c["strategies"] if s["type"] == "momentum_vote")
    assert mv["params"][0] == {"name": "lookbacks", "label": bv.PARAM_LABELS["lookbacks"], "kind": "list_int",
                               "pct": False, "default": [7, 14, 30, 60, 90]}
    tr = next(s for s in c["strategies"] if s["type"] == "trend_regime")
    assert [p["name"] for p in tr["params"]] == ["ema_period", "entry_buffer_pct", "exit_buffer_pct"]   # chauffe cachee
    assert next(p for p in tr["params"] if p["name"] == "entry_buffer_pct")["pct"] is True
    assert [b["name"] for b in c["bots"]] == ["A"]                                                     # market making exclu


def test_parse_reads_lists_and_validates():
    spec = bv.parse({"strategy_type": "momentum_vote", "params": {"lookbacks": "7, 14;30"}, "timeframe": "1d"})
    assert spec["params"]["lookbacks"] == (7, 14, 30)
    assert spec["costs"] == {"fee_pct": 0.0, "spread_pct": 0.0, "overnight_pct": 0.0, "overnight_short_pct": 0.0}
    with pytest.raises(ValueError):
        bv.parse({"strategy_type": "inconnue"})
    with pytest.raises(ValueError, match="refuses"):
        bv.parse({"strategy_type": "momentum_vote", "params": {"lookbacks": "0"}})
    with pytest.raises(ValueError, match="plus fine"):
        bv.parse(base(exit_check_timeframe="4h"))
    with pytest.raises(ValueError, match="AAAA-MM-JJ"):
        bv.parse(base(start="01/02/2025"))


# ---------------------------------------------------------------- simulation
def test_trades_and_equity_are_consistent(market):
    r = bv.run(base())
    assert r["trades"], "le cours synthetique doit produire des trades"
    assert len(r["equity"]) == len(r["candles"]) == len(r["hold"])
    for tr in r["trades"]:
        assert tr["entry_t"] <= tr["exit_t"] and tr["entry_p"] > 0
    open_pnl = sum(p["pnl"] for p in r["open_positions"])
    assert r["stats"]["final_equity"] == pytest.approx(1000 + sum(t["pnl"] for t in r["trades"]) + open_pnl, rel=1e-6)
    assert r["stats"]["trades"] == len(r["trades"])
    assert r["overlays"] and r["overlays"][0]["label"].startswith("tendance")


def test_spread_costs_half_spread_per_order(market):
    free = bv.run(base())
    paid = bv.run(base(costs={"spread_pct": 0.004}))
    assert paid["stats"]["return"] < free["stats"]["return"]
    tr = paid["trades"][0]
    expected = tr["qty"] * (tr["entry_p"] + tr["exit_p"]) * 0.002
    assert tr["fees"] == pytest.approx(expected, rel=1e-6)
    assert "optimistes" in " ".join(free["warnings"]) and "optimistes" not in " ".join(paid["warnings"])


def test_overnight_financing_is_charged_per_day_held(market):
    p = base(strategy_type="buy_and_hold", params={}, start="2025-01-05", end="2025-01-14",
             costs={"overnight_pct": 0.001})
    r = bv.run(p)
    pos = r["open_positions"][0]
    # Achat le 05, puis un changement de jour par jour jusqu'au 14 inclus : 9 nuits.
    assert r["stats"]["financing_paid"] == pytest.approx(pos["qty"] * pos["entry_p"] * 0.001 * 9, rel=0.2)
    assert bv.run({**p, "costs": {}})["stats"]["final_equity"] > r["stats"]["final_equity"]


def test_strategies_start_flat_after_warmup(market):
    """Achat unique : son seul achat etait consomme pendant la chauffe. Le
    moteur lui transmet desormais l'etat reel (`align_position`, EF-102)."""
    r = bv.run(base(strategy_type="buy_and_hold", params={}))
    assert len(r["open_positions"]) == 1
    assert r["open_positions"][0]["entry_t"] == r["candles"][0][0]  # achat a la 1re bougie de la periode


def test_trade_stop_and_target_are_reported(market, monkeypatch):
    class OneShot:
        def __init__(self):
            self.n = 0

        def on_candle(self, c):
            self.n += 1
            return Signal(side=Side.BUY, reason="t", stop_price=c.close * 0.95, target_price=c.close * 1.02) if self.n == 80 else None

    monkeypatch.setitem(bv.STRATEGY_REGISTRY, "one_shot", OneShot)
    monkeypatch.setitem(bv.STRATEGIES, "one_shot", ("test", "test"))
    r = bv.run(base(strategy_type="one_shot", params={}, warmup_bars=0))
    tr = r["trades"][0]
    assert tr["target"] == pytest.approx(tr["entry_p"] * 1.02)
    assert tr["reason"] in ("objectif_trade", "stop_trade")


def test_short_trades_are_reported_with_their_direction_and_own_financing(market, monkeypatch):
    """EF-104 : vente a decouvert dans l'atelier. Gain si le prix baisse, taux de
    nuit propre aux ventes (negatif = credit recu)."""
    class ShortOnce:
        def __init__(self):
            self.n = 0

        def on_candle(self, c):
            self.n += 1
            if self.n == 80:
                return Signal(side=Side.SELL, reason="t", stop_price=c.close * 1.5, target_price=c.close * 0.5,
                              position_side="short")
            return None

    monkeypatch.setitem(bv.STRATEGY_REGISTRY, "short_once", ShortOnce)
    monkeypatch.setitem(bv.STRATEGIES, "short_once", ("test", "test"))
    p = base(strategy_type="short_once", params={}, warmup_bars=0, end="2025-01-20",
             costs={"overnight_short_pct": -0.001})
    r = bv.run(p)
    pos = r["open_positions"][0]
    last = r["candles"][-1][4]
    assert pos["direction"] == "short"
    assert (pos["pnl"] > 0) == (last < pos["entry_p"])          # latent du bon signe
    assert r["stats"]["financing_paid"] < 0                     # credit recu chaque nuit
    assert bv.run({**p, "costs": {}})["stats"]["final_equity"] < r["stats"]["final_equity"]
    with pytest.raises(ValueError):
        bv.parse({**p, "costs": {"overnight_pct": -0.001}})     # seul le taux des ventes peut etre negatif


def test_finer_exit_checks_run(market):
    r = bv.run(base(exit_check_timeframe="5m", risk={"stop_loss_pct": 0.01}))
    assert r["trades"] and "5m" in market


def test_semesters_split_on_calendar_halves(market):
    r = bv.run(base(start="2025-01-05", end="2025-02-28"))
    assert [s["label"] for s in r["semesters"]] == ["S1 2025*"]   # semestre incomplet : etoile


def test_sweep_reuses_the_same_candles(market):
    r = bv.sweep({**base(), "target": "params.ema_period", "values": [30, 50, 80]})
    assert [row["value"] for row in r["rows"]] == [30, 50, 80]
    assert market.count("1h") == 1
    assert len({round(row["stats"]["return"], 6) for row in r["rows"]}) == 3
    with pytest.raises(ValueError):
        bv.sweep({**base(), "target": "params.inconnu", "values": [1, 2]})
    with pytest.raises(ValueError):
        bv.sweep({**base(), "target": "params.ema_period", "values": [1]})


# ---------------------------------------------------------------- cache
class FakeExchange:
    def __init__(self, now, rows):
        self.now, self.rows = now, rows

    def parse_timeframe(self, tf):
        return 3600

    def milliseconds(self):
        return self.now

    def fetch_ohlcv(self, symbol, timeframe, since, limit):
        return [r for r in self.rows if r[0] >= since][:limit]


def test_extend_cache_appends_only_closed_candles(tmp_path, monkeypatch):
    from tradingbot import data_feed

    monkeypatch.setattr(data_feed, "CACHE_DIR", tmp_path)
    path = data_feed._cache_path("binance", "ETH/USDT", "1h")
    pd.DataFrame([[T0, 1, 1, 1, 1, 1], [T0 + H, 2, 2, 2, 2, 2]],
                 columns=["timestamp", "open", "high", "low", "close", "volume"]).to_parquet(path)
    rows = [[T0 + H, 2, 2, 2, 2, 2], [T0 + 2 * H, 3, 3, 3, 3, 3], [T0 + 3 * H, 4, 4, 4, 4, 4]]
    added = data_feed.extend_cache_to_now("binance", "ETH/USDT", "1h", exchange=FakeExchange(T0 + 3 * H + 10, rows))
    df = pd.read_parquet(path)
    assert added == 1 and list(df.timestamp) == [T0, T0 + H, T0 + 2 * H]   # la bougie de 03:00 n'est pas close


# ---------------------------------------------------------------- routes
@pytest.fixture
def server(tmp_path, monkeypatch, market):
    from tradingbot import control_server

    (tmp_path / "config").mkdir()
    monkeypatch.setattr(control_server, "CONFIG_DIR", tmp_path / "config")
    srv = ThreadingHTTPServer(("localhost", 0), control_server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://localhost:{srv.server_address[1]}"
    srv.shutdown()


def call(base_url, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base_url + path, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
            return r.status, (json.loads(body) if r.headers.get_content_type() == "application/json" else body)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_routes(server):
    status, page = call(server, "/backtest.html")
    assert status == 200 and b"Atelier de backtest" in page
    status, cat = call(server, "/api/bt-catalog")
    assert status == 200 and any(s["type"] == "volume_profile" for s in cat["strategies"])
    status, err = call(server, "/api/bt-run", {"strategy_type": "nope"})
    assert status == 400 and "inconnue" in err["error"]
    status, res = call(server, "/api/bt-run", base())
    assert status == 200 and res["trades"]
    status, sw = call(server, "/api/bt-sweep", {**base(), "target": "costs.spread_pct", "values": [0, 0.002]})
    assert status == 200 and sw["rows"][0]["stats"]["return"] > sw["rows"][1]["stats"]["return"]


def test_broker_costs_route_fills_the_cost_fields(server):
    """EF-106 : le courtier choisi donne les couts du formulaire."""
    status, r = call(server, "/api/bt-broker-costs", {"broker": "binance", "symbol": "ETH/USDT"})
    assert status == 200 and r["fee_pct"] == 0.001 and r["shorts"] is False
    status, err = call(server, "/api/bt-broker-costs", {"broker": "nope", "symbol": "ETH/USDT"})
    assert status == 400 and "courtier inconnu" in err["error"]
    status, cat = call(server, "/api/bt-catalog")
    assert cat["default_broker"] in [b["id"] for b in cat["brokers"]]


def test_short_warning_names_a_spot_broker(market):
    p = base(strategy_type="volume_profile", params={"allow_short": True}, timeframe="1h", broker="binance")
    assert any("n'autorise pas la vente a decouvert" in w for w in bv._warnings(bv.parse(p), []))
    with pytest.raises(ValueError):
        bv.parse({**p, "broker": "inconnu"})
    doge = bv.parse({**base(broker="ninjatrader"), "symbol": "DOGE/USDT"})
    assert any("n'est pas proposee" in w for w in bv._warnings(doge, []))
