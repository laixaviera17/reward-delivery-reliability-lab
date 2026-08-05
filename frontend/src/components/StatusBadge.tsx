const labels: Record<string, string> = {
  draft: '草稿',
  queued: '排队中',
  processing: '处理中',
  succeeded: '已成功',
  completed: '已完成',
  failed: '失败',
  partial_failed: '部分失败',
  pending: '待处理',
  consumed: '已消费',
}

export function StatusBadge({ status }: { status: string | null }) {
  const value = status ?? 'not_created'
  return <span className={`status-badge ${value}`}>{labels[value] ?? '未创建'}</span>
}
