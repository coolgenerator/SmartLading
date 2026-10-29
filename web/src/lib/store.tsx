// Client state backed by the FastAPI layer (src/smartlading/api.py, docs/design.md §3).
// Every write goes to the server, then the brand view is refetched so state_version,
// alerts and signals always come from Postgres.

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { toast } from '../components/lucian/Toaster'
import type { Alert, Brand, Explanation, NegotiationTurn, OptionMetrics, PresetEvent, PurchaseOrder, RiskSignal, SKU, Scenario, ScenarioOption, Supplier, SupplierOffer, Terms } from './types'

const BASE = '/api/v1'
const BRAND = 'brand_harbor'

export class ApiError extends Error {
  code: string
  status: number
  constructor(status: number, code: string, message: string) { super(message); this.status = status; this.code = code }
}

async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, { method, headers: body ? { 'content-type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined })
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const err = data?.detail?.error ?? data?.error ?? { code: 'http_' + res.status, message: typeof data?.detail === 'string' ? data.detail : res.statusText }
    throw new ApiError(res.status, err.code, err.message)
  }
  return data as T
}
const b = (p: string) => `/brands/${BRAND}${p}`

interface BrandView {
  brand: Brand
  skus: SKU[]
  suppliers: Supplier[]
  offers: SupplierOffer[]
  purchase_orders: PurchaseOrder[]
  signals: RiskSignal[]
  alerts: Alert[]
  events: PresetEvent[]
  injected: string[]
}

type Grid = { quantity: number; expected_profit: number; runway_p10: number }[]
type ScenarioOut = Scenario & { grid: Grid; is_stale: boolean }

function fail(e: unknown, title: string) {
  toast({ kind: 'err', title, body: e instanceof Error ? e.message : String(e) })
}

function useStoreValue() {
  const [view, setView] = useState<BrandView | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [scenario, setScenario] = useState<Scenario | null>(null)
  const [explanation, setExplanation] = useState<Explanation | null>(null)
  const [grid, setGrid] = useState<Grid | null>(null)
  const negotiations = useRef(new Map<string, string>())
  const pending = useRef(new Map<string, number>())

  const refresh = useCallback(async () => {
    const v = await api<BrandView>(b(''))
    setView(v)
    return v
  }, [])

  useEffect(() => {
    api<BrandView>('/demo/seed', 'POST').then(setView).catch(e => setLoadError(e instanceof Error ? e.message : String(e)))
  }, [])

  // Optimistic local edit + debounced PATCH, so dragging a slider doesn't flood the API.
  const debounced = (key: string, send: () => Promise<unknown>, title: string) => {
    clearTimeout(pending.current.get(key))
    pending.current.set(key, window.setTimeout(() => {
      pending.current.delete(key)
      send().then(refresh).catch(e => { fail(e, title); refresh() })
    }, 350))
  }
  const local = (fn: (v: BrandView) => BrandView) => setView(v => (v ? fn(v) : v))

  // F1
  const patchBrand = (patch: Partial<Brand>) => {
    local(v => ({ ...v, brand: { ...v.brand, ...patch } }))
    debounced('brand', () => api(b(''), 'PATCH', patch), 'Could not save brand')
  }
  const supplierEdits = useRef<Record<string, Partial<Supplier>>>({})
  const patchSupplier = (id: string, patch: Partial<Supplier>) => {
    local(v => ({ ...v, suppliers: v.suppliers.map(x => (x.id === id ? { ...x, ...patch } : x)) }))
    supplierEdits.current[id] = { ...supplierEdits.current[id], ...patch }
    debounced('sup:' + id, () => { const p = supplierEdits.current[id]; delete supplierEdits.current[id]; return api(b(`/suppliers/${id}`), 'PATCH', p) }, 'Could not save supplier')
  }
  const patchSku = (id: string, patch: Partial<SKU>) => {
    local(v => ({ ...v, skus: v.skus.map(x => (x.id === id ? { ...x, ...patch } : x)) }))
    debounced('sku:' + id, () => api(b(`/skus/${id}`), 'PATCH', patch), 'Could not save SKU')
  }

  // F2 + F4: numbers first, explanation as a second request
  const runScenario = async (skuId: string, supId: string, options: ScenarioOption[], seed = 42) => {
    try {
      const scn = await api<ScenarioOut>(b('/scenarios'), 'POST', {
        id: scenario?.id, sku_id: skuId, supplier_id: supId, seed,
        options: options.map(o => ({ id: o.id, label: o.label, quantity: o.quantity, prepay_ratio: o.prepay_ratio })),
      })
      setScenario(scn)
      setGrid(scn.grid)
      setExplanation({ status: 'pending', sections: null })
      await refresh()
      api<Explanation>(b(`/scenarios/${scn.id}/explanation`), 'POST')
        .then(setExplanation)
        .catch(() => setExplanation({ status: 'llm_error', sections: null }))
      return scn
    } catch (e) {
      fail(e, 'Simulation failed')
      return null
    }
  }
  const selectOption = (id: string) => {
    setScenario(s => (s ? { ...s, selected_option_id: id } : s))
    if (scenario) api(b(`/scenarios/${scenario.id}/selection`), 'PUT', { option_id: id }).catch(e => fail(e, 'Could not save your pick'))
  }

  // F3
  const extract = async (text: string, sourceType: RiskSignal['source_type']): Promise<number | null> => {
    try {
      const res = await api<{ signals: RiskSignal[] }>(b('/risk-signals/extract'), 'POST', { text, source_type: sourceType })
      await refresh()
      return res.signals.length
    } catch (e) {
      fail(e, 'Extraction failed')
      return null
    }
  }
  const patchSignal = (id: string, patch: Partial<RiskSignal>) => {
    local(v => ({ ...v, signals: v.signals.map(x => (x.id === id ? { ...x, ...patch, edited_by_user: true } : x)) }))
    const body: Record<string, unknown> = {}
    for (const k of ['change_value', 'probability', 'effective_day', 'target_type', 'target_id'] as const) if (k in patch) body[k] = patch[k]
    debounced('sig:' + id + Object.keys(body).join(), () => api(b(`/risk-signals/${id}`), 'PATCH', body), 'Could not save the edit')
  }
  const decideSignal = (id: string, status: 'accepted' | 'rejected') => {
    local(v => ({ ...v, signals: v.signals.map(x => (x.id === id ? { ...x, status } : x)) }))
    api(b(`/risk-signals/${id}/${status === 'accepted' ? 'accept' : 'reject'}`), 'POST')
      .then(refresh)
      .catch(e => { fail(e, 'Could not update the signal'); refresh() })
  }

  // F5
  const injectEvent = async (evt: PresetEvent) => {
    try {
      const res = await api<{ alerts: Alert[] }>(b(`/events/${evt.id}/inject`), 'POST')
      await refresh()
      toast({ kind: 'err', title: evt.name, body: `${res.alerts.length} order alert${res.alerts.length === 1 ? '' : 's'} · open scenarios are now out of date` })
    } catch (e) { fail(e, 'Could not inject the event') }
  }
  const ackAlert = (id: string) => {
    local(v => ({ ...v, alerts: v.alerts.map(a => (a.id === id ? { ...a, acknowledged: true } : a)) }))
    api(b(`/alerts/${id}/ack`), 'POST').catch(e => fail(e, 'Could not acknowledge'))
  }

  // F6
  const negotiate = async (supId: string, skuId: string, ask: Terms, message: string): Promise<{ user: NegotiationTurn; factory: NegotiationTurn } | null> => {
    try {
      const key = supId + ':' + skuId
      let id = negotiations.current.get(key)
      if (!id) {
        id = (await api<{ id: string }>(b('/negotiations'), 'POST', { supplier_id: supId, sku_id: skuId })).id
        negotiations.current.set(key, id)
      }
      const res = await api<{ status: string; factory_reply: { message: string; counter_terms: Terms }; impact: { proposed: OptionMetrics; counter: OptionMetrics } | null }>(
        b(`/negotiations/${id}/turns`), 'POST', { message: message || 'Here is my offer.', proposed_terms: ask },
      )
      if (res.status !== 'open') negotiations.current.delete(key)
      return {
        user: { role: 'user', message, terms: ask, impact: res.impact?.proposed ?? null },
        factory: { role: 'factory', message: res.factory_reply.message, terms: res.factory_reply.counter_terms, impact: res.impact?.counter ?? null },
      }
    } catch (e) {
      fail(e, 'The factory agent did not reply')
      return null
    }
  }
  const resetNegotiation = (supId: string, skuId: string) => negotiations.current.delete(supId + ':' + skuId)
  const evaluateTerms = (supId: string, skuId: string, terms: Terms) =>
    api<OptionMetrics>(b('/terms/evaluate'), 'POST', { supplier_id: supId, sku_id: skuId, terms })

  const reset = async () => {
    try {
      setView(await api<BrandView>('/demo/reset', 'POST'))
      setScenario(null); setExplanation(null); setGrid(null); negotiations.current.clear()
      toast({ kind: 'ok', title: 'Demo reset', body: 'Harbor & Pine is back to its starting state' })
    } catch (e) { fail(e, 'Reset failed') }
  }

  const v = view
  return {
    ready: !!v, loadError,
    brand: v?.brand as Brand, skus: v?.skus ?? [], suppliers: v?.suppliers ?? [], offers: v?.offers ?? [],
    purchaseOrders: v?.purchase_orders ?? [], signals: v?.signals ?? [], alerts: v?.alerts ?? [], events: v?.events ?? [], injected: v?.injected ?? [],
    scenario, explanation, grid,
    stale: !!scenario && !!v && scenario.state_version !== v.brand.state_version,
    offerFor: (sku: string, sup: string) => v?.offers.find(o => o.sku_id === sku && o.supplier_id === sup),
    patchBrand, patchSupplier, patchSku, runScenario, selectOption,
    extract, patchSignal, decideSignal, injectEvent, ackAlert, negotiate, resetNegotiation, evaluateTerms, reset,
  }
}

type Store = ReturnType<typeof useStoreValue>
const Ctx = createContext<Store | null>(null)

export function StoreProvider({ children }: { children: ReactNode }) {
  const v = useStoreValue()
  return <Ctx.Provider value={v}>{children}</Ctx.Provider>
}

export function useStore() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useStore outside StoreProvider')
  return v
}
