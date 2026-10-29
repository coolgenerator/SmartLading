import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { OrbitLoader } from './components/lucian/OrbitLoader'
import { SideRail, type RailItem } from './components/lucian/SideRail'
import { ThemeToggle } from './components/lucian/ThemeToggle'
import { Toaster } from './components/lucian/Toaster'
import { StoreProvider, useStore } from './lib/store'
import { Negotiation } from './pages/Negotiation'
import { Overview } from './pages/Overview'
import { Signals } from './pages/Signals'
import { Workbench } from './pages/Workbench'

const icon = (d: string) => <svg viewBox="0 0 24 24" aria-hidden="true"><path d={d} /></svg>

function Boot({ error }: { error: string | null }) {
  return (
    <div className="boot">
      <OrbitLoader
        title={error ? 'Can’t reach the SmartLading API' : 'Loading Harbor & Pine'}
        sub={error ? 'Start it with: uv run uvicorn smartlading.api:app --port 8000 (Postgres on 55461), then reload.' : 'Fetching brand state from the server'}
      />
    </div>
  )
}

function Shell() {
  const s = useStore()
  if (!s.ready) return <Boot error={s.loadError} />
  const items: RailItem[] = [
    { to: '/', label: 'Overview', icon: icon('M4 11l8-6.5 8 6.5V19a1 1 0 0 1-1 1h-4.5v-5h-5v5H5a1 1 0 0 1-1-1z'), badge: s.alerts.filter(a => !a.acknowledged).length },
    { to: '/workbench', label: 'Workbench', icon: icon('M4 19V5M4 19h16M8 15l3-4 3 2 5-6') },
    { to: '/signals', label: 'Risk signals', icon: icon('M12 3l9 16H3zM12 10v4M12 17h.01'), badge: s.signals.filter(x => x.status === 'pending').length },
    { to: '/negotiation', label: 'Negotiation', icon: icon('M5 5.5h14a1 1 0 0 1 1 1V16a1 1 0 0 1-1 1h-7l-4.5 3.5V17H5a1 1 0 0 1-1-1V6.5a1 1 0 0 1 1-1z') },
  ]
  return (
    <SideRail items={items} brand={s.brand.name} sub="Demo brand · 20 SKUs">
      <div className="topbar">
        <span className="chip num">State v{s.brand.state_version}{s.stale ? ' · results stale' : ''}</span>
        <ThemeToggle />
      </div>
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/workbench" element={<Workbench />} />
        <Route path="/signals" element={<Signals />} />
        <Route path="/negotiation" element={<Negotiation />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </SideRail>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <StoreProvider>
        <Shell />
        <Toaster />
      </StoreProvider>
    </BrowserRouter>
  )
}
