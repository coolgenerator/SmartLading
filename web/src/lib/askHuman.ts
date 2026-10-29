// ask-human/1 protocol, mirrored from src/smartlading/ask_human.py.
// The server degrades blocks to what CAPABILITIES says this client renders; resolve() repeats
// that here so the mock layer behaves the same and an unknown block never breaks the page.

export const PROTOCOL = 'ask-human/1'

interface Base { id: string; version?: number }
export type Tone = 'plain' | 'info' | 'warn' | 'danger' | 'success'
export interface Fact { label: string; value: string; hint?: string | null; tone?: 'plain' | 'good' | 'bad' }
export interface Column { key: string; label: string; align?: 'left' | 'right' }
export type Cell = string | number | null
export interface BillLine { label: string; amount: number; detail?: string | null; due?: string | null }
export interface MapMarker { id: string; lat: number; lng: number; label: string; kind?: 'supplier' | 'port' | 'warehouse' | 'shipment' | 'other'; detail?: string | null }
export interface MapRoute { from_id: string; to_id: string; label?: string | null; style?: 'sea' | 'air' | 'road' }

export type Block = Base & (
  | { type: 'text'; text: string; tone?: Tone }
  | { type: 'facts'; title?: string | null; facts: Fact[] }
  | { type: 'card'; title: string; subtitle?: string | null; body?: string | null; image_url?: string | null; badges?: string[]; facts?: Fact[]; link?: string | null }
  | { type: 'table'; title?: string | null; columns: Column[]; rows: Record<string, Cell>[]; highlight_row?: number | null }
  | { type: 'bill'; title: string; issuer?: string | null; currency?: string; lines: BillLine[]; total_label?: string }
  | { type: 'image'; url: string; alt: string; caption?: string | null }
  | { type: 'media'; kind: 'video' | 'audio'; url: string; title: string; poster_url?: string | null; duration_s?: number | null }
  | { type: 'map'; title?: string | null; markers: MapMarker[]; routes?: MapRoute[] }
)
export type BlockType = Block['type']
export type BlockOf<T extends BlockType> = Extract<Block, { type: T }>

export interface Action { id: string; label: string; style?: 'primary' | 'secondary' | 'danger'; requires_fields?: boolean }
export interface InputField {
  id: string; label: string; kind: 'text' | 'number' | 'select' | 'boolean'
  required?: boolean; default?: string | number | boolean | null; min?: number | null; max?: number | null
  options?: { value: string; label: string }[]; help?: string | null
}
export type Surface = 'inline' | 'sheet' | 'modal'
export interface RenderPolicy { surface: Surface; urgency: 'low' | 'normal' | 'blocking'; expires_at?: string | null; default_action_id?: string | null }

export interface AskHuman {
  kind: 'ask_human'
  protocol: string
  id: string
  source: string
  title: string
  prompt: string
  blocks: Block[]
  response: { actions: Action[]; fields?: InputField[]; allow_comment?: boolean }
  policy: RenderPolicy
  context?: Record<string, string>
  created_at: string
}

export interface ClientCapabilities { protocol: string; blocks: Partial<Record<BlockType, number>>; surfaces: Surface[]; max_table_rows: number }

export interface HumanAnswer { ask_id: string; action_id: string; values: Record<string, string | number | boolean | null>; comment?: string | null; answered_at: string }

// What this build renders; sent to the server (e.g. as the X-Ask-Capabilities header).
export const CAPABILITIES: ClientCapabilities = {
  protocol: PROTOCOL,
  blocks: { text: 1, facts: 1, card: 1, table: 1, bill: 1, image: 1, media: 1, map: 1 },
  surfaces: ['inline', 'modal'],
  max_table_rows: 50,
}

export const money = (v: number, currency = 'USD') =>
  (v < 0 ? '−' : '') + (currency === 'USD' ? '$' : currency + ' ') + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const billTotal = (b: BlockOf<'bill'>) => Math.round(b.lines.reduce((s, l) => s + l.amount, 0) * 100) / 100
const cell = (v: Cell | undefined) => (v == null ? '—' : typeof v === 'number' ? v.toLocaleString('en-US', { maximumFractionDigits: 2 }) : v)

// Same chains as the Python fallback() methods.
export function fallback(b: Block): Block | null {
  switch (b.type) {
    case 'text': return null
    case 'facts': return { id: b.id, type: 'text', text: [b.title, ...b.facts.map(f => `${f.label}: ${f.value}` + (f.hint ? ` (${f.hint})` : ''))].filter(Boolean).join('\n') }
    case 'card': return { id: b.id, type: 'text', text: [b.title + (b.subtitle ? ` — ${b.subtitle}` : ''), b.badges?.[0] && `[${b.badges[0]}]`, b.body, ...(b.facts ?? []).map(f => `${f.label}: ${f.value}`)].filter(Boolean).join('\n') }
    case 'table': return { id: b.id, type: 'text', text: [b.title, ...b.rows.map(r => b.columns.map(c => `${c.label} ${cell(r[c.key])}`).join(' · '))].filter(Boolean).join('\n') }
    case 'bill': {
      const cur = b.currency ?? 'USD'
      const rows = [...b.lines.map(l => ({ item: l.label, detail: l.detail ?? '', due: l.due ?? '', amount: money(l.amount, cur) })), { item: b.total_label ?? 'Total', detail: '', due: '', amount: money(billTotal(b), cur) }]
      return {
        id: b.id, type: 'table', title: b.title + (b.issuer ? ` · ${b.issuer}` : ''), rows, highlight_row: rows.length - 1,
        columns: [{ key: 'item', label: 'Item' }, { key: 'detail', label: 'Detail' }, { key: 'due', label: 'Due' }, { key: 'amount', label: 'Amount', align: 'right' }],
      }
    }
    case 'image': return { id: b.id, type: 'text', text: `${b.alt}: ${b.url}` }
    case 'media': return b.poster_url
      ? { id: b.id, type: 'image', url: b.poster_url, alt: b.title, caption: `${b.kind}: ${b.url}` }
      : { id: b.id, type: 'text', text: `${b.title} (${b.kind}): ${b.url}` }
    case 'map': {
      const name = Object.fromEntries(b.markers.map(m => [m.id, m.label]))
      return {
        id: b.id, type: 'table', title: b.title,
        columns: [{ key: 'label', label: 'Place' }, { key: 'kind', label: 'Type' }, { key: 'detail', label: 'Detail' }],
        rows: [
          ...b.markers.map(m => ({ label: m.label, kind: m.kind ?? 'other', detail: m.detail ?? `${m.lat.toFixed(2)}, ${m.lng.toFixed(2)}` })),
          ...(b.routes ?? []).map(r => ({ label: `${name[r.from_id] ?? r.from_id} → ${name[r.to_id] ?? r.to_id}`, kind: `route (${r.style ?? 'sea'})`, detail: r.label ?? '' })),
        ],
      }
    }
    default: {
      // a block type newer than this build: show whatever text it carries
      const u = b as { id: string; text?: string; title?: string }
      return { id: u.id, type: 'text', text: u.text ?? u.title ?? '(unsupported content)' }
    }
  }
}

export function resolve(ask: AskHuman, caps: ClientCapabilities = CAPABILITIES): AskHuman {
  const blocks = ask.blocks.map(b0 => {
    let b: Block | null = b0
    while (b && b.type !== 'text' && (caps.blocks[b.type] ?? 0) < (b.version ?? 1)) b = fallback(b)
    if (b?.type === 'table' && b.rows.length > caps.max_table_rows) {
      const hl = b.highlight_row != null && b.highlight_row < caps.max_table_rows ? b.highlight_row : null
      b = { ...b, rows: b.rows.slice(0, caps.max_table_rows), highlight_row: hl, title: `${b.title ?? 'Table'} (first ${caps.max_table_rows} of ${b.rows.length})` }
    }
    return b
  }).filter((b): b is Block => !!b)
  const policy = caps.surfaces.includes(ask.policy.surface) ? ask.policy : { ...ask.policy, surface: 'inline' as const }
  return { ...ask, blocks, policy }
}

// Client-side check for instant feedback; the server re-validates (validate_answer).
export function validate(ask: AskHuman, actionId: string, values: HumanAnswer['values']): string | null {
  const action = ask.response.actions.find(a => a.id === actionId)
  if (!action) return `Unknown action ${actionId}`
  for (const f of ask.response.fields ?? []) {
    const v = values[f.id] ?? f.default
    if (v == null || v === '') {
      if (f.required && action.requires_fields !== false) return `${f.label} is required`
      continue
    }
    if (f.kind === 'number') {
      const n = Number(v)
      if (typeof v === 'boolean' || Number.isNaN(n)) return `${f.label} must be a number`
      if ((f.min != null && n < f.min) || (f.max != null && n > f.max)) return `${f.label} must be between ${f.min} and ${f.max}`
    }
    if (f.kind === 'select' && !f.options?.some(o => o.value === String(v))) return `${f.label}: pick an option`
  }
  return null
}
