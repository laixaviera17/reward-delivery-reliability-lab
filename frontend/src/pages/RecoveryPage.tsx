import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { RewardItem } from '../api/types'
import { PageState } from '../components/PageState'
import { StatusBadge } from '../components/StatusBadge'

export function RecoveryPage() {
  const [items, setItems] = useState<RewardItem[] | null>(null)
  const [error, setError] = useState('')
  const [acting, setActing] = useState('')
  const load = useCallback(() => api.failedItems()
    .then(data => { setItems(data.items); setError('') })
    .catch((reason: Error) => setError(reason.message)), [])
  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 2_000)
    return () => window.clearInterval(timer)
  }, [load])

  const retry = async (item: RewardItem) => {
    if (!window.confirm(`确认重试 ${item.recipient_id} 的 ${item.reward_gems} 宝石奖励？原幂等键将保持不变。`)) return
    setActing(item.item_id); setError('')
    try { await api.retryItem(item.item_id); await load() }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : '重试失败') }
    finally { setActing('') }
  }

  return <>
    <section className="page-heading"><div><span>FAILURE RECOVERY</span><h1>失败恢复</h1><p>集中处理失败明细。安全重试复用原 item_id、Outbox 和唯一账本身份。</p></div></section>
    {error && <div className="inline-error">{error}</div>}
    <section className="panel">
      <div className="panel-head"><div><h2>待人工处理</h2><p>最多尝试 3 次；超过阈值后停止自动操作</p></div><span>{items?.length ?? 0} 条</span></div>
      {items === null ? <PageState>正在加载失败任务…</PageState> : items.length === 0 ? <PageState>当前没有需要人工处理的失败任务。</PageState> : <div className="table-wrap"><table><thead><tr><th>批次/对象</th><th>奖励</th><th>状态</th><th>Outbox</th><th>错误</th><th>尝试</th><th /></tr></thead><tbody>{items.map(item => <tr key={item.item_id}><td><strong>{item.batch_name}</strong><small>{item.recipient_id} · {item.item_id}</small></td><td>{item.reward_gems.toLocaleString()}</td><td><StatusBadge status={item.status} /></td><td><StatusBadge status={item.outbox_status} /></td><td><em className="row-error">{item.last_error}</em></td><td>{item.attempt_count}/3</td><td><button type="button" className="table-link button-link" disabled={!!acting || item.attempt_count >= 3} onClick={() => void retry(item)}>{acting === item.item_id ? '重试中…' : item.attempt_count >= 3 ? '已达上限' : '安全重试'}</button></td></tr>)}</tbody></table></div>}
    </section>
  </>
}
