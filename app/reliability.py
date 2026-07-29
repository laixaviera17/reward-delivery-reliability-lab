"""Compatibility entry point for reliability run creation and execution.

Domain-specific work lives in reliability_scenarios, reliability_events,
reward_delivery, wallet_invariants, and reliability_reports. Public functions
remain available from this module for the API, Celery tasks, and existing users.
"""

from __future__ import annotations

import time

from sqlalchemy import text

from .database import connect, get_engine, initialize_database
from .reliability_events import record_reliability_event, utc_now
from .reliability_reports import finish_reliability_run, get_reliability_run, list_reliability_runs, mark_run_failed, reliability_trend
from .reliability_scenarios import SCENARIOS, available_reliability_scenarios
from .reward_delivery import create_experiment_player, deliver_reward_once, deliver_without_ledger_guard, pending_outbox_order_for_run, poll_outbox_event, request_reward


def create_reliability_run(scenario: str, trigger: str = "dashboard") -> int:
    """Create a queued run while preserving the existing API-visible record."""
    if scenario not in SCENARIOS:
        raise ValueError("不支持的可靠性实验场景")
    initialize_database()
    with connect() as connection:
        cursor = connection.execute(
            text("""INSERT INTO reliability_runs (scenario, `trigger`, status, started_at)
                VALUES (:scenario, :trigger, 'queued', :started_at)"""),
            {"scenario": scenario, "trigger": trigger, "started_at": utc_now()},
        )
        return int(cursor.lastrowid)


def finalize_concurrent_reliability_run(run_id: int, player_id: str) -> dict[str, object]:
    """Celery chord callback: both independent Outbox poller tasks have completed."""
    return finish_reliability_run(run_id, player_id, "concurrent_consume")


def _schedule_concurrent_outbox_pollers(run_id: int, player_id: str) -> None:
    from celery import chord, group

    from .task_queue import celery_app

    pollers = group(
        celery_app.signature("app.tasks.poll_outbox_event", args=[run_id]),
        celery_app.signature("app.tasks.poll_outbox_event", args=[run_id]),
    )
    callback = celery_app.signature("app.tasks.finalize_concurrent_reliability_run", args=[run_id, player_id])
    chord(pollers)(callback)
    record_reliability_event(run_id, "schedule", "已提交两个独立 Outbox 轮询任务，等待回调任务执行最终断言", poller_count=2)


def execute_reliability_run(run_id: int) -> dict[str, object]:
    """Orchestrate the selected scenario; delivery and assertions remain delegated."""
    initialize_database()
    with connect() as connection:
        run = connection.execute(text("SELECT scenario FROM reliability_runs WHERE run_id = :run_id"), {"run_id": run_id}).mappings().first()
        if not run:
            raise ValueError("可靠性实验不存在")
        scenario = str(run["scenario"])
        connection.execute(text("UPDATE reliability_runs SET status = 'running', started_at = :started_at, error_message = NULL WHERE run_id = :run_id"), {"started_at": utc_now(), "run_id": run_id})
    try:
        player_id = create_experiment_player(run_id)
        record_reliability_event(run_id, "setup", "创建实验玩家，初始余额为 0", player_id=player_id, initial_balance=0)
        order_id, duplicate = request_reward(run_id, player_id, f"reliability_{run_id}_request")
        if scenario == "duplicate_request":
            repeated_order, repeated_duplicate = request_reward(run_id, player_id, f"reliability_{run_id}_request")
            if repeated_order != order_id or not repeated_duplicate or duplicate:
                raise AssertionError("重复请求没有稳定命中同一张订单")
            poll_outbox_event(run_id)
        elif scenario == "acknowledgement_loss":
            poll_outbox_event(run_id, lose_acknowledgement=True)
            poll_outbox_event(run_id)
        elif scenario == "concurrent_consume":
            if get_engine().dialect.name == "sqlite":
                pending_order_id = pending_outbox_order_for_run(run_id)
                record_reliability_event(run_id, "poll", "Outbox 轮询发现待消费事件（本地串行仿真双消费者）", order_id=pending_order_id, pending_count=1)
                deliver_reward_once(run_id, pending_order_id)
                deliver_reward_once(run_id, pending_order_id)
            else:
                _schedule_concurrent_outbox_pollers(run_id, player_id)
                return get_reliability_run(run_id) or {}
        elif scenario == "guard_disabled_control":
            deliver_without_ledger_guard(run_id, order_id)
            deliver_without_ledger_guard(run_id, order_id)
        else:
            raise ValueError("不支持的可靠性实验场景")
    except Exception as error:
        return mark_run_failed(run_id, error)
    return finish_reliability_run(run_id, player_id, scenario)


def wait_for_reliability_run(run_id: int, *, timeout_seconds: float = 30.0, poll_interval: float = 0.5) -> dict[str, object]:
    """Poll until a run leaves queued/running, or raise TimeoutError."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        report = get_reliability_run(run_id)
        if report and report["status"] not in {"queued", "running"}:
            return report
        time.sleep(poll_interval)
    raise TimeoutError(f"可靠性实验 #{run_id} 在 {timeout_seconds}s 内未完成")
