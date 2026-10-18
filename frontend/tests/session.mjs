// Node-only checks; these do not claim browser layout or navigation coverage.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createServer } from 'vite'
import { QueryClient, QueryObserver } from '@tanstack/react-query'
const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
try {
  const { queryClient, destination, replaceSession, logoutSession, loginSession } = await server.ssrLoadModule('/src/auth/session.tsx')
  const { ApiError } = await server.ssrLoadModule('/src/api/client.ts')
  const reviewer = { id: 'test-reviewer', role: 'REVIEWER' }
  const employee = { id: 'test-employee', role: 'EMPLOYEE' }
  assert.equal(destination(reviewer), '/queue')
  assert.equal(destination(employee), '/employee')
  // Model Shell's already-mounted useSession observer, not just cache contents.
  queryClient.setQueryData(['session'], null)
  const observer = new QueryObserver(queryClient, { queryKey: ['session'], enabled: false })
  const unsubscribe = observer.subscribe(() => {})
  queryClient.setQueryData(['receipt', 'previous-user'], { receipt_id: 'previous-user' })
  await replaceSession(reviewer)
  assert.equal(observer.getCurrentResult().data, reviewer, 'Mounted page must receive reviewer login')
  assert.equal(destination(observer.getCurrentResult().data), '/queue')
  assert.equal(queryClient.getQueryData(['receipt', 'previous-user']), undefined)
  await replaceSession(null)
  assert.equal(observer.getCurrentResult().data, null, 'Mounted page must receive logout')
  await replaceSession(employee)
  assert.equal(destination(observer.getCurrentResult().data), '/employee')
  unsubscribe()
  await replaceSession(null)
  await queryClient.fetchQuery({ queryKey: ['session'], queryFn: () => reviewer })
  queryClient.setQueryData(['receipt', 'test-private'], { receipt_id: 'test-private' })
  queryClient.setQueryData(['decisions', {}], [])
  await queryClient.fetchQuery({ queryKey: ['session'], queryFn: () => employee, staleTime: 0 })
  assert.equal(queryClient.getQueryData(['receipt', 'test-private']), undefined)
  assert.equal(queryClient.getQueryData(['decisions', {}]), undefined)
  queryClient.setQueryData(['receipt-file', 'private'], 'isolated-cache-entry')
  await assert.rejects(queryClient.fetchQuery({ queryKey: ['decisions', {}], queryFn: () => { throw new ApiError('Sign in to continue.', 401) } }))
  // Wait for the async cancellation and cache purge triggered by the error callback.
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.equal(queryClient.getQueryData(['session']), null)
  assert.equal(queryClient.getQueryData(['receipt-file', 'private']), undefined)
  queryClient.clear()
  // Exercise the actual logout operation with a mounted provider client that
  // differs from the module singleton (as can happen during hot updates).
  const mountedClient = new QueryClient()
  mountedClient.setQueryData(['session'], reviewer)
  mountedClient.setQueryData(['receipt', 'selected'], { receipt_id: 'selected' })
  const mountedObserver = new QueryObserver(mountedClient, { queryKey: ['session'], enabled: false })
  const stopMounted = mountedObserver.subscribe(() => {})
  const originalFetch = globalThis.fetch
  try {
    globalThis.fetch = async (url, init) => {
      assert.ok(url.endsWith('/auth/logout'))
      assert.equal(init.method, 'POST')
      assert.equal(init.credentials, 'include')
      return new Response(null, { status: 204 })
    }
    await logoutSession(mountedClient)
    assert.equal(mountedObserver.getCurrentResult().data, null)
    assert.equal(mountedClient.getQueryData(['receipt', 'selected']), undefined)
    mountedClient.setQueryData(['session'], reviewer)
    globalThis.fetch = async () => { throw new TypeError('Failed to fetch') }
    await assert.rejects(logoutSession(mountedClient))
    assert.equal(mountedObserver.getCurrentResult().data, reviewer, 'Failed logout must not claim server invalidation')
  } finally {
    globalThis.fetch = originalFetch
    stopMounted()
    mountedClient.clear()
  }
  const loginClient = new QueryClient()
  loginClient.setQueryData(['session'], null)
  const loginObserver = new QueryObserver(loginClient, { queryKey: ['session'], enabled: false })
  const stopLogin = loginObserver.subscribe(() => {})
  const savedFetch = globalThis.fetch
  try {
    const calls = []
    globalThis.fetch = async (url, init) => {
      calls.push(url)
      assert.equal(init.credentials, 'include')
      if (url.endsWith('/auth/login')) {
        assert.equal(init.method, 'POST')
        assert.deepEqual(Object.keys(JSON.parse(init.body)).sort(), ['email', 'password'])
        return Response.json(reviewer)
      }
      assert.ok(url.endsWith('/auth/me'))
      return Response.json(reviewer)
    }
    // A pre-login unauthenticated response must not overwrite the new user.
    let finishOldCheck
    const oldCheck = loginClient.fetchQuery({ queryKey: ['session'], staleTime: 0,
      queryFn: () => new Promise(resolve => { finishOldCheck = resolve }) }).catch(() => {})
    const loggedIn = await loginSession(loginClient, { email: 'reviewer@example.test', password: 'isolated-test-only' })
    finishOldCheck(null)
    await oldCheck
    assert.equal(destination(loggedIn), '/queue')
    assert.equal(loginObserver.getCurrentResult().data.role, 'REVIEWER')
    assert.ok(calls[0].endsWith('/auth/login'))
    assert.ok(calls[1].endsWith('/auth/me'))
    // A successful POST without a usable cookie must never enter the queue.
    globalThis.fetch = async url => url.endsWith('/auth/login') ? Response.json(reviewer)
      : Response.json({ error: { message: 'Sign in to continue.' } }, { status: 401 })
    await assert.rejects(loginSession(loginClient, { email: 'reviewer@example.test', password: 'isolated-test-only' }), /session cookie was not accepted/)
    assert.equal(loginObserver.getCurrentResult().data, null)
    globalThis.fetch = async () => Response.json({ error: { message: 'Invalid email or password.' } }, { status: 401 })
    await assert.rejects(loginSession(loginClient, { email: 'reviewer@example.test', password: 'wrong' }), /Invalid email or password/)
    globalThis.fetch = async () => { throw new TypeError('Failed to fetch') }
    await assert.rejects(loginSession(loginClient, { email: 'reviewer@example.test', password: 'isolated-test-only' }), /Failed to fetch/)
  } finally {
    globalThis.fetch = savedFetch
    stopLogin()
    loginClient.clear()
  }
  const artwork = await readFile('public/login-image.png')
  assert.equal(artwork.subarray(1, 4).toString(), 'PNG')
  const bundledArtwork = await readFile('dist/login-image.png')
  assert.deepEqual(bundledArtwork, artwork)
  console.log('PASS: login cookie confirmation, stale-session race, login failures, provider-scoped HTTP logout and failure handling, mounted login/logout session observers, role destinations, account-change cache purge, expired-session cache purge, original artwork included unchanged in build.')
} finally {
  await server.close()
}
