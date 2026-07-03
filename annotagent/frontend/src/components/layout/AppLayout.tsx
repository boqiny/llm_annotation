import { Outlet, NavLink, Link, useParams, useLocation } from 'react-router-dom'
import { useTour } from '../tour/TourProvider'
import { APP_NAME } from '../../lib/brand'

export default function AppLayout() {
  const { id } = useParams()
  const loc = useLocation()
  const onHome = loc.pathname === '/'
  const { start } = useTour()

  return (
    <div className="min-h-screen bg-cream text-ink">
      {/* Main nav */}
      <header className="border-b border-seam bg-cream/80 backdrop-blur-sm sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link to="/" className="group flex items-baseline gap-3">
            <span className="text-xl font-semibold tracking-tight text-ink">
              {APP_NAME}
            </span>
            <span className="font-mono-editorial text-stone-400 hidden sm:inline">
              codebook-aligned annotation
            </span>
          </Link>

          <nav className="flex items-center gap-1">
            <TopLink to="/">Projects</TopLink>
            {id && (
              <>
                <Separator />
                <TopLink to={`/projects/${id}/setup`} step={1}>Setup</TopLink>
                <TopLink to={`/projects/${id}/prompt-lab`} step={2}>Prompts</TopLink>
                <TopLink to={`/projects/${id}/pipeline`} step={3}>Annotate</TopLink>
                <TopLink to={`/projects/${id}/codebook`}>Codebook</TopLink>
              </>
            )}
            <span className="text-stone-300 mx-1 select-none">/</span>
            <button
              onClick={start}
              className="px-3 py-2 text-sm font-medium text-stone-500 hover:text-ink transition-colors"
            >
              Guide
            </button>
          </nav>
        </div>
      </header>

      {/* Content */}
      <main>
        <div className={`max-w-7xl mx-auto px-6 ${onHome ? 'py-12' : 'py-10'}`}>
          <Outlet />
        </div>
      </main>

    </div>
  )
}

function TopLink({ to, step, children }: { to: string; step?: number; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        `relative px-3 py-2 text-sm font-medium transition-colors ` +
        (isActive
          ? 'text-ink after:content-[""] after:absolute after:left-3 after:right-3 after:-bottom-[17px] after:h-[2px] after:bg-ink'
          : 'text-stone-500 hover:text-ink')
      }
    >
      {step != null && <span className="font-mono text-[10px] text-stone-400 mr-1.5">{step}</span>}
      {children}
    </NavLink>
  )
}

function Separator() {
  return <span className="text-stone-300 mx-1 select-none">/</span>
}
