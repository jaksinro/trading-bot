from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.types import Position, Side, Signal


def test_blocks_buy_when_existing_position_is_losing():
    rm = RiskManager(RiskConfig(max_concurrent_positions=3, block_buy_if_any_position_losing=True))
    losing_position = Position(quantity=1.0, avg_entry_price=100.0)

    allowed = rm.validate(
        Signal(Side.BUY), open_positions_count=1, open_positions=[losing_position], current_price=95.0
    )

    assert allowed is False


def test_allows_buy_when_all_positions_are_winning():
    rm = RiskManager(RiskConfig(max_concurrent_positions=3, block_buy_if_any_position_losing=True))
    winning_position = Position(quantity=1.0, avg_entry_price=100.0)

    allowed = rm.validate(
        Signal(Side.BUY), open_positions_count=1, open_positions=[winning_position], current_price=105.0
    )

    assert allowed is True


def test_guard_can_be_disabled():
    rm = RiskManager(RiskConfig(max_concurrent_positions=3, block_buy_if_any_position_losing=False))
    losing_position = Position(quantity=1.0, avg_entry_price=100.0)

    allowed = rm.validate(
        Signal(Side.BUY), open_positions_count=1, open_positions=[losing_position], current_price=95.0
    )

    assert allowed is True


def test_explain_rejection_mentions_losing_position():
    rm = RiskManager(RiskConfig(max_concurrent_positions=3, block_buy_if_any_position_losing=True))
    losing_position = Position(quantity=1.0, avg_entry_price=100.0)

    message = rm.explain_rejection(
        Signal(Side.BUY), open_positions_count=1, open_positions=[losing_position], current_price=95.0
    )

    assert "perte" in message
