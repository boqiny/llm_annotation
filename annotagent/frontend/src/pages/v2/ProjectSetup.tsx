/* ProjectSetup — v2 redesign.
   Layout: 3-step sidebar (codebook / data / model) + main pane.
   Sticky footer with "Generate pipeline" button always visible.
   Reuses CodebookDraftWizard from v1 unchanged. */
import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  getProject, updateProject, listPresets, listCodebooks,
  uploadDataset, listDatasets, decomposePipeline,
  listSeedDatasets, loadSeedDataset, getBackendConfig,
  type SeedDatasetInfo, type BackendConfig,
} from '../../lib/api'
import type { Project, Codebook, Dataset, PresetInfo } from '../../types'
import CodebookDraftWizard from '../../components/CodebookDraftWizard'

type Step = 'codebook' | 'data' | 'model'

function isSelfDisclosure(cb: Codebook | undefined | null): boolean {
  if (!cb) return false
  const n = (cb.name || '').toLowerCase()
  return n.includes('self-disclosure') || n.includes('self_disclosure') || n.includes('self disclosure')
}

export default function ProjectSetupV2() {
  const { id } = useParams<{ id: string }>()
  const projectId = Number(id)
  const navigate = useNavigate()

  const [project, setProject] = useState<Project | null>(null)
  const [presets, setPresets] = useState<PresetInfo[]>([])
  const [codebooks, setCodebooks] = useState<Codebook[]>([])
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [seeds, setSeeds] = useState<SeedDatasetInfo[]>([])
  const [backendCfg, setBackendCfg] = useState<BackendConfig | null>(null)
  const [llmProvider, setLlmProvider] = useState('openai')
  const [llmModel, setLlmModel] = useState('gpt-5.4-mini')
  const [apiKey, setApiKey] = useState('')
  const [step, setStep] = useState<Step>('codebook')
  const [loading, setLoading] = useState(false)
  const [loadingSeed, setLoadingSeed] = useState<string | null>(null)
  const [wizardMode, setWizardMode] = useState(false)

  const loadData = useCallback(async () => {
    const [p, pr, cb, ds, sd, cfg] = await Promise.all([
      getProject(projectId),
      listPresets(projectId),
      listCodebooks(projectId),
      listDatasets(projectId),
      listSeedDatasets(projectId),
      getBackendConfig().catch(() => null),
    ])
    setProject(p); setPresets(pr); setCodebooks(cb); setDatasets(ds); setSeeds(sd); setBackendCfg(cfg)
    setLlmProvider(p.llm_provider); setLlmModel(p.llm_model)
  }, [projectId])

  useEffect(() => { loadData() }, [loadData])

  const handleDataUpload = async (e: React.ChangeEvent<HTMLInputElement>, isGold: boolean) => {
    const file = e.target.files?.[0]; if (!file) return
    await uploadDataset(projectId, file, isGold)
    setDatasets(await listDatasets(projectId))
  }
  const handleLoadSeed = async (seedId: string) => {
    setLoadingSeed(seedId)
    try { await loadSeedDataset(projectId, seedId); setDatasets(await listDatasets(projectId)) }
    finally { setLoadingSeed(null) }
  }
  const handleSaveLLM = async () => {
    const patch: Record<string, string> = { llm_provider: llmProvider, llm_model: llmModel }
    if (apiKey) patch.api_key = apiKey
    await updateProject(projectId, patch)
  }
  const handleGeneratePipeline = async () => {
    setLoading(true)
    try {
      await handleSaveLLM()
      await decomposePipeline(projectId)
      navigate(`/projects/${projectId}/prompt-lab`)
    } finally { setLoading(false) }
  }

  if (!project) return <div className="font-mono-editorial text-stone-400 py-24 text-center">Loading…</div>

  const activeCb = codebooks[codebooks.length - 1]
  const hasDataset = datasets.length > 0
  const keyOK = envKeyAvailable(backendCfg, llmProvider) || apiKey.length > 0
  const canGenerate = !!activeCb && keyOK
  const missing: string[] = []
  if (!activeCb) missing.push('codebook')
  if (!keyOK) missing.push(`${llmProvider === 'anthropic' ? 'anthropic' : 'openai'} key`)

  return (
    <div className="space-y-4 pb-24">
      {/* Compact header */}
      <header className="flex items-baseline justify-between gap-4 border-b border-seam pb-3">
        <div>
          <div className="font-mono-editorial text-stone-500 text-xs mb-0.5">
            Project · {String(project.id).padStart(3, '0')}
          </div>
          <h1 className="text-2xl font-medium tracking-tight">{project.name}</h1>
        </div>
        {project.description && (
          <div className="font-mono-editorial text-stone-500 text-xs max-w-md text-right">
            {project.description}
          </div>
        )}
      </header>

      {/* Sidebar (fixed width) + flex-1 main. Avoids grid col-span ambiguity. */}
      <div className="flex flex-col md:flex-row gap-6">
        {/* Step rail */}
        <aside className="md:w-52 shrink-0">
          <ol className="space-y-1">
            <StepLink n="01" label="Codebook" hint="label schema"
                      active={step === 'codebook'} done={!!activeCb} onClick={() => setStep('codebook')} />
            <StepLink n="02" label="Data" hint="optional"
                      active={step === 'data'} done={hasDataset} onClick={() => setStep('data')} />
            <StepLink n="03" label="Model" hint="LLM + key"
                      active={step === 'model'} done={keyOK} onClick={() => setStep('model')} />
          </ol>
        </aside>

        {/* Main pane */}
        <main className="flex-1 min-w-0">
          {step === 'codebook' && (
            <CodebookStep
              activeCb={activeCb}
              wizardMode={wizardMode}
              setWizardMode={setWizardMode}
              presets={presets}
              projectId={projectId}
              onAccepted={() => { setWizardMode(false); loadData() }}
            />
          )}
          {step === 'data' && (
            <DataStep
              activeCb={activeCb}
              seeds={seeds}
              datasets={datasets}
              loadingSeed={loadingSeed}
              onLoadSeed={handleLoadSeed}
              onUpload={handleDataUpload}
            />
          )}
          {step === 'model' && (
            <ModelStep
              backendCfg={backendCfg}
              llmProvider={llmProvider}
              llmModel={llmModel}
              apiKey={apiKey}
              setLlmProvider={setLlmProvider}
              setLlmModel={setLlmModel}
              setApiKey={setApiKey}
            />
          )}
        </main>
      </div>

      {/* Sticky footer */}
      <div className="fixed bottom-0 left-0 right-0 bg-cream border-t border-seam">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between gap-4">
          <div className="font-mono-editorial text-stone-500 text-xs">
            {missing.length === 0
              ? <span className="text-emerald-700">Ready to generate pipeline.</span>
              : <>Still need: <span className="text-ink">{missing.join(' · ')}</span></>
            }
          </div>
          <button
            onClick={handleGeneratePipeline}
            disabled={!canGenerate || loading}
            className="px-5 py-2 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-40"
          >
            {loading ? 'Generating…' : 'Generate pipeline →'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ─── Step rail ─────────────────────────────────────────────── */

function StepLink({
  n, label, hint, active, done, onClick,
}: { n: string; label: string; hint?: string; active: boolean; done: boolean; onClick: () => void }) {
  return (
    <li>
      <button onClick={onClick}
              className={`w-full px-3 py-2 text-left border-l-2 transition-colors flex items-baseline gap-3 ${
                active ? 'border-ink bg-paper' : 'border-transparent hover:bg-paper/60'
              }`}>
        <span className={`font-mono-editorial text-xs ${active ? 'text-ink' : 'text-stone-400'}`}>{n}</span>
        <span className={`font-medium ${active ? 'text-ink' : 'text-stone-700'}`}>{label}</span>
        {done && <span className="ml-auto font-mono-editorial text-emerald-700 text-xs">✓</span>}
        {!done && hint && <span className="ml-auto font-mono-editorial text-stone-400 text-[11px]">{hint}</span>}
      </button>
    </li>
  )
}

/* ─── Steps ─────────────────────────────────────────────────── */

function CodebookStep({
  activeCb, wizardMode, setWizardMode, presets, projectId, onAccepted,
}: {
  activeCb?: Codebook
  wizardMode: boolean
  setWizardMode: (b: boolean) => void
  presets: PresetInfo[]
  projectId: number
  onAccepted: () => void
}) {
  if (activeCb && !wizardMode) {
    return (
      <div className="border border-seam bg-white">
        {/* Top toolbar: actions on the right, info underneath. Two rows so
            buttons never collide with the heading on narrow widths. */}
        <div className="px-4 pt-3 pb-4 border-b border-seam">
          <div className="flex items-center justify-between gap-3 mb-2">
            <div className="font-mono-editorial text-stone-500 text-xs">Active codebook</div>
            <div className="flex items-center gap-2 shrink-0">
              <Link to={`/projects/${projectId}/codebook`}
                    className="px-3 py-1 text-xs font-medium text-ink border border-ink hover:bg-ink hover:text-cream">
                View →
              </Link>
              <button onClick={() => setWizardMode(true)}
                      className="px-3 py-1 text-xs font-medium text-stone-600 border border-seam hover:border-stone-400">
                Replace
              </button>
            </div>
          </div>
          <h3 className="text-lg font-medium tracking-tight leading-snug">{activeCb.name}</h3>
          {activeCb.description && (
            <p className="text-sm text-stone-600 mt-1 leading-relaxed">{activeCb.description}</p>
          )}
        </div>
        <ul className="divide-y divide-seam">
          {activeCb.dimensions.map((dim, i) => (
            <li key={dim.id} className="px-4 py-2 flex items-baseline gap-3">
              <span className="font-mono-editorial text-stone-400 text-xs w-7 shrink-0">{String(i + 1).padStart(2, '0')}</span>
              <span className="font-medium">{dim.name}</span>
              <span className="font-mono-editorial text-stone-400 text-xs">{dim.dim_type}</span>
              <span className="font-mono-editorial text-stone-400 text-xs">· {dim.labels.length} labels</span>
            </li>
          ))}
        </ul>
      </div>
    )
  }
  return (
    <>
      {activeCb && wizardMode && (
        <div className="mb-3 flex items-center justify-between text-xs border border-amber-200 bg-amber-50/60 px-3 py-2">
          <div>Replacing <span className="font-medium">{activeCb.name}</span></div>
          <button onClick={() => setWizardMode(false)} className="font-mono-editorial text-stone-500 hover:text-ink">cancel</button>
        </div>
      )}
      <CodebookDraftWizard projectId={projectId} presets={presets} onAccepted={onAccepted} />
    </>
  )
}

function DataStep({
  activeCb, seeds, datasets, loadingSeed, onLoadSeed, onUpload,
}: {
  activeCb?: Codebook
  seeds: SeedDatasetInfo[]
  datasets: Dataset[]
  loadingSeed: string | null
  onLoadSeed: (id: string) => void
  onUpload: (e: React.ChangeEvent<HTMLInputElement>, isGold: boolean) => void
}) {
  return (
    <div className="space-y-4">
      <div className="font-mono-editorial text-stone-500 text-xs">
        Labeled examples drive the Improve step. Skip if you'll add later.
      </div>

      {seeds.length > 0 && isSelfDisclosure(activeCb) && (
        <div>
          <div className="font-mono-editorial text-stone-500 text-xs mb-2">Bundled · self-disclosure</div>
          <ul className="divide-y divide-seam border-y border-seam">
            {seeds.filter(s => s.role !== 'test').map(s => {
              const loaded = datasets.some(d => d.name === s.label)
              return (
                <li key={s.id} className={`flex items-center gap-4 py-2.5 ${s.available ? '' : 'opacity-50'}`}>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2 min-w-0">
                      <span className="font-medium truncate">{s.label}</span>
                      <span className="font-mono-editorial text-stone-400 text-[11px] shrink-0">{s.role}</span>
                    </div>
                    <div className="text-xs text-stone-500 truncate">{s.description}</div>
                  </div>
                  <div className="shrink-0 w-24 text-right">
                    {!s.available ? <span className="font-mono-editorial text-stone-400 text-xs">missing</span>
                      : loaded ? <span className="font-mono-editorial text-emerald-700 text-xs">loaded ✓</span>
                      : <button onClick={() => onLoadSeed(s.id)} disabled={loadingSeed === s.id}
                                className="px-2 py-1 text-xs font-medium border border-ink hover:bg-ink hover:text-cream disabled:opacity-50">
                          {loadingSeed === s.id ? '…' : 'Load'}
                        </button>
                    }
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      <div>
        <div className="font-mono-editorial text-stone-500 text-xs mb-2">Upload your own</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <FileField label="Data (CSV/JSON)" onChange={e => onUpload(e, false)} />
          <FileField label="Gold standard (CSV/JSON)" onChange={e => onUpload(e, true)} />
        </div>
      </div>

      {datasets.length > 0 && (
        <div>
          <div className="font-mono-editorial text-stone-500 text-xs mb-2">Loaded · {datasets.length}</div>
          <ul className="divide-y divide-seam border-y border-seam">
            {datasets.map(ds => (
              <li key={ds.id} className="flex items-baseline gap-4 py-2">
                <span className="flex-1 min-w-0 font-medium truncate">{ds.name}</span>
                <span className="shrink-0 w-24 text-right font-mono text-xs text-stone-600">{ds.total_items} items</span>
                <span className="shrink-0 w-16 text-right font-mono-editorial text-stone-400 text-[11px]">{ds.file_type}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function ModelStep({
  backendCfg, llmProvider, llmModel, apiKey, setLlmProvider, setLlmModel, setApiKey,
}: {
  backendCfg: BackendConfig | null
  llmProvider: string
  llmModel: string
  apiKey: string
  setLlmProvider: (v: string) => void
  setLlmModel: (v: string) => void
  setApiKey: (v: string) => void
}) {
  const envOK = envKeyAvailable(backendCfg, llmProvider)
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
        <div className="md:col-span-4">
          <LabelV2>Provider</LabelV2>
          <select value={llmProvider} onChange={e => setLlmProvider(e.target.value)}
                  className="w-full px-0 py-1.5 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-medium">
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </div>
        <div className="md:col-span-4">
          <LabelV2>Model</LabelV2>
          <input value={llmModel} onChange={e => setLlmModel(e.target.value)}
                 className="w-full px-0 py-1.5 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-mono text-sm" />
        </div>
        <div className="md:col-span-4">
          <LabelV2>API key {envOK && <span className="text-emerald-700 ml-1 normal-case tracking-normal text-[10px]">.env loaded</span>}</LabelV2>
          <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
                 placeholder={envOK ? 'leave blank to use .env' : 'sk-…'}
                 className="w-full px-0 py-1.5 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-mono text-sm" />
        </div>
      </div>
      {backendCfg && (
        <div className="flex gap-2">
          <KeyBadge label="OpenAI" loaded={backendCfg.openai_key_loaded} />
          <KeyBadge label="Anthropic" loaded={backendCfg.anthropic_key_loaded} />
        </div>
      )}
    </div>
  )
}

/* ─── Tiny primitives ───────────────────────────────────────── */

function LabelV2({ children }: { children: React.ReactNode }) {
  return <span className="font-mono-editorial text-stone-500 block mb-1 text-xs">{children}</span>
}

function FileField({ label, onChange }: { label: string; onChange: (e: React.ChangeEvent<HTMLInputElement>) => void }) {
  return (
    <label className="block">
      <LabelV2>{label}</LabelV2>
      <input type="file" accept=".csv,.json" onChange={onChange} className="text-sm pt-1" />
    </label>
  )
}

function KeyBadge({ label, loaded }: { label: string; loaded: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 border text-[10px] font-mono tracking-wider uppercase ${
      loaded ? 'border-emerald-300 bg-emerald-50/60 text-emerald-800' : 'border-seam bg-paper text-stone-400'
    }`}>
      <span className={`w-1.5 h-1.5 rounded-full ${loaded ? 'bg-emerald-500' : 'bg-stone-300'}`} />
      {label} · {loaded ? 'env' : 'off'}
    </span>
  )
}

function envKeyAvailable(cfg: BackendConfig | null, provider: string): boolean {
  if (!cfg) return false
  return provider === 'anthropic' ? cfg.anthropic_key_loaded : cfg.openai_key_loaded
}
