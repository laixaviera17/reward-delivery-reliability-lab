import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { RewardItemInput } from '../api/types'

const blankItem = (): RewardItemInput => ({ recipient_id: '', reward_gems: 100, failure_mode: 'none' })

export function CreateBatchPage() {
  const [name, setName] = useState('八月活动奖励')
  const [items, setItems] = useState<RewardItemInput[]>([
    { recipient_id: 'player_001', reward_gems: 100, failure_mode: 'none' },
    { recipient_id: 'player_002', reward_gems: 250, failure_mode: 'fail_once' },
  ])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const update = (index: number, patch: Partial<RewardItemInput>) => setItems(current => current.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item))
  const save = async () => {
    setSaving(true); setError('')
    try {
      const batch = await api.createBatch({ name, created_by: 'portfolio_admin', items })
      window.location.hash = `batch/${batch.batch_id}`
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : '创建失败')
    } finally { setSaving(false) }
  }

  return <>
    <section className="page-heading"><div><span>NEW DELIVERY BATCH</span><h1>创建发放批次</h1><p>批次先保存为草稿，确认后才创建 Outbox 事件并执行发放。</p></div></section>
    <section className="panel form-panel">
      <label className="field"><span>批次名称</span><input value={name} onChange={event => setName(event.target.value)} maxLength={128} /></label>
      <div className="panel-head"><div><h2>奖励明细</h2><p>`fail_once` 用于演示下游失败后的人工安全重试。</p></div><button className="secondary" onClick={() => setItems(current => [...current, blankItem()])}>添加明细</button></div>
      <div className="item-editor"><div className="editor-row header"><span>发放对象</span><span>宝石数量</span><span>故障模式</span><span /></div>{items.map((item, index) => <div className="editor-row" key={index}><input aria-label={`第 ${index + 1} 条发放对象`} value={item.recipient_id} onChange={event => update(index, { recipient_id: event.target.value })} /><input aria-label={`第 ${index + 1} 条奖励数量`} type="number" min="1" max="1000000" value={item.reward_gems} onChange={event => update(index, { reward_gems: Number(event.target.value) })} /><select aria-label={`第 ${index + 1} 条故障模式`} value={item.failure_mode} onChange={event => update(index, { failure_mode: event.target.value as RewardItemInput['failure_mode'] })}><option value="none">正常</option><option value="fail_once">首次失败</option><option value="always_fail">持续失败</option></select><button className="danger-link" disabled={items.length === 1} onClick={() => setItems(current => current.filter((_, itemIndex) => itemIndex !== index))}>移除</button></div>)}</div>
      {error && <div className="inline-error">{error}</div>}
      <div className="form-actions"><a className="secondary" href="#batches">取消</a><button className="primary" disabled={saving || !name.trim() || items.some(item => !item.recipient_id || item.reward_gems < 1)} onClick={save}>{saving ? '正在创建…' : '保存草稿'}</button></div>
    </section>
  </>
}
