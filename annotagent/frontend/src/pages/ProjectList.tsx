import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  listProjects, createProject, deleteProject,
  listPresets, uploadCodebook, listSeedDatasets, loadSeedDataset, decomposePipeline,
  listPipelines,
} from '../lib/api'
import { useTour } from '../components/tour/TourProvider'
import type { Project } from '../types'
import { APP_NAME } from '../lib/brand'

export default function ProjectList() {
  const [projects, setProjects] = useState<Project[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [demoBusy, setDemoBusy] = useState(false)
  const [demoError, setDemoError] = useState<string | null>(null)
  const navigate = useNavigate()
  const { start } = useTour()

  // Open the create form and bring it into view. This is the hero CTA a
  // first-time visitor reaches for before scrolling to the projects band.
  const openCreate = () => {
    setShowCreate(true)
    setTimeout(
      () => document.getElementById('projects-band')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
      50,
    )
  }

  useEffect(() => { listProjects().then(setProjects) }, [])

  // Open a project where the user left off: if a pipeline already exists (setup
  // is done), go straight to Prompts; otherwise start at Setup.
  const openProject = async (id: number) => {
    try {
      const pipelines = await listPipelines(id)
      navigate(pipelines.length > 0
        ? `/projects/${id}/prompt-lab?tab=prompts`
        : `/projects/${id}/setup`)
    } catch {
      navigate(`/projects/${id}/setup`)
    }
  }

  const handleCreate = async () => {
    if (!name.trim()) return
    const project = await createProject({ name, description })
    setProjects([project, ...projects])
    setShowCreate(false); setName(''); setDescription('')
    navigate(`/projects/${project.id}/setup`)
  }

  const handleDelete = async (id: number) => {
    await deleteProject(id)
    setProjects(projects.filter(p => p.id !== id))
  }

  // One-click demo: build a ready-to-run project (preset self-disclosure codebook
  // + Coder A's labels as the gold target, Coder B as reference, + generated
  // prompts) and land on the Improve page, so a first-time visitor reaches a working
  // golden path with no setup. Preset prompts are deterministic, so this needs no
  // API key; running the loop later does.
  const startDemo = async () => {
    setDemoBusy(true); setDemoError(null)
    try {
      const project = await createProject({
        name: 'Demo · Align to Coder A',
        description: 'One-click demo: calibrate the annotator to Coder A on a self-disclosure codebook.',
      })
      const preset = (await listPresets(project.id)).find(p => p.name === 'self_disclosure')
      if (preset) await uploadCodebook(project.id, { preset_name: preset.name })
      const seeds = await listSeedDatasets(project.id)
      // The wedge is per-coder alignment, so the gold target is one chosen coder
      // (Coder A), with the second coder (Coder B) loaded as reference for contrast.
      const target = seeds.find(s => s.id === 'sd_coder_a' && s.available)
        ?? seeds.find(s => s.role === 'reference' && s.available)
        ?? seeds.find(s => s.available)
      if (target) await loadSeedDataset(project.id, target.id, true)
      const other = seeds.find(s => s.id === 'sd_coder_b' && s.available)
      if (other) await loadSeedDataset(project.id, other.id, false)
      await decomposePipeline(project.id)
      navigate(`/projects/${project.id}/prompt-lab?tab=prompts`)
    } catch {
      setDemoError('Could not finish building the demo. Open the project from the list to complete setup.')
      setDemoBusy(false)
      listProjects().then(setProjects)
    }
  }

  return (
    <div className="space-y-16">
      {/* Hero — split: the statement on the left, the workflow visual on the
          right. Collapses to a single column (text, then figure) below lg. */}
      <section className="pt-6 pb-2 grid lg:grid-cols-12 gap-10 items-center">
        <div className="lg:col-span-5">
          <div className="font-mono-editorial text-stone-500 mb-6">
            Codebook-aligned text annotation
          </div>
          <h1 className="text-5xl font-medium tracking-tight leading-[0.95]">
            Label text the way<br />
            <span className="italic font-display font-normal">you</span> would.
          </h1>
          <p className="mt-7 text-xl leading-relaxed text-stone-600 max-w-md">
            You set the labels. {APP_NAME} writes the prompts and labels the rest.
          </p>
          <div className="mt-9 flex flex-wrap items-center gap-5">
            <button
              onClick={startDemo}
              disabled={demoBusy}
              className="px-6 py-3 bg-ink text-cream text-sm font-medium hover:bg-stone-800 transition-colors disabled:opacity-50"
            >
              {demoBusy ? 'Building demo…' : 'Try the live demo →'}
            </button>
            <button
              onClick={openCreate}
              className="px-6 py-3 border border-ink/30 text-ink text-sm font-medium hover:border-ink transition-colors"
            >
              Start your own project
            </button>
            <button
              onClick={start}
              className="text-sm font-medium text-stone-500 hover:text-ink transition-colors underline-offset-4 hover:underline"
            >
              or take the 60-second tour
            </button>
          </div>
          {demoError && (
            <p className="mt-4 text-sm text-red-700">{demoError}</p>
          )}
        </div>
        <figure className="lg:col-span-7">
          <img
            src="/workflow_0705.png"
            alt={`${APP_NAME} workflow: set up, generate, refine, then get results`}
            className="w-full h-auto block"
            onError={(e) => { (e.currentTarget.style.display = 'none') }}
          />
        </figure>
      </section>

      {/* How it works: four steps in a compact 2x2 grid (the workflow figure
          now lives in the hero). Collapses to one column below sm. */}
      <section className="border-t border-seam pt-12">
        <h2 className="text-3xl font-medium tracking-tight mb-10">From your labels to a labeled dataset, in four steps</h2>

        <ol className="grid sm:grid-cols-2 gap-x-12 gap-y-9">
          <Step
            n="01"
            title="Define your labels"
            body="Bring your codebook, or start from a ready-made example and edit it."
          />
          <Step
            n="02"
            title="It writes the prompts"
            body={`${APP_NAME} turns each label into LLM instructions. You write nothing.`}
          />
          <Step
            n="03"
            title="Show a few examples"
            body="It studies your labeled examples and tunes itself to match how you label."
          />
          <Step
            n="04"
            title="Label everything"
            body="Run it on your whole dataset and export the results as CSV or JSON."
          />
        </ol>
      </section>

      {/* Projects band */}
      <section id="projects-band" className="scroll-mt-24">
        <div className="flex items-end justify-between pb-4 mb-4">
          <div>
            <div className="font-mono-editorial text-stone-500 mb-2">
              Total projects: {projects.length}
            </div>
            <h2 className="text-3xl font-medium tracking-tight">Your projects</h2>
          </div>
          <button
            data-tour="create-project"
            onClick={() => setShowCreate(v => !v)}
            className="group inline-flex items-center gap-2 px-5 py-2.5 bg-ink text-cream text-sm font-medium hover:bg-stone-800 transition-colors"
          >
            <span className="font-mono text-xs">+</span>
            <span>New project</span>
          </button>
        </div>

        {showCreate && (
          <div className="mb-8 border border-seam bg-white p-6" data-tour="name-project">
            <div className="font-mono-editorial text-stone-500 mb-4">Create a new project</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div>
                <label className="block font-mono-editorial text-stone-500 mb-2">Name</label>
                <input
                  autoFocus
                  value={name}
                  onChange={e => setName(e.target.value)}
                  className="w-full px-0 py-2 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none text-base font-medium"
                  placeholder="My annotation project"
                />
              </div>
              <div>
                <label className="block font-mono-editorial text-stone-500 mb-2">Description · optional</label>
                <input
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  className="w-full px-0 py-2 bg-transparent border-0 border-b border-seam focus:border-ink focus:outline-none text-base"
                  placeholder="What are you annotating, and why?"
                />
              </div>
            </div>
            <div className="flex items-center gap-3 mt-6">
              <button
                onClick={handleCreate}
                disabled={!name.trim()}
                className="px-5 py-2 bg-ink text-cream text-sm font-medium disabled:opacity-40"
              >
                Create & go to Setup →
              </button>
              <button onClick={() => setShowCreate(false)} className="text-sm text-stone-500 hover:text-ink">
                Cancel
              </button>
            </div>
          </div>
        )}

        {projects.length === 0 ? (
          <EmptyState onCreate={() => setShowCreate(true)} />
        ) : (
          <ul className="divide-y divide-seam border-y border-seam">
            {projects.map(p => (
              <ProjectRow
                key={p.id}
                project={p}
                onOpen={() => openProject(p.id)}
                onDelete={() => handleDelete(p.id)}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function Step({ n, title, body }: { n: string; title: string; body: string }) {
  return (
    <li className="grid grid-cols-12 gap-4 list-none">
      <div className="col-span-2 font-mono-editorial text-stone-400 pt-1">{n}</div>
      <div className="col-span-10">
        <h3 className="text-xl font-medium tracking-tight mb-1.5">{title}</h3>
        <p className="text-sm text-stone-600 leading-relaxed">{body}</p>
      </div>
    </li>
  )
}

function formatDate(value: string | null) {
  if (!value) return '—'

  // Backend stores naive UTC (SQLite func.now()); mark it UTC explicitly so the
  // viewer's local timezone can't misparse it, then render in Pacific. The short
  // timeZoneName resolves to PST/PDT automatically across DST.
  const utc = /(?:Z|[+-]\d\d:?\d\d)$/.test(value) ? value : value + 'Z'
  const date = new Date(utc)
  if (Number.isNaN(date.getTime())) return '—'

  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'America/Los_Angeles',
    timeZoneName: 'short',
  })
}

function ProjectRow({
  project, onOpen, onDelete,
}: {
  project: Project
  onOpen: () => void
  onDelete: () => void
}) {
  const statusTone =
    project.status === 'completed' ? 'text-emerald-700' :
    project.status === 'running' ? 'text-blue-700' :
    'text-stone-500'

  return (
    <li className="group">
      <div
        onClick={onOpen}
        className="grid grid-cols-12 gap-6 py-6 px-2 cursor-pointer hover:bg-paper/60 transition-colors"
      >
        <div className="col-span-1 font-mono-editorial text-stone-400 pt-1">
          {project.id.toString().padStart(3, '0')}
        </div>
        <div className="col-span-4">
          <div className="flex items-baseline gap-3">
            <h3 className="text-xl font-medium tracking-tight">{project.name}</h3>
            <span className={`font-mono-editorial ${statusTone}`}>· {project.status}</span>
          </div>
          {project.description && (
            <p className="mt-1 text-sm text-stone-600 leading-relaxed">{project.description}</p>
          )}
        </div>
        <div className="col-span-3 pt-1">
          <div className="font-mono-editorial text-stone-500 mb-1">Created</div>
          <div className="font-mono text-xs text-stone-700">
            {formatDate(project.created_at)}
          </div>
        </div>
        <div className="col-span-2 pt-1">
          <div className="font-mono-editorial text-stone-500 mb-1">Model</div>
          <div className="font-mono text-xs text-stone-700 truncate">{project.llm_provider} / {project.llm_model}</div>
        </div>
        <div className="col-span-2 flex items-center justify-end gap-4 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={e => { e.stopPropagation(); onDelete() }}
            className="font-mono-editorial text-stone-400 hover:text-red-600"
          >
            Delete
          </button>
          <span className="text-stone-400 group-hover:text-ink transition-colors">→</span>
        </div>
      </div>
    </li>
  )
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="border border-dashed border-seam py-20 text-center bg-paper/40">
      <div className="font-mono-editorial text-stone-500 mb-3">No projects yet</div>
      <p className="text-stone-600 max-w-md mx-auto mb-6">
        Start by creating a project — pick a preset codebook or upload your own.
      </p>
      <button onClick={onCreate} className="px-5 py-2.5 bg-ink text-cream text-sm font-medium">
        Create your first project →
      </button>
    </div>
  )
}
