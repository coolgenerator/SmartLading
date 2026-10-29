// Lucian UX/UI Prompt #017 · MIT License (c) 2026 Seokwoooo · https://lucianlabs.dev/uxui-prompt/#017
import { useEffect, useRef, useState } from 'react'
import './slider.css'

interface Props {
  label: string
  hint?: string
  min: number
  max: number
  step: number
  value: number
  onChange: (v: number) => void
  format: (v: number) => string
  ticks?: number[]
  mark?: { value: number; label: string } // e.g. supplier MOQ
}

export function BubbleSlider({ label, hint, min, max, step, value, onChange, format, ticks, mark }: Props) {
  const track = useRef<HTMLDivElement>(null)
  const bub = useRef<HTMLSpanElement>(null)
  const thumb = useRef<HTMLSpanElement>(null)
  const [drag, setDrag] = useState(false)
  const motion = useRef({ lastX: 0, lastT: 0, still: 0 })
  const p = (value - min) / (max - min || 1)
  const rm = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

  useEffect(() => () => clearTimeout(motion.current.still), [])

  const tilt = (deg: number) => {
    if (rm || !bub.current) return
    bub.current.style.setProperty('--tilt', Math.max(-22, Math.min(22, deg)).toFixed(1) + 'deg')
    clearTimeout(motion.current.still)
    motion.current.still = window.setTimeout(() => bub.current?.style.setProperty('--tilt', '0deg'), 90)
  }
  const clamp = (v: number) => Math.max(min, Math.min(max, Math.round(v / step) * step))
  const fromX = (x: number) => {
    const r = track.current!.getBoundingClientRect()
    onChange(clamp(min + Math.max(0, Math.min(1, (x - r.left) / r.width)) * (max - min)))
  }
  const end = () => { setDrag(false); bub.current?.style.setProperty('--tilt', '0deg') }
  const tk = ticks ?? [min, min + (max - min) / 2, max]

  return (
    <div className={'ux u017' + (drag ? ' is-drag' : '')} style={{ ['--v' as string]: p.toFixed(4) }}>
      <div className="u017-head"><b>{label}</b><span>{hint}</span></div>
      <div
        className="u017-track"
        ref={track}
        onPointerDown={e => {
          if (e.button !== 0) return
          track.current!.setPointerCapture(e.pointerId)
          setDrag(true)
          motion.current.lastX = e.clientX; motion.current.lastT = performance.now()
          fromX(e.clientX)
          thumb.current?.focus({ preventScroll: true })
        }}
        onPointerMove={e => {
          if (!track.current!.hasPointerCapture(e.pointerId)) return
          const now = performance.now()
          const vel = (e.clientX - motion.current.lastX) / Math.max(8, now - motion.current.lastT)
          motion.current.lastX = e.clientX; motion.current.lastT = now
          tilt(-vel * 14)
          fromX(e.clientX)
        }}
        onPointerUp={end}
        onPointerCancel={end}
      >
        <span className="u017-fill" aria-hidden="true" />
        {mark && mark.value > min && mark.value < max && (
          <span className="u017-mark" title={mark.label} style={{ left: `${((mark.value - min) / (max - min)) * 100}%` }} aria-hidden="true" />
        )}
        <span className="u017-bub" ref={bub} aria-hidden="true"><span>{format(value)}</span></span>
        <span
          className="u017-thumb"
          ref={thumb}
          role="slider"
          tabIndex={0}
          aria-label={label}
          aria-valuemin={min}
          aria-valuemax={max}
          aria-valuenow={value}
          aria-valuetext={format(value)}
          onKeyDown={e => {
            const big = (max - min) / 10
            let d = ({ ArrowRight: step, ArrowUp: step, ArrowLeft: -step, ArrowDown: -step, PageUp: big, PageDown: -big } as Record<string, number>)[e.key]
            if (e.key === 'Home') d = -(max - min)
            if (e.key === 'End') d = max - min
            if (!d) return
            e.preventDefault()
            tilt(d > 0 ? -9 : 9)
            onChange(clamp(value + d))
          }}
        />
      </div>
      <div className="u017-ticks" aria-hidden="true">
        {tk.map(t => <span key={t} className={(t - min) / (max - min) <= p + 0.001 ? 'on' : ''}>{format(t)}</span>)}
      </div>
    </div>
  )
}
