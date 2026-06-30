import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Legend,
} from 'recharts'
import api, {
  listAvailableOptimizers, listOptimizerRuns, startOptimizerRun, getOptimizerRun,
  listCodebooks, listDatasets, autoGeneratePrompt, patchOptimizerRun,
  listJobs, getFeedbackEvidence, listPipelines, startJob, uploadDataset,
  listMemoryVersions, deleteOptimizerRun, cancelOptimizerRun,
  previewFeedbackBatch, commitFeedbackBatch, deleteMemoryVersion, commitPrompt,
  type OptimizerInfo, type OptimizerRun, type AutoPromptResponse, type MemoryVersion, type MemoryRule, type FeedbackEvidence,
} from '../lib/api'
import type { Codebook, Dataset, Job, Pipeline } from '../types'
import StructureDiagram from '../components/StructureDiagram'
import { APP_NAME } from '../lib/brand'

type Tab = 'prompts' | 'improve' | 'runs' | 'memory'
const TABS: Tab[] = ['prompts', 'improve', 'runs', 'memory']

function parseTab(value: string | null): Tab {
  return TABS.includes(value as Tab) ? value as Tab : 'prompts'
}

function fmtError(e: any): string {
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (d?.message) return String(d.message)
  if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg)
  return e?.message || 'Unknown error'
}

function normDimensionName(value: string): string {
  return value.trim().replace(/\s+/g, ' ').toLowerCase()
}

function normLabelName(value: string): string {
  return value.trim().replace(/\s+/g, ' ').toLowerCase()
}

function normStatus(value: string): string {
  return String(value || '').toLowerCase()
}

export default function PromptLabV2() {
  const { id } = useParams<{ id: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const projectId = Number(id)

  const [tab, setTab] = useState<Tab>(() => parseTab(searchParams.get('tab')))
  const [codebooks, setCodebooks] = useState<Codebook[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [runs, setRuns] = useState<OptimizerRun[]>([])
  const [optimizers, setOptimizers] = useState<OptimizerInfo[]>([])
  const [memory, setMemory] = useState<MemoryVersion[]>([])
  const [jobs, setJobs] = useState<Job[]>([])
  const [pipelines, setPipelines] = useState<Pipeline[]>([])

  const [autoPrompt, setAutoPrompt] = useState<AutoPromptResponse | null>(null)
  const [autoPromptLoading, setAutoPromptLoading] = useState(false)
  const [autoPromptError, setAutoPromptError] = useState('')
  const [preparingAnnotation, setPreparingAnnotation] = useState(false)

  // Improve tab state
  const [selectedDim, setSelectedDim] = useState('')
  const [selectedGold, setSelectedGold] = useState<number | null>(null)
  const [selectedOptimizer, setSelectedOptimizer] = useState('reflect_agent')
  const [budget, setBudget] = useState(5)
  const [launching, setLaunching] = useState(false)
  const [launchError, setLaunchError] = useState('')

  // Runs master-detail. A `?run=<id>` param deep-links a run so it can be
  // bookmarked or shared (and opens it directly on load).
  const [selectedRunId, setSelectedRunId] = useState<number | null>(() => {
    const r = searchParams.get('run')
    return r ? Number(r) : null
  })
  const [selectedRun, setSelectedRun] = useState<OptimizerRun | null>(null)

  const activeCb = codebooks[codebooks.length - 1]

  const handleTabChange = (next: Tab) => {
    setTab(next)
    setSearchParams(prev => {
      const p = new URLSearchParams(prev)
      p.set('tab', next)
      return p
    }, { replace: true })
  }

  // Select a run and reflect it in the URL (?tab=runs&run=<id>) so the view is
  // shareable and survives a reload.
  const selectRun = (id: number | null) => {
    setSelectedRunId(id)
    setTab('runs')
    setSearchParams(prev => {
      const p = new URLSearchParams(prev)
      p.set('tab', 'runs')
      if (id == null) p.delete('run'); else p.set('run', String(id))
      return p
    }, { replace: true })
  }

  const latestPipeline = pipelines.slice().sort((a, b) => b.id - a.id)[0] ?? null

  const pipelinePromptForDimension = (dimensionName: string): string => {
    const step = (latestPipeline?.steps || []).find((s: any) =>
      normDimensionName(s?.name || '') === normDimensionName(dimensionName)
      || (Array.isArray(s?.dimensions) && s.dimensions.some((d: string) => normDimensionName(d) === normDimensionName(dimensionName)))
    )
    return String((step as any)?.prompt || '')
  }

  const completedRunsForDimension = (dimensionName: string) => runs.filter(run =>
    normDimensionName(run.dimension_name) === normDimensionName(dimensionName)
    && normStatus(run.status) === 'completed'
    && !!run.optimized_prompt
  ).sort((a, b) => b.id - a.id)

  const selectedPromptForAnnotation = (dimensionName: string, startingPrompt: string): string => {
    const completed = completedRunsForDimension(dimensionName)
    const appliedPrompt = pipelinePromptForDimension(dimensionName).trim()
    const appliedRun = completed.find(run => appliedPrompt && run.optimized_prompt.trim() === appliedPrompt)
    return appliedRun?.optimized_prompt ?? completed[0]?.optimized_prompt ?? (appliedPrompt || startingPrompt)
  }

  const bestRunByDimension = () => {
    const byDim: Record<string, OptimizerRun> = {}
    const completed = runs.filter(run =>
      normStatus(run.status) === 'completed'
      && !!run.optimized_prompt
    )

    for (const run of completed) {
      const appliedPrompt = pipelinePromptForDimension(run.dimension_name).trim()
      if (!appliedPrompt || appliedPrompt !== run.optimized_prompt.trim()) continue
      const key = normDimensionName(run.dimension_name)
      if (!byDim[key] || run.id > byDim[key].id) byDim[key] = run
    }

    for (const run of runs) {
      if (normStatus(run.status) !== 'completed' || !run.optimized_prompt) continue
      const key = normDimensionName(run.dimension_name)
      if (byDim[key]) continue
      byDim[key] = run
    }
    return byDim
  }

  const refreshPipelines = () => listPipelines(projectId).then(setPipelines).catch(() => setPipelines([]))

  const handleAnnotateWithBestPrompts = async () => {
    setPreparingAnnotation(true)
    try {
      const promptsToApply = autoPrompt?.prompts ?? []
      if (promptsToApply.length > 0) {
        await Promise.all(promptsToApply.map(prompt =>
          commitPrompt(
            projectId,
            prompt.dimension_name,
            selectedPromptForAnnotation(prompt.dimension_name, prompt.prompt),
          )
        ))
      } else {
        const latestRuns = bestRunByDimension()
        await Promise.all(Object.values(latestRuns).map(run =>
          commitPrompt(projectId, run.dimension_name, run.optimized_prompt)
        ))
      }
      await refreshPipelines()
      navigate(`/projects/${projectId}/pipeline`)
    } catch (e: any) {
      alert(`Could not prepare prompts for annotation: ${fmtError(e)}`)
    } finally {
      setPreparingAnnotation(false)
    }
  }

  useEffect(() => {
    Promise.all([
      listAvailableOptimizers(projectId),
      listCodebooks(projectId),
      listDatasets(projectId),
      listOptimizerRuns(projectId),
      listJobs(projectId),
      listPipelines(projectId),
    ]).then(([opts, cbs, dss, rs, js, ps]) => {
      setOptimizers(opts); setCodebooks(cbs); setDatasets(dss); setRuns(rs)
      setJobs(js)
      setPipelines(ps)
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

  useEffect(() => {
    if (tab !== 'memory') return
    listJobs(projectId).then(setJobs).catch(() => setJobs([]))
  }, [tab, projectId])

  // Auto-prompt cache
  const autoPromptCacheKey = activeCb ? `annotagent.autoPrompt.${projectId}.${activeCb.id}` : null
  useEffect(() => {
    if (!activeCb || !autoPromptCacheKey || autoPrompt) return
    // Only trust a cached entry if its prompts match the CURRENT codebook's
    // dimensions. Codebook ids can be reused (e.g. after a local DB reset), so a
    // stale entry can collide on the same key and surface another codebook's
    // prompts; validating dimension names prevents that.
    const codebookDims = new Set(activeCb.dimensions.map(d => d.name))
    try {
      const cached = localStorage.getItem(autoPromptCacheKey)
      if (cached) {
        const parsed = JSON.parse(cached)
        const dims: string[] = Array.isArray(parsed?.prompts)
          ? parsed.prompts.map((p: any) => p?.dimension_name) : []
        const matchesCodebook = dims.length > 0
          && dims.length === codebookDims.size
          && dims.every(n => codebookDims.has(n))
        if (matchesCodebook) { setAutoPrompt(parsed); return }
        localStorage.removeItem(autoPromptCacheKey)   // stale (codebook changed) — drop it
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

      <DemoWorkflowGuide />

      <div className="flex items-end justify-between gap-4 border-b border-seam" data-tour="lab-tabs">
        <Tabs value={tab} onChange={handleTabChange} items={[
          { id: 'prompts', label: 'Prompts',  count: autoPrompt?.prompts.length },
          { id: 'improve', label: 'Improve',                                     },
          { id: 'runs',    label: 'Runs',     count: runs.length                 },
          { id: 'memory',  label: 'Human feedback', count: memory.length          },
        ]} />
        {tab !== 'prompts' && (
          <button
            type="button"
            onClick={() => handleTabChange('prompts')}
            className="mb-2 shrink-0 px-4 py-2 bg-ink text-cream text-sm font-medium hover:bg-stone-800 transition"
          >
            Back to prompts
          </button>
        )}
      </div>

      {tab === 'prompts' && (
        <PromptsTab
          activeCb={activeCb}
          autoPrompt={autoPrompt}
          loading={autoPromptLoading}
          error={autoPromptError}
          runs={runs}
          projectId={projectId}
          pipelinePromptForDimension={pipelinePromptForDimension}
          onPipelinesRefresh={refreshPipelines}
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
          onJumpToRun={(id) => selectRun(id)}
          onContinue={() => handleTabChange('improve')}
          onHumanFeedback={() => handleTabChange('memory')}
          onAnnotate={handleAnnotateWithBestPrompts}
          preparingAnnotation={preparingAnnotation}
        />
      )}

      {tab === 'improve' && (
        <ImproveTab
          codebooks={codebooks}
          datasets={datasets}
          runs={runs}
          selectedDim={selectedDim} setSelectedDim={setSelectedDim}
          selectedGold={selectedGold} setSelectedGold={setSelectedGold}
          optimizers={optimizers}
          selectedOptimizer={selectedOptimizer}
          setSelectedOptimizer={setSelectedOptimizer}
          budget={budget} setBudget={setBudget}
          launching={launching} launchError={launchError}
          projectId={projectId}
          onLaunched={(run) => {
            setRuns([run, ...runs])
            selectRun(run.id)
          }}
          setLaunching={setLaunching} setLaunchError={setLaunchError}
        />
      )}

      {tab === 'runs' && (
        <RunsTab
          runs={runs}
          selectedRunId={selectedRunId}
          selectedRun={selectedRun}
          onSelect={selectRun}
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
          onPipelinesRefresh={refreshPipelines}
          pipelinePromptForDimension={pipelinePromptForDimension}
          onContinue={() => handleTabChange('memory')}
        />
      )}

      {tab === 'memory' && (
        <MemoryTab
          memory={memory}
          projectId={projectId}
          jobs={jobs}
          datasets={datasets}
          dimensions={activeCb?.dimensions.map(d => d.name) ?? []}
          pipelinePromptForDimension={pipelinePromptForDimension}
          onRefresh={() => listMemoryVersions(projectId).then(setMemory).catch(() => setMemory([]))}
          onJobsRefresh={() => listJobs(projectId).then(setJobs).catch(() => setJobs([]))}
          onDatasetsRefresh={() => listDatasets(projectId).then(setDatasets).catch(() => setDatasets([]))}
          onPromptCommitted={async () => {
            await Promise.all([
              refreshPipelines(),
              listMemoryVersions(projectId).then(setMemory).catch(() => setMemory([])),
            ])
            handleTabChange('prompts')
          }}
        />
      )}
    </div>
  )
}

/* ─── Tabs primitive ───────────────────────────────────────── */

function DemoWorkflowGuide() {
  return (
    <section className="border border-violet-200 bg-violet-50/70 px-4 py-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="font-medium text-violet-950">Suggested workflow</div>
          <p className="mt-1 max-w-4xl text-xs leading-relaxed text-violet-900/85">
            Treat <span className="font-medium">Prompts</span> as the hub. After Setup generates the pipeline, review the prompts here,
            then choose a next step based on what evidence you have.
          </p>
        </div>
        <div className="font-mono-editorial text-xs text-violet-700">route map</div>
      </div>
      <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-4">
        <WorkflowMiniStep
          n="01"
          title="Setup"
          body="Configure model, inspect the codebook, optionally upload labeled data, then generate the pipeline."
        />
        <WorkflowMiniStep
          n="02"
          title="Prompts"
          body="Review active prompts. You can edit, restore, apply an optimization run, or send prompts to annotation."
        />
        <WorkflowMiniStep
          n="03"
          title="Improve"
          body="Use labeled/gold examples first when available. Runs evaluate prompt changes before you apply them."
        />
        <WorkflowMiniStep
          n="04"
          title="Human feedback"
          body="Use after prompts have produced annotated examples. It is not the first step; create evidence first, then correct it."
        />
      </div>
      <p className="mt-3 border-l-2 border-violet-500 pl-3 text-xs leading-relaxed text-violet-950">
        After an improvement run, either apply the better prompt and return to Prompts, or continue to Human feedback to review concrete model outputs.
        After Human feedback applies a generated prompt, return to Prompts to confirm the active source before running large-scale annotation.
      </p>
    </section>
  )
}

function WorkflowMiniStep({ n, title, body }: { n: string; title: string; body: string }) {
  return (
    <div className="border border-violet-200 bg-white/80 px-3 py-2">
      <div className="flex items-baseline gap-2">
        <span className="font-mono-editorial text-[11px] text-violet-500">{n}</span>
        <span className="text-sm font-medium text-violet-950">{title}</span>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-stone-600">{body}</p>
    </div>
  )
}

function Tabs<T extends string>({
  value, onChange, items,
}: {
  value: T
  onChange: (v: T) => void
  items: { id: T; label: string; count?: number }[]
}) {
  return (
    <div className="flex">
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
  activeCb, autoPrompt, loading, error, runs, projectId, pipelinePromptForDimension, onPipelinesRefresh, onRegenerate, onJumpToRun, onContinue, onHumanFeedback, onAnnotate, preparingAnnotation,
}: {
  activeCb?: Codebook
  autoPrompt: AutoPromptResponse | null
  loading: boolean
  error: string
  runs: OptimizerRun[]
  projectId: number
  pipelinePromptForDimension: (dimensionName: string) => string
  onPipelinesRefresh: () => Promise<void>
  onRegenerate: () => void
  onJumpToRun: (runId: number) => void
  onContinue: () => void
  onHumanFeedback: () => void
  onAnnotate: () => void
  preparingAnnotation: boolean
}) {
  if (!activeCb) {
    return <Empty>Load a codebook on Setup first.</Empty>
  }
  if (loading && !autoPrompt) {
    return (
      <div data-tour="first-prompt" className="border border-seam bg-white p-8 text-center">
        <div className="flex items-center justify-center gap-2 mb-3">
          <span className="inline-block w-2 h-2 rounded-full bg-ink animate-pulse" />
          <span className="font-mono-editorial text-stone-600">CodebookAgent · drafting</span>
        </div>
        <h3 className="text-lg font-medium tracking-tight">Generating your starting prompts…</h3>
        <p className="mt-2 text-sm text-stone-600 max-w-md mx-auto leading-relaxed">
          {APP_NAME} is writing one prompt for each of your {activeCb.dimensions.length} codebook
          dimensions. This runs once and takes a few seconds.
        </p>
        <div className="mt-5 mx-auto max-w-xs h-1 overflow-hidden bg-paper">
          <div className="h-full w-1/3 bg-ink" style={{ animation: 'barShimmer 1.2s ease-in-out infinite' }} />
        </div>
      </div>
    )
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
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between mb-3">
        <div className="font-mono-editorial text-stone-500">
          {autoPrompt.prompts.length} prompts · {activeCb.name}
        </div>
        <div className="sm:text-right">
          <button onClick={onRegenerate} disabled={loading}
                  className="px-3 py-1.5 border border-ink bg-white text-ink text-xs font-medium hover:bg-paper disabled:opacity-50 transition">
            {loading ? 'Re-generating…' : 'Re-generate all'}
          </button>
          <p className="mt-1 text-xs text-stone-500 sm:whitespace-nowrap">
            Use this after changing the codebook, or if you want a fresh starting draft.
          </p>
        </div>
      </div>
      {(
        <details className="border border-indigo-200 bg-indigo-50/40 group" open>
          <summary className="cursor-pointer select-none list-none [&::-webkit-details-marker]:hidden px-3 py-2 flex items-center justify-between gap-2">
            <span className="font-mono-editorial text-indigo-800 text-xs flex items-center gap-1.5">
              <span className="transition-transform group-open:rotate-90" aria-hidden="true">▸</span>
              Prediction structure · improve earlier steps first
            </span>
            <span className="shrink-0 text-[11px] font-medium px-2 py-1 border border-indigo-300 rounded bg-white text-indigo-700 hover:bg-indigo-100">
              <span className="group-open:hidden">Show ▾</span>
              <span className="hidden group-open:inline">Hide ▴</span>
            </span>
          </summary>
          <div className="px-3 pb-3 space-y-3">
            <div className="bg-white border border-seam p-3">
              <StructureDiagram projectId={projectId} codebookId={activeCb.id} />
            </div>
            <p className="text-[11px] leading-relaxed text-indigo-900/80">
              Predicted as a cascade: each theme's level is predicted first, then Topics, then the thematic category — each
              step's available labels depend on the ones before it. Improve them in that order; a dependent step's run is
              blocked until its predecessors have a completed run.
            </p>
          </div>
        </details>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {autoPrompt.prompts.map((p, i) => {
          const completedRuns = runs.filter(r =>
            normDimensionName(r.dimension_name) === normDimensionName(p.dimension_name)
            && normStatus(r.status) === 'completed'
            && !!r.optimized_prompt
          ).sort((a, b) => b.id - a.id)
          const appliedPrompt = pipelinePromptForDimension(p.dimension_name).trim()
          const appliedRun = completedRuns.find(r => appliedPrompt && r.optimized_prompt.trim() === appliedPrompt)
          const optimized = appliedRun ?? completedRuns[0]
          return (
            <div key={p.dimension_name} data-tour={i === 0 ? 'first-prompt' : undefined}>
              <PromptCard
                dp={p}
                pipelinePrompt={appliedPrompt}
                optimizedRun={optimized}
                appliedRunId={appliedRun?.id ?? null}
                onJumpToRun={onJumpToRun}
                projectId={projectId}
                onPipelineSaved={onPipelinesRefresh}
              />
            </div>
          )
        })}
      </div>
      <div className="border-t border-seam pt-4">
        <div className="mb-3 border-l-2 border-ink bg-white px-3 py-2 text-sm font-medium text-stone-800">
          Choose the next step for these prompts.
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
          <NextStepButton
            title="📓 Improve with labeled data"
            description="Use existing correct labels to test and refine the prompts."
            onClick={onContinue}
            tone="violet"
          />
          <NextStepButton
            title="💬 Human feedback review"
            description="First create annotated examples, then write corrections and apply them back to prompts."
            onClick={onHumanFeedback}
            tone="sky"
          />
          <NextStepButton
            title={preparingAnnotation ? '🚀 Preparing prompts...' : '🚀 Use prompts for annotation'}
            description="Save the latest improved prompts and annotate your full dataset."
            onClick={onAnnotate}
            disabled={preparingAnnotation}
            tone="emerald"
          />
        </div>
      </div>
    </div>
  )
}

function NextStepButton({
  title,
  description,
  onClick,
  tone,
  disabled = false,
}: {
  title: string
  description: string
  onClick: () => void
  tone: 'violet' | 'sky' | 'emerald'
  disabled?: boolean
}) {
  const styles = {
    violet: {
      button: 'border-violet-200 bg-violet-50 text-violet-950 hover:border-violet-400 hover:bg-violet-100',
      arrow: 'text-violet-500',
      body: 'text-violet-900/75',
      stripe: 'bg-violet-500',
    },
    sky: {
      button: 'border-sky-200 bg-sky-50 text-sky-950 hover:border-sky-400 hover:bg-sky-100',
      arrow: 'text-sky-500',
      body: 'text-sky-900/75',
      stripe: 'bg-sky-500',
    },
    emerald: {
      button: 'border-emerald-200 bg-emerald-50 text-emerald-950 hover:border-emerald-400 hover:bg-emerald-100',
      arrow: 'text-emerald-500',
      body: 'text-emerald-900/75',
      stripe: 'bg-emerald-500',
    },
  }[tone]
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`relative min-h-28 overflow-hidden border px-4 py-3 text-left transition disabled:opacity-40 ${styles.button}`}
    >
      <span className={`absolute inset-y-0 left-0 w-1 ${styles.stripe}`} />
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-semibold">{title}</div>
        <span className={styles.arrow}>→</span>
      </div>
      <p className={`mt-2 text-xs leading-relaxed ${styles.body}`}>
        {description}
      </p>
    </button>
  )
}

function readSavedHumanFeedbackPrompt(projectId: number, dimensionName: string): string {
  try {
    return localStorage.getItem(`annotagent.humanFeedback.generatedPrompt.${projectId}.${dimensionName}`) ?? ''
  } catch {
    return ''
  }
}

function PromptCard({
  dp, pipelinePrompt, optimizedRun, appliedRunId, onJumpToRun, projectId, onPipelineSaved,
}: {
  dp: { dimension_name: string; prompt: string; version: string; path: string; error: string | null }
  pipelinePrompt: string
  optimizedRun?: OptimizerRun
  appliedRunId: number | null
  onJumpToRun: (runId: number) => void
  projectId: number
  onPipelineSaved: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [view, setView] = useState<'starting' | 'optimized'>(optimizedRun ? 'optimized' : 'starting')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [err, setErr] = useState('')
  const [saved, setSaved] = useState(false)
  const [copied, setCopied] = useState(false)
  const test = (optimizedRun?.artifact as any)?.test as { final_score?: number } | undefined
  const score = test?.final_score ?? optimizedRun?.final_score
  const currentPrompt = pipelinePrompt || dp.prompt
  const text = view === 'optimized' && optimizedRun ? optimizedRun.optimized_prompt : currentPrompt
  const dirty = draft !== text
  const canRestoreStartingPrompt = !!pipelinePrompt && pipelinePrompt.trim() !== dp.prompt.trim()
  const savedHumanPrompt = readSavedHumanFeedbackPrompt(projectId, dp.dimension_name)
  const currentFromHumanFeedback = !!savedHumanPrompt && currentPrompt.trim() === savedHumanPrompt.trim()
  const currentSource = appliedRunId
    ? `run ${String(appliedRunId).padStart(4, '0')} from optimization run`
    : currentFromHumanFeedback
      ? 'from Human feedback'
      : pipelinePrompt
        ? 'current pipeline'
        : dp.version
  const optimizedSource = optimizedRun
    ? `run ${String(optimizedRun.id).padStart(4, '0')} from optimization run${typeof score === 'number' ? ` · ${(score * 100).toFixed(0)}%` : ''}`
    : dp.version

  useEffect(() => {
    if (!editing) setDraft(text)
  }, [text, editing])

  const startEdit = () => {
    setOpen(true)
    setEditing(true)
    setDraft(text)
    setErr('')
    setSaved(false)
  }

  const save = async () => {
    setSaving(true); setErr('')
    try {
      await commitPrompt(projectId, dp.dimension_name, draft)
      await onPipelineSaved()
      setEditing(false)
      setSaved(true)
    } catch (e: any) {
      setErr(fmtError(e))
    } finally {
      setSaving(false)
    }
  }

  const restoreStartingPrompt = async () => {
    setRestoring(true); setErr('')
    try {
      await commitPrompt(projectId, dp.dimension_name, dp.prompt)
      await onPipelineSaved()
      setView('starting')
      setEditing(false)
      setDraft(dp.prompt)
      setSaved(true)
    } catch (e: any) {
      setErr(fmtError(e))
    } finally {
      setRestoring(false)
    }
  }

  const copyPrompt = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setErr('Copy failed')
    }
  }

  return (
    <div className="border border-seam bg-white">
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-paper/40">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="font-mono-editorial text-stone-400 w-3">{open ? '−' : '+'}</span>
          <span className="font-medium truncate">{dp.dimension_name}</span>
        </div>
        <div className="font-mono-editorial text-xs flex items-center gap-2 shrink-0">
          <span className={currentFromHumanFeedback ? 'text-sky-700' : appliedRunId ? 'text-violet-700' : 'text-stone-500'}>
            {currentSource}
          </span>
          {optimizedRun && !appliedRunId && !currentFromHumanFeedback && (
            <span className="text-violet-500">{optimizedSource}</span>
          )}
          {(appliedRunId === optimizedRun?.id || currentFromHumanFeedback) && <span className="text-emerald-700">applied</span>}
          {saved && <span className="text-emerald-700">saved</span>}
        </div>
      </button>
      <div className="px-4 py-2 border-t border-seam bg-paper/30 flex items-center justify-end gap-2">
        {canRestoreStartingPrompt && (
          <button
            onClick={restoreStartingPrompt}
            disabled={restoring}
            className="px-3 py-1.5 border border-stone-300 bg-white text-stone-700 text-xs font-medium hover:border-ink hover:text-ink transition disabled:opacity-40"
          >
            {restoring ? 'Restoring…' : 'Restore starting prompt'}
          </button>
        )}
        <button
          onClick={copyPrompt}
          className="px-3 py-1.5 border border-ink bg-white text-ink text-xs font-medium hover:bg-paper transition"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
        <button
          onClick={startEdit}
          className="px-3 py-1.5 bg-ink text-cream text-xs font-medium hover:bg-stone-800 transition"
        >
          Edit prompt
        </button>
      </div>
      {open && !dp.error && (
        <div className="border-t border-seam">
          {optimizedRun && (
            <div className="px-4 py-1.5 flex items-center gap-3 border-b border-seam bg-paper/40">
              <button onClick={() => { setView('starting'); setEditing(false); setErr('') }} className={`text-xs font-mono-editorial ${view === 'starting' ? 'text-ink underline' : 'text-stone-500 hover:text-ink'}`}>current pipeline</button>
              <span className="text-stone-300">·</span>
              <button onClick={() => { setView('optimized'); setEditing(false); setErr('') }} className={`text-xs font-mono-editorial ${view === 'optimized' ? 'text-violet-700 underline' : 'text-stone-500 hover:text-ink'}`}>optimized</button>
              <button onClick={() => onJumpToRun(optimizedRun.id)} className="ml-auto text-xs font-mono-editorial text-stone-500 hover:text-ink">open run →</button>
            </div>
          )}
          {editing ? (
            <div className="p-4 space-y-3">
              <textarea
                value={draft}
                onChange={e => setDraft(e.target.value)}
                rows={Math.min(28, Math.max(10, draft.split('\n').length + 1))}
                className="w-full bg-white border border-seam focus:border-ink focus:outline-none p-3 font-mono text-xs leading-relaxed resize-y"
              />
              <div className="flex items-center gap-3">
                <button
                  onClick={save}
                  disabled={saving || !dirty}
                  className="px-3 py-1.5 bg-ink text-cream text-xs font-medium disabled:opacity-40"
                >
                  {saving ? 'Saving…' : 'Save to annotation pipeline'}
                </button>
                <button
                  onClick={() => { setEditing(false); setDraft(text); setErr('') }}
                  disabled={saving}
                  className="font-mono-editorial text-xs text-stone-500 hover:text-ink"
                >
                  Cancel
                </button>
                {err && <span className="text-xs text-red-700">{err}</span>}
              </div>
            </div>
          ) : (
            <div className="px-4 py-3 max-h-[360px] overflow-auto">
            <MarkdownLite text={text} />
          </div>
          )}
        </div>
      )}
      {open && dp.error && <div className="border-t border-seam px-4 py-3 text-xs text-red-700">{dp.error}</div>}
    </div>
  )
}

/* ─── Improve tab ──────────────────────────────────────────── */

function optimizerCopy(name: string) {
  const copy: Record<string, { title: string; description: string; recommended?: boolean }> = {
    reflect_agent: {
      title: 'Guided prompt improvement',
      description: 'Learns readable rules from labeled examples and rewrites the prompt in a way you can review.',
      recommended: true,
    },
    gepa: {
      title: 'Automatic prompt search',
      description: 'Tries prompt variants using example feedback and keeps moving toward better performance.',
    },
    mipro: {
      title: 'Programmatic optimizer',
      description: 'Searches over instructions and examples for more technical prompt programs.',
    },
    opro: {
      title: 'LLM prompt optimizer',
      description: 'Asks an LLM to propose better prompts from previous prompt scores.',
    },
  }
  return copy[name] ?? {
    title: 'Advanced optimizer',
    description: 'Experimental improvement method for labeled examples.',
  }
}

function optimizerChoices(optimizers: OptimizerInfo[]) {
  const available = optimizers.length > 0
    ? optimizers
    : [{ name: 'reflect_agent', label: 'ReflectAgent', description: '', role: 'method' }]
  return available.map(opt => ({ ...opt, ...optimizerCopy(opt.name) }))
}

function ImproveTab({
  codebooks, datasets, runs, selectedDim, setSelectedDim, selectedGold, setSelectedGold,
  optimizers, selectedOptimizer, setSelectedOptimizer,
  budget, setBudget, launching, launchError, projectId, onLaunched,
  setLaunching, setLaunchError,
}: {
  codebooks: Codebook[]
  datasets: Dataset[]
  runs: OptimizerRun[]
  selectedDim: string
  setSelectedDim: (v: string) => void
  selectedGold: number | null
  setSelectedGold: (v: number) => void
  optimizers: OptimizerInfo[]
  selectedOptimizer: string
  setSelectedOptimizer: (v: string) => void
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
  const [showOptimizers, setShowOptimizers] = useState(false)

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

  const selectedLabelKey = Object.keys(classCounts).find(k => normDimensionName(k) === normDimensionName(selectedDim)) ?? selectedDim
  const classes = classCounts[selectedLabelKey] ?? {}
  const total = Object.values(classes).reduce((a, b) => a + b, 0)
  const goldForDim = (name: string): number => {
    const key = Object.keys(classCounts).find(k => normDimensionName(k) === normDimensionName(name))
    return key ? Object.values(classCounts[key]).reduce((a, b) => a + b, 0) : 0
  }
  const selectedDimension = activeCb?.dimensions.find(d => normDimensionName(d.name) === normDimensionName(selectedDim))
  const expectedLabels = useMemo(() => selectedDimension?.labels.map(l => l.name) ?? [], [selectedDimension])

  // Cascade gating: a dependent dimension (gated by another, or taking another's
  // value as context) must be improved AFTER the ones it depends on. Require each
  // prerequisite to have a completed optimization run first.
  const hasCompletedRun = (dimName: string) => runs.some(r =>
    normDimensionName(r.dimension_name) === normDimensionName(dimName) && normStatus(r.status) === 'completed')
  const prereqs: string[] = selectedDimension
    ? [selectedDimension.gated_by, ...((selectedDimension as any).context_dims || [])].filter(Boolean) as string[]
    : []
  const unmetPrereqs = prereqs.filter(p => !hasCompletedRun(p))
  const blockedByPrereq = unmetPrereqs.length > 0
  const displayedClasses = useMemo(() => {
    const merged: Record<string, number> = {}
    for (const expected of expectedLabels) {
      const actualKey = Object.keys(classes).find(label => normLabelName(label) === normLabelName(expected))
      merged[expected] = actualKey ? classes[actualKey] : 0
    }
    for (const [label, count] of Object.entries(classes)) {
      const alreadyShown = Object.keys(merged).some(existing => normLabelName(existing) === normLabelName(label))
      if (!alreadyShown) merged[label] = count
    }
    return merged
  }, [classes, expectedLabels])
  const missingLabels = expectedLabels.filter(label => (displayedClasses[label] ?? 0) === 0)
  const split = useMemo(() => stratifiedPreview(displayedClasses, 15, 42), [displayedClasses])
  const sorted = Object.keys(displayedClasses).sort((a, b) => {
    const aExpected = expectedLabels.findIndex(label => normLabelName(label) === normLabelName(a))
    const bExpected = expectedLabels.findIndex(label => normLabelName(label) === normLabelName(b))
    if (aExpected !== -1 || bExpected !== -1) return (aExpected === -1 ? 999 : aExpected) - (bExpected === -1 ? 999 : bExpected)
    return displayedClasses[b] - displayedClasses[a]
  })
  const tooFew = total > 0 && total < 15
  const noLabels = total === 0
  // Imbalance: classes under this share of the data get too few val/test items to
  // estimate reliably (stratified split can't make a single-item class meaningful).
  const RARE_PCT = 5
  const rareClasses = total > 0
    ? sorted.filter(c => {
        const n = split.perClass[c]?.n ?? 0
        return n > 0 && (n / total) * 100 < RARE_PCT
      })
    : []

  const handleLaunch = async () => {
    if (!selectedGold || noLabels || tooFew || blockedByPrereq) return
    setLaunching(true); setLaunchError('')
    try {
      const run = await startOptimizerRun(projectId, {
        optimizer_name: selectedOptimizer,
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
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: pickers */}
        <div className="lg:col-span-1 space-y-4">
        <div>
          <Label>Dimension</Label>
          <select value={selectedDim} onChange={e => setSelectedDim(e.target.value)}
                  className="w-full px-0 py-1.5 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-medium">
            {[...(activeCb?.dimensions ?? [])]
              .sort((a, b) => goldForDim(b.name) - goldForDim(a.name))
              .map(d => {
                const g = goldForDim(d.name)
                const note = g === 0 ? 'no labeled data' : g < 15 ? `only ${g} · need 15+` : `${g} gold`
                return (
                  <option key={d.id} value={d.name}>
                    {d.name} · {note}
                  </option>
                )
              })}
          </select>
        </div>
        <div>
          <Label>Labeled examples</Label>
          {datasets.length === 0
            ? (
              <div className="border border-amber-200 bg-amber-50 px-3 py-3">
                <p className="text-sm font-medium text-amber-900">No labeled examples loaded.</p>
                <p className="mt-1 text-xs leading-relaxed text-amber-800">
                  To run improvement, upload labeled data in Setup first.
                </p>
                <a
                  href={`/projects/${projectId}/setup`}
                  className="mt-2 inline-flex px-3 py-1.5 bg-ink text-cream text-xs font-medium hover:bg-stone-800 transition"
                >
                  Go to Setup →
                </a>
              </div>
            )
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
          <Label>Improvement rounds</Label>
          <input type="number" min={1} max={20} value={budget}
                 onChange={e => setBudget(Math.max(1, Math.min(20, Number(e.target.value) || 5)))}
                 className="w-full px-0 py-1.5 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-mono text-sm" />
          <p className="mt-1 text-xs text-stone-500 leading-relaxed">
            Main optimization passes. Baseline scoring and final validation may appear separately in the run summary.
          </p>
        </div>
        <div className="border border-seam bg-paper/30">
          <button
            type="button"
            onClick={() => setShowOptimizers(v => !v)}
            className="w-full px-3 py-2 flex items-center justify-between gap-3 text-left hover:bg-stone-50"
          >
            <span>
              <span className="block text-sm font-medium text-ink">Explore optimizers</span>
              <span className="block text-xs text-stone-500">{optimizerCopy(selectedOptimizer).title}</span>
            </span>
            <span className="text-xs font-mono text-stone-500">{showOptimizers ? 'Hide' : 'Show'}</span>
          </button>
          {showOptimizers && (
            <div className="border-t border-seam p-2 space-y-2">
              {optimizerChoices(optimizers).map(choice => {
                const selected = selectedOptimizer === choice.name
                return (
                  <button
                    key={choice.name}
                    type="button"
                    onClick={() => setSelectedOptimizer(choice.name)}
                    className={`w-full p-3 text-left border transition ${
                      selected ? 'border-ink bg-ink text-cream' : 'border-seam bg-paper hover:border-stone-400 text-ink'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-medium">{choice.title}</div>
                      {choice.recommended && (
                        <div className={`text-[10px] font-mono uppercase tracking-wide ${selected ? 'text-cream/70' : 'text-violet-700'}`}>
                          Recommended
                        </div>
                      )}
                    </div>
                    <div className={`mt-1 text-xs leading-relaxed ${selected ? 'text-cream/75' : 'text-stone-600'}`}>
                      {choice.description}
                    </div>
                    <div className={`mt-2 text-[11px] font-mono ${selected ? 'text-cream/55' : 'text-stone-400'}`}>
                      {choice.label}
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </div>
        <div className="border border-amber-200 bg-amber-50/70 px-3 py-3">
          <div className="font-mono-editorial text-amber-800 mb-2">Before you run</div>
          <div className="flex flex-wrap gap-2">
            <RunInputLabel label="Optimizer" value={optimizerCopy(selectedOptimizer).title} />
            <RunInputLabel label="Rounds" value={budget.toLocaleString()} />
            <RunInputLabel label="Examples" value={total > 0 ? total.toLocaleString() : '—'} />
            <RunInputLabel label="Dimension" value={selectedDim || '—'} />
          </div>
          <p className="mt-2 text-xs leading-relaxed text-amber-900/80">
            Improvement can make many LLM calls; the number scales with the rounds, the examples, and retries. {APP_NAME} tracks measured token usage in the run summary.
          </p>
        </div>
        {blockedByPrereq && (
          <div className="border border-indigo-200 bg-indigo-50/60 px-3 py-2 text-xs text-indigo-900">
            <span className="font-medium">“{selectedDim}” is predicted after {prereqs.join(' and ')}.</span>{' '}
            Improve {unmetPrereqs.join(' and ')} first — run it through this step until it has a completed run, then come back.
          </div>
        )}
        <button onClick={handleLaunch} disabled={launching || noLabels || tooFew || blockedByPrereq}
                data-tour="run-improvement"
                className="w-full py-2.5 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-40">
          {launching ? 'Starting…' : blockedByPrereq ? `Improve ${unmetPrereqs[0]} first` : 'Run improvement →'}
        </button>
        {launchError && <div className="text-xs text-red-700">{launchError}</div>}
        </div>

        {/* Right: split preview */}
        <div className="lg:col-span-2">
        {datasets.length === 0 ? (
          <div className="border border-amber-200 bg-amber-50/60 p-5 text-sm text-amber-900">
            <div className="font-mono-editorial text-amber-700 mb-1">Labeled data required</div>
            Improvement learns from examples that already have correct labels. Go back to Setup and upload labeled CSV/JSON before running this step.
          </div>
        ) : noLabels ? (
          <div className="border border-amber-200 bg-amber-50/50 p-4 text-sm text-amber-800">
            <div className="font-mono-editorial text-amber-700 mb-1">No labeled data for "{selectedDim}"</div>
            Your uploaded file has no labels for this dimension. Dimensions you can improve: {Object.keys(classCounts).filter(k => Object.keys(classCounts[k]).length > 0).join(', ') || '—'}.
          </div>
        ) : tooFew ? (
          <div className="border border-amber-200 bg-amber-50/50 p-4 text-sm text-amber-800">
            <div className="font-mono-editorial text-amber-700 mb-1">Not enough labeled data for "{selectedDim}"</div>
            Your uploaded file has only {total} labeled item{total === 1 ? '' : 's'} here; improvement needs at least 15.
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
            {missingLabels.length > 0 && (
              <div className="mb-3 border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                No labeled examples for: <span className="font-semibold">{missingLabels.join(', ')}</span>. Improvement can still run, but it cannot learn or validate those labels from this dataset.
              </div>
            )}
            {rareClasses.length > 0 && (
              <div className="mb-3 border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                Imbalanced (under {RARE_PCT}% of the data):{' '}
                <span className="font-semibold">
                  {rareClasses.map(c => `${c} (${((split.perClass[c].n / total) * 100).toFixed(1)}%, ${split.perClass[c].n})`).join(', ')}
                </span>. These labels get very few val/test items, so their scores will be noisy.
              </div>
            )}
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
                  const rare = rareClasses.includes(c)
                  return (
                    <tr key={c} className={rare ? 'bg-amber-50/40' : ''}>
                      <td className="py-1.5 truncate max-w-[260px]" title={c}>
                        {rare && <span className="text-amber-600 mr-1" title={`under ${RARE_PCT}% of the data`}>⚠</span>}{c}
                      </td>
                      <td className={`py-1.5 text-right ${rare ? 'text-amber-700' : 'text-stone-700'}`}>{s?.n ?? 0}</td>
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
    </div>
  )
}

function RunInputLabel({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-amber-200 bg-white/70 px-2.5 py-1.5">
      <div className="font-mono-editorial text-[10px] text-amber-700">{label}</div>
      <div className="text-xs font-medium text-amber-950 max-w-[180px] truncate" title={value}>{value}</div>
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
  runs, selectedRunId, selectedRun, onSelect, onUpdate, onDelete, onCancel, projectId, onPipelinesRefresh, pipelinePromptForDimension, onContinue,
}: {
  runs: OptimizerRun[]
  selectedRunId: number | null
  selectedRun: OptimizerRun | null
  onSelect: (id: number | null) => void
  onUpdate: (r: OptimizerRun) => void
  onDelete: (r: OptimizerRun) => void
  onCancel: (r: OptimizerRun) => void
  projectId: number
  onPipelinesRefresh: () => Promise<void>
  pipelinePromptForDimension: (dimensionName: string) => string
  onContinue: () => void
}) {
  if (runs.length === 0) {
    return (
      <div className="space-y-4">
        <Empty>No runs yet. Launch one from <em>Improve</em>.</Empty>
        <div className="flex justify-end border-t border-seam pt-4">
          <button
            onClick={onContinue}
            className="px-5 py-2 bg-ink text-cream text-sm font-medium hover:bg-stone-800 transition"
          >
            Continue to human feedback →
          </button>
        </div>
      </div>
    )
  }
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Master: list */}
        <div className="lg:col-span-3 border border-seam bg-white max-h-[78vh] overflow-auto">
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
        <div className="lg:col-span-9 border border-seam bg-white max-h-[78vh] overflow-auto">
        {selectedRun
          ? (
            <RunDetailV2
              run={selectedRun}
              projectId={projectId}
              onUpdate={onUpdate}
              onPipelinesRefresh={onPipelinesRefresh}
              currentPipelinePrompt={pipelinePromptForDimension(selectedRun.dimension_name)}
            />
          )
          : <Empty>Pick a run on the left.</Empty>
        }
        </div>
      </div>
      <div className="flex justify-end border-t border-seam pt-4">
        <button
          onClick={onContinue}
          className="px-5 py-2 bg-ink text-cream text-sm font-medium hover:bg-stone-800 transition"
        >
          Continue to human feedback →
        </button>
      </div>
    </div>
  )
}

function RunDetailV2({
  run, projectId, onUpdate, onPipelinesRefresh, currentPipelinePrompt,
}: {
  run: OptimizerRun
  projectId: number
  onUpdate: (r: OptimizerRun) => void
  onPipelinesRefresh: () => Promise<void>
  currentPipelinePrompt: string
}) {
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
  const [rulesOpen, setRulesOpen] = useState(false)
  const [trajView, setTrajView] = useState<'overall' | 'per-class'>('overall')
  // Per-class val-F1 lines come from runs that log `val_per_class_f1` each round.
  // Older runs only have the aggregate curve, so the toggle stays hidden for them.
  const perClassClasses: string[] = (() => {
    const fromTest = (test as any)?.final_metrics?.classes
    if (Array.isArray(fromTest) && fromTest.length) return fromTest.slice()
    const set = new Set<string>()
    for (const t of traj) for (const k of Object.keys(t?.val_per_class_f1 || {})) set.add(k)
    return Array.from(set)
  })()
  const hasPerClassTraj = traj.some((t: any) => t?.val_per_class_f1 && Object.keys(t.val_per_class_f1).length > 0)

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
            <div className="self-center font-mono-editorial text-stone-400 text-[10px] leading-tight text-right mr-1">held-out<br/>test</div>
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
        <Card title="Trajectory" rightSlot={hasPerClassTraj ? (
          <div className="inline-flex border border-seam bg-white text-[11px] font-medium">
            {([['overall', 'Overall'], ['per-class', 'Per class']] as const).map(([v, lbl]) => (
              <button
                key={v}
                onClick={() => setTrajView(v)}
                className={`px-2 py-0.5 transition-colors ${trajView === v ? 'bg-ink text-cream' : 'text-stone-500 hover:text-ink'}`}
              >
                {lbl}
              </button>
            ))}
          </div>
        ) : undefined}>
          {traj.length >= 1 ? (
            <div className="space-y-3">
              {/* Phase ribbon: the val curve and the per-round numbers are the
                  optimizer's internal signal; the honest number is the held-out
                  test scored once at the end. */}
              <PhaseRibbon traj={traj} test={test} />
              {trajView === 'per-class' ? (
                <PerClassTrajectoryChart traj={traj} classes={perClassClasses} isRunning={isRunning} />
              ) : (
              <>
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
              <div className="font-mono-editorial text-stone-400 text-[10px] -mt-1 px-1">
                validation accuracy · the optimizer's internal signal, not the reported score
              </div>
              </>
              )}
              {/* Compact step-by-step list — separates requested improvement
                  rounds from baseline/final bookkeeping passes. */}
              <ul className="text-xs font-mono divide-y divide-seam border-t border-seam max-h-40 overflow-auto">
                {traj.map((t: any, i: number) => (
                  <li key={i} className="flex items-baseline gap-2 px-1 py-1">
                    <span className="font-mono-editorial text-stone-400 w-24 shrink-0">{trajectoryStepLabel(t, budget)}</span>
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
              ? <SkeletonTable label="Held-out test is scored after the improvement rounds." />
              : <Empty>{test ? 'Old run — no per-class.' : 'Test eval pending.'}</Empty>}
        </Card>

        <Card
          title={`Rule library · ${ruleLib.length}`}
          className="md:col-span-2"
          rightSlot={
            <button
              onClick={() => setRulesOpen(v => !v)}
              className="px-2 py-0.5 border border-seam bg-white text-xs font-medium text-stone-700 hover:border-ink hover:text-ink"
            >
              {rulesOpen ? 'Hide' : 'Show'}
            </button>
          }
        >
          {!rulesOpen ? (
            <div className="text-xs text-stone-500">
              Learned calibration rules are hidden to keep the run summary focused.
            </div>
          ) : ruleLib.length === 0
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
        run.status === 'completed' && (
          <UseImprovedPromptCard
            run={run}
            projectId={projectId}
            onUpdate={onUpdate}
            onApplied={onPipelinesRefresh}
            currentPipelinePrompt={currentPipelinePrompt}
          />
        )
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
          {elapsedStr} elapsed · {(run.total_tokens || 0).toLocaleString()} tokens
        </span>
      </div>

      {/* Round counter + progress bar */}
      <div className="flex items-center justify-between mb-1.5 text-xs font-mono-editorial">
        <span className="text-blue-700">{progressStepLabel(currentRound, budget)}</span>
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
              <span className="font-mono-editorial text-stone-400 w-24 shrink-0">{trajectoryStepLabel(t, budget)}</span>
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
    case 'prompt_integrated':  return 'rules integrated into prompt'
    default:                   return action || '—'
  }
}

function trajectoryStepLabel(t: any, budget: number): string {
  const action = t?.action
  const round = Number(t?.round ?? 0)
  if (action === 'baseline' || action === 'baseline_seeded' || round === 0) return 'Baseline'
  if (action === 'val_consolidation') return 'Final validation'
  if (action === 'demos_appended') return 'Final examples'
  if (action === 'prompt_integrated') return 'Prompt rewrite'
  if (round <= budget) return `Round ${round}`
  return 'Final pass'
}

function progressStepLabel(currentRound: number, budget: number): string {
  if (currentRound <= 0) return 'Baseline'
  if (currentRound <= budget) return `Improvement round ${currentRound} / ${budget}`
  return 'Final validation and prompt rewrite'
}

/** Phase ribbon over the trajectory: search (val) → finalize (val) → test (once).
    The search rounds and the finalize bookkeeping passes both run on the
    validation set — the optimizer's internal signal. Only the test phase is the
    honest, held-out, scored-once number. */
function PhaseRibbon({ traj, test }: {
  traj: any[]
  test?: { initial_score: number; final_score: number; delta: number } | undefined
}) {
  const isFin = (a?: string) => a === 'val_consolidation' || a === 'demos_appended' || a === 'prompt_integrated'
  const search = traj.filter((t) => !isFin(t?.action))
  const fin = traj.filter((t) => isFin(t?.action))
  const pct = (x: any) => typeof x === 'number' ? `${(x * 100).toFixed(1)}%` : '—'
  const searchVal = search.length ? search[search.length - 1].val_acc : undefined
  const finVal = fin.length ? fin[fin.length - 1].val_acc : undefined
  const ti = test?.initial_score, tf = test?.final_score
  const td = typeof test?.delta === 'number' ? test.delta
    : (typeof ti === 'number' && typeof tf === 'number' ? tf - ti : undefined)
  return (
    <div className="flex items-stretch gap-1.5">
      <RibChip head="Search" sub="validation signal" body={pct(searchVal)} />
      <RibSep />
      <RibChip head="Finalize" sub="val · folds val in" body={fin.length ? pct(finVal) : '—'} />
      <RibSep />
      <RibChip head="Test" sub="held-out · scored once" emphasized
        body={typeof tf === 'number' ? `${pct(ti)} → ${pct(tf)}` : '—'}
        foot={typeof td === 'number' ? `${td >= 0 ? '+' : ''}${(td * 100).toFixed(1)}pp` : undefined} />
    </div>
  )
}

function RibChip({ head, sub, body, foot, emphasized }: {
  head: string; sub: string; body: string; foot?: string; emphasized?: boolean
}) {
  return (
    <div className={`flex-1 min-w-0 px-2 py-1.5 border ${emphasized ? 'border-emerald-300 bg-emerald-50/50' : 'border-seam bg-paper/40'}`}>
      <div className={`font-mono-editorial text-[10px] tracking-wide uppercase ${emphasized ? 'text-emerald-700' : 'text-stone-400'}`}>{head}</div>
      <div className={`font-mono text-xs mt-0.5 truncate ${emphasized ? 'text-emerald-800 font-semibold' : 'text-stone-600'}`}>{body}</div>
      {foot && <div className="font-mono text-[11px] text-emerald-700 leading-tight">{foot}</div>}
      <div className="font-mono-editorial text-[9px] text-stone-400 mt-0.5 truncate">{sub}</div>
    </div>
  )
}

function RibSep() {
  return <div className="self-center text-stone-300 text-sm shrink-0">→</div>
}

/** Minimal markdown renderer for the prompt subset we emit: ## headings,
    **bold**, and - bullet lists. Editing stays raw text; this is display only. */
function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) => {
    const m = /^\*\*([\s\S]+)\*\*$/.exec(part)
    if (m) return <strong key={`${keyPrefix}-${i}`} className="font-semibold text-ink">{m[1]}</strong>
    return <Fragment key={`${keyPrefix}-${i}`}>{part}</Fragment>
  })
}

function MarkdownLite({ text }: { text: string }) {
  const lines = text.split('\n')
  const blocks: React.ReactNode[] = []
  let para: string[] = []
  const flushPara = () => {
    if (!para.length) return
    const k = `p${blocks.length}`
    blocks.push(
      <p key={k} className="text-stone-700">
        {para.map((ln, i) => (
          <Fragment key={i}>{i > 0 && <br />}{renderInline(ln, `${k}-${i}`)}</Fragment>
        ))}
      </p>,
    )
    para = []
  }
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (/^#{1,6}\s+/.test(line)) {
      flushPara()
      blocks.push(
        <h4 key={`h${blocks.length}`} className="font-semibold text-ink text-[13px] mt-3 first:mt-0">
          {line.replace(/^#{1,6}\s+/, '')}
        </h4>,
      )
    } else if (/^[-*]\s+/.test(line)) {
      flushPara()
      const items: string[] = []
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*]\s+/, ''))
        i++
      }
      i--
      const k = `ul${blocks.length}`
      blocks.push(
        <ul key={k} className="list-disc pl-5 space-y-0.5 text-stone-700">
          {items.map((it, j) => <li key={j}>{renderInline(it, `${k}-${j}`)}</li>)}
        </ul>,
      )
    } else if (line.trim() === '') {
      flushPara()
    } else {
      para.push(line)
    }
  }
  flushPara()
  return <div className="text-xs leading-relaxed space-y-2">{blocks}</div>
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
  const labels: string[] = (final?.classes ?? Object.keys(final?.per_class || {})).slice()
    .sort((a: string, b: string) => (final?.per_class?.[b]?.support ?? 0) - (final?.per_class?.[a]?.support ?? 0))
  const [open, setOpen] = useState<string | null>(null)
  const [view, setView] = useState<'table' | 'chart'>('table')
  const pct = (x: any) => `${((x ?? 0) * 100).toFixed(0)}`
  return (
    <div className="text-xs font-mono">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 flex-1 min-w-0">
          <Stat label="Macro F1" value={`${pct(initial?.macro_f1)}% → ${pct(final.macro_f1)}%`} />
          <Stat label="Weighted F1" value={`${pct(initial?.weighted_f1)}% → ${pct(final.weighted_f1)}%`} />
        </div>
        <div className="inline-flex shrink-0 border border-seam bg-white text-[11px] font-medium">
          {(['table', 'chart'] as const).map(v => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-2.5 py-1 capitalize transition-colors ${
                view === v ? 'bg-ink text-cream' : 'text-stone-500 hover:text-ink'
              }`}
            >
              {v}
            </button>
          ))}
        </div>
      </div>
      {view === 'chart' ? (
        <PerClassChart labels={labels} initial={initial} final={final} />
      ) : (
      <>
      <div className="font-mono-editorial text-stone-400 text-[10px] mb-1">click a label for its precision / recall / errors</div>
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
            const isOpen = open === l
            return (
              <Fragment key={l}>
                <tr className="cursor-pointer hover:bg-paper/60" onClick={() => setOpen(isOpen ? null : l)}>
                  <td className="py-1 truncate max-w-[150px]" title={l}>
                    <span className="text-stone-400 mr-1">{isOpen ? '▾' : '▸'}</span>{l}
                  </td>
                  <td className="py-1 text-right text-stone-600">{f?.support ?? 0}</td>
                  <td className="py-1 text-right">
                    <span className="text-stone-500">{pct(i?.f1)}</span>
                    <span className="text-stone-300 mx-1">→</span>
                    <span className={d > 0 ? 'text-emerald-700' : d < 0 ? 'text-red-600' : 'text-stone-700'}>{pct(f?.f1)}</span>
                  </td>
                </tr>
                {isOpen && (
                  <tr className="bg-paper/40">
                    <td colSpan={3} className="px-2 py-2">
                      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-stone-600 mb-1.5">
                        <span>Precision {pct(i?.precision)}% → <span className="text-stone-800">{pct(f?.precision)}%</span></span>
                        <span>Recall {pct(i?.recall)}% → <span className="text-stone-800">{pct(f?.recall)}%</span></span>
                        <span>F1 Δ <span className={d >= 0 ? 'text-emerald-700' : 'text-red-600'}>{d >= 0 ? '+' : ''}{(d * 100).toFixed(0)}pp</span></span>
                        <span className="text-stone-500">final: tp {f?.tp ?? 0} · fp {f?.fp ?? 0} · fn {f?.fn ?? 0}</span>
                      </div>
                      <BeforeAfterBar before={i?.f1 ?? 0} after={f?.f1 ?? 0} />
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
      </>
      )}
    </div>
  )
}

function PerClassChart({ labels, initial, final }: { labels: string[]; initial: any; final: any }) {
  // Per-category before -> after F1. Same data the table shows, charted so the
  // whole class breakdown reads at a glance instead of one expanded row at a time.
  const data = labels.map(l => {
    const i = initial?.per_class?.[l], f = final?.per_class?.[l]
    return {
      label: l,
      before: Math.round((i?.f1 ?? 0) * 100),
      after: Math.round((f?.f1 ?? 0) * 100),
      support: f?.support ?? 0,
    }
  })
  const chartH = Math.max(120, data.length * 44 + 28)
  return (
    <div>
      <div className="font-mono-editorial text-stone-400 text-[10px] mb-1.5">per-class F1 · before → after</div>
      <div style={{ maxHeight: 360, overflowY: 'auto' }}>
        <div style={{ width: '100%', height: chartH }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ top: 4, right: 30, left: 4, bottom: 4 }} barCategoryGap="24%">
              <CartesianGrid horizontal={false} strokeDasharray="2 4" stroke="#E5E2D9" />
              <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 10, fill: '#9A968F' }} stroke="#D6D2C8" tickFormatter={(v) => `${v}%`} />
              <YAxis type="category" dataKey="label" width={104} tick={{ fontSize: 10, fill: '#6B6B6B' }} stroke="#D6D2C8" />
              <Tooltip
                contentStyle={{ fontSize: 11 }}
                formatter={(v: any, name: any) => [`${v}%`, name]}
                labelFormatter={(l: any) => {
                  const row = data.find(d => d.label === l)
                  return row ? `${l} · supp ${row.support}` : l
                }}
              />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar dataKey="before" name="Before" fill="#A8A29E" radius={[0, 2, 2, 0]} isAnimationActive={false} />
              <Bar dataKey="after" name="After" fill="#0B0B0A" radius={[0, 2, 2, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  )
}

// Categorical palette for per-class lines — moderate saturation, on-brand.
const PER_CLASS_COLORS = ['#0B0B0A', '#6E4FBE', '#2F8A6F', '#C2683A', '#B23A48', '#3A6EA5', '#9A7B2E', '#5A5A55']

function PerClassTrajectoryChart({ traj, classes, isRunning }: { traj: any[]; classes: string[]; isRunning: boolean }) {
  // One val-F1 line per class across optimization rounds. Same validation
  // signal as the macro curve, broken out per category.
  const data = traj.map((t: any) => {
    const row: any = { round: t.round }
    const pc = t.val_per_class_f1 || {}
    for (const c of classes) row[c] = typeof pc[c] === 'number' ? pc[c] * 100 : null
    return row
  })
  const vals: number[] = []
  for (const row of data) for (const c of classes) if (typeof row[c] === 'number') vals.push(row[c])
  let domain: [number, number] | ['auto', 'auto'] = ['auto', 'auto']
  if (vals.length) {
    const lo = Math.min(...vals), hi = Math.max(...vals)
    const pad = Math.max(4, (hi - lo) * 0.15)
    domain = [Math.max(0, Math.floor((lo - pad) / 5) * 5), Math.min(100, Math.ceil((hi + pad) / 5) * 5)]
  }
  if (!classes.length) return <Empty>No per-class data in this run.</Empty>
  return (
    <>
      <div style={{ width: '100%', height: 200 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="2 4" stroke="#E5E2D9" />
            <XAxis dataKey="round" type="number" domain={[0, 'dataMax']} tick={{ fontSize: 10, fill: '#9A968F' }} stroke="#D6D2C8" allowDecimals={false} />
            <YAxis domain={domain} tick={{ fontSize: 10, fill: '#9A968F' }} stroke="#D6D2C8" tickFormatter={(v) => `${v}%`} width={42} />
            <Tooltip contentStyle={{ fontSize: 11 }} formatter={(v: any, name: any) => [typeof v === 'number' ? `${v.toFixed(1)}%` : '—', name]} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            {classes.map((c, i) => (
              <Line
                key={c}
                type="monotone"
                dataKey={c}
                name={c}
                stroke={PER_CLASS_COLORS[i % PER_CLASS_COLORS.length]}
                strokeWidth={2}
                dot={{ r: 2 }}
                connectNulls
                isAnimationActive={!isRunning}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="font-mono-editorial text-stone-400 text-[10px] -mt-1 px-1">
        per-class validation F1 · the optimizer's internal signal, not the reported score
      </div>
    </>
  )
}

function BeforeAfterBar({ before, after }: { before: number; after: number }) {
  const w = (x: number) => `${Math.round(Math.max(0, Math.min(1, x)) * 100)}%`
  return (
    <div className="space-y-0.5">
      <div className="flex items-center gap-1.5">
        <span className="w-9 text-[10px] text-stone-400 shrink-0">before</span>
        <div className="flex-1 h-1.5 bg-stone-200"><div className="h-full bg-stone-400" style={{ width: w(before) }} /></div>
        <span className="w-8 text-[10px] text-stone-500 text-right shrink-0">{Math.round(before * 100)}%</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="w-9 text-[10px] text-stone-400 shrink-0">after</span>
        <div className="flex-1 h-1.5 bg-stone-200"><div className={`h-full ${after >= before ? 'bg-emerald-500' : 'bg-red-400'}`} style={{ width: w(after) }} /></div>
        <span className="w-8 text-[10px] text-stone-500 text-right shrink-0">{Math.round(after * 100)}%</span>
      </div>
    </div>
  )
}

function UseImprovedPromptCard({
  run,
  projectId,
  onUpdate,
  onApplied,
  currentPipelinePrompt,
}: {
  run: OptimizerRun
  projectId: number
  onUpdate: (r: OptimizerRun) => void
  onApplied: () => Promise<void>
  currentPipelinePrompt: string
}) {
  const [currentPrompt, setCurrentPrompt] = useState(currentPipelinePrompt)
  const [draft, setDraft] = useState(run.optimized_prompt)
  const [editing, setEditing] = useState(false)
  const [foundCurrentPrompt, setFoundCurrentPrompt] = useState(false)
  const [pipelineId, setPipelineId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [savingDraft, setSavingDraft] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    setCurrentPrompt(currentPipelinePrompt)
  }, [currentPipelinePrompt])

  useEffect(() => {
    let cancelled = false
    setLoading(true); setErr('')
    setFoundCurrentPrompt(false)
    setDraft(run.optimized_prompt)
    setEditing(false)
    listPipelines(projectId)
      .then(pipelines => {
        if (cancelled) return
        const latest = pipelines.slice().sort((a, b) => b.id - a.id)[0]
        setPipelineId(latest?.id ?? null)
        const step = (latest?.steps || []).find((s: any) =>
          normDimensionName(s?.name || '') === normDimensionName(run.dimension_name)
          || (Array.isArray(s?.dimensions) && s.dimensions.some((d: string) => normDimensionName(d) === normDimensionName(run.dimension_name)))
        )
        setFoundCurrentPrompt(!!step)
        setCurrentPrompt(String((step as any)?.prompt || ''))
      })
      .catch(e => {
        if (!cancelled) setErr(fmtError(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [projectId, run.id, run.dimension_name])

  const alreadyApplied = currentPrompt.trim() === draft.trim()
  const canCommit = !!run.optimized_prompt && !alreadyApplied && !loading && !saving
  const draftDirty = draft !== run.optimized_prompt

  const handleCommit = async () => {
    setSaving(true); setErr('')
    try {
      const promptToApply = draft
      if (draftDirty) {
        const updated = await patchOptimizerRun(projectId, run.id, { optimized_prompt: promptToApply })
        onUpdate(updated)
      }
      await commitPrompt(projectId, run.dimension_name, promptToApply)
      await onApplied()
      const pipelines = await listPipelines(projectId)
      const latest = pipelines.slice().sort((a, b) => b.id - a.id)[0]
      const step = (latest?.steps || []).find((s: any) =>
        normDimensionName(s?.name || '') === normDimensionName(run.dimension_name)
        || (Array.isArray(s?.dimensions) && s.dimensions.some((d: string) => normDimensionName(d) === normDimensionName(run.dimension_name)))
      )
      setCurrentPrompt(String((step as any)?.prompt || promptToApply))
      setFoundCurrentPrompt(!!step)
      setPipelineId(latest?.id ?? null)
      setEditing(false)
    } catch (e: any) {
      setErr(fmtError(e))
    } finally {
      setSaving(false)
    }
  }

  const saveDraftOnly = async () => {
    setSavingDraft(true); setErr('')
    try {
      const updated = await patchOptimizerRun(projectId, run.id, { optimized_prompt: draft })
      onUpdate(updated)
      setEditing(false)
    } catch (e: any) {
      setErr(fmtError(e))
    } finally {
      setSavingDraft(false)
    }
  }

  return (
    <div className="px-3 pb-3">
      <Card
        title="Apply improved prompt"
        rightSlot={
          <div className="flex items-center gap-2">
            {draftDirty && <span className="font-mono-editorial text-amber-700 text-[11px]">edited</span>}
            <button
              onClick={() => { setEditing(v => !v); setErr('') }}
              className="px-3 py-1.5 border border-ink bg-white text-ink text-xs font-medium hover:bg-paper transition"
            >
              {editing ? 'Review diff' : 'Edit'}
            </button>
            <button
              onClick={handleCommit}
              disabled={!canCommit}
              className={`px-3 py-1.5 bg-ink text-cream text-xs font-medium hover:bg-stone-800 disabled:opacity-40 transition ${
                canCommit ? 'ring-2 ring-amber-400/70 ring-offset-1' : ''
              }`}
            >
              {saving ? 'Applying…' : alreadyApplied ? 'Applied ✓' : 'Apply →'}
            </button>
          </div>
        }
      >
        <div className="space-y-2">
          {/* Dynamic next-step guidance: users were missing the Apply click. */}
          {!loading && !err && foundCurrentPrompt && (
            alreadyApplied ? (
              <div className="border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-900 flex items-center justify-between gap-3 flex-wrap">
                <span>
                  <span className="font-semibold">Applied.</span> “{run.dimension_name}” now uses this improved prompt for annotation. Apply other dimensions too, then run.
                </span>
                <Link to={`/projects/${projectId}/pipeline`} className="shrink-0 font-medium underline hover:no-underline">
                  Go to Annotate →
                </Link>
              </div>
            ) : (
              <div className="border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                <span className="font-semibold">Not applied yet.</span> This improved prompt is not live — click{' '}
                <span className="font-semibold">Apply →</span> (top right) to replace the active prompt for “{run.dimension_name}”.
                Until you do, annotation keeps using the current prompt.
              </div>
            )
          )}
          <div className="flex items-baseline justify-between gap-3 text-xs">
            <p className="text-stone-600 leading-relaxed">
              {draftDirty ? 'Apply will save your edit and replace the active pipeline prompt.' : 'Replace the active pipeline prompt for this dimension with the improved prompt.'}
            </p>
            {pipelineId ? <span className="font-mono-editorial text-stone-400 shrink-0">Pipeline {pipelineId}</span> : null}
          </div>
          {loading ? (
            <Empty>Loading current pipeline prompt…</Empty>
          ) : err ? (
            <div className="text-xs text-red-700">{err}</div>
          ) : !foundCurrentPrompt ? (
            <div className="border border-amber-200 bg-amber-50/50 px-3 py-2 text-xs text-amber-800">
              Could not find the current active prompt for this dimension, so the diff is unavailable.
            </div>
          ) : editing ? (
            <div className="space-y-3">
              <textarea
                value={draft}
                onChange={e => setDraft(e.target.value)}
                rows={Math.min(28, Math.max(10, draft.split('\n').length + 1))}
                className="w-full bg-white border border-seam focus:border-ink focus:outline-none p-3 font-mono text-xs leading-relaxed resize-y"
              />
              <div className="flex items-center gap-3">
                <button
                  onClick={saveDraftOnly}
                  disabled={savingDraft || !draftDirty}
                  className="px-3 py-1.5 bg-ink text-cream text-xs font-medium disabled:opacity-40"
                >
                  {savingDraft ? 'Saving…' : 'Save edit'}
                </button>
                <button
                  onClick={() => { setDraft(run.optimized_prompt); setEditing(false); setErr('') }}
                  disabled={savingDraft}
                  className="font-mono-editorial text-xs text-stone-500 hover:text-ink"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <details className="border border-seam bg-paper/40">
              <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-stone-700 hover:text-ink">
                Review changes
              </summary>
              <div className="border-t border-seam">
                <DiffView oldText={currentPrompt} newText={draft} />
              </div>
            </details>
          )}
          {err && <div className="text-xs text-red-700">{err}</div>}
        </div>
      </Card>
    </div>
  )
}

/* ─── Line-diff helpers ─────────────────────────────────────── */

type DiffLine = { type: 'same' | 'add' | 'del'; text: string }

function computeLineDiff(a: string, b: string): DiffLine[] {
  const al = a.split('\n'), bl = b.split('\n')
  const m = al.length, n = bl.length
  // LCS table — prompts are short (< 200 lines) so O(m·n) is fine
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      dp[i][j] = al[i - 1] === bl[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1])
  const out: DiffLine[] = []
  let i = m, j = n
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && al[i - 1] === bl[j - 1]) { out.push({ type: 'same', text: al[i - 1] }); i--; j-- }
    else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) { out.push({ type: 'add', text: bl[j - 1] }); j-- }
    else { out.push({ type: 'del', text: al[i - 1] }); i-- }
  }
  return out.reverse()
}

function DiffView({ oldText, newText }: { oldText: string; newText: string }) {
  const lines = computeLineDiff(oldText, newText)
  const adds = lines.filter(l => l.type === 'add').length
  const dels = lines.filter(l => l.type === 'del').length
  return (
    <div className="border border-seam overflow-hidden text-xs font-mono">
      <div className="flex items-center gap-3 px-3 py-1.5 bg-stone-100 border-b border-seam font-mono-editorial text-[11px] select-none">
        <span className="text-stone-500">unified diff</span>
        <span className="text-red-600">−{dels} removed</span>
        <span className="text-green-700">+{adds} added</span>
      </div>
      <div className="max-h-96 overflow-y-auto">
        {lines.map((line, idx) => (
          <div
            key={idx}
            className={
              line.type === 'add' ? 'flex bg-green-50'
              : line.type === 'del' ? 'flex bg-red-50'
              : 'flex'
            }
          >
            <span className={`select-none w-5 shrink-0 text-center leading-5 py-0.5 ${
              line.type === 'add' ? 'text-green-600 bg-green-100'
              : line.type === 'del' ? 'text-red-500 bg-red-100'
              : 'text-stone-300 bg-stone-50'
            }`}>
              {line.type === 'add' ? '+' : line.type === 'del' ? '−' : ' '}
            </span>
            <pre className={`flex-1 px-3 py-0.5 whitespace-pre-wrap leading-5 break-all ${
              line.type === 'add' ? 'text-green-900'
              : line.type === 'del' ? 'text-red-800'
              : 'text-stone-700'
            }`}>{line.text}</pre>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ─── Memory tab ────────────────────────────────────────────── */

function MemoryTab({ memory, projectId, jobs, datasets, dimensions, pipelinePromptForDimension, onRefresh, onJobsRefresh, onDatasetsRefresh, onPromptCommitted }: {
  memory: MemoryVersion[]
  projectId: number
  jobs: Job[]
  datasets: Dataset[]
  dimensions: string[]
  pipelinePromptForDimension: (dimensionName: string) => string
  onRefresh: () => void
  onJobsRefresh: () => void
  onDatasetsRefresh: () => void
  onPromptCommitted: () => Promise<void>
}) {
  const byDim: Record<string, MemoryVersion[]> = {}
  for (const v of memory) {
    if (!v.feedback_text) continue
    if (!byDim[v.dimension_name]) byDim[v.dimension_name] = []
    byDim[v.dimension_name].push(v)
  }

  // All known dimensions: human-feedback history + codebook dimensions that don't yet
  const allDims = Array.from(new Set([...Object.keys(byDim), ...dimensions])).sort()
  const [evidenceDim, setEvidenceDim] = useState(allDims[0] ?? '')

  useEffect(() => {
    if (!evidenceDim && allDims.length > 0) {
      setEvidenceDim(allDims[0])
    } else if (evidenceDim && allDims.length > 0 && !allDims.includes(evidenceDim)) {
      setEvidenceDim(allDims[0])
    }
  }, [allDims.join('\n'), evidenceDim])

  if (allDims.length === 0) {
    return <Empty>Human feedback appears here after you add a correction.</Empty>
  }

  return (
    <div className="space-y-5">
      <EvidencePanel
        projectId={projectId}
        jobs={jobs}
        datasets={datasets}
        dimensions={allDims}
        dimensionName={evidenceDim || allDims[0]}
        onDimensionChange={setEvidenceDim}
        onJobsRefresh={onJobsRefresh}
        onDatasetsRefresh={onDatasetsRefresh}
      />
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
              {byDim[d].map(v => (
                <MemRow
                  key={v.id}
                  v={v}
                  onDelete={async () => {
                    if (!window.confirm(`Delete memory v${String(v.version).padStart(3, '0')} for "${d}"?`)) return
                    await deleteMemoryVersion(projectId, v.id)
                    onRefresh()
                  }}
                />
              ))}
            </ul>
          )}
          <div className="flex items-start gap-4 mt-2">
	            <FeedbackBatchPanel
	              projectId={projectId}
	              dimensionName={d}
	              currentPipelinePrompt={pipelinePromptForDimension(d)}
	              onRefresh={onRefresh}
	              onCommitted={onPromptCommitted}
	            />
          </div>
        </div>
      ))}
    </div>
  )
}

type ApplyState = 'idle' | 'loading' | 'preview' | 'committing' | 'done' | 'error'

type DraftFeedback = { id: string; text: string }

function EvidencePanel({ projectId, jobs, datasets, dimensions, dimensionName, onDimensionChange, onJobsRefresh, onDatasetsRefresh }: {
  projectId: number
  jobs: Job[]
  datasets: Dataset[]
  dimensions: string[]
  dimensionName: string
  onDimensionChange: (dimensionName: string) => void
  onJobsRefresh: () => void
  onDatasetsRefresh: () => void
}) {
  // Any completed annotation job is reviewable — its per-item outputs are already
  // in the DB and the /evidence endpoint serves them. Don't restrict to
  // source='human_feedback'; that forced a redundant re-run of work already done.
  const completedJobs = jobs
    .filter(j => normStatus(j.status) === 'completed')
    .slice()
    .sort((a, b) => b.id - a.id)
  const [jobId, setJobId] = useState<number | ''>('')
  const [runDatasetId, setRunDatasetId] = useState<number | ''>('')
  const [rows, setRows] = useState<FeedbackEvidence[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [launchingJob, setLaunchingJob] = useState(false)
  const [launchStatus, setLaunchStatus] = useState('')
  const [mismatchesOnly, setMismatchesOnly] = useState(false)
  const [uploadingDataset, setUploadingDataset] = useState(false)
  const [page, setPage] = useState(1)
  const pageSize = 50

  useEffect(() => {
    if (jobId || completedJobs.length === 0) return
    setJobId(completedJobs[0].id)
  }, [jobId, completedJobs])

  useEffect(() => {
    if (runDatasetId || datasets.length === 0) return
    const preferred = datasets.find(d => d.is_gold) ?? datasets[0]
    setRunDatasetId(preferred.id)
  }, [runDatasetId, datasets])

  useEffect(() => {
    if (!jobId) { setRows([]); return }
    setLoading(true)
    setError('')
    getFeedbackEvidence(projectId, Number(jobId), dimensionName, {
      limit: 500,
      mismatches_only: mismatchesOnly,
    })
      .then(setRows)
      .catch(e => setError(fmtError(e)))
      .finally(() => setLoading(false))
  }, [projectId, jobId, dimensionName, mismatchesOnly])

  useEffect(() => {
    setPage(1)
  }, [jobId, dimensionName, mismatchesOnly])

  const refreshUntilDone = (newJobId: number) => {
    let tries = 0
    const poll = async () => {
      tries += 1
      const latest = await listJobs(projectId)
      const job = latest.find(j => j.id === newJobId)
      onJobsRefresh()
      if (job && normStatus(job.status) === 'completed') {
        setJobId(newJobId)
        setLaunchStatus('Annotation complete. Showing the latest results.')
        setLaunchingJob(false)
        return
      }
      if (job && ['failed', 'cancelled'].includes(normStatus(job.status))) {
        setLaunchStatus(`Annotation ${normStatus(job.status)}.`)
        setLaunchingJob(false)
        return
      }
      if (tries < 180) {
        setLaunchStatus(job ? `Annotating ${job.completed_items}/${job.total_items} items…` : 'Starting annotation…')
        window.setTimeout(poll, 2000)
      } else {
        setLaunchStatus('Annotation is still running. Reopen Human feedback in a moment.')
        setLaunchingJob(false)
      }
    }
    window.setTimeout(poll, 1200)
  }

  const handleRunLatestPrompt = async () => {
    if (!runDatasetId) return
    setLaunchingJob(true)
    setError('')
    setLaunchStatus('Starting annotation with the latest pipeline prompt…')
    try {
      const pipelines = await listPipelines(projectId)
      const latest = pipelines.slice().sort((a, b) => b.id - a.id)[0]
      if (!latest) throw new Error('No pipeline found. Generate a pipeline first.')
      const job = await startJob(projectId, Number(runDatasetId), latest.id, 'human_feedback')
      onJobsRefresh()
      setJobId('')
      refreshUntilDone(job.id)
    } catch (e: any) {
      setError(fmtError(e))
      setLaunchingJob(false)
      setLaunchStatus('')
    }
  }

  const handleUploadRunDataset = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploadingDataset(true)
    setError('')
    try {
      const dataset = await uploadDataset(projectId, file, false)
      setRunDatasetId(dataset.id)
      onDatasetsRefresh()
    } catch (err: any) {
      setError(fmtError(err))
    } finally {
      setUploadingDataset(false)
      e.target.value = ''
    }
  }

  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize))
  const currentPage = Math.min(page, totalPages)
  const pageRows = rows.slice((currentPage - 1) * pageSize, currentPage * pageSize)

  return (
    <div className="border border-seam bg-paper/20">
      <div className="grid gap-0 border-b border-seam lg:grid-cols-[220px_minmax(260px,360px)_minmax(0,1fr)]">
        <div className="border-b border-seam px-3 py-3 lg:border-b-0 lg:border-r">
          <div className="font-mono-editorial text-xs text-stone-500 mb-1.5">1. Dimension</div>
          <select
            value={dimensionName}
            onChange={e => onDimensionChange(e.target.value)}
            className="w-full bg-white border border-seam px-2 py-1.5 text-xs focus:outline-none focus:border-ink"
          >
            {dimensions.map(d => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>

        {/* 2. Review an existing run — primary path; results are already in the DB */}
        <div className="border-b border-seam px-3 py-3 lg:border-b-0 lg:border-r">
          <div className="font-mono-editorial text-xs text-stone-500 mb-1.5">2. Review a run</div>
          <p className="mb-2 text-xs text-stone-500 leading-relaxed">
            Pick a completed run; its per-item outputs are already saved and load below.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={jobId}
              onChange={e => setJobId(e.target.value ? Number(e.target.value) : '')}
              className="max-w-full bg-white border border-seam px-2 py-1.5 text-xs focus:outline-none focus:border-ink"
            >
              {completedJobs.length === 0 && <option value="">No runs yet</option>}
              {completedJobs.map(j => {
                const dataset = datasets.find(d => d.id === j.dataset_id)
                const src = j.source === 'human_feedback' ? 'feedback' : (j.source || 'annotation')
                return (
                  <option key={j.id} value={j.id}>
                    job {String(j.id).padStart(4, '0')} · {src} · {dataset?.name ?? `dataset ${j.dataset_id}`} · {j.completed_items}/{j.total_items}
                  </option>
                )
              })}
            </select>
            <label className="inline-flex items-center gap-1.5 font-mono-editorial text-xs text-stone-500">
              <input
                type="checkbox"
                checked={mismatchesOnly}
                onChange={e => setMismatchesOnly(e.target.checked)}
                className="accent-ink"
              />
              Only items needing review
            </label>
          </div>
        </div>

        {/* 3. Optional: annotate fresh data to create new examples */}
        <div className="px-3 py-3">
          <div className="font-mono-editorial text-xs text-stone-500 mb-1.5">3. Or annotate new data</div>
          <p className="mb-2 text-xs text-stone-500 leading-relaxed">
            Only if you need outputs on data you have not run yet.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            {datasets.length > 0 && (
              <select
                value={runDatasetId}
                onChange={e => setRunDatasetId(e.target.value ? Number(e.target.value) : '')}
                className="max-w-full bg-white border border-seam px-2 py-1.5 text-xs focus:outline-none focus:border-ink"
              >
                {datasets.map(d => (
                  <option key={d.id} value={d.id}>
                    {d.name} · {d.total_items}
                  </option>
                ))}
              </select>
            )}
            <label className="inline-flex items-center gap-2 px-3 py-1.5 border border-seam bg-white text-stone-700 text-xs font-medium hover:bg-paper cursor-pointer">
              <input type="file" accept=".csv,.json" className="hidden" onChange={handleUploadRunDataset} />
              {uploadingDataset ? 'Uploading…' : datasets.length > 0 ? 'Upload different data' : 'Upload data'}
            </label>
            <button
              onClick={handleRunLatestPrompt}
              disabled={launchingJob || !runDatasetId}
              className="px-3 py-1.5 border border-ink bg-white text-ink text-xs font-medium hover:bg-paper disabled:opacity-40 transition"
            >
              {launchingJob ? 'Running…' : 'Run latest prompt'}
            </button>
          </div>
        </div>
      </div>
      {launchStatus && (
        <div className="border-b border-seam px-3 py-2 text-xs text-stone-600 bg-white">
          {launchStatus}
        </div>
      )}
      {datasets.length === 0 && completedJobs.length === 0 && (
        <div className="border-b border-seam px-3 py-2 text-xs text-stone-600 bg-white">
          Cold start: no runs yet. Annotate data in the Annotate tab, or run on new data above.
        </div>
      )}
      {loading ? (
        <div className="px-3 py-3 font-mono-editorial text-xs text-stone-400">Loading examples…</div>
      ) : error ? (
        <div className="px-3 py-3 font-mono-editorial text-xs text-red-600">{error}</div>
      ) : rows.length === 0 ? (
        <div className="px-3 py-3 text-xs text-stone-500 leading-relaxed">
          {completedJobs.length === 0
            ? 'No completed runs yet. Annotate data in the Annotate tab (or run on new data above), then its outputs appear here for review.'
            : 'No saved outputs for this dimension in the selected run. Try another run.'
          }
        </div>
      ) : (
        <div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-seam bg-white px-3 py-2 text-xs text-stone-500">
          <span>
            Showing {((currentPage - 1) * pageSize + 1).toLocaleString()}-{Math.min(currentPage * pageSize, rows.length).toLocaleString()} of {rows.length.toLocaleString()} example{rows.length === 1 ? '' : 's'}
            {mismatchesOnly ? ' needing review, including partial matches' : ''}
          </span>
          {totalPages > 1 && (
            <div className="flex items-center gap-1">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={currentPage === 1}
                className="px-2 py-1 border border-seam bg-white text-stone-600 hover:border-ink disabled:opacity-40"
              >
                Previous
              </button>
              {Array.from({ length: totalPages }, (_, i) => i + 1).map(p => (
                <button
                  key={p}
                  onClick={() => setPage(p)}
                  className={`px-2 py-1 border ${
                    p === currentPage
                      ? 'border-ink bg-ink text-cream'
                      : 'border-seam bg-white text-stone-600 hover:border-ink'
                  }`}
                >
                  {p}
                </button>
              ))}
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages}
                className="px-2 py-1 border border-seam bg-white text-stone-600 hover:border-ink disabled:opacity-40"
              >
                Next
              </button>
            </div>
          )}
        </div>
        <ul className="max-h-[720px] overflow-auto divide-y divide-stone-300 bg-white">
          {pageRows.map(row => {
            const status = row.match_status || (!row.gold_label ? 'missing' : row.is_mismatch ? 'mismatch' : 'match')
            const statusClass =
              status === 'missing'
                ? 'border-stone-300 bg-stone-50 text-stone-600'
                : status === 'mismatch'
                  ? 'border-red-300 bg-red-50 text-red-700'
                  : status === 'partial'
                    ? 'border-amber-300 bg-amber-50 text-amber-800'
                    : 'border-emerald-300 bg-emerald-50 text-emerald-700'
            const panelClass =
              status === 'missing'
                ? 'border-stone-300 bg-stone-50'
                : status === 'mismatch'
                  ? 'border-red-300 bg-red-50'
                  : status === 'partial'
                    ? 'border-amber-300 bg-amber-50'
                    : 'border-emerald-300 bg-emerald-50'
            const statusLabel =
              status === 'missing'
                ? 'No correct label'
                : status === 'mismatch'
                  ? 'Needs review'
                  : status === 'partial'
                    ? 'Partial match'
                    : 'Agrees'
            return (
            <li key={row.result_id} className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_260px]">
              <div className="min-w-0 px-4 py-4">
                <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-mono-editorial text-stone-600">Item {row.item_id}</span>
                  <span className="text-stone-300">·</span>
                  <span className="font-medium text-stone-700">{dimensionName}</span>
                </div>
                <div className="mb-2 text-[11px] font-semibold text-stone-700">Example text</div>
                <div className="text-base leading-relaxed text-stone-950 whitespace-pre-wrap">{row.content}</div>
                {row.reasoning && (
                  <details className="mt-3 text-sm">
                    <summary className="cursor-pointer text-xs font-semibold text-stone-700 hover:text-ink">Annotation output</summary>
                    <div className="mt-2 border-l-2 border-stone-400 pl-3 text-stone-800 whitespace-pre-wrap leading-relaxed">
                      {row.reasoning}
                    </div>
                  </details>
                )}
              </div>
              <div className={`border-t lg:border-l lg:border-t-0 px-4 py-4 ${panelClass}`}>
                <span className={`px-2 py-0.5 border font-medium ${statusClass}`}>
                  {statusLabel}
                </span>
                <div className="mt-4 space-y-3">
                  <div>
                    <div className="mb-1 text-[11px] font-semibold text-stone-700">Correct</div>
                    <div className={`font-mono text-base break-words ${row.gold_label ? 'text-ink' : 'text-stone-600'}`}>
                    {row.gold_label || 'No correct label available'}
                    </div>
                  </div>
                  <div className="border-t border-current/20 pt-3">
                    <div className={`mb-1 text-[11px] font-semibold ${status === 'mismatch' ? 'text-red-800' : status === 'partial' ? 'text-amber-800' : 'text-stone-700'}`}>
                      Predicted
                    </div>
                    <div className={`font-mono text-base break-words ${status === 'mismatch' ? 'text-red-900' : 'text-ink'}`}>
                      {row.predicted_label || '—'}
                    </div>
                  </div>
                </div>
              </div>
            </li>
          )})}
        </ul>
        </div>
      )}
    </div>
  )
}

function FeedbackBatchPanel({
  projectId, dimensionName, currentPipelinePrompt, onRefresh, onCommitted,
}: {
  projectId: number
  dimensionName: string
  currentPipelinePrompt: string
  onRefresh: () => void
  onCommitted: () => Promise<void>
}) {
  const [state, setState] = useState<ApplyState>('idle')
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [drafts, setDrafts] = useState<DraftFeedback[]>([])
  const [oldPrompt, setOldPrompt] = useState('')
  const [newPrompt, setNewPrompt] = useState('')
  const [generatedRules, setGeneratedRules] = useState<MemoryRule[]>([])
  const [savedPrompt, setSavedPrompt] = useState('')
  const [showSavedPrompt, setShowSavedPrompt] = useState(false)
  const [error, setError] = useState('')
  const [reapplying, setReapplying] = useState(false)
  const savedPromptKey = `annotagent.humanFeedback.generatedPrompt.${projectId}.${dimensionName}`
  const draftsKey = `annotagent.humanFeedback.drafts.${projectId}.${dimensionName}`
  const savedPromptApplied = !!savedPrompt && savedPrompt.trim() === currentPipelinePrompt.trim()

  useEffect(() => {
    try {
      setSavedPrompt(localStorage.getItem(savedPromptKey) ?? '')
    } catch {
      setSavedPrompt('')
    }
    setShowSavedPrompt(false)
  }, [savedPromptKey])

  useEffect(() => {
    try {
      const raw = localStorage.getItem(draftsKey)
      const parsed = raw ? JSON.parse(raw) : []
      setDrafts(Array.isArray(parsed) ? parsed.filter(d => d?.text) : [])
    } catch {
      setDrafts([])
    }
    setOpen(false)
    setText('')
    setState('idle')
    setOldPrompt('')
    setNewPrompt('')
    setGeneratedRules([])
    setError('')
  }, [draftsKey])

  const saveDrafts = (next: DraftFeedback[]) => {
    setDrafts(next)
    try { localStorage.setItem(draftsKey, JSON.stringify(next)) } catch {}
  }

  const addDraft = () => {
    const trimmed = text.trim()
    if (!trimmed) return
    saveDrafts([...drafts, { id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, text: trimmed }])
    setText('')
    setOpen(false)
    setError('')
    setState('idle')
  }

  const removeDraft = (id: string) => {
    saveDrafts(drafts.filter(d => d.id !== id))
    setState('idle')
    setOldPrompt('')
    setNewPrompt('')
    setGeneratedRules([])
    setError('')
  }

  const handlePreview = async () => {
    setState('loading')
    setError('')
    setShowSavedPrompt(false)
    try {
      const res = await previewFeedbackBatch(projectId, dimensionName, drafts.map(d => d.text))
      setOldPrompt(res.old_prompt)
      setNewPrompt(res.new_prompt)
      setGeneratedRules(res.rules)
      setSavedPrompt(res.new_prompt)
      try { localStorage.setItem(savedPromptKey, res.new_prompt) } catch {}
      setState('preview')
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Preview failed')
      setState('error')
    }
  }

  const handleCommit = async () => {
    setState('committing')
    try {
      await commitFeedbackBatch(projectId, dimensionName, drafts.map(d => d.text), generatedRules, newPrompt)
      setSavedPrompt(newPrompt)
      try { localStorage.setItem(savedPromptKey, newPrompt) } catch {}
      saveDrafts([])
      setState('done')
      onRefresh()
      await onCommitted()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Commit failed')
      setState('error')
    }
  }

  const handleReapplySavedPrompt = async () => {
    if (!savedPrompt || savedPromptApplied) return
    setReapplying(true)
    setError('')
    try {
      await commitPrompt(projectId, dimensionName, savedPrompt)
      await onCommitted()
      setState('done')
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Re-apply failed')
      setState('error')
    } finally {
      setReapplying(false)
    }
  }

  const reset = () => {
    setState('idle')
    setOldPrompt('')
    setNewPrompt('')
    setGeneratedRules([])
    setError('')
    setShowSavedPrompt(false)
  }

  const generatedPromptPanel = showSavedPrompt && savedPrompt ? (
    <div className="mt-3 w-full border border-seam bg-paper/30 p-3 space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <div className="font-mono-editorial text-xs text-stone-500">
          Generated prompt for <em>{dimensionName}</em>
          {savedPromptApplied && <span className="ml-2 text-emerald-700">active</span>}
        </div>
        <div className="flex items-center gap-2">
          {!savedPromptApplied && (
            <button
              onClick={handleReapplySavedPrompt}
              disabled={reapplying}
              className="px-2 py-1 bg-violet-700 text-white text-xs font-medium disabled:opacity-40"
            >
              {reapplying ? 'Re-applying…' : 'Re-apply'}
            </button>
          )}
          <button
            onClick={() => setShowSavedPrompt(false)}
            className="font-mono-editorial text-xs text-stone-400 hover:text-ink"
          >
            hide
          </button>
        </div>
      </div>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words border border-seam bg-white p-3 font-mono text-xs leading-relaxed text-stone-800">
        {savedPrompt}
      </pre>
    </div>
  ) : null

  if (state === 'idle') {
    return (
      <div className="min-w-0 flex-1">
        {drafts.length > 0 && (
          <ul className="mt-2 divide-y divide-seam border border-seam bg-paper/30">
            {drafts.map((draft, idx) => (
              <li key={draft.id} className="flex items-start gap-3 px-3 py-2">
                <span className="font-mono-editorial text-xs text-stone-400 shrink-0">#{idx + 1}</span>
                <div className="min-w-0 flex-1 whitespace-pre-wrap text-xs leading-relaxed text-stone-700">{draft.text}</div>
                <button
                  onClick={() => removeDraft(draft.id)}
                  className="shrink-0 px-2 py-0.5 bg-red-50 border border-red-200 font-mono-editorial text-xs text-red-500 hover:bg-red-100 hover:text-red-700 transition-colors"
                >
                  delete
                </button>
              </li>
            ))}
          </ul>
        )}
        {open && (
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
            <div className="flex items-center gap-3">
              <button
                onClick={addDraft}
                disabled={!text.trim()}
                className="px-3 py-1.5 bg-ink text-cream text-xs font-medium disabled:opacity-40"
              >
                Add to batch
              </button>
              <button onClick={() => { setOpen(false); setText(''); setError('') }} className="font-mono-editorial text-xs text-stone-400 hover:text-ink">
                Cancel
              </button>
            </div>
          </div>
        )}
        {error && <p className="mt-2 font-mono-editorial text-xs text-red-600">{error}</p>}
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => setOpen(true)}
            className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 bg-stone-100 border border-stone-300 text-xs font-medium text-stone-700 hover:bg-stone-200 transition-colors"
          >
            <span className="font-mono">+</span> Add correction
          </button>
          <button
            onClick={handlePreview}
            disabled={drafts.length === 0}
            title={drafts.length === 0 ? 'Add at least one correction first' : undefined}
            className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 bg-violet-100 border border-violet-300 text-xs font-medium text-violet-700 hover:bg-violet-200 transition-colors disabled:bg-stone-50 disabled:border-stone-200 disabled:text-stone-400 disabled:cursor-not-allowed"
          >
            Generate prompt
          </button>
          {savedPrompt && (
            <button
              onClick={() => setShowSavedPrompt(v => !v)}
              className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 bg-stone-100 border border-stone-300 text-xs font-medium text-stone-700 hover:bg-stone-200 transition-colors"
            >
              Show generated prompt
            </button>
          )}
          {savedPrompt && !savedPromptApplied && (
            <button
              onClick={handleReapplySavedPrompt}
              disabled={reapplying}
              className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 bg-violet-700 text-white text-xs font-medium hover:bg-violet-800 transition-colors disabled:opacity-40"
            >
              {reapplying ? 'Re-applying…' : 'Re-apply generated prompt'}
            </button>
          )}
        </div>
        {generatedPromptPanel}
      </div>
    )
  }

  if (state === 'loading') {
    return <span className="font-mono-editorial text-xs text-stone-400">Generating preview…</span>
  }

  if (state === 'done') {
    return (
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono-editorial text-xs text-emerald-600">✓ Prompt updated</span>
          {savedPrompt && (
            <button
              onClick={() => setShowSavedPrompt(v => !v)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-stone-100 border border-stone-300 text-xs font-medium text-stone-700 hover:bg-stone-200 transition-colors"
            >
              Show generated prompt
            </button>
          )}
          {savedPrompt && !savedPromptApplied && (
            <button
              onClick={handleReapplySavedPrompt}
              disabled={reapplying}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-violet-700 text-white text-xs font-medium hover:bg-violet-800 transition-colors disabled:opacity-40"
            >
              {reapplying ? 'Re-applying…' : 'Re-apply generated prompt'}
            </button>
          )}
          <button onClick={reset} className="font-mono-editorial text-xs text-stone-400 hover:text-ink">
            done
          </button>
        </div>
        {generatedPromptPanel}
      </div>
    )
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
      <div className="font-mono-editorial text-xs text-stone-500 mb-2">
        Prompt diff for <em>{dimensionName}</em> — review before applying {drafts.length} correction{drafts.length !== 1 ? 's' : ''}
      </div>
      <DiffView oldText={oldPrompt} newText={newPrompt} />
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

function MemRow({ v, onDelete }: { v: MemoryVersion; onDelete: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <li>
      <div className="flex items-baseline gap-3 py-2 px-1 text-xs font-mono">
        <button onClick={() => setOpen(o => !o)} className="text-stone-400 w-3 shrink-0 text-left">
          {open ? '−' : '+'}
        </button>
        <button onClick={() => setOpen(o => !o)} className="text-left hover:text-ink shrink-0">
          v{String(v.version).padStart(3, '0')}
        </button>
        <span className="text-stone-400 font-mono-editorial">
          {v.created_at
            ? new Date(v.created_at).toLocaleString(undefined, {
                year: 'numeric', month: 'short', day: 'numeric',
                hour: '2-digit', minute: '2-digit', timeZone: 'UTC',
              }) + ' UTC'
            : '—'}
        </span>
        <button
          onClick={onDelete}
          className="ml-auto inline-flex items-center px-2 py-0.5 bg-red-50 border border-red-200 font-mono-editorial text-xs text-red-500 hover:bg-red-100 hover:text-red-700 transition-colors"
        >
          delete
        </button>
      </div>
      {open && (
        <div className="px-2 pb-3 space-y-3">
          {v.feedback_text
            ? (
              <div className="pl-3 border-l-2 border-stone-300 text-xs text-stone-700 leading-relaxed whitespace-pre-wrap">
                {v.feedback_text}
              </div>
            ) : (
              <div className="font-mono-editorial text-xs text-stone-400">No feedback text recorded.</div>
            )
          }
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
