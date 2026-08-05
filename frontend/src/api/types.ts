export type BatchStatus = 'draft' | 'processing' | 'completed' | 'partial_failed'
export type ItemStatus = 'draft' | 'queued' | 'processing' | 'succeeded' | 'failed'
export type FailureMode = 'none' | 'fail_once' | 'always_fail'

export interface RewardItemInput {
  recipient_id: string
  reward_gems: number
  failure_mode: FailureMode
}

export interface RewardItem extends RewardItemInput {
  item_id: string
  batch_id: string
  idempotency_key: string
  status: ItemStatus
  attempt_count: number
  last_error: string | null
  outbox_status: string | null
  balance: number
  created_at: string
  updated_at: string
  delivered_at: string | null
  batch_name?: string
}

export interface AuditEvent {
  audit_id: number
  batch_id: string
  item_id: string | null
  actor: string
  action: string
  message: string
  payload: Record<string, unknown>
  created_at: string
}

export interface RewardBatchSummary {
  batch_id: string
  name: string
  status: BatchStatus
  created_by: string
  created_at: string
  submitted_at: string | null
  completed_at: string | null
  item_count: number
  succeeded_count: number
  failed_count: number
  total_gems: number
}

export interface RewardBatch extends Omit<RewardBatchSummary, 'item_count' | 'succeeded_count' | 'failed_count' | 'total_gems'> {
  items: RewardItem[]
  audit_events: AuditEvent[]
}

export interface LedgerEntry {
  entry_id: number
  item_id: string
  batch_id: string
  batch_name: string
  recipient_id: string
  reward_gems: number
  current_balance: number
  created_at: string
}

export interface DeliveryStats {
  batches: { total: number; processing: number; attention: number }
  deliveries: { total: number; succeeded: number; failed: number; success_rate: number }
  total_gems: number
}

export interface Health {
  status: 'ok' | 'degraded'
  mode: 'sync' | 'async'
  dependencies: Record<string, 'healthy' | 'not_required' | 'unavailable'>
  database_backend: string
}
