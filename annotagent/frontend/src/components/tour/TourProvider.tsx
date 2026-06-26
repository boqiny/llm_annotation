import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
} from 'react'
import { useLocation } from 'react-router-dom'
import { TOUR_STEPS, type TourStep, pageOf, stepForPage } from './steps'
import { APP_NAME } from '../../lib/brand'

const DONE_KEY = 'annotagent.tour.v1.done'
const ACTIVE_KEY = 'annotagent.tour.v1.active'

const loadActive = () => {
  try { return localStorage.getItem(ACTIVE_KEY) === '1' } catch { return false }
}

type TourCtx = { start: () => void; stop: () => void; active: boolean }
const Ctx = createContext<TourCtx>({ start() {}, stop() {}, active: false })
export const useTour = () => useContext(Ctx)

const reducedMotion = () =>
  typeof window !== 'undefined' &&
  !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

const PAD = 8
const GAP = 12
const W = 320

export function TourProvider({ children }: { children: React.ReactNode }) {
  const loc = useLocation()
  const [active, setActive] = useState(loadActive)
  const [welcomeOpen, setWelcomeOpen] = useState(false)
  // Bumped by DOM mutations / scroll / resize so we re-measure the anchor.
  const [, setVersion] = useState(0)
  const bump = useCallback(() => setVersion(v => v + 1), [])

  const scrolledTo = useRef<string | null>(null)

  const start = useCallback(() => {
    setWelcomeOpen(false)
    setActive(true)
    scrolledTo.current = null
    try { localStorage.setItem(ACTIVE_KEY, '1'); localStorage.setItem(DONE_KEY, '1') } catch {}
    bump()
  }, [bump])

  const stop = useCallback(() => {
    setActive(false)
    setWelcomeOpen(false)
    try { localStorage.setItem(ACTIVE_KEY, '0'); localStorage.setItem(DONE_KEY, '1') } catch {}
  }, [])

  // First-visit welcome, only on the home page and only once.
  useEffect(() => {
    if (loc.pathname !== '/' || active) return
    let done = false
    try { done = !!localStorage.getItem(DONE_KEY) } catch {}
    if (!done) setWelcomeOpen(true)
  }, [loc.pathname, active])

  // Re-measure on layout / route / DOM changes while the tour runs.
  useEffect(() => {
    if (!active) return
    let raf = 0
    const schedule = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(bump) }
    const mo = new MutationObserver(schedule)
    // Watch structure changes, plus only the tour's own readiness/done attributes
    // (not every class/aria toggle) so a "ready" flip re-scans without a perf loop.
    mo.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['data-tour-ready', 'data-tour-done'],
    })
    window.addEventListener('resize', schedule)
    window.addEventListener('scroll', schedule, true)
    return () => {
      mo.disconnect()
      window.removeEventListener('resize', schedule)
      window.removeEventListener('scroll', schedule, true)
      cancelAnimationFrame(raf)
    }
  }, [active, bump])

  // Esc exits.
  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') stop() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, stop])

  // The displayed step is DERIVED from where the user is — never from a counter
  // the user can advance. This is what keeps the tour matched to the real page
  // and section, and what stops the user from clicking past mandatory work.
  const page = pageOf(loc.pathname)
  const step: TourStep | null = active && page ? stepForPage(page) : null
  const el = step ? document.querySelector(step.selector) : null
  const rect = el ? el.getBoundingClientRect() : null
  const done = el?.getAttribute('data-tour-done') === 'true'
  const num = step ? TOUR_STEPS.indexOf(step) + 1 : 0
  const isLast = step ? num === TOUR_STEPS.length : false
  const reduce = reducedMotion()

  // Scroll the spotlight into view once per step, so the highlighted control is
  // never off screen (for example, the Run improvement button sits low on its tab).
  useEffect(() => {
    if (!active || !step || !el) return
    if (scrolledTo.current === step.id) return
    scrolledTo.current = step.id
    const r = el.getBoundingClientRect()
    const inView = r.top >= 0 && r.bottom <= window.innerHeight
    if (!inView) el.scrollIntoView({ block: 'center', behavior: reduce ? 'auto' : 'smooth' })
  }, [active, step?.id, el, reduce])

  return (
    <Ctx.Provider value={{ start, stop, active }}>
      {children}

      {welcomeOpen && <Welcome onStart={start} onSkip={stop} />}

      {active && step && rect && (
        <>
          {/* Spotlight: ring + page dimmer via one large box-shadow. pointer-events
              stays off so the highlighted control underneath is still usable. */}
          <div
            style={{
              position: 'fixed',
              top: rect.top - PAD,
              left: rect.left - PAD,
              width: rect.width + PAD * 2,
              height: rect.height + PAD * 2,
              borderRadius: 10,
              border: '2px solid #0b0b0a',
              boxShadow: '0 0 0 9999px rgba(11, 11, 10, 0.55)',
              pointerEvents: 'none',
              zIndex: 100,
              transition: reduce ? 'none' : 'all 0.18s ease',
            }}
          />
          <Popover
            step={step}
            rect={rect}
            num={num}
            total={TOUR_STEPS.length}
            isLast={isLast}
            done={done}
            onFinish={stop}
            onSkip={stop}
          />
        </>
      )}

      {/* Anchor not mounted yet (a panel is still loading) — brief hint, no overlay. */}
      {active && step && !rect && (
        <Pill page={page} title={step.title} body={step.body} onSkip={stop} />
      )}

      {/* The user wandered to a page the tour does not cover. */}
      {active && !page && (
        <Pill
          page={page}
          title="Guide paused"
          body="The guide covers Setup and the Prompts hub. Open one to continue, or end the guide."
          onSkip={stop}
        />
      )}
    </Ctx.Provider>
  )
}

function Popover({
  step, rect, num, total, isLast, done, onFinish, onSkip,
}: {
  step: TourStep
  rect: DOMRect
  num: number
  total: number
  isLast: boolean
  done: boolean
  onFinish: () => void
  onSkip: () => void
}) {
  const vh = window.innerHeight
  const vw = window.innerWidth
  const placeBelow = vh - rect.bottom > 220 || vh - rect.bottom > rect.top
  const left = Math.min(Math.max(GAP, rect.left), vw - W - GAP)
  // Cap height to the room on the chosen side so the card can never run off screen.
  const maxHeight = Math.max(140, (placeBelow ? vh - rect.bottom : rect.top) - GAP * 2)
  const style: React.CSSProperties = placeBelow
    ? { top: rect.bottom + GAP, left, width: W, maxHeight, overflowY: 'auto' }
    : { bottom: vh - rect.top + GAP, left, width: W, maxHeight, overflowY: 'auto' }

  return (
    <div
      role="dialog"
      aria-label={step.title}
      className="fixed z-[101] surface-card shadow-xl p-4"
      style={{ ...style, borderColor: '#E4E4E0' }}
    >
      <div className="font-mono-editorial text-stone-500 mb-2">
        Guided tour · step {num} of {total}
      </div>
      <div className="text-sm font-semibold text-ink">{step.title}</div>
      <p className="mt-1.5 text-sm leading-relaxed text-stone-600">{step.body}</p>
      {step.need && !done && (
        <p className="mt-2 border-l-2 border-amber-500 pl-2 text-xs leading-relaxed text-amber-800">
          {step.need}
        </p>
      )}
      {step.need && done && (
        <p className="mt-2 font-mono-editorial text-emerald-700">Done · continue when ready</p>
      )}
      <div className="mt-4 flex items-center justify-between">
        <button onClick={onSkip} className="font-mono-editorial text-stone-400 hover:text-ink">
          End tour
        </button>
        {isLast && (
          <button
            onClick={onFinish}
            className="px-4 py-1.5 bg-ink text-cream text-sm font-medium hover:bg-stone-800 transition-colors"
          >
            Finish
          </button>
        )}
      </div>
    </div>
  )
}

function Pill({
  page, title, body, onSkip,
}: {
  page: string | null
  title: string
  body: string
  onSkip: () => void
}) {
  return (
    <div
      className="fixed bottom-5 left-1/2 z-[101] -translate-x-1/2 surface-card shadow-lg px-4 py-3 max-w-sm"
      style={{ borderColor: '#E4E4E0' }}
    >
      <div className="font-mono-editorial text-stone-500 mb-1">Guided tour{page ? '' : ' · paused'}</div>
      <div className="text-sm font-medium text-ink">{title}</div>
      <p className="mt-1 text-xs leading-relaxed text-stone-600">{body}</p>
      <button onClick={onSkip} className="mt-2 font-mono-editorial text-stone-400 hover:text-ink">
        End tour
      </button>
    </div>
  )
}

function Welcome({ onStart, onSkip }: { onStart: () => void; onSkip: () => void }) {
  return (
    <div
      className="fixed inset-0 z-[110] flex items-center justify-center bg-ink/40 px-4"
      onClick={onSkip}
    >
      <div
        className="surface-card max-w-lg w-full p-8"
        style={{ borderColor: '#E4E4E0' }}
        onClick={e => e.stopPropagation()}
      >
        <div className="font-mono-editorial text-stone-500 mb-3">New here?</div>
        <h2 className="text-2xl font-medium tracking-tight">
          A short tour of the golden path
        </h2>
        <p className="mt-3 text-sm leading-relaxed text-stone-600">
          {APP_NAME} turns a codebook into LLM annotations. The guide follows along as you work, one section at a time:
        </p>
        <ol className="mt-5 space-y-3">
          <WelcomeRow n="01" title="Create a project" body="Name your task and open Setup." />
          <WelcomeRow n="02" title="Set up" body="Pick a model, confirm the codebook, add a few labeled examples, then generate the pipeline." />
          <WelcomeRow n="03" title="Optimize a prompt" body="Open the Prompts hub and run an improvement against your labeled data." />
        </ol>
        <div className="mt-7 flex items-center gap-3">
          <button
            onClick={onStart}
            className="px-5 py-2.5 bg-ink text-cream text-sm font-medium hover:bg-stone-800 transition-colors"
          >
            Take the tour →
          </button>
          <button onClick={onSkip} className="text-sm text-stone-500 hover:text-ink">
            Maybe later
          </button>
        </div>
      </div>
    </div>
  )
}

function WelcomeRow({ n, title, body }: { n: string; title: string; body: string }) {
  return (
    <li className="flex gap-4">
      <span className="font-mono-editorial text-stone-400 pt-0.5">{n}</span>
      <div>
        <div className="text-sm font-medium text-ink">{title}</div>
        <p className="text-sm text-stone-600 leading-relaxed">{body}</p>
      </div>
    </li>
  )
}
