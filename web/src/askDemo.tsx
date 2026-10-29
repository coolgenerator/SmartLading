// Dev-only gallery for the ask-human/1 renderers (open /ask-demo.html on the dev server).
// The same ask is shown at full capability and as a text-and-table-only client would get it.

import { StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/tokens.css'
import './styles/app.css'
import { AskHumanView } from './components/ask/AskHuman'
import { CAPABILITIES, resolve, type AskHuman, type HumanAnswer } from './lib/askHuman'

const SAMPLE: AskHuman = {
  kind: 'ask_human', protocol: 'ask-human/1', id: 'ask_demo', source: 'factory_negotiator', created_at: new Date().toISOString(),
  title: 'Everbright Woodcraft made a final offer',
  prompt: 'Accept 25% deposit, 8,000 units of Oak Bedside Table at $38.00? (Base was 30% at $38.00.)',
  blocks: [
    { id: 'b_card', type: 'card', title: 'Everbright Woodcraft', subtitle: 'Shenzhen, China', badges: ['Low risk'], body: 'Ten years of export work; replies within a day.',
      facts: [{ label: 'Lead time', value: '38 ± 6 d' }, { label: 'MOQ', value: '1,000' }] },
    { id: 'b_bill', type: 'bill', title: 'Proforma invoice', issuer: 'Everbright Woodcraft', lines: [
      { label: 'Deposit (25%)', amount: 76000, detail: '8,000 × $38.00', due: 'On signing' },
      { label: 'Balance', amount: 228000, due: 'Before shipping (~day 38)' },
    ] },
    { id: 'b_map', type: 'map', title: 'Route', markers: [
      { id: 'f', lat: 22.543, lng: 114.058, label: 'Shenzhen', kind: 'supplier', detail: 'Lead time ~38 days' },
      { id: 'p', lat: 33.754, lng: -118.216, label: 'Port of Long Beach', kind: 'port' },
    ], routes: [{ from_id: 'f', to_id: 'p', style: 'sea' }] },
    { id: 'b_table', type: 'table', title: 'Simulated impact', highlight_row: 2,
      columns: [{ key: 'terms', label: 'Terms' }, { key: 'profit', label: 'Exp. profit', align: 'right' }, { key: 'runway', label: 'Runway P10', align: 'right' }],
      rows: [{ terms: 'Base', profit: '$412,300', runway: '>120d' }, { terms: 'Your ask', profit: '$431,900', runway: '>120d' }, { terms: 'Final offer', profit: '$425,100', runway: '>120d' }] },
    { id: 'b_facts', type: 'facts', facts: [{ label: 'Cash after deposit', value: '$144k', hint: '+$15k vs base', tone: 'good' }, { label: 'Lowest P10 cash', value: '$180k' }] },
    { id: 'b_img', type: 'image', url: 'https://picsum.photos/seed/oak/640/240', alt: 'Production sample photo', caption: 'Sample photo from the factory' },
    { id: 'b_text', type: 'text', tone: 'info', text: 'Factory floors are enforced in code; this offer is at or above them.' },
  ],
  response: {
    actions: [{ id: 'accept', label: 'Accept offer', style: 'primary' }, { id: 'continue', label: 'Keep negotiating', requires_fields: false }, { id: 'walk_away', label: 'Walk away', style: 'danger', requires_fields: false }],
    fields: [{ id: 'payment_method', label: 'Pay deposit by', kind: 'select', required: true, default: 'tt', options: [{ value: 'tt', label: 'Wire (T/T)' }, { value: 'lc', label: 'Letter of credit' }] }],
    allow_comment: true,
  },
  policy: { surface: 'inline', urgency: 'blocking', default_action_id: 'continue' },
}

const BASIC = { ...CAPABILITIES, blocks: { text: 1, table: 1 }, surfaces: ['inline' as const] }

function Demo() {
  const [answer, setAnswer] = useState<HumanAnswer | null>(null)
  const [modal, setModal] = useState(false)
  return (
    <main className="page" style={{ maxWidth: 1180, margin: '0 auto', padding: 24 }}>
      <header className="page-head"><div><h1>Ask-human gallery</h1><p className="page-sub">ask-human/1 · same ask at two client capability levels</p></div></header>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(min(100%,440px),1fr))', gap: 16, alignItems: 'start' }}>
        <div>
          <h2 className="card-title">Full client (this build)</h2>
          <AskHumanView ask={SAMPLE} answer={answer} onAnswer={setAnswer} />
          {answer && <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>{JSON.stringify(answer, null, 2)}</pre>}
          <button className="ah-btn" style={{ marginTop: 12 }} onClick={() => setModal(true)}>Open as modal (policy.surface = modal)</button>
          {modal && <AskHumanView ask={{ ...SAMPLE, id: 'ask_modal', policy: { ...SAMPLE.policy, surface: 'modal' } }} onAnswer={() => setModal(false)} />}
        </div>
        <div>
          <h2 className="card-title">Text + table client (degraded by resolve)</h2>
          <AskHumanView ask={resolve(SAMPLE, BASIC)} onAnswer={() => {}} />
        </div>
      </div>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(<StrictMode><Demo /></StrictMode>)
