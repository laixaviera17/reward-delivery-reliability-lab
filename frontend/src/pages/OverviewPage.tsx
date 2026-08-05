import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DeliveryStats, RewardBatchSummary } from '../api/types'
import { PageState } from '../components/PageState'
import { StatCard } from '../components/StatCard'
import { StatusBadge } from '../components/StatusBadge'

export function OverviewPage() {
  const [stats, setStats] = useState<DeliveryStats | null>(null)
  const [batches, setBatches] = useState<RewardBatchSummary[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api.stats(), api.batches()])
      .then(([nextStats, nextBatches]) => { setStats(nextStats); setBatches(nextBatches.items.slice(0, 5)) })
      .catch((reason: Error) => setError(reason.message))
  }, [])

  if (error) return <PageState kind="error">{error}</PageState>
  if (!stats) return <PageState>正在加载业务指标…</PageState>
  return <>
    <section className="page-heading"><div><span>DELIVERY OVERVIEW</span><h1>运行概览</h1><p>查看批次状态、成功率和已入账奖励。所有指标来自真实账本。</p></div><a className="primary" href="#new">创建发放批次</a></section>
    <section className="stats-grid">
      <StatCard label="发放批次" value={stats.batches.total} note={`${stats.batches.processing} 个处理中`} />
      <StatCard label="成功率" value={`${stats.deliveries.success_rate}%`} note={`${stats.deliveries.succeeded}/${stats.deliveries.total} 条明细`} tone="green" />
      <StatCard label="需要关注" value={stats.batches.attention} note={`${stats.deliveries.failed} 条失败明细`} tone="amber" />
      <StatCard label="已入账宝石" value={stats.total_gems.toLocaleString()} note="以唯一账本为统计口径" tone="violet" />
    </section>
    <section className="panel">
      <div className="panel-head"><div><h2>最近发放批次</h2><p>从草稿、处理到最终完成的业务状态</p></div><a href="#batches">查看全部</a></div>
      {batches.length === 0 ? <PageState>尚未创建发放批次。</PageState> : <div className="table-wrap"><table><thead><tr><th>批次</th><th>状态</th><th>明细</th><th>成功/失败</th><th>奖励总量</th><th /></tr></thead><tbody>{batches.map(batch => <tr key={batch.batch_id}><td><strong>{batch.name}</strong><small>{batch.batch_id}</small></td><td><StatusBadge status={batch.status} /></td><td>{batch.item_count}</td><td>{batch.succeeded_count} / {batch.failed_count}</td><td>{batch.total_gems.toLocaleString()}</td><td><a className="table-link" href={`#batch/${batch.batch_id}`}>详情</a></td></tr>)}</tbody></table></div>}
    </section>
  </>
}
