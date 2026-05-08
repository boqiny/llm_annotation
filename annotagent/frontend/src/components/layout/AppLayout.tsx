import { Outlet, NavLink, Link, useParams, useLocation } from 'react-router-dom'
import { useUiVersion } from '../../hooks/useUiVersion'

export default function AppLayout() {
  const { id } = useParams()
  const loc = useLocation()
  const onHome = loc.pathname === '/'
  const [version, setVersion] = useUiVersion()

  return (
    <div className="min-h-screen bg-cream text-ink">
      {/* Main nav */}
      <header className="border-b border-seam bg-cream/80 backdrop-blur-sm sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link to="/" className="group flex items-baseline gap-3">
            <span className="text-xl font-semibold tracking-tight text-ink">
              AnnotAgent
            </span>
            <span className="font-mono-editorial text-stone-400 hidden sm:inline">
              codebook-driven annotation
            </span>
          </Link>

          <nav className="flex items-center gap-1">
            <TopLink to="/">Projects</TopLink>
            {id && (
              <>
                <Separator />
                <TopLink to={`/projects/${id}/setup`}>Setup</TopLink>
                <TopLink to={`/projects/${id}/codebook`}>Codebook</TopLink>
                <TopLink to={`/projects/${id}/prompt-lab`}>Improve</TopLink>
                <TopLink to={`/projects/${id}/pipeline`}>Annotate</TopLink>
              </>
            )}
            <button
              type="button"
              onClick={() => setVersion(version === 'v2' ? 'v1' : 'v2')}
              title={`Switch to ${version === 'v2' ? 'v1 (legacy)' : 'v2 (new)'} UI`}
              className="ml-3 px-2.5 py-1 border border-seam text-[11px] font-mono tracking-wider uppercase text-stone-500 hover:border-ink hover:text-ink transition-colors"
            >
              UI · {version}
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

function TopLink({ to, children }: { to: string; children: React.ReactNode }) {
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
      {children}
    </NavLink>
  )
}

function Separator() {
  return <span className="text-stone-300 mx-1 select-none">/</span>
}
