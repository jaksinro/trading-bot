from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.types import Position, Side, Signal


def test_rejects_buy_when_max_concurrent_positions_reached():
    rm = RiskManager(RiskConfig(max_concurrent_positions=1))
    assert rm.validate(Signal(Side.BUY), open_positions_count=1) is False


def test_rejects_sell_when_no_position():
    rm = RiskManager(RiskConfig())
    assert rm.validate(Signal(Side.SELL), open_positions_count=0) is False


def test_allows_buy_when_flat():
    rm = RiskManager(RiskConfig())
    assert rm.validate(Signal(Side.BUY), open_positions_count=0) is True


def test_allows_buy_below_max_concurrent_positions():
    rm = RiskManager(RiskConfig(max_concurrent_positions=3))
    assert rm.validate(Signal(Side.BUY), open_positions_count=2) is True


def test_rejects_buy_at_max_concurrent_positions():
    rm = RiskManager(RiskConfig(max_concurrent_positions=3))
    assert rm.validate(Signal(Side.BUY), open_positions_count=3) is False


def test_stop_loss_triggers_beyond_threshold():
    rm = RiskManager(RiskConfig(stop_loss_pct=0.02))
    position = Position(quantity=1.0, avg_entry_price=100.0)
    assert rm.should_stop_loss(position, current_price=97.0) is True
    assert rm.should_stop_loss(position, current_price=99.0) is False


def test_daily_loss_halts_trading():
    rm = RiskManager(RiskConfig(max_daily_loss_pct=0.05))
    rm.record_realized_pnl_pct(-0.06)
    assert rm.validate(Signal(Side.BUY), open_positions_count=0) is False


def test_size_for_signal_respects_max_position_pct():
    rm = RiskManager(RiskConfig(max_position_size_pct=0.10))
    quantity = rm.size_for_signal(capital=1000, price=100)
    assert quantity == 1.0  # 10% de 1000 / 100


def test_size_for_signal_applies_size_multiplier():
    rm = RiskManager(RiskConfig(max_position_size_pct=0.10))
    quantity = rm.size_for_signal(capital=1000, price=100, size_multiplier=0.5)
    assert quantity == 0.5  # moitie de la taille normale


def test_size_for_signal_default_multiplier_is_unchanged_behavior():
    rm = RiskManager(RiskConfig(max_position_size_pct=0.10))
    assert rm.size_for_signal(capital=1000, price=100) == rm.size_for_signal(capital=1000, price=100, size_multiplier=1.0)


def test_should_partial_take_profit_false_when_disabled():
    rm = RiskManager(RiskConfig())
    position = Position(quantity=1.0, avg_entry_price=100.0)
    assert rm.should_partial_take_profit(position, current_price=200.0) is False


def test_should_partial_take_profit_true_once_threshold_reached():
    rm = RiskManager(RiskConfig(partial_take_profit_pct=0.05))
    position = Position(quantity=1.0, avg_entry_price=100.0)
    assert rm.should_partial_take_profit(position, current_price=106.0) is True


def test_should_partial_take_profit_false_below_threshold():
    rm = RiskManager(RiskConfig(partial_take_profit_pct=0.05))
    position = Position(quantity=1.0, avg_entry_price=100.0)
    assert rm.should_partial_take_profit(position, current_price=103.0) is False


def test_should_partial_take_profit_false_once_already_done():
    rm = RiskManager(RiskConfig(partial_take_profit_pct=0.05))
    position = Position(quantity=1.0, avg_entry_price=100.0, partial_exit_done=True)
    assert rm.should_partial_take_profit(position, current_price=200.0) is False


def test_should_stop_loss_false_when_disabled():
    """Etape 9 : stop_loss_pct=None desactive reellement le stop-loss (pas
    un contournement via une valeur enorme) - une strategie peut choisir
    explicitement de n'en avoir aucun."""
    rm = RiskManager(RiskConfig(stop_loss_pct=None))
    position = Position(quantity=1.0, avg_entry_price=100.0)
    assert rm.should_stop_loss(position, current_price=1.0) is False  # -99% et toujours pas de stop-loss


def test_should_profit_lock_false_when_disabled():
    rm = RiskManager(RiskConfig())
    position = Position(quantity=1.0, avg_entry_price=100.0, peak_price=110.0)
    assert rm.should_profit_lock(position, current_price=100.0) is False


def test_should_profit_lock_false_before_arm_threshold_reached():
    rm = RiskManager(RiskConfig(profit_lock_arm_pct=0.005, profit_lock_trigger_pct=0.0043))
    position = Position(quantity=1.0, avg_entry_price=100.0, peak_price=100.2)  # pic +0.2%, jamais arme
    assert rm.should_profit_lock(position, current_price=99.0) is False


def test_should_profit_lock_true_once_armed_and_retraced_to_trigger():
    rm = RiskManager(RiskConfig(profit_lock_arm_pct=0.005, profit_lock_trigger_pct=0.0043))
    position = Position(quantity=1.0, avg_entry_price=100.0, peak_price=100.6)  # pic +0.6% >= 0.5% : arme
    assert rm.should_profit_lock(position, current_price=100.40) is True  # gain retombe a +0.40% (<= 0.43%)


def test_should_profit_lock_false_once_armed_but_still_above_trigger():
    rm = RiskManager(RiskConfig(profit_lock_arm_pct=0.005, profit_lock_trigger_pct=0.0043))
    position = Position(quantity=1.0, avg_entry_price=100.0, peak_price=100.6)
    assert rm.should_profit_lock(position, current_price=100.5) is False  # encore au-dessus du seuil de declenchement


def test_explain_rejection_max_concurrent_positions():
    rm = RiskManager(RiskConfig(max_concurrent_positions=1))
    assert "limite" in rm.explain_rejection(Signal(Side.BUY), open_positions_count=1)


def test_explain_rejection_nothing_to_sell():
    rm = RiskManager(RiskConfig())
    assert "aucune position" in rm.explain_rejection(Signal(Side.SELL), open_positions_count=0)


def test_explain_rejection_daily_halt():
    rm = RiskManager(RiskConfig(max_daily_loss_pct=0.05))
    rm.record_realized_pnl_pct(-0.06)
    assert "suspendu" in rm.explain_rejection(Signal(Side.BUY), open_positions_count=0)
