# AnnotAgent — progress

System works end-to-end. Eval + paper + video left.

Paper plan: `IDEA_REPORT.md`. Repo guide: `CLAUDE.md`.

---

## System

### Backend
- [x] FastAPI + SQLAlchemy async + SQLite, ~12 API modules
- [x] FK enforcement on aiosqlite + cascade walk on project delete
- [x] Server-startup sweep of orphaned `running` / `pending` rows
- [x] CodebookAgent (Ingestor / Drafter / Critic) for PDF / DOCX / XLSX / CSV / JSON / TXT
- [x] **AutoPromptGenerator** — per-dimension, parallel, versioned on disk
- [x] Decomposer with `per_dimension` (default) / `all_together` / `auto` modes
- [x] PipelineRunner — async, pause / cancel / resume, WebSocket progress
- [x] ReflectAgent (PatternExtractor + Governor) with rollback + leakage guard
- [x] Cross-session **Memory** (`ReflectMemoryVersion`) — seeds next run from latest
- [x] Per-class P/R/F1 on held-out test, stored in run artifact
- [x] DSPy baselines: GEPA / MIPROv2 / OPRO
- [x] Cooperative cancel via `_RUNNING_TASKS` registry

### Frontend
- [x] Landing — hero + 4-step workflow figure (deterministic SVG)
- [x] Setup — codebook wizard with **editable draft preview**, optional dataset
- [x] Codebook view — clean schema, no IAA noise
- [x] Improve page
  - [x] § 00 Current prompts — per-dim cards, defaults to optimized version
  - [x] § 01 What to improve — sample-availability panel + train/val/test preview
  - [x] § 02 Recent improvements — runs list, hover delete + cancel, line chart, per-class table, editable optimized prompt
  - [x] § 03 Memory — versioned rule library per dimension
- [x] Annotate page — `per-dim ↔ all-together` toggle, seeds gated to self-disclosure, upload-your-own
- [x] Monitor + Results — accuracy bars, macro F1, confusion matrix, CSV/JSON export
- [x] Researcher-mode toggle hides all jargon by default

### Repo
- [x] `annotagent/` is the only live tree; `legacy/` archived
- [x] `annotation_demo/` deleted, value ported in
- [x] Bundled seed data in `annotagent/assets/data/`
- [x] DB gitignored, auto-recreated empty on first start
- [x] TypeScript clean, 53 backend routes load

---

## Paper to-do

- [ ] **Table A** — per-dim self-disclosure (5 dims × zero-shot vs ReflectAgent on `gpt-5.4-mini`). ~3h, ~$10
- [ ] **Table B** — model sweep on flagship dim (gpt-5.4-mini / gpt-5.4 / claude-sonnet-4-5). ~2h, ~$20
- [ ] **Table C** — optimizer comparison: ReflectAgent vs GEPA / MIPROv2 / OPRO. ~2h, ~$10
- [ ] **Demo video** — 2.5 min, narrated, 9-step script in IDEA_REPORT
- [ ] **Screenshot pack** — 8–10 PNGs (default + Researcher mode)
- [ ] **Hosted deploy** — Render or Fly, 24h reset
- [ ] **Paper draft** — 6 pages
- [ ] **Internal review + polish**

---

## Backlog (not paper-blocking)

- [ ] Memory reset endpoint + UI button
- [ ] Filter Recent improvements by dimension
- [ ] Prompt diff view (auto_v001 vs v002, or starting vs optimized)
- [ ] Manual rule editor in Memory section
- [ ] Multi-label support in the optimizer's evaluate loop (annotator side already handles it)
- [ ] Cost estimate before launching a run
- [ ] Per-class P/R/F1 as a bar chart instead of a table

## Known issues

- [ ] `create_all()` doesn't migrate existing tables — new FK constraints don't apply to old DBs. Switch to Alembic if this gets painful.
- [ ] DSPy baselines untested with cross-session memory (memory is reflect_agent-only by design).
- [x] ~~`metadata` field clashes with `Base.metadata` on `DataItemOut`~~ (fixed via `validation_alias` + `serialize_by_alias`)

---

## Smoke tests

- **Auto-prompt path**: new project → upload codebook → Generate pipeline → wait for per-dim cards
- **Memory loop**: run reflect_agent on dim X → wait for done → run again on X → round 0 trajectory shows `action: baseline_seeded`, `n_rules: <prior>`
