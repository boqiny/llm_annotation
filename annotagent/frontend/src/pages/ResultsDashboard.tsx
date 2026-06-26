import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { getJob, getMetrics, getConfusionMatrix, exportResults, editResult, listCodebooks } from '../lib/api'
import { formatTokens, formatPercent } from '../lib/utils'
import type { Job, DimensionMetrics } from '../types'

type OutputRow = Record<string, string | number | null | undefined>

export default function ResultsDashboard() {
  const { id, jobId } = useParams<{ id: string; jobId: string }>()
  const projectId = Number(id)
  const jid = Number(jobId)

  const [job, setJob] = useState<Job | null>(null)
  const [metrics, setMetrics] = useState<DimensionMetrics[]>([])
  const [confusionDim, setConfusionDim] = useState<string>('')
  const [confusionData, setConfusionData] = useState<{ classes: string[]; matrix: Record<string, Record<string, number>> } | null>(null)
  const [resultsOpen, setResultsOpen] = useState(true)
  const [outputRows, setOutputRows] = useState<OutputRow[]>([])
  const [labelsByDim, setLabelsByDim] = useState<Record<string, string[]>>({})
  const [savingCell, setSavingCell] = useState<string>('')

  useEffect(() => {
    getJob(projectId, jid).then(setJob)
    getMetrics(projectId, jid).then(m => {
      setMetrics(m)
      if (m.length > 0) setConfusionDim(m[0].dimension)
    })
    exportResults(projectId, jid, 'json').then(resp => setOutputRows(Array.isArray(resp.data) ? resp.data : []))
    listCodebooks(projectId).then(cbs => {
      const cb = cbs[cbs.length - 1]
      const map: Record<string, string[]> = {}
      for (const d of cb?.dimensions ?? []) map[d.name] = d.labels.map(l => l.name)
      setLabelsByDim(map)
    }).catch(() => setLabelsByDim({}))
  }, [projectId, jid])

  const onEditCell = async (rowIdx: number, item_id: number, dimension: string, label: string) => {
    const cellKey = `${item_id}:${dimension}`
    setSavingCell(cellKey)
    setOutputRows(prev => prev.map((r, i) => (i === rowIdx ? { ...r, [dimension]: label } : r)))
    try {
      await editResult(projectId, jid, item_id, dimension, label)
    } catch (e: any) {
      window.alert('Could not save edit: ' + (e?.response?.data?.detail || e?.message || 'unknown error'))
    } finally {
      setSavingCell('')
    }
  }

  useEffect(() => {
    if (confusionDim) {
      getConfusionMatrix(projectId, jid, confusionDim).then(setConfusionData)
    }
  }, [confusionDim, projectId, jid])

  const handleExport = async (format: 'csv' | 'json' | 'xlsx') => {
    const resp = await exportResults(projectId, jid, format)
    const blob = format === 'json'
      ? new Blob([JSON.stringify(resp.data, null, 2)], { type: 'application/json' })
      : resp.data  // csv + xlsx come back as blobs
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `job_${jid}_results.${format}`
    a.click()
    URL.revokeObjectURL(url)
  }

  const chartData = metrics.map(m => ({
    dimension: m.dimension.length > 15 ? m.dimension.substring(0, 15) + '...' : m.dimension,
    accuracy: +(m.metrics.accuracy * 100).toFixed(1),
    macro_f1: +(m.metrics.macro_f1 * 100).toFixed(1),
  }))
  const outputColumns = outputRows.length > 0
    ? Object.keys(outputRows[0]).filter(k => k !== 'item_id' && k !== 'content')
    : []
  const previewRows = outputRows.slice(0, 200)

  return (
    <div className="space-y-12">
      {/* Masthead */}
      <header className="border-b border-seam pb-6 flex items-end justify-between gap-6 flex-wrap">
        <div>
          <div className="font-mono-editorial text-stone-500 mb-2">
            Results · Job № {jid.toString().padStart(4, '0')}
          </div>
          <h1 className="text-4xl font-medium tracking-tight">Per-dimension outcomes.</h1>
        </div>
        <div className="flex gap-2">
          <Link
            to={`/projects/${projectId}/pipeline`}
            className="px-4 py-2 text-sm font-medium text-ink border border-ink bg-white hover:bg-paper transition-colors"
          >
            Back to annotation
          </Link>
          <button onClick={() => handleExport('csv')} className="px-4 py-2 text-sm font-medium text-ink border border-seam hover:border-ink transition-colors">
            Export · CSV
          </button>
          <button onClick={() => handleExport('xlsx')} className="px-4 py-2 text-sm font-medium text-ink border border-seam hover:border-ink transition-colors">
            Export · XLSX
          </button>
          <button onClick={() => handleExport('json')} className="px-4 py-2 text-sm font-medium text-ink border border-seam hover:border-ink transition-colors">
            Export · JSON
          </button>
        </div>
      </header>

      {/* Summary row — editorial stat blocks, no drop shadows */}
      <section className="grid grid-cols-2 md:grid-cols-5 border-y border-seam divide-x divide-seam">
        <StatBlock label="Items" value={(job?.completed_items ?? 0).toLocaleString()} />
        <StatBlock
          label="Overall accuracy"
          value={metrics.length > 0 ? formatPercent(metrics.reduce((s, m) => s + m.metrics.accuracy, 0) / metrics.length) : '—'}
        />
        <StatBlock label="Tokens" value={formatTokens(job?.total_tokens ?? 0)} />
        <StatBlock
          label="Status"
          value={job?.status ?? '—'}
          tone={job?.status === 'completed' ? 'text-emerald-700' : 'text-stone-600'}
        />
      </section>
      <p className="-mt-8 text-xs text-stone-500">
        Token counts are persisted from actual model usage for this job. Input/output token split is not stored separately yet.
      </p>

      <section className="border border-seam bg-white">
        <button
          type="button"
          onClick={() => setResultsOpen(v => !v)}
          className="w-full px-4 py-3 flex items-center justify-between gap-4 text-left hover:bg-paper/50"
        >
          <div>
            <div className="font-mono-editorial text-stone-500">Annotated results</div>
            <p className="mt-1 text-xs text-stone-500">
              Predicted labels — click any to correct it; edits save automatically and are included in CSV/XLSX exports. Showing {previewRows.length.toLocaleString()} of {outputRows.length.toLocaleString()} rows.
            </p>
          </div>
          <span className="font-mono-editorial text-violet-700">{resultsOpen ? 'Hide' : 'Show'}</span>
        </button>
        {resultsOpen && (
          <div className="border-t border-seam max-h-[460px] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-white border-b border-seam">
                <tr>
                  <th className="px-3 py-3 text-left font-mono-editorial text-stone-500">Item</th>
                  <th className="px-3 py-3 text-left font-mono-editorial text-stone-500 min-w-[320px]">Sentence</th>
                  {outputColumns.map(col => (
                    <th key={col} className="px-3 py-3 text-left font-mono-editorial text-stone-500 min-w-[160px]">{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-seam">
                {previewRows.map((row, idx) => (
                  <tr key={`${row.item_id ?? idx}`} className="hover:bg-paper/40">
                    <td className="px-3 py-3 font-mono text-xs text-stone-500">{String(row.item_id ?? idx + 1).padStart(4, '0')}</td>
                    <td className="px-3 py-3 text-stone-700 max-w-[520px]">
                      <div className="line-clamp-3">{String(row.content ?? '')}</div>
                    </td>
                    {outputColumns.map(col => {
                      const val = String(row[col] ?? '')
                      const opts = labelsByDim[col] ?? []
                      const options = (!val || opts.includes(val)) ? opts : [val, ...opts]
                      const cellKey = `${row.item_id}:${col}`
                      return (
                        <td key={col} className="px-3 py-2">
                          {options.length > 0 ? (
                            <select
                              value={val}
                              disabled={savingCell === cellKey}
                              onChange={e => onEditCell(idx, Number(row.item_id), col, e.target.value)}
                              className="bg-paper border border-seam text-stone-700 text-xs px-1.5 py-1 max-w-[200px] focus:outline-none focus:border-ink hover:border-stone-400 disabled:opacity-50"
                            >
                              {!val && <option value="">—</option>}
                              {options.map(o => <option key={o} value={o}>{o}</option>)}
                            </select>
                          ) : (
                            <span className="px-2 py-0.5 bg-paper border border-seam text-stone-700 text-xs">{val || '—'}</span>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
                {previewRows.length === 0 && (
                  <tr>
                    <td colSpan={Math.max(2, outputColumns.length + 2)} className="px-4 py-12 text-center text-stone-400 font-mono-editorial">
                      No stored predictions found for this job yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Accuracy Chart */}
      {chartData.length > 0 && (
        <section>
          <div className="font-mono-editorial text-stone-500 mb-4">Accuracy per dimension</div>
          <div className="border border-seam bg-white p-4">
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E4E4E0" />
                <XAxis dataKey="dimension" fontSize={11} stroke="#8a8886" />
                <YAxis domain={[0, 100]} fontSize={11} stroke="#8a8886" />
                <Tooltip contentStyle={{ border: '1px solid #E4E4E0', borderRadius: 0, fontSize: 12 }} />
                <Bar dataKey="accuracy" fill="#0b0b0a" name="Accuracy %" />
                <Bar dataKey="macro_f1" fill="#8a8886" name="Macro F1 %" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {/* Confusion Matrix */}
      {metrics.length > 0 && (
        <section>
          <div className="flex items-baseline gap-4 mb-3">
            <div className="font-mono-editorial text-stone-500">Confusion matrix ·</div>
            <select
              value={confusionDim}
              onChange={e => setConfusionDim(e.target.value)}
              className="px-0 py-0 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none text-sm font-medium"
            >
              {metrics.map(m => (
                <option key={m.dimension} value={m.dimension}>{m.dimension}</option>
              ))}
            </select>
          </div>
          {confusionData && (
            <div className="border border-seam bg-white p-4 overflow-auto">
              <table className="text-xs font-mono">
                <thead>
                  <tr>
                    <th className="px-2 py-1.5 text-left font-mono-editorial text-stone-500">True \ pred</th>
                    {confusionData.classes.map(c => (
                      <th key={c} className="px-2 py-1.5 text-center font-mono-editorial text-stone-500">{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {confusionData.classes.map(trueClass => (
                    <tr key={trueClass} className="border-t border-seam">
                      <td className="px-2 py-1.5 font-medium text-stone-700">{trueClass}</td>
                      {confusionData.classes.map(predClass => {
                        const val = confusionData.matrix[trueClass]?.[predClass] ?? 0
                        const isDiag = trueClass === predClass
                        return (
                          <td
                            key={predClass}
                            className={`px-2 py-1.5 text-center ${
                              isDiag ? 'bg-ink text-cream font-semibold' :
                              val > 0 ? 'bg-amber-50 text-amber-900' :
                              'text-stone-300'
                            }`}
                          >
                            {val}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* Per-dimension detailed metrics */}
      {metrics.length > 0 && (
        <section>
          <div className="font-mono-editorial text-stone-500 mb-3">Per-dimension metrics</div>
          <div className="border-y border-seam overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-seam">
                  <th className="px-3 py-3 text-left font-mono-editorial text-stone-500">Dimension</th>
                  <th className="px-3 py-3 text-right font-mono-editorial text-stone-500">Accuracy</th>
                  <th className="px-3 py-3 text-right font-mono-editorial text-stone-500">Macro P</th>
                  <th className="px-3 py-3 text-right font-mono-editorial text-stone-500">Macro R</th>
                  <th className="px-3 py-3 text-right font-mono-editorial text-stone-500">Macro F1</th>
                  <th className="px-3 py-3 text-right font-mono-editorial text-stone-500">N</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-seam">
                {metrics.map(m => (
                  <tr key={m.dimension} className="hover:bg-paper/40">
                    <td className="px-3 py-3 font-medium">{m.dimension}</td>
                    <td className="px-3 py-3 text-right font-mono">{formatPercent(m.metrics.accuracy)}</td>
                    <td className="px-3 py-3 text-right font-mono text-stone-600">{formatPercent(m.metrics.macro_precision)}</td>
                    <td className="px-3 py-3 text-right font-mono text-stone-600">{formatPercent(m.metrics.macro_recall)}</td>
                    <td className="px-3 py-3 text-right font-mono">{formatPercent(m.metrics.macro_f1)}</td>
                    <td className="px-3 py-3 text-right font-mono text-stone-500">{m.metrics.n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

    </div>
  )
}

function StatBlock({ label, value, tone = 'text-ink' }: { label: string; value: string; tone?: string }) {
  return (
    <div className="px-5 py-6">
      <div className="font-mono-editorial text-stone-500 mb-2">{label}</div>
      <div className={`font-display text-3xl font-medium tracking-tight ${tone}`}>{value}</div>
    </div>
  )
}
