import { useNavigate } from 'react-router-dom'
import type { User } from './session'
import { authError, useLogout } from './session'
export function SessionControls({ user }: { user: User }) {
  const logout = useLogout()
  const navigate = useNavigate()
  return <div className="session-controls">
    <span>{user.display_name}<small>{user.role === 'REVIEWER' ? 'Reviewer' : 'Employee'}</small></span>
    <button type="button" disabled={logout.isPending} onClick={() => logout.mutate(undefined, { onSuccess: () => navigate('/login', { replace: true }) })}>{logout.isPending ? 'Signing out…' : 'Log out'}</button>
    {logout.isError && <p role="alert">{authError(logout.error)} Your session has not been signed out.</p>}
  </div>
}
