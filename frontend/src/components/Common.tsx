import type { Verdict } from '../api/client'
export function Badge({ verdict }: { verdict?: Verdict | null }) {
  const labels = { APPROVE: 'Approved', NEEDS_REVIEW: 'Needs review', REJECT: 'Rejected' }
  return <span className={`badge ${verdict || 'pending'}`}>{verdict ? labels[verdict] || verdict : 'Evaluation pending'}</span>
}
export function Money({ value, currency }: { value: unknown; currency?: unknown }) {
  return <span className="money">{typeof value === 'string' ? value : '—'}<small>{typeof currency === 'string' && currency ? currency : 'Currency unavailable'}</small></span>
}
export function ErrorState({ error, retry }: { error: Error; retry: () => void }) {
  return <div className="state error" role="alert"><h3>Unable to load</h3><p>{error.message === 'Failed to fetch' ? 'The API is unavailable. Check that the backend is running and try again.' : error.message}</p><button onClick={retry}>Retry</button></div>
}
export function Skeleton() {
  return <div className="skeletons" role="status" aria-label="Loading"><span className="sr-only">Loading…</span>{[0, 1, 2, 3].map(n => <div className="skeleton" key={n} />)}</div>
}
