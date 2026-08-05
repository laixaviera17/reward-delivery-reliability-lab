from __future__ import annotations

from typing import cast

from sqlalchemy import text

from .database import connect
from .reliability_scenarios import REWARD_GEMS


def wallet_snapshot(run_id: int, player_id: str) -> dict[str, object]:
    """Read the persisted state used by the lab's final wallet assertion."""
    with connect() as connection:
        orders = int(
            connection.execute(text("SELECT COUNT(*) FROM delivery_orders WHERE run_id = :run_id"), {"run_id": run_id}).scalar_one()
        )
        outbox = (
            connection.execute(
                text(
                    "SELECT COUNT(*) AS count, MAX(attempt_count) AS attempts "
                    "FROM delivery_outbox_events o JOIN delivery_orders d ON d.order_id = o.order_id "
                    "WHERE d.run_id = :run_id"
                ),
                {"run_id": run_id},
            )
            .mappings()
            .one()
        )
        outbox_statuses = (
            connection.execute(
                text(
                    "SELECT o.status FROM delivery_outbox_events o "
                    "JOIN delivery_orders d ON d.order_id = o.order_id WHERE d.run_id = :run_id"
                ),
                {"run_id": run_id},
            )
            .scalars()
            .all()
        )
        ledger = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM delivery_wallet_ledger l "
                    "JOIN delivery_orders d ON d.order_id = l.order_id WHERE d.run_id = :run_id"
                ),
                {"run_id": run_id},
            ).scalar_one()
        )
        balance = int(
            connection.execute(text("SELECT gem_balance FROM players WHERE player_id = :player_id"), {"player_id": player_id}).scalar_one()
        )
        statuses = connection.execute(text("SELECT status FROM delivery_orders WHERE run_id = :run_id"), {"run_id": run_id}).scalars().all()
    return {
        "orders": orders,
        "outbox_events": int(outbox["count"]),
        "outbox_statuses": list(outbox_statuses),
        "delivery_attempts": int(outbox["attempts"] or 0),
        "ledger_entries": ledger,
        "balance": balance,
        "delivery_statuses": list(statuses),
    }


def assert_wallet_invariants(run_id: int, player_id: str, scenario: str) -> dict[str, object]:
    """Check the one-order, one-ledger-entry, one-balance-effect invariant.

    A unique ledger entry per order means that balance must equal one reward, which
    exposes duplicate balance mutations caused by a missing idempotency boundary.
    This lab assertion does not model production retries, dead-letter queues,
    cross-server scheduling, configuration drift, or unknown online failures.
    """
    actual = wallet_snapshot(run_id, player_id)
    expected = {
        "orders": 1,
        "outbox_events": 1,
        "outbox_statuses": ["consumed"],
        "ledger_entries": 1,
        "balance": REWARD_GEMS,
        "delivery_statuses": ["delivered"],
    }
    if scenario in {"acknowledgement_loss", "guard_disabled_control"}:
        expected["delivery_attempts_at_least"] = 2
    else:
        expected["delivery_attempts_at_least"] = 1
    passed = (
        actual["orders"] == expected["orders"]
        and actual["outbox_events"] == expected["outbox_events"]
        and actual["outbox_statuses"] == expected["outbox_statuses"]
        and actual["ledger_entries"] == expected["ledger_entries"]
        and actual["balance"] == expected["balance"]
        and actual["delivery_statuses"] == expected["delivery_statuses"]
        and cast(int, actual["delivery_attempts"]) >= cast(int, expected["delivery_attempts_at_least"])
    )
    return {"passed": passed, "expected": expected, "actual": actual}
