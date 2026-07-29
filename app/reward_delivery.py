from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .database import connect, initialize_database
from .outbox import claim_pending_outbox_order, release_outbox_claim
from .reliability_events import record_reliability_event, utc_now
from .reliability_scenarios import REWARD_GEMS


def create_experiment_player(run_id: int) -> str:
    player_id = f"reliability_{run_id}_player"
    with connect() as connection:
        connection.execute(
            text("""INSERT INTO players (player_id, nickname, gem_balance, account_status)
                VALUES (:player_id, :nickname, 0, 'active')"""),
            {"player_id": player_id, "nickname": f"可靠性实验玩家-{run_id}"},
        )
    return player_id


def request_reward(run_id: int, player_id: str, idempotency_key: str) -> tuple[str, bool]:
    """Persist the business order and its Outbox event in one database transaction."""
    with connect() as connection:
        existing = connection.execute(
            text("SELECT order_id FROM delivery_orders WHERE idempotency_key = :key"),
            {"key": idempotency_key},
        ).scalar_one_or_none()
        if existing:
            order_id = str(existing)
            duplicate = True
        else:
            order_id = f"order_{run_id}_{uuid.uuid4().hex[:10]}"
            connection.execute(
                text("""INSERT INTO delivery_orders
                    (order_id, run_id, player_id, idempotency_key, reward_gems, status, created_at)
                    VALUES (:order_id, :run_id, :player_id, :idempotency_key, :reward_gems, 'pending', :created_at)"""),
                {"order_id": order_id, "run_id": run_id, "player_id": player_id, "idempotency_key": idempotency_key, "reward_gems": REWARD_GEMS, "created_at": utc_now()},
            )
            connection.execute(
                text("""INSERT INTO delivery_outbox_events (order_id, status, attempt_count, created_at)
                    VALUES (:order_id, 'pending', 0, :created_at)"""),
                {"order_id": order_id, "created_at": utc_now()},
            )
            duplicate = False
    record_reliability_event(run_id, "request", "重复请求命中已有订单" if duplicate else "订单与 Outbox 事件在同一事务中创建", order_id=order_id, idempotency_key=idempotency_key, duplicate=duplicate)
    return order_id, duplicate


def _complete_delivery(connection, order_id: str) -> None:
    now = utc_now()
    connection.execute(
        text("UPDATE delivery_orders SET status = 'delivered', delivered_at = :now WHERE order_id = :order_id"),
        {"now": now, "order_id": order_id},
    )
    connection.execute(
        text("UPDATE delivery_outbox_events SET status = 'consumed', consumed_at = :now WHERE order_id = :order_id"),
        {"now": now, "order_id": order_id},
    )


def deliver_reward_once(run_id: int, order_id: str, *, lose_acknowledgement: bool = False, task_id: str | None = None) -> str:
    """Apply one delivery attempt; the unique ledger row remains the consumer idempotency boundary."""
    record_reliability_event(run_id, "consume", "消费者开始处理 Outbox 事件", order_id=order_id, lose_acknowledgement=lose_acknowledgement, task_id=task_id)
    try:
        with connect() as connection:
            order = connection.execute(
                text("SELECT player_id, reward_gems FROM delivery_orders WHERE order_id = :order_id"),
                {"order_id": order_id},
            ).mappings().one()
            ledger_exists = connection.execute(
                text("SELECT entry_id FROM delivery_wallet_ledger WHERE order_id = :order_id"),
                {"order_id": order_id},
            ).scalar_one_or_none()
            if ledger_exists:
                _complete_delivery(connection, order_id)
                outcome = "duplicate_consumer"
            else:
                connection.execute(
                    text("""INSERT INTO delivery_wallet_ledger (order_id, player_id, reward_gems, created_at)
                        VALUES (:order_id, :player_id, :reward_gems, :created_at)"""),
                    {"order_id": order_id, "player_id": order["player_id"], "reward_gems": order["reward_gems"], "created_at": utc_now()},
                )
                connection.execute(
                    text("UPDATE players SET gem_balance = gem_balance + :reward_gems WHERE player_id = :player_id"),
                    {"reward_gems": order["reward_gems"], "player_id": order["player_id"]},
                )
                if lose_acknowledgement:
                    outcome = "acknowledgement_lost"
                else:
                    _complete_delivery(connection, order_id)
                    outcome = "effect_applied"
    except IntegrityError:
        with connect() as connection:
            _complete_delivery(connection, order_id)
        outcome = "duplicate_consumer"
    except Exception:
        release_outbox_claim(order_id)
        raise
    if outcome == "acknowledgement_lost":
        release_outbox_claim(order_id)
        record_reliability_event(run_id, "retry", "账本已提交，但模拟确认丢失；Outbox 仍为 pending 并等待再次轮询", order_id=order_id)
    elif outcome == "duplicate_consumer":
        record_reliability_event(run_id, "dedupe", "检测到已存在账本流水，跳过余额变更并完成事件", order_id=order_id)
    else:
        record_reliability_event(run_id, "effect", "账本流水与余额变更已提交，事件标记为已消费", order_id=order_id)
    return outcome


def poll_outbox_event(run_id: int, *, lose_acknowledgement: bool = False, task_id: str | None = None) -> str:
    """Claim then consume one event, so concurrent pollers cannot both own it."""
    order_id = claim_pending_outbox_order(run_id)
    if order_id is None:
        record_reliability_event(run_id, "poll", "Outbox 轮询未发现可领取的待消费事件", task_id=task_id)
        return "no_pending_event"
    record_reliability_event(run_id, "poll", "Outbox 轮询发现并领取待消费事件", order_id=order_id, pending_count=1, task_id=task_id)
    record_reliability_event(run_id, "claim", "Outbox 轮询通过条件更新领取待消费事件", order_id=order_id, task_id=task_id)
    return deliver_reward_once(run_id, order_id, lose_acknowledgement=lose_acknowledgement, task_id=task_id)


def deliver_without_ledger_guard(run_id: int, order_id: str) -> None:
    """Execute the controlled negative path that mutates balance without a ledger entry."""
    record_reliability_event(run_id, "control", "对照消费者跳过账本守卫并直接执行余额变更", order_id=order_id)
    with connect() as connection:
        order = connection.execute(
            text("SELECT player_id, reward_gems FROM delivery_orders WHERE order_id = :order_id"),
            {"order_id": order_id},
        ).mappings().one()
        connection.execute(
            text("UPDATE delivery_outbox_events SET attempt_count = attempt_count + 1 WHERE order_id = :order_id"),
            {"order_id": order_id},
        )
        connection.execute(
            text("UPDATE players SET gem_balance = gem_balance + :reward_gems WHERE player_id = :player_id"),
            {"reward_gems": order["reward_gems"], "player_id": order["player_id"]},
        )
        _complete_delivery(connection, order_id)
    record_reliability_event(run_id, "control", "对照消费者完成一次未受账本保护的余额变更", order_id=order_id)
