from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.types import Position


def test_trailing_stop_disabled_by_default():
    rm = RiskManager(RiskConfig())
    position = Position(quantity=1.0, avg_entry_price=100.0, peak_price=150.0)
    assert rm.should_trailing_stop(position, current_price=90.0) is False


def test_trailing_stop_triggers_on_drop_from_peak():
    rm = RiskManager(RiskConfig(trailing_stop_pct=0.05))
    position = Position(quantity=1.0, avg_entry_price=100.0, peak_price=150.0)
    # chute de 10% depuis le pic (150 -> 135), au-dela du seuil de 5%
    assert rm.should_trailing_stop(position, current_price=135.0) is True


def test_trailing_stop_does_not_trigger_below_threshold():
    rm = RiskManager(RiskConfig(trailing_stop_pct=0.10))
    position = Position(quantity=1.0, avg_entry_price=100.0, peak_price=150.0)
    # chute de seulement 2% depuis le pic
    assert rm.should_trailing_stop(position, current_price=147.0) is False


def test_trailing_stop_uses_entry_price_if_never_moved_up():
    rm = RiskManager(RiskConfig(trailing_stop_pct=0.05))
    position = Position(quantity=1.0, avg_entry_price=100.0, peak_price=0.0)  # jamais mis a jour
    assert rm.should_trailing_stop(position, current_price=94.0) is True
