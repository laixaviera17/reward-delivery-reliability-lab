export function StatCard({ label, value, note, tone = 'blue' }: { label: string; value: string | number; note: string; tone?: string }) {
  return <article className={`stat-card ${tone}`}><span>{label}</span><strong>{value}</strong><small>{note}</small></article>
}
