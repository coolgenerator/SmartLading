import { useEffect, useMemo, useRef, useState } from 'react'
import { Composer } from '../components/lucian/Composer'
import { FanChart } from '../components/lucian/FanChart'
import { num, pct, runway, usd, usdK } from '../lib/format'
import { useStore } from '../lib/store'
import type { NegotiationTurn, OptionMetrics, Terms } from '../lib/types'
import './negotiation.css'

const initials = (name: string) => name.split(/\s+/).filter(w => /^[A-Za-z]/.test(w)).slice(0, 2).map(w => w[0]).join('').toUpperCase()

function Impact({ m, base }: { m: OptionMetrics; base: OptionMetrics }) {
  const cells: [string, string, number][] = [
    ['Runway P10', `${runway(m.runway_p10)}d`, m.runway_p10 - base.runway_p10],
    ['Exp. profit', usdK(m.expected_profit), m.expected_profit - base.expected_profit],
    ['Worst P5', usdK(m.worst_case_p5), m.worst_case_p5 - base.worst_case_p5],
  ]
  return (
    <div className="neg-impact">
      {cells.map(([k, v, d], i) => (
        <div key={k}>
          <small>{k}</small><strong>{v}</strong>
          <em className={d < 0 ? 'dn' : ''}>{d === 0 ? 'same as base' : (d > 0 ? '+' : '−') + (i === 0 ? `${Math.abs(d)}d` : usdK(Math.abs(d)))}</em>
        </div>
      ))}
    </div>
  )
}

export function Negotiation() {
  const { suppliers, skus, offers, offerFor, negotiate, resetNegotiation, evaluateTerms, brand } = useStore()
  const [supId, setSupId] = useState('sup_everbright')
  const [skuId, setSkuId] = useState('sku_07')
  const sup = suppliers.find(s => s.id === supId)!
  const offer = offerFor(skuId, supId)
  const skuChoices = skus.filter(k => offers.some(o => o.sku_id === k.id && o.supplier_id === supId))

  const baseTerms = useMemo<Terms>(() => ({ prepay_ratio: sup.default_prepay_ratio, quantity: 8000, unit_cost: offer?.unit_cost ?? 0 }), [sup.default_prepay_ratio, offer?.unit_cost])
  const [current, setCurrent] = useState<Terms>(baseTerms)
  const [ask, setAsk] = useState<Terms>(baseTerms)
  const [turns, setTurns] = useState<NegotiationTurn[]>([])
  const [msg, setMsg] = useState('')
  const [typing, setTyping] = useState(false)
  const chat = useRef<HTMLDivElement>(null)
  const timer = useRef(0)

  // new counterparty → fresh conversation
  useEffect(() => {
    setCurrent(baseTerms); setAsk({ ...baseTerms, prepay_ratio: Math.max(0, baseTerms.prepay_ratio - 0.1) }); setTurns([]); setTyping(false)
    clearTimeout(timer.current)
    resetNegotiation(supId, skuId)
  }, [supId, skuId, baseTerms]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => clearTimeout(timer.current), [])
  useEffect(() => { chat.current?.scrollTo({ top: chat.current.scrollHeight, behavior: 'smooth' }) }, [turns.length, typing])

  // base-terms metrics come from the engine; refetch when the brand state changes
  const [base, setBase] = useState<OptionMetrics | null>(null)
  const hasOffer = !!offer
  useEffect(() => {
    if (!hasOffer) return
    let live = true
    evaluateTerms(supId, skuId, baseTerms).then(m => { if (live) setBase(m) }).catch(() => {})
    return () => { live = false }
  }, [hasOffer, supId, skuId, baseTerms, brand.state_version]) // eslint-disable-line react-hooks/exhaustive-deps
  const lastCounter = [...turns].reverse().find(t => t.role === 'factory')

  if (!offer) {
    return <div className="page"><p className="muted">No quote from {sup.name} for this SKU.</p></div>
  }
  if (!base) {
    return <div className="page"><p className="muted">Running the base terms through the simulator…</p></div>
  }

  const send = async () => {
    const message = msg.trim()
    setTurns(t => [...t, { role: 'user', message, terms: ask, impact: null }])
    setMsg('')
    setTyping(true)
    const res = await negotiate(supId, skuId, ask, message)
    setTyping(false)
    if (!res) { setTurns(t => t.slice(0, -1)); setMsg(message); return }
    setTurns(t => [...t.slice(0, -1), res.user, res.factory])
    setCurrent(res.factory.terms)
    setAsk(res.factory.terms)
  }

  const termTags = (t: Terms) => [`${pct(t.prepay_ratio)} deposit`, `${num(t.quantity)} units`, `${usd(t.unit_cost, 2)}/unit`]

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Negotiation room</h1>
          <p className="page-sub">Rehearse terms with a factory agent before the real call</p>
        </div>
        <div className="neg-pick">
          <select aria-label="Supplier" value={supId} onChange={e => {
            const id = e.target.value
            setSupId(id)
            if (!offers.some(o => o.sku_id === skuId && o.supplier_id === id)) setSkuId(offers.find(o => o.supplier_id === id)!.sku_id)
          }}>
            {suppliers.map(s => <option key={s.id} value={s.id}>{s.name} · {s.city}</option>)}
          </select>
          <select aria-label="SKU" value={skuId} onChange={e => setSkuId(e.target.value)}>
            {skuChoices.map(k => <option key={k.id} value={k.id}>{k.name}</option>)}
          </select>
        </div>
      </header>

      <div className="neg-layout">
        <section className="card" aria-label="Conversation">
          <h2 className="card-title">Talking to {sup.name}</h2>
          <div className="neg-chat" ref={chat} aria-live="polite">
            {turns.length === 0 && !typing && (
              <p className="neg-empty">Propose a deposit, quantity and price below. The factory answers with a counter, and each counter is run through the simulator.</p>
            )}
            {turns.map((t, i) => (
              <div key={i} className={'neg-msg' + (t.role === 'user' ? ' me' : '')}>
                <span className="neg-av" aria-hidden="true">{t.role === 'user' ? '' : initials(sup.name)}</span>
                <div className="neg-bub">
                  <b>{t.role === 'user' ? 'You' : sup.name}</b>
                  {t.message || (t.role === 'user' ? 'Here is what we can do.' : '')}
                  <div className="neg-tags">{termTags(t.terms).map(x => <span key={x}>{x}</span>)}</div>
                  {t.role === 'factory' && t.impact && <Impact m={t.impact} base={base} />}
                </div>
              </div>
            ))}
            {typing && (
              <div className="neg-msg">
                <span className="neg-av" aria-hidden="true">{initials(sup.name)}</span>
                <div className="neg-bub neg-typing" aria-label={`${sup.name} is typing`}><i /><i /><i /></div>
              </div>
            )}
          </div>

          <div className="neg-ask">
            <label>Deposit %
              <input type="number" min={0} max={100} step={5} value={Math.round(ask.prepay_ratio * 100)} onChange={e => setAsk(a => ({ ...a, prepay_ratio: Math.min(1, Math.max(0, (+e.target.value || 0) / 100)) }))} />
            </label>
            <label>Quantity
              <input type="number" min={0} step={500} value={ask.quantity} onChange={e => setAsk(a => ({ ...a, quantity: Math.max(1, Math.round(+e.target.value || 0)) }))} />
            </label>
            <label>Unit cost $
              <input type="number" min={0} step={0.1} value={ask.unit_cost} onChange={e => setAsk(a => ({ ...a, unit_cost: Math.max(0.01, +e.target.value || 0) }))} />
            </label>
          </div>
          <Composer
            value={msg}
            onChange={setMsg}
            onSubmit={send}
            label="Message to the factory"
            placeholder="e.g. Can you do a 20% deposit if we go to 9,000 units?"
            submitLabel="Send offer"
            max={400}
            maxHeight={120}
            busy={typing}
          />
          <p className="neg-note" style={{ marginTop: 12 }}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>
            Factory floors are enforced in code; the agent can't go below them.
          </p>
        </section>

        <div className="neg-side">
          <section className="card" aria-label="Current terms">
            <h2 className="card-title">{lastCounter ? 'Latest counter' : 'Current terms'}</h2>
            <div className="neg-terms">
              <div><small>Deposit</small><b>{pct(current.prepay_ratio)}</b></div>
              <div><small>Quantity</small><b>{num(current.quantity)}</b></div>
              <div><small>Unit cost</small><b>{usd(current.unit_cost, 2)}</b></div>
            </div>
            {lastCounter?.impact && <Impact m={lastCounter.impact} base={base} />}
          </section>
          <section className="card" aria-label="Cash fan comparison">
            <h2 className="card-title">Cash: base terms vs latest counter</h2>
            <FanChart
              height={240}
              series={[
                { id: 'base', label: 'Base', fan: base.cash_fan },
                ...(lastCounter?.impact ? [{ id: 'counter', label: 'Counter', fan: lastCounter.impact.cash_fan }] : []),
              ]}
              active={lastCounter?.impact ? 'counter' : 'base'}
              compare={lastCounter?.impact ? { id: 'base', label: 'Base' } : null}
            />
          </section>
        </div>
      </div>
    </div>
  )
}
