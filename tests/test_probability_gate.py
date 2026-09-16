from tradingbot.analysis import probability_gate as probability_gate_module
from tradingbot.analysis.probability_gate import ProbabilityGate
from tradingbot.types import Candle


def make_candles(closes):
    return [Candle(timestamp=i, open=c, high=c, low=c, close=c, volume=1.0) for i, c in enumerate(closes)]


def test_allows_buy_when_probability_meets_threshold(monkeypatch):
    rising_closes = [100.0 * (1.001 ** i) for i in range(200)]  # tendance haussiere constante
    monkeypatch.setattr(
        probability_gate_module, "fetch_historical_candles", lambda **kwargs: make_candles(rising_closes)
    )
    gate = ProbabilityGate("binance", "BTC/USDT", min_probability=0.55, n_simulations=5000)

    allowed, probability = gate.allows_buy()

    assert allowed is True
    assert probability > 0.55


def test_blocks_buy_when_probability_below_threshold(monkeypatch):
    falling_closes = [100.0 * (0.999 ** i) for i in range(200)]  # tendance baissiere constante
    monkeypatch.setattr(
        probability_gate_module, "fetch_historical_candles", lambda **kwargs: make_candles(falling_closes)
    )
    gate = ProbabilityGate("binance", "BTC/USDT", min_probability=0.55, n_simulations=5000)

    allowed, probability = gate.allows_buy()

    assert allowed is False
    assert probability < 0.55


def test_caches_probability_within_ttl(monkeypatch):
    call_count = {"n": 0}

    def fake_fetch(**kwargs):
        call_count["n"] += 1
        return make_candles([100.0 + i for i in range(200)])

    monkeypatch.setattr(probability_gate_module, "fetch_historical_candles", fake_fetch)
    gate = ProbabilityGate("binance", "BTC/USDT", n_simulations=1000, cache_ttl_seconds=3600)

    gate.current_probability()
    gate.current_probability()
    gate.current_probability()

    assert call_count["n"] == 1


def test_recomputes_after_cache_expires(monkeypatch):
    call_count = {"n": 0}

    def fake_fetch(**kwargs):
        call_count["n"] += 1
        return make_candles([100.0 + i for i in range(200)])

    monkeypatch.setattr(probability_gate_module, "fetch_historical_candles", fake_fetch)
    gate = ProbabilityGate("binance", "BTC/USDT", n_simulations=1000, cache_ttl_seconds=0)

    gate.current_probability()
    gate.current_probability()

    assert call_count["n"] == 2


def test_allows_buy_on_fetch_failure_fail_open(monkeypatch):
    def failing_fetch(**kwargs):
        raise ConnectionError("API injoignable")

    monkeypatch.setattr(probability_gate_module, "fetch_historical_candles", failing_fetch)
    gate = ProbabilityGate("binance", "BTC/USDT", min_probability=0.9)

    allowed, probability = gate.allows_buy()

    assert allowed is True
    assert probability == -1.0
