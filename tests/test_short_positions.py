"""Ventes a decouvert (EF-104) : comptabilite, regles de risque, moteur, refus au comptant."""
import pytest

from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio, position_value
from tradingbot.risk.risk_manager import RiskConfig, RiskManager, gain_of, is_opening
from tradingbot.types import Candle, OrderResult, Position, Side, Signal


def short_pos(entry=100.0, low=None):
    return Position(quantity=1, avg_entry_price=entry, lot_id=1, peak_price=low if low is not None else entry,
                    direction="short")


def candle(t, price):
    return Candle(timestamp=t, open=price, high=price, low=price, close=price, volume=1)


# ---------------------------------------------------------------- comptabilite
def test_short_gains_when_price_falls_and_cash_never_goes_negative():
    pf = Portfolio(starting_capital=1000, fee_pct=0.001)
    pf.apply_fill(OrderResult(Side.SELL, 5, 100, 0, "filled", position_side="short"))
    assert pf.cash == pytest.approx(1000 - 500 - 0.5)
    assert pf.equity(90) == pytest.approx(pf.cash + 5 * 110)          # montant immobilise + (100 - 90) x 5
    pf.apply_fill(OrderResult(Side.BUY, 5, 90, 1, "filled", position_side="short"))
    trade = pf.trade_history[-1]
    assert trade["direction"] == "short"
    assert trade["pnl"] == pytest.approx(50 - 0.5 - 0.45)               # gain moins frais d'entree et de sortie
    assert pf.cash == pytest.approx(1000 + trade["pnl"])


def test_short_loses_when_price_rises():
    pf = Portfolio(starting_capital=1000)
    pf.apply_fill(OrderResult(Side.SELL, 1, 100, 0, "filled", position_side="short"))
    pf.apply_fill(OrderResult(Side.BUY, 1, 120, 1, "filled", position_side="short"))
    assert pf.trade_history[-1]["pnl"] == pytest.approx(-20)


def test_position_value_by_direction():
    assert position_value(Position(quantity=2, avg_entry_price=100), 110) == 220
    assert position_value(short_pos(), 110) == pytest.approx(90)


# ---------------------------------------------------------------- risque
def test_signal_direction():
    assert is_opening(Signal(Side.BUY)) and not is_opening(Signal(Side.SELL))
    assert is_opening(Signal(Side.SELL, position_side="short")) and not is_opening(Signal(Side.BUY, position_side="short"))
    assert gain_of(short_pos(), 90) == pytest.approx(0.10)


def test_stop_loss_and_take_profit_are_mirrored():
    rm = RiskManager(RiskConfig(stop_loss_pct=0.02, take_profit_pct=0.05))
    assert rm.should_stop_loss(short_pos(), 102.1) and not rm.should_stop_loss(short_pos(), 97)
    assert rm.should_take_profit(short_pos(), 94.9) and not rm.should_take_profit(short_pos(), 98)


@pytest.mark.parametrize("mode,low,threshold", [("distance", 90, 91.8), ("gain", 90, 95.0)])
def test_trailing_stop_follows_the_lowest_price(mode, low, threshold):
    config = RiskConfig(trailing_stop_pct=0.02 if mode == "distance" else 0.5, trailing_mode=mode, trailing_arm_pct=0.02)
    assert config.trailing_stop_price(100, low, "short") == pytest.approx(threshold)
    rm = RiskManager(config)
    assert rm.should_trailing_stop(short_pos(low=low), threshold + 0.01)
    assert not rm.should_trailing_stop(short_pos(low=low), threshold - 0.5)


def test_gain_mode_trailing_not_armed_right_after_short():
    assert RiskConfig(trailing_stop_pct=0.5, trailing_mode="gain", trailing_arm_pct=0.02).trailing_stop_price(
        100, 99.5, "short") is None


def test_closing_needs_a_position_in_the_same_direction():
    rm = RiskManager(RiskConfig())
    longs = [Position(quantity=1, avg_entry_price=100, lot_id=1)]
    assert not rm.validate(Signal(Side.BUY, position_side="short"), open_positions_count=1, open_positions=longs)
    assert rm.validate(Signal(Side.SELL), open_positions_count=1, open_positions=longs)


# ---------------------------------------------------------------- moteur
class Script:
    def __init__(self, signals):
        self.signals = list(signals)

    def on_candle(self, c):
        return self.signals.pop(0) if self.signals else None


def engine_with(signals, **risk):
    pf = Portfolio(starting_capital=1000)
    e = Engine(Script(signals), RiskManager(RiskConfig(stop_loss_pct=None, max_position_size_pct=0.5, **risk)),
               BacktestExecutor(pf), pf)
    return e, pf


def test_engine_opens_a_short_and_exits_at_its_target():
    e, pf = engine_with([Signal(Side.SELL, "vp", stop_price=105, target_price=90, position_side="short")])
    e.process_candle(candle(0, 100))
    assert pf.positions[0].direction == "short" and pf.positions[0].stop_price == 105
    e.process_price_update(candle(1, 95))
    assert pf.positions and pf.positions[0].peak_price == 95                 # plus bas atteint
    e.process_price_update(candle(2, 89))
    assert pf.trade_history[-1]["reason"] == "objectif_trade" and pf.trade_history[-1]["pnl"] == pytest.approx(55)


def test_engine_short_stop_is_above_the_price():
    e, pf = engine_with([Signal(Side.SELL, "vp", stop_price=105, target_price=90, position_side="short")])
    e.process_candle(candle(0, 100))
    e.process_price_update(candle(1, 104))
    assert pf.positions
    e.process_price_update(candle(2, 106))
    assert pf.trade_history[-1]["reason"] == "stop_trade" and pf.trade_history[-1]["pnl"] < 0


def test_strategy_buy_to_cover_closes_only_the_short():
    e, pf = engine_with([Signal(Side.SELL, "s", position_side="short"), None, Signal(Side.BUY, "c", position_side="short")])
    e.process_candle(candle(0, 100))
    e.process_candle(candle(1, 97))
    e.process_candle(candle(2, 96))
    assert not pf.positions and pf.trade_history[-1]["direction"] == "short"


def test_spot_executors_refuse_short_selling():
    from tradingbot.execution.paper_executor import PaperExecutor

    order = PaperExecutor.place_order(object.__new__(PaperExecutor), Side.SELL, 1, 100, 0, position_side="short")
    assert order.status == "rejected" and "decouvert" in order.reason
