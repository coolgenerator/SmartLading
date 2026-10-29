import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BubbleSlider } from '../components/lucian/BubbleSlider'
import { Composer } from '../components/lucian/Composer'
import { OrbitLoader } from '../components/lucian/OrbitLoader'
import { PillTabs } from '../components/lucian/PillTabs'
import { QuoteHighlight, type Span } from '../components/lucian/QuoteHighlight'
import { toast } from '../components/lucian/Toaster'
import { formatChange, PARAM_LABEL, pct } from '../lib/format'
import { sampleNews } from '../lib/seed'
import { useStore } from '../lib/store'
import type { RiskSignal, SignalStatus } from '../lib/types'
import './signals.css'

const COLOR: Record<SignalStatus, string> = { pending: '#FFD43B', accepted: '#38D9A9', rejected: '#FF6B9D' }
const CHIP: Record<SignalStatus, string> = { pending: 'warn', accepted: 'ok', rejected: 'bad' }
const RATIO = new Set(['tariff_rate', 'prepay_ratio', 'default_prob'])
type Filter = SignalStatus | 'all'

export function Signals() {
  const { signals, suppliers, skus, extract, patchSignal, decideSignal } = useStore()
  const navigate = useNavigate()
  const [text, setText] = useState(sampleNews[0].text)
  const [sourceType, setSourceType] = useState<RiskSignal['source_type']>(sampleNews[0].source_type)
  const [busy, setBusy] = useState(false)
  const [lastRun, setLastRun] = useState<{ text: string; found: number } | null>(null)
  const [filter, setFilter] = useState<Filter>('pending')
  const [focus, setFocus] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)

  const run = async () => {
    setBusy(true)
    const found = await extract(text, sourceType)
    setBusy(false)
    if (found === null) return // the store already showed the error toast
    setLastRun({ text, found })
    if (found) setFilter('pending')
  }

  const spans: Span[] = signals
    .filter(s => s.source_text === text && s.quote_span[1] > s.quote_span[0])
    .map(s => ({ id: s.id, start: s.quote_span[0], end: s.quote_span[1], color: COLOR[s.status] }))

  const count = (f: Filter) => (f === 'all' ? signals.length : signals.filter(s => s.status === f).length)
  const shown = filter === 'all' ? signals : signals.filter(s => s.status === filter)
  const tabs = (['pending', 'accepted', 'rejected', 'all'] as Filter[]).map(id => ({ id, label: `${id[0].toUpperCase() + id.slice(1)} · ${count(id)}` }))

  const target = (s: RiskSignal) => {
    if (s.target_type === 'hts_code') return `HTS ${s.target_id}`
    if (s.target_type === 'supplier') return suppliers.find(x => x.id === s.target_id)?.name ?? s.target_id
    return skus.find(x => x.id === s.target_id)?.name ?? s.target_id
  }

  const accept = (s: RiskSignal) => {
    decideSignal(s.id, 'accepted')
    setEditing(null)
    toast({ kind: 'ok', title: 'Signal accepted', body: 'Scenarios using it are now out of date', action: 'Open workbench', onAction: () => navigate('/workbench') })
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Risk signals</h1>
          <p className="page-sub">Paste a tariff notice or supplier news; confirm each change before it reaches the model</p>
        </div>
      </header>

      <div className="sig-layout">
        <div className="sig-input">
          <Composer
            value={text}
            onChange={setText}
            onSubmit={run}
            label="News or notice text"
            placeholder="Paste a tariff announcement or supplier update…"
            submitLabel="Extract signals"
            max={2000}
            busy={busy}
            tools={sampleNews.map(n => (
              <button key={n.title} type="button" className="sig-sample" onClick={() => { setText(n.text); setSourceType(n.source_type) }}>{n.title}</button>
            ))}
          />
          <label className="sig-type">
            Source type
            <select value={sourceType} onChange={e => setSourceType(e.target.value as RiskSignal['source_type'])}>
              <option value="tariff">Tariff notice</option>
              <option value="supplier_news">Supplier news</option>
              <option value="other">Other</option>
            </select>
          </label>

          {busy && <div className="sig-loader"><OrbitLoader compact title="Reading the text…" sub="Matching HTS codes, suppliers and SKUs" /></div>}

          {!busy && lastRun && lastRun.text === text && lastRun.found === 0 && (
            <div className="sig-empty" role="status">
              <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4 4M8.5 11h5" /></svg>
              <span><b>No quantifiable impact found</b>Nothing in this text changes a tariff rate, lead time, cost or supplier term we model. No parameters were created.</span>
            </div>
          )}

          <section className="card sig-source" aria-label="Source text with quoted evidence">
            <h2 className="card-title">Source text</h2>
            <QuoteHighlight text={text} spans={spans} focusId={focus} />
          </section>
        </div>

        <section aria-label="Extracted signals">
          <PillTabs tabs={tabs} value={filter} onChange={id => setFilter(id as Filter)} label="Signal status" />
          <div className="sig-list">
            {shown.length === 0 && <p className="muted">No {filter === 'all' ? '' : filter + ' '}signals yet.</p>}
            {shown.map(s => {
              const ratio = RATIO.has(s.parameter) && s.change_type !== 'multiply'
              const fromEvent = s.quote_span[0] === 0 && s.quote_span[1] === 0
              return (
                <article
                  key={s.id}
                  className="sig-card"
                  style={{ ['--c' as string]: COLOR[s.status] }}
                  onPointerEnter={() => setFocus(s.id)}
                  onPointerLeave={() => setFocus(null)}
                  onFocus={() => setFocus(s.id)}
                >
                  <div className="sig-top">
                    <span className="sig-param">{PARAM_LABEL[s.parameter]}</span>
                    <span className="sig-change">{formatChange(s.parameter, s.change_type, s.change_value)}</span>
                    <span className={'chip ' + CHIP[s.status]}>{s.status}</span>
                    {s.edited_by_user && <span className="chip accent">edited</span>}
                    <span className="sig-target">{target(s)}</span>
                  </div>
                  <p className="sig-quote">{fromEvent ? 'From demo event' : `“${s.quote}”`}</p>
                  <div className="sig-meta">
                    <span>Effective <b>{s.effective_day ? `day ${s.effective_day}` : 'now'}</b></span>
                    <span>Affects <b>{s.affected_skus.length}</b> SKU{s.affected_skus.length === 1 ? '' : 's'}</span>
                    {s.llm_probability !== null && <span>Model suggests <b>{pct(s.llm_probability)}</b></span>}
                    <span>You set <b>{pct(s.probability)}</b></span>
                  </div>

                  {editing === s.id && (
                    <div className="sig-edit">
                      <label>
                        {ratio ? 'New value (%)' : s.parameter.includes('days') ? 'Change (days)' : 'Change value'}
                        <input
                          type="number"
                          step={ratio ? 0.5 : s.change_type === 'multiply' ? 0.01 : 1}
                          value={ratio ? +(s.change_value * 100).toFixed(2) : s.change_value}
                          onChange={e => { const v = +e.target.value; if (!Number.isNaN(v)) patchSignal(s.id, { change_value: ratio ? v / 100 : v }) }}
                        />
                      </label>
                      <label>
                        Effective day
                        <input type="number" min={0} max={120} value={s.effective_day} onChange={e => patchSignal(s.id, { effective_day: Math.max(0, +e.target.value || 0) })} />
                      </label>
                      <div className="full">
                        <BubbleSlider
                          label="Probability it happens"
                          hint={s.llm_probability !== null ? `Model: ${pct(s.llm_probability)}` : undefined}
                          min={0} max={1} step={0.05}
                          value={s.probability}
                          onChange={v => patchSignal(s.id, { probability: v })}
                          format={v => pct(v)}
                          ticks={[0, 0.25, 0.5, 0.75, 1]}
                        />
                      </div>
                    </div>
                  )}

                  {s.status === 'pending' && (
                    <div className="sig-actions">
                      <button type="button" className="btn primary" onClick={() => accept(s)}>Accept</button>
                      <button type="button" className="btn" aria-expanded={editing === s.id} onClick={() => setEditing(editing === s.id ? null : s.id)}>
                        {editing === s.id ? 'Done editing' : 'Modify'}
                      </button>
                      <button type="button" className="btn danger" onClick={() => { decideSignal(s.id, 'rejected'); setEditing(null) }}>Reject</button>
                    </div>
                  )}
                </article>
              )
            })}
          </div>
        </section>
      </div>
    </div>
  )
}
