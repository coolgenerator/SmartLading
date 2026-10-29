import { useEffect, useMemo, useRef, useState } from 'react'
import { BubbleSlider } from '../components/lucian/BubbleSlider'
import { FanChart } from '../components/lucian/FanChart'
import { RollingNumber } from '../components/lucian/MetricCard'
import { OrbitLoader } from '../components/lucian/OrbitLoader'
import { safetyLine } from '../lib/build'
import { num, pct, RISK_LABEL, runway, usd, usdK } from '../lib/format'
import { useStore } from '../lib/store'
import type { ScenarioOption } from '../lib/types'
import './workbench.css'

const LABELS = ['A', 'B', 'C']
const DEFAULT_Q = [5000, 8000, 11000]
const MAX_Q = 20000

interface Draft { quantity: number; prepay: number | null }

export function Workbench() {
  const st = useStore()
  const [skuId, setSkuId] = useState(st.scenario?.sku_id ?? 'sku_07')
  const [supId, setSupId] = useState(st.scenario?.supplier_id ?? 'sup_everbright')
  const [seed, setSeed] = useState(st.scenario?.seed ?? 42)
  const [drafts, setDrafts] = useState<Draft[]>(
    st.scenario?.options.map(o => ({ quantity: o.quantity, prepay: o.prepay_ratio })) ?? DEFAULT_Q.map(q => ({ quantity: q, prepay: null })),
  )
  const [running, setRunning] = useState(false)
  const [fanId, setFanId] = useState<string | null>(null)

  const sku = st.skus.find(s => s.id === skuId)!
  const supplierChoices = st.suppliers.filter(s => st.offers.some(o => o.sku_id === skuId && o.supplier_id === s.id))
  const supplier = supplierChoices.find(s => s.id === supId) ?? supplierChoices[0]
  const offer = st.offerFor(skuId, supplier.id)!

  useEffect(() => {
    if (!supplierChoices.some(s => s.id === supId)) setSupId(supplierChoices[0].id)
  }, [skuId]) // eslint-disable-line react-hooks/exhaustive-deps

  const errors = drafts.map(d => (d.quantity < supplier.moq ? `Below MOQ of ${num(supplier.moq)} units` : null))
  const invalid = errors.some(Boolean)

  const options: ScenarioOption[] = drafts.map((d, i) => ({ id: `opt_${LABELS[i]}`, label: LABELS[i], quantity: d.quantity, prepay_ratio: d.prepay }))

  const run = async () => {
    if (invalid || running) return
    setRunning(true)
    try { await st.runScenario(skuId, supplier.id, options, seed) } finally { setRunning(false) }
  }

  // auto-run once on first mount
  const ran = useRef(false)
  useEffect(() => {
    if (ran.current || st.scenario) return
    ran.current = true
    void run()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const scn = st.scenario
  const result = scn?.result
  const rec = scn?.recommendation
  const labelOf = (id: string) => scn?.options.find(o => o.id === id)?.label ?? id
  const activeFan = fanId && result?.options.some(o => o.option_id === fanId) ? fanId : rec?.recommended_option_id ?? result?.options[0]?.option_id ?? ''
  const selected = scn?.selected_option_id ?? null
  const differs = !!rec && !!selected && selected !== rec.recommended_option_id
  const bestMetrics = result?.options.find(o => o.option_id === rec?.recommended_option_id)

  const setDraft = (i: number, patch: Partial<Draft>) => setDrafts(ds => ds.map((d, j) => (j === i ? { ...d, ...patch } : d)))

  return (
    <div className="page wb">
      <header className="page-head">
        <div>
          <h1>Decision workbench</h1>
          <p className="page-sub">Compare 2–3 order quantities on one purchase order</p>
        </div>
        <div className="wb-head-actions">
          <button type="button" className="btn primary" onClick={run} disabled={invalid || running} aria-disabled={invalid || running}>
            {running ? 'Simulating…' : scn ? 'Run again' : 'Run simulation'}
          </button>
        </div>
      </header>

      <section className="card wb-setup" aria-label="Purchase order setup">
        <div className="wb-setup-fields">
          <label className="wb-field">
            <span>SKU</span>
            <select value={skuId} onChange={e => setSkuId(e.target.value)}>
              {st.skus.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <label className="wb-field">
            <span>Supplier</span>
            <select value={supplier.id} onChange={e => setSupId(e.target.value)}>
              {supplierChoices.map(s => <option key={s.id} value={s.id}>{s.name} · {s.city}</option>)}
            </select>
          </label>
          <label className="wb-field wb-seed">
            <span>Seed</span>
            <input type="number" value={seed} min={0} onChange={e => setSeed(Math.max(0, Math.round(+e.target.value || 0)))} />
          </label>
        </div>
        <dl className="wb-facts">
          <div><dt>Unit cost</dt><dd className="num">{usd(offer.unit_cost, 2)}</dd></div>
          <div><dt>Freight / unit</dt><dd className="num">{usd(offer.unit_freight, 2)}</dd></div>
          <div><dt>Tariff</dt><dd className="num">{pct(sku.tariff_rate, 1)}</dd></div>
          <div><dt>Lead time</dt><dd className="num">{supplier.lead_time_mean_days}±{supplier.lead_time_std_days} d</dd></div>
          <div><dt>MOQ</dt><dd className="num">{num(supplier.moq)}</dd></div>
          <div><dt>On hand</dt><dd className="num">{num(sku.on_hand)}</dd></div>
          <div><dt>Price</dt><dd className="num">{usd(sku.price)}</dd></div>
          <div><dt>Safety line</dt><dd className="num">{usdK(safetyLine(st.brand))}</dd></div>
        </dl>
      </section>

      <section className="wb-options" aria-label="Order options">
        {drafts.map((d, i) => (
          <div key={i} className={'card wb-opt' + (errors[i] ? ' has-err' : '')}>
            <div className="wb-opt-head">
              <span className="wb-badge">{LABELS[i]}</span>
              <b>Option {LABELS[i]}</b>
              {drafts.length > 2 && i === drafts.length - 1 && (
                <button type="button" className="wb-x" aria-label={`Remove option ${LABELS[i]}`} onClick={() => setDrafts(ds => ds.slice(0, -1))}>×</button>
              )}
            </div>
            <BubbleSlider
              label="Order quantity"
              hint={`${(d.quantity / sku.daily_demand).toFixed(0)} days of demand`}
              min={Math.min(supplier.moq, 500)}
              max={MAX_Q}
              step={100}
              value={d.quantity}
              onChange={v => setDraft(i, { quantity: v })}
              format={v => num(v)}
              ticks={[Math.min(supplier.moq, 500), 5000, 10000, 15000, MAX_Q]}
              mark={{ value: supplier.moq, label: `MOQ ${num(supplier.moq)}` }}
            />
            <BubbleSlider
              label="Prepay ratio"
              hint={d.prepay === null ? `default ${pct(supplier.default_prepay_ratio)}` : 'custom'}
              min={0}
              max={0.8}
              step={0.05}
              value={d.prepay ?? supplier.default_prepay_ratio}
              onChange={v => setDraft(i, { prepay: v })}
              format={v => pct(v)}
              ticks={[0, 0.2, 0.4, 0.6, 0.8]}
            />
            <div className="wb-opt-foot">
              {errors[i] ? <span className="wb-err" role="alert">{errors[i]}</span> : <span className="muted">Order value {usdK(d.quantity * offer.unit_cost)}</span>}
              {d.prepay !== null && <button type="button" className="wb-link" onClick={() => setDraft(i, { prepay: null })}>Use default</button>}
            </div>
          </div>
        ))}
        {drafts.length < 3 && (
          <button type="button" className="wb-add" onClick={() => setDrafts(ds => [...ds, { quantity: Math.min(MAX_Q, ds[ds.length - 1].quantity + 3000), prepay: null }])}>
            <span aria-hidden="true">+</span>Add option {LABELS[drafts.length]}
          </button>
        )}
      </section>

      {st.stale && result && (
        <div className="stale-banner" role="status">
          <span>Inputs changed since this run — results are out of date</span>
          <button type="button" className="btn" onClick={run} disabled={running || invalid}>Re-run</button>
        </div>
      )}

      {running && !result && (
        <div className="card wb-loading"><OrbitLoader title="Running 1,000 paths" sub="120 days · fixed seed" compact /></div>
      )}

      {result && rec && (
        <div className={'wb-results' + (st.stale ? ' is-stale' : '') + (running ? ' is-running' : '')}>
          {running && <div className="wb-overlay"><OrbitLoader title="Re-running simulation" sub="1,000 paths × 120 days" compact /></div>}

          <section className="wb-cards" aria-label="Results by option">
            {result.options.map(m => {
              const isRec = m.option_id === rec.recommended_option_id
              const isPick = m.option_id === selected
              const feasible = rec.feasible_option_ids.includes(m.option_id)
              return (
                <button
                  key={m.option_id}
                  type="button"
                  className={'wb-res' + (isRec ? ' is-rec' : '') + (isPick ? ' is-pick' : '')}
                  aria-pressed={isPick}
                  onClick={() => { st.selectOption(m.option_id); setFanId(m.option_id) }}
                >
                  <div className="wb-res-inner">
                    <div className="wb-res-head">
                      <span className="wb-badge">{labelOf(m.option_id)}</span>
                      <span className="num wb-res-q">{num(m.quantity)} units · {pct(m.prepay_ratio)} prepay</span>
                    </div>
                    <div className="wb-chips">
                      {isRec && <span className="chip accent">Recommended</span>}
                      {!feasible && <span className="chip bad">Breaches safety line in P10</span>}
                      {isPick && <span className="chip ok">Your pick</span>}
                    </div>
                    <div className="wb-profit">
                      <small>Expected profit</small>
                      <RollingNumber text={usd(m.expected_profit)} label={`Option ${labelOf(m.option_id)} expected profit`} />
                    </div>
                    <div className="wb-runway">
                      <small>Cash runway (days)</small>
                      <div className="wb-runway-row">
                        {(['runway_p10', 'runway_p50', 'runway_p90'] as const).map((k, j) => (
                          <div key={k} className={k === 'runway_p10' && !feasible ? 'bad' : ''}>
                            <span>P{[10, 50, 90][j]}</span>
                            <b className="num">{runway(m[k], result.horizon_days)}</b>
                          </div>
                        ))}
                      </div>
                    </div>
                    <dl className="wb-kv">
                      <div><dt>Stockout risk</dt><dd className="num">{pct(m.stockout_prob)}</dd></div>
                      <div><dt>Worst case (P5)</dt><dd className={'num' + (m.worst_case_p5 < 0 ? ' neg' : '')}>{usd(m.worst_case_p5)}</dd></div>
                      <div><dt>Credit breach</dt><dd className="num">{pct(m.credit_breach_prob, 1)}</dd></div>
                    </dl>
                  </div>
                </button>
              )
            })}
          </section>

          <div className="wb-lower">
            <section className="card wb-fan">
              <div className="card-title">
                <span>Cash balance over {result.horizon_days} days</span>
                <span className="muted">P10–P90 across {num(result.n_paths)} paths</span>
              </div>
              <FanChart
                series={result.options.map(o => ({ id: o.option_id, label: labelOf(o.option_id), fan: o.cash_fan }))}
                active={activeFan}
                onActive={setFanId}
                compare={differs ? { id: activeFan === selected ? rec.recommended_option_id : selected!, label: labelOf(activeFan === selected ? rec.recommended_option_id : selected!) } : null}
              />
              {differs && (
                <p className="wb-note">
                  You picked Option {labelOf(selected!)}, the engine recommends Option {labelOf(rec.recommended_option_id)}. Both median (P50) cash curves are overlaid so you can see where the gap opens.
                </p>
              )}
            </section>

            <section className="card wb-explain" aria-live="polite">
              <div className="card-title">
                <span>Recommendation</span>
                <span className="chip accent">Option {labelOf(rec.recommended_option_id)}</span>
              </div>
              <p className="wb-rule">
                {rec.rule === 'max_profit_under_runway_constraint'
                  ? 'Highest expected profit among options whose P10 cash never touches the safety line.'
                  : 'Lowest-risk option — no option keeps P10 cash above the safety line.'}
              </p>
              {rec.warning && <p className="wb-warn" role="alert">{rec.warning}</p>}

              {st.explanation?.status === 'pending' && (
                <div className="wb-skel" aria-label="Writing the explanation">
                  <small className="muted">Writing the explanation…</small>
                  <i /><i /><i style={{ width: '70%' }} /><i /><i style={{ width: '55%' }} />
                </div>
              )}
              {st.explanation?.status === 'ok' && st.explanation.sections && (
                <div className="wb-sections">
                  <div><h4>Why</h4><p>{st.explanation.sections.reason}</p></div>
                  <div><h4>Main risks</h4><p>{st.explanation.sections.main_risks}</p></div>
                  {st.explanation.sections.counterfactual && <div><h4>What if</h4><p>{st.explanation.sections.counterfactual}</p></div>}
                </div>
              )}
              {st.explanation && st.explanation.status !== 'ok' && st.explanation.status !== 'pending' && (
                <p className="muted">Explanation unavailable — numbers above are still valid.</p>
              )}

              {bestMetrics && Object.keys(bestMetrics.risk_attribution).length > 0 && (
                <div className="wb-attr">
                  <h4>Where the downside comes from</h4>
                  {Object.entries(bestMetrics.risk_attribution).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                    <div key={k} className="wb-bar">
                      <span>{RISK_LABEL[k] ?? k}</span>
                      <div className="wb-bar-track"><i style={{ width: `${Math.max(0, v) * 100}%` }} /></div>
                      <b className="num">{pct(v)}</b>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>

          {st.grid && st.grid.length > 1 && <GridChart grid={st.grid} horizon={result.horizon_days} options={result.options.map(o => ({ q: o.quantity, label: labelOf(o.option_id) }))} />}

          <footer className="wb-meta muted num">
            Seed {result.seed} · {num(result.n_paths)} paths · {result.horizon_days} days · {result.elapsed_ms} ms · state v{scn.state_version}
            {st.stale && <> (current v{st.brand.state_version})</>}
          </footer>
        </div>
      )}
    </div>
  )
}

function GridChart({ grid, horizon, options }: { grid: { quantity: number; expected_profit: number; runway_p10: number }[]; horizon: number; options: { q: number; label: string }[] }) {
  const W = 640, H = 200, P = { l: 56, r: 16, t: 18, b: 30 }
  const qs = grid.map(g => g.quantity), ps = grid.map(g => g.expected_profit)
  const q0 = Math.min(...qs), q1 = Math.max(...qs)
  const p0 = Math.min(...ps), p1 = Math.max(...ps), pad = (p1 - p0) * 0.15 || 1
  const X = (q: number) => P.l + ((q - q0) / (q1 - q0 || 1)) * (W - P.l - P.r)
  const Y = (v: number) => P.t + (1 - (v - (p0 - pad)) / (p1 - p0 + 2 * pad)) * (H - P.t - P.b)
  const feasible = (g: (typeof grid)[number]) => g.runway_p10 > horizon
  const best = useMemo(() => grid.filter(feasible).reduce<(typeof grid)[number] | null>((a, b) => (!a || b.expected_profit > a.expected_profit ? b : a), null), [grid]) // eslint-disable-line react-hooks/exhaustive-deps
  const path = grid.map((g, i) => (i ? 'L' : 'M') + X(g.quantity).toFixed(1) + ' ' + Y(g.expected_profit).toFixed(1)).join('')

  return (
    <section className="card wb-grid">
      <div className="card-title">
        <span>System-suggested quantity</span>
        {best ? <span className="chip ok">{num(best.quantity)} units · {usdK(best.expected_profit)}</span> : <span className="chip bad">No feasible quantity</span>}
      </div>
      <p className="muted wb-grid-sub">Grid search over order quantity (400 paths each). Hollow points breach the safety line in the P10 case.</p>
      <svg viewBox={`0 0 ${W} ${H}`} className="wb-grid-svg" role="img" aria-label={best ? `Best feasible quantity ${num(best.quantity)} units` : 'No feasible quantity in the grid'}>
        {[0, 0.5, 1].map(t => {
          const v = p0 - pad + (p1 - p0 + 2 * pad) * t
          return <g key={t}><path d={`M${P.l} ${Y(v)}H${W - P.r}`} className="wb-gl" /><text x={P.l - 8} y={Y(v) + 4} textAnchor="end">{usdK(v)}</text></g>
        })}
        {options.map(o => o.q >= q0 && o.q <= q1 && (
          <g key={o.label}>
            <path d={`M${X(o.q)} ${P.t}V${H - P.b}`} className="wb-optline" />
            <text x={X(o.q)} y={P.t - 5} textAnchor="middle" className="wb-optlbl">{o.label}</text>
          </g>
        ))}
        <path d={path} className="wb-gline" />
        {grid.map(g => (
          <circle key={g.quantity} cx={X(g.quantity)} cy={Y(g.expected_profit)} r={best?.quantity === g.quantity ? 7 : 4.5} className={best?.quantity === g.quantity ? 'wb-best' : feasible(g) ? 'wb-ok' : 'wb-bad'}>
            <title>{`${num(g.quantity)} units · ${usd(g.expected_profit)} · P10 runway ${runway(g.runway_p10, horizon)} d`}</title>
          </circle>
        ))}
        {[q0, (q0 + q1) / 2, q1].map(q => <text key={q} x={X(q)} y={H - 8} textAnchor="middle">{num(Math.round(q / 100) * 100)}</text>)}
      </svg>
    </section>
  )
}
