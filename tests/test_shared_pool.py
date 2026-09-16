import pytest

from tradingbot.shared_pool import InsufficientFunds, SharedPool


def make_pool(tmp_path, total_cash=1000.0):
    pool = SharedPool(tmp_path / "shared_pool.db")
    pool.seed_if_empty(total_cash)
    return pool


def test_seed_if_empty_only_seeds_once(tmp_path):
    pool = make_pool(tmp_path, 1000.0)
    pool.seed_if_empty(9999.0)  # ne doit rien changer, le panier existe deja
    assert pool.available_cash() == 1000.0


def test_reserve_debits_available_cash(tmp_path):
    pool = make_pool(tmp_path, 1000.0)
    pool.reserve("bot_a", 300.0)
    assert pool.available_cash() == 700.0


def test_reserve_raises_when_insufficient_funds(tmp_path):
    pool = make_pool(tmp_path, 100.0)
    with pytest.raises(InsufficientFunds):
        pool.reserve("bot_a", 300.0)
    assert pool.available_cash() == 100.0  # inchange, rien n'a ete debite


def test_settle_refunds_surplus_when_actual_cost_lower(tmp_path):
    pool = make_pool(tmp_path, 1000.0)
    reservation_id = pool.reserve("bot_a", 300.0)
    pool.settle(reservation_id, 280.0)
    assert pool.available_cash() == 720.0  # 1000 - 300 + (300-280)


def test_settle_absorbs_deficit_when_actual_cost_higher(tmp_path):
    pool = make_pool(tmp_path, 1000.0)
    reservation_id = pool.reserve("bot_a", 300.0)
    pool.settle(reservation_id, 310.0)
    assert pool.available_cash() == 690.0  # 1000 - 300 - 10


def test_settle_is_idempotent(tmp_path):
    pool = make_pool(tmp_path, 1000.0)
    reservation_id = pool.reserve("bot_a", 300.0)
    pool.settle(reservation_id, 280.0)
    pool.settle(reservation_id, 280.0)  # deuxieme appel : ignore, ne credite pas deux fois
    assert pool.available_cash() == 720.0


def test_release_refunds_full_reservation(tmp_path):
    pool = make_pool(tmp_path, 1000.0)
    reservation_id = pool.reserve("bot_a", 300.0)
    pool.release(reservation_id)
    assert pool.available_cash() == 1000.0


def test_release_is_idempotent(tmp_path):
    pool = make_pool(tmp_path, 1000.0)
    reservation_id = pool.reserve("bot_a", 300.0)
    pool.release(reservation_id)
    pool.release(reservation_id)
    assert pool.available_cash() == 1000.0


def test_credit_adds_to_available_cash_without_reservation(tmp_path):
    pool = make_pool(tmp_path, 1000.0)
    pool.credit("bot_a", 150.0)
    assert pool.available_cash() == 1150.0


def test_reconcile_orphaned_reservations_releases_old_open_reservation(tmp_path):
    pool = make_pool(tmp_path, 1000.0)
    reservation_id = pool.reserve("bot_a", 300.0)
    # Simule une reservation tres ancienne (crash entre reserve() et settle()).
    pool.conn.execute("UPDATE reservations SET created_at = 0 WHERE reservation_id = ?", (reservation_id,))
    pool.conn.commit()

    pool.reconcile_orphaned_reservations("bot_a", known_order_costs=[], max_age_seconds=3600)

    assert pool.available_cash() == 1000.0


def test_reconcile_orphaned_reservations_settles_when_matching_order_found(tmp_path):
    pool = make_pool(tmp_path, 1000.0)
    reservation_id = pool.reserve("bot_a", 303.0)  # 300 + marge de slippage
    pool.conn.execute("UPDATE reservations SET created_at = 0 WHERE reservation_id = ?", (reservation_id,))
    pool.conn.commit()

    # Un ordre d'achat de cout 300 a bien ete rempli avant le crash.
    pool.reconcile_orphaned_reservations("bot_a", known_order_costs=[300.0], max_age_seconds=3600)

    assert pool.available_cash() == 700.0  # 1000 - 303 + (303 - 300) regle, pas libere integralement (1000-300)


def test_reconcile_leaves_recent_reservations_untouched(tmp_path):
    pool = make_pool(tmp_path, 1000.0)
    pool.reserve("bot_a", 300.0)  # reservation "recente" (created_at = maintenant)

    pool.reconcile_orphaned_reservations("bot_a", known_order_costs=[], max_age_seconds=3600)

    assert pool.available_cash() == 700.0  # toujours reservee, pas touchee


def test_effective_cap_defaults_to_base_cap_without_history(tmp_path):
    pool = make_pool(tmp_path, 1000.0)
    assert pool.effective_cap("bot_a", 200.0) == 200.0


def test_update_allocation_does_nothing_before_minimum_trade_count(tmp_path):
    pool = make_pool(tmp_path, 1000.0)
    trade_history = [{"pnl": 5.0} for _ in range(5)]  # moins de 10 trades
    pool.update_allocation_after_trade("bot_a", trade_history, base_cap=200.0)
    assert pool.effective_cap("bot_a", 200.0) == 200.0


def test_update_allocation_increases_multiplier_on_improving_score(tmp_path):
    pool = make_pool(tmp_path, 1000.0)
    modest_history = [{"pnl": 0.1} for _ in range(10)]  # win_rate=1.0, rendement moyen modeste
    pool.update_allocation_after_trade("bot_a", modest_history, base_cap=200.0)
    first_cap = pool.effective_cap("bot_a", 200.0)

    strong_history = modest_history + [{"pnl": 10.0}]  # win_rate toujours 1.0, rendement moyen bien meilleur
    pool.update_allocation_after_trade("bot_a", strong_history, base_cap=200.0)
    second_cap = pool.effective_cap("bot_a", 200.0)

    assert second_cap > first_cap


def test_update_allocation_multiplier_is_bounded(tmp_path):
    pool = make_pool(tmp_path, 1000.0)
    history = [{"pnl": 1.0} for _ in range(10)]
    # Beaucoup de trades ameliorants successifs : le multiplicateur ne doit
    # jamais depasser 1.5x le plafond de base.
    for i in range(50):
        history = history + [{"pnl": 1.0 + i}]
        pool.update_allocation_after_trade("bot_a", history, base_cap=200.0)

    assert pool.effective_cap("bot_a", 200.0) <= 300.0  # 200 * 1.5
