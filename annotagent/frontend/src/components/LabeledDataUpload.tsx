import { useEffect, useState, type ReactNode } from 'react'
import { ArrowRight } from 'lucide-react'
import {
  getExpectedSchema, validateLabeledUpload, autofixLabeledData, applyLabeledFix, commitLabeledData,
  type GoldSchema, type GoldValidation, type GoldAutofix, type GoldReport, type GoldFixSpec,
} from '../lib/api'

type Phase = 'idle' | 'validating' | 'review' | 'fixing' | 'committing'

export default function LabeledDataUpload({
  projectId, onLoaded,
}: {
  projectId: number
  onLoaded: () => void | Promise<void>
}) {
  const [schema, setSchema] = useState<GoldSchema | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [validation, setValidation] = useState<GoldValidation | null>(null)
  const [fixed, setFixed] = useState<GoldAutofix | null>(null)
  const [error, setError] = useState('')

  useEffect(() => { getExpectedSchema(projectId).then(setSchema).catch(() => setSchema(null)) }, [projectId])

  const reset = () => { setPhase('idle'); setValidation(null); setFixed(null); setError('') }

  const commit = async (v: GoldValidation, items: any[]) => {
    setPhase('committing'); setError('')
    try {
      await commitLabeledData(projectId, {
        name: v.filename, is_gold: v.is_gold, file_type: v.file_type, items,
      })
      await onLoaded()
      reset()
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Commit failed')
      setPhase('review')
    }
  }

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; e.target.value = ''
    if (!file) return
    setPhase('validating'); setError(''); setFixed(null); setValidation(null)
    try {
      const v = await validateLabeledUpload(projectId, file, true)
      setValidation(v); setSchema(v.schema)
      if (v.report.ok) { await commit(v, v.items); return }   // matches → load straight away
      setPhase('review')
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Validation failed')
      setPhase('idle')
    }
  }

  const runAutofix = async () => {
    if (!validation) return
    setPhase('fixing'); setError('')
    try {
      const result = await autofixLabeledData(projectId, validation.items)
      setFixed(result); setPhase('review')
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Auto-fix failed')
      setPhase('review')
    }
  }

  const onManualApply = (res: { items: any[]; report: GoldReport }) => {
    if (!validation) return
    const before = (fixed?.report ?? validation.report).n_errors_shown
    setFixed({
      items: res.items,
      trace: [{ round: 'manual', errors_before: before, errors_after: res.report.n_errors_shown }],
      report: res.report,
    })
  }

  const busy = phase === 'validating' || phase === 'fixing' || phase === 'committing'
  const report = fixed?.report ?? validation?.report ?? null

  return (
    <div className="space-y-3">
      {schema && <SchemaView schema={schema} />}

      {/* uploader */}
      <label className={`block border border-dashed border-stone-300 bg-white px-4 py-6 text-center cursor-pointer hover:border-stone-400 ${busy ? 'opacity-60 pointer-events-none' : ''}`}>
        <input type="file" accept=".csv,.json" className="hidden" onChange={onFile} disabled={busy} />
        <div className="text-sm font-medium text-stone-700">
          {phase === 'validating' ? 'Checking against the codebook…'
            : phase === 'committing' ? 'Loading…'
            : 'Upload labeled data (CSV / JSON)'}
        </div>
        <div className="text-xs text-stone-500 mt-1">
          We validate it against the codebook before loading. Mismatches can be auto-fixed.
        </div>
      </label>

      {error && <div className="border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

      {/* review: validation failed and/or auto-fix result */}
      {phase !== 'idle' && phase !== 'validating' && report && validation && (
        <div className="border border-seam bg-paper/60 p-4 space-y-3">
          <div className="flex items-baseline justify-between gap-3">
            <div className="font-medium text-sm">
              {report.ok
                ? <span className="text-emerald-700">Matches the codebook · {report.n_items} items</span>
                : <span className="text-red-700">{report.n_error_items} of {report.n_items} rows don’t match the codebook</span>}
            </div>
            <span className="font-mono-editorial text-stone-400 text-[11px]">{validation.filename}</span>
          </div>

          <ReportSummary report={report} />

          {/* interactive manual fixer — map each mismatch to the codebook yourself */}
          {!report.ok && schema && (
            <MismatchFixer
              projectId={projectId}
              schema={schema}
              report={report}
              originalItems={validation.items}
              busy={busy}
              onApply={onManualApply}
            />
          )}

          {/* auto-fix output */}
          {fixed && (
            <div className="space-y-2 border-t border-seam pt-3">
              <TraceView trace={fixed.trace} />
              <BeforeAfter original={validation.items} fixedItems={fixed.items} />
            </div>
          )}

          <div className="flex flex-wrap gap-2 pt-1">
            {!report.ok && (
              <button onClick={runAutofix} disabled={busy}
                className="px-3 py-1.5 text-sm font-medium border border-violet-300 bg-violet-50 text-violet-800 hover:bg-violet-100 disabled:opacity-50">
                {phase === 'fixing' ? 'Auto-fixing…' : fixed ? 'Re-run auto-fix' : 'Or auto-fix with LLM'}
              </button>
            )}
            {fixed && (
              <button onClick={() => commit(validation, fixed.items)} disabled={busy}
                className="px-3 py-1.5 text-sm font-medium border border-ink bg-ink text-cream hover:opacity-90 disabled:opacity-50">
                {phase === 'committing' ? 'Loading…' : report.ok ? 'Apply & load →' : 'Apply & load anyway →'}
              </button>
            )}
            {report.ok && !fixed && (
              <button onClick={() => commit(validation, validation.items)} disabled={busy}
                className="px-3 py-1.5 text-sm font-medium border border-ink bg-ink text-cream hover:opacity-90 disabled:opacity-50">
                Load →
              </button>
            )}
            <button onClick={reset} disabled={busy}
              className="px-3 py-1.5 text-sm font-medium border border-seam text-stone-600 hover:bg-paper disabled:opacity-50">
              Discard
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function SchemaView({ schema }: { schema: GoldSchema }) {
  return (
    <details className="border border-violet-200 bg-violet-50/70 px-4 py-3 text-sm" open>
      <summary className="cursor-pointer font-medium text-violet-950">
        Expected schema · {schema.dimensions.length} dimensions
      </summary>
      <div className="mt-2 space-y-2">
        {schema.dimensions.map(d => (
          <div key={d.name} className="text-xs">
            <span className="font-medium text-violet-950">{d.name}</span>
            <span className="ml-2 font-mono-editorial text-violet-700/80">{d.type.replace('_', '-')}</span>
            <div className="mt-1 flex flex-wrap gap-1">
              {d.labels.map(l => (
                <span key={l} className="px-1.5 py-0.5 bg-white border border-violet-200 text-violet-900 font-mono text-[11px]">{l}</span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </details>
  )
}

const KIND_LABEL: Record<string, string> = {
  missing_content: 'rows missing text',
  unknown_dimension: 'dimensions not in codebook (dropped)',
  unknown_label: 'label values not in the codebook',
  cardinality: 'single-label rows with multiple values',
  unmatched_row: 'rows matching no codebook dimension',
}

function ReportSummary({ report }: { report: GoldValidation['report'] }) {
  const rows = Object.entries(report.summary).filter(([, n]) => n > 0)
  if (rows.length === 0) return null
  return (
    <ul className="text-xs text-stone-600 space-y-0.5">
      {rows.map(([kind, n]) => (
        <li key={kind}>
          <span className="font-mono text-stone-800">{n}</span>{' '}
          {KIND_LABEL[kind] || kind.replace('_', ' ')}
        </li>
      ))}
    </ul>
  )
}

const DROP = '__drop__'

const _norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
/** Tokens, de-pluralised so "Topic" matches "Topics" (drop trailing 's' on real words). */
function _tok(s: string): string[] {
  return _norm(s).split(' ').filter(Boolean).map(t => (t.length > 2 ? t.replace(/s$/, '') : t))
}
/** Best-guess mapping by Jaccard token overlap + a starts-with bonus, so plurals
 *  and typos win over longer names that merely share a word:
 *  "Topic" -> "Topics" (not "Topic Thematic Categories"), "No" -> "No, it's not a confession",
 *  "Initmacy of self-disclosure" -> "Intimacy Of Self-Disclosure". Returns '' when unsure. */
function bestMatch(target: string, options: string[]): string {
  const A = new Set(_tok(target))
  const tn = _norm(target)
  let best = '', score = 0
  for (const o of options) {
    const B = _tok(o)
    const inter = B.filter(t => A.has(t)).length
    const union = new Set([...A, ...B]).size || 1
    let s = inter / union
    if (_norm(o).startsWith(tn) || tn.startsWith(_norm(o))) s += 0.5
    if (s > score) { score = s; best = o }
  }
  return score >= 0.3 ? best : ''
}

/** Interactive mismatch fixer: one dropdown per unknown dimension / label value,
 *  with prefilled suggestions and an inline "where?" example peek. Builds the same
 *  transform spec the LLM auto-fix produces, applied deterministically server-side. */
function MismatchFixer({ projectId, schema, report, originalItems, busy, onApply }: {
  projectId: number
  schema: GoldSchema
  report: GoldReport
  originalItems: any[]
  busy: boolean
  onApply: (r: { items: any[]; report: GoldReport }) => void
}) {
  const dimNames = schema.dimensions.map(d => d.name)
  const labelsByDim: Record<string, string[]> = Object.fromEntries(schema.dimensions.map(d => [d.name, d.labels]))
  const [dimMap, setDimMap] = useState<Record<string, string>>({})
  const [labelMap, setLabelMap] = useState<Record<string, Record<string, string>>>({})
  const [applying, setApplying] = useState(false)

  const unknownDims = Object.keys(report.unknown_dimensions || {})
  const unknownLabels = Object.entries(report.unknown_label_values || {})

  // Prefill suggestions for any NEWLY-revealed mismatch without clobbering edits.
  useEffect(() => {
    setDimMap(prev => {
      const next = { ...prev }
      for (const u of unknownDims) if (!(u in next)) next[u] = bestMatch(u, dimNames)
      return next
    })
    setLabelMap(prev => {
      const next: Record<string, Record<string, string>> = { ...prev }
      for (const [dim, vals] of unknownLabels) {
        next[dim] = { ...(next[dim] || {}) }
        for (const v of Object.keys(vals)) if (!(v in next[dim])) next[dim][v] = bestMatch(v, labelsByDim[dim] || [])
      }
      return next
    })
  }, [report])  // eslint-disable-line react-hooks/exhaustive-deps

  const contentByIndex = new Map<number, string>(originalItems.map(it => [it.index, String(it.content || '')]))
  const examples = (kind: string, dimension: string, value?: string): string[] =>
    (report.issues || [])
      .filter(i => i.kind === kind && i.dimension === dimension && (value === undefined || String(i.value) === value))
      .slice(0, 3)
      .map(i => contentByIndex.get(i.row) || '')
      .filter(Boolean)

  const apply = async () => {
    setApplying(true)
    try {
      const spec: GoldFixSpec = {
        dimension_map: Object.fromEntries(Object.entries(dimMap).filter(([, v]) => v && v !== DROP)),
        drop_dimensions: Object.entries(dimMap).filter(([, v]) => v === DROP).map(([k]) => k),
        label_map: Object.fromEntries(
          Object.entries(labelMap).map(([d, m]) => [d, Object.fromEntries(Object.entries(m).filter(([, v]) => v))]),
        ),
        multi_split: [' & ', ','],
      }
      onApply(await applyLabeledFix(projectId, originalItems, spec))
    } finally { setApplying(false) }
  }

  return (
    <div className="border border-seam bg-white p-3 space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <span className="text-xs font-medium text-stone-700">Fix mismatches manually</span>
        <span className="inline-flex items-center gap-1.5 text-[11px]">
          <span className="font-mono text-red-700 bg-red-50 border border-red-200 px-1.5 py-0.5">your value</span>
          <ArrowRight className="h-3 w-3 text-stone-400" aria-hidden="true" />
          <span className="font-mono text-stone-700 bg-paper border border-seam px-1.5 py-0.5">codebook</span>
        </span>
      </div>

      {unknownDims.length > 0 && (
        <div className="space-y-1.5">
          <div className="font-mono-editorial text-[11px] text-stone-400">Dimensions not in the codebook</div>
          {unknownDims.map(u => (
            <FixRow key={u} from={u} count={report.unknown_dimensions[u]} examples={examples('unknown_dimension', u)}>
              <select value={dimMap[u] ?? ''} disabled={busy || applying}
                onChange={e => setDimMap(p => ({ ...p, [u]: e.target.value }))}
                className="bg-white border border-seam px-2 py-1 text-xs focus:outline-none focus:border-ink">
                <option value="">(choose)</option>
                {dimNames.map(d => <option key={d} value={d}>{d}</option>)}
                <option value={DROP}>— drop —</option>
              </select>
            </FixRow>
          ))}
        </div>
      )}

      {unknownLabels.length > 0 && (
        <div className="space-y-2">
          <div className="font-mono-editorial text-[11px] text-stone-400">Label values not in the codebook</div>
          {unknownLabels.map(([dim, vals]) => (
            <div key={dim} className="space-y-1">
              <div className="text-xs font-medium text-stone-700">{dim}</div>
              {Object.entries(vals).map(([v, cnt]) => (
                <FixRow key={v} from={v} count={cnt} examples={examples('unknown_label', dim, v)}>
                  <select value={labelMap[dim]?.[v] ?? ''} disabled={busy || applying}
                    onChange={e => setLabelMap(p => ({ ...p, [dim]: { ...(p[dim] || {}), [v]: e.target.value } }))}
                    className="bg-white border border-seam px-2 py-1 text-xs focus:outline-none focus:border-ink">
                    <option value="">(choose)</option>
                    {(labelsByDim[dim] || []).map(l => <option key={l} value={l}>{l}</option>)}
                  </select>
                </FixRow>
              ))}
            </div>
          ))}
        </div>
      )}

      {unknownDims.length === 0 && unknownLabels.length === 0 && (
        <div className="text-xs text-stone-500">No name-level mismatches left to map. Apply to normalize remaining values, or auto-fix with the LLM.</div>
      )}

      <button onClick={apply} disabled={busy || applying}
        className="px-3 py-1.5 text-sm font-medium border border-ink bg-white text-ink hover:bg-paper disabled:opacity-50">
        {applying ? 'Applying…' : 'Apply fixes'}
      </button>
    </div>
  )
}

function FixRow({ from, count, examples, children }: {
  from: string; count: number; examples: string[]; children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="text-xs">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono text-red-700 break-words">{from || '(empty)'}</span>
        <span className="text-stone-400">{count} {count === 1 ? 'row' : 'rows'}</span>
        <ArrowRight className="h-3 w-3 text-stone-400 shrink-0" aria-hidden="true" />
        {children}
        {examples.length > 0 && (
          <button type="button" onClick={() => setOpen(o => !o)} className="text-stone-400 underline">
            {open ? 'hide' : 'where?'}
          </button>
        )}
      </div>
      {open && (
        <ul className="mt-1 ml-1 space-y-0.5 text-stone-500">
          {examples.map((ex, i) => <li key={i} className="truncate">· {ex.slice(0, 90)}</li>)}
        </ul>
      )}
    </div>
  )
}

function TraceView({ trace }: { trace: any[] }) {
  if (!trace?.length) return null
  return (
    <div className="text-xs text-stone-600">
      <span className="font-mono-editorial text-stone-400">Auto-fix · </span>
      {trace.map((t, i) => (
        <span key={i} className="mr-3">
          {t.error
            ? <span className="text-red-600">round {t.round}: {t.error}</span>
            : <span>round {t.round}: {t.errors_before} → {t.errors_after} errors</span>}
        </span>
      ))}
    </div>
  )
}

function BeforeAfter({ original, fixedItems }: { original: any[]; fixedItems: any[] }) {
  const byIndex = new Map(fixedItems.map((it, i) => [it.index ?? i, it]))
  const sample = original.slice(0, 6)
  return (
    <div className="space-y-1.5">
      <div className="font-mono-editorial text-stone-400 text-[11px]">Preview · first {sample.length} rows</div>
      <div className="space-y-2">
        {sample.map((o, i) => {
          const f = byIndex.get(o.index ?? i)
          return (
            <div key={i} className="text-xs border border-seam bg-white px-2.5 py-1.5">
              <div className="truncate text-stone-700">{String(o.content || '').slice(0, 80) || <span className="text-stone-400">(no content)</span>}</div>
              <div className="mt-1 grid grid-cols-1 md:grid-cols-2 gap-1">
                <div className="text-stone-400 font-mono break-words">before: {JSON.stringify(o.gold_labels || {})}</div>
                <div className="text-emerald-700 font-mono break-words">after: {JSON.stringify(f?.gold_labels || {})}</div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
