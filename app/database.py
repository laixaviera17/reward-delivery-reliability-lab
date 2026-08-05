from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Column, ForeignKey, Index, Integer, MetaData, String, Table, Text, create_engine, event
from sqlalchemy.engine import Connection, Engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "reliability_lab.db"
metadata = MetaData()

players = Table(
    "players",
    metadata,
    Column("player_id", String(64), primary_key=True),
    Column("nickname", String(128), nullable=False),
    Column("gem_balance", Integer, nullable=False, server_default="0"),
    Column("account_status", String(16), nullable=False, server_default="active"),
)
reliability_runs = Table(
    "reliability_runs",
    metadata,
    Column("run_id", Integer, primary_key=True, autoincrement=True),
    Column("scenario", String(64), nullable=False),
    Column("trigger", String(32), nullable=False),
    Column("status", String(16), nullable=False),
    Column("started_at", String(40), nullable=False),
    Column("completed_at", String(40)),
    Column("passed", Integer),
    Column("summary_json", Text),
    Column("error_message", Text),
)
delivery_orders = Table(
    "delivery_orders",
    metadata,
    Column("order_id", String(80), primary_key=True),
    Column("run_id", Integer, ForeignKey("reliability_runs.run_id"), nullable=False),
    Column("player_id", String(64), ForeignKey("players.player_id"), nullable=False),
    Column("idempotency_key", String(128), nullable=False, unique=True),
    Column("reward_gems", Integer, nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("delivered_at", String(40)),
)
delivery_outbox_events = Table(
    "delivery_outbox_events",
    metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("order_id", String(80), ForeignKey("delivery_orders.order_id"), nullable=False, unique=True),
    Column("status", String(16), nullable=False),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("created_at", String(40), nullable=False),
    Column("consumed_at", String(40)),
)
delivery_wallet_ledger = Table(
    "delivery_wallet_ledger",
    metadata,
    Column("entry_id", Integer, primary_key=True, autoincrement=True),
    Column("order_id", String(80), ForeignKey("delivery_orders.order_id"), nullable=False, unique=True),
    Column("player_id", String(64), ForeignKey("players.player_id"), nullable=False),
    Column("reward_gems", Integer, nullable=False),
    Column("created_at", String(40), nullable=False),
)
reliability_events = Table(
    "reliability_events",
    metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Integer, ForeignKey("reliability_runs.run_id"), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("message", String(255), nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("created_at", String(40), nullable=False),
)

# Minimal production-facing reward delivery domain.  The reliability lab tables
# above remain isolated so controlled failure experiments cannot pollute business
# batches, balances, or audit records.
reward_accounts = Table(
    "reward_accounts",
    metadata,
    Column("recipient_id", String(64), primary_key=True),
    Column("balance", Integer, nullable=False, server_default="0"),
    Column("updated_at", String(40), nullable=False),
)
reward_batches = Table(
    "reward_batches",
    metadata,
    Column("batch_id", String(64), primary_key=True),
    Column("name", String(128), nullable=False),
    Column("status", String(24), nullable=False),
    Column("created_by", String(64), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("submitted_at", String(40)),
    Column("completed_at", String(40)),
)
reward_items = Table(
    "reward_items",
    metadata,
    Column("item_id", String(64), primary_key=True),
    Column("batch_id", String(64), ForeignKey("reward_batches.batch_id"), nullable=False),
    Column("recipient_id", String(64), ForeignKey("reward_accounts.recipient_id"), nullable=False),
    Column("reward_gems", Integer, nullable=False),
    Column("idempotency_key", String(128), nullable=False, unique=True),
    Column("failure_mode", String(24), nullable=False, server_default="none"),
    Column("status", String(24), nullable=False),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("last_error", Text),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("delivered_at", String(40)),
)
reward_outbox_events = Table(
    "reward_outbox_events",
    metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("item_id", String(64), ForeignKey("reward_items.item_id"), nullable=False, unique=True),
    Column("status", String(24), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("consumed_at", String(40)),
)
reward_ledger = Table(
    "reward_ledger",
    metadata,
    Column("entry_id", Integer, primary_key=True, autoincrement=True),
    Column("item_id", String(64), ForeignKey("reward_items.item_id"), nullable=False, unique=True),
    Column("batch_id", String(64), ForeignKey("reward_batches.batch_id"), nullable=False),
    Column("recipient_id", String(64), ForeignKey("reward_accounts.recipient_id"), nullable=False),
    Column("reward_gems", Integer, nullable=False),
    Column("created_at", String(40), nullable=False),
)
reward_audit_events = Table(
    "reward_audit_events",
    metadata,
    Column("audit_id", Integer, primary_key=True, autoincrement=True),
    Column("batch_id", String(64), ForeignKey("reward_batches.batch_id"), nullable=False),
    Column("item_id", String(64), ForeignKey("reward_items.item_id")),
    Column("actor", String(64), nullable=False),
    Column("action", String(48), nullable=False),
    Column("message", String(255), nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("created_at", String(40), nullable=False),
)
Index("ix_reward_batches_status_created", reward_batches.c.status, reward_batches.c.created_at)
Index("ix_reward_items_batch_status", reward_items.c.batch_id, reward_items.c.status)
Index("ix_reward_ledger_recipient_created", reward_ledger.c.recipient_id, reward_ledger.c.created_at)
Index("ix_reward_audit_batch_created", reward_audit_events.c.batch_id, reward_audit_events.c.created_at)

_engine: Engine | None = None
_engine_url: str | None = None


def database_url() -> str:
    if url := os.getenv("DATABASE_URL"):
        return url
    path = Path(os.getenv("RELIABILITY_LAB_DB", DEFAULT_DB))
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+pysqlite:///{path}"


def get_engine() -> Engine:
    global _engine, _engine_url
    url = database_url()
    if _engine is not None and _engine_url == url:
        return _engine
    if _engine is not None:
        _engine.dispose()
    options: dict[str, object] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(url, **options)
    _engine_url = url
    if url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()

    return _engine


@contextmanager
def connect() -> Iterator[Connection]:
    connection = get_engine().connect()
    try:
        yield connection
        if connection.in_transaction():
            connection.commit()
    except BaseException:
        if connection.in_transaction():
            connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    metadata.create_all(get_engine())
