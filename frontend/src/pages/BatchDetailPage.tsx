import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { RewardBatch } from '../api/types'
import { PageState } from '../components/PageState'
import { StatusBadge } from '../components/StatusBadge'

const formatDate = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'

export function BatchDetailPage({ batchId }: { batchId: string }) {
  const [batch, setBatch] = useState<RewardBatch | null>(null)
  const [error, setError] = useState('')
  const [acting, setActing] = useState('')
  const load = useCallback(() => api.batch(batchId).then(setBatch).catch((reason: Error) => setError(reason.message)), [batchId])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (batch?.status !== 'processing') return
    const timer = window.setInterval(() => void load(), 1000)
    return () => window.clearInterval(timer)
  }, [batch?.status, load])

  const act = async (key: string, operation: () => Promise<unknown>) => {
    setActing(key); setError('')
    try { await operation(); await load() } catch (reason) { setError(reason instanceof ApiError ? reason.message : '操作失败') } finally { setActing('') }
  }
  const submit = () => {
    if (window.confirm(`确认提交“${batch?.name ?? ''}”？提交后将创建 Outbox 事件并开始发放。`)) {
      void act('submit', () => api.submitBatch(batchId))
    }
  }
  const retry = (itemId: string) => {
    if (window.confirm('确认安全重试该明细？系统将复用原 item_id 和幂等键，不会创建第二笔奖励。')) {
      void act(itemId, () => api.retryItem(itemId))
    }
  }
  if (error && !batch) return <PageState kind="error">{error}</PageState>
  if (!batch) return <PageState>正在加载批次详情…</PageState>
  const succeeded = batch.items.filter(item => item.status === 'succeeded').length
  const failed = batch.items.filter(item => item.status === 'failed').length
  return <>
    <section className="page-heading"><div><span>BATCH DETAIL · {batch.batch_id}</span><h1>{batch.name}</h1><p>由 {batch.created_by} 创建 · {formatDate(batch.created_at)}</p></div><div className="heading-actions"><StatusBadge status={batch.status} />{batch.status === 'draft' && <button type="button" className="primary" disabled={!!acting} onClick={submit}>{acting === 'submit' ? '正在提交…' : '提交发放'}</button>}</div></section>
    {error && <div className="inline-error">{error}</div>}
    <section className="batch-progress"><div><span>总明细</span><strong>{batch.items.length}</strong></div><div><span>成功</span><strong className="green-text">{succeeded}</strong></div><div><span>失败</span><strong className="red-text">{failed}</strong></div><div><span>提交时间</span><strong className="date-value">{formatDate(batch.submitted_at)}</strong></div></section>
    <section className="panel"><div className="panel-head"><div><h2>发放明细</h2><p>幂等键、Outbox、重试次数和余额均可追溯</p></div></div><div className="table-wrap"><table><thead><tr><th>发放对象</th><th>奖励</th><th>业务状态</th><th>Outbox</th><th>尝试</th><th>当前余额</th><th /></tr></thead><tbody>{batch.items.map(item => <tr key={item.item_id}><td><strong>{item.recipient_id}</strong><small>{item.idempotency_key}</small>{item.last_error && <em className="row-error">{item.last_error}</em>}</td><td>{item.reward_gems.toLocaleString()}</td><td><StatusBadge status={item.status} /></td><td><StatusBadge status={item.outbox_status} /></td><td>{item.attempt_count}/3</td><td>{item.balance.toLocaleString()}</td><td>{item.status === 'failed' && <button type="button" className="table-link button-link" disabled={!!acting || item.attempt_count >= 3} onClick={() => retry(item.item_id)}>{acting === item.item_id ? '重试中…' : item.attempt_count >= 3 ? '已达上限' : '安全重试'}</button>}</td></tr>)}</tbody></table></div></section>
    <section className="panel audit-panel"><div className="panel-head"><div><h2>审计时间线</h2><p>创建、提交、失败、重试与入账均持久化记录</p></div></div><div className="audit-list">{batch.audit_events.map(event => <article key={event.audit_id}><i /><div><strong>{event.message}</strong><p>{event.action} · {event.actor}{event.item_id ? ` · ${event.item_id}` : ''}</p><details><summary>查看审计载荷</summary><pre>{JSON.stringify(event.payload, null, 2)}</pre></details></div><time>{formatDate(event.created_at)}</time></article>)}</div></section>
  </>
}
