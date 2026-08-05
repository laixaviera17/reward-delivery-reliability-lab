from fastapi.testclient import TestClient

from app.main import app
from app.reward_batches import process_reward_batch


def _create_batch(client: TestClient, *, failure_mode: str = "fail_once") -> dict:
    response = client.post(
        "/api/v1/reward-batches",
        json={
            "name": "八月活动奖励",
            "created_by": "qa_admin",
            "items": [
                {"recipient_id": "player_001", "reward_gems": 100, "failure_mode": "none"},
                {"recipient_id": "player_002", "reward_gems": 250, "failure_mode": failure_mode},
            ],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_minimum_delivery_flow_retry_ledger_and_audit():
    with TestClient(app) as client:
        draft = _create_batch(client)
        assert draft["status"] == "draft"
        assert len(draft["items"]) == 2

        submitted = client.post(
            f"/api/v1/reward-batches/{draft['batch_id']}/submit",
            json={"actor": "operator_01"},
        )
        assert submitted.status_code == 202

        partial = client.get(f"/api/v1/reward-batches/{draft['batch_id']}").json()
        assert partial["status"] == "partial_failed"
        assert {item["status"] for item in partial["items"]} == {"succeeded", "failed"}

        failed_item = next(item for item in partial["items"] if item["status"] == "failed")
        retried = client.post(
            f"/api/v1/reward-items/{failed_item['item_id']}/retry",
            json={"actor": "reviewer_01"},
        )
        assert retried.status_code == 202

        completed = client.get(f"/api/v1/reward-batches/{draft['batch_id']}").json()
        assert completed["status"] == "completed"
        assert all(item["status"] == "succeeded" for item in completed["items"])
        assert next(item for item in completed["items"] if item["recipient_id"] == "player_002")["attempt_count"] == 2

        ledger = client.get("/api/v1/reward-ledger").json()["items"]
        assert len(ledger) == 2
        assert sum(item["reward_gems"] for item in ledger) == 350

        actions = [event["action"] for event in completed["audit_events"]]
        assert "batch.created" in actions
        assert "batch.submitted" in actions
        assert "item.failed" in actions
        assert "item.retry_requested" in actions
        assert "item.succeeded" in actions
        assert "batch.completed" in actions

        stats = client.get("/api/v1/reward-stats").json()
        assert stats["deliveries"] == {"total": 2, "succeeded": 2, "failed": 0, "success_rate": 100.0}
        assert stats["total_gems"] == 350


def test_processing_a_completed_batch_again_is_idempotent():
    with TestClient(app) as client:
        draft = _create_batch(client, failure_mode="none")
        client.post(f"/api/v1/reward-batches/{draft['batch_id']}/submit", json={"actor": "operator"})
        first = client.get(f"/api/v1/reward-batches/{draft['batch_id']}").json()
        assert first["status"] == "completed"

        result = process_reward_batch(draft["batch_id"])
        assert result["status"] == "completed"
        assert result["outcomes"] == []
        ledger = client.get("/api/v1/reward-ledger").json()["items"]
        assert len(ledger) == 2
        assert {item["current_balance"] for item in ledger} == {100, 250}
        refreshed = client.get(f"/api/v1/reward-batches/{draft['batch_id']}").json()
        assert [event["action"] for event in refreshed["audit_events"]].count("batch.completed") == 1


def test_invalid_batch_transitions_and_duplicate_recipients_are_rejected():
    with TestClient(app) as client:
        duplicate = client.post(
            "/api/v1/reward-batches",
            json={
                "name": "重复对象",
                "items": [
                    {"recipient_id": "same_player", "reward_gems": 10},
                    {"recipient_id": "same_player", "reward_gems": 20},
                ],
            },
        )
        assert duplicate.status_code == 422

        draft = _create_batch(client, failure_mode="none")
        first_submit = client.post(f"/api/v1/reward-batches/{draft['batch_id']}/submit", json={"actor": "operator"})
        second_submit = client.post(f"/api/v1/reward-batches/{draft['batch_id']}/submit", json={"actor": "operator"})
        assert first_submit.status_code == 202
        assert second_submit.status_code == 409

        completed = client.get(f"/api/v1/reward-batches/{draft['batch_id']}").json()
        retry_succeeded = client.post(
            f"/api/v1/reward-items/{completed['items'][0]['item_id']}/retry",
            json={"actor": "operator"},
        )
        assert retry_succeeded.status_code == 409


def test_always_failing_item_stops_at_retry_limit():
    with TestClient(app) as client:
        draft = _create_batch(client, failure_mode="always_fail")
        client.post(f"/api/v1/reward-batches/{draft['batch_id']}/submit", json={"actor": "operator"})

        for expected_attempt in (2, 3):
            batch = client.get(f"/api/v1/reward-batches/{draft['batch_id']}").json()
            item = next(item for item in batch["items"] if item["status"] == "failed")
            response = client.post(f"/api/v1/reward-items/{item['item_id']}/retry", json={"actor": "operator"})
            assert response.status_code == 202
            updated = client.get(f"/api/v1/reward-batches/{draft['batch_id']}").json()
            failed = next(item for item in updated["items"] if item["status"] == "failed")
            assert failed["attempt_count"] == expected_attempt

        exhausted = client.get(f"/api/v1/reward-batches/{draft['batch_id']}").json()
        failed = next(item for item in exhausted["items"] if item["status"] == "failed")
        response = client.post(f"/api/v1/reward-items/{failed['item_id']}/retry", json={"actor": "operator"})
        assert response.status_code == 409
        assert response.json()["error"]["message"] == "已达到最大重试次数"


def test_failed_item_operational_list_exposes_retry_context():
    with TestClient(app) as client:
        draft = _create_batch(client, failure_mode="always_fail")
        client.post(f"/api/v1/reward-batches/{draft['batch_id']}/submit", json={"actor": "operator"})

        failed = client.get("/api/v1/reward-items?status=failed").json()["items"]
        assert len(failed) == 1
        assert failed[0]["batch_name"] == "八月活动奖励"
        assert failed[0]["outbox_status"] == "failed"
        assert failed[0]["attempt_count"] == 1


def test_unexpected_delivery_error_becomes_visible_and_retryable(monkeypatch):
    from app import reward_batches

    with TestClient(app) as client:
        draft = _create_batch(client, failure_mode="none")
        original = reward_batches._deliver_reward_item
        calls = 0

        def interrupt_once(item_id: str) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("simulated downstream interruption")
            return original(item_id)

        monkeypatch.setattr(reward_batches, "_deliver_reward_item", interrupt_once)
        client.post(f"/api/v1/reward-batches/{draft['batch_id']}/submit", json={"actor": "operator"})

        partial = client.get(f"/api/v1/reward-batches/{draft['batch_id']}").json()
        failed = next(item for item in partial["items"] if item["status"] == "failed")
        assert failed["outbox_status"] == "failed"
        assert "RuntimeError" in failed["last_error"]

        retried = client.post(f"/api/v1/reward-items/{failed['item_id']}/retry", json={"actor": "reviewer"})
        assert retried.status_code == 202
        completed = client.get(f"/api/v1/reward-batches/{draft['batch_id']}").json()
        assert completed["status"] == "completed"
