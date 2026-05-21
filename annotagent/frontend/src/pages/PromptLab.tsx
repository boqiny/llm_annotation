import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Legend,
} from 'recharts'
import api, {
  listAvailableOptimizers, listOptimizerRuns, startOptimizerRun, getOptimizerRun,
  listCodebooks, listDatasets, autoGeneratePrompt, patchOptimizerRun,
  listMemoryVersions, deleteOptimizerRun, cancelOptimizerRun, submitMemoryFeedback,
  previewPrompt, commitPrompt,
  type OptimizerInfo, type OptimizerRun, type AutoPromptResponse, type MemoryVersion,
} from '../lib/api'
import type { Codebook, Dataset } from '../types'

type Tab = 'prompts' | 'improve' | 'runs' | 'memory'

function fmtError(e: any): string {
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (d?.message) return String(d.message)
  if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg)
  return e?.message || 'Unknown error'
}

export default function PromptLabV2() {
  const { id } = useParams<{ id: string }>()
  const projectId = Number(id)

  const [tab, setTab] = useState<Tab>('runs')
  const [codebooks, setCodebooks] = useState<Codebook[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [runs, setRuns] = useState<OptimizerRun[]>([])
  const [optimizers, setOptimizers] = useState<OptimizerInfo[]>([])
  const [memory, setMemory] = useState<MemoryVersion[]>([])

  const [autoPrompt, setAutoPrompt] = useState<AutoPromptResponse | null>(null)
  const [autoPromptLoading, setAutoPromptLoading] = useState(false)
  const [autoPromptError, setAutoPromptError] = useState('')

  // Improve tab state
  const [selectedDim, setSelectedDim] = useState('')
  const [selectedGold, setSelectedGold] = useState<number | null>(null)
  const [budget, setBudget] = useState(5)
  const [launching, setLaunching] = useState(false)
  const [launchError, setLaunchError] = useState('')

  // Runs master-detail
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null)
  const [selectedRun, setSelectedRun] = useState<OptimizerRun | null>(null)

  const activeCb = codebooks[codebooks.length - 1]

  useEffect(() => {
    Promise.all([
      listAvailableOptimizers(projectId),
      listCodebooks(projectId),
      listDatasets(projectId),
      listOptimizerRuns(projectId),
    ]).then(([opts, cbs, dss, rs]) => {
      setOptimizers(opts); setCodebooks(cbs); setDatasets(dss); setRuns(rs)
      if (cbs.length > 0 && cbs[cbs.length - 1].dimensions[0]) {
        setSelectedDim(cbs[cbs.length - 1].dimensions[0].name)
      }
      const def = dss.find(d => d.is_gold) ?? dss[0]
      if (def) setSelectedGold(def.id)
    })
  }, [projectId])

  // Poll in-flight runs
  useEffect(() => {
    const inFlight = runs.some(r => r.status === 'running' || r.status === 'pending')
    if (!inFlight) return
    const iv = setInterval(() => listOptimizerRuns(projectId).then(setRuns), 3000)
    return () => clearInterval(iv)
  }, [runs, projectId])

  // Selected run polling
  useEffect(() => {
    if (!selectedRunId) { setSelectedRun(null); return }
    getOptimizerRun(projectId, selectedRunId).then(setSelectedRun)
    const status = selectedRun?.status
    if (status !== 'running' && status !== 'pending') return
    const iv = setInterval(() => {
      getOptimizerRun(projectId, selectedRunId).then(r => {
        setSelectedRun(r)
        setRuns(prev => prev.map(x => x.id === r.id ? r : x))
      }).catch(() => {})
    }, 2000)
    return () => clearInterval(iv)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRunId, selectedRun?.status, projectId])

  // Memory refresh
  useEffect(() => {
    listMemoryVersions(projectId).then(setMemory).catch(() => setMemory([]))
  }, [projectId, runs.length, runs.map(r => r.status).join(',')])

  // Auto-prompt cache
  const autoPromptCacheKey = activeCb ? `annotagent.autoPrompt.${projectId}.${activeCb.id}` : null
  useEffect(() => {
    if (!activeCb || !autoPromptCacheKey || autoPrompt) return
    try {
      const cached = localStorage.getItem(autoPromptCacheKey)
      if (cached) {
        const parsed = JSON.parse(cached)
        if (parsed && Array.isArray(parsed.prompts)) { setAutoPrompt(parsed); return }
      }
    } catch {}
    setAutoPromptLoading(true)
    autoGeneratePrompt(projectId, activeCb.id)
      .then(r => {
        setAutoPrompt(r)
        try { localStorage.setItem(autoPromptCacheKey, JSON.stringify(r)) } catch {}
      })
      .catch(e => setAutoPromptError(fmtError(e)))
      .finally(() => setAutoPromptLoading(false))
  }, [activeCb, autoPromptCacheKey, autoPrompt, projectId])

  return (
    <div className="space-y-6">
      <header className="flex items-baseline justify-between gap-4 border-b border-seam pb-4">
        <div>
          <div className="font-mono-editorial text-stone-500 mb-1">Improve</div>
          <h1 className="text-2xl font-medium tracking-tight">Find and fix annotation mistakes from your examples.</h1>
        </div>
        <div className="font-mono-editorial text-stone-400">
          {runs.length} run{runs.length !== 1 ? 's' : ''}
        </div>
      </header>

      <Tabs value={tab} onChange={setTab} items={[
        { id: 'prompts', label: 'Prompts',  count: autoPrompt?.prompts.length },
        { id: 'improve', label: 'Improve',                                     },
        { id: 'runs',    label: 'Runs',     count: runs.length                 },
        { id: 'memory',  label: 'Memory',   count: memory.length               },
      ]} />

      {tab === 'prompts' && (
        <PromptsTab
          activeCb={activeCb}
          autoPrompt={autoPrompt}
          loading={autoPromptLoading}
          error={autoPromptError}
          runs={runs}
          onRegenerate={async () => {
            if (!activeCb || !autoPromptCacheKey) return
            setAutoPromptLoading(true); setAutoPromptError('')
            try {
              const r = await autoGeneratePrompt(projectId, activeCb.id)
              setAutoPrompt(r)
              try { localStorage.setItem(autoPromptCacheKey, JSON.stringify(r)) } catch {}
            } catch (e: any) { setAutoPromptError(fmtError(e)) }
            finally { setAutoPromptLoading(false) }
          }}
          onJumpToRun={(id) => { setSelectedRunId(id); setTab('runs') }}
        />
      )}

      {tab === 'improve' && (
        <ImproveTab
          codebooks={codebooks}
          datasets={datasets}
          selectedDim={selectedDim} setSelectedDim={setSelectedDim}
          selectedGold={selectedGold} setSelectedGold={setSelectedGold}
          budget={budget} setBudget={setBudget}
          launching={launching} launchError={launchError}
          projectId={projectId}
          onLaunched={(run) => {
            setRuns([run, ...runs])
            setSelectedRunId(run.id)
            setTab('runs')
          }}
          setLaunching={setLaunching} setLaunchError={setLaunchError}
        />
      )}

      {tab === 'runs' && (
        <RunsTab
          runs={runs}
          selectedRunId={selectedRunId}
          selectedRun={selectedRun}
          onSelect={setSelectedRunId}
          onUpdate={(r) => {
            setSelectedRun(r)
            setRuns(prev => prev.map(x => x.id === r.id ? r : x))
          }}
          onDelete={async (r) => {
            if (!window.confirm(`Delete run ${String(r.id).padStart(4, '0')} (${r.dimension_name})?`)) return
            try {
              await deleteOptimizerRun(projectId, r.id)
              setRuns(prev => prev.filter(x => x.id !== r.id))
              if (selectedRunId === r.id) setSelectedRunId(null)
            } catch (e: any) { alert(`Delete failed: ${fmtError(e)}`) }
          }}
          onCancel={async (r) => {
            if (!window.confirm(`Stop run ${String(r.id).padStart(4, '0')}?`)) return
            try { await cancelOptimizerRun(projectId, r.id) }
            catch (e: any) { alert(`Cancel failed: ${fmtError(e)}`) }
          }}
          projectId={projectId}
        />
      )}

      {tab === 'memory' && (
        <MemoryTab
          memory={memory}
          projectId={projectId}
          dimensions={activeCb?.dimensions.map(d => d.name) ?? []}
          onRefresh={() => listMemoryVersions(projectId).then(setMemory).catch(() => setMemory([]))}
        />
      )}
    </div>
  )
}

/* ─── Tabs primitive ───────────────────────────────────────── */

function Tabs<T extends string>({
  value, onChange, items,
}: {
  value: T
  onChange: (v: T) => void
  items: { id: T; label: string; count?: number }[]
}) {
  return (
    <div className="flex border-b border-seam">
      {items.map(it => {
        const active = it.id === value
        return (
          <button
            key={it.id}
            onClick={() => onChange(it.id)}
            className={`px-4 py-2 -mb-px border-b-2 text-sm font-medium transition-colors ${
              active ? 'border-ink text-ink' : 'border-transparent text-stone-500 hover:text-ink'
            }`}
          >
            {it.label}
            {typeof it.count === 'number' && (
              <span className={`ml-1.5 font-mono-editorial ${active ? 'text-stone-500' : 'text-stone-400'}`}>
                {it.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

/* ─── Prompts tab ──────────────────────────────────────────── */

function PromptsTab({
  activeCb, autoPrompt, loading, error, runs, onRegenerate, onJumpToRun,
}: {
  activeCb?: Codebook
  autoPrompt: AutoPromptResponse | null
  loading: boolean
  error: string
  runs: OptimizerRun[]
  onRegenerate: () => void
  onJumpToRun: (runId: number) => void
}) {
  if (!activeCb) {
    return <Empty>Load a codebook on Setup first.</Empty>
  }
  if (loading && !autoPrompt) {
    return <Empty>Drafting prompts for {activeCb.dimensions.length} dimensions…</Empty>
  }
  if (error) {
    return (
      <div className="border border-red-200 bg-red-50/60 p-4 text-sm">
        <div className="font-mono-editorial text-red-700 mb-1">Generation failed</div>
        <p className="text-stone-700">{error}</p>
        <button onClick={onRegenerate} className="mt-3 px-3 py-1.5 text-xs font-medium border border-ink hover:bg-ink hover:text-cream">
          Try again
        </button>
      </div>
    )
  }
  if (!autoPrompt) {
    return (
      <button onClick={onRegenerate} className="px-4 py-2 text-sm font-medium border border-ink hover:bg-ink hover:text-cream">
        Generate prompts
      </button>
    )
  }
  return (
    <div>
      <div className="flex items-baseline justify-between mb-3">
        <div className="font-mono-editorial text-stone-500">
          {autoPrompt.prompts.length} prompts · {activeCb.name}
        </div>
        <button onClick={onRegenerate} disabled={loading}
                className="font-mono-editorial text-stone-500 hover:text-ink disabled:opacity-50">
          {loading ? 're-generating…' : 're-generate all'}
        </button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {autoPrompt.prompts.map(p => {
          const optimized = runs.filter(r => r.dimension_name === p.dimension_name
            && r.optimizer_name === 'reflect_agent' && r.status === 'completed')
            .sort((a, b) => b.id - a.id)[0]
          return <PromptCard key={p.dimension_name} dp={p} optimizedRun={optimized} onJumpToRun={onJumpToRun} />
        })}
      </div>
    </div>
  )
}

function PromptCard({
  dp, optimizedRun, onJumpToRun,
}: {
  dp: { dimension_name: string; prompt: string; version: string; path: string; error: string | null }
  optimizedRun?: OptimizerRun
  onJumpToRun: (runId: number) => void
}) {
  const [open, setOpen] = useState(false)
  const [view, setView] = useState<'starting' | 'optimized'>(optimizedRun ? 'optimized' : 'starting')
  const test = (optimizedRun?.artifact as any)?.test as { final_score?: number } | undefined
  const score = test?.final_score ?? optimizedRun?.final_score
  const text = view === 'optimized' && optimizedRun ? optimizedRun.optimized_prompt : dp.prompt

  return (
    <div className="border border-seam bg-white">
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-paper/40">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="font-mono-editorial text-stone-400 w-3">{open ? '−' : '+'}</span>
          <span className="font-medium truncate">{dp.dimension_name}</span>
        </div>
        <div className="font-mono-editorial text-xs">
          {optimizedRun
            ? <span className="text-violet-700">run {String(optimizedRun.id).padStart(4, '0')}{typeof score === 'number' ? ` · ${(score * 100).toFixed(0)}%` : ''}</span>
            : <span className="text-stone-400">{dp.version}</span>
          }
        </div>
      </button>
      {open && !dp.error && (
        <div className="border-t border-seam">
          {optimizedRun && (
            <div className="px-4 py-1.5 flex items-center gap-3 border-b border-seam bg-paper/40">
              <button onClick={() => setView('starting')} className={`text-xs font-mono-editorial ${view === 'starting' ? 'text-ink underline' : 'text-stone-500 hover:text-ink'}`}>starting</button>
              <span className="text-stone-300">·</span>
              <button onClick={() => setView('optimized')} className={`text-xs font-mono-editorial ${view === 'optimized' ? 'text-violet-700 underline' : 'text-stone-500 hover:text-ink'}`}>optimized</button>
              <button onClick={() => onJumpToRun(optimizedRun.id)} className="ml-auto text-xs font-mono-editorial text-stone-500 hover:text-ink">open run →</button>
            </div>
          )}
          <pre className="px-4 py-3 text-xs text-stone-800 whitespace-pre-wrap font-mono leading-relaxed max-h-[360px] overflow-auto">{text}</pre>
        </div>
      )}
      {open && dp.error && <div className="border-t border-seam px-4 py-3 text-xs text-red-700">{dp.error}</div>}
    </div>
  )
}

/* ─── Improve tab ──────────────────────────────────────────── */

function ImproveTab({
  codebooks, datasets, selectedDim, setSelectedDim, selectedGold, setSelectedGold,
  budget, setBudget, launching, launchError, projectId, onLaunched,
  setLaunching, setLaunchError,
}: {
  codebooks: Codebook[]
  datasets: Dataset[]
  selectedDim: string
  setSelectedDim: (v: string) => void
  selectedGold: number | null
  setSelectedGold: (v: number) => void
  budget: number
  setBudget: (v: number) => void
  launching: boolean
  launchError: string
  projectId: number
  onLaunched: (run: OptimizerRun) => void
  setLaunching: (v: boolean) => void
  setLaunchError: (v: string) => void
}) {
  const activeCb = codebooks[codebooks.length - 1]

  // Per-class peek
  const [classCounts, setClassCounts] = useState<Record<string, Record<string, number>>>({})
  useEffect(() => {
    if (!selectedGold) { setClassCounts({}); return }
    api.get(`/projects/${projectId}/datasets/${selectedGold}`, { params: { limit: 500, offset: 0 } })
      .then(r => {
        const items: any[] = r.data?.items || []
        const cc: Record<string, Record<string, number>> = {}
        for (const it of items) {
          const g = it.gold_labels || {}
          for (const k of Object.keys(g)) {
            const v = g[k]; if (v == null || v === '') continue
            if (!cc[k]) cc[k] = {}
            const labels = Array.isArray(v) ? v.map(String) : [String(v)]
            for (const lbl of labels) cc[k][lbl] = (cc[k][lbl] || 0) + 1
          }
        }
        setClassCounts(cc)
      })
      .catch(() => setClassCounts({}))
  }, [selectedGold, projectId])

  const classes = classCounts[selectedDim] ?? {}
  const total = Object.values(classes).reduce((a, b) => a + b, 0)
  const split = useMemo(() => stratifiedPreview(classes, 15, 42), [classes])
  const sorted = Object.keys(classes).sort((a, b) => classes[b] - classes[a])
  const tooFew = total > 0 && total < 15
  const noLabels = total === 0

  const handleLaunch = async () => {
    if (!selectedGold || noLabels || tooFew) return
    setLaunching(true); setLaunchError('')
    try {
      const run = await startOptimizerRun(projectId, {
        optimizer_name: 'reflect_agent',
        dimension_name: selectedDim,
        gold_dataset_id: selectedGold,
        budget,
        train_frac: 0.15, val_frac: 0.42, test_frac: 0.43,
      })
      onLaunched(run)
    } catch (e: any) { setLaunchError(fmtError(e)) }
    finally { setLaunching(false) }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Left: pickers */}
      <div className="lg:col-span-1 space-y-4">
        <div>
          <Label>Dimension</Label>
          <select value={selectedDim} onChange={e => setSelectedDim(e.target.value)}
                  className="w-full px-0 py-1.5 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-medium">
            {activeCb?.dimensions.map(d => (
              <option key={d.id} value={d.name}>{d.name} ({d.labels.length})</option>
            ))}
          </select>
        </div>
        <div>
          <Label>Labeled examples</Label>
          {datasets.length === 0
            ? <p className="text-sm text-stone-500">None loaded.</p>
            : (
              <select value={selectedGold ?? ''} onChange={e => setSelectedGold(Number(e.target.value))}
                      className="w-full px-0 py-1.5 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-medium">
                {datasets.map(d => (
                  <option key={d.id} value={d.id}>{d.name} ({d.total_items})</option>
                ))}
              </select>
            )}
        </div>
        <div>
          <Label>Rounds</Label>
          <input type="number" min={1} max={20} value={budget}
                 onChange={e => setBudget(Math.max(1, Math.min(20, Number(e.target.value) || 5)))}
                 className="w-full px-0 py-1.5 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-mono text-sm" />
        </div>
        <button onClick={handleLaunch} disabled={launching || noLabels || tooFew}
                className="w-full py-2.5 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-40">
          {launching ? 'Starting…' : 'Improve from examples →'}
        </button>
        {launchError && <div className="text-xs text-red-700">{launchError}</div>}
      </div>

      {/* Right: split preview */}
      <div className="lg:col-span-2">
        {noLabels ? (
          <div className="border border-amber-200 bg-amber-50/50 p-4 text-sm text-amber-800">
            <div className="font-mono-editorial text-amber-700 mb-1">No labels for "{selectedDim}"</div>
            Available: {Object.keys(classCounts).filter(k => Object.keys(classCounts[k]).length > 0).join(', ') || '—'}.
          </div>
        ) : tooFew ? (
          <div className="border border-amber-200 bg-amber-50/50 p-4 text-sm text-amber-800">
            Need ≥15 labeled items; gold has {total}.
          </div>
        ) : (
          <div className="border border-seam bg-paper/40 p-4">
            <div className="flex items-baseline justify-between mb-3">
              <div className="font-mono-editorial text-stone-500">
                {total} labeled · stratified
              </div>
              <div className="font-mono text-xs text-stone-500">
                {split.n_train} train · {split.n_val} val · {split.n_test} test
              </div>
            </div>
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-seam font-mono-editorial text-stone-500">
                  <th className="text-left py-1.5">label</th>
                  <th className="text-right py-1.5">total</th>
                  <th className="text-right py-1.5">train</th>
                  <th className="text-right py-1.5">val</th>
                  <th className="text-right py-1.5">test</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-seam">
                {sorted.map(c => {
                  const s = split.perClass[c]
                  const tiny = (s?.n ?? 0) < 3
                  return (
                    <tr key={c}>
                      <td className="py-1.5 truncate max-w-[260px]" title={c}>{c}</td>
                      <td className="py-1.5 text-right text-stone-700">{s?.n ?? 0}</td>
                      <td className="py-1.5 text-right text-stone-700">{s?.train ?? 0}</td>
                      <td className={`py-1.5 text-right ${tiny ? 'text-amber-700' : 'text-stone-700'}`}>{s?.val ?? 0}</td>
                      <td className={`py-1.5 text-right ${tiny ? 'text-amber-700' : 'text-stone-700'}`}>{s?.test ?? 0}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function stratifiedPreview(classes: Record<string, number>, trainPct: number, valPct: number) {
  const tf = trainPct / 100, vf = valPct / 100
  const perClass: Record<string, { n: number; train: number; val: number; test: number }> = {}
  let n_train = 0, n_val = 0, n_test = 0
  for (const c of Object.keys(classes).sort()) {
    const n = classes[c]
    if (n < 3) { perClass[c] = { n, train: n, val: 0, test: 0 }; n_train += n; continue }
    const nt = Math.max(1, Math.round(tf * n))
    let nv = Math.max(1, Math.round(vf * n))
    if (nt + nv > n - 1) nv = Math.max(1, n - nt - 1)
    const nx = n - nt - nv
    perClass[c] = { n, train: nt, val: nv, test: nx }
    n_train += nt; n_val += nv; n_test += nx
  }
  return { n_train, n_val, n_test, perClass }
}

/* ─── Runs tab (master-detail) ─────────────────────────────── */

function RunsTab({
  runs, selectedRunId, selectedRun, onSelect, onUpdate, onDelete, onCancel, projectId,
}: {
  runs: OptimizerRun[]
  selectedRunId: number | null
  selectedRun: OptimizerRun | null
  onSelect: (id: number | null) => void
  onUpdate: (r: OptimizerRun) => void
  onDelete: (r: OptimizerRun) => void
  onCancel: (r: OptimizerRun) => void
  projectId: number
}) {
  if (runs.length === 0) {
    return <Empty>No runs yet. Launch one from <em>Improve</em>.</Empty>
  }
  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
      {/* Master: list */}
      <div className="lg:col-span-4 border border-seam bg-white max-h-[78vh] overflow-auto">
        {runs.map(r => {
          const test = (r.artifact as any)?.test as { final_score?: number; delta?: number } | undefined
          const score = test?.final_score ?? r.final_score
          const delta = test?.delta ?? (r.final_score - r.initial_score)
          const sel = r.id === selectedRunId
          const tone = r.status === 'completed' ? 'text-emerald-700'
                     : r.status === 'running'   ? 'text-blue-700'
                     : r.status === 'failed'    ? 'text-red-700'
                     : 'text-stone-500'
          return (
            <div key={r.id}
                 onClick={() => onSelect(sel ? null : r.id)}
                 className={`px-4 py-3 border-b border-seam cursor-pointer transition-colors group ${
                   sel ? 'bg-paper' : 'hover:bg-paper/60'
                 }`}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-mono text-xs text-stone-400">{String(r.id).padStart(4, '0')}</span>
                <span className={`font-mono-editorial ${tone}`}>{r.status}</span>
              </div>
              <div className="mt-0.5 font-medium truncate">{r.dimension_name}</div>
              <div className="mt-1 flex items-baseline justify-between gap-2 text-xs font-mono">
                <span className="text-stone-700">
                  {r.status === 'completed' ? `${(score * 100).toFixed(1)}%` : '—'}
                </span>
                {r.status === 'completed' && (
                  <span className={delta >= 0 ? 'text-emerald-700' : 'text-red-700'}>
                    {delta >= 0 ? '+' : ''}{(delta * 100).toFixed(1)}pp
                  </span>
                )}
                <span className="ml-auto opacity-0 group-hover:opacity-100 transition-opacity flex gap-2">
                  {(r.status === 'running' || r.status === 'pending') && (
                    <button onClick={e => { e.stopPropagation(); onCancel(r) }} className="font-mono-editorial text-stone-400 hover:text-amber-700">stop</button>
                  )}
                  {(r.status !== 'running' && r.status !== 'pending') && (
                    <button onClick={e => { e.stopPropagation(); onDelete(r) }} className="font-mono-editorial text-stone-400 hover:text-red-600">delete</button>
                  )}
                </span>
              </div>
            </div>
          )
        })}
      </div>

      {/* Detail */}
      <div className="lg:col-span-8 border border-seam bg-white max-h-[78vh] overflow-auto">
        {selectedRun
          ? <RunDetailV2 run={selectedRun} projectId={projectId} onUpdate={onUpdate} />
          : <Empty>Pick a run on the left.</Empty>
        }
      </div>
    </div>
  )
}

function RunDetailV2({
  run, projectId, onUpdate,
}: { run: OptimizerRun; projectId: number; onUpdate: (r: OptimizerRun) => void }) {
  const test = (run.artifact as any)?.test as
    | { initial_score: number; final_score: number; delta: number; n: number; initial_metrics?: any; final_metrics?: any }
    | undefined
  const splits = (run.artifact as any)?.splits as
    | { n_train: number; n_val: number; n_test: number; per_class?: Record<string, any> }
    | undefined
  const ruleLib: any[] = Array.isArray(run.artifact?.rule_library) ? run.artifact.rule_library : []
  const score = test?.final_score ?? run.final_score
  const delta = test?.delta ?? (run.final_score - run.initial_score)

  const isRunning = run.status === 'running' || run.status === 'pending'
  const traj = (run.trajectory || []) as any[]
  const currentRound = traj.reduce((m, t) => Math.max(m, t?.round ?? 0), 0)
  const budget = run.budget || 1
  const progressPct = isRunning ? Math.max(4, Math.min(100, (currentRound / budget) * 100)) : 100

  return (
    <div>
      {/* Header */}
      <div className="px-5 py-4 border-b border-seam">
        <div className="flex items-baseline justify-between">
          <div>
            <div className="font-mono-editorial text-stone-500 mb-0.5 flex items-center gap-2">
              <span>Run {String(run.id).padStart(4, '0')} · {run.optimizer_name}</span>
              {isRunning && <LivePulse />}
            </div>
            <h3 className="text-xl font-medium tracking-tight">{run.dimension_name}</h3>
          </div>
          <div className="flex gap-5 text-right">
            <Stat label="Before" value={
              isRunning && (test?.initial_score ?? run.initial_score) === 0 ? '—'
              : `${((test?.initial_score ?? run.initial_score) * 100).toFixed(1)}%`
            } />
            <Stat label="After"  value={
              isRunning ? '—'
              : `${(score * 100).toFixed(1)}%`
            } tone={!isRunning && delta >= 0 ? 'text-emerald-700' : !isRunning ? 'text-red-700' : 'text-stone-500'} />
            <Stat label="Δ"      value={
              isRunning ? '—'
              : `${delta >= 0 ? '+' : ''}${(delta * 100).toFixed(1)}pp`
            } tone={!isRunning && delta > 0 ? 'text-emerald-700' : !isRunning && delta < 0 ? 'text-red-700' : 'text-stone-500'} />
          </div>
        </div>
        {splits && (
          <div className="mt-2 font-mono-editorial text-stone-500 text-xs">
            {splits.n_train} train · {splits.n_val} val · {splits.n_test} test
          </div>
        )}
        <AuditBadge run={run} />
      </div>

      {/* Live progress strip */}
      {isRunning && (
        <LiveStrip run={run} budget={budget} progressPct={progressPct}
                   currentRound={currentRound} traj={traj} />
      )}

      {/* Cards row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 p-3">
        <Card title="Trajectory">
          {traj.length >= 1 ? (
            <div className="space-y-3">
              <div style={{ width: '100%', height: 200 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={traj.map((t: any) => ({
                      round: t.round,
                      acc: typeof t.val_acc === 'number' ? t.val_acc * 100 : null,
                      f1:  typeof t.val_macro_f1 === 'number' ? t.val_macro_f1 * 100 : null,
                    }))}
                    margin={{ top: 4, right: 8, left: 0, bottom: 4 }}
                  >
                    <CartesianGrid strokeDasharray="2 4" stroke="#E5E2D9" />
                    <XAxis dataKey="round" type="number" domain={[0, 'dataMax']} tick={{ fontSize: 10, fill: '#9A968F' }} stroke="#D6D2C8" allowDecimals={false} />
                    <YAxis
                      domain={zoomedYDomain(traj)}
                      tick={{ fontSize: 10, fill: '#9A968F' }}
                      stroke="#D6D2C8"
                      tickFormatter={(v) => `${v}%`}
                      width={42}
                    />
                    <Tooltip contentStyle={{ fontSize: 11 }} formatter={(v: any) => typeof v === 'number' ? `${v.toFixed(1)}%` : '—'} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    <Line type="monotone" dataKey="acc" name="Val acc"  stroke="#0B0B0A" strokeWidth={2} dot={{ r: 2 }} connectNulls isAnimationActive={!isRunning} />
                    <Line type="monotone" dataKey="f1"  name="Val F1"   stroke="#6E4FBE" strokeWidth={2} strokeDasharray="4 3" dot={{ r: 2 }} connectNulls isAnimationActive={!isRunning} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {/* Compact round-by-round list — shows every action including
                  val_consolidation and demos_appended after the run finishes. */}
              <ul className="text-xs font-mono divide-y divide-seam border-t border-seam max-h-40 overflow-auto">
                {traj.map((t: any, i: number) => (
                  <li key={i} className="flex items-baseline gap-2 px-1 py-1">
                    <span className="font-mono-editorial text-stone-400 w-10 shrink-0">r{t.round}</span>
                    <span className={
                      t.action === 'accept' || t.action === 'baseline' || t.action === 'baseline_seeded' || t.action === 'converged'
                        ? 'text-emerald-700'
                      : t.action === 'rollback' ? 'text-amber-700'
                      : t.action === 'val_consolidation' || t.action === 'demos_appended' ? 'text-violet-700'
                      : 'text-stone-600'
                    }>
                      {humanAction(t.action)}
                    </span>
                    <span className="ml-auto text-stone-500 flex gap-3">
                      {typeof t.val_acc === 'number' && <span>{(t.val_acc * 100).toFixed(1)}%</span>}
                      {typeof t.n_rules === 'number' && <span>· {t.n_rules} rules</span>}
                      {typeof t.n_failures === 'number' && <span>· {t.n_failures} fails</span>}
                      {typeof t.n_demos === 'number' && t.n_demos > 0 && <span>· {t.n_demos} demos</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : isRunning
            ? <SkeletonChart label="Scoring baseline on val…" />
            : <Empty>Not enough rounds.</Empty>}
        </Card>

        <Card title="Per-class · test">
          {test?.final_metrics
            ? <PerClassMini initial={test.initial_metrics} final={test.final_metrics} />
            : isRunning
              ? <SkeletonTable label={`Held-out test scored once after round ${budget}.`} />
              : <Empty>{test ? 'Old run — no per-class.' : 'Test eval pending.'}</Empty>}
        </Card>

        <Card title={`Rule library · ${ruleLib.length}`} className="md:col-span-2">
          {ruleLib.length === 0
            ? isRunning
              ? <SkeletonRules label="Rules accumulate as the optimizer mines failures from train each round." />
              : <Empty>No rules yet.</Empty>
            : <div className="space-y-2 max-h-56 overflow-auto pr-2">
                {ruleLib.map((r: any, i: number) => (
                  <div key={i} className="pl-3 border-l-2 border-violet-300">
                    <div className="font-mono-editorial text-stone-400 text-[11px]">
                      {String(i + 1).padStart(2, '0')} · {r.id || 'unnamed'}
                      {r.target_labels?.length ? ` · ${r.target_labels.join(' / ')}` : ''}
                    </div>
                    <div className="text-sm">{r.boundary || r.rule || '(no boundary)'}</div>
                  </div>
                ))}
              </div>
          }
        </Card>
      </div>

      {/* Editable prompt */}
      {run.optimized_prompt && (
        <EditablePromptV2 run={run} projectId={projectId} onUpdate={onUpdate} />
      )}
    </div>
  )
}

function LivePulse() {
  return (
    <span className="inline-flex items-center gap-1.5 px-1.5 py-0.5 border border-blue-300 bg-blue-50 text-blue-700 text-[10px] font-mono tracking-wider uppercase">
      <span className="relative inline-flex w-1.5 h-1.5">
        <span className="absolute inline-flex w-full h-full rounded-full bg-blue-500 opacity-75 animate-ping" />
        <span className="relative inline-flex w-1.5 h-1.5 rounded-full bg-blue-600" />
      </span>
      live
    </span>
  )
}

function Spinner() {
  return (
    <span className="inline-block w-3 h-3 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
  )
}

/** Phase texts that cycle while the optimizer is working a round.
    Picked based on the LATEST trajectory action so the message tracks
    where we actually are in the loop. */
function phasesForRound(currentRound: number, budget: number, lastAction?: string): string[] {
  if (lastAction === 'val_consolidation') {
    return [
      'picking worked examples from train + val',
      'evaluating final prompt on held-out test',
      'computing per-class metrics',
      'almost done',
    ]
  }
  if (currentRound >= budget) {
    return [
      'mining val failures (consolidation pass)',
      'distilling val rules',
      'preparing held-out test eval',
    ]
  }
  if (currentRound === 0 || lastAction === undefined) {
    return [
      'scoring baseline on val',
      'measuring initial accuracy',
    ]
  }
  // Most likely sequence inside an in-flight round (after round currentRound completed).
  return [
    `annotating ${currentRound === 0 ? 'train' : `train for round ${currentRound + 1}`}`,
    'identifying failure cases',
    'distilling rules from failures',
    'deduping near-duplicate rules',
    'evaluating candidate prompt on val',
    'governor deciding accept / rollback',
  ]
}

function LiveStrip({
  run, budget, progressPct, currentRound, traj,
}: {
  run: OptimizerRun
  budget: number
  progressPct: number
  currentRound: number
  traj: any[]
}) {
  const lastAction = traj[traj.length - 1]?.action as string | undefined
  const phases = phasesForRound(currentRound, budget, lastAction)
  const [phaseIdx, setPhaseIdx] = useState(0)
  const [tick, setTick] = useState(0)
  const startTime = useRef(Date.now())
  const lastRoundRef = useRef(currentRound)

  // Reset phase when a new round lands.
  useEffect(() => {
    if (lastRoundRef.current !== currentRound) {
      lastRoundRef.current = currentRound
      setPhaseIdx(0)
      startTime.current = Date.now()
    }
  }, [currentRound])

  // Cycle through phases every 2.4s for that "thinking…" feel.
  useEffect(() => {
    const i = setInterval(() => setPhaseIdx(p => (p + 1) % phases.length), 2400)
    return () => clearInterval(i)
  }, [phases.length])

  // Tick once per second so elapsed-time text updates.
  useEffect(() => {
    const i = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(i)
  }, [])

  const elapsed = Math.floor((Date.now() - startTime.current) / 1000)
  const elapsedStr = elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`

  return (
    <div className="px-5 py-3 border-b border-seam bg-gradient-to-b from-blue-50/60 to-transparent">
      {/* Action line — spinner + animated phase text */}
      <div className="flex items-center gap-3 mb-2">
        <Spinner />
        <PhaseLine text={phases[phaseIdx]} />
        <span className="ml-auto font-mono-editorial text-stone-500 text-xs">
          {elapsedStr} elapsed · {(run.total_tokens || 0).toLocaleString()} tokens · ${(run.total_cost || 0).toFixed(4)}
        </span>
      </div>

      {/* Round counter + progress bar */}
      <div className="flex items-center justify-between mb-1.5 text-xs font-mono-editorial">
        <span className="text-blue-700">Round {currentRound} / {budget}</span>
        <span className="text-stone-500">{Math.round(progressPct)}%</span>
      </div>
      <div className="w-full h-[3px] bg-seam overflow-hidden relative">
        <div
          className="h-full bg-blue-600 transition-all duration-700 relative"
          style={{ width: `${progressPct}%` }}
        >
          {/* Shimmer at the leading edge of the bar */}
          <div className="absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-r from-transparent to-blue-300 animate-pulse" />
        </div>
      </div>

      {/* Streaming trajectory rows */}
      {traj.length > 0 && (
        <ul className="mt-3 space-y-0.5 text-xs font-mono">
          {traj.slice(-4).map((t: any, i: number) => (
            <li
              key={`${t.round}-${i}`}
              className="flex items-baseline gap-2 animate-[fadeIn_300ms_ease-out]"
              style={{ animationDelay: `${i * 30}ms` }}
            >
              <span className="font-mono-editorial text-stone-400 w-12 shrink-0">r{t.round}</span>
              <span className={
                t.action === 'accept' || t.action === 'baseline' || t.action === 'baseline_seeded'
                  ? 'text-emerald-700'
                : t.action === 'rollback' ? 'text-amber-700'
                : t.action === 'demos_appended' ? 'text-violet-700'
                : t.action === 'val_consolidation' ? 'text-violet-700'
                : 'text-stone-600'
              }>
                {humanAction(t.action)}
              </span>
              <span className="text-stone-500 ml-auto">
                {typeof t.val_acc === 'number' ? `${(t.val_acc * 100).toFixed(1)}%` : '…'}
                {typeof t.n_rules === 'number' && <span className="ml-2">· {t.n_rules} rules</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Animated phase text — fades + slides between values. */
function PhaseLine({ text }: { text: string }) {
  return (
    <span
      key={text}
      className="text-sm font-medium text-blue-900 animate-[fadeSlide_400ms_ease-out]"
    >
      {text}…
    </span>
  )
}

function SkeletonChart({ label }: { label: string }) {
  return (
    <div className="relative w-full" style={{ height: 200 }}>
      <div className="absolute inset-0 flex flex-col justify-end gap-1 p-2">
        {[60, 40, 75, 35, 55].map((w, i) => (
          <div key={i} className="h-1.5 bg-stone-200 rounded animate-pulse" style={{ width: `${w}%`, animationDelay: `${i * 100}ms` }} />
        ))}
      </div>
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="font-mono-editorial text-stone-500 text-xs flex items-center gap-2">
          <span className="inline-block w-1 h-1 rounded-full bg-blue-500 animate-pulse" />
          {label}
        </div>
      </div>
    </div>
  )
}

function SkeletonTable({ label }: { label: string }) {
  return (
    <div className="space-y-2">
      {[80, 60, 70, 55].map((w, i) => (
        <div key={i} className="flex items-center gap-2">
          <div className="h-2 w-12 bg-stone-200 rounded animate-pulse" style={{ animationDelay: `${i * 80}ms` }} />
          <div className="h-2 bg-stone-200 rounded animate-pulse" style={{ width: `${w}%`, animationDelay: `${i * 80 + 40}ms` }} />
        </div>
      ))}
      <div className="pt-2 font-mono-editorial text-stone-500 text-xs">{label}</div>
    </div>
  )
}

function SkeletonRules({ label }: { label: string }) {
  return (
    <div className="space-y-3">
      {[0, 1].map(i => (
        <div key={i} className="pl-3 border-l-2 border-stone-200 space-y-1.5">
          <div className="h-2 w-32 bg-stone-200 rounded animate-pulse" style={{ animationDelay: `${i * 120}ms` }} />
          <div className="h-2 bg-stone-200 rounded animate-pulse" style={{ width: '85%', animationDelay: `${i * 120 + 60}ms` }} />
          <div className="h-2 bg-stone-200 rounded animate-pulse" style={{ width: '70%', animationDelay: `${i * 120 + 120}ms` }} />
        </div>
      ))}
      <p className="pt-1 text-xs text-stone-500 leading-relaxed">{label}</p>
    </div>
  )
}

/** Tight y-domain for the trajectory chart so small per-round deltas are
    visible. Pads +/- 4pp around the data range, with a 12pp minimum span,
    and clamps to [0, 100]. Returns ['auto', 'auto'] if the trajectory is
    empty. */
function zoomedYDomain(traj: any[]): [number, number] | ['auto', 'auto'] {
  const vals: number[] = []
  for (const t of traj) {
    if (typeof t?.val_acc === 'number') vals.push(t.val_acc * 100)
    if (typeof t?.val_macro_f1 === 'number') vals.push(t.val_macro_f1 * 100)
  }
  if (vals.length === 0) return ['auto', 'auto']
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const span = hi - lo
  const pad = Math.max(4, span * 0.15)
  const minSpan = 12
  let yLo = Math.max(0, lo - pad)
  let yHi = Math.min(100, hi + pad)
  if (yHi - yLo < minSpan) {
    const mid = (yHi + yLo) / 2
    yLo = Math.max(0, mid - minSpan / 2)
    yHi = Math.min(100, mid + minSpan / 2)
  }
  // Snap to nearest 5 for clean tick labels.
  yLo = Math.max(0, Math.floor(yLo / 5) * 5)
  yHi = Math.min(100, Math.ceil(yHi / 5) * 5)
  return [yLo, yHi]
}

function humanAction(action: string | undefined): string {
  switch (action) {
    case 'baseline':           return 'baseline scored'
    case 'baseline_seeded':    return 'seeded from memory'
    case 'accept':             return 'rule accepted'
    case 'rollback':           return 'rolled back'
    case 'no_new_rules':       return 'no new rules'
    case 'converged':          return 'converged · no failures'
    case 'val_consolidation':  return 'val consolidated into rules'
    case 'demos_appended':     return 'worked examples added'
    default:                   return action || '—'
  }
}

function AuditBadge({ run }: { run: OptimizerRun }) {
  const a = (run.artifact as any)?.audit as
    | { clean?: boolean; val_leak_count?: number; test_leak_count?: number; checked_val?: number; checked_test?: number; val_samples?: string[]; test_samples?: string[] }
    | undefined
  if (!a) return null
  if (a.clean) {
    return (
      <div className="mt-2 inline-flex items-center gap-2 text-[11px] font-mono-editorial text-emerald-700">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
        leakage audit · clean · checked {a.checked_val} val + {a.checked_test} test
      </div>
    )
  }
  return (
    <details className="mt-2 border border-red-200 bg-red-50/60 px-3 py-1.5 text-xs">
      <summary className="font-mono-editorial text-red-700 cursor-pointer">
        leakage audit · FAILED · {a.val_leak_count} val + {a.test_leak_count} test sentences appear in prompt
      </summary>
      <div className="mt-2 space-y-1 text-stone-700">
        {(a.val_samples || []).map((s, i) => <div key={`v${i}`}><span className="font-mono-editorial text-red-700 mr-1">val:</span>{s}</div>)}
        {(a.test_samples || []).map((s, i) => <div key={`t${i}`}><span className="font-mono-editorial text-red-700 mr-1">test:</span>{s}</div>)}
      </div>
    </details>
  )
}

function PerClassMini({ initial, final }: { initial: any; final: any }) {
  const labels: string[] = (final?.classes ?? Object.keys(final?.per_class || {})).slice().sort()
  return (
    <div className="text-xs font-mono">
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 mb-2">
        <Stat label="Macro F1" value={`${(initial.macro_f1 * 100).toFixed(0)}% → ${(final.macro_f1 * 100).toFixed(0)}%`} />
        <Stat label="Weighted F1" value={`${(initial.weighted_f1 * 100).toFixed(0)}% → ${(final.weighted_f1 * 100).toFixed(0)}%`} />
      </div>
      <table className="w-full">
        <thead><tr className="border-b border-seam text-stone-500 font-mono-editorial">
          <th className="text-left py-1">label</th>
          <th className="text-right py-1">supp</th>
          <th className="text-right py-1">F1 i→f</th>
        </tr></thead>
        <tbody className="divide-y divide-seam">
          {labels.map(l => {
            const i = initial?.per_class?.[l], f = final?.per_class?.[l]
            const d = (f?.f1 ?? 0) - (i?.f1 ?? 0)
            return (
              <tr key={l}>
                <td className="py-1 truncate max-w-[140px]" title={l}>{l}</td>
                <td className="py-1 text-right text-stone-600">{f?.support ?? 0}</td>
                <td className="py-1 text-right">
                  <span className="text-stone-600">{((i?.f1 ?? 0) * 100).toFixed(0)}</span>
                  <span className="text-stone-300 mx-1">→</span>
                  <span className={d > 0 ? 'text-emerald-700' : d < 0 ? 'text-red-600' : 'text-stone-700'}>
                    {((f?.f1 ?? 0) * 100).toFixed(0)}
                  </span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function EditablePromptV2({
  run, projectId, onUpdate,
}: { run: OptimizerRun; projectId: number; onUpdate: (r: OptimizerRun) => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(run.optimized_prompt)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')
  const [tracked, setTracked] = useState(run.id)
  if (tracked !== run.id) { setTracked(run.id); setDraft(run.optimized_prompt); setEditing(false); setErr('') }
  const dirty = draft !== run.optimized_prompt
  const editable = run.status === 'completed' || run.status === 'failed'

  const save = async () => {
    setSaving(true); setErr('')
    try {
      const updated = await patchOptimizerRun(projectId, run.id, { optimized_prompt: draft })
      onUpdate(updated); setEditing(false)
    } catch (e: any) { setErr(e?.response?.data?.detail || e?.message || 'Save failed') }
    finally { setSaving(false) }
  }

  return (
    <div className="px-3 pb-3">
      <Card title="Updated prompt" rightSlot={
        <div className="flex items-center gap-2">
          {dirty && <span className="font-mono-editorial text-amber-700 text-[11px]">unsaved</span>}
          {!editing && editable && <button onClick={() => setEditing(true)} className="font-mono-editorial text-stone-500 hover:text-ink">edit</button>}
          {editing && (
            <>
              <button onClick={() => { setDraft(run.optimized_prompt); setEditing(false); setErr('') }} disabled={saving} className="font-mono-editorial text-stone-500 hover:text-ink">cancel</button>
              <button onClick={save} disabled={saving || !dirty} className="px-2 py-0.5 text-xs bg-ink text-cream disabled:opacity-40">{saving ? 'saving…' : 'save'}</button>
            </>
          )}
        </div>
      }>
        {editing ? (
          <textarea value={draft} onChange={e => setDraft(e.target.value)} rows={Math.min(28, Math.max(10, draft.split('\n').length + 1))}
                    className="w-full bg-white border border-seam focus:border-ink focus:outline-none p-3 font-mono text-xs leading-relaxed resize-y" />
        ) : (
          <pre className="bg-paper/50 border border-seam p-3 font-mono text-xs leading-relaxed max-h-72 overflow-auto whitespace-pre-wrap">{run.optimized_prompt}</pre>
        )}
        {err && <div className="mt-2 text-xs text-red-700">{err}</div>}
      </Card>
    </div>
  )
}

/* ─── Memory tab ────────────────────────────────────────────── */

function MemoryTab({ memory, projectId, dimensions, onRefresh }: {
  memory: MemoryVersion[]
  projectId: number
  dimensions: string[]
  onRefresh: () => void
}) {
  const byDim: Record<string, MemoryVersion[]> = {}
  for (const v of memory) {
    if (!byDim[v.dimension_name]) byDim[v.dimension_name] = []
    byDim[v.dimension_name].push(v)
  }

  // All known dimensions: those with memory + those from the codebook that don't yet
  const allDims = Array.from(new Set([...Object.keys(byDim), ...dimensions])).sort()

  if (allDims.length === 0) {
    return <Empty>Memory accumulates after each successful run.</Empty>
  }

  return (
    <div className="space-y-5">
      {allDims.map(d => (
        <div key={d}>
          <div className="flex items-baseline justify-between border-b border-seam pb-1.5 mb-2">
            <h3 className="text-base font-medium">{d}</h3>
            {byDim[d]
              ? <span className="font-mono-editorial text-stone-500">latest v{String(byDim[d][0].version).padStart(3, '0')} · {byDim[d][0].n_rules} rules</span>
              : <span className="font-mono-editorial text-stone-400">no rules yet</span>
            }
          </div>
          {byDim[d] && (
            <ul className="divide-y divide-seam">
              {byDim[d].map(v => <MemRow key={v.id} v={v} />)}
            </ul>
          )}
          <div className="flex items-start gap-4 mt-2">
            <FeedbackForm projectId={projectId} dimensionName={d} onDone={onRefresh} />
            <ApplyPanel projectId={projectId} dimensionName={d} hasRules={!!byDim[d]} />
          </div>
        </div>
      ))}
    </div>
  )
}

function FeedbackForm({ projectId, dimensionName, onDone }: {
  projectId: number
  dimensionName: string
  onDone: () => void
}) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async () => {
    if (!text.trim()) return
    setLoading(true)
    setError('')
    try {
      await submitMemoryFeedback(projectId, dimensionName, text.trim())
      setText('')
      setOpen(false)
      onDone()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="mt-2 font-mono-editorial text-xs text-stone-400 hover:text-ink"
      >
        + add correction
      </button>
    )
  }

  return (
    <div className="mt-3 border border-seam bg-paper/30 p-3 space-y-2">
      <Label>Describe what the model is getting wrong for <em>{dimensionName}</em></Label>
      <textarea
        autoFocus
        value={text}
        onChange={e => setText(e.target.value)}
        rows={3}
        className="w-full text-sm bg-transparent border border-seam p-2 resize-none focus:outline-none focus:border-ink"
        placeholder="e.g. the model keeps labelling past-tense experiences as High when they should be Low"
      />
      {error && <p className="font-mono-editorial text-xs text-red-600">{error}</p>}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSubmit}
          disabled={loading || !text.trim()}
          className="px-3 py-1.5 bg-ink text-cream text-xs font-medium disabled:opacity-40"
        >
          {loading ? 'Applying…' : 'Apply feedback'}
        </button>
        <button onClick={() => { setOpen(false); setText(''); setError('') }} className="font-mono-editorial text-xs text-stone-400 hover:text-ink">
          Cancel
        </button>
      </div>
    </div>
  )
}

type ApplyState = 'idle' | 'loading' | 'preview' | 'committing' | 'done' | 'error'

function ApplyPanel({ projectId, dimensionName, hasRules }: { projectId: number; dimensionName: string; hasRules: boolean }) {
  const [state, setState] = useState<ApplyState>('idle')
  const [oldPrompt, setOldPrompt] = useState('')
  const [newPrompt, setNewPrompt] = useState('')
  const [error, setError] = useState('')

  const handlePreview = async () => {
    setState('loading')
    setError('')
    try {
      const res = await previewPrompt(projectId, dimensionName)
      setOldPrompt(res.old_prompt)
      setNewPrompt(res.new_prompt)
      setState('preview')
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Preview failed')
      setState('error')
    }
  }

  const handleCommit = async () => {
    setState('committing')
    try {
      await commitPrompt(projectId, dimensionName, newPrompt)
      setState('done')
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Commit failed')
      setState('error')
    }
  }

  const reset = () => { setState('idle'); setOldPrompt(''); setNewPrompt(''); setError('') }

  if (state === 'idle') {
    return (
      <button
        onClick={handlePreview}
        disabled={!hasRules}
        title={!hasRules ? 'Add feedback first to build rules' : undefined}
        className="font-mono-editorial text-xs text-violet-600 hover:text-violet-800 disabled:text-stone-300 disabled:cursor-not-allowed"
      >
        ↑ apply to prompt
      </button>
    )
  }

  if (state === 'loading') {
    return <span className="font-mono-editorial text-xs text-stone-400">Generating preview…</span>
  }

  if (state === 'done') {
    return <span className="font-mono-editorial text-xs text-emerald-600">✓ Prompt updated</span>
  }

  if (state === 'error') {
    return (
      <span className="font-mono-editorial text-xs text-red-600">
        {error} · <button onClick={reset} className="underline">retry</button>
      </span>
    )
  }

  // preview or committing
  return (
    <div className="mt-3 w-full border border-violet-200 bg-paper/30 p-3 space-y-3">
      <div className="font-mono-editorial text-xs text-stone-500 mb-1">
        Prompt diff for <em>{dimensionName}</em> — review before applying
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="font-mono-editorial text-[11px] text-stone-400 mb-1">Current prompt</div>
          <pre className="text-xs whitespace-pre-wrap bg-stone-50 border border-seam p-2 max-h-64 overflow-y-auto">{oldPrompt}</pre>
        </div>
        <div>
          <div className="font-mono-editorial text-[11px] text-violet-600 mb-1">Updated prompt</div>
          <pre className="text-xs whitespace-pre-wrap bg-violet-50 border border-violet-200 p-2 max-h-64 overflow-y-auto">{newPrompt}</pre>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <button
          onClick={handleCommit}
          disabled={state === 'committing'}
          className="px-3 py-1.5 bg-violet-700 text-white text-xs font-medium disabled:opacity-40"
        >
          {state === 'committing' ? 'Saving…' : 'Confirm & apply'}
        </button>
        <button onClick={reset} className="font-mono-editorial text-xs text-stone-400 hover:text-ink">
          Cancel
        </button>
      </div>
    </div>
  )
}

function MemRow({ v }: { v: MemoryVersion }) {
  const [open, setOpen] = useState(false)
  return (
    <li>
      <button onClick={() => setOpen(o => !o)}
              className="w-full grid grid-cols-12 gap-3 py-2 px-1 text-left hover:bg-paper/40 text-xs font-mono">
        <span className="col-span-1 text-stone-400">{open ? '−' : '+'}</span>
        <span className="col-span-2">v{String(v.version).padStart(3, '0')}</span>
        <span className="col-span-2 text-stone-700">{v.n_rules} rules</span>
        <span className="col-span-2 text-stone-500">{v.new_rules_count > 0 ? `+${v.new_rules_count}` : '—'}</span>
        <span className="col-span-3 text-stone-500">{v.source_optimizer_run_id !== null ? `run ${String(v.source_optimizer_run_id).padStart(4, '0')}` : 'manual'}</span>
        <span className="col-span-2 text-right text-stone-400">{v.created_at ? new Date(v.created_at).toLocaleDateString() : '—'}</span>
      </button>
      {open && (
        <div className="px-1 pb-3 space-y-2">
          {v.rules.map((r, i) => (
            <div key={i} className="pl-3 border-l-2 border-violet-300 text-xs">
              <div className="font-mono-editorial text-stone-400">{String(i + 1).padStart(2, '0')} · {r.id || 'unnamed'}</div>
              <div>{r.boundary || r.rule || '(no boundary)'}</div>
            </div>
          ))}
        </div>
      )}
    </li>
  )
}

/* ─── Tiny primitives ───────────────────────────────────────── */

function Card({
  title, children, rightSlot, className = '',
}: { title: string; children: React.ReactNode; rightSlot?: React.ReactNode; className?: string }) {
  return (
    <div className={`border border-seam bg-paper/30 ${className}`}>
      <div className="flex items-baseline justify-between px-3 py-2 border-b border-seam">
        <span className="font-mono-editorial text-stone-500 text-xs">{title}</span>
        {rightSlot}
      </div>
      <div className="p-3">{children}</div>
    </div>
  )
}

function Stat({ label, value, tone = 'text-ink' }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <div className="font-mono-editorial text-stone-500 text-[11px]">{label}</div>
      <div className={`font-mono text-sm mt-0.5 ${tone}`}>{value}</div>
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <span className="font-mono-editorial text-stone-500 block mb-1 text-xs">{children}</span>
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="border border-dashed border-seam bg-paper/30 p-6 text-center text-sm text-stone-500">
      {children}
    </div>
  )
}
