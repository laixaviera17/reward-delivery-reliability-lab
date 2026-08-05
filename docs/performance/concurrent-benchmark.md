# Concurrent Delivery Benchmark

Generated: `2026-08-04T09:31:25.356001+00:00`

## Scope

This benchmark measures the repository's `concurrent_consume` correctness path
under concurrent submissions. Each run creates one reward order and schedules
two independent Celery Outbox pollers competing for the same pending event. It
is a portfolio-scale correctness/load measurement, not a production capacity
guarantee.

## Environment

| Item | Value |
| --- | --- |
| Database | mysql |
| Execution mode | celery |
| Python | 3.14.4 |
| Submit concurrency | 8 |
| Celery worker concurrency | 4 |
| Runs | 40 |
| Pollers per run | 2 |
| Artificial sleep | False |

## Results

| Metric | Result |
| --- | ---: |
| Passed / failed | 40 / 0 |
| Wallet invariant pass rate | 100.0% |
| Exactly one claim rate | 100.0% |
| Two independent poller IDs observed | 100.0% |
| Throughput | 12.36 runs/s |
| Total duration | 3.235 s |
| Latency min / P50 / P95 / P99 / max | 602.43 / 625.42 / 762.87 / 767.82 / 767.82 ms |

## Pass criteria

- Every run finishes with status `passed`.
- Every run has one ledger entry, balance `100`, and Outbox status `consumed`.
- Exactly one of the two competing pollers claims the event.
- Two independent Celery task IDs are observable per run.

Raw samples are stored in the adjacent JSON report. Results depend on local
Docker resources and must not be presented as production capacity.
