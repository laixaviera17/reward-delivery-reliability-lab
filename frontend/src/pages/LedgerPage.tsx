import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AuditEvent, LedgerEntry } from '../api/types'
import { PageState } from '../components/PageState'

const formatDate = (value: string) => new Date(value).toLocaleString('zh-CN', { hour12: false })

export function LedgerPage() {
  const [ledger, setLedger] = useState<LedgerEntry[] | null>(null)
  const [audits, setAudits] = useState<AuditEvent[]>([])
  const [error, setError] = useState('')
  useEffect(() => {
    Promise.all([api.ledger(), api.audits()])
      .then(([entries, events]) => { setLedger(entries.items); setAudits(events.items) })
      .catch((reason: Error) => setError(reason.message))
  }, [])
  if (error) return <PageState kind="error">{error}</PageState>
  return <>
    <section className="page-heading"><div><span>LEDGER & AUDIT</span><h1>账本与审计</h1><p>唯一账本是余额副作用边界；审计记录解释每一次人工和系统操作。</p></div></section>
    <section className="split-grid">
      <div className="panel"><div className="panel-head"><div><h2>奖励账本</h2><p>每个 item_id 最多一条记录</p></div><span>{ledger?.length ?? 0} 条</span></div>{ledger === null ? <PageState>正在加载账本…</PageState> : ledger.length === 0 ? <PageState>尚无已入账奖励。</PageState> : <div className="ledger-list">{ledger.map(entry => <article key={entry.entry_id}><div><strong>+{entry.reward_gems.toLocaleString()} 宝石</strong><span>{entry.recipient_id}</span></div><p>{entry.batch_name}<small>{entry.item_id}</small></p><time>{formatDate(entry.created_at)}<small>余额 {entry.current_balance}</small></time></article>)}</div>}</div>
      <div className="panel"><div className="panel-head"><div><h2>全局审计流</h2><p>按时间倒序展示最近操作</p></div><span>{audits.length} 条</span></div><div className="audit-list compact">{audits.length === 0 ? <PageState>尚无审计事件。</PageState> : audits.map(event => <article key={event.audit_id}><i /><div><strong>{event.message}</strong><p>{event.action} · {event.actor}</p><details><summary>载荷</summary><pre>{JSON.stringify(event.payload, null, 2)}</pre></details></div><time>{formatDate(event.created_at)}</time></article>)}</div></div>
    </section>
  </>
}
