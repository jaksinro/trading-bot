import json
import re

from tradingbot.portfolio import Portfolio
from tradingbot.reporting.dashboard import DASHBOARD_DIR, write_dashboard


def _read_instance_data(name):
    content = (DASHBOARD_DIR / f"{name}.js").read_text(encoding="utf-8")
    match = re.search(r"window\.BOT_INSTANCES\[.*?\]\s*=\s*(\{.*\});", content, re.S)
    return json.loads(match.group(1))


def test_write_dashboard_includes_price_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    portfolio = Portfolio(starting_capital=1000.0)

    write_dashboard(
        instance_name="price_chart_test",
        symbol="ETH/USDT",
        mode="paper",
        portfolio=portfolio,
        current_price=100.0,
        updated_at="2026-09-12 10:00:00",
        price_history=[[1, 95.0], [2, 100.0], [3, 105.0]],
    )

    data = _read_instance_data("price_chart_test")
    assert data["price_history"] == [[1, 95.0], [2, 100.0], [3, 105.0]]
    assert "equity_curve" not in data


def test_write_dashboard_defaults_price_history_to_empty_list(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    portfolio = Portfolio(starting_capital=1000.0)

    write_dashboard(
        instance_name="price_chart_empty_test",
        symbol="BTC/USDT",
        mode="paper",
        portfolio=portfolio,
        current_price=50000.0,
        updated_at="2026-09-12 10:00:00",
    )

    data = _read_instance_data("price_chart_empty_test")
    assert data["price_history"] == []
