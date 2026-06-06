import { useEffect, useMemo, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getProject, listCodebooks } from '../lib/api'
import type { Codebook, Dimension, Label, Project } from '../types'

type RawCodebook = {
  mode?: 'single_label' | 'multi_label' | 'mixed'
  dimensions?: Array<{ name: string; type?: string; instructions?: string }>
}

export default function CodebookView() {
  const { id } = useParams<{ id: string }>()
  const projectId = Number(id)

  const [project, setProject] = useState<Project | null>(null)
  const [codebook, setCodebook] = useState<Codebook | null>(null)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  useEffect(() => {
    Promise.all([getProject(projectId), listCodebooks(projectId)]).then(([p, cbs]) => {
      setProject(p)
      if (cbs.length > 0) setCodebook(cbs[cbs.length - 1])
    })
  }, [projectId])

  const raw = (codebook?.raw_json ?? {}) as RawCodebook
  const mode: 'single_label' | 'multi_label' | 'mixed' = useMemo(() => {
    if (!codebook) return 'single_label'
    if (raw.mode) return raw.mode
    const types = new Set(codebook.dimensions.map(d => (d.dim_type || '').toLowerCase()))
    if (types.has('multi_label') && types.has('single_label')) return 'mixed'
    if (types.has('multi_label')) return 'multi_label'
    return 'single_label'
  }, [codebook, raw])

  if (!codebook || !project) {
    return (
      <div className="min-h-[60vh] grid place-items-center">
        <div className="text-center space-y-4">
          <div className="font-mono-editorial text-stone-400">
            No codebook loaded
          </div>
          <Link
            to={`/projects/${projectId}/setup`}
            className="inline-flex items-center gap-2 px-4 py-2 bg-ink text-cream text-sm font-medium hover:bg-stone-800 transition"
          >
            <span aria-hidden="true">←</span>
            Back to setup
          </Link>
        </div>
      </div>
    )
  }

  const toggleDim = (id: number) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const allExpanded = expanded.size === codebook.dimensions.length
  const toggleAll = () => {
    if (allExpanded) setExpanded(new Set())
    else setExpanded(new Set(codebook.dimensions.map(d => d.id)))
  }

  return (
    <div className="space-y-12">
      {/* Masthead */}
      <header className="border-b border-seam pb-8">
        <div className="flex items-center justify-between gap-4 mb-4">
          <div className="font-mono-editorial text-stone-500">
            Codebook · №{codebook.id.toString().padStart(3, '0')}
          </div>
          <Link
            to={`/projects/${projectId}/setup`}
            className="inline-flex items-center gap-2 px-4 py-2 bg-ink text-cream text-sm font-medium hover:bg-stone-800 transition shrink-0"
          >
            <span aria-hidden="true">←</span>
            Back to setup
          </Link>
        </div>

        <h1 className="text-4xl sm:text-5xl font-medium tracking-tight text-ink mb-3 leading-[1.05]">
          {codebook.name}
        </h1>
        {codebook.description && (
          <p className="text-stone-600 text-base max-w-3xl leading-relaxed">
            {codebook.description}
          </p>
        )}

        <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-3 text-sm">
          <ModeBadge mode={mode} />
          <MetaPair label="Dimensions" value={codebook.dimensions.length} />
          <MetaPair label="Labels" value={codebook.dimensions.reduce((s, d) => s + d.labels.length, 0)} />
        </div>
      </header>

      {/* Dimensions header + expand-all */}
      <section>
        <div className="flex items-baseline justify-between border-b border-seam pb-3 mb-6">
          <SectionLabel className="mb-0">
            The {codebook.dimensions.length} dimensions
          </SectionLabel>
          <button
            onClick={toggleAll}
            className="font-mono-editorial text-stone-500 hover:text-ink transition"
          >
            {allExpanded ? 'Collapse all' : 'Expand all'}
          </button>
        </div>

        <div className="space-y-5">
          {codebook.dimensions.map((dim, index) => (
            <DimensionCard
              key={dim.id}
              dim={dim}
              index={index}
              rawDim={raw.dimensions?.find(d => d.name === dim.name)}
              isOpen={expanded.has(dim.id)}
              onToggle={() => toggleDim(dim.id)}
            />
          ))}
        </div>
      </section>

      <section className="border border-violet-200 bg-violet-50 px-5 py-4">
        <div className="font-medium text-violet-950">Final codebook check</div>
        <p className="mt-1 max-w-4xl text-sm leading-relaxed text-violet-900">
          Review the dimensions, labels, and definitions carefully before generating prompts or running annotation.
          This codebook controls the prompts, improvement behavior, annotation labels, and exported result columns.
          If anything looks wrong, go back to setup and replace or edit the codebook first.
        </p>
        <Link
          to={`/projects/${projectId}/setup`}
          className="mt-3 inline-flex items-center gap-2 px-4 py-2 bg-ink text-cream text-sm font-medium hover:bg-stone-800 transition"
        >
          <span aria-hidden="true">←</span>
          Back to setup
        </Link>
      </section>

      {/* Footer */}
      <footer className="pt-8 border-t border-seam flex items-baseline justify-between font-mono-editorial text-stone-400">
        <span>CodebookAgent artifact</span>
        <span>editable at /api/projects/{projectId}/codebooks</span>
      </footer>
    </div>
  )
}

/* ─── Primitives ─────────────────────────────────────────── */

function ModeBadge({ mode }: { mode: 'single_label' | 'multi_label' | 'mixed' }) {
  const cfg = {
    single_label: { bg: 'bg-emerald-50', text: 'text-emerald-800', border: 'border-emerald-300', label: 'single-label' },
    multi_label:  { bg: 'bg-violet-50',  text: 'text-violet-800',  border: 'border-violet-300',  label: 'multi-label' },
    mixed:        { bg: 'bg-amber-50',   text: 'text-amber-800',   border: 'border-amber-300',   label: 'mixed' },
  }[mode]
  return (
    <span className={`inline-flex items-center gap-2 px-3 py-1 text-xs font-mono tracking-wider uppercase border ${cfg.bg} ${cfg.text} ${cfg.border}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {cfg.label}
    </span>
  )
}

function MetaPair({ label, value, accent = false }: { label: string; value: number | string; accent?: boolean }) {
  return (
    <span className="inline-flex items-baseline gap-2">
      <span className="font-mono-editorial text-stone-500">{label}</span>
      <span className={`font-mono text-sm ${accent ? 'text-indigo-700 font-semibold' : 'text-stone-800 font-medium'}`}>
        {value}
      </span>
    </span>
  )
}

function SectionLabel({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`font-mono-editorial text-stone-500 flex items-center gap-3 ${className}`}>
      <span className="w-5 h-px bg-stone-400" />
      {children}
    </div>
  )
}

/* ─── DimensionCard (the main refactor) ─────────────────── */

function DimensionCard({
  dim, index, rawDim, isOpen, onToggle,
}: {
  dim: Dimension
  index: number
  rawDim?: { name: string; type?: string; instructions?: string }
  isOpen: boolean
  onToggle: () => void
}) {
  const isMulti = (dim.dim_type || '').toLowerCase() === 'multi_label'
  const accentColor = isMulti ? 'bg-violet-500' : 'bg-indigo-500'

  return (
    <article className="relative bg-white border border-seam">
      {/* Slim left accent strip */}
      <div className={`absolute left-0 top-0 bottom-0 w-[3px] ${accentColor}`} />

      {/* Header row — clickable */}
      <button
        type="button"
        onClick={onToggle}
        className="w-full text-left pl-6 pr-6 py-5 hover:bg-paper/40 transition-colors"
      >
        <div className="grid grid-cols-12 gap-4 items-center">
          <div className="col-span-1 font-mono text-stone-400 text-sm">
            {String(index + 1).padStart(2, '0')}
          </div>
          <div className="col-span-10 min-w-0">
            <div className="font-mono-editorial text-stone-400 mb-1">
              {isMulti ? 'multi-label' : 'single-label'} · {dim.labels.length} labels
            </div>
            <h2 className="text-xl font-medium tracking-tight text-ink truncate">{dim.name}</h2>
          </div>
          <div className="col-span-1 text-right font-mono text-stone-400 text-sm">
            {isOpen ? '−' : '+'}
          </div>
        </div>
      </button>

      {/* Expanded body */}
      {isOpen && (
        <div className="border-t border-seam pl-6 pr-6 py-5 space-y-6">
          {/* Guidance */}
          {(dim.instructions || rawDim?.instructions) && (
            <div>
              <div className="font-mono-editorial text-stone-500 mb-2">
                Annotator guidance
              </div>
              <p className="text-sm text-stone-700 leading-relaxed max-w-3xl">
                {dim.instructions || rawDim?.instructions}
              </p>
            </div>
          )}

          {/* Labels — uniform grid */}
          <div>
            <div className="font-mono-editorial text-stone-500 mb-3">
              Labels
            </div>
            <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {dim.labels.map(lbl => (
                <LabelCard key={lbl.id} label={lbl} isMulti={isMulti} />
              ))}
            </ul>
          </div>
        </div>
      )}
    </article>
  )
}

function LabelCard({ label, isMulti }: { label: Label; isMulti: boolean }) {
  const accent = isMulti ? 'border-l-violet-400' : 'border-l-indigo-400'

  const examples: string[] = Array.isArray(label.examples)
    ? label.examples.map(e => typeof e === 'string' ? e : JSON.stringify(e))
    : []

  return (
    <li className={`border border-seam border-l-2 ${accent} bg-white p-4`}>
      <div className="font-medium text-ink mb-1">{label.name}</div>
      {label.definition && (
        <p className="text-sm text-stone-600 leading-relaxed mb-3">
          {label.definition}
        </p>
      )}
      {examples.length > 0 && (
        <div>
          <div className="font-mono-editorial text-stone-400 mb-1.5">
            Exemplars · {examples.length}
          </div>
          <ul className="space-y-1.5">
            {examples.slice(0, 3).map((ex, i) => (
              <li key={i} className="text-xs text-stone-600 pl-3 border-l border-stone-200 leading-relaxed">
                {ex}
              </li>
            ))}
            {examples.length > 3 && (
              <li className="font-mono-editorial text-stone-400">
                + {examples.length - 3} more
              </li>
            )}
          </ul>
        </div>
      )}
    </li>
  )
}
