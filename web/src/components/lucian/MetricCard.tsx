// Lucian UX/UI Prompt #098 · MIT License (c) 2026 Seokwoooo · https://lucianlabs.dev/uxui-prompt/#098
import { useEffect, useId, useRef, useState } from 'react'
import './metric.css'

export interface Metric {
  name: string
  title: string
  text: string // formatted value, e.g. "$380,000"
  delta: number // relative change vs base, e.g. -0.12
  deltaLabel: string
  series: number[]
}

const W = 340, H = 128

// The rolling digits from #098: one column per digit, only changed digits spin.
export function RollingNumber({ text, label }: { text: string; label: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const shown = useRef('')
  useEffect(() => {
    const num = ref.current!
    let cols = num.querySelectorAll<HTMLSpanElement>('.u098-col')
    const same = shown.current.replace(/\d/g, '0') === text.replace(/\d/g, '0')
    if (!same) {
      num.innerHTML = ''
      text.split('').forEach((ch, i) => {
        const s = document.createElement('span')
        if (/\d/.test(ch)) {
          s.className = 'u098-col'; s.style.setProperty('--d', '0'); s.style.setProperty('--i', String(i))
          s.innerHTML = '<span>0</span><span>1</span><span>2</span><span>3</span><span>4</span><span>5</span><span>6</span><span>7</span><span>8</span><span>9</span>'
        } else { s.className = 'u098-sym' + (ch === 'k' || ch === 'M' || ch === '%' || ch === 'd' ? ' sm' : ''); s.textContent = ch }
        num.appendChild(s)
      })
      void num.offsetWidth
      cols = num.querySelectorAll('.u098-col')
    }
    let j = 0
    text.split('').forEach(ch => { if (/\d/.test(ch)) cols[j++].style.setProperty('--d', ch) })
    shown.current = text
  }, [text])
  return <div className="u098-num" role="img" aria-label={`${label} ${text}`} ref={ref} />
}

export function MetricCard({ metrics, header }: { metrics: Metric[]; header?: string }) {
  const [k, setK] = useState(0)
  const uid = useId().replace(/:/g, '')
  const ln = useRef<SVGPathElement>(null)
  const ar = useRef<SVGPathElement>(null)
  const hd = useRef<SVGCircleElement>(null)
  const ys = useRef<number[] | null>(null)
  const m = metrics[k]

  useEffect(() => {
    const v = m.series
    const mn = Math.min(...v), mx = Math.max(...v), pad = (mx - mn) * 0.35 || 1
    const Y = (x: number) => 8 + (1 - (x - (mn - pad)) / (mx - mn + 2 * pad)) * (H - 16)
    const step = (W - 16) / (v.length - 1)
    const to = v.map(Y)
    const from = ys.current && ys.current.length === to.length ? ys.current : to
    const rm = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const t0 = performance.now()
    let raf = 0
    const paint = (y: number[]) => {
      const p = y.map((yy, i) => (i ? 'L' : 'M') + (i * step).toFixed(1) + ' ' + yy.toFixed(1)).join('')
      const n = y.length - 1
      ln.current!.setAttribute('d', p)
      ar.current!.setAttribute('d', p + 'L' + (n * step).toFixed(1) + ' ' + (H + 4) + 'L0 ' + (H + 4) + 'Z')
      hd.current!.setAttribute('cx', (n * step).toFixed(1)); hd.current!.setAttribute('cy', y[n].toFixed(1))
    }
    const f = (now: number) => {
      const t = rm ? 1 : Math.min(1, (now - t0) / 600), e = t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
      const y = from.map((yy, j) => yy + (to[j] - yy) * e)
      ys.current = y
      paint(y)
      if (t < 1) raf = requestAnimationFrame(f)
    }
    raf = requestAnimationFrame(f)
    return () => cancelAnimationFrame(raf)
  }, [m.series])

  const up = m.delta >= 0
  return (
    <div className="ux u098">
      <div className="u098-h"><span className="u098-live" aria-hidden="true" /><span>{m.title}</span>{header && <span className="u098-ver">{header}</span>}</div>
      <RollingNumber text={m.text} label={m.title} />
      <div className="u098-dl">
        <span className={'u098-bd' + (up ? '' : ' dn')} style={{ ['--c' as string]: up ? 'var(--ux-mint)' : 'var(--ux-danger)' }}>
          <svg viewBox="0 0 10 10" aria-hidden="true"><path d="M5 1.5L9 7.5H1z" /></svg><b>{Math.abs(m.delta * 100).toFixed(1)}%</b>
        </span>
        <span>{m.deltaLabel}</span>
      </div>
      <div className="u098-sp" aria-hidden="true">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          <defs><linearGradient id={uid} className="u098-gd" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopOpacity=".26" /><stop offset="1" stopOpacity="0" /></linearGradient></defs>
          <path ref={ar} fill={`url(#${uid})`} /><path ref={ln} className="u098-ln" />
          <circle ref={hd} r="5" style={{ fill: 'var(--ux-accent)', stroke: 'var(--ux-surface)', strokeWidth: 2.5 }} />
        </svg>
      </div>
      <div className="u098-tabs" role="group" aria-label="Metrics">
        {metrics.map((mm, i) => (
          <button key={mm.name} type="button" className="u098-tb" aria-pressed={i === k} onClick={() => setK(i)}>
            <small>{mm.name}</small><b>{mm.text}</b>
            <em className={mm.delta < 0 ? 'dn' : ''}>{(mm.delta >= 0 ? '+' : '−') + Math.abs(mm.delta * 100).toFixed(1)}%</em>
          </button>
        ))}
      </div>
    </div>
  )
}
