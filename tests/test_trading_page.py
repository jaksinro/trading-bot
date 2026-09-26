"""Page Trading (EF-89) : reglages de risque modifies sans perdre les
commentaires, ordres de vente dans les deux sens, routes de la page. Aucun
appel reseau, aucun ordre reel."""
import json
import sqlite3
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from tradingbot import control_server
from tradingbot.config_edit import update_risk_block, validate_risk_updates
from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.manual_triggers import TriggerStore
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal

CONFIG = """name: ETH_TEST
symbol: ETH/USDT
timeframe: 1h
strategy:
  type: trend_regime
  exit_buffer_pct: 0.0     # sort des le retour sous la tendance

risk:
  # Volontairement aucun stop-loss : mesure deux fois comme perdant.
  max_position_size_pct: 1.0
  stop_loss_pct: null
  trailing_stop_pct: null   # desactive expres
  max_daily_loss_pct: 0.05
  max_concurrent_positions: 1

backtest:
  starting_capital: 1000
"""


# --- modification des reglages ----------------------------------------------------


def test_values_change_and_every_comment_survives():
    new = update_risk_block(CONFIG, {"stop_loss_pct": 0.08, "trailing_stop_pct": 0.05})
    data = yaml.safe_load(new)
    assert data["risk"]["stop_loss_pct"] == 0.08
    assert data["risk"]["trailing_stop_pct"] == 0.05
    assert "# Volontairement aucun stop-loss : mesure deux fois comme perdant." in new
    assert "trailing_stop_pct: 0.05 # desactive expres" in new or "trailing_stop_pct: 0.05   # desactive expres" in new
    assert "# sort des le retour sous la tendance" in new


def test_nothing_outside_the_risk_block_is_touched():
    new = update_risk_block(CONFIG, {"max_concurrent_positions": 3})
    before, after = CONFIG.splitlines(), new.splitlines()
    changed = [(a, b) for a, b in zip(before, after) if a != b]
    assert changed == [("  max_concurrent_positions: 1", "  max_concurrent_positions: 3")]
    assert yaml.safe_load(new)["strategy"]["exit_buffer_pct"] == 0.0


def test_a_missing_key_is_added_inside_the_risk_block():
    new = update_risk_block(CONFIG, {"take_profit_pct": 0.2})
    data = yaml.safe_load(new)
    assert data["risk"]["take_profit_pct"] == 0.2
    assert data["backtest"] == {"starting_capital": 1000}, "ajoute DANS le bloc, pas apres"


def test_a_protection_can_be_switched_off():
    enabled = update_risk_block(CONFIG, {"stop_loss_pct": 0.08})
    disabled = update_risk_block(enabled, {"stop_loss_pct": None})
    assert yaml.safe_load(disabled)["risk"]["stop_loss_pct"] is None


def test_a_config_without_risk_block_is_refused():
    with pytest.raises(ValueError):
        update_risk_block("name: x\nstrategy:\n  type: y\n", {"stop_loss_pct": 0.1})


def test_the_real_eth_config_keeps_its_explanations():
    """Sur la vraie config du bot ETH, dont les commentaires expliquent
    pourquoi il n'a pas de stop-loss."""
    path = Path(__file__).resolve().parents[1] / "config" / "ETH_TREND_REGIME.yml"
    if not path.exists():
        pytest.skip("config ETH absente")
    text = path.read_text(encoding="utf-8")
    new = update_risk_block(text, {"stop_loss_pct": 0.1})
    assert yaml.safe_load(new)["risk"]["stop_loss_pct"] == 0.1
    assert [l for l in text.splitlines() if l.lstrip().startswith("#")] == \
           [l for l in new.splitlines() if l.lstrip().startswith("#")]


@pytest.mark.parametrize("updates", [
    {"stop_loss_pct": 0},          # 0 % vendrait au premier tick
    {"stop_loss_pct": 1.5},        # 150 % : absurde
    {"trailing_stop_pct": -0.1},
    {"max_concurrent_positions": 0},
    {"max_concurrent_positions": 2.5},
    {"max_daily_loss_pct": None},  # ne se desactive pas
    {"leverage": 5},               # cle non modifiable
    {"profit_lock_arm_pct": 0.05, "profit_lock_trigger_pct": 0.08},  # vendrait AU-DESSUS de l'armement
])
def test_out_of_range_values_are_refused(updates):
    with pytest.raises(ValueError):
        validate_risk_updates(updates)


def test_valid_values_are_normalised():
    assert validate_risk_updates({"stop_loss_pct": "0.08", "max_concurrent_positions": 2.0, "take_profit_pct": ""}) == \
        {"stop_loss_pct": 0.08, "max_concurrent_positions": 2, "take_profit_pct": None}


# --- ordres de vente ------------------------------------------------------------------


def test_sell_orders_fire_in_their_own_direction(tmp_path):
    store = TriggerStore(tmp_path / "b.db")
    take_profit = store.add("sell", "above", 3000)
    stop = store.add("sell", "below", 2400)
    assert store.due(2700) == []
    assert [t["id"] for t in store.due(3000)] == [take_profit]
    assert [t["id"] for t in store.due(2400)] == [stop]


def test_a_buy_above_a_price_is_refused(tmp_path):
    with pytest.raises(ValueError):
        TriggerStore(tmp_path / "b.db").add("buy", "above", 3000)


def test_a_database_from_before_sell_orders_is_migrated(tmp_path):
    """La base du bot ETH contient deja un ordre cree avant l'ajout du sens :
    elle doit etre completee sur place, l'ancien ordre valant un achat 'sous'."""
    db = tmp_path / "old.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE manual_triggers (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, "
                       "side TEXT NOT NULL, trigger_price REAL NOT NULL, status TEXT NOT NULL, resolved_at TEXT, detail TEXT)")
    connection.execute("INSERT INTO manual_triggers (created_at, side, trigger_price, status) VALUES ('x', 'buy', 2500, 'en attente')")
    connection.commit(); connection.close()

    store = TriggerStore(db)
    assert store.recent()[0]["direction"] == "below"
    assert [t["trigger_price"] for t in store.due(2400)] == [2500]


class Silent(Strategy):
    def on_candle(self, candle):
        return None


def test_a_manual_sell_closes_the_bot_position():
    executor = BacktestExecutor(Portfolio(starting_capital=1000.0))
    engine = Engine(Silent(), RiskManager(RiskConfig(max_position_size_pct=0.5, stop_loss_pct=None)),
                    executor, executor.portfolio)
    tick = lambda p, ts: Candle(timestamp=ts, open=p, high=p, low=p, close=p, volume=0)
    engine.process_manual_signal(Signal(side=Side.BUY, reason="ordre_manuel"), tick(2500, 1))
    messages = engine.process_manual_signal(Signal(side=Side.SELL, reason="ordre_manuel"), tick(2600, 2))

    assert any(m.startswith("Vente executee") for m in messages)
    assert executor.get_positions() == []


def test_a_manual_sell_without_position_is_refused_not_crashed():
    executor = BacktestExecutor(Portfolio(starting_capital=1000.0))
    engine = Engine(Silent(), RiskManager(RiskConfig()), executor, executor.portfolio)
    messages = engine.process_manual_signal(Signal(side=Side.SELL, reason="ordre_manuel"),
                                            Candle(timestamp=1, open=1, high=1, low=1, close=1, volume=0))
    assert not any(m.startswith("Vente executee") for m in messages)


# --- routes ----------------------------------------------------------------------------


class FakeExchange:
    def fetch_ohlcv(self, symbol, timeframe, limit):
        return [[1_790_000_000_000 + i * 60_000, 10.0, 12.0, 9.0, 11.0, 5.0] for i in range(limit)]


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "ETH_TEST.yml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr(control_server, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(control_server, "ROOT", tmp_path)
    monkeypatch.setattr(control_server, "_public_exchange", FakeExchange())
    monkeypatch.setattr(control_server, "is_bot_running", lambda name: False)
    control_server._candles_cache.clear()
    srv = ThreadingHTTPServer(("localhost", 0), control_server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://localhost:{srv.server_address[1]}", tmp_path
    srv.shutdown()


def call(base, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"},
                                     method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as r:
            body = r.read()
            return r.status, (json.loads(body) if r.headers.get_content_type() == "application/json" else body)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_the_trading_page_is_served(server):
    base, _ = server
    status, body = call(base, "/trading.html?bot=ETH_TEST")
    assert status == 200 and b"Espace Trading" in body


def test_candles_come_in_the_requested_timeframe(server):
    base, _ = server
    status, body = call(base, "/api/candles?symbol=ETH%2FUSDT&timeframe=15m&limit=50")
    assert status == 200 and len(body["candles"]) == 50
    assert body["candles"][0][1:5] == [10.0, 12.0, 9.0, 11.0], "ouverture, haut, bas, cloture"


def test_an_unknown_timeframe_is_refused(server):
    base, _ = server
    status, _ = call(base, "/api/candles?symbol=ETH%2FUSDT&timeframe=7m")
    assert status == 400


def test_bot_state_returns_config_and_risk(server):
    base, _ = server
    status, body = call(base, "/api/bot-state?name=ETH_TEST")
    assert status == 200
    assert body["symbol"] == "ETH/USDT" and body["strategy_type"] == "trend_regime"
    assert body["risk"]["max_daily_loss_pct"] == 0.05


def test_risk_settings_are_written_with_comments_kept(server):
    base, root = server
    status, body = call(base, "/api/bot-risk", {"name": "ETH_TEST", "risk": {"stop_loss_pct": 0.08}})
    assert status == 200 and body["restarted"] is False
    text = (root / "config" / "ETH_TEST.yml").read_text(encoding="utf-8")
    assert yaml.safe_load(text)["risk"]["stop_loss_pct"] == 0.08
    assert "Volontairement aucun stop-loss" in text


def test_invalid_risk_settings_leave_the_file_untouched(server):
    base, root = server
    before = (root / "config" / "ETH_TEST.yml").read_text(encoding="utf-8")
    status, _ = call(base, "/api/bot-risk", {"name": "ETH_TEST", "risk": {"stop_loss_pct": 5}})
    assert status == 400
    assert (root / "config" / "ETH_TEST.yml").read_text(encoding="utf-8") == before


def test_a_sell_order_is_accepted_over_http(server):
    base, _ = server
    status, body = call(base, "/api/bot-trigger", {"name": "ETH_TEST", "price": 3000, "side": "sell", "direction": "above"})
    assert status == 200 and body["side"] == "sell"
    status, listed = call(base, "/api/bot-triggers?name=ETH_TEST")
    assert listed["triggers"][0]["direction"] == "above"


def test_open_orders_publish_the_peak_even_without_trailing():
    """L'apercu du trailing part du plus haut depuis l'achat : ce plus haut doit
    etre publie meme quand le trailing est desactive."""
    from tradingbot.reporting.stats import build_orders_table
    portfolio = Portfolio(starting_capital=1000.0)
    BacktestExecutor(portfolio).place_order(Side.BUY, 1.0, 100.0, 1)
    portfolio.positions[0].peak_price = 130.0
    row = [r for r in build_orders_table(portfolio, RiskConfig()) if r["status"] == "ouvert"][0]
    assert row["peak_price"] == 130.0


def test_applying_settings_keeps_the_file_line_endings(server):
    """Un fichier en fins de ligne Unix ne doit pas etre converti en entier
    (Windows ecrit du CRLF en mode texte) pour une modification d'une ligne."""
    base, root = server
    path = root / "config" / "ETH_TEST.yml"
    path.write_bytes(CONFIG.encode("utf-8"))  # fins de ligne Unix
    call(base, "/api/bot-risk", {"name": "ETH_TEST", "risk": {"stop_loss_pct": 0.08}})
    raw = path.read_bytes()
    assert b"\r\n" not in raw
    changed = [l for l in raw.decode().splitlines() if l not in CONFIG.splitlines()]
    assert changed == ["  stop_loss_pct: 0.08"]
