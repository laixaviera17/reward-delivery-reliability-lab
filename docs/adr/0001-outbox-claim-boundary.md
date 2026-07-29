# ADR 0001: Conditional Outbox claim before reward delivery

## Context

Two pollers can observe the same pending Outbox event. A unique wallet-ledger
row still protects the final balance, but it does not make event ownership
explicit and causes unnecessary duplicate consumer work.

## Decision

Before delivery, a poller changes one candidate event from `pending` to
`processing` with `UPDATE ... WHERE status = 'pending'`. Only the poller whose
conditional update affects one row owns the event. An acknowledgement-loss
scenario returns `processing` to `pending` after the ledger effect commits, so
the retry proves that the ledger remains the side-effect idempotency boundary.

## Consequences

This reduces duplicate consumer work in the lab and makes claim ownership
observable in the event timeline. It is deliberately not a production queue:
there is no lease expiry, dead-letter queue, retry backoff, or worker crash
recovery policy.
