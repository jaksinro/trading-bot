"""EF-103 - le 2026-10-07 a 09h51, le testnet Binance a repondu "502 Bad
Gateway" au chargement des marches (`load_markets`, dans le constructeur de
PaperExecutor). L'erreur est survenue AVANT la boucle protegee par EF-85 : le
processus est mort et ETH_MOMENTUM est reste a l'arret jusqu'a l'ouverture de
session suivante. Le demarrage reessaie desormais, avec une attente
croissante, sur toute erreur reseau passagere, journalise chaque tentative et
abandonne proprement au-dela d'un delai borne."""
import sqlite3

import ccxt
import pytest
import requests
import yaml

from tradingbot import run_paper
from tradingbot.execution.paper_executor import PaperExecutor
from tradingbot.reporting.logger import TradeLogger
from tradingbot.run_paper import (
    StartupNetworkGiveUp,
    StartupRetry,
    is_transient_network_error,
    warm_up_strategy,
)

# Message exact de l'exception levee par ccxt le 2026-10-07 (logs/ETH_MOMENTUM.log).
BAD_GATEWAY = (
    "binance GET https://testnet.binance.vision/api/v3/exchangeInfo 502 Bad Gateway <html>\n"
    "<head><title>502 Bad Gateway</title></head>\n<body>\n"
    "<center><h1>502 Bad Gateway</h1></center>\n<hr><center>nginx</center>\n</body>\n</html>\n"
)
HOUR_MS = 3_600_000
FIRST_TS = 1_700_000_000_000


class FlakyExchange:
    """Exchange factice : `load_markets` repond 502 ses `load_markets_failures`
    premiers appels, `fetch_ohlcv` expire ses `ohlcv_failures` premiers appels."""

    def __init__(self, load_markets_failures: int = 0, ohlcv_failures: int = 0, load_markets_error=None):
        self.load_markets_failures = load_markets_failures
        self.ohlcv_failures = ohlcv_failures
        self.load_markets_error = load_markets_error or ccxt.ExchangeNotAvailable(BAD_GATEWAY)
        self.load_markets_calls = 0
        self.ohlcv_calls = 0

    def load_markets(self):
        self.load_markets_calls += 1
        if self.load_markets_calls <= self.load_markets_failures:
            raise self.load_markets_error

    def fetch_balance(self):
        return {"USDT": {"free": 1000.0}, "ETH": {"free": 0.0}}

    def fetch_ticker(self, symbol):
        return {"last": 2000.0}

    def parse_timeframe(self, timeframe):
        return 3600

    def fetch_ohlcv(self, symbol, timeframe="1h", since=None, limit=None):
        self.ohlcv_calls += 1
        if self.ohlcv_calls <= self.ohlcv_failures:
            raise ccxt.RequestTimeout("binance GET https://api.binance.com/api/v3/klines delai depasse")
        return [[FIRST_TS + i * HOUR_MS, 2000.0 + i, 2001.0 + i, 1999.0 + i, 2000.0 + i, 10.0]
                for i in range(limit or 10)]


class FakeClock:
    """Horloge et sommeil simules : aucun test n'attend reellement."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _events(logger: TradeLogger) -> list[tuple[str, str]]:
    return logger.conn.execute("SELECT level, message FROM events ORDER BY id").fetchall()


def test_502_on_load_markets_at_startup_is_retried_until_the_exchange_answers(tmp_path, monkeypatch):
    """Reproduction de l'incident : deux 502 sur `exchangeInfo`, puis le
    testnet repond. Le bot doit demarrer au lieu de mourir."""
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("startup_502")
    clock = FakeClock()
    fake = FlakyExchange(load_markets_failures=2)
    startup = StartupRetry(logger, sleep=clock.sleep, clock=clock.time)

    executor = startup.run("connexion a l'exchange", lambda: PaperExecutor("binance", "ETH/USDT", exchange=fake))

    assert fake.load_markets_calls == 3
    assert executor.portfolio.starting_capital == 1000.0
    assert clock.sleeps == [5, 10]  # attente croissante
    events = _events(logger)
    assert [level for level, _ in events] == ["warning", "warning", "info"]
    assert "tentative 1" in events[0][1] and "502 Bad Gateway" in events[0][1]
    assert "<body>" not in events[0][1]  # pas de page HTML dans le journal
    assert "tentative 2" in events[1][1]
    assert "reussi" in events[2][1]
    logger.close()


def test_startup_gives_up_cleanly_after_the_time_budget(tmp_path, monkeypatch):
    """Exchange durablement indisponible : abandon au bout du budget, avec une
    erreur claire journalisee - pas une pile d'appels illisible."""
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("startup_give_up")
    clock = FakeClock()
    fake = FlakyExchange(load_markets_failures=10_000)
    startup = StartupRetry(logger, budget_seconds=900, sleep=clock.sleep, clock=clock.time)

    with pytest.raises(StartupNetworkGiveUp) as excinfo:
        startup.run("connexion a l'exchange", lambda: PaperExecutor("binance", "ETH/USDT", exchange=fake))

    assert clock.now == 900  # ni plus tot, ni plus tard
    assert clock.sleeps[:6] == [5, 10, 20, 40, 80, 120]
    assert max(clock.sleeps) == 120  # attente plafonnee
    message = str(excinfo.value)
    assert "DEMARRAGE ABANDONNE" in message and "connexion a l'exchange" in message
    assert f"{fake.load_markets_calls} tentatives" in message
    level, logged = _events(logger)[-1]
    assert level == "error" and logged == message
    logger.close()


def test_the_budget_is_shared_by_every_startup_step(tmp_path, monkeypatch):
    """Le delai est celui de TOUT le demarrage : une etape suivante ne repart
    pas avec un budget neuf (sinon 3 etapes = 3 fois l'attente annoncee)."""
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("startup_shared_budget")
    clock = FakeClock()
    startup = StartupRetry(logger, budget_seconds=60, sleep=clock.sleep, clock=clock.time)
    fake = FlakyExchange(load_markets_failures=3)
    startup.run("connexion a l'exchange", lambda: PaperExecutor("binance", "ETH/USDT", exchange=fake))
    assert clock.now == 35  # 5 + 10 + 20

    always_down = FlakyExchange(ohlcv_failures=10_000)
    with pytest.raises(StartupNetworkGiveUp):
        startup.run("historique", lambda: always_down.fetch_ohlcv("ETH/USDT", limit=2))
    assert clock.now == 60
    logger.close()


@pytest.mark.parametrize("error", [
    ccxt.AuthenticationError("binance {\"code\":-2015,\"msg\":\"Invalid API-key\"}"),
    ccxt.BadSymbol("paire inconnue"),
    ValueError("bug de logique"),
])
def test_non_network_errors_at_startup_still_stop_immediately(tmp_path, monkeypatch, error):
    """Une cle invalide ou un bug ne se corrige pas en attendant : arret
    immediat, sans attente ni tentative supplementaire."""
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("startup_fatal")
    clock = FakeClock()
    fake = FlakyExchange(load_markets_failures=1, load_markets_error=error)
    startup = StartupRetry(logger, sleep=clock.sleep, clock=clock.time)

    with pytest.raises(type(error)):
        startup.run("connexion a l'exchange", lambda: PaperExecutor("binance", "ETH/USDT", exchange=fake))

    assert fake.load_markets_calls == 1
    assert clock.sleeps == []
    logger.close()


class RecordingStrategy:
    def __init__(self):
        self.seen: list[int] = []

    def on_candle(self, candle):
        self.seen.append(candle.timestamp)


def test_retried_warm_up_feeds_each_candle_exactly_once(tmp_path, monkeypatch):
    """Le rechauffage telecharge tout l'historique AVANT de nourrir la
    strategie : un nouvel essai apres expiration ne doit jamais lui faire
    compter une bougie deux fois (indicateurs fausses en silence)."""
    monkeypatch.chdir(tmp_path)
    logger = TradeLogger("startup_warmup")
    clock = FakeClock()
    fake = FlakyExchange(ohlcv_failures=1)
    strategy = RecordingStrategy()
    startup = StartupRetry(logger, sleep=clock.sleep, clock=clock.time)

    startup.run("rechauffage", lambda: warm_up_strategy(fake, "ETH/USDT", "1h", strategy, 20))

    assert fake.ohlcv_calls == 2
    assert len(strategy.seen) == 20
    assert len(set(strategy.seen)) == 20
    logger.close()


@pytest.mark.parametrize("status, transient", [(502, True), (503, True), (504, True), (400, False), (401, False)])
def test_raw_http_gateway_errors_are_transient(status, transient):
    """Le 502 du 2026-10-07 est d'abord une `requests.HTTPError` (traduite
    ensuite par ccxt en ExchangeNotAvailable) : la forme brute est reconnue
    aussi, mais seulement pour les codes de passerelle/indisponibilite."""
    response = requests.Response()
    response.status_code = status
    error = requests.exceptions.HTTPError(f"{status} Server Error", response=response)
    assert is_transient_network_error(error) is transient


def test_run_paper_main_survives_a_502_at_startup(tmp_path, monkeypatch):
    """Scenario complet du 2026-10-07 : `main()` (le vrai point d'entree du
    bot) recoit deux 502 au chargement des marches, attend, puis demarre et
    entre dans sa boucle - au lieu de planter."""
    monkeypatch.chdir(tmp_path)
    config = {
        "name": "STARTUP_502_TEST",
        "exchange": "binance",
        "symbol": "ETH/USDT",
        "timeframe": "1h",
        "warmup_candles": 5,
        "flatten_on_start": False,
        "capital_allocated": 200,
        "strategy": {"type": "trend_regime", "ema_period": 5, "entry_buffer_pct": 0.03, "exit_buffer_pct": 0.0},
        "risk": {"max_position_size_pct": 1.0, "fee_pct": 0.0},
    }
    config_path = tmp_path / "bot.yml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    fake = FlakyExchange(load_markets_failures=2)
    monkeypatch.setattr(run_paper, "PaperExecutor",
                        lambda exchange_id, symbol, api_key, api_secret: PaperExecutor(exchange_id, symbol, exchange=fake))
    monkeypatch.setattr(run_paper, "build_market_data_exchange", lambda exchange_id, fallback=None: fake)
    monkeypatch.setattr(run_paper.webbrowser, "open", lambda url: None)
    sleeps: list[float] = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if seconds == 60:  # premiere pause de la boucle principale : le bot a demarre
            raise KeyboardInterrupt

    monkeypatch.setattr(run_paper.time, "sleep", fake_sleep)

    run_paper.main(str(config_path))

    assert fake.load_markets_calls == 3
    assert sleeps == [5, 10, 60]
    with sqlite3.connect(tmp_path / "data" / "STARTUP_502_TEST.db") as conn:
        events = conn.execute("SELECT level, message FROM events ORDER BY id").fetchall()
    retries = [message for level, message in events if level == "warning" and "Demarrage" in message]
    assert len(retries) == 2
    assert any("Demarrage mode paper" in message for _, message in events)
