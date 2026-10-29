// Lucian UX/UI Prompt #040 · MIT License (c) 2026 Seokwoooo · https://lucianlabs.dev/uxui-prompt/#040
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import './siderail.css'

export interface RailItem { to: string; label: string; icon: ReactNode; badge?: number }

export function SideRail({ items, brand, sub, children }: { items: RailItem[]; brand: string; sub: string; children: ReactNode }) {
  const [wide, setWide] = useState(false)
  const { pathname } = useLocation()
  const hl = useRef<HTMLLIElement>(null)
  const links = useRef<(HTMLAnchorElement | null)[]>([])
  const active = Math.max(0, items.findIndex(it => (it.to === '/' ? pathname === '/' : pathname.startsWith(it.to))))

  useLayoutEffect(() => {
    const li = links.current[active]?.parentElement
    if (li && hl.current) hl.current.style.setProperty('--y', li.offsetTop + 'px')
  }, [active])

  return (
    <div className={'ux u040' + (wide ? ' is-wide' : '')}>
      <nav className="u040-rail" aria-label="Main menu">
        <div className="u040-top">
          <span className="u040-logo" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M3 15l2.5 4h13L21 15M5 15V9h14v6M9 9V5h6v4" /></svg>
          </span>
          <span className="u040-name">SmartLading</span>
        </div>
        <button className="u040-tog" type="button" aria-expanded={wide} aria-label={wide ? 'Collapse menu' : 'Expand menu'} onClick={() => setWide(w => !w)}>
          <svg viewBox="0 0 16 16"><path d="M6 3.5L10.5 8 6 12.5" /></svg>
        </button>
        <ul className="u040-nav">
          <li className="u040-hl" role="presentation" ref={hl} />
          {items.map((it, i) => (
            <li key={it.to}>
              <Link
                ref={el => { links.current[i] = el }}
                to={it.to}
                className="u040-it"
                style={{ ['--i' as string]: i }}
                aria-current={i === active ? 'page' : undefined}
                aria-label={it.label}
                onKeyDown={e => {
                  const d = e.key === 'ArrowDown' ? 1 : e.key === 'ArrowUp' ? -1 : 0
                  if (d) { e.preventDefault(); links.current[(i + d + items.length) % items.length]?.focus() }
                }}
              >
                {it.icon}
                <span>{it.label}</span>
                {it.badge ? <em className="u040-bd" aria-label={`${it.badge} new`}>{it.badge}</em> : null}
              </Link>
            </li>
          ))}
        </ul>
        <div className="u040-me"><i aria-hidden="true" /><span>{brand}<small>{sub}</small></span></div>
      </nav>
      <main className="u040-main">{children}</main>
    </div>
  )
}
