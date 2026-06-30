import { useEffect, useMemo, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { generateStructureSchema, type StructureSchema } from '../lib/api'

/* Renders a codebook's prediction-structure tree from an LLM-generated schema:
 *   root -> themes (with citation) -> their levels -> [converge] -> output chain.
 * The LLM infers the roles (themes/levels/outputs/citations) for ANY codebook; the
 * layout here is fixed, so the shape is consistent. Cached per codebook. */

const ROOT = { x: 0, w: 150, h: 54 }
const THEME = { x: 230, w: 210, h: 54 }
const LEVEL = { x: 510, w: 158, h: 46, gap: 10 }
const OUT = { x: 740, w: 172, h: 50, gap: 18 }
const GROUP_GAP = 30
const BUS = LEVEL.x + LEVEL.w + 26

export default function StructureDiagram({ projectId, codebookId }: { projectId: number; codebookId: number }) {
  const [schema, setSchema] = useState<StructureSchema | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const cacheKey = `annotagent.structure.${projectId}.${codebookId}`

  const load = async (force = false) => {
    if (!force) {
      try {
        const c = localStorage.getItem(cacheKey)
        if (c) {
          const parsed = JSON.parse(c)
          // Ignore stale entries from an older schema format (must have `themes`).
          if (parsed && Array.isArray(parsed.themes)) { setSchema(parsed); return }
          localStorage.removeItem(cacheKey)
        }
      } catch {}
    }
    setLoading(true); setError('')
    try {
      const s = await generateStructureSchema(projectId, codebookId)
      setSchema(s)
      try { localStorage.setItem(cacheKey, JSON.stringify(s)) } catch {}
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Could not generate the diagram')
    } finally { setLoading(false) }
  }
  useEffect(() => { setSchema(null); load() }, [projectId, codebookId])  // eslint-disable-line react-hooks/exhaustive-deps

  if (loading && !schema) {
    return <div className="text-xs text-stone-500 py-6 text-center font-mono-editorial">Predicting structure…</div>
  }
  if (error && !schema) {
    return (
      <div className="text-xs text-stone-600 py-4 text-center">
        {error} <button onClick={() => load(true)} className="ml-2 underline hover:text-ink">retry</button>
      </div>
    )
  }
  if (!schema || schema.themes.length === 0) return null

  return (
    <div className="space-y-2">
      <Diagram schema={schema} />
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-4 text-xs text-stone-600">
          <Swatch cls="bg-violet-100 border-violet-300" label="Theme" />
          <Swatch cls="bg-emerald-50 border-emerald-200" label="Level" />
          <Swatch cls="bg-stone-100 border-stone-300" label="Topics / categories" />
        </div>
        <button onClick={() => load(true)} disabled={loading}
                className="inline-flex items-center gap-1.5 text-[11px] text-stone-500 hover:text-ink disabled:opacity-50">
          <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
          {loading ? 'regenerating…' : 'regenerate'}
        </button>
      </div>
    </div>
  )
}

function Diagram({ schema }: { schema: StructureSchema }) {
  const L = useMemo(() => {
    let cursor = 0
    const themes = schema.themes.map(t => {
      const levelYs = t.levels.map((_, i) => cursor + i * (LEVEL.h + LEVEL.gap))
      const groupH = t.levels.length
        ? t.levels.length * LEVEL.h + (t.levels.length - 1) * LEVEL.gap
        : THEME.h
      const centerY = cursor + groupH / 2
      cursor += groupH + GROUP_GAP
      return { ...t, levelYs, centerY }
    })
    const totalH = Math.max(cursor - GROUP_GAP, 80)
    // Only themes that FEED the outputs (feeds !== false) connect to the convergence
    // bracket; an independent theme like Temporality shows its levels but no arrow.
    const feedCenters = themes.filter(t => t.feeds !== false).flatMap(t => t.levelYs.map(y => y + LEVEL.h / 2))
    const busTop = feedCenters.length ? Math.min(...feedCenters) : totalH / 2
    const busBot = feedCenters.length ? Math.max(...feedCenters) : totalH / 2
    const outs = schema.outputs
    const outBlockH = outs.length * OUT.h + Math.max(0, outs.length - 1) * OUT.gap
    const outTop = totalH / 2 - outBlockH / 2
    const outYs = outs.map((_, i) => outTop + i * (OUT.h + OUT.gap))
    const W = outs.length ? OUT.x + OUT.w : LEVEL.x + LEVEL.w
    return { themes, totalH, busTop, busBot, outYs, W }
  }, [schema])

  const { themes, totalH, busTop, busBot, outYs, W } = L
  const rootY = totalH / 2
  const hasRoot = !!schema.root
  const link = (x1: number, y1: number, x2: number, y2: number) => {
    const dx = Math.max(22, (x2 - x1) / 2)
    return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`
  }

  return (
    <div className="overflow-x-auto">
      <div className="relative" style={{ width: W, height: totalH, minWidth: W }}>
        <svg width={W} height={totalH} className="absolute inset-0" style={{ pointerEvents: 'none' }}>
          <defs>
            <marker id="sd-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="#9ca3af" />
            </marker>
          </defs>
          <g fill="none" stroke="#9ca3af" strokeWidth="1.5">
            {hasRoot && themes.map((t, i) => (
              <path key={`r${i}`} d={link(ROOT.w, rootY, THEME.x, t.centerY)} markerEnd="url(#sd-arrow)" />
            ))}
            {themes.map((t, ti) => t.levelYs.map((y, li) => (
              <path key={`t${ti}-${li}`} d={link(THEME.x + THEME.w, t.centerY, LEVEL.x, y + LEVEL.h / 2)}
                    markerEnd="url(#sd-arrow)" />
            )))}
            {themes.map((t, ti) => t.feeds === false ? null : t.levelYs.map((y, li) => (
              <path key={`b${ti}-${li}`} d={`M ${LEVEL.x + LEVEL.w} ${y + LEVEL.h / 2} L ${BUS} ${y + LEVEL.h / 2}`} />
            )))}
            {schema.outputs.length > 0 && (
              <>
                <path d={`M ${BUS} ${busTop} L ${BUS} ${busBot}`} />
                <path d={link(BUS, totalH / 2, OUT.x, outYs[0] + OUT.h / 2)} markerEnd="url(#sd-arrow)" />
                {schema.outputs.slice(1).map((_, i) => (
                  <path key={`o${i}`}
                        d={`M ${OUT.x + OUT.w / 2} ${outYs[i] + OUT.h} L ${OUT.x + OUT.w / 2} ${outYs[i + 1]}`}
                        markerEnd="url(#sd-arrow)" />
                ))}
              </>
            )}
          </g>
        </svg>

        {hasRoot && (
          <Box x={ROOT.x} y={rootY - ROOT.h / 2} w={ROOT.w} h={ROOT.h} cls="bg-stone-100 border-stone-300 text-stone-800"
               title={schema.root!.label} sub={schema.root!.sublabel} bold />
        )}
        {themes.map((t, ti) => (
          <div key={ti}>
            <Box x={THEME.x} y={t.centerY - THEME.h / 2} w={THEME.w} h={THEME.h}
                 cls="bg-violet-100 border-violet-300 text-violet-950" title={t.name} sub={t.citation} bold />
            {t.levelYs.map((y, li) => (
              <Box key={li} x={LEVEL.x} y={y} w={LEVEL.w} h={LEVEL.h}
                   cls="bg-emerald-50 border-emerald-200 text-emerald-900"
                   title={t.levels[li].label} sub={t.levels[li].sublabel} />
            ))}
          </div>
        ))}
        {schema.outputs.map((o, i) => (
          <Box key={i} x={OUT.x} y={outYs[i]} w={OUT.w} h={OUT.h}
               cls="bg-stone-100 border-stone-300 text-stone-800" title={o.name} sub={o.sublabel} bold />
        ))}
      </div>
    </div>
  )
}

function Box({ x, y, w, h, cls, title, sub, bold }: {
  x: number; y: number; w: number; h: number; cls: string; title: string; sub?: string; bold?: boolean
}) {
  return (
    <div className={`absolute rounded-lg border flex flex-col items-center justify-center text-center px-2 leading-tight ${cls}`}
         style={{ left: x, top: y, width: w, height: h }}>
      <div className={`text-[13px] truncate max-w-full ${bold ? 'font-semibold' : ''}`}>{title}</div>
      {sub ? <div className="text-[11px] font-medium opacity-75 mt-0.5 truncate max-w-full">{sub}</div> : null}
    </div>
  )
}

function Swatch({ cls, label }: { cls: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block w-3.5 h-3.5 rounded border ${cls}`} />
      {label}
    </span>
  )
}
