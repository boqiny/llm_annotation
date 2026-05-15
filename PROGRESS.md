# AnnotAgent — progress

Paper substance lives in `IDEA_REPORT.md`. Workflow figure description lives in `WORKFLOW_FIGURE.md`. Repo guide lives in `CLAUDE.md`.

Status: the system as of last week works end-to-end on the gold-label optimization flow (what we now call **Flow C / C2**). Tonight's planning session expanded the scope to two more flows (Flow A cold-start, Flow B disputed-item adjudication) and merged the proposed C1 contribution into a single two-half claim (adjudication mechanism + data-centric overlay measurement). **Nothing from tonight's scope is implemented yet.** This file separates what is built from what we just decided to build.

---

## Built (pre-tonight, in main)

### Backend
- [x] FastAPI + SQLAlchemy async + SQLite, ~12 API modules
- [x] FK enforcement on aiosqlite + cascade walk on project delete
- [x] Server-startup sweep of orphaned `running` / `pending` rows
- [x] CodebookAgent (Ingestor / Drafter / Critic) for PDF / DOCX / XLSX / CSV / JSON / TXT
- [x] AutoPromptGenerator — per-dimension, parallel, versioned on disk
- [x] Decomposer with `per_dimension` (default) / `all_together` / `auto` modes
- [x] PipelineRunner — async, pause / cancel / resume, WebSocket progress
- [x] ReflectAgent (PatternExtractor + Governor) with rollback + leakage guard
- [x] Cross-session Memory (`ReflectMemoryVersion`) — seeds next run from latest
- [x] Per-class P/R/F1 on held-out test, stored in run artifact
- [x] DSPy baselines: GEPA / MIPROv2 / OPRO
- [x] Cooperative cancel via `_RUNNING_TASKS` registry

### Frontend
- [x] Landing — hero + 4-step workflow figure
- [x] Setup — codebook wizard with editable draft preview, optional dataset
- [x] Codebook view — clean schema, no IAA noise
- [x] Improve page — current prompts, what to improve, recent improvements, Memory
- [x] Annotate page — per-dim ↔ all-together toggle, seeds gated to self-disclosure, upload-your-own
- [x] Monitor + Results — accuracy bars, macro F1, confusion matrix, CSV/JSON export
- [x] Researcher-mode toggle hides all jargon by default

### Repo
- [x] `annotagent/` is the only live tree; `legacy/` archived
- [x] `annotation_demo/` deleted, value ported in
- [x] Bundled seed data in `annotagent/assets/data/`
- [x] DB gitignored, auto-recreated empty on first start
- [x] TypeScript clean, 53 backend routes load

---

## Tonight's new scope — not yet implemented

### Gate before anything else: the C1 verification spike

C1 is a proposal whose empirical premise is unverified. The spike answers whether rules mined from the agreed subset transfer to disputed items on a real codebook. If the spike comes back positive, we build the full C1 pipeline below. If it comes back negative, we ship a negative-result paragraph and skip the UI work.

- [ ] **C1 spike on Fiona, dimension `Level`** — offline notebook or script
  - [ ] Build agreed/disputed split from per-annotator data
  - [ ] Run existing ReflectAgent on the agreed subset; record trajectory
  - [ ] Apply final rule-augmented prompt zero-shot to disputed items; record verdict + cited rules per item
  - [ ] Compare verdicts to Fiona's eventually-adjudicated labels
  - [ ] Compute `rate_grounded` (cited_rules non-empty), `acc_disputed_with_rules` vs `acc_disputed_zero_shot`, bias check (correlation of LLM verdict with each individual annotator)
  - [ ] Decision: ship C1 or pivot to negative result

### C1 — adjudication-as-data-cleaning loop (build only if spike is positive)

The proposed contribution has two halves; both must clear empirically for C1 to ship as a positive result. The first half is the adjudication mechanism (gated on the verification spike above). The second half is the overlay measurement (gated on the first half producing an adjudicated corpus).

**Mechanism — backend:**
- [ ] `DataItem.labels_by_annotator: dict[str, dict[str, str | list[str]]]` schema extension
- [ ] Per-annotator dataset ingest: join two or more annotator files on item index or user-selected key column; allow missing values
- [ ] IAA computation per dimension: Cohen's κ pairwise (N=2 or any selected pair), Fleiss' κ (N≥3, no missing), Krippendorff's α (default, any N, missing OK)
- [ ] Agreement-mode toggle: `unanimous` (default) / `majority` / `plurality`
- [ ] Derived fields per item × dimension: `agreed`, `disputed`, `consensus_label`
- [ ] PatternExtractor variant prompt for "mine rules from agreed items" (positive evidence) — same output schema as failure mining
- [ ] Annotator output schema extension: `verdict`, `confidence`, `reasoning`, `cited_rules`, `human_labels`
- [ ] Ungrounded-verdict flag when `cited_rules` is empty for non-default verdicts
- [ ] "Snapshot agreed-only subset as derived Dataset" endpoint
- [ ] Disagreement Review API: list disputed items, post accept/override/skip, recompute IAA on action

**Mechanism — frontend:**
- [ ] Setup wizard: multi-annotator file ingest, key-column picker
- [ ] Improve page: IAA panel per dimension with κ / α and Landis-Koch threshold labels
- [ ] Improve page: agreement-mode toggle (Researcher mode)
- [ ] Improve page: "Learn from the agreed items" button (runs ReflectAgent on agreed subset)
- [ ] **New: Disagreement Review page** — disputed-item queue, side-by-side annotator labels, LLM verdict + reasoning + cited rules with clickable popovers, Accept/Override/Skip controls
- [ ] IAA delta arrow on action (treats LLM verdict as additional rater on resolved item)
- [ ] Frontend: ungrounded-verdict yellow flag rendering

**Measurement — backend:**
- [ ] "Matched-N random slice" derived-dataset helper (fixed seed, A items sampled from A+D corpus)
- [ ] Optimizer run metadata to identify a run as one of `agreed-only` / `full-post-adjudication` / `matched-N` for plotting

**Measurement — frontend:**
- [ ] Improve page: "Compare runs" toggle / multi-select for two or three runs
- [ ] Trajectory chart: overlay multiple runs on same axes, color-coded, with run-id legend
- [ ] Inline annotation on the chart at the plateau and the lift point

**Measurement — paper:**
- [ ] Run the three optimizer runs on the flagship dimension; export trajectory data
- [ ] Render Figure 4 (the overlay curve) from exported trajectories
- [ ] Render matched-N appendix figure

### Flow A — cold-start labeling

Backend:
- [ ] Annotator interactive mode: API for "label next item" returning prefilled verdict + reasoning per dimension
- [ ] Accept/edit/reject commit endpoint that writes to `gold_labels` and bumps the accepted-label count
- [ ] Threshold trigger: when accepted count per dim crosses a configurable N (default 20), schedule a background ReflectAgent run
- [ ] Background ReflectAgent run writes a new Memory version and updates the active prompt; queue position survives the prompt change

Frontend:
- [ ] **New: Cold-start Labeling page** — one-item-at-a-time view, prefilled dimensions with reasoning, Accept/Edit/Reject controls, queue position counter
- [ ] "Pre-fill improved (rev N)" badge surfaces when shadow ReflectAgent commits a new prompt
- [ ] Smooth queue advance: no scroll jumps on commit

### Workflow figure

The figure description in `WORKFLOW_FIGURE.md` was redesigned tonight (vertical six-stage layout). It is not yet rendered.

- [ ] Render the workflow figure from `WORKFLOW_FIGURE.md` (via figure-spec, paper-illustration, or manual SVG)
- [ ] Iterate on layout until it passes the 30-second sanity checklist at the bottom of `WORKFLOW_FIGURE.md`

### Paper artifacts

- [ ] Table A — per-dim self-disclosure (5 dims × zero-shot vs ReflectAgent on `gpt-5.4-mini`) — C2
- [ ] Table B — adjudication metrics on disputed items (depends on C1 spike outcome) — C1 mechanism
- [ ] Figure 4 — the overlay curve plus matched-N appendix variant — C1 measurement
- [ ] Supporting context: throughput, raw IAA on Fiona, memory growth across sessions
- [ ] Screenshot pack — at minimum: Setup, Improve, Disagreement Review (new), Annotate, Results
- [ ] Hosted demo URL — Render or Fly, 24h reset
- [ ] First paper draft (arxiv format, no fixed page budget yet)
- [ ] Internal review + polish

---

## Open questions and gates

- **Does C1 ship?** Gated on the verification spike result. Block all C1 UI/backend work until the spike comes back.
- **What is the agreement-mode default for projects with N ≥ 3?** Plan says `unanimous`. Revisit if Fiona/Chang at N=3+ produces too few agreed items to train rules on.
- **Does the shadow ReflectAgent in Flow A interfere with the user's flow?** A mid-session prompt update could surprise the user if the prefill style shifts noticeably mid-queue. Watch for this when the cold-start page is first usable.
- **Matched-N: random slice or stratified?** Plan says random with fixed seed. Stratified (matched class proportions) is cheap to add and may produce a tighter control.

---

## Smoke tests (still apply)

- **Auto-prompt path** — new project → upload codebook → Generate pipeline → wait for per-dim cards
- **Memory loop** — run reflect_agent on dim X → wait for done → run again on X → round 0 trajectory shows `action: baseline_seeded`, `n_rules: <prior>`

To-add once C1 / C3 / Flow A ship:

- [ ] **C1 mechanism** — upload N annotator files → see IAA panel → click "Learn from agreed" → open Disagreement Review → accept first three items → IAA delta arrow updates
- [ ] **C1 measurement** — after a Flow B session, run Flow C on agreed-only and full corpus from same `auto_v001`; "Compare runs" overlay shows two curves on same axes
- [ ] **Flow A path** — fresh project, no labels → label 25 items → "Pre-fill improved (rev 2)" badge appears → labeling continues without queue jump

---

## Known issues

- [ ] `create_all()` does not migrate existing tables — new FK constraints do not apply to old DBs. Switch to Alembic if this gets painful.
- [ ] DSPy baselines untested with cross-session memory (memory is reflect_agent-only by design).
- [ ] No multi-label support in the optimizer's evaluate loop (annotator side already handles it).

---

## Backlog (not paper-blocking)

- [ ] Memory reset endpoint + UI button
- [ ] Filter Recent improvements by dimension
- [ ] Prompt diff view (auto_v001 vs v002, or starting vs optimized)
- [ ] Manual rule editor in Memory section
- [ ] Cost estimate before launching a run
- [ ] Per-class P/R/F1 as a bar chart instead of a table
