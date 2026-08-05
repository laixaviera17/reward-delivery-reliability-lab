import pytest
from sqlalchemy import event, text

from app.database import connect, get_engine, initialize_database
from app.outbox import release_outbox_claim
from app.reliability import create_reliability_run
from app.reward_delivery import (
    create_experiment_player,
    deliver_reward_once,
    poll_outbox_event,
    request_reward,
)
from app.wallet_invariants import wallet_snapshot


def _prepared_order() -> tuple[int, str, str]:
    run_id = create_reliability_run("duplicate_request", trigger="test")
    player_id = create_experiment_player(run_id)
    order_id, duplicate = request_reward(run_id, player_id, f"test-{run_id}")
    assert duplicate is False
    return run_id, player_id, order_id


def test_direct_duplicate_consumer_does_not_repeat_wallet_effect():
    run_id, player_id, order_id = _prepared_order()

    assert poll_outbox_event(run_id) == "effect_applied"
    assert deliver_reward_once(run_id, order_id) == "duplicate_consumer"

    snapshot = wallet_snapshot(run_id, player_id)
    assert snapshot["ledger_entries"] == 1
    assert snapshot["balance"] == 100
    assert snapshot["outbox_statuses"] == ["consumed"]


def test_failed_worker_attempt_releases_claim_and_can_be_retried(monkeypatch):
    run_id, player_id, _order_id = _prepared_order()
    from app import reward_delivery

    original_complete = reward_delivery._complete_delivery
    calls = 0

    def fail_once(connection, order_id: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated worker interruption")
        original_complete(connection, order_id)

    monkeypatch.setattr(reward_delivery, "_complete_delivery", fail_once)

    with pytest.raises(RuntimeError, match="simulated worker interruption"):
        poll_outbox_event(run_id)

    assert poll_outbox_event(run_id) == "effect_applied"
    snapshot = wallet_snapshot(run_id, player_id)
    assert snapshot["ledger_entries"] == 1
    assert snapshot["balance"] == 100
    assert snapshot["delivery_attempts"] == 2


def test_released_outbox_claim_is_recoverable():
    run_id, player_id, order_id = _prepared_order()
    from app.outbox import claim_pending_outbox_order

    assert claim_pending_outbox_order(run_id) == order_id
    release_outbox_claim(order_id)
    assert poll_outbox_event(run_id) == "effect_applied"
    assert wallet_snapshot(run_id, player_id)["balance"] == 100


def test_idempotency_key_cannot_be_reused_for_a_different_player():
    run_id, _player_id, _order_id = _prepared_order()
    other_player = f"other-{run_id}"
    with connect() as connection:
        connection.execute(
            text("INSERT INTO players (player_id, nickname, gem_balance, account_status) VALUES (:player_id, 'other', 0, 'active')"),
            {"player_id": other_player},
        )

    with pytest.raises(ValueError, match="幂等键已用于不同的奖励请求"):
        request_reward(run_id, other_player, f"test-{run_id}")


def test_order_and_outbox_are_rolled_back_together_on_insert_failure():
    initialize_database()
    run_id = create_reliability_run("duplicate_request", trigger="test")
    player_id = create_experiment_player(run_id)
    engine = get_engine()

    def fail_outbox_insert(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "INSERT INTO delivery_outbox_events" in statement:
            raise RuntimeError("simulated outbox insert failure")

    event.listen(engine, "before_cursor_execute", fail_outbox_insert)
    try:
        with pytest.raises(RuntimeError, match="simulated outbox insert failure"):
            request_reward(run_id, player_id, f"rollback-{run_id}")
    finally:
        event.remove(engine, "before_cursor_execute", fail_outbox_insert)

    with connect() as connection:
        orders = connection.execute(
            text("SELECT COUNT(*) FROM delivery_orders WHERE run_id = :run_id"),
            {"run_id": run_id},
        ).scalar_one()
        outbox = connection.execute(text("SELECT COUNT(*) FROM delivery_outbox_events")).scalar_one()
    assert orders == 0
    assert outbox == 0
