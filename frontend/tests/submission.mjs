import assert from 'node:assert/strict'
import { createServer } from 'vite'
const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
try {
  const { reserveSubmissionKey } = await server.ssrLoadModule('/src/api/submissionAttempt.ts')
  const values = new Map()
  const storage = { getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
  const file = new File(['test-content'], 'receipt.png', { type: 'image/png' })
  const body = new FormData()
  body.set('purpose', 'Client meeting')
  const first = await reserveSubmissionKey('employee-one', file, body, storage)
  const retry = await reserveSubmissionKey('employee-one', file, body, storage)
  assert.equal(first.key, retry.key, 'Same content after reload must retain its key')
  const other = await reserveSubmissionKey('employee-two', file, body, storage)
  assert.notEqual(first.key, other.key)
  const changed = new FormData()
  changed.set('purpose', 'Travel')
  assert.notEqual(first.key, (await reserveSubmissionKey('employee-one', file, changed, storage)).key)
  storage.removeItem(first.storageKey)
  assert.notEqual(first.key, (await reserveSubmissionKey('employee-one', file, body, storage)).key, 'Confirmed success or deliberate new submission gets a new key')
  assert.ok([...values.keys()].every(key => !key.includes('Client meeting') && !key.includes('receipt.png')))
  console.log('PASS: retry keys survive reload, isolate accounts/content, rotate for new submissions, and contain no form fields.')
} finally { await server.close() }
