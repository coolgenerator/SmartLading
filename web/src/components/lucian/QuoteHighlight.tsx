// Lucian UX/UI Prompt #281 · MIT License (c) 2026 Seokwoooo · https://lucianlabs.dev/uxui-prompt/#281
// Adapted: marks come from signal quote_spans in the source text; the pen color follows the
// signal status (yellow pending, mint accepted, pink rejected) instead of a pen picker.
import { useEffect, useRef, useState } from 'react'
import './highlight.css'

export interface Span { start: number; end: number; color: string; id: string }

export function QuoteHighlight({ text, spans, focusId }: { text: string; spans: Span[]; focusId?: string | null }) {
  const ref = useRef<HTMLParagraphElement>(null)
  const [on, setOn] = useState(false)
  const key = spans.map(s => s.id).join('|')

  useEffect(() => {
    setOn(false)
    const rm = matchMedia('(prefers-reduced-motion: reduce)').matches
    let at = 0.25
    ref.current!.querySelectorAll<HTMLElement>('mark').forEach(m => {
      const d = Math.min(1.4, 0.25 + (m.textContent ?? '').length * 0.045)
      m.style.setProperty('--d', d.toFixed(2) + 's')
      m.style.setProperty('--w', at.toFixed(2) + 's')
      at += d + 0.12
    })
    let r2 = 0
    const r1 = requestAnimationFrame(() => { r2 = requestAnimationFrame(() => setOn(true)) })
    if (rm) setOn(true)
    return () => { cancelAnimationFrame(r1); cancelAnimationFrame(r2) }
  }, [key, text])

  const sorted = [...spans].sort((a, b) => a.start - b.start)
  const parts: React.ReactNode[] = []
  let i = 0
  for (const s of sorted) {
    if (s.start < i) continue
    parts.push(text.slice(i, s.start))
    parts.push(
      <mark key={s.id} data-sig={s.id} className={focusId === s.id ? 'is-focus' : ''} style={{ ['--u281-m' as string]: s.color }}>
        {text.slice(s.start, s.end)}
      </mark>,
    )
    i = s.end
  }
  parts.push(text.slice(i))
  return <p ref={ref} className={'ux u281-p' + (on ? ' is-on' : '')}>{parts}</p>
}
