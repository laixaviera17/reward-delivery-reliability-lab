#!/usr/bin/env python3
"""Wait for the configured Celery worker instead of relying on a fixed sleep."""

from __future__ import annotations

import sys
import time

from app.task_queue import celery_app


def main() -> int:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if celery_app.control.ping(timeout=1.0):
            return 0
        time.sleep(0.5)
    print("Celery worker did not respond within 30 seconds.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
