// Lucian UX/UI Prompt #028 · MIT License (c) 2026 Seokwoooo · https://lucianlabs.dev/uxui-prompt/#028
import { useLayoutEffect, useRef, type ReactNode } from 'react'
import './composer.css'

interface Props {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  label: string
  placeholder: string
  submitLabel: string
  max?: number
  maxHeight?: number
  busy?: boolean
  tools?: ReactNode
}

export function Composer({ value, onChange, onSubmit, label, placeholder, submitLabel, max = 1200, maxHeight = 216, busy, tools }: Props) {
  const ta = useRef<HTMLTextAreaElement>(null)
  const n = Array.from(value).length
  const rest = max - n
  const bad = n === 0 || rest < 0 || !!busy

  useLayoutEffect(() => {
    const el = ta.current!
    const h = el.style.height
    el.style.transition = 'none'
    el.style.height = '24px'
    const need = Math.min(maxHeight, el.scrollHeight)
    el.style.height = h || '24px'
    void el.offsetHeight
    el.style.transition = ''
    el.style.height = need + 'px'
    el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden'
  }, [value, maxHeight])

  const near = rest <= Math.max(20, max * 0.08)
  return (
    <div className={'ux u028' + (near ? ' is-near' : '') + (rest < 0 ? ' is-over' : '')} style={{ ['--p' as string]: Math.min(1, n / max).toFixed(3) }}>
      <div className="u028-box">
        <textarea
          ref={ta}
          className="u028-ta"
          rows={1}
          placeholder={placeholder}
          aria-label={label}
          value={value}
          onChange={e => onChange(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !bad) onSubmit() }}
        />
        <div className="u028-foot">
          <div className="u028-tools">{tools}</div>
          <span className="u028-ring" aria-hidden="true">
            <svg viewBox="0 0 30 30"><circle className="bg" cx="15" cy="15" r="12" /><circle className="fg" cx="15" cy="15" r="12" /></svg>
            <span className="u028-left">{rest}</span>
          </span>
          <span className="u028-sep" aria-hidden="true" />
          <button className="u028-send" type="button" aria-disabled={bad} onClick={() => { if (bad) ta.current?.focus(); else onSubmit() }}>
            {busy ? 'Working…' : submitLabel}
          </button>
        </div>
      </div>
      <span className="u028-sr" aria-live="polite">{rest < 0 ? 'Over the character limit' : ''}</span>
    </div>
  )
}
