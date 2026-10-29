import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef } from 'react'
import { num } from '../lib/format'
import { PORT } from '../lib/seed'
import type { PurchaseOrder, SKU, Supplier } from '../lib/types'
import './supplymap.css'

interface Props {
  suppliers: Supplier[]
  purchaseOrders: PurchaseOrder[]
  skus: SKU[]
  selectedSupplier?: string | null
  onSelectSupplier?: (id: string) => void
}

const riskColor = (r: number) => (r < 0.3 ? 'var(--ux-mint)' : r < 0.5 ? 'var(--ux-warn)' : 'var(--ux-danger)')
// Esri gray canvas basemaps: keyless, with matching light and dark styles
const tiles = (theme: string) => `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${theme === 'dark' ? 'Dark' : 'Light'}_Gray_Base/MapServer/tile/{z}/{y}/{x}`
const currentTheme = () => document.documentElement.dataset.theme ?? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')

// US longitudes shifted by +360 so routes run across the Pacific
const portLL: [number, number] = [PORT.lat, PORT.lng + 360]

function arc(from: [number, number], to: [number, number], n = 60): [number, number][] {
  const mid: [number, number] = [(from[0] + to[0]) / 2 + (to[1] - from[1]) * 0.18, (from[1] + to[1]) / 2]
  return Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n, u = 1 - t
    return [u * u * from[0] + 2 * u * t * mid[0] + t * t * to[0], u * u * from[1] + 2 * u * t * mid[1] + t * t * to[1]]
  })
}

const SHIP = '<svg viewBox="0 0 16 16"><path d="M2 10l1.5 3h9L14 10M3.5 10V6.5h9V10M7 6.5V3.5h3v3"/></svg>'
const ANCHOR = '<svg viewBox="0 0 16 16"><circle cx="8" cy="3.5" r="1.5"/><path d="M8 5v9M3 9a5 5 0 0 0 10 0M5.5 7.5h5"/></svg>'

export function SupplyMap({ suppliers, purchaseOrders, skus, selectedSupplier, onSelectSupplier }: Props) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layer = useRef<L.LayerGroup | null>(null)
  const onSel = useRef(onSelectSupplier)
  onSel.current = onSelectSupplier

  useEffect(() => {
    const m = L.map(el.current!, { center: [26, 172], zoom: 2.6, zoomSnap: 0.1, worldCopyJump: false, attributionControl: true, scrollWheelZoom: false })
    const tl = L.tileLayer(tiles(currentTheme()), {
      maxZoom: 10,
      attribution: 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ',
    }).addTo(m)
    layer.current = L.layerGroup().addTo(m)
    map.current = m
    const onTheme = () => tl.setUrl(tiles(currentTheme()))
    window.addEventListener('sl-theme', onTheme)
    const ro = new ResizeObserver(() => m.invalidateSize())
    ro.observe(el.current!)
    return () => {
      window.removeEventListener('sl-theme', onTheme)
      ro.disconnect()
      m.remove()
      map.current = null
      layer.current = null
    }
  }, [])

  useEffect(() => {
    const g = layer.current
    if (!g) return
    g.clearLayers()
    const routes: Record<string, [number, number][]> = {}
    for (const s of suppliers) {
      const pts = arc([s.lat, s.lng], portLL)
      routes[s.id] = pts
      const on = selectedSupplier === s.id
      const dim = !!selectedSupplier && !on
      L.polyline(pts, { color: getComputedStyle(document.documentElement).getPropertyValue('--ux-accent').trim() || '#6A57F2', weight: on ? 3.2 : 2, className: 'sm-route' + (on ? ' is-on' : '') + (dim ? ' is-dim' : ''), interactive: false }).addTo(g)
    }
    for (const s of suppliers) {
      const on = selectedSupplier === s.id
      const icon = L.divIcon({
        className: '',
        iconSize: [18, 18],
        iconAnchor: [9, 9],
        html: `<div class="sm-pin${on ? ' is-on' : ''}" style="--c:${riskColor(s.risk_score)}"><span class="sm-pin-lbl">${s.city}</span></div>`,
      })
      L.marker([s.lat, s.lng], { icon, keyboard: true, title: `${s.name}, ${s.city}` })
        .bindTooltip(`<b>${s.name}</b><br>${s.city}, ${s.country}<br>Lead ${s.lead_time_mean_days}±${s.lead_time_std_days} d · risk ${s.risk_score.toFixed(2)}`, { direction: 'top', offset: [0, -10] })
        .on('click', () => onSel.current?.(s.id))
        .addTo(g)
    }
    L.marker(portLL, { icon: L.divIcon({ className: '', iconSize: [26, 26], iconAnchor: [13, 13], html: `<div class="sm-port">${ANCHOR}</div>` }), title: PORT.name })
      .bindTooltip(`<b>${PORT.name}</b><br>${PORT.city}`, { direction: 'top', offset: [0, -12] })
      .addTo(g)
    for (const po of purchaseOrders) {
      if (po.status !== 'in_transit') continue
      const pts = routes[po.supplier_id]
      if (!pts) continue
      const p = Math.max(0.03, Math.min(0.97, -po.ship_day / Math.max(1, po.eta_day - po.ship_day)))
      const at = pts[Math.round(p * (pts.length - 1))]
      const sku = skus.find(k => k.id === po.sku_id)
      L.marker(at, { icon: L.divIcon({ className: '', iconSize: [22, 22], iconAnchor: [11, 11], html: `<div class="sm-ship">${SHIP}</div>` }) })
        .bindTooltip(`<b>${po.id.toUpperCase()}</b> · ${sku?.name ?? po.sku_id}<br>${num(po.quantity)} units · ETA day ${po.eta_day} · ${Math.round(p * 100)}% of the way`, { direction: 'top', offset: [0, -10] })
        .addTo(g)
    }
  }, [suppliers, purchaseOrders, skus, selectedSupplier])

  useEffect(() => {
    const s = suppliers.find(x => x.id === selectedSupplier)
    if (s && map.current) map.current.flyTo([(s.lat + portLL[0]) / 2 + 6, (s.lng + portLL[1]) / 2], 2.8, { duration: 0.8 })
  }, [selectedSupplier, suppliers])

  return (
    <div className="sm-wrap">
      <div ref={el} className="sm-map" role="region" aria-label="Supply routes map" />
      <div className="sm-legend" aria-hidden="true">
        <span><i style={{ ['--c' as string]: 'var(--ux-mint)' }} />Low risk</span>
        <span><i style={{ ['--c' as string]: 'var(--ux-warn)' }} />Medium</span>
        <span><i style={{ ['--c' as string]: 'var(--ux-danger)' }} />High</span>
        <span><i style={{ ['--c' as string]: 'var(--ux-accent)' }} />In transit</span>
        <span><i className="sq" style={{ ['--c' as string]: 'var(--ux-ink)' }} />Port</span>
      </div>
    </div>
  )
}
