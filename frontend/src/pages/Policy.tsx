import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { request } from '../api/client'
import { refreshResults, type PolicyData, type CompileResult } from '../api/reviewer'
import { authError } from '../auth/session'
import { ErrorState, Skeleton } from '../components/Common'
import { Evidence } from '../components/Evidence'
import './reviewer.css'

export function PolicyPage() {
  const client = useQueryClient()
  const policy = useQuery({ queryKey: ['policy'], queryFn: ({ signal }) => request<PolicyData>('/policies/active', signal) })
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const period = start && end ? { start, end } : {}
  const compile = useMutation({
    mutationFn: () => request<{ activated: boolean; result: CompileResult }> (`/policies/${encodeURIComponent(policy.data!.id)}/compile`, undefined, false, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...period, activate: true }),
    }),
    onSuccess: () => refreshResults(client),
  })
  const evaluate = useMutation({
    mutationFn: () => request('/evaluations', undefined, false, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(period) }),
    onSuccess: () => refreshResults(client),
  })
  const busy = compile.isPending || evaluate.isPending
  if (policy.isPending) return <main><Skeleton /></main>
  if (policy.isError) return <main><h1>Policy</h1><ErrorState error={policy.error} retry={() => policy.refetch()} /></main>
  const data = policy.data
  const report = compile.data?.result || data.latest_compilation
  return <main className="reviewer-page"><div className="intro"><span className="eyebrow">Rules with evidence</span><h1>Expense policy</h1><p>Read the source, inspect its rules, and review the checks behind each policy version.</p></div>
    <section className="policy-actions"><div><span className="eyebrow">Active policy</span><h2>{data.id}</h2><p className="muted">Version {data.version} · Base currency {data.compiled.base_currency}</p></div>
      <div className="policy-controls"><label>Period start <input type="date" value={start} onChange={e => setStart(e.target.value)} /></label><label>Period end <input type="date" value={end} onChange={e => setEnd(e.target.value)} /></label><small>Leave both blank to reuse the last period, or derive it from available receipts.</small><button disabled={busy || Boolean(start) !== Boolean(end)} onClick={() => compile.mutate()}>{compile.isPending ? 'Compiling and checking…' : 'Compile & activate if accepted'}</button><button disabled={busy || Boolean(start) !== Boolean(end)} onClick={() => evaluate.mutate()}>{evaluate.isPending ? 'Evaluating…' : 'Reevaluate current policy'}</button></div>
    </section>
    {compile.isError && <p className="action-message error" role="alert">{authError(compile.error)}</p>}
    {evaluate.isError && <p className="action-message error" role="alert">{authError(evaluate.error)}</p>}
    {compile.data && <p className="action-message" role="status">{compile.data.activated ? 'The accepted policy is active and its evaluation has been saved.' : 'Compilation did not activate a replacement. The previous policy and results are preserved.'}</p>}
    {evaluate.isSuccess && <p className="action-message" role="status">Evaluation saved. Overview, employee results, and replay have been refreshed.</p>}
    <div className="policy-layout"><nav aria-label="Policy clauses"><h3>Clauses</h3>{data.compiled.clauses.map(clause => <a key={clause.clause_id} href={`#clause-${clause.clause_id}`}>§ {clause.clause_id}</a>)}</nav><section><h2>Source & compiled rules</h2><details className="evidence-section"><summary>Full source policy</summary><div className="policy-source">{data.source_text}</div></details>{data.compiled.clauses.map(clause => <article className="policy-clause" id={`clause-${clause.clause_id}`} key={clause.clause_id}><span className="eyebrow">Clause {clause.clause_id}</span><p>{clause.text}</p>{data.compiled.rules.filter(rule => rule.clause_id === clause.clause_id).map((rule, index) => <div className="policy-rule" key={index}><h3>{rule.rule_type.replaceAll('_', ' ')}</h3><p>{rule.summary}</p><blockquote>{rule.source_quote}</blockquote><Evidence value={rule.parameters} /></div>)}</article>)}</section><aside><h2>Trust Report</h2><p className="muted">Actual compiler checks; unavailable checks are not passed checks.</p><Evidence value={report?.trust_report || data.trust_report} /><h3>Compiler flags</h3>{report ? report.flags.length ? report.flags.map((flag, index) => <div className="policy-flag" key={index}><strong>{flag.code}</strong><p>{flag.message}</p>{flag.clause_id && <a href={`#clause-${flag.clause_id}`}>Clause {flag.clause_id}</a>}</div>) : <p>No flags returned.</p> : <p className="muted">No new compilation has been run.</p>}</aside></div>
  </main>
}
