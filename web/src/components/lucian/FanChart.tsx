// Lucian UX/UI Prompt #165 · MIT License (c) 2026 Seokwoooo · https://lucianlabs.dev/uxui-prompt/#165
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { usdK } from '../../lib/format'
import type { CashFan } from '../../lib/types'
import './fanchart.css'

export interface FanSeries { id: string; label: string; fan: CashFan }

interface Props {
  series: FanSeries[]
  active: string
  onActive?: (id: string) => void
  compare?: { id: string; label: string } | null // second P50 overlay (US-6)
  height?: number
}

const PAD = { l: 52, r: 12, t: 14, b: 26 }

export function FanChart({ series, active, onActive, compare, height = 280 }: Props) {
  const wrap = useRef<HTMLDivElement>(null)
  const band = useRef<SVGPolygonElement>(null)
  const [w, setW] = useState(600)
  const [hover, setHover] = useState<number | null>(null)
  const cur = series.find(s => s.id === active) ?? series[0]
  const cmp = compare ? series.find(s => s.id === compare.id) : null

  useLayoutEffect(() => {
    const el = wrap.current!
    const ro = new ResizeObserver(() => setW(el.clientWidth))
    ro.observe(el)
    setW(el.clientWidth)
    return () => ro.disconnect()
  }, [])

  // shared y-domain across options so switching shows real differences
  const all = series.flatMap(s => [...s.fan.p10, ...s.fan.p90, s.fan.safety_line])
  const lo = Math.min(0, ...all), hi = Math.max(...all)
  const n = cur.fan.days.length - 1
  const X = (d: number) => PAD.l + (d / n) * (w - PAD.l - PAD.r)
  const Y = (v: number) => PAD.t + (1 - (v - lo) / (hi - lo || 1)) * (height - PAD.t - PAD.b)
  const line = (arr: number[]) => arr.map((v, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1)).join('')

  // #165 band morph: interpolate polygon points with an ease-out cubic over 500ms
  useEffect(() => {
    const el = band.current!
    const target = cur.fan.p90.map((v, i) => [X(i), Y(v)]).concat(cur.fan.p10.map((v, i) => [X(i), Y(v)]).reverse())
    const prev = el.getAttribute('points')
    const old = prev ? prev.split(' ').map(p => p.split(',').map(Number)) : target
    const same = old.length === target.length
    const start = performance.now()
    const duration = !same || matchMedia('(prefers-reduced-motion:reduce)').matches ? 0 : 500
    let af = 0
    const tick = (now: number) => {
      let t = duration ? Math.min(1, (now - start) / duration) : 1
      t = 1 - Math.pow(1 - t, 3)
      el.setAttribute('points', target.map((p, i) => p.map((v, j) => (same ? old[i][j] + (v - old[i][j]) * t : v).toFixed(1)).join(',')).join(' '))
      if (t < 1) af = requestAnimationFrame(tick)
    }
    tick(start)
    return () => cancelAnimationFrame(af)
  })

  const ticksY = 4
  const yTicks = Array.from({ length: ticksY + 1 }, (_, i) => lo + ((hi - lo) * i) / ticksY)
  const xTicks = [0, 30, 60, 90, n]
  const hd = hover ?? null

  return (
    <div className="ux u165" ref={wrap}>
      <svg
        className="forecast"
        style={{ height }}
        viewBox={`0 0 ${w} ${height}`}
        role="img"
        aria-label={`Cash fan for option ${cur.label}: P50 ends at ${usdK(cur.fan.p50[n])}, P10 low ${usdK(Math.min(...cur.fan.p10))}`}
        onPointerMove={e => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
          const d = Math.round(((e.clientX - r.left - PAD.l) / (w - PAD.l - PAD.r)) * n)
          setHover(d >= 0 && d <= n ? d : null)
        }}
        onPointerLeave={() => setHover(null)}
      >
        {yTicks.map(v => (
          <g key={v}>
            <path className="gridline" d={`M${PAD.l} ${Y(v)}H${w - PAD.r}`} opacity={0.5} />
            <text x={PAD.l - 8} y={Y(v) + 4} textAnchor="end">{usdK(v)}</text>
          </g>
        ))}
        {xTicks.map(d => <text key={d} x={X(d)} y={height - 6} textAnchor="middle">{d === 0 ? 'Today' : `Day ${d}`}</text>)}
        <polygon ref={band} className="band" />
        <path className="safety" d={`M${PAD.l} ${Y(cur.fan.safety_line)}H${w - PAD.r}`} />
        <text className="safety-lbl" x={w - PAD.r} y={Y(cur.fan.safety_line) - 6} textAnchor="end">Safety line {usdK(cur.fan.safety_line)}</text>
        {cmp && cmp.id !== cur.id && <path className="future" d={line(cmp.fan.p50)} />}
        <path className="past" d={line(cur.fan.p50)} />
        {hd !== null && (
          <g>
            <line className="cross" x1={X(hd)} x2={X(hd)} y1={PAD.t} y2={height - PAD.b} />
            <circle className="dot" cx={X(hd)} cy={Y(cur.fan.p50[hd])} r={4.5} />
          </g>
        )}
      </svg>
      <div className="legend" aria-hidden="true">
        <span><i className="band" />P10–P90</span>
        <span><i style={{ ['--c' as string]: 'var(--ux-ink)' }} />P50 · Option {cur.label}</span>
        {cmp && cmp.id !== cur.id && <span><i className="dash" style={{ ['--c' as string]: 'var(--ux-warn)' }} />P50 · Option {cmp.label}</span>}
        <span><i className="dash" style={{ ['--c' as string]: 'var(--ux-danger)' }} />Cash safety line</span>
      </div>
      {onActive && series.length > 1 && (
        <div className="controls" role="group" aria-label="Option shown in the fan">
          {series.map(s => <button key={s.id} type="button" aria-pressed={s.id === cur.id} onClick={() => onActive(s.id)}>Option {s.label}</button>)}
        </div>
      )}
      <div className="status" aria-live="polite">
        {hd !== null
          ? <>Day {hd} · P10 <b>{usdK(cur.fan.p10[hd])}</b> · P50 <b>{usdK(cur.fan.p50[hd])}</b> · P90 <b>{usdK(cur.fan.p90[hd])}</b>{cmp && cmp.id !== cur.id ? <> · {cmp.label} P50 <b>{usdK(cmp.fan.p50[hd])}</b></> : null}</>
          : <>Lowest P10 cash · <b>{usdK(Math.min(...cur.fan.p10))}</b> · Day-{n} P50 · <b>{usdK(cur.fan.p50[n])}</b></>}
      </div>
    </div>
  )
}
