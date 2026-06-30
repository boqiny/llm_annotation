import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { ArrowRight, Download } from 'lucide-react'
import {
  getExpectedSchema, validateLabeledUpload, autofixLabeledData, applyLabeledFix, commitLabeledData,
  addCodebookLabel,
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
  const [previewOpen, setPreviewOpen] = useState(false)

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

  // The cleaned, codebook-aligned rows currently in hand (after any fixes).
  const cleanedItems = fixed?.items ?? validation?.items ?? []
  const exportCleaned = (fmt: 'json' | 'csv') => {
    const rows = cleanedItems.map((it: any) => ({
      content: it.content ?? '', context: it.context ?? '', ...(it.gold_labels || {}),
    }))
    let blob: Blob, ext: string
    if (fmt === 'json') {
      blob = new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' }); ext = 'json'
    } else {
      const cols = Array.from(rows.reduce((s: Set<string>, r: any) => { Object.keys(r).forEach(k => s.add(k)); return s }, new Set<string>()))
      const esc = (x: any) => { const s = Array.isArray(x) ? x.join(' & ') : String(x ?? ''); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s }
      const lines = [cols.join(','), ...rows.map((r: any) => cols.map(c => esc(r[c])).join(','))]
      blob = new Blob([lines.join('\n')], { type: 'text/csv' }); ext = 'csv'
    }
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = (validation?.filename?.replace(/\.[^.]+$/, '') || 'labeled-data') + `.cleaned.${ext}`
    a.click()
    URL.revokeObjectURL(url)
  }

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
            <div className="flex items-center gap-3 shrink-0">
              <button
                onClick={() => setPreviewOpen(true)}
                className="px-2.5 py-1 text-xs font-medium border border-seam bg-white text-stone-700 hover:border-ink hover:text-ink transition"
              >
                Preview file
              </button>
              <span className="font-mono-editorial text-stone-400 text-[11px]">{validation.filename}</span>
            </div>
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
            </div>
          )}

          {cleanedItems.length > 0 && (
            <div className="flex items-center justify-between gap-3 flex-wrap border border-emerald-200 bg-emerald-50/60 px-3 py-2.5">
              <div className="text-xs text-emerald-900">
                <span className="font-medium">Cleaned data ready</span>
                <span className="text-emerald-700"> · {cleanedItems.length} rows, aligned to the codebook</span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button onClick={() => exportCleaned('csv')} disabled={busy}
                  className="px-2.5 py-1 text-xs font-medium border border-emerald-300 bg-white text-emerald-800 hover:bg-emerald-100 disabled:opacity-50">
                  CSV
                </button>
                <button onClick={() => exportCleaned('json')} disabled={busy}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium bg-emerald-700 text-white hover:bg-emerald-800 disabled:opacity-50">
                  <Download className="h-3.5 w-3.5" aria-hidden="true" />
                  Export cleaned data
                </button>
              </div>
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

      {previewOpen && validation && (
        <FilePreviewModal
          validation={validation}
          modifiedItems={fixed?.items}
          onClose={() => setPreviewOpen(false)}
        />
      )}
    </div>
  )
}

function FilePreviewModal({ validation, modifiedItems, onClose }: {
  validation: GoldValidation; modifiedItems?: any[]; onClose: () => void
}) {
  const original: any[] = validation.items || []
  const hasModified = !!modifiedItems && modifiedItems.length > 0
  const [view, setView] = useState<'original' | 'modified'>('original')
  const showModified = view === 'modified' && hasModified
  const items = showModified ? (modifiedItems as any[]) : original

  const cell = (v: any) => Array.isArray(v) ? v.join(' & ') : String(v ?? '')

  // Columns are derived from the ACTIVE view only — the modified data uses the
  // canonical codebook dimension names (e.g. "Topics"), the original uses the
  // file's own columns (e.g. "Topic"); unioning them would show every column
  // empty in the other view.
  const { dims, meta } = useMemo(() => {
    const d = new Set<string>(), m = new Set<string>()
    for (const it of items) {
      for (const [k, v] of Object.entries(it.gold_labels || {})) {
        if (Array.isArray(v) ? v.length : String(v ?? '').trim()) d.add(k)
      }
      for (const k of Object.keys(it.metadata || {})) m.add(k)
    }
    return { dims: [...d], meta: [...m] }
  }, [items])

  const CAP = 1000
  const rows = items.slice(0, CAP)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/40" onClick={onClose}>
      <div className="bg-white border border-seam shadow-xl w-full max-w-6xl max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-seam">
          <div className="min-w-0 flex items-center gap-3">
            {hasModified && (
              <div className="inline-flex border border-seam shrink-0">
                <button onClick={() => setView('original')}
                  className={`px-2.5 py-1 text-xs font-medium ${!showModified ? 'bg-ink text-cream' : 'bg-white text-stone-600 hover:text-ink'}`}>
                  Original file
                </button>
                <button onClick={() => setView('modified')}
                  className={`px-2.5 py-1 text-xs font-medium border-l border-seam ${showModified ? 'bg-amber-600 text-white' : 'bg-white text-stone-600 hover:text-ink'}`}>
                  Modified (your edits)
                </button>
              </div>
            )}
            <div className="text-sm font-medium text-ink truncate">
              {validation.filename}
              <span className="ml-2 font-mono-editorial text-stone-400 text-[11px]">
                {validation.file_type} · {items.length.toLocaleString()} rows{items.length > CAP ? ` (showing first ${CAP})` : ''}
              </span>
            </div>
          </div>
          <button onClick={onClose} className="px-2.5 py-1 text-xs font-medium border border-seam text-stone-600 hover:border-ink hover:text-ink">
            Close ✕
          </button>
        </div>

        {showModified && (
          <div className="px-4 py-2 bg-amber-50 border-b border-amber-200 text-[11px] text-amber-900">
            This is <span className="font-medium">your modified version</span> — the file cleaned by your fixes (not the original upload). Changed cells are highlighted.
          </div>
        )}

        <div className="overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-paper">
              <tr className="font-mono-editorial text-stone-500 border-b border-seam">
                <th className="px-2 py-2 text-left">#</th>
                <th className="px-2 py-2 text-left min-w-[280px]">content</th>
                {dims.map(d => <th key={`d-${d}`} className="px-2 py-2 text-left whitespace-nowrap bg-violet-50/60">{d}</th>)}
                {meta.map(m => <th key={`m-${m}`} className="px-2 py-2 text-left whitespace-nowrap">{m}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-seam">
              {rows.map((it, i) => (
                <tr key={i} className="align-top">
                  <td className="px-2 py-1.5 font-mono text-stone-400">{it.index ?? i + 1}</td>
                  <td className="px-2 py-1.5 text-stone-800 max-w-[420px]"><div className="line-clamp-3">{cell(it.content)}</div></td>
                  {dims.map(d => <td key={`d-${d}`} className="px-2 py-1.5 font-mono text-violet-900 whitespace-nowrap">{cell((it.gold_labels || {})[d])}</td>)}
                  {meta.map(m => <td key={`m-${m}`} className="px-2 py-1.5 text-stone-500 max-w-[200px] truncate" title={cell((it.metadata || {})[m])}>{cell((it.metadata || {})[m])}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
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
  // Per-row overrides: { rowIndex: { dimension: value } }.
  const [itemOverrides, setItemOverrides] = useState<Record<string, Record<string, string>>>({})
  const [applying, setApplying] = useState(false)

  // Mirror the backend's _norm/_stem (gold_align.py) so a singular gold column
  // ("Topic thematic category") matches a plural codebook dim ("…categories");
  // a naive /s\b/ strip leaves "categorie" vs "category" and finds no rows.
  const stem = (t: string) =>
    t.length > 4 && t.endsWith('ies') ? t.slice(0, -3) + 'y'
    : t.length > 3 && t.endsWith('s') && !t.endsWith('ss') ? t.slice(0, -1)
    : t
  const norm = (s: string) =>
    String(s ?? '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().split(/\s+/).filter(Boolean).map(stem).join(' ')
  // Rows whose value for `dim` matches `value` (dim is canonical; item key may differ).
  const rowsFor = (dim: string, value: string) => originalItems.filter(it => {
    const g = it.gold_labels || {}
    for (const [k, val] of Object.entries(g)) {
      if (norm(k) !== norm(dim)) continue
      const vals = Array.isArray(val) ? val : [val]
      if (vals.some(x => norm(String(x)) === norm(value))) return true
    }
    return false
  })
  const setRowOverride = (index: number, dim: string, value: string) =>
    setItemOverrides(p => {
      const row = { ...(p[String(index)] || {}) }
      if (value === '') delete row[dim]; else row[dim] = value
      const next = { ...p, [String(index)]: row }
      if (Object.keys(row).length === 0) delete next[String(index)]
      return next
    })

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

  // Per-value example text comes straight from the report now, so every value
  // (not just the first N) can show "where?".
  const examples = (kind: string, dimension: string, value?: string): string[] => {
    if (kind === 'unknown_dimension') return report.dimension_samples?.[dimension] ?? []
    if (kind === 'unknown_label' && value !== undefined) return report.label_value_samples?.[dimension]?.[value] ?? []
    return []
  }

  const buildSpec = (dm: Record<string, string>, lm: Record<string, Record<string, string>>): GoldFixSpec => ({
    dimension_map: Object.fromEntries(Object.entries(dm).filter(([, v]) => v && v !== DROP)),
    drop_dimensions: Object.entries(dm).filter(([, v]) => v === DROP).map(([k]) => k),
    label_map: Object.fromEntries(Object.entries(lm).map(([d, m]) => [d, Object.fromEntries(Object.entries(m).filter(([, v]) => v))])),
    multi_split: [' & ', ','],
    item_overrides: itemOverrides,
  })

  const apply = async () => {
    setApplying(true)
    try {
      onApply(await applyLabeledFix(projectId, originalItems, buildSpec(dimMap, labelMap)))
    } finally { setApplying(false) }
  }

  // "this value is actually a valid label I forgot": add it to the codebook,
  // then re-validate (it now matches as a label).
  const createLabel = async (dim: string, value: string) => {
    setApplying(true)
    try {
      await addCodebookLabel(projectId, dim, value)
      const nextLabelMap = { ...labelMap, [dim]: { ...(labelMap[dim] || {}), [value]: value } }
      setLabelMap(nextLabelMap)
      onApply(await applyLabeledFix(projectId, originalItems, buildSpec(dimMap, nextLabelMap)))
    } catch (e: any) {
      window.alert('Could not add label: ' + (e?.response?.data?.detail || e?.message || 'unknown error'))
    } finally { setApplying(false) }
  }

  // Dimensions left blank in some rows: offer to add a "-" no-label option (with a
  // definition of when it applies). Blank cells then become an explicit "-".
  const [noLabelDef, setNoLabelDef] = useState<Record<string, string>>({})
  const emptyDims = Object.entries(report.empty_dimensions || {})
    .filter(([, info]) => info.count > 0 && !info.has_no_label)
  const addNoLabel = async (dim: string) => {
    setApplying(true)
    try {
      await addCodebookLabel(projectId, dim, '-', noLabelDef[dim] || 'No label applies to this item.')
      onApply(await applyLabeledFix(projectId, originalItems, buildSpec(dimMap, labelMap)))
    } catch (e: any) {
      window.alert('Could not add option: ' + (e?.response?.data?.detail || e?.message || 'unknown error'))
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
                <div key={v} className="space-y-1">
                  <FixRow from={v} count={cnt} examples={examples('unknown_label', dim, v)}>
                    <select value={labelMap[dim]?.[v] ?? ''} disabled={busy || applying}
                      onChange={e => {
                        if (e.target.value === '__create__') createLabel(dim, v)
                        else setLabelMap(p => ({ ...p, [dim]: { ...(p[dim] || {}), [v]: e.target.value } }))
                      }}
                      className="bg-white border border-seam px-2 py-1 text-xs focus:outline-none focus:border-ink">
                      <option value="">(choose)</option>
                      {(labelsByDim[dim] || []).map(l => <option key={l} value={l}>{l}</option>)}
                      <option value="__create__">＋ add “{v}” as a new codebook label</option>
                      <option value={DROP}>— discard (drop this value) —</option>
                    </select>
                  </FixRow>
                  <PerRowFixer
                    rows={rowsFor(dim, v)} dim={dim}
                    options={labelsByDim[dim] || []}
                    overrides={itemOverrides} onSet={setRowOverride}
                    fallback={labelMap[dim]?.[v] || ''} disabled={busy || applying}
                  />
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {emptyDims.length > 0 && (
        <div className="space-y-2">
          <div className="font-mono-editorial text-[11px] text-stone-400">Dimensions left blank in some rows</div>
          {emptyDims.map(([dim, info]) => (
            <div key={dim} className="border border-seam bg-paper/40 p-2 space-y-1.5">
              <div className="text-xs">
                <span className="font-medium text-stone-700">{dim}</span>
                <span className="text-stone-400"> · {info.count} {info.count === 1 ? 'row has' : 'rows have'} no value</span>
              </div>
              {info.samples.length > 0 && (
                <ul className="text-[11px] text-stone-500 space-y-0.5">
                  {info.samples.slice(0, 2).map((s, i) => <li key={i} className="truncate">· {s.slice(0, 80)}</li>)}
                </ul>
              )}
              <div className="flex items-center gap-2 flex-wrap">
                <input
                  value={noLabelDef[dim] ?? ''} disabled={busy || applying}
                  onChange={e => setNoLabelDef(p => ({ ...p, [dim]: e.target.value }))}
                  placeholder="When does “no label” apply here? (definition)"
                  className="flex-1 min-w-[220px] bg-white border border-seam px-2 py-1 text-xs focus:outline-none focus:border-ink"
                />
                <button onClick={() => addNoLabel(dim)} disabled={busy || applying}
                  className="px-2.5 py-1 text-xs font-medium border border-ink bg-white text-ink hover:bg-paper disabled:opacity-50 whitespace-nowrap">
                  ＋ add “-” option
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {unknownDims.length === 0 && unknownLabels.length === 0 && emptyDims.length === 0 && (
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

/* Per-row override editor: fix individual rows of one mismatch differently from
 * the apply-all mapping. Collapsed by default to keep the panel compact. */
function PerRowFixer({ rows, dim, options, overrides, onSet, fallback, disabled }: {
  rows: any[]; dim: string; options: string[]
  overrides: Record<string, Record<string, string>>
  onSet: (index: number, dim: string, value: string) => void
  fallback: string; disabled: boolean
}) {
  const [open, setOpen] = useState(false)
  if (rows.length === 0) return null
  const overriddenCount = rows.filter(r => overrides[String(r.index)]?.[dim] !== undefined).length
  return (
    <div className="ml-1 text-xs">
      <button type="button" onClick={() => setOpen(o => !o)} className="text-stone-400 underline">
        {open ? 'hide rows' : `fix individual rows (${rows.length})`}
        {overriddenCount > 0 && <span className="text-indigo-600"> · {overriddenCount} set</span>}
      </button>
      {open && (
        <ul className="mt-1 space-y-1 border-l border-seam pl-2">
          {rows.slice(0, 50).map(r => {
            const cur = overrides[String(r.index)]?.[dim]
            const content = String(r.content || '').slice(0, 70)
            return (
              <li key={r.index} className="flex items-center gap-2 flex-wrap">
                <span className="text-stone-400 font-mono">#{r.index}</span>
                <span className="text-stone-600 truncate max-w-[280px]">{content}</span>
                <select value={cur ?? ''} disabled={disabled}
                  onChange={e => onSet(r.index, dim, e.target.value)}
                  className="bg-white border border-seam px-1.5 py-0.5 text-[11px] focus:outline-none focus:border-ink">
                  <option value="">
                    {fallback === DROP ? 'discard (default)' : fallback ? `use “${fallback}”` : '(use mapping)'}
                  </option>
                  {options.map(l => <option key={l} value={l}>{l}</option>)}
                </select>
              </li>
            )
          })}
          {rows.length > 50 && <li className="text-stone-400">+ {rows.length - 50} more rows…</li>}
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

