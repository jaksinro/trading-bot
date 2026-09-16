from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.shared_pool import SharedPool
from tradingbot.strategies.sma_cross import SmaCrossStrategy
from tradingbot.types import Candle


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def make_engine(tmp_path, pool_cash, capital_cap, max_position_size_pct=0.5):
    strategy = SmaCrossStrategy(short_window=2, long_window=4)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=max_position_size_pct, fee_pct=0.0))
    portfolio = Portfolio(starting_capital=capital_cap)
    executor = BacktestExecutor(portfolio)
    pool = SharedPool(tmp_path / "shared_pool.db")
    pool.seed_if_empty(pool_cash)
    engine = Engine(
        strategy, risk_manager, executor, portfolio,
        shared_pool=pool, instance_name="bot_a", capital_cap=capital_cap,
    )
    return engine, portfolio, pool


def test_buy_reserves_and_settles_against_shared_pool(tmp_path):
    engine, portfolio, pool = make_engine(tmp_path, pool_cash=1000.0, capital_cap=500.0)
    closes = [100, 100, 100, 100, 105]  # sma_cross(2,4) declenche un achat sur la 5e bougie
    for i, close in enumerate(closes):
        engine.process_candle(make_candle(i, close))

    assert len(portfolio.positions) == 1
    spent = portfolio.positions[0].quantity * portfolio.positions[0].avg_entry_price
    assert pool.available_cash() == 1000.0 - spent


def test_buy_skipped_when_pool_has_insufficient_funds(tmp_path):
    # max_position_size_pct=1.0 : la reference de capital sera bornee au cash
    # du panier (1.0), donc la valeur de position visee = 1.0 x le panier -
    # la marge de securite de 1% (RESERVATION_SLIPPAGE_BUFFER) fait alors
    # deborder la reservation du cash reellement disponible.
    engine, portfolio, pool = make_engine(tmp_path, pool_cash=1.0, capital_cap=500.0, max_position_size_pct=1.0)
    closes = [100, 100, 100, 100, 105]
    for i, close in enumerate(closes):
        engine.process_candle(make_candle(i, close))

    assert portfolio.positions == []  # achat ignore, pool insuffisant
    assert pool.available_cash() == 1.0  # panier intact, rien reserve/perdu


def test_sell_credits_shared_pool(tmp_path):
    engine, portfolio, pool = make_engine(tmp_path, pool_cash=1000.0, capital_cap=500.0)
    closes = [100, 100, 100, 100, 105, 110, 115, 108, 102, 95, 90]  # achat puis signal de vente
    for i, close in enumerate(closes):
        engine.process_candle(make_candle(i, close))

    assert portfolio.positions == []  # position revendue
    # Le panier a recupere l'argent depense a l'achat + le produit net de la vente.
    assert pool.available_cash() > 0

    row = pool.conn.execute("SELECT op FROM ledger WHERE instance_name = 'bot_a' AND op = 'credit'").fetchall()
    assert len(row) == 1


def test_effective_cap_bounds_buy_size_by_pool_available_cash(tmp_path):
    # Plafond de base tres large (10000) mais panier commun tres restreint (50) :
    # la taille d'achat doit etre bornee par le panier, pas par le plafond seul.
    # max_position_size_pct < 1.0 pour laisser de la marge a la reservation
    # (avec marge de slippage de 1%) sans depasser le cash reellement disponible.
    engine, portfolio, pool = make_engine(tmp_path, pool_cash=50.0, capital_cap=10_000.0, max_position_size_pct=0.9)
    closes = [100, 100, 100, 100, 105]
    for i, close in enumerate(closes):
        engine.process_candle(make_candle(i, close))

    assert len(portfolio.positions) == 1
    spent = portfolio.positions[0].quantity * portfolio.positions[0].avg_entry_price
    assert spent <= 50.0
