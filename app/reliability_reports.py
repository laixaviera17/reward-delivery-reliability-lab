from __future__ import annotations

import json

from sqlalchemy import text

from .database import connect, initialize_database
from .reliability_events import record_reliability_event, utc_now
from .reliability_scenarios import SCENARIOS
from .wallet_invariants import assert_wallet_invariants


def get_reliability_run(run_id: int) -> dict[str, object] | None:
    """Serialize an existing run into the unchanged public report shape."""
    initialize_database()
    with connect() as connection:
        run = connection.execute(text("SELECT * FROM reliability_runs WHERE run_id = :run_id"), {"run_id": run_id}).mappings().first()
        if not run:
            return None
        events = (
            connection.execute(
                text("SELECT kind, message, payload_json, created_at FROM reliability_events WHERE run_id = :run_id ORDER BY event_id"),
                {"run_id": run_id},
            )
            .mappings()
            .all()
        )
    return {
        "run_id": run["run_id"],
        "scenario": run["scenario"],
        "scenario_title": SCENARIOS[run["scenario"]]["title"],
        "trigger": run["trigger"],
        "status": run["status"],
        "started_at": run["started_at"],
        "completed_at": run["completed_at"],
        "passed": bool(run["passed"]) if run["passed"] is not None else None,
        "summary": json.loads(run["summary_json"]) if run["summary_json"] else None,
        "error_message": run["error_message"],
        "events": [
            {
                "kind": event["kind"],
                "message": event["message"],
                "payload": json.loads(event["payload_json"]),
                "created_at": event["created_at"],
            }
            for event in events
        ],
    }


def list_reliability_runs(limit: int = 12) -> list[dict[str, object]]:
    initialize_database()
    with connect() as connection:
        rows = (
            connection.execute(text("SELECT * FROM reliability_runs ORDER BY run_id DESC LIMIT :limit"), {"limit": limit}).mappings().all()
        )
    return [
        {
            "run_id": row["run_id"],
            "scenario": row["scenario"],
            "scenario_title": SCENARIOS[row["scenario"]]["title"],
            "status": row["status"],
            "passed": bool(row["passed"]) if row["passed"] is not None else None,
            "completed_at": row["completed_at"],
            "summary": json.loads(row["summary_json"]) if row["summary_json"] else None,
        }
        for row in rows
    ]


def reliability_trend(limit: int = 12) -> dict[str, object]:
    runs = list_reliability_runs(limit)
    finished = [run for run in runs if run["status"] in {"passed", "detected", "failed"}]
    passed = sum(run["status"] in {"passed", "detected"} for run in finished)
    return {
        "total_runs": len(finished),
        "verified_runs": passed,
        "failed_runs": len(finished) - passed,
        "verification_rate": round(passed / len(finished) * 100, 1) if finished else 0,
        "points": list(reversed(finished)),
    }


def finish_reliability_run(run_id: int, player_id: str, scenario: str) -> dict[str, object]:
    """Persist the invariant result and return the unchanged run report."""
    try:
        assertion = assert_wallet_invariants(run_id, player_id, scenario)
        if scenario == "guard_disabled_control":
            verification_passed = not bool(assertion["passed"])
            status = "detected" if verification_passed else "failed"
            record_reliability_event(
                run_id, "detection", "已检出账本守卫失效导致的重复余额副作用" if verification_passed else "对照失效未被检出", **assertion
            )
        else:
            verification_passed = bool(assertion["passed"])
            status = "passed" if verification_passed else "failed"
            record_reliability_event(
                run_id, "assertion", "最终不变量校验通过" if verification_passed else "最终不变量校验失败", **assertion
            )
        error_message = None
    except Exception as error:
        assertion = {"passed": False, "expected": {}, "actual": {}}
        verification_passed = False
        status = "failed"
        error_message = f"{type(error).__name__}: {error}"
        record_reliability_event(run_id, "error", "实验执行出现异常", error_message=error_message)
    with connect() as connection:
        connection.execute(
            text("""UPDATE reliability_runs SET status = :status, completed_at = :completed_at, passed = :passed,
                summary_json = :summary_json, error_message = :error_message WHERE run_id = :run_id"""),
            {
                "status": status,
                "completed_at": utc_now(),
                "passed": int(verification_passed),
                "summary_json": json.dumps(
                    {"verification_passed": verification_passed, "invariant_passed": assertion["passed"], **assertion}, ensure_ascii=False
                ),
                "error_message": error_message,
                "run_id": run_id,
            },
        )
    return get_reliability_run(run_id) or {}


def mark_run_failed(run_id: int, error: Exception) -> dict[str, object]:
    """Record an execution failure using the existing report payload and status."""
    message = f"{type(error).__name__}: {error}"
    record_reliability_event(run_id, "error", "实验执行出现异常", error_message=message)
    with connect() as connection:
        connection.execute(
            text("""UPDATE reliability_runs SET status = 'failed', completed_at = :completed_at, passed = 0,
                summary_json = :summary_json, error_message = :error_message WHERE run_id = :run_id"""),
            {
                "completed_at": utc_now(),
                "summary_json": json.dumps(
                    {"verification_passed": False, "invariant_passed": False, "passed": False, "expected": {}, "actual": {}},
                    ensure_ascii=False,
                ),
                "error_message": message,
                "run_id": run_id,
            },
        )
    return get_reliability_run(run_id) or {}
