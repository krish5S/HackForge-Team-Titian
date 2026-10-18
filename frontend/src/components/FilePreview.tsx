import { useEffect, useState } from 'react'
export function FilePreview({ file, title }: { file: Blob; title: string }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    const next = URL.createObjectURL(file)
    // Browser-owned URL must be released when the selected file changes.
    // oxlint-disable-next-line react/set-state-in-effect
    setUrl(next)
    return () => URL.revokeObjectURL(next)
  }, [file])
  if (!url) return <p>Preparing preview…</p>
  return <div className="employee-file-preview">
    {file.type === 'application/pdf' ? <iframe src={url} title={title} /> : file.type.startsWith('image/') ? <img src={url} alt={title} /> : <p>Preview unavailable.</p>}
    <a href={url} target="_blank" rel="noopener noreferrer">Open file in a new tab ↗</a>
  </div>
}
