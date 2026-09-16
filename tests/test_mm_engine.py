from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.mm_engine import MarketMakingEngine
from tradingbot.portfolio import Portfolio
from tradingbot.shared_pool import SharedPool
from tradingbot.strategies.market_making import MarketMakingStrategy
from tradingbot.types import Candle


def make_candle(timestamp: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(timestamp=timestamp, open=open_, high=high, low=low, close=close, volume=1.0)


def make_engine(starting_capital=1000.0, spread_pct=0.02, order_size_quote=100.0, max_inventory_quote=500.0):
    strategy = MarketMakingStrategy(
        spread_pct=spread_pct, order_size_quote=order_size_quote, max_inventory_quote=max_inventory_quote, skew_factor=0.0
    )
    portfolio = Portfolio(starting_capital=starting_capital, fee_pct=0.0)
    executor = BacktestExecutor(portfolio)
    engine = MarketMakingEngine(strategy, executor, portfolio)
    return engine, portfolio


def test_no_fill_when_price_stays_within_bid_ask():
    engine, portfolio = make_engine()
    # mid=100, spread 2% -> bid=99, ask=101 ; bougie qui ne touche ni l'un ni l'autre
    engine.process_candle(make_candle(0, open_=100.0, high=100.5, low=99.5, close=100.0))
    assert portfolio.positions == []


def test_bid_fill_only_when_low_touches_bid():
    engine, portfolio = make_engine()
    # bid=99 ; low descend jusqu'a 98.5 -> fill bid, high ne touche pas l'ask (101)
    engine.process_candle(make_candle(0, open_=100.0, high=100.0, low=98.5, close=99.0))
    assert len(portfolio.positions) == 1
    assert portfolio.positions[0].avg_entry_price == 99.0


def test_ask_fill_only_when_high_touches_ask_and_inventory_available():
    engine, portfolio = make_engine()
    # D'abord un fill bid pour obtenir de l'inventaire.
    engine.process_candle(make_candle(0, open_=100.0, high=100.0, low=98.5, close=99.0))
    assert len(portfolio.positions) == 1

    # Puis une bougie qui touche l'ask (101) sans redescendre sous le bid.
    engine.process_candle(make_candle(1, open_=100.0, high=101.5, low=100.0, close=101.0))
    assert portfolio.positions == []  # inventaire revendu (FIFO, seul lot ferme)


def test_both_sides_fill_in_the_same_candle():
    engine, portfolio = make_engine()
    engine.process_candle(make_candle(0, open_=100.0, high=100.0, low=98.5, close=99.0))
    assert len(portfolio.positions) == 1

    # bougie qui touche a la fois le bid (99) et l'ask (101) dans son range.
    engine.process_candle(make_candle(1, open_=100.0, high=101.5, low=98.0, close=100.0))
    # Achat (nouveau lot) ET vente (ferme le lot le plus ancien, FIFO) : il
    # reste donc exactement 1 lot ouvert (celui achete ce cycle).
    assert len(portfolio.positions) == 1


def test_no_ask_quote_at_zero_inventory_even_if_high_would_have_crossed():
    engine, portfolio = make_engine()
    # Aucune position ouverte : la strategie ne cote pas d'ask du tout.
    engine.process_candle(make_candle(0, open_=100.0, high=200.0, low=100.0, close=100.0))
    assert portfolio.positions == []


def test_ask_fill_across_multiple_lots_does_not_create_phantom_profit():
    """Regression CT-22 (STB) : plusieurs fills bid ouvrent plusieurs petits
    lots distincts (Portfolio.open_new_lot). Un fill ask qui vend une
    quantite calculee sur l'INVENTAIRE TOTAL (superieure au lot le plus
    ancien pris isolement) ne doit jamais generer de profit superieur a ce
    que le spread reel autorise - avant le fix, `_fill_ask` vendait tout en
    un seul ordre FIFO sans verifier que la quantite tenait dans le lot le
    plus ancien, imputant le prix d'entree de ce lot a une quantite qu'il
    n'avait jamais detenue (profit fictif)."""
    engine, portfolio = make_engine(spread_pct=0.02, order_size_quote=100.0, max_inventory_quote=1000.0)

    # 3 fills bid successifs -> 3 lots distincts, ~3 unites d'inventaire (a ~99 chacun).
    for i in range(3):
        engine.process_candle(make_candle(i, open_=100.0, high=100.0, low=98.5, close=99.0))
    assert len(portfolio.positions) == 3
    inventory_before = portfolio.total_position_quantity
    cash_before = portfolio.cash

    # Bougie qui touche l'ask : la strategie demande a vendre min(order_size_base, inventory)
    # calcule sur l'inventaire TOTAL (~3 unites), largement plus que ce que
    # detient le lot le plus ancien (~1 unite) - le fix doit vendre lot par
    # lot sans jamais depasser la quantite reellement detenue par chacun.
    engine.process_candle(make_candle(3, open_=100.0, high=101.5, low=100.0, close=101.0))

    proceeds = portfolio.cash - cash_before
    sold_qty = inventory_before - portfolio.total_position_quantity
    assert sold_qty > 0
    # Le produit de la vente ne peut pas depasser la quantite vendue x le prix
    # de vente (101, le meilleur cas possible) - une marge large suffit a
    # detecter un profit fictif type "vendre 3x plus cher que possible".
    assert proceeds <= sold_qty * 101.0 + 1e-6


def test_shared_pool_reserve_and_settle_on_bid_fill(tmp_path):
    strategy = MarketMakingStrategy(spread_pct=0.02, order_size_quote=100.0, max_inventory_quote=500.0, skew_factor=0.0)
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.0)
    executor = BacktestExecutor(portfolio)
    pool = SharedPool(tmp_path / "shared_pool.db")
    pool.seed_if_empty(1000.0)
    engine = MarketMakingEngine(strategy, executor, portfolio, shared_pool=pool, instance_name="mm_bot", capital_cap=500.0)

    engine.process_candle(make_candle(0, open_=100.0, high=100.0, low=98.5, close=99.0))

    assert len(portfolio.positions) == 1
    spent = portfolio.positions[0].quantity * portfolio.positions[0].avg_entry_price
    assert pool.available_cash() == 1000.0 - spent


def test_shared_pool_never_overdrawn_when_funds_insufficient(tmp_path):
    strategy = MarketMakingStrategy(spread_pct=0.02, order_size_quote=100.0, max_inventory_quote=500.0, skew_factor=0.0)
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.0)
    executor = BacktestExecutor(portfolio)
    pool = SharedPool(tmp_path / "shared_pool.db")
    pool.seed_if_empty(1.0)  # panier presque vide, largement insuffisant pour un ordre de 100
    engine = MarketMakingEngine(strategy, executor, portfolio, shared_pool=pool, instance_name="mm_bot", capital_cap=500.0)

    engine.process_candle(make_candle(0, open_=100.0, high=100.0, low=98.5, close=99.0))

    assert portfolio.positions == []  # fill bid ignore, pool insuffisant
    assert pool.available_cash() == 1.0  # panier intact


def test_shared_pool_credited_on_ask_fill(tmp_path):
    strategy = MarketMakingStrategy(spread_pct=0.02, order_size_quote=100.0, max_inventory_quote=500.0, skew_factor=0.0)
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.0)
    executor = BacktestExecutor(portfolio)
    pool = SharedPool(tmp_path / "shared_pool.db")
    pool.seed_if_empty(1000.0)
    engine = MarketMakingEngine(strategy, executor, portfolio, shared_pool=pool, instance_name="mm_bot", capital_cap=500.0)

    engine.process_candle(make_candle(0, open_=100.0, high=100.0, low=98.5, close=99.0))
    cash_after_buy = pool.available_cash()
    engine.process_candle(make_candle(1, open_=100.0, high=101.5, low=100.0, close=101.0))

    assert portfolio.positions == []
    assert pool.available_cash() > cash_after_buy  # produit de la vente reverse au panier
