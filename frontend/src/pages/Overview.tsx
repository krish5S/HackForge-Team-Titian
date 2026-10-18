import { useEffect, useRef } from 'react'
import { useMutation } from '@tanstack/react-query'
import { request } from '../api/client'
import { useMetrics } from '../api/reviewer'
import { authError } from '../auth/session'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useDecisions, useHealth } from '../api/hooks'
import { Badge, ErrorState, Money, Skeleton } from '../components/Common'
import { ReceiptPanel } from '../components/ReceiptPanel'
export function Overview() {
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const verdict = params.get('verdict') || ''
  const employee = params.get('employee_id') || ''
  const health = useHealth()
  const metrics = useMetrics()
  const download = useMutation({ mutationFn: async () => {
    const blob = await request<Blob>('/exports/decisions', undefined, true)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = 'decisions.csv'; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } })
  const all = useDecisions()
  const queue = useDecisions({ verdict, employee_id: employee })
  const opener = useRef<HTMLElement | null>(null)
  const queuePosition = useRef<number | null>(null)
  const filterChange = useRef(false)
  const fallback = useRef<HTMLSelectElement>(null)
  const employees = [...new Map((all.data || []).map(row => [row.employee_id, row.employee_name])).entries()]
  function close() {
    navigate(`/queue${params.size ? `?${params}` : ''}`, { replace: true })
    requestAnimationFrame(() => {
      (opener.current?.isConnected ? opener.current : fallback.current)?.focus({ preventScroll: true })
      if (queuePosition.current !== null) window.scrollTo({ top: queuePosition.current, behavior: 'instant' })
    })
  }
  function filter(key?: string, value?: string) {
    const next = new URLSearchParams(params)
    if (!key) { next.delete('verdict'); next.delete('employee_id') }
    else if (value) next.set(key, value)
    else next.delete(key)
    filterChange.current = true
    setParams(next)
  }
  useEffect(() => {
    if (!filterChange.current || !queue.isSuccess || queue.isFetching) return
    filterChange.current = false
    if (id && !queue.data.some(row => row.receipt_id === id)) close()
  })
  return <main><div className="intro"><span className="eyebrow">The review desk</span><h1>Expense overview</h1><p>Review receipts, understand policy decisions, and identify expenses needing attention.</p></div>
    <section className="summary" aria-label="Expense summary">
      <div><span className="eyebrow">Total receipts</span><strong>{health.isPending ? '…' : health.isError ? '—' : health.data.receipt_count}</strong><small>{health.isError ? <button className="text-button" onClick={() => health.refetch()}>Count unavailable · Retry</button> : health.isPending ? 'Loading receipt count' : 'Receipts received'}</small></div>
      <div><span className="eyebrow">Automatically decided</span><strong>{metrics.isPending ? '…' : metrics.data?.automatically_decided ?? '—'}</strong><small>Approved or rejected in the latest run</small></div>
      {([['Approved amount', metrics.data?.approved_amount], ['Blocked amount', metrics.data?.blocked_amount]] as const).map(([label, value]) => <div key={label}><span className="eyebrow">{label}</span><strong>{metrics.isPending ? '…' : value ?? '—'}</strong><small>{metrics.data?.currency || 'Currency unavailable'} · {label === 'Blocked amount' ? 'Final denied portions; excludes pending review' : 'Approved reimbursements'}</small></div>)}
    </section>
    {metrics.isError && <ErrorState error={metrics.error} retry={() => metrics.refetch()} />}
    {metrics.data?.run_id && <p className="evaluation-scope">Policy {metrics.data.policy_id} · Version {metrics.data.policy_version} · Period {metrics.data.period}</p>}
    <div className={`workspace ${id ? 'with-detail' : ''}`}><section className="queue" aria-label="Review queue">
      <div className="queue-heading"><div><h2>Review queue</h2><p className="muted">Highest amount at risk first</p></div><div className="export"><button disabled={download.isPending} onClick={() => download.mutate()}> {download.isPending ? 'Exporting…' : 'Export all CSV'} ↗</button><small>All saved results in the latest completed run.</small>{download.isError && <p role="alert">{authError(download.error)}</p>}</div></div>
      <div className="toolbar"><label>Verdict<select ref={fallback} value={verdict} onChange={e => filter('verdict', e.target.value)}><option value="">All verdicts</option><option value="APPROVE">Approved</option><option value="NEEDS_REVIEW">Needs Review</option><option value="REJECT">Rejected</option></select></label><label>Employee<select value={employee} onChange={e => filter('employee_id', e.target.value)}><option value="">All employees</option>{employees.map(([key, name]) => <option key={key} value={key}>{name || key}</option>)}{employee && !employees.some(([key]) => key === employee) && <option value={employee}>{employee}</option>}</select></label><button className="text-button" disabled={!verdict && !employee} onClick={() => filter()}>Clear filters</button><span className="result-count" role="status">{queue.isPending ? 'Loading…' : queue.isError ? 'Results unavailable' : `${queue.data.length} ${queue.data.length === 1 ? 'result' : 'results'}`}</span></div>
      {all.isError && <p className="employee-error">Employee options unavailable. <button className="text-button" onClick={() => all.refetch()}>Retry options</button></p>}
      <div className="table-scroll"><table><thead><tr>{['Receipt', 'Employee', 'Transaction date', 'Claimed amount', 'Verdict', 'Amount at risk'].map(title => <th key={title}>{title}</th>)}</tr></thead><tbody>{queue.data?.map(row => <tr key={row.receipt_id} className={row.receipt_id === id ? 'selected' : ''}><td><Link aria-current={row.receipt_id === id ? 'true' : undefined} to={`/receipts/${encodeURIComponent(row.receipt_id)}${params.size ? `?${params}` : ''}`} onClick={event => { opener.current = event.currentTarget; queuePosition.current = window.scrollY }}><span>{row.merchant_name || 'Unknown merchant'}</span><small>{row.receipt_id}</small></Link></td><td>{row.employee_name || row.employee_id}</td><td>{row.transaction_date || '—'}</td><td><Money value={row.claimed} currency={row.currency} /></td><td><Badge verdict={row.verdict} /><small className="reason">{row.top_reason || 'Reason unavailable'}</small></td><td><Money value={row.amount_at_risk} currency={row.currency} /></td></tr>)}</tbody></table></div>
      {queue.isPending ? <Skeleton /> : queue.isError ? <ErrorState error={queue.error} retry={() => queue.refetch()} /> : !queue.data.length && <div className="state"><span className="empty-mark" aria-hidden="true">—</span><h3>{verdict || employee ? 'No receipts match these filters.' : 'No evaluated receipts yet.'}</h3><p>{verdict || employee ? 'Try another verdict or employee to see more results.' : 'Once receipts are evaluated, their decisions and supporting evidence will appear here.'}</p>{(verdict || employee) && <button onClick={() => filter()}>Clear filters</button>}</div>}
      <div className="queue-footer"><span>Every decision, backed by evidence.</span><span>Read-only review</span></div>
    </section>{id && <ReceiptPanel id={id} onClose={close} />}</div>
  </main>
}
