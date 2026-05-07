# AnnotAgent — EMNLP 2026 Demo Paper Plan

**Target**: EMNLP 2026 System Demonstrations (6-page limit, ≤2.5 min video, live demo, public repo)
**Date**: 2026-04-24
**Status**: system working end-to-end · remaining work is an open-data eval run, video, screenshots, and the paper draft

---

## Pitch

> **A multi-agent annotation workbench that learns from its own mistakes.**

Extended: an end-to-end, runnable system that turns a researcher's messy codebook materials into a working LLM annotator, then quietly improves itself by reviewing its own errors against gold examples — no machine-learning expertise required from the user.

**Audience the UI assumes:** an HCI / qualitative / social-science researcher with a coding manual and ~hundreds of items. Not an ML practitioner. The default surface uses plain English ("Improve from examples", "Apply learned guidance"); algorithmic names (ReflectAgent, GEPA, MIPROv2, OPRO) live behind a single "Researcher mode" toggle for the paper-relevant audience and reproducibility.

---

## Scope

**System applicability:** general single-label and multi-label classification over text with a codebook — any task where a human annotator would read a sentence (or short passage) and assign categorical labels along one or more dimensions.

**Flagship showcase:** AI-companion conversation analysis. User-side self-disclosure (5 dimensions, single-label) and AI-side behavior (3 themes, multi-label), annotated on adjudicated dialogues — chosen because it exposes the hardest case: subtle, multi-dimensional, low-IAA codebooks where adjudication is expensive. All evaluation runs on this flagship; no public-dataset substitute is bundled, since this is a demo paper, not an empirical-results paper.

---

## Paper shape — 6-page budget (references uncounted)

| Section | Pages | Contents |
|---|---|---|
| 1. Introduction | 1.0 | Problem + pitch + demo teaser screenshot + contributions |
| 2. System architecture | 1.5 | 4-agent figure · per-agent paragraph · stack summary |
| 3. Workflow & UI (flagship demo) | 1.5 | End-to-end walkthrough with 4–5 screenshots: messy XLSX → annotations |
| 4. Evaluation | 1.125 | Table A (flagship, private) · Table B (GoEmotions × 3 models, public) · throughput · IAA panel |
| 5. Related work | 0.375 | 0.75-column block: CrowdAgent · EvoAgentX · offline prompt-repair (GEPA/MIPROv2/OPRO) |
| 6. Availability & limitations | 0.5 | URL · repo · install · known limits |
| References | (free) | does not count against the 6-page limit |
| **Total** | **6.0** | |

Screenshots + diagrams together eat ~1.5 pages. With references off the page-count, evaluation gains room for a third table and a small throughput/IAA panel.

---

## System — four cooperating agents

```
           ┌────────────────────────────────────────────────────────────┐
           │  CodebookAgent                                              │
  messy ───│  Ingestor → Drafter → Critic                               │──▶ structured codebook
  input    │  (PDF/DOCX/XLSX/CSV/JSON/TXT, auto mode-inference)         │
           └────────────────────────────────────────────────────────────┘
                                │
                                ▼
           ┌────────────────────────────────────────────────────────────┐
           │  Annotator                                                  │
           │  dependency-aware pipeline · single + multi-label support  │
           └────────────────────────────────────────────────────────────┘
                                │
                                ▼
           ┌────────────────────────────────────────────────────────────┐
           │  ReflectAgent (the standout module)                         │
           │  Online, reflective (cf. batch/offline GEPA · MIPRO · OPRO)│
           │  Per round: PatternExtractor mines failure batch → rules   │
           │  Governor evaluates on held-out val; rolls back on regress │
           │  Accumulates an editable, versioned Rule Library           │
           └────────────────────────────────────────────────────────────┘
                                │
                                ▼
           ┌────────────────────────────────────────────────────────────┐
           │  Improve page (UI module)                                   │
           │  Default: "Improve from examples" (one button)             │
           │  Researcher mode: ReflectAgent · GEPA · MIPROv2 · OPRO     │
           └────────────────────────────────────────────────────────────┘
```

### Per-agent roles

**CodebookAgent.** Three internal roles (Ingestor / Drafter / Critic) convert user-supplied materials — PDF, DOCX, XLSX, CSV, JSON, plain text — into a structured `CodebookDef` with automatic single- vs multi-label inference per dimension. Messy annotator spreadsheets (multiple sheets, continuation rows, `&`-separated multi-label cells) are normalized by a format-aware Ingestor that also produces an analysis-friendly `cleaned_data.json` side-artifact.

**Annotator.** Applies the codebook to new text via dependency-aware pipeline steps. Supports single-label and multi-label dimensions, conditional gating (skip step if prior step emits "No"), and structured output validation.

**ReflectAgent.** Our method. Three LLM roles cooperate over a persistent Rule Library:
- *PatternExtractor* — given a batch of failure cases (predictions that differ from adjudicated gold), distils **generalizable rules** (not exemplars) with per-rule `boundary`, `positive_cues`, `negative_cues`, and `exemplars`.
- *Annotator* — labels items with the current prompt plus active rules.
- *Governor* — scores candidate prompts on a held-out validation set; rolls back any rule update that regresses val accuracy.

Rules are editable, versioned, and exportable — a human-inspectable artifact that accumulates across runs.

**Improve page (UI module).** Default surface is one button — *"Improve from examples"* — that runs ReflectAgent on the user's labeled examples and shows: a live trajectory ("Round 2 of 4 · 3 new guidance notes accepted, 1 rolled back"), a held-out accuracy bar (before → after), and the resulting Rule Library in plain language. No optimizer dropdown, no algorithm names, no "trainset / valset / testset" jargon by default. A single **Researcher mode** toggle exposes the optimizer selector (ReflectAgent · GEPA · MIPROv2 · OPRO), the 3-way split sliders, and the per-round token/cost meters — that surface is what the paper screenshots and what reproducibility uses.

---

## Positioning

### Versus recent EMNLP demo systems (0.75-column block)

**CrowdAgent** (EMNLP'25) manages *who labels* — routing between LLMs, SLMs and human experts with Bayesian quality control; AnnotAgent is orthogonal, assumes a single LLM source, and instead optimizes the schema-acquisition and prompt-repair stages CrowdAgent presumes complete. **EvoAgentX** (EMNLP'25) evolves general agentic workflows; we target one workflow (annotation) with an explicit, inspectable artifact (the Rule Library) and safety-gated rollback. **Offline prompt-repair** (GEPA, MIPROv2, OPRO) returns a single optimized prompt from a fixed trainset, with no persistent artifact; ReflectAgent is online and reflective — per-round failure mining + rule distillation + holdout-gated rollback — and accumulates an editable Rule Library across runs. We include all three as baselines under Researcher mode.

---

## Flagship demo — two-minute video script

One continuous flow, narrated in plain English. Every screenshot doubles as a paper figure.

1. **Drop** the raw annotator spreadsheet (`Codes - Fiona.xlsx`, 1040 rows) onto the page. The system reads it directly — no manual cleanup.
2. The codebook appears: 6 dimensions, each with labels and definitions auto-extracted from the file. A downloadable cleaned-data file is offered as a side artifact.
3. **Load** the agreed-subset gold (169 adjudicated items, pre-shipped, one click).
4. **Annotate** the held-out test set (58 items) — predictions stream in.
5. Click **"Improve from examples."** A live trajectory shows the system reviewing its own mistakes, proposing guidance notes, and silently rolling back any note that hurts accuracy. The accuracy bar moves visibly.
6. Open one **guidance note**: plain-English boundary, positive and negative cues, two example sentences, before/after accuracy on its target dimension.
7. **Export** annotations as JSON or CSV.

What a reviewer sees in two minutes: messy spreadsheet → clean codebook → predictions → measurable improvement → inspectable, editable guidance — all without touching a config file or seeing the words "optimizer," "trainset," or "split." The Researcher-mode toggle (briefly shown at 1:45) reveals the optimizer selector and split sliders for the reproducibility audience.

---

## Evaluation — three small tables + a context panel

References don't count, so we use the recovered space for one extra table and a context panel. All three tables use the same private flagship data; demo papers don't need public reproducibility numbers.

### Table A · per-dimension breakdown — self-disclosure

3-way split: train 15% / val 42% / test 43%. Test items never enter the optimizer.

| Dimension (self-disclosure) | n_agreed | Zero-shot test | + ReflectAgent test | Δ pp |
|---|---|---|---|---|
| Level of disclosure | 118 | (run) | (run) | +X.X |
| Depth of disclosure | 62 | (run) | (run) | +X.X |
| Disclosure as confession | 104 | (run) | (run) | +X.X |

### Table B · model sweep on the flagship dimension

One informative dimension (Level of disclosure) across three vendors so cost/quality is visible. Same split, same gold source as Table A.

| Model | Zero-shot test | + ReflectAgent test | Δ pp | $/100 items |
|---|---|---|---|---|
| gpt-5.4-mini | (run) | (run) | +X.X | $X.XX |
| gpt-5.4 | (run) | (run) | +X.X | $X.XX |
| claude-sonnet-4-5 | (run) | (run) | +X.X | $X.XX |

### Table C · optimizer comparison on the flagship dimension

Same model (gpt-5.4-mini), same dimension and split as Table B, four optimizers — surfaces ReflectAgent's online + Rule-Library trade-off vs offline batch baselines.

| Optimizer | Test acc | Δ pp vs zero-shot | Persistent artifact | Tokens (k) |
|---|---|---|---|---|
| Zero-shot | (run) | — | — | — |
| GEPA | (run) | +X.X | none | X |
| MIPROv2 | (run) | +X.X | none | X |
| OPRO | (run) | +X.X | none | X |
| **ReflectAgent (ours)** | (run) | +X.X | Rule Library | X |

### Context panel (one short paragraph)

End-to-end annotation throughput on 200 items (items / min on gpt-5.4-mini). Raw inter-annotator agreement on the gold source (68.6% on Level, 24.6% on Topic) — motivates why subtle codebooks are hard. Rule Library size after a flagship run (e.g. "7 rules across 3 dimensions, median 2 exemplars each").

Explicit non-goals: full optimizer × codebook matrix, ablations, human-baseline comparisons, significance tests — those belong in a follow-up research paper.

---

## System availability

| Asset | Plan |
|---|---|
| Hosted demo URL | Render.com or Fly.io, one-click reset every 24h |
| Source code | github repo (MIT) |
| Install | `docker compose up` → localhost:8080 |
| Demo video | ≤ 2.5 min, 1080p, narrated |
| Demo credentials | anonymous — no login required |
| Sample data | self-disclosure agreed subset + test_v1/v2, all pre-loaded |
| Screenshots pack | 8–10 PNGs for paper + repo README |

Mitigation for the "live link breaks at review" risk: double-host (cloud deploy + local `docker compose`) and include the fallback URL in the paper.

---

## Implementation status

### Built

| Component | LOC |
|---|---|
| CodebookAgent (format parsers + Ingestor + Drafter + rule-based Critic) | ~1,100 |
| 4-door wizard UI (upload / paste / preset / scratch) | ~450 |
| Annotator (single + multi-label, gating) | ~110 |
| ReflectAgent (PatternExtractor + Governor, online reflective loop) | ~260 |
| GEPA / MIPROv2 / OPRO baselines (DSPy wrappers) | ~300 |
| Prompt Lab UI (runs leaderboard, live trajectory, 3-way split controls) | ~460 |
| Multi-model sweep CLI (`scripts/sweep_models.py`) | ~200 |
| Editorial palette across all pages (Geist Sans + Geist Mono, cream / ink) | — |
| Failure-catching (16-point defense at parse / LLM / transport / DB layers) | — |
| 3-way split with explicit leakage guard (test never enters optimizer) | — |
| Live per-round progress streaming (backend callback → DB → UI polling) | — |

### Remaining for the paper

1. **User-friendly default UI** (~1 day) — rename "Prompt Lab" → "Improve" in nav; replace optimizer dropdown with a single "Improve from examples" button on the Improve page; auto-pick split (15/42/43) under the hood; rename "Rule Library" panel to "Guidance notes" with the technical name as a tooltip; gate optimizer selector + split sliders + token meters behind one **Researcher mode** toggle. Default landing copy stays plain English ("Find and fix annotation mistakes from your examples").
2. Hosted deploy (Render or Fly, ~1 day).
3. Table A · per-dimension eval — self-disclosure 3 dims × zero-shot vs ReflectAgent on `gpt-5.4-mini` (~3 hours LLM, ~$10).
4. Table B · model sweep on the flagship dimension — 3 models (~2 hours LLM, ~$20).
5. Table C · optimizer comparison on the flagship dimension — 4 optimizers on `gpt-5.4-mini` (~2 hours LLM, ~$10).
6. Record demo video (~1 day including retakes) — narrated in plain English; Researcher mode shown briefly.
7. Screenshot pack (~0.5 day) — capture both default and Researcher-mode views.
8. Paper draft (~4 days).
9. Internal review + polish (~2 days).

Total remaining: ~11 working days.

---

## Demo-track risk register

1. **Hosted URL dies at review time** — double-host (cloud + local docker compose) and include the fallback URL in the paper; check weekly.
2. **Demo video is weak or confusing** — storyboard the seven steps above before recording; add narration and captioned callouts.
3. **Paper reads like underpowered research** — keep eval to two tables and lead with system, not method.
4. **Too little concrete system detail** — screenshots + architecture figure occupy ~1.5 pages; don't shrink them.
5. **Overclaiming ReflectAgent novelty** — frame as "online reflective prompt repair with holdout-gated rollback," a named technique, not a universal improvement claim.
6. **Reviewer can't tell who would use it tomorrow** — Section 1 opens with a concrete persona: an HCI researcher with ~1000 AI-companion dialogues and a half-written coding manual.
7. **UI looks like an ML-researcher tool, not a research instrument** — default surface hides optimizer names, split sliders, and token counters; one "Improve from examples" button does the right thing; Researcher mode is a single toggle for reviewers and reproducibility users.

---

## References (systems + techniques we position against)

- CrowdAgent: Multi-Agent Managed Multi-Source Annotation System. EMNLP 2025 Demo. https://aclanthology.org/2025.emnlp-demos.72/
- EvoAgentX: An Automated Framework for Evolving Agentic Workflows. EMNLP 2025 Demo. https://aclanthology.org/2025.emnlp-demos.47/
- MASA: LLM-Driven Multi-Agent Systems for Autoformalization. EMNLP 2025 Demo. https://aclanthology.org/2025.emnlp-demos.44/
- MCPEval: Automatic MCP-based Deep Evaluation for AI Agent Models. EMNLP 2025 Demo. https://arxiv.org/abs/2507.12806
- Agrawal, L. et al. (2025). *GEPA: Reflective Prompt Evolution.*
- Opsahl-Ong, K. et al. (2024). *MIPROv2: Multi-Prompt Instruction Optimization.* DSPy.
- Yang, C. et al. (2024). *Large Language Models as Optimizers (OPRO).*
