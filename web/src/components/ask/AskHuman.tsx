import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef, useState, type ComponentType } from 'react'
import { billTotal, money, resolve, validate, type AskHuman, type Block, type BlockOf, type BlockType, type HumanAnswer } from '../../lib/askHuman'
import './ask.css'

// --- block renderers: one per type in CAPABILITIES.blocks ---

const TextB = ({ b }: { b: BlockOf<'text'> }) => <p className={`ah-text tone-${b.tone ?? 'plain'}`}>{b.text}</p>

const FactsB = ({ b }: { b: BlockOf<'facts'> }) => (
  <div className="ah-block">
    {b.title && <h4>{b.title}</h4>}
    <dl className="ah-facts">
      {b.facts.map(f => (
        <div key={f.label}><dt>{f.label}</dt><dd>{f.value}</dd>{f.hint && <em className={f.tone ?? ''}>{f.hint}</em>}</div>
      ))}
    </dl>
  </div>
)

const CardB = ({ b }: { b: BlockOf<'card'> }) => (
  <article className="ah-card">
    {b.image_url && <img src={b.image_url} alt="" />}
    <div>
      <div className="ah-card-head">
        <b>{b.title}</b>
        {b.badges?.map(x => <span key={x} className="ah-badge">{x}</span>)}
      </div>
      {b.subtitle && <small>{b.subtitle}</small>}
      {b.body && <p>{b.body}</p>}
      {!!b.facts?.length && <FactsB b={{ id: b.id, type: 'facts', facts: b.facts }} />}
      {b.link && <a href={b.link} target="_blank" rel="noreferrer">Open</a>}
    </div>
  </article>
)

const TableB = ({ b }: { b: BlockOf<'table'> }) => (
  <div className="ah-block">
    {b.title && <h4>{b.title}</h4>}
    <div className="ah-scroll">
      <table className="ah-table">
        <thead><tr>{b.columns.map(c => <th key={c.key} className={c.align === 'right' ? 'r' : ''}>{c.label}</th>)}</tr></thead>
        <tbody>
          {b.rows.map((r, i) => (
            <tr key={i} className={i === b.highlight_row ? 'hl' : ''}>
              {b.columns.map(c => <td key={c.key} className={c.align === 'right' ? 'r' : ''}>{r[c.key] ?? '—'}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </div>
)

const BillB = ({ b }: { b: BlockOf<'bill'> }) => (
  <div className="ah-bill">
    <div className="ah-bill-head"><b>{b.title}</b>{b.issuer && <small>{b.issuer}</small>}</div>
    {b.lines.map(l => (
      <div key={l.label} className="ah-bill-line">
        <div><span>{l.label}</span>{(l.detail || l.due) && <small>{[l.detail, l.due].filter(Boolean).join(' · ')}</small>}</div>
        <strong>{money(l.amount, b.currency)}</strong>
      </div>
    ))}
    <div className="ah-bill-line total"><span>{b.total_label ?? 'Total'}</span><strong>{money(billTotal(b), b.currency)}</strong></div>
  </div>
)

const ImageB = ({ b }: { b: BlockOf<'image'> }) => (
  <figure className="ah-figure"><img src={b.url} alt={b.alt} loading="lazy" />{b.caption && <figcaption>{b.caption}</figcaption>}</figure>
)

const MediaB = ({ b }: { b: BlockOf<'media'> }) => (
  <figure className="ah-figure">
    {b.kind === 'video'
      ? <video src={b.url} poster={b.poster_url ?? undefined} controls preload="metadata" aria-label={b.title} />
      : <audio src={b.url} controls preload="metadata" aria-label={b.title} />}
    <figcaption>{b.title}</figcaption>
  </figure>
)

const tiles = () => {
  const dark = (document.documentElement.dataset.theme ?? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark'
  return `https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_${dark ? 'Dark' : 'Light'}_Gray_Base/MapServer/tile/{z}/{y}/{x}`
}

function MapB({ b }: { b: BlockOf<'map'> }) {
  const el = useRef<HTMLDivElement>(null)
  useEffect(() => {
    // routes that cross the Pacific are drawn eastward: shift western longitudes by +360
    const span = Math.max(...b.markers.map(m => m.lng)) - Math.min(...b.markers.map(m => m.lng))
    const ll = (m: { lat: number; lng: number }): [number, number] => [m.lat, span > 180 && m.lng < 0 ? m.lng + 360 : m.lng]
    const m = L.map(el.current!, { scrollWheelZoom: false, attributionControl: false, zoomSnap: 0.1 })
    L.tileLayer(tiles(), { maxZoom: 10 }).addTo(m)
    const byId = Object.fromEntries(b.markers.map(x => [x.id, x]))
    const accent = getComputedStyle(document.documentElement).getPropertyValue('--ux-accent').trim() || '#6A57F2'
    for (const r of b.routes ?? []) {
      const a = byId[r.from_id], z = byId[r.to_id]
      if (!a || !z) continue
      const [p, q] = [ll(a), ll(z)]
      const mid: [number, number] = [(p[0] + q[0]) / 2 + (q[1] - p[1]) * 0.15, (p[1] + q[1]) / 2]
      const pts = Array.from({ length: 41 }, (_, i) => { const t = i / 40, u = 1 - t; return [u * u * p[0] + 2 * u * t * mid[0] + t * t * q[0], u * u * p[1] + 2 * u * t * mid[1] + t * t * q[1]] as [number, number] })
      L.polyline(pts, { color: accent, weight: 2.5, dashArray: r.style === 'air' ? '4 6' : undefined }).addTo(m)
    }
    for (const x of b.markers) {
      L.marker(ll(x), { icon: L.divIcon({ className: '', iconSize: [14, 14], iconAnchor: [7, 7], html: `<div class="ah-pin k-${x.kind ?? 'other'}"></div>` }), title: x.label })
        .bindTooltip(`<b>${x.label}</b>${x.detail ? `<br>${x.detail}` : ''}`, { permanent: true, direction: 'top', offset: [0, -8], className: 'ah-tip' })
        .addTo(m)
    }
    m.fitBounds(L.latLngBounds(b.markers.map(ll)).pad(0.35))
    const ro = new ResizeObserver(() => m.invalidateSize())
    ro.observe(el.current!)
    return () => { ro.disconnect(); m.remove() }
  }, [b])
  return (
    <div className="ah-block">
      {b.title && <h4>{b.title}</h4>}
      <div ref={el} className="ah-map" role="img" aria-label={`Map: ${b.markers.map(x => x.label).join(', ')}`} />
    </div>
  )
}

const RENDERERS: { [T in BlockType]: ComponentType<{ b: BlockOf<T> }> } = {
  text: TextB, facts: FactsB, card: CardB, table: TableB, bill: BillB, image: ImageB, media: MediaB, map: MapB,
}

export function BlockView({ b }: { b: Block }) {
  const R = RENDERERS[b.type] as ComponentType<{ b: Block }> | undefined
  return R ? <R b={b} /> : <TextB b={{ id: b.id, type: 'text', text: '(unsupported content)' }} />
}

// --- the ask itself: blocks + fields + actions, placed by policy.surface ---

interface Props {
  ask: AskHuman
  answer?: HumanAnswer | null
  onAnswer: (a: HumanAnswer) => void
}

function AskBody({ ask, answer, onAnswer }: Props) {
  const fields = ask.response.fields ?? []
  const [values, setValues] = useState<HumanAnswer['values']>(() => Object.fromEntries(fields.map(f => [f.id, f.default ?? null])))
  const [comment, setComment] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const done = !!answer

  const submit = (actionId: string) => {
    const e = validate(ask, actionId, values)
    setErr(e)
    if (!e) onAnswer({ ask_id: ask.id, action_id: actionId, values, comment: comment.trim() || null, answered_at: new Date().toISOString() })
  }

  return (
    <>
      <div className="ah-head">
        <span className={`ah-urg u-${ask.policy.urgency}`}>{ask.policy.urgency === 'blocking' ? 'Needs your decision' : 'Question'}</span>
        <h3>{ask.title}</h3>
        <p>{ask.prompt}</p>
      </div>
      <div className="ah-blocks">{ask.blocks.map(b => <BlockView key={b.id} b={b} />)}</div>
      {done ? (
        <p className="ah-done">You chose <b>{ask.response.actions.find(a => a.id === answer.action_id)?.label}</b>{answer.comment ? ` — “${answer.comment}”` : ''}</p>
      ) : (
        <form className="ah-form" onSubmit={e => e.preventDefault()}>
          {fields.map(f => (
            <label key={f.id} className={f.kind === 'boolean' ? 'ah-check' : ''}>
              <span>{f.label}{f.required ? ' *' : ''}</span>
              {f.kind === 'select' ? (
                <select value={String(values[f.id] ?? '')} onChange={e => setValues(v => ({ ...v, [f.id]: e.target.value }))}>
                  {!f.required && <option value="">—</option>}
                  {f.options?.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              ) : f.kind === 'boolean' ? (
                <input type="checkbox" checked={!!values[f.id]} onChange={e => setValues(v => ({ ...v, [f.id]: e.target.checked }))} />
              ) : (
                <input type={f.kind} min={f.min ?? undefined} max={f.max ?? undefined} value={String(values[f.id] ?? '')}
                  onChange={e => setValues(v => ({ ...v, [f.id]: f.kind === 'number' ? (e.target.value === '' ? null : +e.target.value) : e.target.value }))} />
              )}
              {f.help && <small>{f.help}</small>}
            </label>
          ))}
          {ask.response.allow_comment && (
            <label className="ah-wide"><span>Note (optional)</span><input value={comment} maxLength={300} onChange={e => setComment(e.target.value)} placeholder="Anything the agent should pass on" /></label>
          )}
          {err && <p className="ah-err" role="alert">{err}</p>}
          <div className="ah-actions">
            {ask.response.actions.map(a => (
              <button key={a.id} type="button" className={`ah-btn s-${a.style ?? 'secondary'}`} onClick={() => submit(a.id)}>{a.label}</button>
            ))}
          </div>
        </form>
      )}
    </>
  )
}

export function AskHumanView(props: Props) {
  const ask = resolve(props.ask)
  const dlg = useRef<HTMLDialogElement>(null)
  const modal = ask.policy.surface === 'modal' && !props.answer

  useEffect(() => {
    const d = dlg.current
    if (modal && d && !d.open) d.showModal()
  }, [modal])

  if (modal) {
    return (
      <dialog ref={dlg} className="ah ah-modal" aria-label={ask.title}
        // a blocking ask can't be dismissed with Esc; the default action covers walking off
        onCancel={e => { if (ask.policy.urgency === 'blocking') e.preventDefault() }}>
        <AskBody {...props} ask={ask} />
      </dialog>
    )
  }
  return <section className={`ah ah-${ask.policy.surface}`} aria-label={ask.title}><AskBody {...props} ask={ask} /></section>
}
