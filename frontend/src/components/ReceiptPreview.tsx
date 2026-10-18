import { useEffect, useRef, useState } from 'react'
import { useReceiptFile } from '../api/hooks'
export function ReceiptPreview({ id, variants = ['original'] }: { id: string; variants?: string[] }) {
  const [variant, setVariant] = useState<'original' | 'clean'>('original')
  const file = useReceiptFile(id, variant)
  const [url, setUrl] = useState('')
  const dialog = useRef<HTMLDialogElement>(null)
  const expand = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!file.data) return
    const next = URL.createObjectURL(file.data)
    // Synchronize a browser-owned blob URL; cleanup releases it on change/unmount.
    // oxlint-disable-next-line react/set-state-in-effect
    setUrl(next)
    return () => URL.revokeObjectURL(next)
  }, [file.data])
  const type = file.data?.type.split(';')[0]
  const supported = type === 'application/pdf' || ['image/jpeg', 'image/png', 'image/webp', 'image/gif'].includes(type || '')
  function preview() {
    return type === 'application/pdf' ? <iframe title="Original receipt PDF" src={url} /> : <img src={url} alt="Original receipt" />
  }
  return <section className="preview"><div className="section-heading"><h3>{variant === 'clean' ? 'Cleaned receipt' : 'Original receipt'}</h3><button ref={expand} disabled={!url || !supported} onClick={() => dialog.current?.showModal()}>Expand ↗</button></div>
    {variants.includes('clean') && <label>Preview <select value={variant} onChange={event => setVariant(event.target.value as 'original' | 'clean')}><option value="original">Original</option><option value="clean">Cleaned</option></select></label>}
    {file.isPending ? <p role="status">Loading original file…</p> : file.isError ? <div className="muted"><p>Receipt file unavailable. {file.error.message}</p><button onClick={() => file.refetch()}>Retry file</button></div> : !supported ? <p>Preview unavailable for this file type.</p> : url && preview()}
    <dialog ref={dialog} className="preview-dialog" aria-label="Expanded original receipt" onClose={() => expand.current?.focus()} onCancel={event => event.stopPropagation()}><div className="section-heading"><h2>{variant === 'clean' ? 'Cleaned receipt' : 'Original receipt'}</h2><button autoFocus onClick={() => dialog.current?.close()}>Close preview ×</button></div>{url && supported && preview()}</dialog>
  </section>
}
