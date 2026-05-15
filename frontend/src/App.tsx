import { lazy, Suspense, useEffect, useState } from 'react'
import { NavLink, Outlet, Route, Routes, useLocation, Link } from 'react-router-dom'
import Landing from './pages/Landing'
import { BrandMark, Loading } from './components/ui'
import { useAiStatus } from './lib/queries'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const Queue = lazy(() => import('./pages/Queue'))
const Meter = lazy(() => import('./pages/Meter'))
const Zones = lazy(() => import('./pages/Zones'))
const Copilot = lazy(() => import('./pages/Copilot'))
const Alerts = lazy(() => import('./pages/Alerts'))
const Quality = lazy(() => import('./pages/Quality'))
const Ops = lazy(() => import('./pages/Ops'))

const NAV = [
  { to: '/app', label: 'Overview', end: true },
  { to: '/app/queue', label: 'Inspection queue' },
  { to: '/app/zones', label: 'Zones & transformers' },
  { to: '/app/alerts', label: 'Alerts' },
  { to: '/app/copilot', label: 'Ask the data' },
  null,
  { to: '/app/quality', label: 'Accuracy & ROI' },
  { to: '/app/ops', label: 'AI operations' },
]

function Shell() {
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  const status = useAiStatus()
  useEffect(() => { setOpen(false); window.scrollTo(0, 0) }, [loc.pathname])
  const ai = status.data?.agent_enabled
  return (
    <div className="shell">
      <div className="topbar">
        <Link to="/" className="brand"><BrandMark /><span className="brand-name">VidyutDrishti</span></Link>
        <button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls="sidebar">{open ? 'Close' : 'Menu'}</button>
      </div>
      <aside id="sidebar" className={`sidebar${open ? ' open' : ''}`}>
        <Link to="/" className="brand"><BrandMark /><span className="brand-name">VidyutDrishti</span></Link>
        <nav className="nav" aria-label="Main">
          {NAV.map((n, i) => n === null ? <div key={i} className="nav-sep" /> : (
            <NavLink key={n.to} to={n.to} end={n.end}>{n.label}</NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span>
            <i className="dot" style={{ background: status.isError ? '#F97066' : status.data ? '#47CD89' : '#98A2B3' }} />
            {status.isError ? 'Server unreachable' : status.data ? (status.data.data_ready ? 'Data loaded' : 'Loading data…') : 'Connecting…'}
          </span>
          {status.data && <span>AI model: {ai ? status.data.llm_providers.join(', ') : 'not configured (rule-based answers)'}</span>}
          <span>Synthetic demo network · <a href="https://github.com/Asha0509/vidyutdrishti" target="_blank" rel="noreferrer">Source</a></span>
        </div>
      </aside>
      <main className="main" id="main">
        <Suspense fallback={<Loading />}><Outlet /></Suspense>
      </main>
    </div>
  )
}

function NotFound() {
  return (
    <div className="section">
      <h1>Page not found</h1>
      <p className="muted" style={{ margin: '0.6rem 0 1.2rem' }}>That address doesn't exist.</p>
      <Link className="btn btn-primary" to="/app">Go to the overview</Link>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/app" element={<Shell />}>
        <Route index element={<Dashboard />} />
        <Route path="queue" element={<Queue />} />
        <Route path="meters/:id" element={<Meter />} />
        <Route path="zones" element={<Zones />} />
        <Route path="copilot" element={<Copilot />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="quality" element={<Quality />} />
        <Route path="ops" element={<Ops />} />
        <Route path="*" element={<NotFound />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}
