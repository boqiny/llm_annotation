# AnnotAgent progress

Paper substance lives in `IDEA_REPORT.md` and the LaTeX in `paper_draft/latex/`
(gitignored). Repo guide lives in `CLAUDE.md`.

## Direction

The framing pivoted from "a self-evolving annotator that improves annotation
quality against adjudicated gold" to **personalization**: AnnotAgent learns
interpretable rules from a chosen coder's own labels and aligns the annotator to
that coder. On subjective dimensions there is no single gold, so each annotator
is a separate alignment target. The old adjudication-as-data-cleaning
contribution (C1), the cold-start Flow A, and the matched-N overlay are dropped.

The system handles two label types with a config matched to each:

- **single-label** dimensions: predict one class; the Governor scores accuracy.
- **multi-label** dimensions: predict a label set; the Governor scores set F1 and
  mines rules from set errors (missed label is a recall error, extra label is a
  precision error).

---

## Built

### Backend / system

- [x] FastAPI + async SQLAlchemy + SQLite; ~12 API modules; FK enforcement;
      startup sweep of orphaned running/pending rows.
- [x] CodebookAgent (Ingestor / Drafter / Critic) for PDF / DOCX / XLSX / CSV /
      JSON / TXT.
- [x] AutoPromptGenerator: per-dimension, parallel, versioned on disk.
- [x] PipelineRunner: async, pause / cancel / resume, WebSocket progress.
- [x] ReflectAgent (PatternExtractor + Governor): rollback plus a
      leakage-guarded train / val / test split, held-out test scored once.
- [x] Cross-session Memory (`ReflectMemoryVersion`): seeds the next run from the
      latest version.
- [x] DSPy baselines: GEPA / MIPROv2 / OPRO.
- [x] Per-class P / R / F1 on held-out test in the run artifact.

### Frontend

- [x] Home redesign: split hero with the workflow figure, compact step grid,
      plain-language onboarding, one clear primary CTA.
- [x] Guided onboarding tour (golden path).
- [x] Numbered project sub-nav (Setup / Prompts / Annotate).
- [x] Setup, Codebook view, Improve (prompts + trajectory + Memory), Annotate,
      Results (per-class P / R / F1, confusion matrix, CSV / JSON export).

### This session

- [x] **Per-user alignment eval** (`backend/scripts/run_per_user_eval.py`):
      stratified train / val / test, zero-shot vs ReflectAgent, agreement against
      each annotator's held-out labels; saves the per-round val trajectory. Ran
      Fiona and Chang on self-disclosure (4 dimensions).
- [x] **Multi-label config (B)** + diagnostic
      (`backend/scripts/multilabel_diag.py`): set prediction, set parser, set-F1
      Governor, rule mining from set errors; micro / macro P / R / F1 via
      `compute_metrics_multilabel`. Saves everything (prompts, rules, trajectory,
      full predictions, per-label metrics).
- [x] **AI-behavior data cleaning** (`backend/scripts/clean_raw_annotations.py`):
      header-driven parse of the raw Fiona / Chang CSVs, splits `&`-packed label
      cells, filters Chang's mixed-behavior rows into
      `*_ai_behavior_ground_truth.json`.
- [x] **Harm dropped**: the data is unusable (Fiona is almost all "No harm";
      Chang-Harm is a mis-exported AI-behavior file). Removed the preset and all
      paper references.
- [x] **Paper reframed to personalization** (IDEA_REPORT.md + paper_draft/latex):
      title, abstract, intro, evaluation (per-coder gold), per-annotator results
      table, method (the two configs), conclusion, limitations.
- [x] **UI screenshot tool** (`frontend/scripts/shot.mjs`, `npm run shot`) and a
      `.env` loader fix so an empty placeholder no longer shadows a populated
      parent `.env`.

---

## Results so far

Self-disclosure, Improve-tab defaults (budget 5, split 0.15 / 0.42 / 0.43),
agreement = accuracy against that annotator's held-out labels (`exp_result.md`):

- Fiona: 59.8% to 70.7% mean (+10.9 pp). Confession +25, Intimacy +23.
- Chang: 57.9% to 68.1% mean (+10.3 pp). Level +20, Intimacy +12.

AI-behavior, Fiona, Listening strategy (multi-label config B, budget 5, test
n=88, `exp_result_ai_behavior_fiona.json`):

- micro-F1 0.655 to 0.732, precision 0.578 to 0.646, recall 0.756 to 0.846,
  exact-match 0.330 to 0.409. macro-F1 flat (rare labels with tiny support).

---

## TODO

### Validation

- [ ] **Enforce that user-provided input matches the codebook schema the user
      designed; raise an error on mismatch.** Labeled-data uploads and annotation
      inputs whose dimensions or label values are not in the active codebook
      should be rejected with a clear error, not silently dropped or coerced (the
      current ingest filter drops non-matching labels quietly).

### Eval

- [ ] **Multi-seed eval**: re-run each split with at least 3 seeds and report
      mean and standard deviation, so the per-annotator gains are not read as
      single-split noise.
- [ ] **Specificity control** (cross-target): score the prompt tuned for coder A
      on A-test and B-test; the diagonal should beat the off-diagonal, proving the
      loop learns a specific coder's standard rather than improving generically.
- [ ] Wire config B into `run_per_user_eval.py` as the auto-routed multi-label
      pipe (route by `dim_type`), replacing the single-label explosion.
- [ ] Run Chang AI-behavior and Fiona Support type; fill the paper's AI-Behavior
      table rows and the validation curves.
- [ ] Optional: one weaker / cheaper model run on one codebook, to rebut "the
      gain is just a strong model."

### Paper / demo

- [ ] Render the workflow figure; fill the per-annotator table's AI-Behavior rows
      and the trajectory figure from exported curves.
- [ ] Screenshot pack: Setup, Improve, Annotate, Results.
- [ ] Hosted demo URL and a 2.5-minute screencast.
- [ ] Keep IDEA_REPORT.md and paper_draft/latex on one personalization story end
      to end; internal review.

---

## Known issues

- [ ] Multi-label optimization (config B) is validated in the diagnostic script
      only; not yet integrated into the main eval or the system's optimizer path.
- [ ] `create_all()` does not migrate existing tables; switch to Alembic if
      schema changes get painful.
- [ ] DSPy baselines untested with cross-session memory (reflect_agent-only).

## Smoke tests

- **Auto-prompt path**: new project, upload codebook, Generate pipeline, per-dim
  cards appear.
- **Memory loop**: run reflect_agent on dim X, run again on X, round 0 trajectory
  shows `action: baseline_seeded`.
- **UI screenshot**: `cd annotagent/frontend && npm run shot -- / /tmp/home.png --full`, then read the PNG.

## Backlog

- [ ] Memory reset endpoint + UI button
- [ ] Prompt diff view (starting vs optimized)
- [ ] Manual rule editor in the Memory section
- [ ] Cost estimate before launching a run