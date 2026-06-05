import { useEffect, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  listPipelines, listDatasets, startJob, decomposePipeline, uploadDataset,
  listSeedDatasets, loadSeedDataset, listCodebooks,
  type SeedDatasetInfo, type DecomposeMode,
} from '../lib/api'
import type { Pipeline, PipelineStep, Dataset, Codebook } from '../types'

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
  const [decomposing, setDecomposing] = useState<DecomposeMode | null>(null)

  const reload = () => Promise.all([
    listPipelines(projectId),
    listDatasets(projectId),
    listSeedDatasets(projectId),
    listCodebooks(projectId),
  ]).then(([pipelines, ds, sd, cbs]) => {
    if (pipelines.length > 0) setPipeline(pipelines[pipelines.length - 1])
    setDatasets(ds)
    setTestSeeds(sd.filter(s => s.role === 'test'))
    setActiveCb(cbs.length > 0 ? cbs[cbs.length - 1] : null)
    const nonGold = ds.filter(d => !d.is_gold)
    if (nonGold.length > 0 && !selectedDataset) {
      const testDs = nonGold.find(d => d.name.toLowerCase().includes('test set'))
      setSelectedDataset(testDs?.id ?? nonGold[0].id)
    }
  })

  useEffect(() => { reload() }, [projectId])

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

  const handleDecompose = async (mode: DecomposeMode) => {
    setDecomposing(mode)
    try {
      const p = await decomposePipeline(projectId, mode)
      setPipeline(p)
    } finally {
      setDecomposing(null)
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
  const currentMode: DecomposeMode = steps.length === 1
    ? 'all_together'
    : steps.every(s => s.dimensions.length === 1) ? 'per_dimension' : 'auto'

  return (
    <div className="space-y-12">
      {/* Masthead */}
      <header className="border-b border-seam pb-6">
        <div>
          <div className="font-mono-editorial text-stone-500 mb-2">
            Annotate · {steps.length} step{steps.length !== 1 ? 's' : ''} · {currentMode.replace('_', ' ')}
          </div>
          <h1 className="text-4xl font-medium tracking-tight">
            Run the calibrated prompts on your data.
          </h1>
        </div>
      </header>

      {/* Decomposition strategy switch */}
      <section>
        <div className="flex items-baseline justify-between mb-3">
          <div className="font-mono-editorial text-stone-500">Decomposition</div>
          <div className="flex items-center gap-2 text-xs">
            <span className="font-mono-editorial text-stone-500">label as:</span>
            <ModeButton
              active={currentMode === 'per_dimension'}
              busy={decomposing === 'per_dimension'}
              onClick={() => handleDecompose('per_dimension')}
              label="one dimension at a time"
            />
            <ModeButton
              active={currentMode === 'all_together'}
              busy={decomposing === 'all_together'}
              onClick={() => handleDecompose('all_together')}
              label="all together"
            />
          </div>
        </div>

        <div className="flex items-stretch gap-0 overflow-x-auto pb-3">
          {steps.map((step, i) => (
            <div key={i} className="flex items-stretch">
              <button
                onClick={() => setExpandedStep(expandedStep === i ? null : i)}
                className={`text-left bg-white border border-seam p-5 min-w-[240px] transition-all hover:border-ink ${
                  expandedStep === i ? 'border-ink shadow-[4px_4px_0_0_rgba(11,11,10,0.08)]' : ''
                }`}
              >
                <div className="font-mono-editorial text-stone-400 mb-2">
                  Step {(i + 1).toString().padStart(2, '0')}
                </div>
                <div className="font-medium mb-3 tracking-tight">{step.name}</div>
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {step.dimensions.map(dim => (
                    <span key={dim} className="px-2 py-0.5 bg-paper border border-seam text-stone-700 text-xs">
                      {dim}
                    </span>
                  ))}
                </div>
                {step.gate && (
                  <div className="font-mono-editorial text-amber-700 mt-2">Gate · {step.gate}</div>
                )}
              </button>
              {i < steps.length - 1 && (
                <div className="self-center px-3 font-mono text-stone-300 text-xl">→</div>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* Prompt preview */}
      {expandedStep !== null && steps[expandedStep] && (
        <section className="border border-seam bg-white">
          <div className="flex items-center justify-between p-5 border-b border-seam">
            <div>
              <div className="font-mono-editorial text-stone-500 mb-1">
                Prompt · step {(expandedStep + 1).toString().padStart(2, '0')}
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
        <div className="font-mono-editorial text-stone-500">Pick the data to annotate</div>

        {/* Bundled unseen test sets — only relevant for the self-disclosure
            project (the rest of the test corpus belongs to that codebook). */}
        {testSeeds.length > 0 && isSelfDisclosure(activeCb) && (
          <div>
            <div className="font-mono-editorial text-stone-500 mb-3">
              Bundled unseen test sets <code className="ml-2 font-mono text-[11px] normal-case tracking-normal bg-paper px-1.5 py-0.5 border border-seam">assets/data/test/cleaned/</code>
            </div>
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

        {/* Upload-your-own */}
        <div>
          <div className="font-mono-editorial text-stone-500 mb-3">Upload your own data</div>
          <label className="block border border-dashed border-seam bg-paper/40 px-5 py-6 cursor-pointer hover:border-stone-400">
            <input type="file" accept=".csv,.json" className="hidden" onChange={handleUpload} />
            <div className="flex items-center justify-between gap-4">
              <div>
                <div className="font-medium text-ink">Click to upload CSV or JSON</div>
                <p className="text-xs text-stone-500 mt-0.5">Each row / item is one annotation target. Goes straight into the dataset list below.</p>
              </div>
              <span className="font-mono-editorial text-stone-500">choose file →</span>
            </div>
          </label>
        </div>

        {/* Run */}
        <div className="flex items-end justify-between gap-6 flex-wrap">
          <div className="font-mono-editorial text-stone-500">
            {selectedDataset
              ? <>Selected · <span className="text-ink">{datasets.find(d => d.id === selectedDataset)?.name ?? '—'}</span></>
              : 'Pick or upload a dataset above'}
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

function ModeButton({
  active, busy, onClick, label,
}: { active: boolean; busy: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className={`px-2 py-1 border ${
        active ? 'border-ink bg-ink text-cream' : 'border-seam text-stone-600 hover:border-stone-400 hover:text-ink'
      } disabled:opacity-50 transition-colors`}
    >
      {busy ? 'switching…' : label}
    </button>
  )
}
