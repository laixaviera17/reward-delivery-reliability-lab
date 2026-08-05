from fastapi.testclient import TestClient

from app.main import app


def test_sync_health_marks_async_dependencies_not_required():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["mode"] == "sync"
    assert response.json()["dependencies"] == {
        "database": "healthy",
        "redis": "not_required",
        "worker": "not_required",
    }
    assert response.headers["X-Request-ID"]


def test_v1_run_contract_is_stable_in_sync_mode():
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/reliability/runs",
            json={"scenario": "duplicate_request"},
        )

        assert created.status_code == 202
        task = created.json()
        assert set(task) == {"run_id", "status", "detail_url"}
        assert task["status"] == "passed"
        assert task["detail_url"] == f"/api/v1/reliability/runs/{task['run_id']}"

        detail = client.get(task["detail_url"])
        assert detail.status_code == 200
        assert detail.json()["run_id"] == task["run_id"]


def test_v1_rejects_unknown_fields_with_consistent_error_contract():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/reliability/runs",
            json={"scenario": "duplicate_request", "scenairo": "typo"},
            headers={"X-Request-ID": "contract-test"},
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["error"]["fields"]
    assert payload["request_id"] == "contract-test"
    assert response.headers["X-Request-ID"] == "contract-test"


def test_v1_not_found_uses_the_same_error_contract():
    with TestClient(app) as client:
        response = client.get("/api/v1/reliability/runs/999999")

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "可靠性实验不存在",
        "fields": [],
    }


def test_dashboard_uses_versioned_api_and_recovers_pending_runs():
    with TestClient(app) as client:
        response = client.get("/dashboard")

    assert response.status_code == 200
    assert "const $=selector=>document.querySelector(selector),API='/api/v1'" in response.text
    assert "reward-platform.pending-run" in response.text
    assert "Promise.allSettled" in response.text
