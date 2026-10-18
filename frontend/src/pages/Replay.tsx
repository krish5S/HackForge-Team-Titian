import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { request } from '../api/client'
import type { Replay, Timeline } from '../api/reviewer'
import { Badge, ErrorState, Money, Skeleton } from '../components/Common'
import './reviewer.css'

function percentage(used: string, cap: string) {
  const cents = (amount: string) => BigInt(amount.replace('.', ''))
  try { const max = cents(cap); return max > 0n ? Math.min(100, Number(cents(used) * 100n / max)) : 0 } catch { return 0 }
}
function ReplayView({ timeline }: { timeline: Timeline }) {
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const timestamps = [...new Set(timeline.events.map(event => event.submitted_at))]
  const asOf = timestamps[index]
  useEffect(() => {
    if (!playing) return
    const timer = setInterval(() => setIndex(current => {
      if (current >= timestamps.length - 1) { setPlaying(false); return current }
      return current + 1
    }), 1800)
    return () => clearInterval(timer)
  }, [playing, timestamps.length])
  const snapshot = useQuery({ queryKey: ['replay', timeline.run_id, asOf], queryFn: ({ signal }) => request<Replay>(`/replay?as_of=${encodeURIComponent(asOf)}&run_id=${encodeURIComponent(timeline.run_id || "")}`, signal), enabled: Boolean(asOf) })
  if (!timestamps.length) return <div className="state"><h3>No evaluated arrivals yet.</h3><p>Import processed receipts and run an evaluation to see their history.</p></div>
  const events = timeline.events.filter(event => event.submitted_at === asOf)
  return <><section className="replay-controls"><button onClick={() => setPlaying(!playing)}>{playing ? 'Pause' : 'Play'}</button><label htmlFor="replay-time">Submission time: {new Date(asOf).toLocaleString()}</label><input id="replay-time" type="range" min="0" max={timestamps.length - 1} value={index} onChange={event => { setPlaying(false); setIndex(Number(event.target.value)) }} /><span className="muted">Arrival group {index + 1} of {timestamps.length} · Policy version {timeline.policy_version}</span></section>
    <section className="replay-events"><h2>Arrivals & changes</h2>{events.map(event => <article key={event.seq}><Link to={`/receipts/${encodeURIComponent(event.receipt_id)}`}>{event.receipt_id}</Link> <Badge verdict={event.verdict_at_arrival} />{event.flips.map((flip, i) => <p key={i}><Link to={`/receipts/${encodeURIComponent(flip.receipt_id)}`}>{flip.receipt_id}</Link>: {flip.from} → {flip.to} · {flip.reason}</p>)}</article>)}</section>
    {snapshot.isPending ? <Skeleton /> : snapshot.isError ? <ErrorState error={snapshot.error} retry={() => snapshot.refetch()} /> : snapshot.data.snapshot && <>
      <section className="summary">{Object.entries(snapshot.data.snapshot.verdict_counts).map(([verdict, count]) => <div key={verdict}><span className="eyebrow">{verdict.replaceAll('_', ' ')}</span><strong>{count}</strong></div>)}<div><span className="eyebrow">Reimbursable at this time</span><strong><Money value={snapshot.data.snapshot.amounts.reimbursable} currency={snapshot.data.currency} /></strong></div></section>
      <section><h2>Budget meters</h2><div className="budget-grid">{snapshot.data.snapshot.ledger_meters.length ? snapshot.data.snapshot.ledger_meters.map((meter, i) => <article key={i}><h3>{meter.employee_id} · {meter.label}</h3><progress value={percentage(meter.used_after, meter.cap)} max="100" aria-label={`${meter.employee_id} ${meter.label} budget used`} /><p>Used {meter.used_after} of {meter.cap} {snapshot.data.currency}</p><small>Remaining {meter.remaining} {snapshot.data.currency}</small></article>) : <p className="muted">No budget meters apply at this time.</p>}</div></section>
      <section className="table-scroll"><table><thead><tr><th>Receipt</th><th>Snapshot verdict</th><th>Reimbursable</th><th>At risk</th></tr></thead><tbody>{snapshot.data.snapshot.decisions.map(decision => <tr key={decision.receipt_id}><td><Link to={`/receipts/${encodeURIComponent(decision.receipt_id)}`}>{decision.receipt_id}</Link></td><td><Badge verdict={decision.verdict} /></td><td><Money value={decision.reimbursable} currency={snapshot.data.currency} /></td><td><Money value={decision.amount_at_risk} currency={snapshot.data.currency} /></td></tr>)}</tbody></table></section><p className="muted">Receipt links open current details; the amounts above belong to this historical snapshot.</p>
    </>}
  </>
}
export function ReplayPage() {
  const timeline = useQuery({ queryKey: ['timeline'], queryFn: ({ signal }) => request<Timeline>('/timeline', signal) })
  return <main className="reviewer-page"><div className="intro"><span className="eyebrow">The month, as it happened</span><h1>Month replay</h1><p>Explore arrivals, changing decisions, and budget use from the saved evaluation input.</p></div>{timeline.isPending ? <Skeleton /> : timeline.isError ? <ErrorState error={timeline.error} retry={() => timeline.refetch()} /> : <ReplayView key={timeline.data.run_id} timeline={timeline.data} />}</main>
}
