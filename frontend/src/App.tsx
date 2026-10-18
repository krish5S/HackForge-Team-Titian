import { BrowserRouter, Link, Navigate, NavLink, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { Overview } from './pages/Overview'
import { EmployeePage } from './pages/Employee'
import { Login } from './pages/Login'
import { authError, destination, queryClient, useSession, type User } from './auth/session'
import { SessionControls } from './auth/SessionControls'
import './App.css'

function ReviewerLayout({ user }: { user: User }) {
  const location = useLocation()
  return <><header className="site-header">
    <Link className="brand" to="/queue">The Receipt Graveyard<small>Expense review with evidence.</small></Link>
    <nav aria-label="Main navigation">
      <NavLink to="/queue" className={() => location.pathname === '/queue' || location.pathname.startsWith('/receipts/') ? 'active' : ''}>Overview</NavLink>
      <NavLink to="/policy">Policy</NavLink><NavLink to="/month-replay">Month Replay</NavLink>
    </nav><SessionControls user={user} />
  </header><Outlet /></>
}
function Shell() {
  const session = useSession()
  if (session.isPending) return <main className="session-state" role="status">Checking your session…</main>
  if (session.isError) return <main className="session-state"><h1>Unable to connect</h1><p role="alert">{authError(session.error)}</p><button onClick={() => session.refetch()}>Retry</button></main>
  const user = session.data
  if (!user) return <Routes><Route path="/login" element={<Login />} /><Route path="*" element={<Navigate to="/login" replace />} /></Routes>
  return <Routes>
    <Route path="/login" element={<Navigate to={destination(user)} replace />} />
    <Route path="/" element={<Navigate to={destination(user)} replace />} />
    <Route path="/employee" element={user.role === 'EMPLOYEE' ? <EmployeePage user={user} /> : <Navigate to="/queue" replace />} />
    <Route element={user.role === 'REVIEWER' ? <ReviewerLayout user={user} /> : <Navigate to="/employee" replace />}>
      <Route path="/queue" element={<Overview />} /><Route path="/receipts/:id" element={<Overview />} />
      { [['policy', 'Policy'], ['month-replay', 'Month Replay']].map(([path, name]) => <Route key={path} path={`/${path}`} element={<main className="placeholder"><span className="eyebrow">Coming soon</span><h1>{name}</h1><p>This page is not available yet.</p><Link to="/queue">Return to expense overview →</Link></main>} />) }
    </Route>
    <Route path="*" element={<Navigate to={destination(user)} replace />} />
  </Routes>
}
export default function App() {
  return <QueryClientProvider client={queryClient}><BrowserRouter><Shell /></BrowserRouter></QueryClientProvider>
}
