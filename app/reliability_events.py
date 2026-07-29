from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text

from .database import connect


def utc_now() -> str:
    """Return the timestamp format stored by the lab's existing tables."""
    return datetime.now(UTC).isoformat()


def record_reliability_event(run_id: int, kind: str, message: str, **payload: object) -> None:
    """Append an event to the existing run timeline without changing its schema."""
    with connect() as connection:
        connection.execute(
            text("""INSERT INTO reliability_events (run_id, kind, message, payload_json, created_at)
                VALUES (:run_id, :kind, :message, :payload_json, :created_at)"""),
            {
                "run_id": run_id,
                "kind": kind,
                "message": message,
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "created_at": utc_now(),
            },
        )
