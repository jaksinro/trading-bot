"""Tests de la strategie de regime de tendance (EF-68)."""
import pytest

from tradingbot.strategies.trend_regime import TrendRegimeStrategy
from tradingbot.types import Candle, Side


def make_candle(close: float, index: int = 0) -> Candle:
    return Candle(
        timestamp=index * 3_600_000, open=close, high=close, low=close, close=close, volume=1.0,
    )


def feed(strategy, closes):
    return [strategy.on_candle(make_candle(c, i)) for i, c in enumerate(closes)]


def test_rejects_invalid_parameters():
    with pytest.raises(ValueError, match="ema_period"):
        TrendRegimeStrategy(ema_period=1)
    with pytest.raises(ValueError, match="hysteresis"):
        TrendRegimeStrategy(entry_buffer_pct=-0.01)


def test_no_signal_during_warmup():
    """Une EMA amorcee sur la premiere cloture n'est pas significative tout
    de suite : decider dessus reviendrait a comparer le prix a lui-meme."""
    strategy = TrendRegimeStrategy(ema_period=10)
    assert feed(strategy, [100.0] * 9) == [None] * 9


def test_buys_in_an_uptrend():
    strategy = TrendRegimeStrategy(ema_period=5, warmup_candles=5)
    signals = feed(strategy, [100.0, 101.0, 102.0, 103.0, 104.0, 110.0])
    assert signals[-1] is not None
    assert signals[-1].side is Side.BUY
    assert signals[-1].reason == "trend_regime_bullish"


def test_sells_when_the_regime_turns_down():
    """Coeur de la strategie, et ce que `TrendFilter` ne fait pas : elle
    SORT quand la tendance casse, au lieu de subir la baisse en portefeuille."""
    strategy = TrendRegimeStrategy(ema_period=5, warmup_candles=5)
    signals = feed(strategy, [100.0, 101.0, 102.0, 103.0, 104.0, 70.0])
    assert signals[-1] is not None
    assert signals[-1].side is Side.SELL
    assert signals[-1].reason == "trend_regime_bearish"


def test_hysteresis_creates_a_neutral_band_where_nothing_happens():
    """Avec des marges, un prix tres proche de l'EMA ne doit declencher NI
    achat NI vente - c'est ce qui evite le va-et-vient couteux autour de la
    ligne."""
    strategy = TrendRegimeStrategy(
        ema_period=5, warmup_candles=5, entry_buffer_pct=0.05, exit_buffer_pct=0.05,
    )
    # Prix stable : l'EMA converge vers 100, et 100 est dans la bande neutre.
    signals = feed(strategy, [100.0] * 12)
    assert all(s is None for s in signals[5:]), "la bande neutre doit tout bloquer"


def test_without_hysteresis_the_line_itself_is_bullish():
    """Sans marge, etre exactement sur l'EMA compte comme haussier (>=) -
    comportement documente, et le complement du test precedent."""
    strategy = TrendRegimeStrategy(ema_period=5, warmup_candles=5)
    signals = feed(strategy, [100.0] * 8)
    assert signals[-1] is not None
    assert signals[-1].side is Side.BUY


def test_entry_requires_clearing_the_upper_margin():
    strategy = TrendRegimeStrategy(
        ema_period=5, warmup_candles=5, entry_buffer_pct=0.10, exit_buffer_pct=0.10,
    )
    # +5% au-dessus d'une EMA ~100 : insuffisant pour la marge de 10%.
    assert feed(strategy, [100.0] * 6 + [105.0])[-1] is None
    # +20% : franchi.
    assert feed(strategy, [120.0])[-1].side is Side.BUY


def test_no_internal_position_flag_signals_may_repeat():
    """Comme les autres strategies du projet, l'anti-doublon est delegue au
    RiskManager : la strategie doit pouvoir resignaler a chaque bougie."""
    strategy = TrendRegimeStrategy(ema_period=5, warmup_candles=5)
    signals = feed(strategy, [100.0, 101.0, 102.0, 103.0, 104.0, 110.0, 112.0, 115.0])
    buys = [s for s in signals if s is not None and s.side is Side.BUY]
    assert len(buys) >= 3


def test_ema_is_exposed_for_inspection():
    strategy = TrendRegimeStrategy(ema_period=5)
    assert strategy.ema is None
    feed(strategy, [100.0, 200.0])
    assert strategy.ema is not None
    assert 100.0 < strategy.ema < 200.0


# --- Integration : creation d'un bot depuis le formulaire du dashboard ---


def _form_payload(**overrides) -> dict:
    payload = {
        "name": "eth_tr", "account_type": "crypto", "symbol": "ETH/USDT", "timeframe": "1h",
        "strategy_type": "trend_regime", "ema_period": "500", "entry_buffer_pct": 0.03,
        "exit_buffer_pct": 0.0, "capital_allocated": "200", "max_position_size_pct": 1.0,
        "max_daily_loss_pct": 0.05, "stop_loss_pct": "", "max_concurrent_positions": "1",
    }
    payload.update(overrides)
    return payload


def test_is_registered_in_the_strategy_registry():
    """Sans cette entree, une config `type: trend_regime` planterait au
    demarrage du bot."""
    from tradingbot.run_backtest import STRATEGY_REGISTRY

    assert STRATEGY_REGISTRY["trend_regime"] is TrendRegimeStrategy


def test_config_file_builds_the_strategy():
    import yaml

    from tradingbot.run_backtest import build_strategy

    config = yaml.safe_load(open("config/ETH_TREND_REGIME.yml", encoding="utf-8"))
    strategy = build_strategy(config)

    assert isinstance(strategy, TrendRegimeStrategy)
    assert strategy.ema_period == 500
    # Le rechauffement doit couvrir la fenetre, sinon le bot reste muet
    # plusieurs semaines apres son demarrage.
    assert config["warmup_candles"] >= strategy.ema_period


def test_form_payload_produces_a_valid_config():
    from tradingbot.control_server import build_config

    config = build_config(_form_payload())

    assert config["strategy"] == {
        "type": "trend_regime", "ema_period": 500,
        "entry_buffer_pct": 0.03, "exit_buffer_pct": 0.0,
    }
    assert config["warmup_candles"] >= 500
    # Stop-loss laisse vide : doit RESTER desactive, pas basculer sur 2 % -
    # la sortie de cette strategie est le retournement de tendance.
    assert config["risk"]["stop_loss_pct"] is None


def test_form_rejects_a_window_that_is_too_short():
    from tradingbot.control_server import build_config

    with pytest.raises(ValueError, match="fenetre de tendance"):
        build_config(_form_payload(ema_period="1"))


def test_form_rejects_negative_margins():
    from tradingbot.control_server import build_config

    with pytest.raises(ValueError, match="marges"):
        build_config(_form_payload(entry_buffer_pct=-0.01))


def test_the_backtest_preset_exposes_the_three_parameters():
    from tradingbot.backtest_lab import PRESETS

    preset = PRESETS["trend_regime"]
    assert preset.strategy_type == "trend_regime"
    assert {spec.name for spec in preset.param_specs} == {
        "ema_period", "entry_buffer_pct", "exit_buffer_pct",
    }
    # Stop-loss optionnel, jamais impose par defaut dans le dos de l'utilisateur.
    assert preset.default_stop_loss_pct is None
