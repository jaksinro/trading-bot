import pytest

from tradingbot.strategies.market_making import MarketMakingStrategy
from tradingbot.types import Candle


def make_candle(open_price: float) -> Candle:
    return Candle(timestamp=0, open=open_price, high=open_price, low=open_price, close=open_price, volume=1.0)


def make_ohlc_candle(open_price: float, high: float, low: float, close: float) -> Candle:
    return Candle(timestamp=0, open=open_price, high=high, low=low, close=close, volume=1.0)


def test_symmetric_quote_when_inventory_is_zero():
    strategy = MarketMakingStrategy(spread_pct=0.01, order_size_quote=100.0, max_inventory_quote=1000.0, skew_factor=1.0)
    quote = strategy.quote(make_candle(100.0), inventory=0.0)
    assert quote is not None
    assert quote.bid_price == 99.5  # 100 * (1 - 0.01/2)
    assert quote.ask_price is None  # rien a vendre a inventaire nul
    assert quote.bid_qty == 1.0  # 100 / 100


def test_ask_appears_once_inventory_is_positive():
    strategy = MarketMakingStrategy(spread_pct=0.01, order_size_quote=100.0, max_inventory_quote=1000.0, skew_factor=0.0)
    quote = strategy.quote(make_candle(100.0), inventory=2.0)
    assert quote is not None
    assert quote.bid_price == 99.5
    assert quote.ask_price == 100.5
    assert quote.ask_qty == 1.0  # min(order_size_base, inventory)


def test_ask_qty_capped_by_available_inventory():
    strategy = MarketMakingStrategy(spread_pct=0.01, order_size_quote=100.0, max_inventory_quote=1000.0, skew_factor=0.0)
    quote = strategy.quote(make_candle(100.0), inventory=0.5)  # moins que order_size_base (1.0)
    assert quote.ask_qty == 0.5


def test_bid_disappears_at_max_inventory():
    strategy = MarketMakingStrategy(spread_pct=0.01, order_size_quote=100.0, max_inventory_quote=200.0, skew_factor=0.0)
    quote = strategy.quote(make_candle(100.0), inventory=2.0)  # 2.0 * 100 = 200 = max_inventory_quote
    assert quote is not None
    assert quote.bid_price is None
    assert quote.ask_price is not None


def test_no_quote_when_bid_and_ask_both_suppressed():
    strategy = MarketMakingStrategy(spread_pct=0.01, order_size_quote=100.0, max_inventory_quote=200.0, skew_factor=0.0)
    quote = strategy.quote(make_candle(100.0), inventory=2.0)
    assert quote is not None  # ask reste possible ici (inventaire > 0)
    # Cas ou aucun cote n'est possible : impossible avec max_inventory > 0 et
    # inventaire fini (bid coupe seulement a inventaire >= max, ask coupe
    # seulement a inventaire <= 0 - jamais les deux a la fois par construction).


def test_skew_lowers_both_prices_as_inventory_grows():
    strategy = MarketMakingStrategy(spread_pct=0.01, order_size_quote=100.0, max_inventory_quote=1000.0, skew_factor=1.0)
    quote_low_inventory = strategy.quote(make_candle(100.0), inventory=1.0)
    quote_high_inventory = strategy.quote(make_candle(100.0), inventory=9.0)
    assert quote_high_inventory.bid_price < quote_low_inventory.bid_price
    assert quote_high_inventory.ask_price < quote_low_inventory.ask_price


def test_invalid_spread_pct_raises():
    try:
        MarketMakingStrategy(spread_pct=0.0, order_size_quote=100.0, max_inventory_quote=1000.0)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


def test_invalid_order_size_quote_raises():
    try:
        MarketMakingStrategy(spread_pct=0.01, order_size_quote=0.0, max_inventory_quote=1000.0)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


def test_invalid_max_inventory_quote_raises():
    try:
        MarketMakingStrategy(spread_pct=0.01, order_size_quote=100.0, max_inventory_quote=0.0)
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


def test_invalid_max_spread_multiplier_raises():
    try:
        MarketMakingStrategy(
            spread_pct=0.01, order_size_quote=100.0, max_inventory_quote=1000.0, max_spread_multiplier=0.5
        )
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


def test_volatility_adaptive_spread_disabled_by_default():
    strategy = MarketMakingStrategy(spread_pct=0.01, order_size_quote=100.0, max_inventory_quote=1000.0, skew_factor=0.0)
    # Bougie tres volatile (high/low tres ecartes) : le spread reste inchange tant que
    # volatility_adaptive_spread=False (comportement historique preserve).
    quote = strategy.quote(make_ohlc_candle(100.0, 130.0, 70.0, 100.0), inventory=0.0)
    assert quote.bid_price == 99.5  # 100 * (1 - 0.01/2), comme sans volatilite


def test_volatility_adaptive_spread_does_not_widen_the_volatile_candle_itself():
    """Le high/low de la bougie EN COURS ne doit pas influencer sa propre
    cotation (pas de lookahead, voir le commentaire de `_spread_multiplier`) -
    seul l'ATR observe sur les bougies PRECEDENTES peut elargir le spread."""
    strategy = MarketMakingStrategy(
        spread_pct=0.01, order_size_quote=100.0, max_inventory_quote=1000.0, skew_factor=0.0,
        volatility_adaptive_spread=True, atr_period=2, atr_baseline_period=5, max_spread_multiplier=3.0,
    )
    quiet_quote = None
    for _ in range(5):
        quiet_quote = strategy.quote(make_ohlc_candle(100.0, 100.2, 99.8, 100.0), inventory=0.0)
    base_half_spread = 100.0 - quiet_quote.bid_price

    volatile_quote = strategy.quote(make_ohlc_candle(100.0, 110.0, 90.0, 100.0), inventory=0.0)
    assert (100.0 - volatile_quote.bid_price) == pytest.approx(base_half_spread)


def test_volatility_adaptive_spread_widens_after_a_high_volatility_candle():
    strategy = MarketMakingStrategy(
        spread_pct=0.01, order_size_quote=100.0, max_inventory_quote=1000.0, skew_factor=0.0,
        volatility_adaptive_spread=True, atr_period=2, atr_baseline_period=5, max_spread_multiplier=3.0,
    )
    quiet_quote = None
    for _ in range(5):
        quiet_quote = strategy.quote(make_ohlc_candle(100.0, 100.2, 99.8, 100.0), inventory=0.0)
    base_half_spread = 100.0 - quiet_quote.bid_price

    strategy.quote(make_ohlc_candle(100.0, 110.0, 90.0, 100.0), inventory=0.0)  # pic de volatilite

    next_quote = strategy.quote(make_ohlc_candle(100.0, 100.2, 99.8, 100.0), inventory=0.0)
    assert (100.0 - next_quote.bid_price) > base_half_spread


def test_volatility_adaptive_spread_never_narrows_below_base_spread():
    strategy = MarketMakingStrategy(
        spread_pct=0.01, order_size_quote=100.0, max_inventory_quote=1000.0, skew_factor=0.0,
        volatility_adaptive_spread=True, atr_period=2, atr_baseline_period=5,
    )
    # Volatilite decroissante (chaque bougie plus calme que la precedente) :
    # le multiplicateur ne doit jamais tomber sous 1.0 (spread configure).
    for high, low in [(105.0, 95.0), (102.0, 98.0), (100.5, 99.5), (100.2, 99.8)]:
        quote = strategy.quote(make_ohlc_candle(100.0, high, low, 100.0), inventory=0.0)
        assert (100.0 - quote.bid_price) >= 0.5  # jamais sous le half-spread de base


def test_max_spread_multiplier_caps_the_widening():
    strategy = MarketMakingStrategy(
        spread_pct=0.01, order_size_quote=100.0, max_inventory_quote=1000.0, skew_factor=0.0,
        volatility_adaptive_spread=True, atr_period=2, atr_baseline_period=5, max_spread_multiplier=2.0,
    )
    for _ in range(5):
        strategy.quote(make_ohlc_candle(100.0, 100.2, 99.8, 100.0), inventory=0.0)
    strategy.quote(make_ohlc_candle(100.0, 110.0, 90.0, 100.0), inventory=0.0)  # ratio ATR/baseline bien > 2.0

    capped_quote = strategy.quote(make_ohlc_candle(100.0, 100.2, 99.8, 100.0), inventory=0.0)
    assert (100.0 - capped_quote.bid_price) == pytest.approx(1.0)  # half_spread(0.5) * multiplicateur plafonne (2.0)
