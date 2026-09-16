from tradingbot.portfolio import Portfolio
from tradingbot.reporting.stats import build_orders_table
from tradingbot.risk.risk_manager import RiskConfig
from tradingbot.types import OrderResult, Side


def test_open_position_shows_target_prices_no_sell_price():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=10, status="filled"))
    risk_config = RiskConfig(stop_loss_pct=0.02, take_profit_pct=0.05)

    rows = build_orders_table(portfolio, risk_config)

    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "ouvert"
    assert row["buy_price"] == 100.0
    assert row["sell_price"] is None
    assert row["target_take_profit"] == 105.0
    assert row["target_stop_loss"] == 98.0


def test_closed_trade_shows_real_and_target_sell_price():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=10, status="filled"))
    portfolio.apply_fill(
        OrderResult(Side.SELL, quantity=1.0, price=105.0, timestamp=20, status="filled", reason="take_profit")
    )
    risk_config = RiskConfig(stop_loss_pct=0.02, take_profit_pct=0.05)

    rows = build_orders_table(portfolio, risk_config)

    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "vendu"
    assert row["buy_price"] == 100.0
    assert row["sell_price"] == 105.0
    assert row["target_take_profit"] == 105.0
    assert row["reason"] == "take_profit"
    assert row["pnl"] == 5.0


def test_no_take_profit_configured_gives_none_target():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=10, status="filled"))
    risk_config = RiskConfig(stop_loss_pct=0.02, take_profit_pct=None)

    rows = build_orders_table(portfolio, risk_config)

    assert rows[0]["target_take_profit"] is None


def test_no_stop_loss_configured_gives_none_target_instead_of_crashing():
    """Bug reel rencontre en paper trading (2026-09-15) : un bot dip_bounce
    (stop_loss_pct=None, decision assumee) plantait des sa premiere position
    ouverte - `_target_prices` calculait `entry_price * (1 - None)` sans
    jamais verifier que `stop_loss_pct` etait bien defini."""
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=10, status="filled"))
    risk_config = RiskConfig(stop_loss_pct=None, take_profit_pct=None)

    rows = build_orders_table(portfolio, risk_config)

    assert rows[0]["target_stop_loss"] is None
    assert rows[0]["target_take_profit"] is None


def test_no_stop_loss_configured_on_a_closed_trade_gives_none_target():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=10, status="filled"))
    portfolio.apply_fill(
        OrderResult(Side.SELL, quantity=1.0, price=102.0, timestamp=20, status="filled", reason="profit_lock")
    )
    risk_config = RiskConfig(stop_loss_pct=None, take_profit_pct=None)

    rows = build_orders_table(portfolio, risk_config)

    assert rows[0]["target_stop_loss"] is None


def test_strategy_driven_sell_gets_signal_reason_fallback():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=10, status="filled"))
    portfolio.apply_fill(OrderResult(Side.SELL, quantity=1.0, price=102.0, timestamp=20, status="filled", reason=""))
    risk_config = RiskConfig(stop_loss_pct=0.02, take_profit_pct=0.05)

    rows = build_orders_table(portfolio, risk_config)

    assert rows[0]["reason"] == "signal"


def test_rows_sorted_most_recent_first():
    portfolio = Portfolio(starting_capital=1000.0)
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=100.0, timestamp=10, status="filled"))
    portfolio.apply_fill(OrderResult(Side.SELL, quantity=1.0, price=101.0, timestamp=20, status="filled"))
    portfolio.apply_fill(OrderResult(Side.BUY, quantity=1.0, price=102.0, timestamp=30, status="filled"))
    portfolio.apply_fill(OrderResult(Side.SELL, quantity=1.0, price=103.0, timestamp=40, status="filled"))
    risk_config = RiskConfig(stop_loss_pct=0.02, take_profit_pct=0.05)

    rows = build_orders_table(portfolio, risk_config)

    assert [r["entry_timestamp"] for r in rows] == [30, 10]
