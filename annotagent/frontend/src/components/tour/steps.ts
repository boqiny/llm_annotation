// Golden-path onboarding tour: create a project, set it up, run one optimization.
//
// The tour is a FOLLOWER of app state, not a clickable slideshow. There is no
// Next button. The tour shows guidance for whatever page and section the user is
// actually on, and it advances only when the user performs the real action. The
// app already gates progress (you cannot reach the Prompts hub without a model, a
// codebook, and clicking Generate), so the tour cannot run ahead of the work.
//
// Each step's anchor is a [data-tour="<id>"] element. For a page, the tour picks
// the highest-numbered step whose anchor is on screen, so it tracks the furthest
// section the user has opened (for example, the create form once it is open, or
// the Improve tab once it is selected).
//
// `need` is the mandatory requirement for a step. While the step's anchor carries
// data-tour-done="false", the tour shows `need` so the user knows what is still
// missing. The app sets data-tour-done from its own completion state.

export type TourPage = 'home' | 'setup' | 'lab'

export type TourStep = {
  id: string
  selector: string
  page: TourPage
  title: string
  body: string
  need?: string
}

export const TOUR_STEPS: TourStep[] = [
  {
    id: 'create-project',
    selector: '[data-tour="create-project"]',
    page: 'home',
    title: 'Create a project',
    body: 'One project holds one annotation task. Click New project to open the form.',
  },
  {
    id: 'name-project',
    selector: '[data-tour="name-project"]',
    page: 'home',
    title: 'Name your project',
    body: 'Type a name, then click "Create & go to Setup".',
  },
  {
    id: 'setup-model',
    selector: '[data-tour="setup-model"]',
    page: 'setup',
    title: 'Step 1 · Model',
    body: 'Choose a provider and model, then paste your API key. Then open "02 Codebook".',
    need: 'Still needed: a model and an API key.',
  },
  {
    id: 'setup-codebook',
    selector: '[data-tour="setup-codebook"]',
    page: 'setup',
    title: 'Step 2 · Codebook',
    body: 'Your label schema. No codebook? Use a preset, or upload or draft one. Then open "03 Labeled data".',
    need: 'Still needed: pick, upload, or draft a codebook.',
  },
  {
    id: 'setup-data',
    selector: '[data-tour="setup-data"]',
    page: 'setup',
    title: 'Step 3 · Labeled data',
    body: 'Optional but recommended: add a few labeled examples, or load a preset dataset. The optimizer uses them to improve prompts.',
  },
  {
    // Anchor matches only when the button is enabled (data-tour-ready="true"), so
    // this step appears the moment Setup is ready and overrides the panel steps —
    // wherever the user is, it tells them to generate.
    id: 'generate-pipeline',
    selector: '[data-tour="generate-pipeline"][data-tour-ready="true"]',
    page: 'setup',
    title: 'Generate the pipeline',
    body: 'Setup is ready. Click Generate pipeline to draft one prompt per dimension and open the Prompts hub.',
  },
  {
    id: 'lab-prompts',
    selector: '[data-tour="first-prompt"]',
    page: 'lab',
    title: 'Your starting prompts',
    body: 'AnnotAgent drafts one prompt per dimension from your codebook; the first appears here. Read or edit it, then open the Improve tab to optimize a prompt against your labeled examples.',
  },
  {
    id: 'run-improvement',
    selector: '[data-tour="run-improvement"]',
    page: 'lab',
    title: 'Run an optimization',
    body: 'Pick a dimension and labeled set, set rounds, then Run improvement. It scores each change on held-out data first.',
  },
]

export function pageOf(pathname: string): TourPage | null {
  if (pathname === '/') return 'home'
  if (pathname.includes('/prompt-lab')) return 'lab'
  if (pathname.includes('/setup')) return 'setup'
  return null
}

// The step the tour should show on a given page: the furthest section the user
// has opened (highest index) whose anchor is currently on screen.
export function stepForPage(page: TourPage): TourStep | null {
  for (let i = TOUR_STEPS.length - 1; i >= 0; i--) {
    const s = TOUR_STEPS[i]
    if (s.page === page && document.querySelector(s.selector)) return s
  }
  // No anchor mounted yet (a panel is still loading). Fall back to the first
  // step of the page so the tour can show a hint while it waits.
  return TOUR_STEPS.find(s => s.page === page) ?? null
}
