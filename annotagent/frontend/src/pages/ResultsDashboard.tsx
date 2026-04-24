import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { getJob, getMetrics, getConfusionMatrix, exportResults, listDatasets, listCalibrations, runCalibration } from '../lib/api'
import { formatTokens, formatPercent } from '../lib/utils'
import type { Job, DimensionMetrics, Dataset, CalibrationRun } from '../types'

export default function ResultsDashboard() {
  const { id, jobId } = useParams<{ id: string; jobId: string }>()
  const projectId = Number(id)
  const jid = Number(jobId)

  const [job, setJob] = useState<Job | null>(null)
  const [metrics, setMetrics] = useState<DimensionMetrics[]>([])
  const [confusionDim, setConfusionDim] = useState<string>('')
  const [confusionData, setConfusionData] = useState<{ classes: string[]; matrix: Record<string, Record<string, number>> } | null>(null)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [calibrations, setCalibrations] = useState<CalibrationRun[]>([])
  const [calLoading, setCalLoading] = useState(false)

  useEffect(() => {
    getJob(projectId, jid).then(setJob)
    getMetrics(projectId, jid).then(m => {
      setMetrics(m)
      if (m.length > 0) setConfusionDim(m[0].dimension)
    })
    listDatasets(projectId).then(setDatasets)
    listCalibrations(projectId, jid).then(setCalibrations)
  }, [projectId, jid])

  useEffect(() => {
    if (confusionDim) {
      getConfusionMatrix(projectId, jid, confusionDim).then(setConfusionData)
    }
  }, [confusionDim, projectId, jid])

  const handleExport = async (format: 'csv' | 'json') => {
    const resp = await exportResults(projectId, jid, format)
    if (format === 'csv') {
      const url = URL.createObjectURL(resp.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `job_${jid}_results.csv`
      a.click()
    } else {
      const blob = new Blob([JSON.stringify(resp.data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `job_${jid}_results.json`
      a.click()
    }
  }

  const handleCalibration = async () => {
    const goldDs = datasets.find(d => d.is_gold)
    if (!goldDs) return
    setCalLoading(true)
    try {
      await runCalibration(projectId, jid, goldDs.id)
      const cals = await listCalibrations(projectId, jid)
      setCalibrations(cals)
    } finally {
      setCalLoading(false)
    }
  }

  const goldDataset = datasets.find(d => d.is_gold)

  const chartData = metrics.map(m => ({
    dimension: m.dimension.length > 15 ? m.dimension.substring(0, 15) + '...' : m.dimension,
    accuracy: +(m.metrics.accuracy * 100).toFixed(1),
    macro_f1: +(m.metrics.macro_f1 * 100).toFixed(1),
  }))

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
          <button onClick={() => handleExport('csv')} className="px-4 py-2 text-sm font-medium text-ink border border-seam hover:border-ink transition-colors">
            Export · CSV
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
        <StatBlock label="Cost (USD)" value={`$${(job?.total_cost ?? 0).toFixed(4)}`} />
        <StatBlock
          label="Status"
          value={job?.status ?? '—'}
          tone={job?.status === 'completed' ? 'text-emerald-700' : 'text-stone-600'}
        />
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

      {/* Calibration */}
      <section className="border-t border-seam pt-8">
        <div className="font-mono-editorial text-stone-500 mb-3">Calibration loop</div>
        <h3 className="text-2xl font-medium tracking-tight mb-4">Distil agreed-subset errors into rules.</h3>
        {goldDataset ? (
          <div>
            <button
              onClick={handleCalibration}
              disabled={calLoading}
              className="group inline-flex items-center gap-3 px-5 py-2.5 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-50 transition-colors"
            >
              <span>{calLoading ? 'Running calibration…' : 'Run calibration'}</span>
              <span className="transition-transform group-enabled:group-hover:translate-x-1">→</span>
            </button>
            {calibrations.length > 0 && (
              <div className="mt-8 space-y-8">
                {calibrations.map(cal => {
                  const m = cal.metrics_json as {
                    before?: Record<string, { accuracy?: number; macro_f1?: number }>
                    after?: Record<string, { accuracy?: number; macro_f1?: number }>
                    delta?: Record<string, { accuracy_delta?: number; macro_f1_delta?: number }>
                  }
                  const dims = Object.keys(m.before ?? {})
                  const hasAfter = m.after && Object.keys(m.after).length > 0
                  return (
                    <div key={cal.id} className="border border-seam bg-white">
                      <div className="px-5 py-3 border-b border-seam flex items-baseline gap-3">
                        <div className="font-mono-editorial text-stone-500">
                          Run · {cal.id.toString().padStart(3, '0')}
                        </div>
                        {hasAfter ? (
                          <span className="font-mono-editorial text-emerald-700">re-annotated</span>
                        ) : (
                          <span className="font-mono-editorial text-amber-700">rules only</span>
                        )}
                      </div>

                      {dims.length > 0 && (
                        <div className="overflow-auto">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="border-b border-seam">
                                <th className="px-4 py-3 text-left font-mono-editorial text-stone-500">Dimension</th>
                                <th className="px-4 py-3 text-right font-mono-editorial text-stone-500">Before acc</th>
                                <th className="px-4 py-3 text-right font-mono-editorial text-stone-500">After acc</th>
                                <th className="px-4 py-3 text-right font-mono-editorial text-stone-500">Δ acc</th>
                                <th className="px-4 py-3 text-right font-mono-editorial text-stone-500">Before F1</th>
                                <th className="px-4 py-3 text-right font-mono-editorial text-stone-500">After F1</th>
                                <th className="px-4 py-3 text-right font-mono-editorial text-stone-500">Δ F1</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-seam">
                              {dims.map(dim => {
                                const b = m.before?.[dim] ?? {}
                                const a = m.after?.[dim] ?? {}
                                const d = m.delta?.[dim] ?? {}
                                const fmt = (v?: number) => v !== undefined ? (v * 100).toFixed(1) + '%' : '—'
                                const fmtD = (v?: number) => {
                                  if (v === undefined) return '—'
                                  const pct = (v * 100).toFixed(1)
                                  const cls = v > 0 ? 'text-emerald-700' : v < 0 ? 'text-red-600' : 'text-stone-500'
                                  return <span className={cls}>{v > 0 ? '+' : ''}{pct}pp</span>
                                }
                                return (
                                  <tr key={dim} className="hover:bg-paper/40">
                                    <td className="px-4 py-3 font-medium">{dim}</td>
                                    <td className="px-4 py-3 text-right font-mono text-stone-600">{fmt(b.accuracy)}</td>
                                    <td className="px-4 py-3 text-right font-mono">{hasAfter ? fmt(a.accuracy) : '—'}</td>
                                    <td className="px-4 py-3 text-right font-mono">{hasAfter ? fmtD(d.accuracy_delta) : '—'}</td>
                                    <td className="px-4 py-3 text-right font-mono text-stone-600">{fmt(b.macro_f1)}</td>
                                    <td className="px-4 py-3 text-right font-mono">{hasAfter ? fmt(a.macro_f1) : '—'}</td>
                                    <td className="px-4 py-3 text-right font-mono">{hasAfter ? fmtD(d.macro_f1_delta) : '—'}</td>
                                  </tr>
                                )
                              })}
                            </tbody>
                          </table>
                          {!hasAfter && (
                            <p className="px-5 py-3 border-t border-seam text-xs text-stone-500">
                              No re-annotation pass ran. The rule library was updated; run calibration again with a larger gold subset to re-score.
                            </p>
                          )}
                        </div>
                      )}

                      {cal.rules_generated.length > 0 && (
                        <div className="border-t border-seam p-5">
                          <div className="font-mono-editorial text-stone-500 mb-2">Generated calibration rules</div>
                          <pre className="bg-paper/50 border border-seam p-3 font-mono text-[11px] leading-relaxed max-h-40 overflow-auto text-stone-700">
                            {JSON.stringify(cal.rules_generated, null, 2)}
                          </pre>
                        </div>
                      )}
                      {cal.error_patterns.length > 0 && (
                        <div className="border-t border-seam p-5">
                          <div className="font-mono-editorial text-stone-500 mb-2">Mined error patterns</div>
                          <pre className="bg-paper/50 border border-seam p-3 font-mono text-[11px] leading-relaxed max-h-40 overflow-auto text-stone-700">
                            {JSON.stringify(cal.error_patterns, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        ) : (
          <div className="border border-dashed border-seam bg-paper/40 py-10 text-center">
            <div className="font-mono-editorial text-stone-500 mb-1">No gold dataset</div>
            <p className="text-sm text-stone-600">Upload a gold standard dataset in Setup to enable calibration.</p>
          </div>
        )}
      </section>
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
