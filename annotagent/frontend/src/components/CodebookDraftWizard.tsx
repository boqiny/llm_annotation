import { useEffect, useRef, useState } from 'react'
import { Pencil, Loader2, Check } from 'lucide-react'
import {
  uploadCodebookDraft, pasteCodebookDraft, presetCodebookDraft, codebookToDraft,
  acceptCodebookDraft, deleteCodebookDraft, patchCodebookDraft,
  artifactDownloadUrl, getPreset,
  type CodebookDraft,
} from '../lib/api'
import type { PresetInfo } from '../types'

type Door = 'upload' | 'paste' | 'preset'

export default function CodebookDraftWizard({
  projectId,
  presets,
  onAccepted,
  replacingName,
  seedFromCodebookId,
}: {
  projectId: number
  presets: PresetInfo[]
  onAccepted: () => void
  replacingName?: string
  // When set, the wizard opens with this codebook loaded as an editable draft
  // (revise it in place) instead of the empty door chooser.
  seedFromCodebookId?: number
}) {
  const [door, setDoor] = useState<Door>('upload')            // Door A default
  const [draft, setDraft] = useState<CodebookDraft | null>(null)
  const [loading, setLoading] = useState<string>('')         // free-form status line
  const [accepting, setAccepting] = useState(false)
  const [error, setError] = useState<string>('')

  // Door-specific inputs
  const [pasteText, setPasteText] = useState('')
  const [presetName, setPresetName] = useState(presets[0]?.name || 'self_disclosure')
  // File awaiting a multi-sheet merge/import decision (XLSX guardrail).
  const [pendingFile, setPendingFile] = useState<File | null>(null)

  useEffect(() => {
    if (!presetName && presets.length > 0) setPresetName(presets[0].name)
  }, [presets, presetName])

  // Seed the editable draft from an existing codebook, once. After a discard the
  // ref stays set, so the user lands on the door chooser to build a fresh one.
  const seededRef = useRef(false)
  useEffect(() => {
    if (!seedFromCodebookId || draft || seededRef.current) return
    seededRef.current = true
    setLoading('Loading codebook for editing…'); setError('')
    codebookToDraft(seedFromCodebookId)
      .then(d => { setDraft(d); if (d.status !== 'ready') setError(d.error_message || '') })
      .catch(e => setError(e?.response?.data?.detail?.message || e?.message || 'Failed to load codebook'))
      .finally(() => setLoading(''))
  }, [seedFromCodebookId, draft])

  const resetAll = () => {
    setDraft(null); setError(''); setLoading(''); setPasteText('')
  }

  const clearDraft = async () => {
    if (draft?.id) { try { await deleteCodebookDraft(draft.id) } catch {} }
    resetAll()
  }

  const runUpload = async (file: File, opts?: { mergeSheets?: boolean; sheet?: string }) => {
    setLoading(`Ingesting ${file.name}…`); setError(''); setDraft(null)
    try {
      const d = await uploadCodebookDraft(projectId, file, opts)
      setDraft(d)
      if (d.status === 'needs_sheet_choice') setPendingFile(file)        // await user's choice
      else { setPendingFile(null); if (d.status !== 'ready') setError(d.error_message || 'Draft failed.') }
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Upload failed')
    } finally {
      setLoading('')
    }
  }
  const handleUpload = (file: File) => runUpload(file)

  const handlePaste = async () => {
    if (pasteText.trim().length < 20) {
      setError('Paste at least 20 characters.')
      return
    }
    setLoading('Agent reading your text…'); setError(''); setDraft(null)
    try {
      const d = await pasteCodebookDraft(projectId, pasteText)
      setDraft(d)
      if (d.status !== 'ready') setError(d.error_message || 'Draft failed.')
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Draft failed')
    } finally {
      setLoading('')
    }
  }

  const handlePreset = async () => {
    setLoading('Loading preset…'); setError(''); setDraft(null)
    try {
      const d = await presetCodebookDraft(presetName)
      setDraft(d)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Preset load failed')
    } finally {
      setLoading('')
    }
  }

  const handleAccept = async (editedJson?: Record<string, any>) => {
    if (!draft) return
    setAccepting(true); setError('')
    try {
      // Persist user edits (if any) before accepting so the codebook row
      // committed to the project reflects the final state shown in the UI.
      if (editedJson) {
        await patchCodebookDraft(draft.id, editedJson)
      }
      await acceptCodebookDraft(projectId, draft.id)
      onAccepted()
    } catch (e: any) {
      setError(e?.response?.data?.detail?.message || e?.response?.data?.detail || e?.message || 'Accept failed')
    } finally {
      setAccepting(false)
    }
  }

  const inFlight = !!loading
  const hasDraft = draft && draft.status === 'ready'
  const choosingSheet = draft?.status === 'needs_sheet_choice'

  /* Render --------------------------------------------------------------- */
  return (
    <div className="space-y-4">
      {/* Door chooser */}
      {!hasDraft && !choosingSheet && (
        <div className="space-y-3">
          <div className="border-l-2 border-ink pl-4 text-sm leading-relaxed text-stone-700">
            A codebook is your label definition. Select one option below to define your codebook.
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <DoorCard
              door="upload"
              active={door === 'upload'}
              onClick={() => setDoor('upload')}
              title="A. Upload a file"
              hint="PDF · DOCX · XLSX · CSV · JSON · TXT — agent parses + cleans"
              emphasized
            />
            <DoorCard
              door="paste"
              active={door === 'paste'}
              onClick={() => setDoor('paste')}
              title="B. Text"
              hint="Paste codebook text — annotator notes, instructions, spreadsheet contents, or an old draft"
            />
            <DoorCard
              door="preset"
              active={door === 'preset'}
              onClick={() => setDoor('preset')}
              title="C. Use a preset"
              hint={`Self-disclosure · AI behavior · ${presets.length} available`}
            />
          </div>
        </div>
      )}

      {/* Door body */}
      {!hasDraft && !choosingSheet && (
        <div className="border border-seam bg-white p-4">
          {door === 'upload' && (
            <UploadForm onFile={handleUpload} busy={inFlight} />
          )}
          {door === 'paste' && (
            <PasteForm
              value={pasteText}
              onChange={setPasteText}
              onSubmit={handlePaste}
              busy={inFlight}
            />
          )}
          {door === 'preset' && (
            <PresetForm
              projectId={projectId}
              presets={presets}
              value={presetName}
              onChange={setPresetName}
              onSubmit={handlePreset}
              busy={inFlight}
            />
          )}
        </div>
      )}

      {/* Processing panel */}
      {inFlight && <ProcessingPanel door={door} caption={loading} />}

      {error && (
        <div className="border border-red-200 bg-red-50/60 text-red-800 p-4 text-sm">
          <div className="font-mono-editorial text-red-700 mb-1">Error</div>
          <div>{error}</div>
        </div>
      )}

      {/* Multi-sheet guardrail: ask to merge all sheets or import one */}
      {choosingSheet && !inFlight && (
        <SheetChoice
          filename={draft!.source_filename}
          sheets={draft!.sheet_options || draft!.draft_json?._sheet_options || []}
          onMerge={() => pendingFile && runUpload(pendingFile, { mergeSheets: true })}
          onPick={(s) => pendingFile && runUpload(pendingFile, { sheet: s })}
          onCancel={clearDraft}
        />
      )}

      {/* Draft preview */}
      {draft && !choosingSheet && (
        <DraftPreview
          draft={draft}
          onAccept={handleAccept}
          onDiscard={clearDraft}
          accepting={accepting}
          replacingName={replacingName}
        />
      )}
    </div>
  )
}

/* ─── Multi-sheet guardrail ─────────────────────────────────── */

function SheetChoice({
  filename, sheets, onMerge, onPick, onCancel,
}: {
  filename: string
  sheets: string[]
  onMerge: () => void
  onPick: (sheet: string) => void
  onCancel: () => void
}) {
  const [sel, setSel] = useState(sheets[0] || '')
  return (
    <div className="border border-amber-200 bg-amber-50/60 p-4 space-y-4">
      <div>
        <div className="font-mono-editorial text-amber-800 text-xs mb-1">Multiple sheets detected</div>
        <p className="text-sm text-stone-700 leading-relaxed">
          <span className="font-medium">{filename}</span> has {sheets.length} sheets:{' '}
          {sheets.map((s, i) => (
            <span key={s}>{i > 0 && ', '}<span className="font-medium">{s}</span></span>
          ))}.
          Merge them into one codebook, or import a single sheet?
        </p>
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        <button onClick={onMerge}
                className="px-4 py-2 bg-ink text-cream text-sm font-medium hover:bg-stone-800 transition">
          Merge all {sheets.length} sheets →
        </button>
        <div className="flex items-center gap-2">
          <select value={sel} onChange={e => setSel(e.target.value)}
                  className="text-sm border border-seam bg-white px-2 py-2 focus:border-ink focus:outline-none">
            {sheets.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <button onClick={() => sel && onPick(sel)}
                  className="px-4 py-2 border border-ink text-ink text-sm font-medium hover:bg-ink hover:text-cream transition">
            Import this sheet →
          </button>
        </div>
      </div>

      <button onClick={onCancel}
              className="font-mono-editorial text-stone-500 hover:text-ink text-xs">
        ← cancel, choose another file
      </button>
    </div>
  )
}

/* ─── Door cards ───────────────────────────────────────────── */

function DoorCard({
  door, title, hint, active, onClick, emphasized = false, disabled = false,
}: {
  door: Door
  title: string
  hint: string
  active: boolean
  onClick: () => void
  emphasized?: boolean
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`text-left p-4 bg-white border transition-all disabled:opacity-40 disabled:cursor-not-allowed ${
        active
          ? 'border-ink shadow-[4px_4px_0_0_rgba(11,11,10,0.08)]'
          : 'border-seam hover:border-stone-400'
      } ${emphasized ? 'ring-1 ring-offset-0 ring-indigo-200' : ''}`}
    >
      <div className="text-base font-medium tracking-tight mb-0.5">
        {title}
        {emphasized && <span className="ml-2 align-middle font-mono-editorial text-xs text-indigo-700">default</span>}
      </div>
      <p className="text-sm text-stone-600 leading-relaxed">{hint}</p>
    </button>
  )
}

/* ─── Processing panel ─────────────────────────────────────── */

const STAGE_SETS: Record<Door, string[]> = {
  upload: ['Ingesting file', 'Reading sheet structure', 'Drafting label schema', 'Reviewing for overlaps', 'Finalizing codebook'],
  paste: ['Reading your text', 'Drafting label schema', 'Reviewing for overlaps', 'Finalizing codebook'],
  preset: ['Loading preset'],
}

function ProcessingPanel({ door, caption }: { door: Door; caption: string }) {
  const stages = STAGE_SETS[door] ?? ['Working']
  const animated = door !== 'preset'
  const [active, setActive] = useState(0)

  // Advance through the agent's stages on a timer. The backend runs synchronously
  // (no progress events), so we pace the stages and HOLD on the last one until the
  // real response lands and this panel unmounts. Never claims a precise percentage.
  useEffect(() => {
    if (stages.length <= 1) return
    const id = setInterval(
      () => setActive(a => (a < stages.length - 1 ? a + 1 : a)),
      2600,
    )
    return () => clearInterval(id)
  }, [stages.length])

  return (
    <div className="border border-seam bg-paper/60 p-4 space-y-3">
      <style>{`
        @keyframes clairSweep { from { transform: translateX(-110%) } to { transform: translateX(360%) } }
        @keyframes clairBreathe { 0%,100% { opacity: .3 } 50% { opacity: 1 } }
        @media (prefers-reduced-motion: reduce) {
          .clair-sweep { animation: none !important; transform: none !important; width: 100% !important; opacity: .5 }
          .clair-breathe { animation: none !important; opacity: 1 }
        }
      `}</style>

      <div className="flex items-center gap-2">
        <Loader2 className="h-4 w-4 text-ink animate-spin motion-reduce:animate-none" aria-hidden="true" />
        <span className="text-sm font-medium text-ink">CodebookAgent</span>
        <span className="font-mono-editorial text-stone-400 text-[11px] ml-auto">working…</span>
      </div>

      {/* indeterminate sweep */}
      <div className="relative h-1 w-full overflow-hidden bg-stone-200" role="progressbar" aria-label="Processing">
        <div className="clair-sweep absolute inset-y-0 w-1/3 bg-ink"
             style={{ animation: 'clairSweep 1.25s linear infinite' }} />
      </div>

      <ul className="space-y-1.5">
        {stages.map((s, i) => {
          const done = i < active
          const current = i === active && animated
          return (
            <li key={s} className="flex items-center gap-2.5 text-sm">
              <span className="w-4 h-4 shrink-0 flex items-center justify-center">
                {done ? (
                  <Check className="h-3.5 w-3.5 text-emerald-600" aria-hidden="true" />
                ) : current ? (
                  <span className="clair-breathe w-2 h-2 rounded-full bg-violet-600"
                        style={{ animation: 'clairBreathe 1.1s ease-in-out infinite' }} />
                ) : (
                  <span className="w-1.5 h-1.5 rounded-full border border-stone-300" />
                )}
              </span>
              <span className={done ? 'text-stone-400' : current ? 'text-ink font-medium' : 'text-stone-400'}>
                {s}
              </span>
            </li>
          )
        })}
      </ul>

      {caption && <div className="font-mono-editorial text-stone-400 text-[11px] truncate">{caption}</div>}
      {animated && (
        <div className="text-xs text-stone-500">A strong model reads the whole codebook, so this usually takes ~15-30s.</div>
      )}
    </div>
  )
}

/* ─── Door forms ───────────────────────────────────────────── */

function UploadForm({ onFile, busy }: { onFile: (f: File) => void; busy: boolean }) {
  const [drag, setDrag] = useState(false)
  return (
    <div>
      <div className="font-mono-editorial text-stone-500 mb-3">
        Upload · 16 MB max · pdf · docx · xlsx · csv · json · txt
      </div>
      <label
        onDragOver={e => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={e => {
          e.preventDefault()
          setDrag(false)
          const f = e.dataTransfer.files?.[0]
          if (f) onFile(f)
        }}
        className={`block border-2 border-dashed p-10 text-center cursor-pointer transition-colors ${
          drag ? 'border-ink bg-paper' : 'border-seam bg-paper/40 hover:border-stone-400'
        }`}
      >
        <input
          type="file"
          accept=".pdf,.docx,.xlsx,.csv,.json,.txt,.md"
          className="hidden"
          disabled={busy}
          onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f) }}
        />
        <div className="font-mono-editorial text-stone-500 mb-2">
          {busy ? 'uploading…' : 'click or drag a file here'}
        </div>
        <p className="text-sm text-stone-600">
          Dropping raw annotator XLSX auto-produces both a codebook and a cleaned <code className="font-mono text-[11px]">cleaned_data.json</code>.
        </p>
      </label>
    </div>
  )
}

function PasteForm({
  value, onChange, onSubmit, busy,
}: {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  busy: boolean
}) {
  return (
    <div>
      <div className="font-mono-editorial text-stone-500 mb-3">
        Paste annotator notes, an old codebook, or any structured text
      </div>
      <textarea
        value={value}
        onChange={e => onChange(e.target.value)}
        rows={10}
        className="w-full px-3 py-3 border border-seam bg-white focus:border-ink focus:outline-none font-mono text-xs leading-relaxed"
        placeholder="Example:&#10;&#10;Annotate user messages on three dimensions:&#10;1. Level of disclosure — High / Low / No&#10;2. Topic — causal, emotional, advice, intimate...&#10;3. Confession — yes / no&#10;&#10;Paste as much detail as you have; the agent will structure it."
      />
      <div className="mt-4 flex items-center justify-between">
        <div className="font-mono text-xs text-stone-500">
          {value.length.toLocaleString()} chars {value.length < 20 && '· need ≥ 20'}
        </div>
        <button
          onClick={onSubmit}
          disabled={busy || value.trim().length < 20}
          className="px-5 py-2.5 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-40 transition-colors"
        >
          {busy ? 'Drafting…' : 'Draft with agent →'}
        </button>
      </div>
    </div>
  )
}

function PresetForm({
  projectId, presets, value, onChange, onSubmit, busy,
}: {
  projectId: number
  presets: PresetInfo[]
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  busy: boolean
}) {
  const [preview, setPreview] = useState<{ name: string; data: any } | null>(null)
  const [loadingPreview, setLoadingPreview] = useState<string | null>(null)
  const openPreview = async (name: string) => {
    setLoadingPreview(name)
    try { setPreview({ name, data: await getPreset(projectId, name) }) }
    catch { /* ignore */ }
    finally { setLoadingPreview(null) }
  }
  return (
    <div>
      <div className="font-mono-editorial text-stone-500 mb-2">
        Choose a preset — instant load, no LLM drafting
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 mb-4">
        {presets.map(p => (
          <label
            key={p.name}
            className={`flex items-start gap-3 p-3 border cursor-pointer transition-colors ${
              value === p.name ? 'border-ink bg-paper' : 'border-seam hover:border-stone-400'
            }`}
          >
            <input
              type="radio"
              name="preset"
              value={p.name}
              checked={value === p.name}
              onChange={() => onChange(p.name)}
              className="mt-1"
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-medium">{p.name}</span>
                <button
                  type="button"
                  onClick={(e) => { e.preventDefault(); openPreview(p.name) }}
                  className="ml-auto shrink-0 text-[11px] font-mono-editorial text-stone-500 hover:text-ink underline"
                >
                  {loadingPreview === p.name ? 'loading…' : 'preview'}
                </button>
              </div>
              <div className="text-xs text-stone-500 mt-0.5">{p.dimensions} dimensions</div>
              {p.description && (
                <div className="text-sm text-stone-600 mt-1 leading-relaxed">{p.description}</div>
              )}
            </div>
          </label>
        ))}
      </div>
      {preview && <PresetPreviewModal name={preview.name} data={preview.data} onClose={() => setPreview(null)} />}
      <div className="flex justify-end">
        <button
          onClick={onSubmit}
          disabled={busy || !value}
          className="px-5 py-2.5 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-40 transition-colors"
        >
          {busy ? 'Loading…' : 'Load preset →'}
        </button>
      </div>
    </div>
  )
}

/* ─── Draft preview (editable) ──────────────────────────────── */

function DraftPreview({
  draft, onAccept, onDiscard, accepting, replacingName,
}: {
  draft: CodebookDraft
  onAccept: (editedJson?: Record<string, any>) => void
  onDiscard: () => void
  accepting: boolean
  replacingName?: string
}) {
  // Local working copy. Reset whenever we get a new draft from the server.
  const [working, setWorking] = useState<any>(() => structuredClone(draft.draft_json || {}))
  const [draftId, setDraftId] = useState<number>(draft.id)
  if (draft.id !== draftId) {
    setDraftId(draft.id)
    setWorking(structuredClone(draft.draft_json || {}))
  }

  const dirty = JSON.stringify(working) !== JSON.stringify(draft.draft_json || {})
  const dimensions: any[] = Array.isArray(working.dimensions) ? working.dimensions : []
  const rationalePerDim: Record<string, string> =
    (draft.draft_json || {})._rationale_per_dim || {}

  const flags = draft.critic_flags || []
  const errorFlags = flags.filter(f => f.severity === 'error')
  const warnFlags = flags.filter(f => f.severity === 'warn')
  const infoFlags = flags.filter(f => f.severity === 'info')

  const updateDim = (i: number, patch: Partial<any>) => {
    setWorking((w: any) => {
      const dims = [...(w.dimensions || [])]
      dims[i] = { ...dims[i], ...patch }
      return { ...w, dimensions: dims }
    })
  }
  const updateLabel = (i: number, j: number, patch: Partial<any>) => {
    setWorking((w: any) => {
      const dims = [...(w.dimensions || [])]
      const labels = [...(dims[i].labels || [])]
      labels[j] = { ...labels[j], ...patch }
      dims[i] = { ...dims[i], labels }
      return { ...w, dimensions: dims }
    })
  }
  const removeLabel = (i: number, j: number) => {
    setWorking((w: any) => {
      const dims = [...(w.dimensions || [])]
      const labels = [...(dims[i].labels || [])]
      labels.splice(j, 1)
      dims[i] = { ...dims[i], labels }
      return { ...w, dimensions: dims }
    })
  }
  const addLabel = (i: number) => {
    setWorking((w: any) => {
      const dims = [...(w.dimensions || [])]
      const labels = [...(dims[i].labels || []), { name: 'new_label', definition: '', examples: [] }]
      dims[i] = { ...dims[i], labels }
      return { ...w, dimensions: dims }
    })
  }
  // For the flat "Topics" view of a gated dimension: rename/remove a topic across
  // every gate value it appears under (a topic is one concept, repeated per level).
  const renameLeavesByName = (i: number, oldName: string, newName: string) => {
    setWorking((w: any) => {
      const dims = [...(w.dimensions || [])]
      dims[i] = { ...dims[i], labels: (dims[i].labels || []).map((l: any) => l.name === oldName ? { ...l, name: newName } : l) }
      return { ...w, dimensions: dims }
    })
  }
  const removeLeavesByName = (i: number, name: string) => {
    setWorking((w: any) => {
      const dims = [...(w.dimensions || [])]
      dims[i] = { ...dims[i], labels: (dims[i].labels || []).filter((l: any) => l.name !== name) }
      return { ...w, dimensions: dims }
    })
  }
  const removeDim = (i: number) => {
    setWorking((w: any) => {
      const dims = [...(w.dimensions || [])]
      dims.splice(i, 1)
      return { ...w, dimensions: dims }
    })
  }

  const handleAccept = () => onAccept(dirty ? working : undefined)

  const ActionBar = () => (
    <div className="flex items-center justify-between gap-3 flex-wrap">
      <div className="font-mono-editorial text-stone-500">
        {dirty ? <span className="text-amber-700">unsaved edits</span> : <span>no edits</span>}
        <span className="text-stone-400 mx-2">·</span>
        {dimensions.length} dimensions ·{' '}
        {dimensions.reduce((n, d) => n + (d.gated_by
          ? new Set((d.labels || []).map((l: any) => l.name).filter(Boolean)).size
          : (d.labels?.length || 0)), 0)} labels
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={onDiscard}
          disabled={accepting}
          className="px-4 py-2 text-sm font-medium text-stone-600 border border-seam hover:border-stone-400"
        >
          Discard
        </button>
        <button
          onClick={handleAccept}
          disabled={accepting || errorFlags.length > 0}
          title={errorFlags.length > 0 ? 'Resolve critic errors first' : ''}
          className="px-5 py-2 bg-ink text-cream text-sm font-medium hover:bg-stone-800 disabled:opacity-40 transition-colors"
        >
          {accepting ? 'Accepting…' : dirty ? 'Save & load →' : 'Accept & load →'}
        </button>
      </div>
    </div>
  )

  return (
    <div className="border border-seam bg-white">
      {/* TOP: editable header + action bar */}
      <div className="p-5 border-b border-seam space-y-4">
        <div className="font-mono-editorial text-stone-500">
          Draft · №{draft.id.toString().padStart(4, '0')} · {draft.source}
          {draft.source_filename && ` · ${draft.source_filename}`}
        </div>
        <input
          value={working.name || ''}
          onChange={e => setWorking((w: any) => ({ ...w, name: e.target.value }))}
          className="w-full px-0 py-1 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none text-2xl font-medium tracking-tight"
          placeholder="Codebook name"
        />
        <textarea
          value={working.description || ''}
          onChange={e => setWorking((w: any) => ({ ...w, description: e.target.value }))}
          rows={2}
          className="w-full px-0 py-1 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none text-sm text-stone-700 leading-relaxed resize-none"
          placeholder="One-line description of what this codebook annotates"
        />
        <ActionBar />
      </div>

      {/* Split: schema | rationale */}
      <div className="grid grid-cols-1 lg:grid-cols-3">
        <div className="lg:col-span-2 divide-y divide-seam">
          {dimensions.map((dim: any, i: number) => (
            <div key={i} className="p-5 flex gap-5">
              <div className="font-mono-editorial text-stone-400 w-8 shrink-0 pt-2">
                {(i + 1).toString().padStart(2, '0')}
              </div>
              <div className="flex-1 min-w-0 space-y-2.5">
                {dim.derived_from && (
                  <p className="text-[11px] leading-relaxed text-stone-500 border-l-2 border-indigo-200 pl-2">
                    Derived from <span className="font-medium text-indigo-700">{dim.derived_from}</span>: filled
                    automatically from the chosen topic. Editable here, but not predicted on its own yet.
                  </p>
                )}
                <div className="space-y-2">
                  <div className="relative">
                    <Pencil className="absolute left-0 top-2 h-3.5 w-3.5 text-stone-400" aria-hidden="true" />
                    <input
                      value={dim.name || ''}
                      onChange={e => updateDim(i, { name: e.target.value })}
                      className="w-full pl-5 pr-0 py-0.5 bg-transparent border-0 border-b border-transparent hover:border-seam focus:border-ink focus:outline-none text-lg font-medium"
                      placeholder="Dimension name"
                      aria-label="Edit dimension name"
                    />
                  </div>
                  <div className="flex items-center gap-3 flex-wrap">
                    <select
                      value={dim.type || 'single_label'}
                      onChange={e => updateDim(i, { type: e.target.value })}
                      className={`text-sm font-medium bg-transparent border-0 border-b border-transparent hover:border-seam focus:border-ink focus:outline-none ${
                        (dim.type || '').includes('multi') ? 'text-violet-700' : 'text-indigo-700'
                      }`}
                    >
                      <option value="single_label">Single-label (one per item)</option>
                      <option value="multi_label">Multi-label (a set per item)</option>
                    </select>
                    <span className="text-sm text-stone-500">
                      {/* Gated dimensions repeat a label once per gate value; count
                          the distinct labels so it matches the chip list. */}
                      {dim.gated_by
                        ? new Set((dim.labels || []).map((l: any) => l.name).filter(Boolean)).size
                        : (dim.labels || []).length} labels
                    </span>
                    <button
                      onClick={() => removeDim(i)}
                      className="ml-auto px-2.5 py-1 bg-red-50 border border-red-200 text-xs font-medium text-red-600 hover:bg-red-100 hover:border-red-300 transition-colors"
                    >
                      Remove dimension
                    </button>
                  </div>
                </div>
                <div className="relative">
                  <Pencil className="absolute left-2 top-2 h-3.5 w-3.5 text-stone-400" aria-hidden="true" />
                  <textarea
                    value={dim.instructions || ''}
                    onChange={e => updateDim(i, { instructions: e.target.value })}
                    rows={2}
                    className="w-full pl-7 pr-2 py-2 bg-paper/40 border border-transparent hover:border-seam focus:border-ink focus:outline-none text-sm text-stone-600 leading-relaxed resize-y"
                    placeholder="Annotation instructions for this dimension (optional)"
                    aria-label="Edit dimension instructions"
                  />
                </div>
                {dim.gated_by && (dim.labels || []).some((l: any) => l.path?.length) ? (
                  // Gated dimension: show the distinct labels as a normal compact
                  // list. The per-gate-value breakdown lives in the right structure panel.
                  <FlatTwoLists
                    dim={dim}
                    onRenameTopic={(oldN, newN) => renameLeavesByName(i, oldN, newN)}
                    onRemoveTopic={(n) => removeLeavesByName(i, n)}
                    onAddTopic={() => addLabel(i)}
                  />
                ) : (dim.labels || []).some((l: any) => l.path?.length) ? (
                  <div className="space-y-2">
                    <WizardNestedGroups
                      node={wBuildTree(dim.labels || [])} depth={0}
                      levelKinds={[dim.gated_by || '', dim.category_dimension || '']}
                      keyPrefix={`${draft.id}-${i}`}
                      onChange={(j, patch) => updateLabel(i, j, patch)}
                      onRemove={(j) => removeLabel(i, j)}
                    />
                    <button onClick={() => addLabel(i)}
                      className="text-xs px-2 py-1 border border-dashed border-seam hover:border-ink text-stone-500 hover:text-ink">
                      + add label
                    </button>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {(dim.labels || []).map((lbl: any, j: number) => (
                      <LabelEditor
                        key={`${draft.id}-${i}-${j}`}
                        lbl={lbl}
                        onChange={(patch) => updateLabel(i, j, patch)}
                        onRemove={() => removeLabel(i, j)}
                      />
                    ))}
                    <button
                      onClick={() => addLabel(i)}
                      className="text-xs px-2 py-1 border border-dashed border-seam hover:border-ink text-stone-500 hover:text-ink"
                    >
                      + add label
                    </button>
                  </div>
                )}
                {rationalePerDim[dim.name] && (
                  <p className="text-xs text-stone-500 italic leading-relaxed border-l-2 border-stone-200 pl-3 mt-3">
                    {rationalePerDim[dim.name]}
                  </p>
                )}
              </div>
            </div>
          ))}
          {dimensions.length === 0 && (
            <div className="p-10 text-center font-mono-editorial text-stone-400">
              No dimensions in draft.
            </div>
          )}
        </div>

        <div className="border-t lg:border-t-0 lg:border-l border-seam bg-paper/30 p-5 space-y-5">
          <div>
            <div className="font-mono-editorial text-stone-500 mb-2">Source</div>
            <div className="text-sm text-stone-700">{draft.source_filename || '(inline)'}</div>
            {draft.source_bytes > 0 && (
              <div className="font-mono text-[11px] text-stone-400 mt-0.5">
                {(draft.source_bytes / 1024).toFixed(1)} KB
              </div>
            )}
            <div className="font-mono text-[11px] text-stone-400 mt-0.5">
              Drafter model: {draft.drafter_model || 'n/a'}
            </div>
          </div>

          {/* Prediction-flow cascade across the gated dimensions, then each
              gated dimension's per-gate-value structure underneath. */}
          {dimensions.some((d: any) => d.gated_by) && (
            <div>
              <div className="font-mono-editorial text-stone-500 mb-2">Prediction flow</div>
              <div className="border border-seam bg-white p-2 overflow-x-auto">
                <CascadeArrow dims={dimensions} />
              </div>
            </div>
          )}

          {dimensions.filter((d: any) => (d.labels || []).some((l: any) => l.path?.length)).map((d: any, idx: number) => (
            <div key={idx}>
              <div className="font-mono-editorial text-stone-500 mb-2">Structure · {d.name}</div>
              {d.gated_by && (
                <p className="text-[11px] leading-relaxed text-stone-500 mb-2">
                  Predicted after <span className="font-medium text-indigo-700">{d.gated_by}</span>; the available labels depend on its value
                  {d.context_dims?.length ? <> , with <span className="font-medium text-indigo-700">{d.context_dims.join(', ')}</span> given as context</> : null}.
                </p>
              )}
              <div className="max-h-[420px] overflow-auto pr-1 border border-seam bg-white p-2">
                <WizardTreeLines node={wBuildTree(d.labels || [])} depth={0}
                  levelKinds={[d.gated_by || '', '']} />
              </div>
            </div>
          ))}

          {draft.has_cleaned_data && (
            <div>
              <div className="font-mono-editorial text-stone-500 mb-2">
                Cleaned data · {draft.cleaned_data_rows.toLocaleString()} rows
              </div>
              <div className="flex gap-2">
                <a
                  href={artifactDownloadUrl(draft.id, 'cleaned_data.json')}
                  className="text-xs px-3 py-1.5 border border-seam hover:border-ink transition-colors"
                >
                  download .json
                </a>
                <a
                  href={artifactDownloadUrl(draft.id, 'cleaned_data.csv')}
                  className="text-xs px-3 py-1.5 border border-seam hover:border-ink transition-colors"
                >
                  download .csv
                </a>
              </div>
            </div>
          )}

          {draft.warnings?.length > 0 && (
            <div>
              <div className="font-mono-editorial text-stone-500 mb-2">Ingestor warnings</div>
              <ul className="space-y-1 text-xs text-stone-700">
                {draft.warnings.map((w, i) => (
                  <li key={i} className="leading-relaxed">· {w}</li>
                ))}
              </ul>
            </div>
          )}

          {errorFlags.length + warnFlags.length + infoFlags.length > 0 && (
            <div>
              <div className="font-mono-editorial text-stone-500 mb-2.5">Critic flags</div>
              <ul className="space-y-2.5">
                {[...errorFlags, ...warnFlags, ...infoFlags].map((f, i) => (
                  <li key={i} className="flex gap-2.5">
                    <span className={`mt-0.5 shrink-0 inline-flex items-center px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wide rounded-sm ${
                      f.severity === 'error' ? 'bg-red-50 text-red-700 border border-red-200' :
                      f.severity === 'warn' ? 'bg-amber-50 text-amber-700 border border-amber-200' :
                      'bg-stone-100 text-stone-500 border border-stone-200'
                    }`}>
                      {f.severity}
                    </span>
                    <p className="min-w-0 text-[13px] text-stone-700 leading-relaxed">
                      {f.dim && <span className="font-medium text-stone-600">{f.dim}: </span>}
                      {f.message}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
      {replacingName && (
        <div className="border-t border-violet-200 bg-violet-50 px-5 py-4">
          <div className="flex items-center justify-between gap-3 text-sm">
            <div className="font-medium text-violet-950">Replacing {replacingName}</div>
            <button
              onClick={onDiscard}
              disabled={accepting}
              className="font-mono-editorial text-stone-500 hover:text-ink disabled:opacity-40"
            >
              cancel
            </button>
          </div>
          <p className="mt-2 text-sm leading-relaxed text-violet-900">
            Please inspect the parsed dimensions and labels before accepting. A codebook mistake will affect prompt generation, improvement, annotation, and exported results.
          </p>
        </div>
      )}
	    </div>
	  )
	}

/* ─── Hierarchy tree for the draft wizard (editable leaves) ── */

type WNode = { name: string; children: Map<string, WNode>; leaves: { lbl: any; j: number }[] }

function wBuildTree(labels: any[]): WNode {
  const root: WNode = { name: '', children: new Map(), leaves: [] }
  labels.forEach((lbl, j) => {
    let node = root
    for (const seg of (lbl.path || [])) {
      let child = node.children.get(seg)
      if (!child) { child = { name: seg, children: new Map(), leaves: [] }; node.children.set(seg, child) }
      node = child
    }
    node.leaves.push({ lbl, j })
  })
  return root
}

function wCount(node: WNode): number {
  let n = node.leaves.length
  for (const c of node.children.values()) n += wCount(c)
  return n
}

/* Editable labels grouped under nested path headers (gate value, then category). */
function WizardNestedGroups({ node, depth, levelKinds, keyPrefix, onChange, onRemove }: {
  node: WNode; depth: number; levelKinds: string[]; keyPrefix: string
  onChange: (j: number, patch: any) => void; onRemove: (j: number) => void
}) {
  const isGate = depth === 0 && !!levelKinds[0]
  return (
    <div className="space-y-3">
      {node.leaves.length > 0 && (
        <div className="space-y-1.5">
          {node.leaves.map(({ lbl, j }) => (
            <LabelEditor key={`${keyPrefix}-${j}`} lbl={lbl}
              onChange={(patch) => onChange(j, patch)} onRemove={() => onRemove(j)} />
          ))}
        </div>
      )}
      {[...node.children.values()].map((child, i) => (
        <section key={i} className={`border-l-2 pl-3 ${isGate ? 'border-indigo-300' : 'border-stone-200'}`}>
          <header className="mb-1.5">
            {levelKinds[depth] && (
              <div className="font-mono-editorial text-[10px] uppercase tracking-wider text-stone-400">{levelKinds[depth]}</div>
            )}
            <div className={`text-sm font-medium ${isGate ? 'text-indigo-800' : 'text-stone-700'}`}>
              {isGate && <span className="font-normal text-stone-400">when = </span>}
              {child.name}
              <span className="ml-2 font-mono text-[11px] text-stone-400">{wCount(child)}</span>
            </div>
          </header>
          <WizardNestedGroups node={child} depth={depth + 1} levelKinds={levelKinds}
            keyPrefix={keyPrefix} onChange={onChange} onRemove={onRemove} />
        </section>
      ))}
    </div>
  )
}

/* Prediction-flow cascade across the gated dimensions: the temporal order in
 * which a coder works, e.g. "Level of disclosure -> Topics -> Topic thematic
 * categories". Built universally from the dimension graph: each gate (a name some
 * dimension is `gated_by`) is followed by the dimensions it gates, ordered so a
 * dimension that takes another as `context_dims` comes after it. */
function CascadeArrow({ dims }: { dims: any[] }) {
  const distinct = (d: any) => new Set<string>((d.labels || []).map((l: any) => l.name).filter(Boolean)).size
  const gateValues = (d: any) => new Set<string>((d.labels || []).map((l: any) => (l.path || [])[0]).filter(Boolean)).size

  const orderByContext = (group: any[]) => {
    const placed: any[] = []
    const remaining = [...group]
    let progress = true
    while (remaining.length && progress) {
      progress = false
      for (let i = 0; i < remaining.length; i++) {
        const ctx = (remaining[i].context_dims || []).filter((c: string) => group.some(g => g.name === c))
        if (ctx.every((c: string) => placed.some(p => p.name === c))) {
          placed.push(remaining.splice(i, 1)[0]); progress = true; break
        }
      }
    }
    return [...placed, ...remaining]
  }

  const gateNames = Array.from(new Set(dims.filter(d => d.gated_by).map(d => d.gated_by)))

  return (
    <div className="space-y-3">
      {gateNames.map(gate => {
        const gateDim = dims.find(d => d.name === gate)
        const gated = orderByContext(dims.filter(d => d.gated_by === gate))
        const nodes: { label: string; sub: string }[] = [
          { label: gate, sub: `${gateDim ? distinct(gateDim) : gateValues(gated[0])} values` },
          ...gated.map(d => ({ label: d.name, sub: `${distinct(d)} labels` })),
        ]
        return (
          <div key={gate} className="flex flex-wrap items-center gap-1.5">
            {nodes.map((n, i) => (
              <div key={n.label} className="flex items-center gap-1.5">
                {i > 0 && <span className="text-stone-400 text-sm" aria-hidden="true">&rarr;</span>}
                <div className="border border-seam bg-white px-2.5 py-1.5">
                  <div className="text-[12px] font-medium text-stone-800 leading-tight">{n.label}</div>
                  <div className="font-mono text-[10px] text-stone-400 mt-0.5">{n.sub}</div>
                </div>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}

function WizardTreeLines({ node, depth, levelKinds }: { node: WNode; depth: number; levelKinds: string[] }) {
  const isGate = depth === 0 && !!levelKinds[0]
  return (
    <ul className="space-y-0.5">
      {[...node.children.values()].map((c, i) => (
        <li key={`n${i}`}>
          <div className="flex items-baseline gap-1.5 text-[11px]" style={{ paddingLeft: depth * 12 }}>
            <span className={`truncate ${isGate ? 'text-indigo-700 font-medium' : 'text-stone-700'}`}>{c.name}</span>
            <span className="font-mono text-[10px] text-stone-400 shrink-0">{wCount(c)}</span>
          </div>
          {(c.children.size > 0 || c.leaves.length > 0) &&
            <WizardTreeLines node={c} depth={depth + 1} levelKinds={levelKinds} />}
        </li>
      ))}
      {node.leaves.map(({ lbl }, i) => (
        <li key={`l${i}`} className="flex items-baseline gap-1.5 text-[10.5px] text-stone-500"
            style={{ paddingLeft: depth * 12 + 8 }}>
          <span className="text-stone-300" aria-hidden="true">·</span>
          <span className="truncate">{lbl.name}</span>
        </li>
      ))}
    </ul>
  )
}

/* Read-only preview of a preset codebook before loading it. */
function PresetPreviewModal({ name, data, onClose }: { name: string; data: any; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const dims = data?.dimensions || []
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-cream border border-seam w-full max-w-2xl max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-4 px-5 py-3 border-b border-seam">
          <div>
            <div className="font-medium">{data?.name || name}</div>
            <div className="font-mono-editorial text-[11px] text-stone-400">{dims.length} dimensions · preview</div>
          </div>
          <button onClick={onClose} className="text-stone-400 hover:text-ink text-xl leading-none px-1" title="Close (Esc)">×</button>
        </div>
        <div className="overflow-auto p-5 space-y-5">
          {data?.description && <p className="text-sm text-stone-600 leading-relaxed">{data.description}</p>}
          {dims.map((d: any, i: number) => {
            const hier = (d.labels || []).some((l: any) => l.path?.length)
            return (
              <div key={i} className="border-l-2 border-stone-200 pl-3">
                <div className="flex items-baseline gap-2 mb-1.5 flex-wrap">
                  <span className="font-medium text-ink">{d.name}</span>
                  <span className={`font-mono-editorial text-[10px] uppercase tracking-wider ${(d.type || '').includes('multi') ? 'text-violet-600' : 'text-indigo-600'}`}>
                    {(d.type || 'single_label').replace('_', ' ')}
                  </span>
                  <span className="font-mono text-[11px] text-stone-400">{(d.labels || []).length}</span>
                </div>
                {hier ? (
                  <div className="max-h-[280px] overflow-auto pr-1">
                    <WizardTreeLines node={wBuildTree(d.labels || [])} depth={0}
                      levelKinds={[d.gated_by || '', d.category_dimension || '']} />
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {(d.labels || []).map((l: any, j: number) => (
                      <span key={j} className="text-xs px-2 py-0.5 bg-white border border-seam text-stone-700">{l.name}</span>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
        <div className="px-5 py-3 border-t border-seam">
          <button onClick={onClose} className="text-sm px-4 py-1.5 border border-ink hover:bg-paper">Close</button>
        </div>
      </div>
    </div>
  )
}

/* Gated dimension shown as two normal lists: the topics (deduped, editable by
 * name across gate values) and the thematic categories (read-only chips). The
 * conditional tree itself lives in the right-hand "Structure" panel. */
function FlatTwoLists({ dim, onRenameTopic, onRemoveTopic, onAddTopic }: {
  dim: any
  onRenameTopic: (oldName: string, newName: string) => void
  onRemoveTopic: (name: string) => void
  onAddTopic: () => void
}) {
  const labels = dim.labels || []
  const topics: string[] = []
  const seenT = new Set<string>()
  for (const l of labels) if (l.name && !seenT.has(l.name)) { seenT.add(l.name); topics.push(l.name) }
  // Categories are not edited here — they live in their own derived "thematic
  // categories" entry below, which keeps both representations in sync.
  return (
    <div>
      <div className="font-mono-editorial text-[10px] uppercase tracking-wider text-stone-400 mb-1.5">
        {dim.name} · {topics.length}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {topics.map(t => (
          <TopicChip key={t} name={t} onRename={n => onRenameTopic(t, n)} onRemove={() => onRemoveTopic(t)} />
        ))}
        <button onClick={onAddTopic}
          className="text-xs px-2 py-1 border border-dashed border-seam hover:border-ink text-stone-500 hover:text-ink">
          + add
        </button>
      </div>
    </div>
  )
}

function TopicChip({ name, onRename, onRemove }: {
  name: string; onRename: (n: string) => void; onRemove: () => void
}) {
  const [val, setVal] = useState(name)
  useEffect(() => setVal(name), [name])
  return (
    <span className="inline-flex items-center gap-1 bg-white border border-seam pl-2 pr-1 py-0.5">
      <input
        value={val}
        onChange={e => setVal(e.target.value)}
        onBlur={() => { const v = val.trim(); if (v && v !== name) onRename(v); else setVal(name) }}
        style={{ width: `${Math.max(4, val.length)}ch` }}
        className="bg-transparent border-0 focus:outline-none text-xs text-stone-800"
        aria-label="Edit topic name"
      />
      <button onClick={onRemove} className="text-stone-400 hover:text-red-600 text-xs px-0.5" title="Remove topic">×</button>
    </span>
  )
}

function LabelEditor({
  lbl, onChange, onRemove,
}: {
  lbl: any
  onChange: (patch: Partial<any>) => void
  onRemove: () => void
}) {
  const [open, setOpen] = useState(true)
  return (
    <div className="border border-seam bg-paper/40">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <button
          type="button"
          onClick={() => setOpen(o => !o)}
          className="font-mono-editorial text-stone-400 hover:text-ink text-xs w-4 shrink-0"
          title="Toggle definition"
        >
          {open ? '−' : '+'}
        </button>
        <div className="relative flex-1 min-w-0">
          <Pencil className="absolute left-1 top-1.5 h-3 w-3 text-stone-400" aria-hidden="true" />
          <input
            value={lbl.name || ''}
            onChange={e => onChange({ name: e.target.value })}
            className="w-full pl-5 pr-1 py-1 bg-transparent border-0 focus:outline-none focus:bg-white text-sm text-stone-800"
            placeholder="label name"
            aria-label="Edit label name"
          />
        </div>
        <button
          onClick={onRemove}
          className="font-mono-editorial text-stone-400 hover:text-red-600 text-xs px-1"
          title="Remove label"
        >
          ×
        </button>
      </div>
      {open && (
        <div className="relative border-t border-seam bg-white">
          <Pencil className="absolute left-3 top-2.5 h-3 w-3 text-stone-400" aria-hidden="true" />
          <textarea
            value={lbl.definition || ''}
            onChange={e => onChange({ definition: e.target.value })}
            rows={3}
            className="w-full pl-8 pr-3 py-2.5 bg-white text-sm text-stone-700 leading-relaxed focus:outline-none resize-y"
            placeholder="What does this label mean? (definition, edge cases)"
            aria-label="Edit label definition"
          />
        </div>
      )}
    </div>
  )
}
