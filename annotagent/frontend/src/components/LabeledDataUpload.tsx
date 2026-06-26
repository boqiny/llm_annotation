import { useEffect, useState } from 'react'
import {
  getExpectedSchema, validateLabeledUpload, autofixLabeledData, commitLabeledData,
  type GoldSchema, type GoldValidation, type GoldAutofix,
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
          {!report.ok && <IssuesList report={report} />}

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
                {phase === 'fixing' ? 'Auto-fixing…' : fixed ? 'Re-run auto-fix' : 'Auto-fix with LLM'}
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

function IssuesList({ report }: { report: GoldValidation['report'] }) {
  const unknownLabels = Object.entries(report.unknown_label_values)
  return (
    <div className="space-y-1.5 text-xs">
      {Object.keys(report.unknown_dimensions).length > 0 && (
        <div>
          <span className="text-stone-500">Unknown dimensions: </span>
          {Object.keys(report.unknown_dimensions).map(d => (
            <span key={d} className="font-mono text-red-700 mr-2">{d}</span>
          ))}
        </div>
      )}
      {unknownLabels.map(([dim, vals]) => (
        <div key={dim}>
          <span className="text-stone-500">Unknown values in </span>
          <span className="font-medium">{dim}</span>:{' '}
          {Object.keys(vals).slice(0, 8).map(v => (
            <span key={v} className="font-mono text-red-700 mr-1.5">{v}</span>
          ))}
        </div>
      ))}
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
