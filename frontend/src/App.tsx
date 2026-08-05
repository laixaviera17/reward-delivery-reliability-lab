import { useEffect, useMemo, useState } from 'react'
import { api } from './api/client'
import { Layout } from './components/Layout'
import { BatchDetailPage } from './pages/BatchDetailPage'
import { BatchesPage } from './pages/BatchesPage'
import { CreateBatchPage } from './pages/CreateBatchPage'
import { LedgerPage } from './pages/LedgerPage'
import { OverviewPage } from './pages/OverviewPage'
import { RecoveryPage } from './pages/RecoveryPage'

function routeFromHash() {
  const value = window.location.hash.replace(/^#/, '') || 'overview'
  const [page, id] = value.split('/')
  return { page, id }
}

export default function App() {
  const [route, setRoute] = useState(routeFromHash)
  const [health, setHealth] = useState({ ok: false, label: '正在探活…' })
  useEffect(() => {
    const change = () => setRoute(routeFromHash())
    window.addEventListener('hashchange', change)
    return () => window.removeEventListener('hashchange', change)
  }, [])
  useEffect(() => {
    const refresh = () => api.health().then(data => setHealth({ ok: data.status === 'ok', label: `${data.mode === 'async' ? '异步' : '同步'} · ${data.database_backend}` })).catch(() => setHealth({ ok: false, label: '依赖不可用' }))
    refresh(); const timer = window.setInterval(refresh, 10_000)
    return () => window.clearInterval(timer)
  }, [])
  const page = useMemo(() => {
    if (route.page === 'batches') return <BatchesPage />
    if (route.page === 'new') return <CreateBatchPage />
    if (route.page === 'ledger') return <LedgerPage />
    if (route.page === 'recovery') return <RecoveryPage />
    if (route.page === 'batch' && route.id) return <BatchDetailPage batchId={route.id} />
    return <OverviewPage />
  }, [route])
  return <Layout route={route.page} healthLabel={health.label} healthOk={health.ok}>{page}</Layout>
}
