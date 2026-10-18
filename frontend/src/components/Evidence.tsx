import { record } from '../api/client'
const label = (key: string) => key.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase())
// Flexible processed payloads have no more specific contract in this repository.
// Preserve supplied labels and decimal strings instead of inferring values or units.
export function Evidence({ value }: { value: unknown }) {
  if (value == null || value === '' || (Array.isArray(value) && !value.length)) return <span className="muted">Unavailable</span>
  if (typeof value === 'boolean') return <span>{value ? 'Yes / pass' : 'No / fail'}</span>
  if (typeof value !== 'object') return <span>{String(value)}</span>
  if (Array.isArray(value)) return <ol className="evidence-list">{value.map((entry, i) => <li key={i}><Evidence value={entry} /></li>)}</ol>
  const entries = Object.entries(record(value))
  if (!entries.length) return <span className="muted">Unavailable</span>
  return <dl className="fields">{entries.map(([key, entry]) => <div key={key}><dt>{label(key)}</dt><dd><Evidence value={entry} /></dd></div>)}</dl>
}
export function EvidenceSection({ title, value, open = false }: { title: string; value: unknown; open?: boolean }) {
  return <details className="evidence-section" open={open}><summary>{title}</summary><Evidence value={value} /></details>
}
