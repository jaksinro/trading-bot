from tradingbot.strategies.dip_bounce import DipBounceStrategy
from tradingbot.types import Candle, Side


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_no_signal_before_window_is_filled():
    strategy = DipBounceStrategy(trend_ma_period=5, dip_threshold_pct=0.01)
    for i in range(4):
        assert strategy.on_candle(make_candle(i, 100.0)) is None


def test_buy_when_near_the_dip():
    strategy = DipBounceStrategy(trend_ma_period=5, dip_threshold_pct=0.01)
    closes = [100, 100, 100, 100, 100.5]
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    assert len(buy_signals) == 1
    assert buy_signals[0].reason == "dip_bounce_entry"


def test_buy_even_in_a_falling_market_when_price_is_the_new_low():
    """Aucune condition de regime/tendance n'est requise (retiree le
    2026-09-14) - le prix qui vient de faire un nouveau plus bas de la
    fenetre compte toujours comme "pres du creux", meme en pleine baisse."""
    strategy = DipBounceStrategy(trend_ma_period=5, dip_threshold_pct=0.5)  # seuil tres large : "pres du creux" toujours vrai
    closes = [100, 100, 100, 90, 80]  # baisse continue, aucun rebond
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    assert len(buy_signals) >= 1


def test_no_buy_when_far_from_the_dip():
    strategy = DipBounceStrategy(trend_ma_period=5, dip_threshold_pct=0.001)  # tolerance tres etroite
    closes = [100, 100, 100, 102, 110]  # prix loin du min (100) de la fenetre
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    assert all(s is None for s in signals)


def test_never_emits_a_sell_signal():
    """La seule sortie possible est le verrou de gain, gere par le
    RiskManager (should_profit_lock) - la strategie elle-meme n'emet jamais
    de Signal(SELL), meme apres un nouveau plus haut de la fenetre glissante
    (comportement retire a la demande de l'utilisateur, voir dip_bounce.py)."""
    strategy = DipBounceStrategy(trend_ma_period=5, dip_threshold_pct=0.01)
    closes = [100, 100, 100, 100, 100.5, 101, 102, 105, 110, 120]
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    assert all(s is None or s.side == Side.BUY for s in signals)


def test_signals_buy_again_on_every_candle_while_conditions_persist():
    """La strategie ne suit plus d'etat interne "en position" (retire avec
    la sortie sur nouveau plus haut) - eviter un double achat pendant qu'une
    position est deja ouverte est desormais entierement la responsabilite du
    RiskManager (max_concurrent_positions), pas de la strategie."""
    strategy = DipBounceStrategy(trend_ma_period=5, dip_threshold_pct=0.02)
    closes = [100, 100, 100, 100, 100.5, 100.3, 100.4, 100.2]
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    assert len(buy_signals) > 1


def test_works_identically_with_a_different_window_size():
    """Agnostique du timeframe : meme logique avec trend_ma_period=60 (ex:
    bougies 1 minute sur une fenetre d'1h) qu'avec 24 (bougies 1h/24h)."""
    strategy = DipBounceStrategy(trend_ma_period=60, dip_threshold_pct=0.01)
    closes = [100.0] * 59 + [100.5]
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    assert len(buy_signals) == 1


def test_invalid_trend_ma_period_raises():
    try:
        DipBounceStrategy(trend_ma_period=1, dip_threshold_pct=0.01)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


def test_invalid_dip_threshold_pct_raises():
    try:
        DipBounceStrategy(trend_ma_period=24, dip_threshold_pct=0.0)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


HOUR_MS = 3_600_000


def make_hourly_candle(hour_index: int, close: float) -> Candle:
    return Candle(timestamp=hour_index * HOUR_MS, open=close, high=close, low=close, close=close, volume=1.0)


def _steadily_rising_closes(n: int, growth: float = 0.01) -> list[float]:
    """Prix qui monte regulierement : le plus bas de la fenetre glissante
    reste TOUJOURS a distance constante (~4% pour growth=0.01/fenetre=5) du
    prix courant - jamais de plateau qui ferait trivialement matcher un
    seuil par accident, contrairement a une serie qui reste plate."""
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(closes[-1] * (1 + growth))
    return closes


def test_force_trade_after_hours_disabled_by_default_never_widens():
    """Sans force_trade_after_hours (None), le comportement est inchange :
    un seuil etroit qui ne matche jamais reste etroit indefiniment."""
    strategy = DipBounceStrategy(trend_ma_period=5, dip_threshold_pct=0.001)
    closes = _steadily_rising_closes(200)
    signals = [strategy.on_candle(make_hourly_candle(i, c)) for i, c in enumerate(closes)]
    assert all(s is None for s in signals)


def test_force_trade_after_hours_eventually_widens_the_threshold():
    """Avec force_trade_after_hours=24, un prix qui reste hors du seuil
    initial finit par declencher un achat une fois le seuil suffisamment
    assoupli (double a chaque 24h supplementaire sans achat)."""
    strategy = DipBounceStrategy(trend_ma_period=5, dip_threshold_pct=0.001, force_trade_after_hours=24)
    closes = _steadily_rising_closes(200)
    signals = [strategy.on_candle(make_hourly_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    assert len(buy_signals) >= 1


def test_force_trade_after_hours_resets_clock_after_a_buy():
    """Le compteur d'heures sans achat repart de zero a chaque signal
    d'achat emis (matche normalement ou via l'assouplissement)."""
    strategy = DipBounceStrategy(trend_ma_period=5, dip_threshold_pct=0.01, force_trade_after_hours=24)
    closes = [100, 100, 100, 100, 100.5]  # achat normal des la 5e bougie (pres du creux)
    for i, c in enumerate(closes):
        strategy.on_candle(make_hourly_candle(i, c))
    assert strategy._last_buy_ts == 4 * HOUR_MS


def test_invalid_force_trade_after_hours_raises():
    try:
        DipBounceStrategy(trend_ma_period=24, dip_threshold_pct=0.01, force_trade_after_hours=0)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass
