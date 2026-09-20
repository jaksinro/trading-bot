from tradingbot.strategies.mean_dip import MeanDipStrategy
from tradingbot.types import Candle, Side


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_no_signal_before_window_is_filled():
    strategy = MeanDipStrategy(window=5, num_std=2.0)
    for i in range(4):
        assert strategy.on_candle(make_candle(i, 100.0)) is None


def test_buy_signal_when_price_drops_below_lower_band():
    strategy = MeanDipStrategy(window=5, num_std=1.0)
    closes = [100, 101, 99, 100, 101, 80]  # chute brutale sous la bande basse
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    assert len(buy_signals) == 1
    assert buy_signals[0].reason == "mean_dip_oversold"


def test_no_signal_when_price_stays_within_bands():
    strategy = MeanDipStrategy(window=5, num_std=2.0)
    closes = [100, 101, 99, 100, 101, 100, 99, 100]
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    assert all(s is None for s in signals)


def test_never_emits_a_sell_signal():
    """Difference essentielle avec MeanReversionStrategy : cette strategie
    ne gere jamais elle-meme la sortie (verrou/retour a la moyenne) - seul
    le RiskManager (stop-loss/trailing) doit fermer une position. Meme un
    prix qui remonte tres fort au-dessus de la moyenne ne doit jamais
    produire de signal SELL."""
    strategy = MeanDipStrategy(window=5, num_std=1.0)
    closes = [100, 100, 100, 100, 100, 80, 90, 100, 110, 150, 200]
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    assert all(s is None or s.side == Side.BUY for s in signals)


def test_repeats_buy_signal_while_price_stays_under_the_band():
    """Contrairement a MeanReversionStrategy (etat interne `_in_position` qui
    bloque tout nouvel achat), cette strategie n'a AUCUN etat interne -
    l'anti-doublon est delegue entierement a `RiskManager.max_concurrent_positions`
    (voir dip_bounce.py pour la meme decision). Un signal BUY repete a chaque
    bougie sous la bande n'est donc pas un bug : c'est volontaire, et surtout
    ca evite le piege ou une sortie EXTERNE (stop-loss/trailing) fermerait la
    position sans que la strategie ne le sache jamais si elle suivait un flag."""
    strategy = MeanDipStrategy(window=5, num_std=1.0)
    closes = [100, 101, 99, 100, 101, 80, 70, 60]  # reste sous la bande basse plusieurs bougies
    signals = [strategy.on_candle(make_candle(i, c)) for i, c in enumerate(closes)]
    buy_signals = [s for s in signals if s is not None and s.side == Side.BUY]
    assert len(buy_signals) == 3  # une bougie sous la bande = un signal, a chaque fois


def test_invalid_window_raises():
    try:
        MeanDipStrategy(window=1, num_std=2.0)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


def test_invalid_num_std_raises():
    try:
        MeanDipStrategy(window=10, num_std=0)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass
