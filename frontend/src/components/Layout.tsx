import type { ReactNode } from 'react'

interface LayoutProps {
  route: string
  healthLabel: string
  healthOk: boolean
  children: ReactNode
}

const nav = [
  ['overview', '运行概览'],
  ['batches', '发放批次'],
  ['new', '创建批次'],
  ['recovery', '失败恢复'],
  ['ledger', '账本与审计'],
]

export function Layout({ route, healthLabel, healthOk, children }: LayoutProps) {
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#overview">
          <span className="brand-mark">R</span>
          <span><strong>RewardOps</strong><small>可靠奖励发放平台</small></span>
        </a>
        <nav aria-label="主导航">
          {nav.map(([key, label]) => (
            <a key={key} className={route === key || (key === 'batches' && route === 'batch') ? 'active' : ''} href={`#${key}`}>
              <span className="nav-dot" />{label}
            </a>
          ))}
        </nav>
        <div className="lab-link">
          <span>可靠性验证</span>
          <p>重复请求、确认丢失与并发消费实验</p>
          <a href="/dashboard">打开 Reliability Lab ↗</a>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div><span className="environment">PORTFOLIO ENVIRONMENT</span><strong>奖励发放控制台</strong></div>
          <span className={`health ${healthOk ? 'ok' : 'bad'}`}><i />{healthLabel}</span>
        </header>
        <div className="content">{children}</div>
      </main>
    </div>
  )
}
