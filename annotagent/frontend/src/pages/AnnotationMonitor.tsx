import { useEffect, useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getJob, cancelJob, pauseJob, resumeJob, getResults } from '../lib/api'
import { connectJobWS } from '../lib/ws'
import { formatTokens } from '../lib/utils'
import type { Job, AnnotationResult, WSProgressMessage } from '../types'

export default function AnnotationMonitor() {
  const { id, jobId } = useParams<{ id: string; jobId: string }>()
  const projectId = Number(id)
  const jid = Number(jobId)
  const navigate = useNavigate()

  const [job, setJob] = useState<Job | null>(null)
  const [progress, setProgress] = useState<WSProgressMessage | null>(null)
  const [results, setResults] = useState<AnnotationResult[]>([])
  const [selectedResult, setSelectedResult] = useState<AnnotationResult | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    getJob(projectId, jid).then(setJob)
    getResults(projectId, jid, { limit: 50 }).then(setResults)
  }, [projectId, jid])

  useEffect(() => {
    const ws = connectJobWS(jid, (msg) => {
      setProgress(msg)
      if (msg.status === 'completed' || msg.status === 'cancelled') {
        getJob(projectId, jid).then(setJob)
        getResults(projectId, jid, { limit: 50 }).then(setResults)
      }
    })
    wsRef.current = ws
    return () => ws.close()
  }, [jid, projectId])

  // Poll for results periodically
  useEffect(() => {
    const interval = setInterval(() => {
      getResults(projectId, jid, { limit: 50 }).then(setResults)
    }, 5000)
    return () => clearInterval(interval)
  }, [projectId, jid])

  const handleCancel = async () => {
    await cancelJob(projectId, jid)
    getJob(projectId, jid).then(setJob)
  }
  const handlePause = async () => {
    await pauseJob(projectId, jid)
    getJob(projectId, jid).then(setJob)
  }
  const handleResume = async () => {
    await resumeJob(projectId, jid)
    getJob(projectId, jid).then(setJob)
  }

  const completed = progress?.completed ?? job?.completed_items ?? 0
  const total = progress?.total ?? job?.total_items ?? 1
  const pct = total > 0 ? (completed / total) * 100 : 0
  const status = progress?.status ?? job?.status ?? 'pending'
  const tokens = progress?.tokens ?? job?.total_tokens ?? 0
  const cost = progress?.cost ?? job?.total_cost ?? 0
  const isRunning = status === 'running'
  const isPaused = status === 'paused'

  const statusTone =
    status === 'completed' ? 'text-emerald-700 bg-emerald-50 border-emerald-300' :
    status === 'running' ? 'text-blue-700 bg-blue-50 border-blue-300' :
    status === 'paused' ? 'text-amber-700 bg-amber-50 border-amber-300' :
    status === 'failed' ? 'text-red-700 bg-red-50 border-red-300' :
    status === 'cancelled' ? 'text-stone-600 bg-paper border-seam' :
    'text-stone-500 bg-paper border-seam'

  return (
    <div className="space-y-10">
      {/* Masthead */}
      <header className="border-b border-seam pb-6 flex items-end justify-between gap-6 flex-wrap">
        <div>
          <div className="font-mono-editorial text-stone-500 mb-2">
            Job · № {jid.toString().padStart(4, '0')}
          </div>
          <h1 className="text-4xl font-medium tracking-tight">Annotation in flight.</h1>
        </div>
        <div className="flex gap-2">
          {isRunning && (
            <button onClick={handlePause} className="px-4 py-2 border border-amber-600 text-amber-700 text-sm font-medium hover:bg-amber-50 transition-colors">
              Pause
            </button>
          )}
          {isPaused && (
            <button onClick={handleResume} className="px-4 py-2 border border-emerald-700 text-emerald-700 text-sm font-medium hover:bg-emerald-50 transition-colors">
              Resume
            </button>
          )}
          {(isRunning || isPaused) && (
            <button onClick={handleCancel} className="px-4 py-2 border border-red-600 text-red-700 text-sm font-medium hover:bg-red-50 transition-colors">
              Cancel
            </button>
          )}
          {!isRunning && status !== 'pending' && (
            <button
              onClick={() => navigate(`/projects/${projectId}/results/${jid}`)}
              className="px-4 py-2 bg-ink text-cream text-sm font-medium hover:bg-stone-800 transition-colors"
            >
              View results →
            </button>
          )}
        </div>
      </header>

      {/* Progress */}
      <section className="border border-seam bg-white p-6">
        <div className="flex items-end justify-between gap-6 flex-wrap mb-4">
          <div className="flex items-center gap-4">
            <span className={`font-mono-editorial px-2.5 py-1 border ${statusTone}`}>
              {status}
            </span>
            <div className="font-mono text-sm text-stone-700">
              {completed.toLocaleString()} <span className="text-stone-400">/</span> {total.toLocaleString()} items
            </div>
          </div>
          <div className="flex gap-8 text-sm">
            <Metric label="Tokens" value={formatTokens(tokens)} />
            <Metric label="Cost (USD)" value={`$${cost.toFixed(4)}`} />
            <Metric label="Progress" value={`${pct.toFixed(1)}%`} />
          </div>
        </div>
        <div className="w-full bg-paper h-1.5">
          <div className="bg-ink h-1.5 transition-all duration-500" style={{ width: `${pct}%` }} />
        </div>
      </section>

      {/* Results Table */}
      <section>
        <div className="font-mono-editorial text-stone-500 mb-3">
          Stream · latest {results.length} predictions
        </div>
        <div className="border-y border-seam">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-seam">
                <th className="px-3 py-3 text-left font-mono-editorial text-stone-500">#</th>
                <th className="px-3 py-3 text-left font-mono-editorial text-stone-500">Dimension</th>
                <th className="px-3 py-3 text-left font-mono-editorial text-stone-500">Predicted</th>
                <th className="px-3 py-3 text-right font-mono-editorial text-stone-500">Tokens</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-seam">
              {results.map(r => (
                <tr
                  key={r.id}
                  onClick={() => setSelectedResult(r)}
                  className="hover:bg-paper/60 cursor-pointer transition-colors"
                >
                  <td className="px-3 py-3 font-mono text-xs text-stone-500">{r.data_item_id.toString().padStart(4, '0')}</td>
                  <td className="px-3 py-3">{r.dimension_name}</td>
                  <td className="px-3 py-3">
                    <span className="px-2 py-0.5 bg-paper border border-seam text-stone-700 text-xs">
                      {r.predicted_label}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-right font-mono text-xs text-stone-500">{r.tokens_used}</td>
                </tr>
              ))}
              {results.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-16 text-center text-stone-400 font-mono-editorial">Waiting for predictions…</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Reasoning Drawer */}
      {selectedResult && (
        <section className="border border-seam bg-white">
          <div className="flex items-center justify-between p-5 border-b border-seam">
            <div>
              <div className="font-mono-editorial text-stone-500 mb-1">Reasoning</div>
              <h3 className="font-medium">{selectedResult.dimension_name}</h3>
            </div>
            <button onClick={() => setSelectedResult(null)} className="font-mono-editorial text-stone-400 hover:text-ink">Close</button>
          </div>
          <div className="px-5 py-3 border-b border-seam text-sm">
            Predicted · <span className="font-medium">{selectedResult.predicted_label}</span>
          </div>
          <pre className="p-5 font-mono text-xs leading-relaxed whitespace-pre-wrap max-h-64 overflow-auto text-stone-700">
            {selectedResult.reasoning}
          </pre>
        </section>
      )}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-right">
      <div className="font-mono-editorial text-stone-500">{label}</div>
      <div className="font-mono text-sm text-ink mt-0.5">{value}</div>
    </div>
  )
}
