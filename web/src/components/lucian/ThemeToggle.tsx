// Lucian UX/UI Prompt #219 · MIT License (c) 2026 Seokwoooo · https://lucianlabs.dev/uxui-prompt/#219
// Adapted: instead of stacking two copies of the page, the real document theme flips inside a
// View Transition whose new snapshot is revealed by the same circular clip-path (.7s, same curve).
import { useEffect, useRef, useState } from 'react'
import './theme.css'

type Theme = 'light' | 'dark'
const KEY = 'sl-theme'

function initial(): Theme {
  try { const t = localStorage.getItem(KEY); if (t === 'light' || t === 'dark') return t } catch { /* storage blocked */ }
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initial)
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem(KEY, theme) } catch { /* storage blocked */ }
    window.dispatchEvent(new CustomEvent('sl-theme', { detail: theme }))
  }, [theme])
  return [theme, setTheme] as const
}

export function ThemeToggle() {
  const [theme, setTheme] = useTheme()
  const btn = useRef<HTMLButtonElement>(null)
  const dark = theme === 'dark'

  const flip = () => {
    const next: Theme = dark ? 'light' : 'dark'
    const doc = document as Document & { startViewTransition?: (cb: () => void) => { ready: Promise<void> } }
    const rm = matchMedia('(prefers-reduced-motion: reduce)').matches
    if (!doc.startViewTransition || rm) { setTheme(next); return }
    const b = btn.current!.getBoundingClientRect()
    const cx = b.left + b.width / 2, cy = b.top + b.height / 2
    const r = Math.hypot(Math.max(cx, innerWidth - cx), Math.max(cy, innerHeight - cy))
    const vt = doc.startViewTransition(() => {
      document.documentElement.dataset.theme = next
      setTheme(next)
    })
    vt.ready.then(() => {
      document.documentElement.animate(
        { clipPath: [`circle(0px at ${cx}px ${cy}px)`, `circle(${r}px at ${cx}px ${cy}px)`] },
        { duration: 700, easing: 'cubic-bezier(.65,0,.35,1)', pseudoElement: '::view-transition-new(root)' },
      )
    })
  }

  return (
    <button ref={btn} type="button" className={'u219-tg' + (dark ? ' is-dark' : '')} aria-pressed={dark} aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'} onClick={flip}>
      {dark
        ? <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M13.5 9.8A5.6 5.6 0 0 1 6.2 2.5a5.6 5.6 0 1 0 7.3 7.3z" fill="currentColor" /></svg>
        : <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="3" fill="currentColor" /><g stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M8 1.5v1.4M8 13.1v1.4M1.5 8h1.4M13.1 8h1.4M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" /></g></svg>}
    </button>
  )
}
