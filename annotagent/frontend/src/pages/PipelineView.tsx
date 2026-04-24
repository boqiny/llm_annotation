import { useEffect, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  listPipelines, listDatasets, startJob,
  listSeedDatasets, loadSeedDataset,
  type SeedDatasetInfo,
} from '../lib/api'
import type { Pipeline, PipelineStep, Dataset } from '../types'

export default function PipelineView() {
  const { id } = useParams<{ id: string }>()
  const projectId = Number(id)
  const navigate = useNavigate()

  const [pipeline, setPipeline] = useState<Pipeline | null>(null)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [testSeeds, setTestSeeds] = useState<SeedDatasetInfo[]>([])
  const [selectedDataset, setSelectedDataset] = useState<number | null>(null)
  const [expandedStep, setExpandedStep] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingSeed, setLoadingSeed] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      listPipelines(projectId),
      listDatasets(projectId),
      listSeedDatasets(projectId),
    ]).then(([pipelines, ds, sd]) => {
      if (pipelines.length > 0) setPipeline(pipelines[pipelines.length - 1])
      setDatasets(ds)
      setTestSeeds(sd.filter(s => s.role === 'test'))
      const nonGold = ds.filter(d => !d.is_gold)
      // Prefer an unseen "Test set" dataset as the default annotation target;
      // fall back to any non-gold dataset.
      const testDs = nonGold.find(d => d.name.toLowerCase().includes('test set'))
      if (testDs) setSelectedDataset(testDs.id)
      else if (nonGold.length > 0) setSelectedDataset(nonGold[0].id)
    })
  }, [projectId])

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
      <header className="border-b border-seam pb-6 flex items-end justify-between gap-6 flex-wrap">
        <div>
          <div className="font-mono-editorial text-stone-500 mb-2">
            Pipeline · {pipeline.auto_generated ? 'auto-generated' : 'manually edited'}
          </div>
          <h1 className="text-4xl font-medium tracking-tight">
            {steps.length} step{steps.length !== 1 ? 's' : ''} in the annotator.
          </h1>
        </div>
        <Link
          to={`/projects/${projectId}/codebook`}
          className="px-4 py-2 text-sm font-medium text-ink border border-ink hover:bg-ink hover:text-cream transition-colors"
        >
          View codebook →
        </Link>
      </header>

      {/* Pipeline graph — horizontal editorial strip */}
      <section>
        <div className="font-mono-editorial text-stone-500 mb-4">Decomposition</div>
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
        <div className="font-mono-editorial text-stone-500">Run the annotator on unseen data</div>

        {/* Test sets — one-click load from data/test/cleaned/ */}
        {testSeeds.length > 0 && (
          <div>
            <div className="font-mono-editorial text-stone-500 mb-3">
              Unseen test sets <code className="ml-2 font-mono text-[11px] normal-case tracking-normal bg-paper px-1.5 py-0.5 border border-seam">data/test/cleaned/</code>
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

        <div className="flex items-end justify-between gap-6 flex-wrap">
          <label className="block">
            <span className="font-mono-editorial text-stone-500 block mb-1">
              Target dataset {datasets.filter(d => !d.is_gold).length === 0 && '· none loaded'}
            </span>
            <select
              value={selectedDataset ?? ''}
              onChange={e => setSelectedDataset(Number(e.target.value))}
              disabled={datasets.filter(d => !d.is_gold).length === 0}
              className="min-w-[320px] px-0 py-2 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-medium disabled:text-stone-400"
            >
              {datasets.filter(d => !d.is_gold).length === 0 && (
                <option value="">Load a test set above →</option>
              )}
              {datasets.filter(d => !d.is_gold).map(ds => (
                <option key={ds.id} value={ds.id}>{ds.name} ({ds.total_items.toLocaleString()} items)</option>
              ))}
            </select>
          </label>
          <button
            onClick={handleRunAnnotation}
            disabled={!selectedDataset || loading}
            className="group inline-flex items-center gap-3 px-6 py-3 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-40 transition-colors"
          >
            <span>{loading ? 'Starting…' : 'Run annotation'}</span>
            <span className="transition-transform group-enabled:group-hover:translate-x-1">→</span>
          </button>
        </div>
      </section>
    </div>
  )
}
