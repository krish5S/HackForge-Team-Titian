import { useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { authError, destination, useLogin } from '../auth/session'
import './auth.css'

export function Login() {
  const [visible, setVisible] = useState(false)
  const pending = useRef(false)
  const login = useLogin()
  const navigate = useNavigate()
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending.current) return
    pending.current = true
    const form = event.currentTarget
    const fields = new FormData(form)
    try {
      const user = await login.mutateAsync({ email: String(fields.get('email')).trim(), password: String(fields.get('password')) })
      form.reset()
      navigate(destination(user), { replace: true })
    } catch { /* The form displays the mutation error below. */ }
    finally { pending.current = false }
  }
  return <main className="auth-page"><div className="auth-shell">
    <section className="auth-content" aria-labelledby="login-heading">
      <div className="auth-brand">The Receipt Graveyard<span>Expense review with evidence.</span></div>
      <div className="auth-form-wrap">
        <h1 id="login-heading">Welcome back</h1>
        <p className="auth-subtitle">Sign in to submit expenses or review receipts.</p>
        <form onSubmit={submit} aria-busy={login.isPending}>
          <label htmlFor="email">Email address</label>
          <input id="email" name="email" type="email" autoComplete="username" placeholder="you@company.com" maxLength={254} required disabled={login.isPending} />
          <label htmlFor="password">Password</label>
          <div className="auth-password"><input id="password" name="password" type={visible ? 'text' : 'password'} autoComplete="current-password" maxLength={1024} required disabled={login.isPending} /><button type="button" aria-label={visible ? 'Hide password' : 'Show password'} aria-controls="password" aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? 'Hide' : 'Show'}</button></div>
          {login.isError && <p className="auth-error" role="alert">{authError(login.error)}</p>}
          <button className="auth-submit" type="submit" disabled={login.isPending}>{login.isPending ? 'Signing in…' : 'Sign in'}</button>
          <p className="auth-support">Use the account provided by your organization.</p>
        </form>
      </div>
      <div className="auth-footnote">A little clarity for every expense.</div>
    </section>
    <div className="auth-art"><img src="/login-image.png" alt="Finance team reviewing receipts. Every receipt. A clear reason. The Receipt Graveyard." /></div>
  </div></main>
}
