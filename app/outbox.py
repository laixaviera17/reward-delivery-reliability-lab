from __future__ import annotations

from sqlalchemy import text

from .database import connect, initialize_database


def list_pending_outbox_orders(run_id: int) -> list[str]:
    """Return pending outbox order ids for a reliability run.

    In this lab, experiment runners and Celery poller tasks call this query.
    There is no separate production sweeper, dead-letter queue, or timed retry
    policy — those are intentionally out of scope.
    """
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            text(
                """SELECT o.order_id FROM delivery_outbox_events e
                JOIN delivery_orders o ON o.order_id = e.order_id
                WHERE o.run_id = :run_id AND e.status = 'pending'
                ORDER BY e.event_id"""
            ),
            {"run_id": run_id},
        ).scalars().all()
    return [str(order_id) for order_id in rows]


def claim_pending_outbox_order(run_id: int) -> str | None:
    """Atomically claim one pending event for a run.

    The initial read only identifies a candidate.  The conditional status update
    is the ownership boundary: competing pollers can select the same order, but
    only one can move it from ``pending`` to ``processing``.  This is a small
    lab-level claim protocol, not a production lease, timeout, or dead-letter
    implementation.
    """
    initialize_database()
    with connect() as connection:
        candidate = connection.execute(
            text(
                """SELECT o.order_id FROM delivery_outbox_events e
                JOIN delivery_orders o ON o.order_id = e.order_id
                WHERE o.run_id = :run_id AND e.status = 'pending'
                ORDER BY e.event_id LIMIT 1"""
            ),
            {"run_id": run_id},
        ).scalar_one_or_none()
        if candidate is None:
            return None
        order_id = str(candidate)
        result = connection.execute(
            text(
                """UPDATE delivery_outbox_events
                SET status = 'processing', attempt_count = attempt_count + 1
                WHERE order_id = :order_id AND status = 'pending'"""
            ),
            {"order_id": order_id},
        )
        return order_id if result.rowcount == 1 else None


def release_outbox_claim(order_id: str) -> None:
    """Make an unacknowledged lab event retryable without changing its effect."""
    with connect() as connection:
        connection.execute(
            text("UPDATE delivery_outbox_events SET status = 'pending' WHERE order_id = :order_id AND status = 'processing'"),
            {"order_id": order_id},
        )
