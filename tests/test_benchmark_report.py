from scripts.run_concurrent_benchmark import build_summary, markdown_report, percentile


def test_percentile_and_benchmark_summary_are_deterministic():
    samples = [
        {
            "run_id": index,
            "status": "passed",
            "latency_ms": float(index * 10),
            "claim_count": 1,
            "poll_task_count": 2,
            "ledger_entries": 1,
            "balance": 100,
            "outbox_statuses": ["consumed"],
        }
        for index in range(1, 5)
    ]

    assert percentile([10.0, 20.0, 30.0, 40.0], 0.5) == 30.0
    summary = build_summary(samples, concurrency=2, worker_concurrency=4, duration_seconds=2.0)
    assert summary["results"]["wallet_invariant_pass_rate"] == 100.0
    assert summary["results"]["single_claim_rate"] == 100.0
    assert summary["results"]["throughput_runs_per_second"] == 2.0
    assert "portfolio-scale correctness/load measurement" in markdown_report(summary)
