import os
from uuid import uuid4

import pytest

from app.reliability import create_reliability_run, wait_for_reliability_run
from app.reward_batches import create_reward_batch, get_reward_batch, submit_reward_batch, wait_for_reward_batch
from app.task_queue import dispatch_reliability_run, dispatch_reward_batch, uses_async_worker

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def integration_ready():
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("set RUN_INTEGRATION=1 to run MySQL/Redis/Celery integration tests")
    if not uses_async_worker():
        pytest.skip("integration tests require EXECUTION_MODE=celery")
    if not os.getenv("DATABASE_URL", "").startswith("mysql"):
        pytest.skip("integration tests require DATABASE_URL pointing to MySQL")


def test_concurrent_outbox_poll_via_celery_chord(integration_ready):
    run_id = create_reliability_run("concurrent_consume", trigger="integration")
    assert dispatch_reliability_run(run_id) == "queued"

    report = wait_for_reliability_run(run_id, timeout_seconds=45.0)

    assert report["status"] == "passed"
    assert report["summary"]["actual"]["ledger_entries"] == 1
    assert report["summary"]["actual"]["balance"] == 100
    assert any(event["kind"] == "schedule" for event in report["events"])

    poll_events = [event for event in report["events"] if event["kind"] == "poll"]
    assert len(poll_events) >= 2
    task_ids = {event["payload"].get("task_id") for event in poll_events if event["payload"].get("task_id")}
    assert len(task_ids) >= 2

    # Conditional claim gives ownership to exactly one poller. The other poller must
    # observe that no event remains claimable, while the wallet remains correct.
    outcomes = {event["kind"] for event in report["events"]}
    assert "effect" in outcomes
    assert len([event for event in report["events"] if event["kind"] == "claim"]) == 1
    assert any(event["payload"].get("order_id") is None for event in poll_events)


def test_business_batch_duplicate_dispatch_remains_exactly_once(integration_ready):
    run_suffix = uuid4().hex[:10]
    batch_id = create_reward_batch(
        "integration duplicate dispatch",
        "integration_test",
        [
            {"recipient_id": f"integration_player_1_{run_suffix}", "reward_gems": 100, "failure_mode": "none"},
            {"recipient_id": f"integration_player_2_{run_suffix}", "reward_gems": 250, "failure_mode": "none"},
        ],
    )
    submit_reward_batch(batch_id, "integration_test")

    assert dispatch_reward_batch(batch_id) == "queued"
    assert dispatch_reward_batch(batch_id) == "queued"
    batch = wait_for_reward_batch(batch_id, timeout_seconds=45.0)

    assert batch["status"] == "completed"
    assert len(batch["items"]) == 2
    assert all(item["status"] == "succeeded" for item in batch["items"])
    assert sorted(item["balance"] for item in batch["items"]) == [100, 250]
    assert [event["action"] for event in batch["audit_events"]].count("item.succeeded") == 2
    assert [event["action"] for event in batch["audit_events"]].count("batch.completed") == 1
    assert get_reward_batch(batch_id) == batch
