import { useEffect, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  listPipelines, listDatasets, startJob, uploadDataset, estimateAnnotationRun, listJobs,
  listSeedDatasets, loadSeedDataset, listCodebooks,
  type AnnotationCostEstimate, type SeedDatasetInfo,
} from '../lib/api'
import type { Pipeline, PipelineStep, Dataset, Codebook, Job } from '../types'

function isSelfDisclosure(cb: Codebook | null | undefined): boolean {
  if (!cb) return false
  const n = (cb.name || '').toLowerCase()
  return n.includes('self-disclosure') || n.includes('self_disclosure') || n.includes('self disclosure')
}

export default function PipelineView() {
  const { id } = useParams<{ id: string }>()
  const projectId = Number(id)
  const navigate = useNavigate()

  const [pipeline, setPipeline] = useState<Pipeline | null>(null)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [testSeeds, setTestSeeds] = useState<SeedDatasetInfo[]>([])
  const [activeCb, setActiveCb] = useState<Codebook | null>(null)
  const [selectedDataset, setSelectedDataset] = useState<number | null>(null)
  const [expandedStep, setExpandedStep] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingSeed, setLoadingSeed] = useState<string | null>(null)
  const [estimate, setEstimate] = useState<AnnotationCostEstimate | null>(null)
  const [estimateLoading, setEstimateLoading] = useState(false)
  const [estimateError, setEstimateError] = useState('')
  const [jobs, setJobs] = useState<Job[]>([])

  const reload = () => Promise.all([
    listPipelines(projectId),
    listDatasets(projectId),
    listSeedDatasets(projectId),
    listCodebooks(projectId),
    listJobs(projectId),
  ]).then(([pipelines, ds, sd, cbs, js]) => {
    if (pipelines.length > 0) setPipeline(pipelines[pipelines.length - 1])
    setDatasets(ds)
    setTestSeeds(sd.filter(s => s.role === 'test'))
    setActiveCb(cbs.length > 0 ? cbs[cbs.length - 1] : null)
    setJobs(js)
    const nonGold = ds.filter(d => !d.is_gold)
    if (nonGold.length > 0 && !selectedDataset) {
      const testDs = nonGold.find(d => d.name.toLowerCase().includes('test set'))
      setSelectedDataset(testDs?.id ?? nonGold[0].id)
    }
  })

  useEffect(() => { reload() }, [projectId])

  useEffect(() => {
    if (!pipeline || !selectedDataset) {
      setEstimate(null)
      setEstimateError('')
      return
    }
    let cancelled = false
    setEstimateLoading(true)
    setEstimateError('')
    estimateAnnotationRun(projectId, pipeline.id, selectedDataset)
      .then(res => { if (!cancelled) setEstimate(res) })
      .catch(() => {
        if (!cancelled) {
          setEstimate(null)
          setEstimateError('Could not estimate this run yet.')
        }
      })
      .finally(() => { if (!cancelled) setEstimateLoading(false) })
    return () => { cancelled = true }
  }, [pipeline, selectedDataset, projectId])

  const handleLoadTestSeed = async (seedId: string) => {
    setLoadingSeed(seedId)
    try {
      const newDs = await loadSeedDataset(projectId, seedId)
      const ds = await listDatasets(projectId)
      setDatasets(ds)
      setSelectedDataset(newDs.id)
    } finally {
      setLoadingSeed(null)
    }
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const newDs = await uploadDataset(projectId, file, false)
    const ds = await listDatasets(projectId)
    setDatasets(ds)
    setSelectedDataset(newDs.id)
    e.target.value = ''
  }

  const handleRunAnnotation = async () => {
    if (!pipeline || !selectedDataset) return
    setLoading(true)
    try {
      const job = await startJob(projectId, selectedDataset, pipeline.id)
      navigate(`/projects/${projectId}/monitor/${job.id}`)
    } finally {
      setLoading(false)
    }
  }

  if (!pipeline) {
    return (
      <div className="border border-dashed border-seam bg-paper/40 py-16 text-center">
        <div className="font-mono-editorial text-stone-500 mb-2">No pipeline yet</div>
        <p className="text-stone-600 text-sm">
          Run <span className="font-medium text-ink">Generate pipeline</span> from the Setup page.
        </p>
      </div>
    )
  }

  const steps = pipeline.steps as PipelineStep[]

  return (
    <div className="space-y-12">
      {/* Masthead */}
      <header className="border-b border-seam pb-6">
        <div>
          <div className="font-mono-editorial text-stone-500 mb-2">
            Annotate · {steps.length} prompt{steps.length !== 1 ? 's' : ''}
          </div>
          <h1 className="text-4xl font-medium tracking-tight">
            Run the calibrated prompts on your data.
          </h1>
        </div>
      </header>

      {/* Prompt structure */}
      <section>
        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="font-mono-editorial text-stone-500">Selected prompts for labeling</div>
            <p className="mt-1 text-xs text-stone-500">
              The annotation run will use these active pipeline prompts, one for each codebook dimension.
            </p>
          </div>
          <Link
            to={`/projects/${projectId}/prompt-lab?tab=prompts`}
            className="text-xs font-medium text-violet-700 hover:text-violet-900"
          >
            Review or edit prompts →
          </Link>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2 pb-3">
          {steps.map((step, i) => {
            const title = step.dimensions.length === 1 ? step.dimensions[0] : step.name
            const showDimensionChips = step.dimensions.length > 1
            const promptTokens = approxTokens(step.prompt)
            return (
              <button
                key={i}
                onClick={() => setExpandedStep(expandedStep === i ? null : i)}
                className={`text-left bg-white border p-3 min-h-[92px] transition-all hover:border-ink ${
                  expandedStep === i ? 'border-ink shadow-[4px_4px_0_0_rgba(11,11,10,0.08)]' : 'border-emerald-200'
                }`}
              >
                <div className="flex items-center justify-between gap-3 mb-1.5">
                  <div className="font-mono-editorial text-stone-400">Dimension prompt</div>
                  <div className="font-mono-editorial text-violet-700">View</div>
                </div>
                <div className="font-medium tracking-tight truncate" title={title}>{title}</div>
                <div className="mt-1 font-mono text-[11px] text-stone-400">
                  Active prompt · ~{formatTokens(promptTokens)} tokens
                </div>
                {showDimensionChips && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {step.dimensions.map(dim => (
                      <span key={dim} className="px-2 py-0.5 bg-paper border border-seam text-stone-700 text-xs">
                        {dim}
                      </span>
                    ))}
                  </div>
                )}
                {step.gate && (
                  <div className="font-mono-editorial text-amber-700 mt-2">Gate · {step.gate}</div>
                )}
              </button>
            )
          })}
        </div>
      </section>

      {/* Prompt preview */}
      {expandedStep !== null && steps[expandedStep] && (
        <section className="border border-seam bg-white">
          <div className="flex items-center justify-between p-5 border-b border-seam">
            <div>
              <div className="font-mono-editorial text-stone-500 mb-1">
                Prompt
              </div>
              <h3 className="text-lg font-medium">{steps[expandedStep].name}</h3>
            </div>
            <button
              onClick={() => setExpandedStep(null)}
              className="font-mono-editorial text-stone-400 hover:text-ink"
            >
              Close
            </button>
          </div>
          <pre className="p-5 font-mono text-xs leading-relaxed overflow-auto max-h-96 whitespace-pre-wrap text-stone-700">
            {steps[expandedStep].prompt}
          </pre>
        </section>
      )}

      {/* Run */}
      <section className="border-t border-seam pt-8 space-y-8">
        <div className="border-l-4 border-ink bg-white px-4 py-3">
          <div className="text-xl font-medium text-ink">Data to label</div>
          <p className="mt-1 text-sm text-stone-600">
            Select or upload the unlabeled dataset AnnotAgent should annotate with these prompts.
          </p>
        </div>

        {/* Upload-your-own */}
        <div className="border border-violet-200 bg-violet-50/70 p-5">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between mb-4">
            <div className="font-mono-editorial text-violet-700">Upload your own data</div>
            <div className="text-xs text-violet-900/70">Recommended for real annotation runs</div>
          </div>
          <label className="block border-2 border-dashed border-violet-300 bg-white px-5 py-6 cursor-pointer hover:border-violet-500 hover:bg-violet-50/50 transition">
            <input type="file" accept=".csv,.json" className="hidden" onChange={handleUpload} />
            <div className="flex items-center justify-between gap-4">
              <div>
                <div className="text-lg font-medium text-ink">Choose a CSV or JSON file to label</div>
                <p className="text-sm text-stone-600 mt-1">Each row or item becomes one annotation target. After upload, AnnotAgent selects it and shows the run cost estimate.</p>
              </div>
              <span className="shrink-0 px-4 py-2 bg-ink text-cream text-sm font-medium">Choose file →</span>
            </div>
          </label>
          <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-3">
            <FormatNote
              title="Input format"
              body="CSV: include a text column named sentence, text, content, message, input, or utterance. Add context if you have it. JSON: use a list of strings or objects, or an object with items/data/rows/examples."
              sample={`text,context\n"I want to lose weight","health chat"`}
            />
            <FormatNote
              title="Output format"
              body="After annotation, results can be exported as CSV or JSON. Each output row keeps the original item and adds predicted labels across all codebook dimensions."
              sample={`item_id,content,Level Of Disclosure,Depth Of Disclosure\n42,"I want to lose weight",Low,Peripheral`}
            />
          </div>
        </div>

        {jobs.length > 0 && (
          <section className="border border-seam bg-white">
            <div className="flex items-baseline justify-between gap-4 px-4 py-3 border-b border-seam">
              <div>
                <div className="font-mono-editorial text-stone-500">Recent annotation runs</div>
                <p className="mt-1 text-xs text-stone-500">Completed runs are saved. Reopen results anytime without exporting first.</p>
              </div>
            </div>
            <div className="divide-y divide-seam">
              {jobs.slice(0, 5).map(job => {
                const dataset = datasets.find(d => d.id === job.dataset_id)
                const completed = job.status === 'completed'
                return (
                  <div key={job.id} className="grid grid-cols-12 gap-3 items-center px-4 py-3 text-sm">
                    <div className="col-span-4">
                      <div className="font-medium">Job № {job.id.toString().padStart(4, '0')}</div>
                      <div className="text-xs text-stone-500 truncate">{dataset?.name ?? `Dataset ${job.dataset_id}`}</div>
                    </div>
                    <div className="col-span-2 font-mono-editorial text-stone-500">{job.status}</div>
                    <div className="col-span-2 font-mono text-xs text-stone-500">
                      {job.completed_items.toLocaleString()} / {job.total_items.toLocaleString()} items
                    </div>
                    <div className="col-span-2 font-mono text-xs text-stone-500">
                      ${job.total_cost.toFixed(4)}
                    </div>
                    <div className="col-span-2 text-right">
                      <Link
                        to={`/projects/${projectId}/${completed ? 'results' : 'monitor'}/${job.id}`}
                        className="px-3 py-1.5 border border-ink text-ink text-xs font-medium hover:bg-ink hover:text-cream transition"
                      >
                        {completed ? 'View results' : 'Open run'}
                      </Link>
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        )}

        {/* Bundled unseen test sets — only relevant for the self-disclosure
            project (the rest of the test corpus belongs to that codebook). */}
        {testSeeds.length > 0 && isSelfDisclosure(activeCb) && (
          <div>
            <div className="font-mono-editorial text-stone-500 mb-1">
              Self-disclosure demo test sets
              <code className="ml-2 font-mono text-[11px] normal-case tracking-normal bg-paper px-1.5 py-0.5 border border-seam">assets/data/test/cleaned/</code>
            </div>
            <p className="mb-3 text-xs text-stone-500">
              Built-in held-out examples for the self-disclosure codebook. These are not files you uploaded.
            </p>
            <ul className="divide-y divide-seam border-y border-seam">
              {testSeeds.map(s => {
                const loaded = datasets.find(d => d.name === s.label)
                const isSelected = loaded && selectedDataset === loaded.id
                return (
                  <li key={s.id} className={`grid grid-cols-12 gap-4 py-4 items-center ${s.available ? '' : 'opacity-50'}`}>
                    <div className="col-span-7">
                      <div className="flex items-baseline gap-3">
                        <span className="font-medium">{s.label}</span>
                        <span className="font-mono-editorial text-blue-700">Unseen</span>
                      </div>
                      <p className="text-sm text-stone-600 mt-0.5">{s.description}</p>
                      <p className="font-mono text-[11px] text-stone-400 mt-1 truncate">{s.path}</p>
                    </div>
                    <div className="col-span-3 font-mono-editorial text-stone-400">
                      {s.role}
                    </div>
                    <div className="col-span-2 text-right">
                      {!s.available ? (
                        <span className="font-mono-editorial text-stone-400">file missing</span>
                      ) : isSelected ? (
                        <span className="font-mono-editorial text-emerald-700">selected ✓</span>
                      ) : loaded ? (
                        <button
                          onClick={() => setSelectedDataset(loaded.id)}
                          className="px-3 py-1.5 text-xs font-medium text-ink border border-seam hover:border-ink transition-colors"
                        >
                          Select
                        </button>
                      ) : (
                        <button
                          onClick={() => handleLoadTestSeed(s.id)}
                          disabled={loadingSeed === s.id}
                          className="px-3 py-1.5 text-xs font-medium text-ink border border-ink hover:bg-ink hover:text-cream disabled:opacity-50 transition-colors"
                        >
                          {loadingSeed === s.id ? 'Loading…' : 'Load & select'}
                        </button>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          </div>
        )}

        {/* Run */}
        <div className="flex items-end justify-between gap-6 flex-wrap">
          <div className="space-y-3">
            <div className="font-mono-editorial text-stone-500">
            {selectedDataset
              ? <>Selected data · <span className="text-ink">{datasets.find(d => d.id === selectedDataset)?.name ?? '—'}</span></>
              : 'Select or upload data above'}
            </div>
            {selectedDataset && (
              <CostEstimatePanel
                estimate={estimate}
                loading={estimateLoading}
                error={estimateError}
              />
            )}
          </div>
          <div className="flex items-center gap-2">
            <Link
              to={`/projects/${projectId}/prompt-lab?tab=prompts`}
              className="px-5 py-3 border border-ink bg-white text-ink text-sm font-medium hover:bg-paper transition-colors"
            >
              Back to prompts
            </Link>
            <button
              onClick={handleRunAnnotation}
              disabled={!selectedDataset || loading}
              className="group inline-flex items-center gap-3 px-6 py-3 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-40 transition-colors"
            >
              <span>{loading ? 'Starting…' : 'Run annotation'}</span>
              <span className="transition-transform group-enabled:group-hover:translate-x-1">→</span>
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}

function CostEstimatePanel({
  estimate, loading, error,
}: {
  estimate: AnnotationCostEstimate | null
  loading: boolean
  error: string
}) {
  if (loading) {
    return (
      <div className="border border-seam bg-paper/40 px-4 py-3 text-xs text-stone-500">
        Estimating tokens and cost…
      </div>
    )
  }
  if (error) {
    return (
      <div className="border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800">
        {error}
      </div>
    )
  }
  if (!estimate) return null

  return (
    <div className="border border-violet-200 bg-violet-50/70 px-4 py-3 max-w-3xl">
      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-2">
        <div>
          <div className="font-mono-editorial text-violet-700">Conservative estimated cost</div>
          <div className="text-xl font-semibold text-violet-950">{formatCost(estimate.estimated_cost)}</div>
        </div>
        <EstimateMetric label="LLM calls" value={estimate.n_calls.toLocaleString()} />
        <EstimateMetric label="Model" value={estimate.model} />
      </div>
      <p className="mt-2 text-xs leading-relaxed text-violet-900/75">
        Conservative pre-run estimate based on {estimate.n_items.toLocaleString()} items × {estimate.n_prompts} prompt{estimate.n_prompts === 1 ? '' : 's'}, prompt length, and a {estimate.sample_size}-item input sample. The final cost shown after annotation is measured from actual model usage.
      </p>
    </div>
  )
}

function EstimateMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono-editorial text-violet-700">{label}</div>
      <div className="text-sm font-medium text-violet-950">{value}</div>
    </div>
  )
}

function FormatNote({
  title, body, sample,
}: {
  title: string
  body: string
  sample: string
}) {
  return (
    <div className="border border-violet-200 bg-white/80 p-3">
      <div className="font-mono-editorial text-violet-700 mb-1">{title}</div>
      <p className="text-xs leading-relaxed text-stone-600">{body}</p>
      <pre className="mt-2 overflow-auto bg-paper px-3 py-2 font-mono text-[11px] leading-relaxed text-stone-700 border border-seam">
        {sample}
      </pre>
    </div>
  )
}

function formatCost(cost: number): string {
  if (cost < 0.01) return `$${cost.toFixed(4)}`
  return `$${cost.toFixed(2)}`
}

function formatTokens(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`
  return tokens.toLocaleString()
}

function approxTokens(text: string): number {
  return Math.max(1, Math.ceil((text || '').length / 4))
}
