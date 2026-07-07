import { useEffect, useRef, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  listPipelines, listDatasets, startJob, listJobs,
  listCodebooks,
  extractInputPreview, extractInputCommit,
  type ExtractPreview,
} from '../lib/api'
import type { Pipeline, PipelineStep, Dataset, Codebook, Job } from '../types'
import { APP_NAME } from '../lib/brand'

export default function PipelineView() {
  const { id } = useParams<{ id: string }>()
  const projectId = Number(id)
  const navigate = useNavigate()

  const [pipeline, setPipeline] = useState<Pipeline | null>(null)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [activeCb, setActiveCb] = useState<Codebook | null>(null)
  const [selectedDataset, setSelectedDataset] = useState<number | null>(null)
  const [expandedStep, setExpandedStep] = useState<number | null>(null)
  const previewRef = useRef<HTMLElement | null>(null)
  // When a prompt card is opened, scroll its preview into view so it's obvious
  // something happened (the preview renders below the card grid).
  useEffect(() => {
    if (expandedStep !== null) {
      previewRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [expandedStep])
  const [loading, setLoading] = useState(false)
  const [jobs, setJobs] = useState<Job[]>([])

  const reload = () => Promise.all([
    listPipelines(projectId),
    listDatasets(projectId),
    listCodebooks(projectId),
    listJobs(projectId),
  ]).then(([pipelines, ds, cbs, js]) => {
    if (pipelines.length > 0) setPipeline(pipelines[pipelines.length - 1])
    setDatasets(ds)
    setActiveCb(cbs.length > 0 ? cbs[cbs.length - 1] : null)
    setJobs(js)
    const nonGold = ds.filter(d => !d.is_gold)
    if (nonGold.length > 0 && !selectedDataset) {
      const testDs = nonGold.find(d => d.name.toLowerCase().includes('test set'))
      setSelectedDataset(testDs?.id ?? nonGold[0].id)
    }
  })

  useEffect(() => { reload() }, [projectId])

  const [inputPreview, setInputPreview] = useState<ExtractPreview | null>(null)
  const [contentCol, setContentCol] = useState('')
  const [extracting, setExtracting] = useState(false)
  const [committing, setCommitting] = useState(false)
  const [extractErr, setExtractErr] = useState('')

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; e.target.value = ''
    if (!file) return
    setExtracting(true); setExtractErr(''); setInputPreview(null)
    try {
      const p = await extractInputPreview(projectId, file)
      setInputPreview(p)
      setContentCol(p.suggested_content_column || p.columns[0] || '')
    } catch (err: any) {
      setExtractErr(err?.response?.data?.detail || err?.message || 'Could not read the file')
    } finally {
      setExtracting(false)
    }
  }

  const handleConfirmInput = async () => {
    if (!inputPreview || !contentCol) return
    setCommitting(true); setExtractErr('')
    try {
      const ds = await extractInputCommit(projectId, {
        filename: inputPreview.filename, file_type: inputPreview.file_type,
        rows: inputPreview.rows, content_column: contentCol,
      })
      setDatasets(await listDatasets(projectId))
      setSelectedDataset(ds.id)
      setInputPreview(null)
    } catch (err: any) {
      setExtractErr(err?.response?.data?.detail || err?.message || 'Could not load the data')
    } finally {
      setCommitting(false)
    }
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

      <section className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <RunStepNote
          n="1"
          title="Check prompts"
          body="Use this page when the prompts look ready. Open a dimension prompt if you want one last read before spending tokens."
          tone="emerald"
        />
        <RunStepNote
          n="2"
          title="Choose data"
          body="Upload your real dataset, or select a loaded test dataset for a dry run. Unselect if you are only inspecting prompts."
          tone="violet"
        />
        <RunStepNote
          n="3"
          title="Run and review"
          body="Run annotation, then review the results. Completed jobs stay available in Recent annotation runs."
          tone="sky"
        />
      </section>

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
        <section ref={previewRef} className="border border-seam bg-white scroll-mt-4">
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
            Select or upload the unlabeled dataset {APP_NAME} should annotate with these prompts.
          </p>
          <p className="mt-2 text-xs font-medium text-violet-700">
            Best moment to run: after you have accepted the codebook, reviewed prompts, and decided which dataset should receive predicted labels.
          </p>
        </div>

        {/* Upload-your-own */}
        <div className="border border-violet-200 bg-violet-50/70 p-5">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between mb-4">
            <div className="font-mono-editorial text-violet-700">Upload your own data</div>
            <div className="text-xs text-violet-900/70">Recommended for real annotation runs</div>
          </div>
          <div className="mb-3 border border-violet-200 bg-white/80 px-3 py-2 text-xs leading-relaxed text-violet-900">
            Use this for the dataset you want {APP_NAME} to label now. Labeled/gold examples belong in Setup or Improve; this upload is for annotation inputs.
          </div>
          <label className={`block border-2 border-dashed border-violet-300 bg-white px-5 py-6 cursor-pointer hover:border-violet-500 hover:bg-violet-50/50 transition ${extracting ? 'opacity-60 pointer-events-none' : ''}`}>
            <input type="file" accept=".csv,.json" className="hidden" onChange={handleUpload} disabled={extracting} />
            <div className="flex items-center justify-between gap-4">
              <div>
                <div className="text-lg font-medium text-ink">{extracting ? 'Reading your file…' : 'Choose a CSV or JSON file to label'}</div>
                <p className="text-sm text-stone-600 mt-1">Messy spreadsheet is fine — {APP_NAME} finds the text column, you confirm it, then it loads.</p>
              </div>
              <span className="shrink-0 px-4 py-2 bg-ink text-cream text-sm font-medium">{extracting ? '…' : 'Choose file →'}</span>
            </div>
          </label>

          {extractErr && <div className="mt-3 border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{extractErr}</div>}

          {inputPreview && (
            <div className="mt-3 border border-seam bg-white p-4 space-y-3">
              <div className="flex items-baseline justify-between gap-3 flex-wrap">
                <div className="text-sm font-medium text-ink">Confirm the text column to annotate</div>
                <span className="font-mono-editorial text-stone-400 text-[11px]">{inputPreview.filename} · {inputPreview.n_rows.toLocaleString()} rows</span>
              </div>
              <div className="flex items-center gap-2 flex-wrap text-sm">
                <span className="text-stone-600">Text to label:</span>
                <select
                  value={contentCol}
                  onChange={e => setContentCol(e.target.value)}
                  className="bg-paper border border-seam px-2 py-1 text-sm focus:outline-none focus:border-ink"
                >
                  {inputPreview.columns.map(c => (
                    <option key={c} value={c}>{c}{c === inputPreview.suggested_content_column ? '  (suggested)' : ''}</option>
                  ))}
                </select>
              </div>
              <div className="overflow-auto border border-seam">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-paper/70 font-mono-editorial text-stone-500">
                      {inputPreview.columns.map(c => (
                        <th key={c} className={`px-2 py-1.5 text-left whitespace-nowrap ${c === contentCol ? 'bg-violet-100 text-violet-900' : ''}`}>
                          {c}{c === contentCol ? ' ←' : ''}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-seam">
                    {inputPreview.sample_rows.map((r, i) => (
                      <tr key={i}>
                        {inputPreview.columns.map(c => (
                          <td key={c} className={`px-2 py-1.5 align-top max-w-[260px] truncate ${c === contentCol ? 'bg-violet-50 text-stone-900 font-medium' : 'text-stone-500'}`} title={String(r[c] ?? '')}>
                            {String(r[c] ?? '')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex flex-wrap gap-2">
                <button onClick={handleConfirmInput} disabled={committing || !contentCol}
                  className="px-3 py-1.5 text-sm font-medium border border-ink bg-ink text-cream hover:opacity-90 disabled:opacity-50">
                  {committing ? 'Loading…' : 'Use this column & load →'}
                </button>
                <button onClick={() => { setInputPreview(null); setExtractErr('') }} disabled={committing}
                  className="px-3 py-1.5 text-sm font-medium border border-seam text-stone-600 hover:bg-paper disabled:opacity-50">
                  Cancel
                </button>
              </div>
            </div>
          )}
          <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-3">
            <FormatNote
              title="Input format"
              body="CSV: include a text column named sentence, text, content, message, input, or utterance. Add context if you have it. JSON: use a list of strings or objects, or an object with items/data/rows/examples."
              sample={`text,context\n"I want to lose weight","health chat"`}
            />
            <FormatNote
              title="Output format"
              body="After annotation, results can be exported as CSV or JSON. Each output row keeps the original item and adds a column for every codebook dimension — the same schema as your labeled data."
              sample={(() => {
                const dims = activeCb?.dimensions ?? []
                if (!dims.length) return `item_id,content,Level Of Disclosure,Depth Of Disclosure\n42,"I want to lose weight",Low,Peripheral`
                const header = `item_id,content,${dims.map(d => d.name).join(',')}`
                const row = `42,"I want to lose weight",${dims.map(d => d.labels?.[0]?.name ?? '…').join(',')}`
                return `${header}\n${row}`
              })()}
            />
          </div>
        </div>

        {jobs.length > 0 && (
          <section className="border border-seam bg-white">
            <div className="flex items-baseline justify-between gap-4 px-4 py-3 border-b border-seam">
              <div>
                <div className="font-mono-editorial text-stone-500">Recent annotation runs</div>
                <p className="mt-1 text-xs text-stone-500">Completed runs are saved. The source label shows where the run was started.</p>
              </div>
            </div>
            <div className="grid grid-cols-12 gap-3 px-4 py-2 border-b border-seam bg-paper/40 font-mono-editorial text-xs text-stone-500">
              <div className="col-span-3">Run</div>
              <div className="col-span-2">Created from</div>
              <div className="col-span-2">Status</div>
              <div className="col-span-3">Items</div>
              <div className="col-span-2 text-right">Results</div>
            </div>
            <div className="divide-y divide-seam">
              {jobs.slice(0, 5).map(job => {
                const dataset = datasets.find(d => d.id === job.dataset_id)
                const completed = job.status === 'completed'
                const source = runSourceDisplay(job.source)
                return (
                  <div key={job.id} className="grid grid-cols-12 gap-3 items-center px-4 py-3 text-sm">
                    <div className="col-span-3">
                      <div className="font-medium">Job № {job.id.toString().padStart(4, '0')}</div>
                      <div className="text-xs text-stone-500 truncate">{dataset?.name ?? `Dataset ${job.dataset_id}`}</div>
                    </div>
                    <div className="col-span-2">
                      <span className={`px-2 py-0.5 border text-xs ${source.className}`}>
                        {source.label}
                      </span>
                    </div>
                    <div className="col-span-2 font-mono-editorial text-stone-500">{job.status}</div>
                    <div className="col-span-3 font-mono text-xs text-stone-500">
                      {job.completed_items.toLocaleString()} / {job.total_items.toLocaleString()} items
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

        {/* Run */}
        <div className="flex items-end justify-between gap-6 flex-wrap">
          <div className="space-y-3">
            {datasets.filter(d => !d.is_gold).length > 0 && (
              <div>
                <label className="font-mono-editorial text-stone-500 block mb-1 text-xs">
                  Loaded data to label
                </label>
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    value={selectedDataset ?? ''}
                    onChange={e => setSelectedDataset(e.target.value ? Number(e.target.value) : null)}
                    className="min-w-[280px] max-w-full bg-white border border-seam px-3 py-2 text-sm focus:outline-none focus:border-ink"
                  >
                    {datasets.filter(d => !d.is_gold).map(d => (
                      <option key={d.id} value={d.id}>
                        {d.name} · {d.total_items.toLocaleString()} items
                      </option>
                    ))}
                  </select>
                  {selectedDataset && (
                    <button
                      type="button"
                      onClick={() => setSelectedDataset(null)}
                      className="px-3 py-2 border border-stone-300 bg-white text-stone-700 text-sm font-medium hover:border-ink hover:text-ink transition"
                    >
                      Unselect
                    </button>
                  )}
                </div>
              </div>
            )}
            <div className="font-mono-editorial text-stone-500">
            {selectedDataset
              ? <>Selected data · <span className="text-ink">{datasets.find(d => d.id === selectedDataset)?.name ?? '—'}</span></>
              : 'Select or upload data above'}
            </div>
            {!selectedDataset && (
              <div className="border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900">
                No data is selected, so {APP_NAME} will not start an annotation run. Choose a loaded dataset or upload a new one when you are ready.
              </div>
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

function RunStepNote({
  n, title, body, tone,
}: {
  n: string
  title: string
  body: string
  tone: 'emerald' | 'violet' | 'sky'
}) {
  const styles = {
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-950 shadow-[0_0_0_1px_rgba(16,185,129,0.08),0_0_24px_rgba(16,185,129,0.12)]',
    violet: 'border-violet-200 bg-violet-50 text-violet-950 shadow-[0_0_0_1px_rgba(139,92,246,0.08),0_0_24px_rgba(139,92,246,0.12)]',
    sky: 'border-sky-200 bg-sky-50 text-sky-950 shadow-[0_0_0_1px_rgba(14,165,233,0.08),0_0_24px_rgba(14,165,233,0.12)]',
  }[tone]
  const dot = {
    emerald: 'bg-emerald-500',
    violet: 'bg-violet-500',
    sky: 'bg-sky-500',
  }[tone]
  return (
    <div className={`relative overflow-hidden border px-4 py-3 ${styles}`}>
      <span className={`absolute left-0 top-0 h-full w-1 ${dot}`} />
      <div className="flex items-baseline gap-3">
        <span className="font-mono-editorial text-xs opacity-70">{n}</span>
        <div className="font-medium">{title}</div>
      </div>
      <p className="mt-2 text-xs leading-relaxed opacity-80">{body}</p>
    </div>
  )
}

function runSourceDisplay(source: string | null | undefined): { label: string; className: string } {
  if (source === 'human_feedback') {
    return { label: 'Human feedback', className: 'border-sky-200 bg-sky-50 text-sky-800' }
  }
  if (source === 'improve') {
    return { label: 'Improve page', className: 'border-amber-200 bg-amber-50 text-amber-800' }
  }
  if (source === 'annotation') {
    return { label: 'Annotation page', className: 'border-emerald-200 bg-emerald-50 text-emerald-800' }
  }
  return { label: 'Older run', className: 'border-stone-200 bg-paper text-stone-600' }
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


function formatTokens(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`
  return tokens.toLocaleString()
}

function approxTokens(text: string): number {
  return Math.max(1, Math.ceil((text || '').length / 4))
}
