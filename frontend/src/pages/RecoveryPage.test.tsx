import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { RecoveryPage } from './RecoveryPage'

vi.mock('../api/client', () => ({
  api: { failedItems: vi.fn(), retryItem: vi.fn() },
  ApiError: class ApiError extends Error {},
}))

afterEach(() => vi.restoreAllMocks())

describe('RecoveryPage', () => {
  it('requires confirmation and dispatches a safe retry', async () => {
    vi.mocked(api.failedItems).mockResolvedValue({
      items: [{
        item_id: 'item_1', batch_id: 'batch_1', batch_name: '活动奖励', recipient_id: 'player_1',
        reward_gems: 100, failure_mode: 'fail_once', status: 'failed', attempt_count: 1,
        last_error: '渠道超时', outbox_status: 'failed', balance: 0, idempotency_key: 'batch_1:player_1',
        created_at: '2026-08-04T00:00:00Z', updated_at: '2026-08-04T00:00:00Z', delivered_at: null,
      }],
    })
    vi.mocked(api.retryItem).mockResolvedValue({})
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<RecoveryPage />)

    const button = await screen.findByRole('button', { name: '安全重试' })
    await userEvent.click(button)

    await waitFor(() => expect(api.retryItem).toHaveBeenCalledWith('item_1'))
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('原幂等键将保持不变'))
  })
})
