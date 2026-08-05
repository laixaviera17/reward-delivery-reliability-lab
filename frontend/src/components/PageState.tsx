export function PageState({ children, kind = 'empty' }: { children: string; kind?: 'empty' | 'error' }) {
  return <div className={`page-state ${kind}`}>{children}</div>
}
