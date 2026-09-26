"""Ordres "acheter si le cours descend sous X" poses a la main sur un bot, et
zones affichees sur son graphique (EF-88). Aucun appel reseau, aucun ordre
reel : moteur reel sur un executeur de backtest."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from tradingbot import control_server
from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.manual_triggers import CANCELLED, EXECUTED, PENDING, REJECTED, TriggerStore
from tradingbot.portfolio import Portfolio
from tradingbot.reporting.stats import build_orders_table
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.run_paper import strategy_chart_levels
from tradingbot.strategies.base import Strategy
from tradingbot.strategies.trend_regime import TrendRegimeStrategy
from tradingbot.types import Candle, Side, Signal


# --- registre -----------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return TriggerStore(tmp_path / "bot.db")


def test_a_trigger_fires_when_the_price_reaches_or_goes_below_it(store):
    tid = store.add_buy_below(2500)
    assert store.due(2600) == []
    assert [t["id"] for t in store.due(2500)] == [tid], "au niveau : declenche"
    assert [t["id"] for t in store.due(2400)] == [tid]


def test_a_trigger_price_must_be_positive(store):
    for bad in (0, -10, None):
        with pytest.raises(ValueError):
            store.add_buy_below(bad)


def test_a_cancelled_trigger_never_fires(store):
    tid = store.add_buy_below(2500)
    assert store.cancel(tid)
    assert store.due(1000) == []
    assert store.recent()[0]["status"] == CANCELLED


def test_a_cancel_between_check_and_execution_wins(store):
    """Le bot releve l'ordre, puis l'utilisateur l'annule avant l'execution :
    la reservation doit echouer et l'ordre ne pas partir."""
    tid = store.add_buy_below(2500)
    assert store.due(2400)
    store.cancel(tid)
    assert store.claim(tid) is False


def test_an_executed_trigger_fires_only_once(store):
    tid = store.add_buy_below(2500)
    assert store.claim(tid)
    store.finish(tid, EXECUTED, "achat execute")
    assert store.due(1000) == []
    assert store.cancel(tid) is False, "on n'annule pas un ordre deja execute"


def test_a_reading_on_a_bot_that_never_had_triggers_creates_nothing(tmp_path):
    db = tmp_path / "jamais.db"
    assert TriggerStore(db).recent() == []
    assert not db.exists()


# --- execution par le vrai moteur ---------------------------------------------


class SilentStrategy(Strategy):
    """Ne signale jamais rien, et compte ses appels : un ordre manuel ne doit
    pas faire avancer la strategie."""

    def __init__(self):
        self.calls = 0

    def on_candle(self, candle):
        self.calls += 1
        return None


def make_engine(max_positions=1):
    executor = BacktestExecutor(Portfolio(starting_capital=1000.0))
    risk = RiskManager(RiskConfig(max_position_size_pct=0.5, max_concurrent_positions=max_positions,
                                  stop_loss_pct=None, max_daily_loss_pct=0.05))
    strategy = SilentStrategy()
    return Engine(strategy, risk, executor, executor.portfolio), executor, strategy


def tick(price, ts=1_790_000_000_000):
    return Candle(timestamp=ts, open=price, high=price, low=price, close=price, volume=0.0)


def test_a_manual_buy_goes_through_the_engine_and_opens_a_position():
    engine, executor, strategy = make_engine()
    messages = engine.process_manual_signal(Signal(side=Side.BUY, reason="ordre_manuel"), tick(2500))

    assert any(m.startswith("Achat execute") for m in messages)
    assert len(executor.get_positions()) == 1
    assert strategy.calls == 0, "la strategie n'avance qu'avec les vraies bougies"


def test_a_manual_buy_respects_the_position_limit():
    """Meme garde-fous qu'un signal de la strategie : sur un bot deja en
    position avec un maximum de 1, l'ordre manuel est refuse, et le dit."""
    engine, executor, _ = make_engine(max_positions=1)
    engine.process_manual_signal(Signal(side=Side.BUY, reason="ordre_manuel"), tick(2500))
    messages = engine.process_manual_signal(Signal(side=Side.BUY, reason="ordre_manuel"), tick(2400, ts=1_790_000_060_000))

    assert len(executor.get_positions()) == 1
    assert any("limite" in m for m in messages)


def test_the_manual_decision_is_reported_to_the_journal():
    engine, _, _ = make_engine()
    seen = []
    engine.on_decision = lambda candle, message: seen.append(message)
    engine.process_manual_signal(Signal(side=Side.BUY, reason="ordre_manuel"), tick(2500))
    assert seen and seen[0].startswith("[ordre manuel]")


# --- niveaux affiches ------------------------------------------------------------


def test_trend_regime_exposes_its_trend_and_thresholds():
    strategy = TrendRegimeStrategy(ema_period=3, entry_buffer_pct=0.03, exit_buffer_pct=0.02, warmup_candles=0)
    assert strategy.chart_levels() == [], "rien tant que l'EMA n'existe pas"
    for price in (100, 100, 100):
        strategy.on_candle(tick(price))
    levels = {lv["kind"]: lv["price"] for lv in strategy.chart_levels()}
    assert levels["trend"] == pytest.approx(100)
    assert levels["entry"] == pytest.approx(103)
    assert levels["exit"] == pytest.approx(98)


def test_without_an_exit_buffer_the_trend_line_is_the_exit():
    strategy = TrendRegimeStrategy(ema_period=3, entry_buffer_pct=0.03, exit_buffer_pct=0.0, warmup_candles=0)
    strategy.on_candle(tick(100))
    kinds = [lv["kind"] for lv in strategy.chart_levels()]
    assert kinds == ["trend", "entry"]
    assert "sortie" in strategy.chart_levels()[0]["label"]


def test_a_strategy_without_levels_or_with_a_broken_getter_shows_nothing():
    class Broken:
        def chart_levels(self):
            raise RuntimeError("bug d'affichage")
    assert strategy_chart_levels(SilentStrategy()) == []
    assert strategy_chart_levels(Broken()) == [], "un simple affichage ne doit jamais faire planter le bot"


def test_open_orders_carry_trailing_and_profit_lock_levels():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    executor.place_order(Side.BUY, 1.0, 100.0, 1)
    portfolio.positions[0].peak_price = 120.0
    config = RiskConfig(trailing_stop_pct=0.10, profit_lock_arm_pct=0.05, profit_lock_trigger_pct=0.02)

    row = [r for r in build_orders_table(portfolio, config) if r["status"] == "ouvert"][0]

    assert row["target_trailing_stop"] == pytest.approx(108.0), "10 % sous le plus haut atteint (120)"
    assert row["profit_lock_arm"] == pytest.approx(105.0)
    assert row["profit_lock_trigger"] == pytest.approx(102.0)


def test_disabled_protections_publish_no_level():
    portfolio = Portfolio(starting_capital=1000.0)
    BacktestExecutor(portfolio).place_order(Side.BUY, 1.0, 100.0, 1)
    row = [r for r in build_orders_table(portfolio, RiskConfig()) if r["status"] == "ouvert"][0]
    assert row["target_trailing_stop"] is None and row["profit_lock_arm"] is None


# --- routes du serveur -------------------------------------------------------------


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "ETH_BOT.yml").write_text("name: ETH_BOT\n", encoding="utf-8")
    monkeypatch.setattr(control_server, "CONFIG_DIR", tmp_path / "config")
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
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_place_list_and_cancel_a_trigger_over_http(server):
    base, root = server
    status, placed = call(base, "/api/bot-trigger", {"name": "ETH_BOT", "price": 2500})
    assert status == 200

    status, listed = call(base, "/api/bot-triggers?name=ETH_BOT")
    assert listed["triggers"][0]["status"] == PENDING
    assert (root / "data" / "ETH_BOT.db").exists(), "stocke dans la base du bot, qui l'executera"

    status, _ = call(base, "/api/bot-trigger-cancel", {"name": "ETH_BOT", "id": placed["id"]})
    assert status == 200
    status, _ = call(base, "/api/bot-trigger-cancel", {"name": "ETH_BOT", "id": placed["id"]})
    assert status == 409, "un ordre deja annule ne s'annule pas deux fois"


@pytest.mark.parametrize("name", ["BOT_INCONNU", "../shared_pool", "..\\\\config\\\\ETH_BOT", ""])
def test_only_existing_bots_can_receive_a_trigger(server, name):
    """Le nom sert a construire un chemin de fichier : il ne doit jamais
    designer autre chose que la base d'un bot existant."""
    base, root = server
    status, _ = call(base, "/api/bot-trigger", {"name": name, "price": 2500})
    assert status == 404
    assert not (root / "data" / "shared_pool.db").exists()


def test_an_invalid_price_is_refused(server):
    base, _ = server
    for bad in (0, -1, "abc", None):
        status, _ = call(base, "/api/bot-trigger", {"name": "ETH_BOT", "price": bad})
        assert status == 400
