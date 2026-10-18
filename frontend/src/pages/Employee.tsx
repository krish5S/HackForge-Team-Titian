import { useRef, useState, type DragEvent, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type User, authError, replaceSession } from '../auth/session'
import { SessionControls } from '../auth/SessionControls'
import { reserveSubmissionKey } from '../api/submissionAttempt'
import { ApiError, request } from '../api/client'
import { employeeHistoryKey, submissionPath, useEmployeeHistory, type EmployeeSubmission } from '../api/employee'
import { Badge, ErrorState, Money, Skeleton } from '../components/Common'
import { EvidenceSection } from '../components/Evidence'
import { FilePreview } from '../components/FilePreview'
import './employee.css'

const statusLabels = { UPLOADED: 'Uploaded — awaiting processing', PROCESSING: 'Processing', PROCESSED: 'Processed — awaiting evaluation', EVALUATED: 'Evaluated', FAILED: 'Processing failed' }
const allowed = ['image/jpeg', 'image/png', 'image/webp', 'application/pdf']

function SubmissionDetails({ id, onClose }: { id: string; onClose: () => void }) {
  const detail = useQuery({ queryKey: ['employee-submission', id], queryFn: ({ signal }) => request<EmployeeSubmission>(submissionPath(id), signal), refetchInterval: 30_000 })
  const file = useQuery({ queryKey: ['employee-submission-file', id], queryFn: ({ signal }) => request<Blob>(`${submissionPath(id)}/file`, signal, true), retry: false })
  return <section className="employee-detail" aria-label="Submission details">
    <div className="section-heading"><h2>Submission details</h2><button onClick={onClose}>Close ×</button></div>
    {detail.isPending ? <Skeleton /> : detail.isError ? <ErrorState error={detail.error} retry={() => detail.refetch()} /> : <>
      <p className="muted">{detail.data.id}</p><p>{detail.data.decision && detail.data.processing_status === 'PROCESSED' ? 'Processed' : statusLabels[detail.data.processing_status]}</p>
      {detail.data.processing_status === 'FAILED' && <p role="status" className="employee-error">{detail.data.processing_error || 'Processing failed. Contact your organization for assistance.'}</p>}
      {detail.data.processing_warnings?.map(warning => <p role="status" className="employee-error" key={warning}>{warning}</p>)}
      {detail.data.extraction && <><p>Extraction: {detail.data.extraction_status}</p><EvidenceSection title="Extracted receipt fields" value={detail.data.extraction} open /></>}
      {detail.data.extraction_checks && <EvidenceSection title="Extraction checks" value={detail.data.extraction_checks} />}
      {detail.data.ocr_text && <details><summary>Recognized receipt text</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{detail.data.ocr_text}</pre></details>}
      <EvidenceSection title="Expense information" value={detail.data.fields} open />
      {detail.data.decision && <><Badge verdict={detail.data.decision.verdict} /><div className="amount-grid">{['claimed', 'proposed', 'reimbursable', 'amount_at_risk'].map(key => <div key={key}><span className="eyebrow">{key.replaceAll('_', ' ')}</span><Money value={detail.data.decision?.amounts[key]} currency={detail.data.decision?.amounts.currency} /></div>)}</div><EvidenceSection title="Decision reasons" value={detail.data.decision.reasons} open /><EvidenceSection title="What would change this decision" value={detail.data.decision.counterfactuals} /></>}
    </>}
    {file.isPending ? <p role="status">Loading original file…</p> : file.isError ? <ErrorState error={file.error} retry={() => file.refetch()} /> : <FilePreview file={file.data} title="Your uploaded receipt" />}
  </section>
}

export function EmployeePage({ user }: { user: User }) {
  const client = useQueryClient()
  const history = useEmployeeHistory(user.id)
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState('')
  const [success, setSuccess] = useState<EmployeeSubmission | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [attempted, setAttempted] = useState(false)
  const [preparing, setPreparing] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const formRef = useRef<HTMLFormElement>(null)
  const busy = useRef(false)
  const attempt = useRef<{ key: string; storageKey: string; body: FormData } | null>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const opener = useRef<HTMLButtonElement | null>(null)
  const mutation = useMutation({
    mutationFn: (pending: { key: string; body: FormData }) => request<EmployeeSubmission>('/employee/submissions', undefined, false, {
      method: 'POST', headers: { 'Idempotency-Key': pending.key }, body: pending.body,
    }),
  })
  function choose(next: File | undefined) {
    if (attempted || busy.current) return
    setSuccess(null)
    if (!next) return
    if (next.size === 0 || next.size > 10 * 1024 * 1024 || (!/\.(jpe?g|png|webp|pdf)$/i.test(next.name) || (next.type !== '' && !allowed.includes(next.type)))) {
      setFileError('Choose a nonempty JPEG, PNG, WebP, or PDF, no larger than 10 MiB.')
      return
    }
    setFileError('')
    setFile(next)
    mutation.reset()
  }
  function drop(event: DragEvent) {
    event.preventDefault()
    if (event.dataTransfer.files.length !== 1) { setFileError('Select one receipt per submission.'); return }
    choose(event.dataTransfer.files[0])
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy.current) return
    if (!file) { setFileError('Select a receipt file.'); input.current?.focus(); return }
    if (!attempt.current && !String(new FormData(event.currentTarget).get('purpose') || '').trim()) {
      setFileError('Expense purpose is required.'); return
    }
    busy.current = true
    setPreparing(true)
    setFileError('')
    setAttempted(true)
    setSuccess(null)
    try {
      if (!attempt.current) {
        const body = new FormData(event.currentTarget)
        body.set('file', file)
        attempt.current = await reserveSubmissionKey(user.id, file, body, sessionStorage)
      }
      setPreparing(false)
      const saved = await mutation.mutateAsync(attempt.current)
      setSuccess(saved)
      setFile(null)
      formRef.current?.reset()
      if (input.current) input.current.value = ''
      sessionStorage.removeItem(attempt.current.storageKey)
      attempt.current = null
      setAttempted(false)
      client.setQueryData<EmployeeSubmission[]>(employeeHistoryKey(user.id), old => [saved, ...(old || []).filter(row => row.id !== saved.id)])
      void client.invalidateQueries({ queryKey: employeeHistoryKey(user.id) })
    } catch (error) {
      if (!attempt.current) { setFileError('Could not prepare a safe retry key. Allow browser session storage and try again.'); setAttempted(false) }
      if (error instanceof ApiError && error.status === 401) await replaceSession(null, client)
      // A definitive validation failure saved nothing; allow corrections.
      if (error instanceof ApiError && [400, 413, 415, 422].includes(error.status)) {
        if (attempt.current) sessionStorage.removeItem(attempt.current.storageKey)
        attempt.current = null
        setAttempted(false)
      }
    } finally { busy.current = false; setPreparing(false) }
  }
  function newAttempt() {
    if (!window.confirm('The previous request may already have saved a receipt. Check your history first. Start a deliberate new submission with a new key?')) return
    if (attempt.current) sessionStorage.removeItem(attempt.current.storageKey)
    attempt.current = null
    setAttempted(false)
    mutation.reset()
  }
  function openDetails(id: string, button: HTMLButtonElement) {
    opener.current = button
    setSelected(id)
    dialog.current?.showModal()
  }
  return <><header className="site-header"><Link className="brand" to="/employee">The Receipt Graveyard<small>Expense review with evidence.</small></Link><SessionControls user={user} /></header>
    <main className="employee-page"><div className="intro"><span className="eyebrow">Your workspace</span><h1>Your expenses</h1><p>Submit receipts, add supporting details, and track each expense.</p></div>
      {success && <div className="submission-success" role="status"><strong>Receipt submitted.</strong><p>Submission ID: {success.id}</p><p>{statusLabels[success.status]}</p><button onClick={event => openDetails(success.id, event.currentTarget)}>View submission</button></div>}
      <div className="employee-upload-layout"><section><h2>Submit a receipt</h2>
        <form ref={formRef} onSubmit={submit} aria-busy={mutation.isPending || preparing}>
          <fieldset disabled={attempted || mutation.isPending}>
            <div className="receipt-drop" onDragOver={event => event.preventDefault()} onDrop={drop}>
              <p>Drop your receipt here</p><button type="button" onClick={() => input.current?.click()}>Browse files</button>
              <input className="sr-only" ref={input} type="file" accept=".jpg,.jpeg,.png,.webp,.pdf" aria-label="Choose receipt file" onChange={event => choose(event.target.files?.[0])} />
              <small>JPEG, PNG, WebP or PDF · One file · Maximum 10 MiB</small>
              {file && <div className="selected-file"><strong>{file.name}</strong><span>{(file.size / 1024).toFixed(1)} KiB</span><button type="button" onClick={() => { setFile(null); if (input.current) input.current.value = '' }}>Remove file</button></div>}
            </div>
            {fileError && <p role="alert" className="employee-error">{fileError}</p>}
            <label>Expense purpose <span aria-hidden="true">*</span><textarea name="purpose" required maxLength={1000} rows={2} placeholder="What was this expense for?" /></label>
            <label className="employee-checkbox"><input type="checkbox" name="client_meal" value="true" /> This is a client meal</label>
            <label>Client name <span className="muted">(optional)</span><input name="client_name" maxLength={300} /></label>
            <div className="employee-field-pair"><label>Attendee names <span className="muted">(optional)</span><input name="attendee_names" maxLength={2000} /></label><label>Attendee count <span className="muted">(optional)</span><input name="attendee_count" type="number" min="0" max="10000" step="1" /></label></div>
            <label>Supporting notes <span className="muted">(optional)</span><textarea name="notes" maxLength={5000} rows={3} /></label>
          </fieldset>
          {mutation.isError && <div role="alert" className="employee-error"><p>{authError(mutation.error)}</p>{attempted && <p>Your information is preserved. Retry sends the same submission key. Check history before starting a new submission.</p>}</div>}
          <div className="employee-submit-actions"><button className="submit-receipt" type="submit" disabled={mutation.isPending || preparing}>{preparing ? 'Preparing…' : mutation.isPending ? 'Uploading…' : attempted ? 'Retry submission' : 'Submit receipt'}</button>{attempted && !mutation.isPending && !preparing && <button type="button" onClick={newAttempt}>Start a new submission</button>}</div>
        </form>
      </section><section className="employee-preview"><div className="section-heading"><h2>Receipt preview</h2><span className="eyebrow">Original file</span></div>{file ? <FilePreview key={`${file.name}-${file.lastModified}-${file.size}`} file={file} title="Selected receipt" /> : <div className="preview-empty"><p>Select a receipt to preview it here.</p><small>Your original file is saved with your submission.</small></div>}</section></div>
      <section className="employee-history"><div className="section-heading"><div><h2>Submission history</h2><p className="muted">Your receipts and their latest available results.</p></div><button onClick={() => history.refetch()}>Refresh</button></div>
        {history.isPending ? <Skeleton /> : history.isError ? <ErrorState error={history.error} retry={() => history.refetch()} /> : !history.data.length ? <div className="state"><h3>No submissions yet.</h3><p>Your submitted receipts will appear here.</p></div> : <div className="table-scroll"><table><thead><tr><th>Receipt / purpose</th><th>Submitted</th><th>Status</th><th>Result</th><th>Claimed</th><th>Reimbursable</th><th>File & details</th></tr></thead><tbody>{history.data.map(row => <tr key={row.id}><td>{row.filename}<small>{row.fields.purpose || 'Purpose unavailable'}</small><small>{row.id}</small></td><td>{new Date(row.submitted_at).toLocaleString()}</td><td><span className="submission-status">{row.decision && row.processing_status === 'PROCESSED' ? 'Processed' : statusLabels[row.processing_status]}</span></td><td>{row.decision ? <Badge verdict={row.decision.verdict} /> : <span className="muted">Not evaluated</span>}</td><td><Money value={row.decision?.amounts.claimed} currency={row.decision?.amounts.currency} /></td><td><Money value={row.decision?.amounts.reimbursable} currency={row.decision?.amounts.currency} /></td><td><button onClick={event => openDetails(row.id, event.currentTarget)}>View receipt</button></td></tr>)}</tbody></table></div>}
      </section>
      <dialog ref={dialog} className="employee-dialog" aria-label="Your submission" onClose={() => { setSelected(null); opener.current?.focus() }}>
        {selected && <SubmissionDetails id={selected} onClose={() => dialog.current?.close()} />}
      </dialog>
    </main></>
}
