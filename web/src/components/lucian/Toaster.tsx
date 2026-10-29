// Lucian UX/UI Prompt #070 · MIT License (c) 2026 Seokwoooo · https://lucianlabs.dev/uxui-prompt/#070
import { useEffect, useRef } from 'react'
import './toaster.css'

export type ToastKind = 'ok' | 'err' | 'info' | 'wait'
export interface ToastInput { kind: ToastKind; title: string; body?: string; action?: string; onAction?: () => void }

const BUS = 'sl-toast'
export function toast(t: ToastInput) {
  window.dispatchEvent(new CustomEvent<ToastInput>(BUS, { detail: t }))
}

const COLOR: Record<ToastKind, string> = { ok: 'var(--ux-mint)', err: 'var(--ux-danger)', info: 'var(--ux-accent)', wait: 'var(--ux-warn)' }
const ICON: Record<ToastKind, string> = {
  ok: '<svg viewBox="0 0 18 18"><path d="M4 9.4l3.2 3.2L14 5.6"/></svg>',
  err: '<svg viewBox="0 0 18 18"><path d="M9 5v5M9 13h.01"/></svg>',
  info: '<svg viewBox="0 0 18 18"><path d="M3.5 4.5h11v7h-6l-3 2.5v-2.5h-2z"/></svg>',
  wait: '<i></i>',
}

export function Toaster() {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const root = ref.current!
    const zone = root.querySelector<HTMLDivElement>('.u070-zone')!
    const live = root.querySelector<HTMLDivElement>('.u070-live')!
    type T = { el: HTMLDivElement; left: number }
    let list: T[] = [], open = false, raf = 0
    const DUR = 4500
    function layout() {
      let acc = 0
      list.forEach((t, i) => {
        const el = t.el
        el.classList.toggle('back', !open && i > 0)
        if (open) { el.style.setProperty('--y', -acc + 'px'); el.style.setProperty('--s', '1'); el.style.setProperty('--o', '1'); acc += el.offsetHeight + 8 }
        else { el.style.setProperty('--y', -(i * 14) + 'px'); el.style.setProperty('--s', (1 - i * 0.06).toFixed(2)); el.style.setProperty('--o', i > 2 ? '0' : '1') }
        el.style.zIndex = String(50 - i)
        el.inert = !open && i > 0
      })
    }
    function remove(t: T, dir?: number) {
      const i = list.indexOf(t)
      if (i < 0) return
      list.splice(i, 1)
      t.el.classList.add('leave')
      if (dir) { t.el.style.setProperty('--dir', String(dir)); t.el.classList.add('side') }
      setTimeout(() => t.el.remove(), 450)
      layout()
    }
    function push(d: ToastInput) {
      const el = document.createElement('div')
      el.className = 'u070-t enter'
      el.style.setProperty('--c', COLOR[d.kind])
      el.setAttribute('role', d.kind === 'err' ? 'alert' : 'status')
      el.innerHTML = '<span class="u070-ic" aria-hidden="true">' + ICON[d.kind] + '</span><span class="u070-tx"><b></b><small></small></span>' + (d.action ? '<button class="u070-act" type="button"></button>' : '') + '<button class="u070-x" type="button" aria-label="Dismiss"><svg viewBox="0 0 14 14"><path d="M3.5 3.5l7 7M10.5 3.5l-7 7"/></svg></button><span class="u070-bar" aria-hidden="true"></span>'
      el.querySelector('b')!.textContent = d.title
      el.querySelector('small')!.textContent = d.body ?? ''
      const t: T = { el, left: DUR }
      zone.appendChild(el)
      list.unshift(t)
      void el.offsetWidth
      el.classList.remove('enter')
      layout()
      live.textContent = d.title
      el.querySelector('.u070-x')!.addEventListener('click', () => remove(t))
      if (d.action) {
        const b = el.querySelector<HTMLButtonElement>('.u070-act')!
        b.textContent = d.action
        b.addEventListener('click', () => { remove(t); d.onAction?.() })
      }
      let sx = 0, dx = 0, down = false
      el.addEventListener('pointerdown', e => { if ((e.target as Element).closest('button')) return; down = true; sx = e.clientX; dx = 0; el.setPointerCapture(e.pointerId); el.classList.add('drag') })
      el.addEventListener('pointermove', e => { if (!down) return; dx = e.clientX - sx; el.style.setProperty('--dx', dx + 'px'); el.style.setProperty('--o', String(Math.max(0.2, 1 - Math.abs(dx) / 260))) })
      const end = () => { if (!down) return; down = false; el.classList.remove('drag'); if (Math.abs(dx) > 90) remove(t, dx > 0 ? 1 : -1); else { el.style.setProperty('--dx', '0px'); layout() } }
      el.addEventListener('pointerup', end); el.addEventListener('pointercancel', end)
      el.addEventListener('pointerenter', e => { if (e.pointerType === 'mouse') setOpen(true) })
      el.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse' && !zone.contains(document.activeElement)) setOpen(false) })
    }
    let last = performance.now()
    const loop = (now: number) => {
      const dt = now - last; last = now
      if (!open) list.slice().forEach((t, i) => {
        if (i > 0) return
        t.left -= dt
        t.el.style.setProperty('--left', Math.max(0, t.left / DUR).toFixed(3))
        if (t.left <= 0) remove(t)
      })
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    function setOpen(v: boolean) { if (open === v) return; open = v; layout() }
    zone.addEventListener('focusin', () => setOpen(true))
    zone.addEventListener('focusout', e => { if (!zone.contains(e.relatedTarget as Node)) setOpen(false) })
    const onToast = (e: Event) => push((e as CustomEvent<ToastInput>).detail)
    window.addEventListener(BUS, onToast)
    return () => {
      window.removeEventListener(BUS, onToast)
      cancelAnimationFrame(raf)
      list.forEach(t => t.el.remove())
      list = []
    }
  }, [])
  return (
    <div ref={ref} className="ux u070">
      <div className="u070-zone" role="region" aria-label="Notifications" tabIndex={-1}>
        <div className="u070-live" aria-live="polite" />
      </div>
    </div>
  )
}
