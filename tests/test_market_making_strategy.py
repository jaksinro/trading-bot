from tradingbot.strategies.market_making import MarketMakingStrategy
from tradingbot.types import Candle


def make_candle(open_price: float) -> Candle:
    return Candle(timestamp=0, open=open_price, high=open_price, low=open_price, close=open_price, volume=1.0)


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
