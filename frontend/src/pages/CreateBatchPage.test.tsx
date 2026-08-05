import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { CreateBatchPage } from './CreateBatchPage'

vi.mock('../api/client', () => ({
  api: { createBatch: vi.fn() },
  ApiError: class ApiError extends Error {},
}))

afterEach(() => vi.clearAllMocks())

describe('CreateBatchPage', () => {
  it('creates a draft with explicit recipients and failure simulation', async () => {
    vi.mocked(api.createBatch).mockResolvedValue({ batch_id: 'batch_test' } as never)
    render(<CreateBatchPage />)

    expect(screen.getByRole('heading', { name: '创建发放批次' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }))

    await waitFor(() => expect(api.createBatch).toHaveBeenCalledWith({
      name: '八月活动奖励',
      created_by: 'portfolio_admin',
      items: [
        { recipient_id: 'player_001', reward_gems: 100, failure_mode: 'none' },
        { recipient_id: 'player_002', reward_gems: 250, failure_mode: 'fail_once' },
      ],
    }))
    expect(window.location.hash).toBe('#batch/batch_test')
  })
})
