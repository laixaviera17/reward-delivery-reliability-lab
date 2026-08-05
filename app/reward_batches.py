from __future__ import annotations

import json
import time
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from .database import connect, initialize_database
from .reliability_events import utc_now

MAX_DELIVERY_ATTEMPTS = 3
TERMINAL_BATCH_STATUSES = {"completed", "partial_failed"}


def _audit(
    connection: Connection,
    batch_id: str,
    action: str,
    message: str,
    *,
    actor: str = "system",
    item_id: str | None = None,
    **payload: object,
) -> None:
    connection.execute(
        text(
            """INSERT INTO reward_audit_events
            (batch_id, item_id, actor, action, message, payload_json, created_at)
            VALUES (:batch_id, :item_id, :actor, :action, :message, :payload_json, :created_at)"""
        ),
        {
            "batch_id": batch_id,
            "item_id": item_id,
            "actor": actor,
            "action": action,
            "message": message,
            "payload_json": json.dumps(payload, ensure_ascii=False),
            "created_at": utc_now(),
        },
    )


def create_reward_batch(name: str, created_by: str, items: list[dict[str, object]]) -> str:
    """Create a draft batch and its recipients without scheduling side effects."""
    if not items:
        raise ValueError("发放批次至少需要一条奖励明细")
    recipients = [str(item["recipient_id"]) for item in items]
    if len(recipients) != len(set(recipients)):
        raise ValueError("同一批次不能包含重复发放对象")

    initialize_database()
    batch_id = f"batch_{uuid.uuid4().hex[:16]}"
    now = utc_now()
    with connect() as connection:
        connection.execute(
            text(
                """INSERT INTO reward_batches
                (batch_id, name, status, created_by, created_at)
                VALUES (:batch_id, :name, 'draft', :created_by, :created_at)"""
            ),
            {"batch_id": batch_id, "name": name, "created_by": created_by, "created_at": now},
        )
        for item in items:
            recipient_id = str(item["recipient_id"])
            account_exists = connection.execute(
                text("SELECT recipient_id FROM reward_accounts WHERE recipient_id = :recipient_id"),
                {"recipient_id": recipient_id},
            ).scalar_one_or_none()
            if account_exists is None:
                connection.execute(
                    text(
                        """INSERT INTO reward_accounts (recipient_id, balance, updated_at)
                        VALUES (:recipient_id, 0, :updated_at)"""
                    ),
                    {"recipient_id": recipient_id, "updated_at": now},
                )
            item_id = f"item_{uuid.uuid4().hex[:16]}"
            connection.execute(
                text(
                    """INSERT INTO reward_items
                    (item_id, batch_id, recipient_id, reward_gems, idempotency_key, failure_mode,
                     status, attempt_count, created_at, updated_at)
                    VALUES (:item_id, :batch_id, :recipient_id, :reward_gems, :idempotency_key,
                            :failure_mode, 'draft', 0, :created_at, :updated_at)"""
                ),
                {
                    "item_id": item_id,
                    "batch_id": batch_id,
                    "recipient_id": recipient_id,
                    "reward_gems": int(str(item["reward_gems"])),
                    "idempotency_key": f"{batch_id}:{recipient_id}",
                    "failure_mode": str(item.get("failure_mode", "none")),
                    "created_at": now,
                    "updated_at": now,
                },
            )
        _audit(connection, batch_id, "batch.created", "已创建奖励发放草稿", actor=created_by, item_count=len(items))
    return batch_id


def submit_reward_batch(batch_id: str, actor: str) -> None:
    """Atomically submit all draft items and create their Outbox events."""
    now = utc_now()
    with connect() as connection:
        batch = connection.execute(
            text("SELECT status FROM reward_batches WHERE batch_id = :batch_id"), {"batch_id": batch_id}
        ).mappings().first()
        if not batch:
            raise LookupError("奖励批次不存在")
        if batch["status"] != "draft":
            raise ValueError("只有草稿批次可以提交")
        items = connection.execute(
            text("SELECT item_id FROM reward_items WHERE batch_id = :batch_id ORDER BY item_id"), {"batch_id": batch_id}
        ).scalars().all()
        for item_id in items:
            connection.execute(
                text(
                    """INSERT INTO reward_outbox_events (item_id, status, created_at)
                    VALUES (:item_id, 'pending', :created_at)"""
                ),
                {"item_id": item_id, "created_at": now},
            )
        connection.execute(
            text("UPDATE reward_items SET status = 'queued', updated_at = :now WHERE batch_id = :batch_id"),
            {"now": now, "batch_id": batch_id},
        )
        connection.execute(
            text("UPDATE reward_batches SET status = 'processing', submitted_at = :now WHERE batch_id = :batch_id"),
            {"now": now, "batch_id": batch_id},
        )
        _audit(connection, batch_id, "batch.submitted", "批次已提交至可靠发放引擎", actor=actor, item_count=len(items))


def _claim_reward_item(batch_id: str) -> str | None:
    with connect() as connection:
        candidate = connection.execute(
            text(
                """SELECT i.item_id FROM reward_items i
                JOIN reward_outbox_events o ON o.item_id = i.item_id
                WHERE i.batch_id = :batch_id AND o.status = 'pending'
                ORDER BY o.event_id LIMIT 1"""
            ),
            {"batch_id": batch_id},
        ).scalar_one_or_none()
        if candidate is None:
            return None
        item_id = str(candidate)
        claimed = connection.execute(
            text(
                """UPDATE reward_outbox_events SET status = 'processing'
                WHERE item_id = :item_id AND status = 'pending'"""
            ),
            {"item_id": item_id},
        )
        if claimed.rowcount != 1:
            return None
        connection.execute(
            text(
                """UPDATE reward_items SET status = 'processing', attempt_count = attempt_count + 1,
                updated_at = :now WHERE item_id = :item_id"""
            ),
            {"now": utc_now(), "item_id": item_id},
        )
        return item_id


def _fail_item(connection: Connection, item: dict[str, Any], error_message: str) -> None:
    now = utc_now()
    connection.execute(
        text(
            """UPDATE reward_items SET status = 'failed', last_error = :error_message,
            updated_at = :now WHERE item_id = :item_id"""
        ),
        {"error_message": error_message, "now": now, "item_id": item["item_id"]},
    )
    connection.execute(
        text("UPDATE reward_outbox_events SET status = 'failed' WHERE item_id = :item_id"),
        {"item_id": item["item_id"]},
    )
    _audit(
        connection,
        str(item["batch_id"]),
        "item.failed",
        "奖励发放失败，等待人工重试",
        item_id=str(item["item_id"]),
        recipient_id=item["recipient_id"],
        attempt_count=item["attempt_count"],
        error=error_message,
    )


def _mark_claimed_item_failed(item_id: str, error: Exception) -> None:
    """Move an unexpectedly interrupted claimed item into a retryable state."""
    with connect() as connection:
        item = connection.execute(
            text("SELECT * FROM reward_items WHERE item_id = :item_id"),
            {"item_id": item_id},
        ).mappings().one()
        _fail_item(connection, dict(item), f"{type(error).__name__}: {error}")


def _deliver_reward_item(item_id: str) -> str:
    """Apply one idempotent item effect and persist an audit event."""
    with connect() as connection:
        item = connection.execute(
            text("SELECT * FROM reward_items WHERE item_id = :item_id"), {"item_id": item_id}
        ).mappings().one()
        failure_mode = str(item["failure_mode"])
        attempt_count = int(item["attempt_count"])
        if failure_mode == "always_fail" or (failure_mode == "fail_once" and attempt_count == 1):
            _fail_item(connection, dict(item), f"模拟下游渠道失败（{failure_mode}）")
            return "failed"

        try:
            ledger_exists = connection.execute(
                text("SELECT entry_id FROM reward_ledger WHERE item_id = :item_id"), {"item_id": item_id}
            ).scalar_one_or_none()
            if ledger_exists is None:
                now = utc_now()
                connection.execute(
                    text(
                        """INSERT INTO reward_ledger
                        (item_id, batch_id, recipient_id, reward_gems, created_at)
                        VALUES (:item_id, :batch_id, :recipient_id, :reward_gems, :created_at)"""
                    ),
                    {
                        "item_id": item_id,
                        "batch_id": item["batch_id"],
                        "recipient_id": item["recipient_id"],
                        "reward_gems": item["reward_gems"],
                        "created_at": now,
                    },
                )
                connection.execute(
                    text(
                        """UPDATE reward_accounts SET balance = balance + :reward_gems,
                        updated_at = :now WHERE recipient_id = :recipient_id"""
                    ),
                    {"reward_gems": item["reward_gems"], "now": now, "recipient_id": item["recipient_id"]},
                )
            now = utc_now()
            connection.execute(
                text(
                    """UPDATE reward_items SET status = 'succeeded', last_error = NULL,
                    delivered_at = :now, updated_at = :now WHERE item_id = :item_id"""
                ),
                {"now": now, "item_id": item_id},
            )
            connection.execute(
                text(
                    """UPDATE reward_outbox_events SET status = 'consumed', consumed_at = :now
                    WHERE item_id = :item_id"""
                ),
                {"now": now, "item_id": item_id},
            )
            _audit(
                connection,
                str(item["batch_id"]),
                "item.succeeded",
                "奖励已写入唯一账本并更新账户余额",
                item_id=item_id,
                recipient_id=item["recipient_id"],
                reward_gems=item["reward_gems"],
                attempt_count=attempt_count,
                deduplicated=ledger_exists is not None,
            )
            return "deduplicated" if ledger_exists is not None else "succeeded"
        except IntegrityError:
            # A competing consumer won the unique ledger insert.  The enclosing
            # transaction is rolled back and the caller can safely retry.
            raise


def _refresh_batch_status(batch_id: str) -> str:
    with connect() as connection:
        statuses = list(
            connection.execute(
                text("SELECT status FROM reward_items WHERE batch_id = :batch_id"), {"batch_id": batch_id}
            ).scalars()
        )
        if statuses and all(status == "succeeded" for status in statuses):
            status = "completed"
        elif any(status == "failed" for status in statuses) and all(status in {"succeeded", "failed"} for status in statuses):
            status = "partial_failed"
        else:
            status = "processing"
        completed_at = utc_now() if status in TERMINAL_BATCH_STATUSES else None
        transition = connection.execute(
            text(
                """UPDATE reward_batches SET status = :status, completed_at = :completed_at
                WHERE batch_id = :batch_id AND status <> :status"""
            ),
            {"status": status, "completed_at": completed_at, "batch_id": batch_id},
        )
        if status in TERMINAL_BATCH_STATUSES and transition.rowcount == 1:
            _audit(
                connection,
                batch_id,
                f"batch.{status}",
                "批次全部发放成功" if status == "completed" else "批次完成，但存在失败明细",
                status=status,
            )
        return status


def process_reward_batch(batch_id: str) -> dict[str, object]:
    """Drain pending Outbox events for a batch and refresh its aggregate state."""
    initialize_database()
    outcomes: list[str] = []
    while item_id := _claim_reward_item(batch_id):
        try:
            outcomes.append(_deliver_reward_item(item_id))
        except Exception as error:
            _mark_claimed_item_failed(item_id, error)
            outcomes.append("failed")
    return {"batch_id": batch_id, "status": _refresh_batch_status(batch_id), "outcomes": outcomes}


def retry_reward_item(item_id: str, actor: str) -> str:
    """Reset one failed item to pending without creating another ledger identity."""
    with connect() as connection:
        item = connection.execute(
            text("SELECT * FROM reward_items WHERE item_id = :item_id"), {"item_id": item_id}
        ).mappings().first()
        if not item:
            raise LookupError("奖励明细不存在")
        if item["status"] != "failed":
            raise ValueError("只有失败明细可以重试")
        if int(item["attempt_count"]) >= MAX_DELIVERY_ATTEMPTS:
            raise ValueError("已达到最大重试次数")
        now = utc_now()
        connection.execute(
            text("UPDATE reward_items SET status = 'queued', updated_at = :now WHERE item_id = :item_id"),
            {"now": now, "item_id": item_id},
        )
        connection.execute(
            text("UPDATE reward_outbox_events SET status = 'pending' WHERE item_id = :item_id AND status = 'failed'"),
            {"item_id": item_id},
        )
        connection.execute(
            text("UPDATE reward_batches SET status = 'processing', completed_at = NULL WHERE batch_id = :batch_id"),
            {"batch_id": item["batch_id"]},
        )
        _audit(
            connection,
            str(item["batch_id"]),
            "item.retry_requested",
            "操作人员发起安全重试",
            actor=actor,
            item_id=item_id,
            previous_attempts=item["attempt_count"],
        )
        return str(item["batch_id"])


def get_reward_batch(batch_id: str) -> dict[str, object] | None:
    initialize_database()
    with connect() as connection:
        batch = connection.execute(
            text("SELECT * FROM reward_batches WHERE batch_id = :batch_id"), {"batch_id": batch_id}
        ).mappings().first()
        if not batch:
            return None
        items = connection.execute(
            text(
                """SELECT i.*, o.status AS outbox_status, a.balance
                FROM reward_items i
                JOIN reward_accounts a ON a.recipient_id = i.recipient_id
                LEFT JOIN reward_outbox_events o ON o.item_id = i.item_id
                WHERE i.batch_id = :batch_id ORDER BY i.created_at, i.item_id"""
            ),
            {"batch_id": batch_id},
        ).mappings().all()
        audits = connection.execute(
            text("SELECT * FROM reward_audit_events WHERE batch_id = :batch_id ORDER BY audit_id DESC"),
            {"batch_id": batch_id},
        ).mappings().all()
    return {
        **dict(batch),
        "items": [dict(item) for item in items],
        "audit_events": [
            {**dict(audit), "payload": json.loads(audit["payload_json"]), "payload_json": None} for audit in audits
        ],
    }


def wait_for_reward_batch(
    batch_id: str,
    *,
    timeout_seconds: float = 30.0,
    poll_interval: float = 0.25,
) -> dict[str, object]:
    """Wait for an asynchronously dispatched batch to reach a terminal state."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        batch = get_reward_batch(batch_id)
        if batch and batch["status"] in TERMINAL_BATCH_STATUSES:
            return batch
        time.sleep(poll_interval)
    raise TimeoutError(f"奖励批次 {batch_id} 在 {timeout_seconds}s 内未完成")


def list_reward_batches(limit: int = 30) -> list[dict[str, object]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            text(
                """SELECT b.*,
                COUNT(i.item_id) AS item_count,
                SUM(CASE WHEN i.status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded_count,
                SUM(CASE WHEN i.status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                COALESCE(SUM(i.reward_gems), 0) AS total_gems
                FROM reward_batches b LEFT JOIN reward_items i ON i.batch_id = b.batch_id
                GROUP BY b.batch_id, b.name, b.status, b.created_by, b.created_at, b.submitted_at, b.completed_at
                ORDER BY b.created_at DESC LIMIT :limit"""
            ),
            {"limit": limit},
        ).mappings().all()
    return [dict(row) for row in rows]


def list_reward_ledger(limit: int = 100) -> list[dict[str, object]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            text(
                """SELECT l.*, b.name AS batch_name, a.balance AS current_balance
                FROM reward_ledger l JOIN reward_batches b ON b.batch_id = l.batch_id
                JOIN reward_accounts a ON a.recipient_id = l.recipient_id
                ORDER BY l.entry_id DESC LIMIT :limit"""
            ),
            {"limit": limit},
        ).mappings().all()
    return [dict(row) for row in rows]


def list_reward_items(*, status: str | None = None, limit: int = 100) -> list[dict[str, object]]:
    """List operational delivery items, optionally filtered by status."""
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            text(
                """SELECT i.*, b.name AS batch_name, o.status AS outbox_status, a.balance
                FROM reward_items i JOIN reward_batches b ON b.batch_id = i.batch_id
                JOIN reward_accounts a ON a.recipient_id = i.recipient_id
                LEFT JOIN reward_outbox_events o ON o.item_id = i.item_id
                WHERE (:status IS NULL OR i.status = :status)
                ORDER BY i.updated_at DESC LIMIT :limit"""
            ),
            {"status": status, "limit": limit},
        ).mappings().all()
    return [dict(row) for row in rows]


def list_reward_audit_events(limit: int = 100) -> list[dict[str, object]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            text("SELECT * FROM reward_audit_events ORDER BY audit_id DESC LIMIT :limit"), {"limit": limit}
        ).mappings().all()
    return [
        {**dict(row), "payload": json.loads(row["payload_json"]), "payload_json": None}
        for row in rows
    ]


def reward_delivery_stats() -> dict[str, object]:
    initialize_database()
    with connect() as connection:
        batch_counts = connection.execute(
            text(
                """SELECT COUNT(*) AS total,
                SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) AS processing,
                SUM(CASE WHEN status = 'partial_failed' THEN 1 ELSE 0 END) AS attention
                FROM reward_batches"""
            )
        ).mappings().one()
        delivery = connection.execute(
            text(
                """SELECT COUNT(*) AS total,
                SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
                FROM reward_items WHERE status != 'draft'"""
            )
        ).mappings().one()
        total_gems = int(connection.execute(text("SELECT COALESCE(SUM(reward_gems), 0) FROM reward_ledger")).scalar_one())
    total = int(delivery["total"] or 0)
    succeeded = int(delivery["succeeded"] or 0)
    return {
        "batches": {
            "total": int(batch_counts["total"] or 0),
            "processing": int(batch_counts["processing"] or 0),
            "attention": int(batch_counts["attention"] or 0),
        },
        "deliveries": {
            "total": total,
            "succeeded": succeeded,
            "failed": int(delivery["failed"] or 0),
            "success_rate": round(succeeded / total * 100, 1) if total else 0,
        },
        "total_gems": total_gems,
    }
