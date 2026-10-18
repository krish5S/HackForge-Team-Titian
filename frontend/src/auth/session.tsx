import { useMutation, useQuery, useQueryClient, QueryCache, QueryClient } from '@tanstack/react-query'
import { ApiError, request } from '../api/client'

export interface User {
  id: string
  email: string
  display_name: string
  role: 'EMPLOYEE' | 'REVIEWER'
  employee_id: string | null
}
const sessionKey = ['session'] as const
export const destination = (user: User) => user.role === 'REVIEWER' ? '/queue' : '/employee'

// Never retain another account's receipt, image, or selected evidence caches.
export const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (error instanceof ApiError && error.status === 401 && query.queryKey[0] !== 'session') {
        void replaceSession(null)
      }
    },
    onSuccess: (data, query) => {
      if (query.queryKey[0] === 'session') {
        const next = (data as User | null)?.id ?? null
        if (lastUserId !== undefined && lastUserId !== next) {
          void queryClient.cancelQueries({ predicate: q => q.queryKey[0] !== 'session' })
          queryClient.removeQueries({ predicate: q => q.queryKey[0] !== 'session' })
        }
        lastUserId = next
      }
    },
  }),
  defaultOptions: { queries: {
    staleTime: 30_000,
    retry: (attempt, error) => !(error instanceof ApiError && [401, 403].includes(error.status)) && attempt < 1,
    refetchOnWindowFocus: false,
  } },
})
let lastUserId: string | null | undefined

export async function replaceSession(user: User | null, client: QueryClient = queryClient) {
  await client.cancelQueries()
  // Keep the session query connected to its mounted observers. Removing it
  // would leave Shell watching the old null session after a successful login.
  client.removeQueries({ predicate: query => query.queryKey[0] !== 'session' })
  lastUserId = user?.id ?? null
  client.setQueryData(sessionKey, user)
}

export function useSession() {
  return useQuery({
    queryKey: sessionKey,
    queryFn: async ({ signal }) => {
      try { return await request<User>('/auth/me', signal) }
      catch (error) {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
    staleTime: 0,
    refetchOnWindowFocus: true,
    refetchInterval: 60_000,
    retry: false,
  })
}

export async function loginSession(client: QueryClient, input: { email: string; password: string }) {
  // Stop an initial or background unauthenticated check before changing sessions.
  await client.cancelQueries()
  await request<User>('/auth/login', undefined, false, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  })
  let user: User
  try {
    // Only enter a protected route once the server recognizes the cookie.
    user = await request<User>('/auth/me')
  } catch (error) {
    await replaceSession(null, client)
    if (error instanceof ApiError && error.status === 401) {
      throw new ApiError('Sign-in succeeded, but the session cookie was not accepted. Open http://localhost:5173, allow cookies, and try again. Local HTTP requires AUTH_COOKIE_SECURE=false.', 401)
    }
    throw error
  }
  await replaceSession(user, client)
  return user
}

export function useLogin() {
  const client = useQueryClient()
  return useMutation({ mutationFn: (input: { email: string; password: string }) => loginSession(client, input) })
}

export async function logoutSession(client: QueryClient) {
  await request<void>('/auth/logout', undefined, false, { method: 'POST' })
  await replaceSession(null, client)
}

export function useLogout() {
  // Use the mounted provider's client, including after development hot updates.
  const client = useQueryClient()
  return useMutation({ mutationFn: () => logoutSession(client) })
}

export function authError(error: Error) {
  return error instanceof ApiError ? error.message : 'Unable to reach the server. Check your connection and try again.'
}
