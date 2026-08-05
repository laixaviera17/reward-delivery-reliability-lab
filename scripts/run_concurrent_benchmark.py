from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from app.database import get_engine, initialize_database
from app.reliability import create_reliability_run, wait_for_reliability_run
from app.task_queue import dispatch_reliability_run, uses_async_worker


def percentile(values: list[float], fraction: float) -> float:
    """Return a deterministic nearest-rank percentile for benchmark reporting."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return round(ordered[index], 2)


def _run_once(timeout_seconds: float) -> dict[str, object]:
    started = time.perf_counter()
    run_id = create_reliability_run("concurrent_consume", trigger="benchmark")
    dispatch_reliability_run(run_id)
    report = wait_for_reliability_run(run_id, timeout_seconds=timeout_seconds)
    latency_ms = (time.perf_counter() - started) * 1000
    events = cast(list[dict[str, Any]], report.get("events") or [])
    claim_events = [event for event in events if event["kind"] == "claim"]
    poll_events = [event for event in events if event["kind"] == "poll"]
    poll_task_ids = {
        event["payload"].get("task_id")
        for event in poll_events
        if event.get("payload", {}).get("task_id")
    }
    summary = cast(dict[str, Any], report.get("summary") or {})
    actual = cast(dict[str, Any], summary.get("actual") or {})
    return {
        "run_id": run_id,
        "status": str(report["status"]),
        "latency_ms": round(latency_ms, 2),
        "claim_count": len(claim_events),
        "empty_claim_observed": any(event.get("payload", {}).get("order_id") is None for event in poll_events),
        "poll_task_count": len(poll_task_ids),
        "ledger_entries": actual.get("ledger_entries"),
        "balance": actual.get("balance"),
        "outbox_statuses": actual.get("outbox_statuses"),
    }


def build_summary(
    samples: list[dict[str, object]],
    *,
    concurrency: int,
    worker_concurrency: int,
    duration_seconds: float,
) -> dict[str, object]:
    latencies = [float(str(sample["latency_ms"])) for sample in samples]
    passed = sum(sample.get("status") == "passed" for sample in samples)
    single_claim = sum(sample.get("claim_count") == 1 for sample in samples)
    two_pollers = sum(sample.get("poll_task_count") == 2 for sample in samples)
    invariant_passed = sum(
        sample.get("ledger_entries") == 1
        and sample.get("balance") == 100
        and sample.get("outbox_statuses") == ["consumed"]
        for sample in samples
    )
    runs = len(samples)

    def rate(value: int) -> float:
        return round(value / runs * 100, 2) if runs else 0.0
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "database_backend": get_engine().dialect.name,
            "execution_mode": os.getenv("EXECUTION_MODE", "sync"),
            "submit_concurrency": concurrency,
            "worker_concurrency": worker_concurrency,
        },
        "workload": {
            "scenario": "concurrent_consume",
            "runs": runs,
            "outbox_pollers_per_run": 2,
            "artificial_sleep": False,
        },
        "results": {
            "passed": passed,
            "failed": runs - passed,
            "wallet_invariant_pass_rate": rate(invariant_passed),
            "single_claim_rate": rate(single_claim),
            "two_independent_poller_rate": rate(two_pollers),
            "duration_seconds": round(duration_seconds, 3),
            "throughput_runs_per_second": round(runs / duration_seconds, 2) if duration_seconds else 0.0,
            "latency_ms": {
                "min": round(min(latencies), 2) if latencies else 0.0,
                "p50": percentile(latencies, 0.50),
                "p95": percentile(latencies, 0.95),
                "p99": percentile(latencies, 0.99),
                "max": round(max(latencies), 2) if latencies else 0.0,
            },
        },
        "samples": sorted(samples, key=lambda sample: int(str(sample.get("run_id", 0)))),
    }


def markdown_report(summary: dict[str, object]) -> str:
    environment = cast(dict[str, object], summary["environment"])
    workload = cast(dict[str, object], summary["workload"])
    results = cast(dict[str, object], summary["results"])
    latency = cast(dict[str, object], results["latency_ms"])
    return f"""# Concurrent Delivery Benchmark

Generated: `{summary['generated_at']}`

## Scope

This benchmark measures the repository's `concurrent_consume` correctness path
under concurrent submissions. Each run creates one reward order and schedules
two independent Celery Outbox pollers competing for the same pending event. It
is a portfolio-scale correctness/load measurement, not a production capacity
guarantee.

## Environment

| Item | Value |
| --- | --- |
| Database | {environment['database_backend']} |
| Execution mode | {environment['execution_mode']} |
| Python | {environment['python']} |
| Submit concurrency | {environment['submit_concurrency']} |
| Celery worker concurrency | {environment['worker_concurrency']} |
| Runs | {workload['runs']} |
| Pollers per run | {workload['outbox_pollers_per_run']} |
| Artificial sleep | {workload['artificial_sleep']} |

## Results

| Metric | Result |
| --- | ---: |
| Passed / failed | {results['passed']} / {results['failed']} |
| Wallet invariant pass rate | {results['wallet_invariant_pass_rate']}% |
| Exactly one claim rate | {results['single_claim_rate']}% |
| Two independent poller IDs observed | {results['two_independent_poller_rate']}% |
| Throughput | {results['throughput_runs_per_second']} runs/s |
| Total duration | {results['duration_seconds']} s |
| Latency min / P50 / P95 / P99 / max | {latency['min']} / {latency['p50']} / {latency['p95']} / {latency['p99']} / {latency['max']} ms |

## Pass criteria

- Every run finishes with status `passed`.
- Every run has one ledger entry, balance `100`, and Outbox status `consumed`.
- Exactly one of the two competing pollers claims the event.
- Two independent Celery task IDs are observable per run.

Raw samples are stored in the adjacent JSON report. Results depend on local
Docker resources and must not be presented as production capacity.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Concurrent Celery/Outbox correctness and latency benchmark.")
    parser.add_argument("--runs", type=int, default=40)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--worker-concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--json-output", type=Path, default=Path("docs/performance/concurrent-benchmark.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("docs/performance/concurrent-benchmark.md"))
    args = parser.parse_args()

    if args.runs < 1 or args.concurrency < 1:
        parser.error("--runs and --concurrency must be positive")
    if not uses_async_worker():
        print("Set EXECUTION_MODE=celery before running the benchmark.", file=sys.stderr)
        return 2
    if not os.getenv("DATABASE_URL", "").startswith("mysql"):
        print("Benchmark requires DATABASE_URL pointing to MySQL.", file=sys.stderr)
        return 2

    initialize_database()
    started = time.perf_counter()
    samples: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(_run_once, args.timeout) for _ in range(args.runs)]
        for future in as_completed(futures):
            try:
                samples.append(future.result())
            except Exception as error:
                samples.append({"run_id": 0, "status": "failed", "latency_ms": 0.0, "error": f"{type(error).__name__}: {error}"})
    duration = time.perf_counter() - started
    summary = build_summary(
        samples,
        concurrency=args.concurrency,
        worker_concurrency=args.worker_concurrency,
        duration_seconds=duration,
    )

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(markdown_report(summary), encoding="utf-8")
    print(json.dumps(summary["results"], ensure_ascii=False, indent=2))
    results = cast(dict[str, object], summary["results"])
    return 0 if results["failed"] == 0 and results["wallet_invariant_pass_rate"] == 100.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
