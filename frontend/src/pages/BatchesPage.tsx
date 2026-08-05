import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { RewardBatchSummary } from '../api/types'
import { PageState } from '../components/PageState'
import { StatusBadge } from '../components/StatusBadge'

export function BatchesPage() {
  const [items, setItems] = useState<RewardBatchSummary[] | null>(null)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    api.batches()
      .then(data => setItems(data.items))
      .catch((reason: Error) => setError(reason.message))
  }, [])
  const filtered = items?.filter(item => `${item.name}${item.batch_id}${item.status}`.toLowerCase().includes(query.toLowerCase())) ?? []
  return <>
    <section className="page-heading"><div><span>BATCH OPERATIONS</span><h1>发放批次</h1><p>查询批次进度并进入失败恢复流程。</p></div><a className="primary" href="#new">新建批次</a></section>
    <section className="panel">
      <div className="toolbar"><input aria-label="搜索批次" placeholder="搜索名称、ID 或状态" value={query} onChange={event => setQuery(event.target.value)} /><span>{filtered.length} 个批次</span></div>
      {error ? <PageState kind="error">{error}</PageState> : items === null ? <PageState>正在加载批次…</PageState> : filtered.length === 0 ? <PageState>没有匹配的批次。</PageState> : <div className="table-wrap"><table><thead><tr><th>批次</th><th>状态</th><th>创建人</th><th>成功</th><th>失败</th><th>总奖励</th><th /></tr></thead><tbody>{filtered.map(batch => <tr key={batch.batch_id}><td><strong>{batch.name}</strong><small>{batch.batch_id}</small></td><td><StatusBadge status={batch.status} /></td><td>{batch.created_by}</td><td>{batch.succeeded_count}/{batch.item_count}</td><td>{batch.failed_count}</td><td>{batch.total_gems.toLocaleString()}</td><td><a className="table-link" href={`#batch/${batch.batch_id}`}>打开</a></td></tr>)}</tbody></table></div>}
    </section>
  </>
}
