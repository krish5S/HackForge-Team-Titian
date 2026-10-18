import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useReceipt } from '../api/hooks'
import { Badge, ErrorState, Money, Skeleton } from './Common'
import { EvidenceSection } from './Evidence'
import { record } from '../api/client'
import { ReceiptPreview } from './ReceiptPreview'
export function ReceiptPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const query = useReceipt(id)
  const close = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    close.current?.focus({ preventScroll: true })
    if (window.matchMedia('(max-width: 760px)').matches) close.current?.scrollIntoView({ block: 'start' })
  }, [id])
  const data = query.data
  const processed = record(data?.processed_receipt)
  const extraction = record(processed.extraction)
  const decision = data?.decision
  const extracted = Object.fromEntries(Object.entries(extraction).filter(([key]) => !['line_items', 'confidence', 'confidences'].includes(key)))
  return <aside className="receipt-panel" aria-label="Receipt details" onKeyDown={event => { if (event.key === 'Escape' && !(event.target instanceof Element && event.target.closest('dialog'))) { event.stopPropagation(); onClose() } }}>
    <div className="section-heading"><span className="eyebrow">Receipt details</span><button ref={close} onClick={onClose} aria-label="Close receipt details">Close ×</button></div>
    {query.isPending ? <Skeleton /> : query.isError ? <ErrorState error={query.error} retry={() => query.refetch()} /> : data && <>
      <h2>{typeof extraction.merchant_name === 'string' ? extraction.merchant_name : 'Receipt'}</h2><p className="muted receipt-id">{data.receipt_id}</p><p>{data.employee_name || data.employee_id}</p><Badge verdict={decision?.verdict} />
      <section className="amount-grid">{(['claimed', 'proposed', 'reimbursable', 'amount_at_risk'] as const).map(key => <div key={key}><span className="eyebrow">{key.replaceAll('_', ' ')}</span><Money value={decision?.[key]} currency={decision?.currency} /></div>)}</section>
      <ReceiptPreview key={id} id={id} variants={data.available_variants} />
      <EvidenceSection title="Extracted fields" value={extracted} open />
      <EvidenceSection title="Line items" value={extraction.line_items ?? processed.line_items} />
      <EvidenceSection title="Confidence indicators" value={extraction.confidence ?? extraction.confidences ?? processed.confidence} />
      <EvidenceSection title="Validation checks" value={processed.validation ?? processed.validation_checks} />
      <EvidenceSection title="Policy reasons & clauses" value={decision?.reasons} open />
      <EvidenceSection title="What would change this decision" value={decision?.counterfactuals} />
      <section className="forensics"><h3>Forensic signals</h3><p className="muted">Signals for review, not proof of fraud.</p><EvidenceSection title="Score & signals" value={processed.forensics ?? processed.forensic ?? { risk_score: decision?.risk_score }} /></section>
      {typeof decision?.duplicate_of === 'string' && <section><h3>Duplicate reference</h3><Link to={`/receipts/${encodeURIComponent(decision.duplicate_of)}${window.location.search}`}>{decision.duplicate_of}</Link></section>}
      <EvidenceSection title="Ledger impact & budget" value={decision && { ledger_refs: decision.ledger_refs, ledger_impact: decision.ledger_impact, budget: decision.budget }} />
      {processed.fx != null && <EvidenceSection title="Currency conversion evidence" value={processed.fx} />}
    </>}
  </aside>
}
