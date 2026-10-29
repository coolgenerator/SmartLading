// Lucian UX/UI Prompt #039 · MIT License (c) 2026 Seokwoooo · https://lucianlabs.dev/uxui-prompt/#039
// Adapted: only the tab row with the sliding pill; the page renders its own panel content.
import { useLayoutEffect, useRef } from 'react'
import './pilltabs.css'

interface Props { tabs: { id: string; label: string }[]; value: string; onChange: (id: string) => void; label: string }

export function PillTabs({ tabs, value, onChange, label }: Props) {
  const pill = useRef<HTMLSpanElement>(null)
  const btns = useRef<(HTMLButtonElement | null)[]>([])
  const first = useRef(true)
  const cur = Math.max(0, tabs.findIndex(t => t.id === value))

  useLayoutEffect(() => {
    const t = btns.current[cur], p = pill.current
    if (!t || !p) return
    const place = () => { p.style.setProperty('--x', t.offsetLeft + 'px'); p.style.setProperty('--w', t.offsetWidth + 'px') }
    if (first.current) { p.style.transition = 'none'; place(); void p.offsetWidth; p.style.transition = ''; first.current = false }
    else place()
    const ro = new ResizeObserver(place)
    ro.observe(t)
    return () => ro.disconnect()
  }, [cur, tabs.length])

  return (
    <div className="ux u039-tabs" role="tablist" aria-label={label}>
      <span className="u039-pill" ref={pill} aria-hidden="true" />
      {tabs.map((t, i) => (
        <button
          key={t.id}
          ref={el => { btns.current[i] = el }}
          className="u039-tab"
          type="button"
          role="tab"
          aria-selected={i === cur}
          tabIndex={i === cur ? 0 : -1}
          onClick={() => onChange(t.id)}
          onKeyDown={e => {
            const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
            if (!d) return
            e.preventDefault()
            const j = (i + d + tabs.length) % tabs.length
            onChange(tabs[j].id)
            btns.current[j]?.focus()
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}
