"""Couts des courtiers existants pour l'atelier (EF-106)."""
import pytest

from tradingbot.brokers import costs
from tradingbot.brokers.costs import BROKERS, capitalcom_reader, costs_for

PRICES = {"BTC": 100_000.0, "ETH": 2_500.0, "DOGE": 0.2}
FIELDS = ("fee_pct", "spread_pct", "overnight_pct", "overnight_short_pct")


def price_of(base):
    return PRICES.get(base)


@pytest.mark.parametrize("broker", list(BROKERS))
def test_every_broker_fills_every_cost_field_for_eth(broker):
    r = costs_for(broker, "ETH/USDT", price_of)
    assert r["available"] and all(isinstance(r[f], float) for f in FIELDS)
    assert r["notes"] and r["sources"] and r["checked"]


def test_published_bitcoin_spread_in_points_becomes_a_percentage():
    assert costs_for("capitalcom", "BTC/USDT", price_of)["spread_pct"] == pytest.approx(50 / 100_000)


def test_unpublished_spread_is_estimated_like_bitcoin_and_said_so():
    r = costs_for("capitalcom", "DOGE/USDT", price_of)
    assert r["spread_pct"] == pytest.approx(50 / 100_000)
    assert "non publie" in r["notes"][0]


def test_leveraged_cfd_charges_buyers_and_credits_sellers_overnight():
    r = costs_for("capitalcom_2x", "ETH/USDT", price_of)
    assert r["overnight_pct"] == pytest.approx(0.0006164) and r["overnight_short_pct"] == pytest.approx(-0.000137)
    assert costs_for("capitalcom", "ETH/USDT", price_of)["overnight_pct"] == 0.0     # sans levier


def test_futures_fee_per_contract_and_unlisted_asset():
    r = costs_for("ninjatrader", "ETH/USDT", price_of)
    assert r["fee_pct"] == pytest.approx(0.79 / (0.1 * 2_500))
    assert r["spread_pct"] == pytest.approx(0.5 / 2_500)
    doge = costs_for("ninjatrader", "DOGE/USDT", price_of)
    assert doge["available"] is False and "fee_pct" not in doge


def test_spot_brokers_refuse_short_selling():
    assert not costs_for("binance", "ETH/USDT", price_of)["shorts"]
    assert costs_for("capitalcom", "ETH/USDT", price_of)["shorts"]


def test_unknown_broker_is_refused():
    with pytest.raises(ValueError):
        costs_for("nope", "ETH/USDT", price_of)


# ---------------------------------------------------------------- lecture en direct (Capital.com)
class FakeClient:
    def market(self, epic):
        return {"snapshot": {"bid": 2499.0, "offer": 2501.0},
                "instrument": {"overnightFee": {"longRate": -0.06164, "shortRate": 0.0137}}}


def test_live_values_replace_published_ones_when_the_demo_key_is_set(monkeypatch):
    monkeypatch.setenv("CAPITALCOM_API_KEY", "x")
    r = costs_for("capitalcom_2x", "ETH/USDT", price_of, live_reader=capitalcom_reader(FakeClient))
    assert r["live"] and r["spread_pct"] == pytest.approx(2 / 2500)
    assert r["overnight_pct"] == pytest.approx(0.0006164) and r["overnight_short_pct"] == pytest.approx(-0.000137)
    assert "ETHUSD" in r["notes"][0]


def test_live_failure_keeps_published_values(monkeypatch):
    monkeypatch.setenv("CAPITALCOM_API_KEY", "x")

    def broken(broker, base):
        raise ConnectionError("hors ligne")

    r = costs_for("capitalcom", "ETH/USDT", price_of, live_reader=broken)
    assert not r["live"] and r["spread_pct"] == pytest.approx(50 / 100_000)
    assert "impossible" in r["notes"][0]


def test_without_demo_key_no_live_read_is_attempted(monkeypatch):
    monkeypatch.delenv("CAPITALCOM_API_KEY", raising=False)

    def must_not_run(broker, base):
        raise AssertionError("lecture en direct sans cle")

    r = costs_for("capitalcom", "ETH/USDT", price_of, live_reader=must_not_run)
    assert not r["live"] and any("absente" in n for n in r["notes"])


def test_published_values_are_dated():
    assert costs.CHECKED == "2026-10-09"
