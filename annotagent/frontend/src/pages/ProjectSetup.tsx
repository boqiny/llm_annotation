import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  getProject, updateProject, listPresets, listCodebooks,
  listDatasets, deleteDataset, decomposePipeline,
  listSeedDatasets, loadSeedDataset, getBackendConfig,
  type SeedDatasetInfo, type BackendConfig,
} from '../lib/api'
import type { Project, Codebook, Dataset, PresetInfo } from '../types'
import CodebookDraftWizard from '../components/CodebookDraftWizard'
import LabeledDataUpload from '../components/LabeledDataUpload'
import { APP_NAME } from '../lib/brand'

type Step = 'model' | 'codebook' | 'data'

const MODEL_OPTIONS: Record<string, string[]> = {
  openai: ['gpt-5.4-mini', 'gpt-5.4', 'gpt-5.5', 'gpt-5.5-mini'],
  anthropic: ['claude-sonnet-4-5-20250929', 'claude-opus-4-1-20250805', 'claude-3-5-haiku-20241022'],
}

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
  const [step, setStep] = useState<Step>('model')
  const [loading, setLoading] = useState(false)
  const [loadingSeed, setLoadingSeed] = useState<string | null>(null)
  const [removingDataset, setRemovingDataset] = useState<number | null>(null)
  const [fewShot, setFewShot] = useState(false)
  // When a codebook is already loaded, the Codebook step shows it; the setup
  // wizard only appears once the user explicitly chooses to change it.
  const [changingCodebook, setChangingCodebook] = useState(false)

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

  const handleLoadSeed = async (seedId: string) => {
    setLoadingSeed(seedId)
    try { await loadSeedDataset(projectId, seedId); setDatasets(await listDatasets(projectId)) }
    finally { setLoadingSeed(null) }
  }
  const handleRemoveDataset = async (datasetId: number) => {
    setRemovingDataset(datasetId)
    try {
      await deleteDataset(projectId, datasetId)
      setDatasets(await listDatasets(projectId))
    } catch (e: any) {
      window.alert('Could not remove dataset: ' + (e?.response?.data?.detail || e?.message || 'unknown error'))
    } finally { setRemovingDataset(null) }
  }
  const handleSaveLLM = async () => {
    const patch: Record<string, string> = { llm_provider: llmProvider, llm_model: llmModel }
    if (apiKey) patch.api_key = apiKey
    await updateProject(projectId, patch)
    setProject(prev => prev ? { ...prev, llm_provider: llmProvider, llm_model: llmModel } : prev)
  }
  const handleSaveModelAndContinue = async () => {
    setLoading(true)
    try {
      await handleSaveLLM()
      setStep('codebook')
    } finally { setLoading(false) }
  }
  const handleGeneratePipeline = async () => {
    setLoading(true)
    try {
      await handleSaveLLM()
      await decomposePipeline(projectId, fewShot)
      navigate(`/projects/${projectId}/prompt-lab?tab=prompts`)
    } finally { setLoading(false) }
  }

  if (!project) return <div className="font-mono-editorial text-stone-400 py-24 text-center">Loading…</div>

  const activeCb = codebooks[codebooks.length - 1]
  const codebookHasExamples = !!activeCb?.dimensions?.some(
    d => d.labels?.some(l => (l.examples?.length ?? 0) > 0)
  )
  const hasDataset = datasets.length > 0
  const keyOK = envKeyAvailable(backendCfg, llmProvider) || apiKey.length > 0
  const canGenerate = !!activeCb && keyOK
  const missing: string[] = []
  if (!activeCb) missing.push('codebook')
  if (!keyOK) missing.push(`${llmProvider === 'anthropic' ? 'anthropic' : 'openai'} key`)
  // On the codebook step, once a codebook exists the editable wizard + banner
  // carry their own actions, so suppress the global generate-pipeline footer.
  // (First-time, with no codebook yet, the footer still shows "Still need: codebook".)
  const replacingCodebook = step === 'codebook' && !!activeCb

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
            <StepLink n="01" label="Model" hint="LLM + key"
                      active={step === 'model'} done={keyOK} onClick={() => setStep('model')} />
            <StepLink n="02" label="Codebook" hint="label schema"
                      active={step === 'codebook'} done={!!activeCb} onClick={() => setStep('codebook')} />
            <StepLink n="03" label="Labeled data" hint="optional"
                      active={step === 'data'} done={hasDataset} onClick={() => setStep('data')} />
          </ol>
        </aside>

        {/* Main pane */}
        <main className="flex-1 min-w-0">
          {step === 'codebook' && (
            <div data-tour="setup-codebook" data-tour-done={activeCb ? 'true' : 'false'}>
              <CodebookStep
                activeCb={activeCb}
                changing={changingCodebook}
                setChanging={setChangingCodebook}
                presets={presets}
                projectId={projectId}
                onAccepted={() => { setChangingCodebook(false); loadData(); setStep('data') }}
                onContinue={() => setStep('data')}
              />
            </div>
          )}
          {step === 'data' && (
            <div data-tour="setup-data">
              <DataStep
                projectId={projectId}
                activeCb={activeCb}
                seeds={seeds}
                datasets={datasets}
                loadingSeed={loadingSeed}
                removingDataset={removingDataset}
                onLoadSeed={handleLoadSeed}
                onRemoveDataset={handleRemoveDataset}
                onUploaded={async () => setDatasets(await listDatasets(projectId))}
              />
            </div>
          )}
          {step === 'model' && (
            <div data-tour="setup-model" data-tour-done={keyOK ? 'true' : 'false'}>
              <ModelStep
                backendCfg={backendCfg}
                llmProvider={llmProvider}
                llmModel={llmModel}
                apiKey={apiKey}
                setLlmProvider={setLlmProvider}
                setLlmModel={setLlmModel}
                setApiKey={setApiKey}
                onSaveAndContinue={handleSaveModelAndContinue}
                saving={loading}
              />
            </div>
          )}
        </main>
      </div>

      <div className="border-l-2 border-ink bg-paper px-4 py-3 text-sm">
        <div className="font-medium">What happens next</div>
        <p className="mt-1 text-xs leading-relaxed text-stone-600">
          Work through the three steps on the left: pick a model, confirm a codebook, and (optionally) add a
          few labeled examples. When they show a checkmark, click <span className="font-medium text-ink">Generate
          pipeline</span> at the bottom. {APP_NAME} writes one set of labeling instructions per label in your
          codebook and opens the Prompts page, where you improve them and start labeling.
        </p>
      </div>

      {/* Sticky footer */}
      {!replacingCodebook && (
        <div className="fixed bottom-0 left-0 right-0 bg-cream border-t border-seam">
          <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between gap-4">
            <div className="font-mono-editorial text-stone-500 text-xs">
              {missing.length === 0
                ? <span className="text-emerald-700">Ready to generate pipeline.</span>
                : <>Still need: <span className="text-ink">{missing.join(' · ')}</span></>
              }
            </div>
            <div className="flex items-center gap-4">
              {codebookHasExamples && (
                <label className="flex items-center gap-2 text-xs text-stone-600 cursor-pointer select-none"
                       title="Append each label's codebook examples to the generated prompts as few-shot demonstrations.">
                  <input
                    type="checkbox"
                    checked={fewShot}
                    onChange={e => setFewShot(e.target.checked)}
                    className="accent-ink"
                  />
                  Include few-shot examples
                </label>
              )}
              <button
                data-tour="generate-pipeline"
                data-tour-ready={canGenerate ? 'true' : 'false'}
                onClick={handleGeneratePipeline}
                disabled={!canGenerate || loading}
                className="px-5 py-2 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-40"
              >
                {loading ? 'Generating…' : 'Generate pipeline →'}
              </button>
            </div>
          </div>
        </div>
      )}
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
  activeCb, changing, setChanging, presets, projectId, onAccepted, onContinue,
}: {
  activeCb?: Codebook
  changing: boolean
  setChanging: (b: boolean) => void
  presets: PresetInfo[]
  projectId: number
  onAccepted: () => void
  onContinue: () => void
}) {
  // No codebook yet: the empty door chooser (upload / paste / preset).
  if (!activeCb) {
    return <CodebookDraftWizard projectId={projectId} presets={presets} onAccepted={onAccepted} />
  }

  // "Start a different codebook": the empty door chooser, replacing the current one.
  if (changing) {
    return (
      <>
        <div className="mb-3 border border-seam bg-paper/60 px-4 py-3 flex items-center justify-between gap-3 flex-wrap">
          <p className="text-xs leading-relaxed text-stone-500 min-w-0">
            Building a different codebook to replace <span className="font-medium text-ink">{activeCb.name}</span>.
            Accepting it replaces the current one.
          </p>
          <button onClick={() => setChanging(false)}
                  className="font-mono-editorial text-stone-500 hover:text-ink text-xs shrink-0">
            ← keep current
          </button>
        </div>
        <CodebookDraftWizard
          key="new-codebook"
          projectId={projectId}
          presets={presets}
          onAccepted={onAccepted}
          replacingName={activeCb.name}
        />
      </>
    )
  }

  // Default: the current codebook loaded as an EDITABLE draft (left: dimensions,
  // right: structure/arrow). Edit and Accept to save a new version, keep it and
  // move on, or start a different codebook from scratch.
  return (
    <>
      <div className="mb-3 border border-seam bg-paper/60 px-4 py-3 flex items-center justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="font-mono-editorial text-stone-500 text-xs">Editing current codebook</div>
          <div className="font-medium leading-snug truncate">
            {activeCb.name}
            <span className="font-mono-editorial text-stone-400 text-xs"> · {activeCb.dimensions.length} dimensions</span>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button onClick={() => setChanging(true)}
                  className="px-3 py-1 text-xs font-medium text-stone-600 border border-seam hover:border-stone-400">
            Start a different codebook
          </button>
          <button onClick={onContinue}
                  className="px-3 py-1 text-xs font-medium text-cream bg-ink hover:bg-stone-800">
            Keep current, continue to data →
          </button>
        </div>
      </div>
      <CodebookDraftWizard
        key={`edit-${activeCb.id}`}
        projectId={projectId}
        presets={presets}
        onAccepted={onAccepted}
        replacingName={activeCb.name}
        seedFromCodebookId={activeCb.id}
      />
    </>
  )
}

function DataStep({
  projectId, activeCb, seeds, datasets, loadingSeed, removingDataset, onLoadSeed, onRemoveDataset, onUploaded,
}: {
  projectId: number
  activeCb?: Codebook
  seeds: SeedDatasetInfo[]
  datasets: Dataset[]
  loadingSeed: string | null
  removingDataset: number | null
  onLoadSeed: (id: string) => void
  onRemoveDataset: (id: number) => void
  onUploaded: () => void | Promise<void>
}) {
  const labeledDatasets = datasets.filter(ds =>
    ds.is_gold
    || seeds.some(s => s.role !== 'test' && s.label === ds.name)
  )

  return (
    <div className="space-y-4">
      <div className="border-l-2 border-violet-700 bg-violet-50 px-4 py-3 text-sm text-violet-950 leading-relaxed">
        Upload existing labeled data if you have it. {APP_NAME} can learn from those correct labels to improve the prompts and check annotation quality.
      </div>
      <div className="border border-violet-200 bg-violet-50/70 px-4 py-3 text-sm text-violet-950">
        <div className="font-medium">Expected labeled-data format</div>
        <p className="mt-1 text-xs leading-relaxed text-violet-900/85">
          The labels should match the active codebook dimensions and label names. For annotator spreadsheets, use one row per quote-label pair with columns like
          <span className="font-mono text-[11px]"> Relevant quotes </span>,
          <span className="font-mono text-[11px]"> Coding theme </span>, and
          <span className="font-mono text-[11px]"> Level </span>.
          {APP_NAME} groups repeated quotes and reads each Coding theme as a dimension and each Level as its correct label.
        </p>
        <p className="mt-2 text-xs leading-relaxed text-violet-900/85">
          JSON or CSV files can also include a
          <span className="font-mono text-[11px]"> labels </span> or
          <span className="font-mono text-[11px]"> gold_labels </span>
          object, for example <span className="font-mono text-[11px]">{'{"Listening strategy": "Question-asking"}'}</span>.
        </p>
      </div>

      {seeds.length > 0 && isSelfDisclosure(activeCb) && (
        <div>
          <div className="font-mono-editorial text-stone-500 text-xs mb-2">Bundled labeled data · self-disclosure</div>
          <ul className="divide-y divide-seam border-y border-seam">
            {seeds.filter(s => s.role !== 'test').map(s => {
              const loadedDataset = datasets.find(d => d.name === s.label)
              return (
                <li key={s.id} className={`flex items-center gap-4 py-2.5 ${s.available ? '' : 'opacity-50'}`}>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline gap-2 min-w-0">
                      <span className="font-medium truncate">{s.label}</span>
                      <span className="font-mono-editorial text-stone-400 text-[11px] shrink-0">{s.role}</span>
                    </div>
                    <div className="text-xs text-stone-500 truncate">{s.description}</div>
                  </div>
                  <div className="shrink-0 w-28 text-right">
                    {!s.available ? <span className="font-mono-editorial text-stone-400 text-xs">missing</span>
                      : loadedDataset ? (
                        <button
                          onClick={() => onRemoveDataset(loadedDataset.id)}
                          disabled={removingDataset === loadedDataset.id}
                          className="px-2 py-1 text-xs font-medium border border-red-300 text-red-700 hover:bg-red-50 disabled:opacity-50"
                        >
                          {removingDataset === loadedDataset.id ? 'Removing…' : 'Remove'}
                        </button>
                      )
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
        <div className="font-mono-editorial text-stone-500 text-xs mb-2">Upload labeled data</div>
        <LabeledDataUpload projectId={projectId} onLoaded={onUploaded} />
      </div>

      {labeledDatasets.length > 0 && (
        <div>
          <div className="font-mono-editorial text-stone-500 text-xs mb-2">Loaded labeled data · {labeledDatasets.length}</div>
          <ul className="divide-y divide-seam border-y border-seam">
            <li className="flex items-baseline gap-4 py-2 bg-paper/70 text-[11px] font-mono-editorial text-stone-500 uppercase tracking-wide">
              <span className="flex-1 min-w-0">File</span>
              <span className="shrink-0 w-24 text-right">Items</span>
              <span className="shrink-0 w-16 text-right">Format</span>
              <span className="shrink-0 w-28 text-right">Type</span>
              <span className="shrink-0 w-[72px] text-right">Action</span>
            </li>
            {labeledDatasets.map(ds => (
              <li key={ds.id} className="flex items-baseline gap-4 py-2">
                <span className="flex-1 min-w-0 font-medium truncate">{ds.name}</span>
                <span className="shrink-0 w-24 text-right font-mono text-xs text-stone-600">{ds.total_items} items</span>
                <span className="shrink-0 w-16 text-right font-mono-editorial text-stone-400 text-[11px]">{ds.file_type}</span>
                <span className="shrink-0 w-28 text-right text-xs text-stone-700">{ds.is_gold ? 'Labeled (gold)' : 'Reference labels'}</span>
                <button
                  onClick={() => onRemoveDataset(ds.id)}
                  disabled={removingDataset === ds.id}
                  className="shrink-0 w-[72px] px-2 py-1 text-xs font-medium border border-red-300 text-red-700 hover:bg-red-50 disabled:opacity-50"
                >
                  {removingDataset === ds.id ? 'Removing…' : 'Remove'}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function ModelStep({
  backendCfg, llmProvider, llmModel, apiKey, setLlmProvider, setLlmModel, setApiKey, onSaveAndContinue, saving,
}: {
  backendCfg: BackendConfig | null
  llmProvider: string
  llmModel: string
  apiKey: string
  setLlmProvider: (v: string) => void
  setLlmModel: (v: string) => void
  setApiKey: (v: string) => void
  onSaveAndContinue: () => void
  saving: boolean
}) {
  const envOK = envKeyAvailable(backendCfg, llmProvider)
  const modelOptions = MODEL_OPTIONS[llmProvider] || []
  const modelChoices = modelOptions.includes(llmModel) ? modelOptions : [llmModel, ...modelOptions].filter(Boolean)
  const handleProviderChange = (provider: string) => {
    setLlmProvider(provider)
    const defaults = MODEL_OPTIONS[provider]
    if (defaults?.length) setLlmModel(defaults[0])
  }
  const keyPlaceholder = llmProvider === 'anthropic' ? 'sk-ant-...' : 'sk-...'
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
        <div className="md:col-span-4">
          <LabelV2>Provider</LabelV2>
          <select value={llmProvider} onChange={e => handleProviderChange(e.target.value)}
                  className="w-full px-0 py-1.5 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-medium">
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
          </select>
        </div>
        <div className="md:col-span-4">
          <LabelV2>Model</LabelV2>
          <select value={llmModel} onChange={e => setLlmModel(e.target.value)}
                  className="w-full px-0 py-1.5 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-mono text-sm">
            {modelChoices.map(model => (
              <option key={model} value={model}>{model}</option>
            ))}
          </select>
        </div>
        <div className="md:col-span-4">
          <LabelV2>API key {envOK && <span className="text-emerald-700 ml-1 normal-case tracking-normal text-[10px]">.env loaded</span>}</LabelV2>
          <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
                 placeholder={envOK ? 'leave blank to use .env' : keyPlaceholder}
                 className="w-full px-0 py-1.5 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none font-mono text-sm" />
        </div>
      </div>
      {backendCfg && (
        <div className="flex gap-2">
          <KeyBadge label="OpenAI" loaded={backendCfg.openai_key_loaded} />
          <KeyBadge label="Anthropic" loaded={backendCfg.anthropic_key_loaded} />
        </div>
      )}
      <div className="flex justify-end">
        <button
          onClick={onSaveAndContinue}
          disabled={saving || (!envOK && !apiKey)}
          className="px-5 py-2 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-40"
        >
          {saving ? 'Saving…' : 'Save model & continue →'}
        </button>
      </div>
    </div>
  )
}

/* ─── Tiny primitives ───────────────────────────────────────── */

function LabelV2({ children }: { children: React.ReactNode }) {
  return <span className="font-mono-editorial text-stone-500 block mb-1 text-xs">{children}</span>
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
