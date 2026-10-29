// Lucian UX/UI Prompt #080 · MIT License (c) 2026 Seokwoooo · https://lucianlabs.dev/uxui-prompt/#080
// Adapted: driven by props (title/sub/done) instead of a timed fake sync; cancel button removed;
// `compact` scales the orbit system down for inline use.
import { useEffect, useRef } from 'react'
import './orbit.css'

const O: [number, number, number, string, number][] = [[105, -18, 5.5, '#22C3A6', 12], [75, 24, 3.6, '#FF6B8B', 10], [50, -58, 2.2, '#FFB547', 9]]

export function OrbitLoader({ title, sub, done, compact }: { title: string; sub?: string; done?: boolean; compact?: boolean }) {
  const sys = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const root = sys.current!
    const core = root.querySelector('.u080-core')!
    const rm = matchMedia('(prefers-reduced-motion: reduce)').matches
    const planets: { el: HTMLElement; o: (typeof O)[number]; ph: number }[] = []
    O.forEach((o, i) => [0, Math.PI].forEach((ph, k) => {
      const p = document.createElement('i')
      p.className = 'u080-p'
      p.style.setProperty('--c', o[3]); p.style.setProperty('--s', (k ? o[4] - 4 : o[4]) + 'px')
      if (k) p.style.opacity = '.7'
      root.insertBefore(p, core)
      planets.push({ el: p, o, ph: ph + i })
    }))
    let t = 0, last = performance.now(), raf = 0
    const orbit = (now: number) => {
      if (!rm) t += (now - last) / 1000
      last = now
      planets.forEach(p => {
        const a = p.ph + t * Math.PI * 2 / p.o[2], tl = p.o[1] * Math.PI / 180
        const x = Math.cos(a) * p.o[0], y = Math.sin(a) * p.o[0] * 0.38
        p.el.style.transform = `translate(${(115 + x * Math.cos(tl) - y * Math.sin(tl)).toFixed(1)}px,${(100 + x * Math.sin(tl) + y * Math.cos(tl)).toFixed(1)}px)`
        p.el.style.zIndex = Math.sin(a) < 0 ? '0' : '2'
      })
      raf = requestAnimationFrame(orbit)
    }
    raf = requestAnimationFrame(orbit)
    return () => { cancelAnimationFrame(raf); planets.forEach(p => p.el.remove()) }
  }, [])
  return (
    <div className={'ux u080' + (done ? ' is-done' : '') + (compact ? ' is-compact' : '')}>
      <div className="u080-sys" ref={sys} aria-hidden="true">
        <div className="u080-o" style={{ ['--d' as string]: '210px', ['--t' as string]: '-18deg' }} />
        <div className="u080-o" style={{ ['--d' as string]: '150px', ['--t' as string]: '24deg' }} />
        <div className="u080-o" style={{ ['--d' as string]: '100px', ['--t' as string]: '-58deg' }} />
        <span className="u080-wave" />
        <span className="u080-core"><svg viewBox="0 0 34 34"><path d="M9 17.5l5.5 5.5L25.5 12" /></svg></span>
      </div>
      <div className="u080-msg" role="status" aria-live="polite"><div className="u080-t"><b>{title}</b></div>{sub && <p className="u080-sub">{sub}</p>}</div>
    </div>
  )
}
