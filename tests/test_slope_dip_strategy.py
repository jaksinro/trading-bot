from tradingbot.strategies.slope_dip import SlopeDipStrategy
from tradingbot.types import Candle, Side


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_no_signal_on_first_candle():
    strategy = SlopeDipStrategy(slope_threshold_pct=0.005)
    assert strategy.on_candle(make_candle(0, 100.0)) is None


def test_buy_signal_on_steep_single_candle_drop():
    strategy = SlopeDipStrategy(slope_threshold_pct=0.005)
    strategy.on_candle(make_candle(0, 100.0))
    signal = strategy.on_candle(make_candle(1, 99.0))  # -1%, au-dela du seuil de 0.5%
    assert signal is not None
    assert signal.side == Side.BUY
    assert signal.reason == "slope_dip_sharp_drop"


def test_no_signal_on_mild_move():
    strategy = SlopeDipStrategy(slope_threshold_pct=0.005)
    strategy.on_candle(make_candle(0, 100.0))
    signal = strategy.on_candle(make_candle(1, 99.7))  # -0.3%, sous le seuil
    assert signal is None


def test_no_signal_on_price_rise():
    strategy = SlopeDipStrategy(slope_threshold_pct=0.005)
    strategy.on_candle(make_candle(0, 100.0))
    signal = strategy.on_candle(make_candle(1, 110.0))  # hausse, pas une chute
    assert signal is None


def test_never_emits_a_sell_signal():
    """Meme philosophie de sortie que mean_dip/dip_bounce : aucun signal de
    vente propre a la strategie, seul le RiskManager (stop-loss/trailing)
    ferme une position."""
    strategy = SlopeDipStrategy(slope_threshold_pct=0.005)
    closes = [100, 99, 98, 150, 90, 200, 50]
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    assert all(s is None or s.side == Side.BUY for s in signals)


def test_repeats_buy_signal_on_each_consecutive_steep_drop():
    """Aucun etat 'en position' - l'anti-doublon est delegue entierement a
    RiskManager.max_concurrent_positions (meme decision que dip_bounce/mean_dip)."""
    strategy = SlopeDipStrategy(slope_threshold_pct=0.005)
    closes = [100, 99, 98, 97]  # chute de ~1% a chaque bougie
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    assert len(buy_signals) == 3  # une chute forte par bougie = un signal, a chaque fois


def test_invalid_slope_threshold_raises():
    try:
        SlopeDipStrategy(slope_threshold_pct=0)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


def test_invalid_candles_window_raises():
    try:
        SlopeDipStrategy(candles_window=1)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


def test_wider_candles_window_measures_slope_over_more_candles():
    """2026-09-16, suite a l'observation du graphique reel d'une journee :
    avec candles_window=5, la pente se mesure entre la bougie courante et
    celle 4 bougies plus tot (5 bougies au total), pas juste la precedente."""
    strategy = SlopeDipStrategy(slope_threshold_pct=0.005, candles_window=5)
    # chute lente etalee sur 4 bougies (0.2% par bougie, jamais assez d'un
    # coup pour declencher avec candles_window=2) mais cumulee > 0.5% sur 5 bougies.
    closes = [100, 99.8, 99.6, 99.4, 99.2]
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    assert signals[:4] == [None, None, None, None]  # pas assez de bougies accumulees avant la 5e
    assert signals[4] is not None
    assert signals[4].side == Side.BUY


def test_wider_candles_window_ignores_a_single_candle_spike():
    """Avec candles_window=5, une chute isolee sur UNE SEULE bougie qui
    remonte aussitot ne doit pas forcement declencher un signal si l'ecart
    net sur les 5 bougies reste sous le seuil."""
    strategy = SlopeDipStrategy(slope_threshold_pct=0.02, candles_window=5)
    closes = [100, 99, 100, 100, 100]  # chute isolee de 1% suivie d'un retour immediat
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    assert all(s is None for s in signals)


def test_one_buy_per_slope_disabled_by_default():
    strategy = SlopeDipStrategy(slope_threshold_pct=0.005)
    assert strategy.one_buy_per_slope is False


def test_one_buy_per_slope_suppresses_repeated_signals_on_a_continuous_decline():
    """2026-09-16, constat reel de l'utilisateur ("sa foire pendant les
    longues pentes") : sur une derive continue, la condition de pente reste
    vraie a chaque bougie - sans garde-fou, la strategie empile un achat par
    bougie sur la MEME tendance. Avec one_buy_per_slope=True, un seul signal
    par episode de pente continue."""
    strategy = SlopeDipStrategy(slope_threshold_pct=0.005, one_buy_per_slope=True)
    closes = [100, 99, 98, 97, 96, 95]  # chute continue de ~1% a chaque bougie
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None]
    assert len(buy_signals) == 1  # un seul achat, pas un par bougie qualifiante


def test_one_buy_per_slope_rearms_after_the_slope_condition_breaks():
    """Une fois la pente interrompue (une bougie qui ne declenche pas la
    condition, meme brievement), la strategie se rearme pour le prochain
    episode de chute continue."""
    strategy = SlopeDipStrategy(slope_threshold_pct=0.005, one_buy_per_slope=True)
    closes = [100, 99, 98, 98, 97, 96]  # chute, pause (98->98, pas de signal), puis nouvelle chute
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None]
    assert len(buy_signals) == 2  # un achat par episode de chute continue, 2 episodes ici
