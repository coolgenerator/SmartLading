// Brand overview (PRD 品牌概览): F1 business state + F5 alert entry.
import { useMemo, useRef, useState } from 'react'
import { SupplyMap } from '../components/SupplyMap'
import { BubbleSlider } from '../components/lucian/BubbleSlider'
import { MetricCard, type Metric } from '../components/lucian/MetricCard'
import { toast } from '../components/lucian/Toaster'
import { defaultProb, safetyLine } from '../lib/build'
import { num, pct, usd, usdK } from '../lib/format'
import { mulberry32 } from '../lib/rng'
import { useStore } from '../lib/store'
import type { SKU, Supplier } from '../lib/types'
import './overview.css'

// Deterministic 24-point recent history that ends at the current value.
function history(end: number, seed: number, vol: number): number[] {
  const rand = mulberry32(seed)
  const out = [end]
  for (let i = 1; i < 24; i++) out.unshift(out[0] * (1 + (rand() - 0.47) * vol))
  return out
}

const riskTone = (r: number) => (r < 0.3 ? 'ok' : r < 0.5 ? 'warn' : 'bad')
const riskColor = (r: number) => (r < 0.3 ? 'var(--ux-mint)' : r < 0.5 ? 'var(--ux-warn)' : 'var(--ux-danger)')
const riskLabel = (r: number) => (r < 0.3 ? 'Low risk' : r < 0.5 ? 'Medium risk' : 'High risk')

type SortKey = 'name' | 'category' | 'hts_code' | 'tariff_rate' | 'on_hand' | 'cover' | 'price'

export function Overview() {
  const st = useStore()
  const { brand, suppliers, skus, purchaseOrders, alerts } = st
  const [focus, setFocus] = useState<string | null>(null)

  const metrics: Metric[] = useMemo(() => {
    const sl = safetyLine(brand)
    const cash = history(brand.cash_balance, 11, 0.05)
    const credit = history(brand.credit_limit, 23, 0.015)
    const safety = history(sl, 37, 0.02)
    const d = (s: number[]) => (s[s.length - 1] - s[0]) / (s[0] || 1)
    return [
      { name: 'Cash', title: 'Cash on hand', text: usd(brand.cash_balance), delta: d(cash), deltaLabel: 'vs 24 days ago', series: cash },
      { name: 'Credit', title: 'Credit headroom', text: usd(brand.credit_limit), delta: d(credit), deltaLabel: 'available line', series: credit },
      { name: 'Safety', title: 'Cash safety line', text: usd(sl), delta: d(safety), deltaLabel: `${brand.safety_line_days} days of fixed cost`, series: safety },
    ]
  }, [brand])

  const open = alerts.filter(a => !a.acknowledged)
  const active = purchaseOrders.filter(p => p.status !== 'arrived').sort((a, b) => a.eta_day - b.eta_day)
  const inTransit = purchaseOrders.filter(p => p.status === 'in_transit')

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{brand.name}</h1>
          <p className="page-sub">Business state · version <span className="num">{brand.state_version}</span> · {skus.length} SKUs · {suppliers.length} suppliers</p>
        </div>
        <div className="ov-actions">
          {st.events.map(e => (
            <button key={e.id} type="button" className="btn danger" disabled={st.injected.includes(e.id)} title={e.description} onClick={() => st.injectEvent(e)}>
              {st.injected.includes(e.id) ? '✓ ' : '⚡ '}{e.name}
            </button>
          ))}
          <button type="button" className="btn" onClick={st.reset}>Reset demo</button>
        </div>
      </header>

      <section className="ov-hero">
        <div className="card ov-map">
          <div className="ov-map-head">
            <span className="card-title">Supply routes · Asia → Long Beach</span>
            <span className="stats">
              <span><b>{inTransit.length}</b>in transit</span>
              <span><b>{num(inTransit.reduce((a, p) => a + p.quantity, 0))}</b>units on water</span>
            </span>
          </div>
          <SupplyMap suppliers={suppliers} purchaseOrders={purchaseOrders} skus={skus} selectedSupplier={focus} onSelectSupplier={id => setFocus(f => (f === id ? null : id))} />
        </div>
        <MetricCard metrics={metrics} header={`v${brand.state_version}`} />
      </section>

      <section className="ov-row">
        <div className="card">
          <div className="ov-section-head">
            <span className="card-title">Alerts</span>
            {open.length > 0 && <span className="chip bad">{open.length} open</span>}
          </div>
          {open.length === 0 ? (
            <div className="ov-empty"><i aria-hidden="true">✓</i><b>No open alerts</b><span>Inject an event above to see how it hits orders on the water.</span></div>
          ) : (
            <div className="ov-alerts">
              {open.map(a => (
                <div key={a.id} className="ov-alert" role="alert">
                  <span className="ov-alert-ic" aria-hidden="true">!</span>
                  <div>
                    <p>{a.message}</p>
                    <small>Next step: {a.next_step}</small>
                    <div className="figs">
                      {a.extra_cost > 0 && <span>Extra cost <b>{usd(a.extra_cost)}</b></span>}
                      <span>Cash gap <b>{usd(a.cash_gap)}</b></span>
                    </div>
                  </div>
                  <button type="button" className="btn" onClick={() => st.ackAlert(a.id)}>Acknowledge</button>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="card">
          <div className="ov-section-head">
            <span className="card-title">Open purchase orders</span>
            <span className="muted">{active.length} orders</span>
          </div>
          <div className="ov-pos">
            {active.map(po => {
              const sku = skus.find(s => s.id === po.sku_id)
              const sup = suppliers.find(s => s.id === po.supplier_id)
              const p = po.status === 'in_transit' ? Math.max(0, Math.min(1, -po.ship_day / Math.max(1, po.eta_day - po.ship_day))) : 0
              return (
                <div key={po.id} className="ov-po">
                  <div>
                    <b>{po.id.toUpperCase()} · {sku?.name}</b>
                    <small> {num(po.quantity)} units from {sup?.city}</small>
                  </div>
                  <div className="eta">
                    <span className={'chip ' + (po.status === 'in_transit' ? 'accent' : '')}>{po.status === 'in_transit' ? 'In transit' : 'Planned'}</span>{' '}
                    {po.status === 'in_transit' ? `ETA day ${po.eta_day}` : `Ships day ${po.ship_day}`}
                  </div>
                  <div className="ov-bar" role="progressbar" aria-label={`${po.id} progress`} aria-valuenow={Math.round(p * 100)} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${p * 100}%` }} /></div>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      <section className="ov-section">
        <div className="ov-section-head">
          <span className="card-title">Suppliers</span>
          <span className="muted">Edits bump the state version and mark open scenarios out of date</span>
        </div>
        <div className="ov-sups">
          {suppliers.map(s => (
            <SupplierCard key={s.id} s={s} on={focus === s.id} onFocus={() => setFocus(f => (f === s.id ? null : s.id))} onPatch={p => st.patchSupplier(s.id, p)} />
          ))}
        </div>
      </section>

      <section className="card ov-section">
        <SkuTable skus={skus} />
      </section>
    </div>
  )
}

function SupplierCard({ s, on, onFocus, onPatch }: { s: Supplier; on: boolean; onFocus: () => void; onPatch: (p: Partial<Supplier>) => void }) {
  const [edit, setEdit] = useState(false)
  const told = useRef(false)
  const patch = (p: Partial<Supplier>) => {
    onPatch(p)
    if (!told.current) {
      told.current = true
      toast({ kind: 'info', title: `${s.name} updated`, body: 'Open scenarios now need a re-run' })
    }
  }
  return (
    <article className={'card ov-sup' + (on ? ' is-on' : '')} onClick={onFocus}>
      <div className="ov-sup-top">
        <div><h3>{s.name}</h3><small>{s.city}, {s.country}</small></div>
        <span className={'chip ' + riskTone(s.risk_score)}>{riskLabel(s.risk_score)}</span>
      </div>
      <div className="ov-kv">
        <div><small>Lead time</small><b>{s.lead_time_mean_days}<span className="muted"> ±{s.lead_time_std_days} d</span></b></div>
        <div><small>MOQ</small><b>{num(s.moq)}</b></div>
        <div><small>Prepay</small><b>{pct(s.default_prepay_ratio)}</b></div>
        <div><small>Default prob.</small><b>{pct(defaultProb(s), 1)}</b></div>
      </div>
      <div className="ov-risk" aria-label={`Risk score ${s.risk_score.toFixed(2)}`}><span style={{ width: `${s.risk_score * 100}%`, ['--c' as string]: riskColor(s.risk_score) }} /></div>
      {edit && (
        <div className="ov-edit" onClick={e => e.stopPropagation()}>
          <BubbleSlider label="Lead time (mean)" hint="days" min={10} max={90} step={1} value={s.lead_time_mean_days} onChange={v => patch({ lead_time_mean_days: v })} format={v => `${v}d`} ticks={[10, 50, 90]} />
          <BubbleSlider label="Minimum order" hint="units" min={0} max={5000} step={100} value={s.moq} onChange={v => patch({ moq: v })} format={v => usdK(v).replace('$', '')} ticks={[0, 2500, 5000]} />
          <BubbleSlider label="Prepay ratio" hint="deposit" min={0} max={0.8} step={0.05} value={s.default_prepay_ratio} onChange={v => patch({ default_prepay_ratio: Math.round(v * 100) / 100 })} format={v => pct(v)} ticks={[0, 0.4, 0.8]} />
          <BubbleSlider label="Risk score" hint="0–1" min={0} max={1} step={0.01} value={s.risk_score} onChange={v => patch({ risk_score: Math.round(v * 100) / 100 })} format={v => v.toFixed(2)} ticks={[0, 0.5, 1]} />
        </div>
      )}
      <div className="ov-sup-foot">
        <button type="button" className={'btn' + (edit ? ' primary' : '')} aria-expanded={edit} onClick={e => { e.stopPropagation(); setEdit(x => !x); told.current = false }}>
          {edit ? 'Done' : 'Edit terms'}
        </button>
      </div>
    </article>
  )
}

function SkuTable({ skus }: { skus: SKU[] }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'cover', dir: 1 })
  const cover = (s: SKU) => s.on_hand / Math.max(1, s.daily_demand)
  const rows = [...skus].sort((a, b) => {
    const va = sort.key === 'cover' ? cover(a) : a[sort.key]
    const vb = sort.key === 'cover' ? cover(b) : b[sort.key]
    return (typeof va === 'string' ? va.localeCompare(vb as string) : (va as number) - (vb as number)) * sort.dir
  })
  const maxCover = Math.max(...skus.map(cover))
  const cols: [SortKey, string, boolean][] = [
    ['name', 'SKU', false], ['category', 'Category', false], ['hts_code', 'HTS', false], ['tariff_rate', 'Tariff', true],
    ['on_hand', 'On hand', true], ['cover', 'Days of cover', false], ['price', 'Price', true],
  ]
  return (
    <>
      <div className="ov-section-head">
        <span className="card-title">Inventory</span>
        <span className="muted">{skus.length} SKUs · sorted by {cols.find(c => c[0] === sort.key)?.[1].toLowerCase()}</span>
      </div>
      <div className="ov-table-wrap">
        <table className="ov-table">
          <thead>
            <tr>
              {cols.map(([k, label, right]) => (
                <th key={k} className={right ? 'r' : ''} aria-sort={sort.key === k ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
                  <button type="button" onClick={() => setSort(s => ({ key: k, dir: s.key === k ? (-s.dir as 1 | -1) : 1 }))}>
                    {label}{sort.key === k ? (sort.dir === 1 ? ' ↑' : ' ↓') : ''}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(s => {
              const c = cover(s)
              const tone = c < 30 ? 'var(--ux-danger)' : c < 50 ? 'var(--ux-warn)' : 'var(--ux-mint)'
              return (
                <tr key={s.id}>
                  <td className="name">{s.name}</td>
                  <td>{s.category}</td>
                  <td className="muted">{s.hts_code}</td>
                  <td className="r">{pct(s.tariff_rate, s.tariff_rate * 1000 % 10 ? 1 : 0)}</td>
                  <td className="r">{num(s.on_hand)}</td>
                  <td><div className="ov-cover"><span><i style={{ width: `${(c / maxCover) * 100}%`, ['--c' as string]: tone }} /></span><b>{Math.round(c)}d</b></div></td>
                  <td className="r">{usd(s.price)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}
