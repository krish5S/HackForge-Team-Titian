// Persist only a random retry key and content digest, never receipt/context data.
// A reload followed by reselecting the same file and fields can safely retry.
export async function reserveSubmissionKey(userId: string, file: File, body: FormData, storage: Storage) {
  const fields = Array.from(body.entries()).filter((entry): entry is [string, string] => typeof entry[1] === 'string')
    .sort(([left], [right]) => left.localeCompare(right))
  const context = new TextEncoder().encode(JSON.stringify({ fields, name: file.name }))
  const bytes = new Uint8Array(await file.arrayBuffer())
  const payload = new Uint8Array(bytes.length + context.length)
  payload.set(bytes)
  payload.set(context, bytes.length)
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', payload)), byte => byte.toString(16).padStart(2, '0')).join('')
  const storageKey = `receipt-upload:${userId}:${digest}`
  const key = storage.getItem(storageKey) || crypto.randomUUID()
  storage.setItem(storageKey, key)
  return { key, storageKey, body }
}
