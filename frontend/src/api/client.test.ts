import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, request } from './client'

afterEach(() => vi.restoreAllMocks())

describe('API client', () => {
  it('returns typed JSON for successful responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ value: 42 }), { status: 200 })))
    await expect(request<{ value: number }>('/api/test')).resolves.toEqual({ value: 42 })
  })

  it('uses the platform error contract', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'CONFLICT', message: '状态冲突' } }), { status: 409 })))
    await expect(request('/api/test')).rejects.toEqual(new ApiError('状态冲突', 409, 'CONFLICT'))
  })
})
