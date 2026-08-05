import type {
  AuditEvent,
  DeliveryStats,
  Health,
  LedgerEntry,
  RewardBatch,
  RewardBatchSummary,
  RewardItem,
  RewardItemInput,
} from './types'

const API = '/api/v1'

interface ApiErrorBody {
  error?: { code?: string; message?: string }
  detail?: string
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code = 'REQUEST_ERROR',
  ) {
    super(message)
  }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 10_000)
  try {
    const response = await fetch(path, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options.headers },
      signal: options.signal ?? controller.signal,
    })
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody & T
    if (!response.ok) {
      throw new ApiError(body.error?.message ?? body.detail ?? '请求失败', response.status, body.error?.code)
    }
    return body
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError('请求超时，请检查服务状态', 408, 'TIMEOUT')
    }
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
}

export const api = {
  health: () => request<Health>('/health'),
  stats: () => request<DeliveryStats>(`${API}/reward-stats`),
  batches: () => request<{ items: RewardBatchSummary[] }>(`${API}/reward-batches`),
  batch: (batchId: string) => request<RewardBatch>(`${API}/reward-batches/${batchId}`),
  createBatch: (body: { name: string; created_by: string; items: RewardItemInput[] }) =>
    request<RewardBatch>(`${API}/reward-batches`, { method: 'POST', body: JSON.stringify(body) }),
  submitBatch: (batchId: string) =>
    request(`${API}/reward-batches/${batchId}/submit`, {
      method: 'POST',
      body: JSON.stringify({ actor: 'portfolio_admin' }),
    }),
  retryItem: (itemId: string) =>
    request(`${API}/reward-items/${itemId}/retry`, {
      method: 'POST',
      body: JSON.stringify({ actor: 'portfolio_reviewer' }),
    }),
  failedItems: () => request<{ items: RewardItem[] }>(`${API}/reward-items?status=failed`),
  ledger: () => request<{ items: LedgerEntry[] }>(`${API}/reward-ledger`),
  audits: () => request<{ items: AuditEvent[] }>(`${API}/reward-audit-events`),
}
