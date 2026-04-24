# AnnotAgent — EMNLP 2026 Demo Paper Plan

**Target**: EMNLP 2026 System Demonstrations (6-page limit, ≤2.5 min video, live demo, public repo)
**Date**: 2026-04-24
**Status**: system working end-to-end · remaining work is an open-data eval run, video, screenshots, and the paper draft

---

## Pitch

> **A multi-agent annotation workbench with rollback-safe rule induction.**

Extended: an end-to-end, runnable annotation system for multi-dimensional codebooks with four cooperating LLM agents — ingest messy annotator materials, annotate reliably, inspect failures, improve prompts online, and deploy revisions safely.

---

## Scope

**System applicability:** general single-label and multi-label classification over text with a codebook — any task where a human annotator would read a sentence (or short passage) and assign categorical labels along one or more dimensions.

**Flagship showcase:** AI-companion conversation analysis. User-side self-disclosure (5 dimensions, single-label) and AI-side behavior (3 themes, multi-label), annotated on adjudicated dialogues — chosen because it exposes the hardest case: subtle, multi-dimensional, low-IAA codebooks where adjudication is expensive.

**Public reproducibility:** bundled GoEmotions (Demszky et al., 2020; Apache 2.0) end-to-end example that a reviewer can run in ~20 minutes.

---

## Paper shape — 6-page budget

| Section | Pages | Contents |
|---|---|---|
| 1. Introduction | 1.0 | Problem + pitch + demo teaser screenshot + contributions |
| 2. System architecture | 1.5 | 4-agent figure · per-agent paragraph · stack summary |
| 3. Workflow & UI (flagship demo) | 1.5 | End-to-end walkthrough with 4–5 screenshots: messy XLSX → annotations |
| 4. Evaluation | 0.75 | Table A (flagship, private) + Table B (GoEmotions × 3 models, public) |
| 5. Related work | 0.5 | One paragraph each vs CrowdAgent · EvoAgentX · MASA · MCPEval |
| 6. Availability & limitations | 0.5 | URL · repo · install · known limits |
| References | 0.25 | |
| **Total** | **6.0** | |

Screenshots + diagrams together eat ~1.5 pages. Prose is tight.

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
           │  Prompt Optimization Workbench (UI module)                  │
           │  plug-in interface: ReflectAgent · GEPA · MIPROv2 · OPRO   │
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

**Prompt Optimization Workbench.** Plug-in interface exposing ReflectAgent alongside three post-2023 SOTA baselines (GEPA, MIPROv2, OPRO — all via DSPy). Lets practitioners A/B any optimizer on their own codebook and dimension.

---

## Positioning

### Versus recent EMNLP demo systems

- **CrowdAgent** (EMNLP'25) manages *who labels* — it routes tasks between LLMs, SLMs, and human experts with Bayesian quality control. AnnotAgent is orthogonal: we assume a single LLM source and instead optimize the *schema acquisition* (CodebookAgent) and *prompt repair* (ReflectAgent) stages that CrowdAgent presumes complete. The two systems compose.
- **EvoAgentX** (EMNLP'25) evolves general agentic workflows. We target a specific workflow (annotation) with an explicit, inspectable artifact (the Rule Library) and safety-gated rollback.
- **MASA** (EMNLP'25) is autoformalization (NL → Lean4). We target conversational annotation codebooks; the method families don't overlap.
- **MCPEval** (EMNLP'25) evaluates agent models. We build annotations with agents and evaluate the resulting labels.

### Versus prompt-optimization baselines (batch vs online)

- **GEPA · MIPROv2 · OPRO** are *offline batch* prompt optimizers — trained on a fixed trainset, return one optimized prompt, no persistent artifact.
- **ReflectAgent** is *online reflective* — per-round failure mining + rule distillation + holdout-gated rollback, producing an editable Rule Library that accumulates across runs.

---

## Flagship demo — two-minute video script

One continuous flow; every screenshot doubles as a paper figure.

1. **Drop** `Codes - Fiona.xlsx` (1040-row raw annotator sheet) into CodebookAgent.
2. CodebookAgent auto-detects annotator format, forward-fills, canonicalizes, produces (a) a 6-dimensional codebook with correct mode per dim and (b) a downloadable `cleaned_data.json` analysis artifact.
3. **Load** the agreed-subset gold (169 adjudicated items, pre-shipped).
4. **Launch Annotator** on the held-out test set (v1, 58 items).
5. **Trigger ReflectAgent.** The trajectory streams live: rules are proposed each round, the Governor evaluates on held-out val, rules are accepted or rolled back. The Rule Library panel fills with human-readable rules.
6. **Inspect a rule**: boundary statement, positive and negative cues, exemplars, before/after F1 on the dimension it targets.
7. **Export** annotations as JSON or CSV.

What a reviewer sees in two minutes: messy input → clean codebook → actual predictions → measurable improvement → inspectable, editable artifact.

---

## Evaluation — two tables, two stories

One flagship table (per-dim, private data) and one reproducibility + model-sweep table (one dim, public data, multiple models).

### Table A · flagship — self-disclosure (private, AI-companion)

3-way split: train 15% / val 42% / test 43%. Test items are never seen by the optimizer.

| Dimension (self-disclosure) | n_agreed | Zero-shot test acc | + ReflectAgent test acc | Δ pp |
|---|---|---|---|---|
| Level of disclosure | 118 | (run) | (run) | +X.X |
| Depth of disclosure | 62 | (run) | (run) | +X.X |
| Disclosure as confession | 104 | (run) | (run) | +X.X |

### Table B · reproducibility + model sweep — GoEmotions (public)

Same 3-way split on the bundled 30-item sample (`data/cleaned/goemotions_sample.json`). One informative emotion label swept across three models so cost/quality is visible; reviewers can rerun with real GoEmotions via the bundled fetch helper.

| Model | Zero-shot test acc | + ReflectAgent test acc | Δ pp | Cost per 100 items (USD) |
|---|---|---|---|---|
| gpt-5.4-mini | (run) | (run) | +X.X | $X.XX |
| gpt-5.4 | (run) | (run) | +X.X | $X.XX |
| claude-sonnet-4-5 | (run) | (run) | +X.X | $X.XX |

Produced by `backend/scripts/sweep_models.py` and documented for reviewers in `examples/goemotions/README.md` as a 20-minute end-to-end run.

### Side numbers (one sentence each)

- End-to-end annotation throughput on 200 items (items / min).
- Inter-annotator agreement on the self-disclosure gold source (68.6% raw on Level, 24.6% on Topic — motivates why subtle codebooks are hard).
- Rule Library size after optimization (e.g. "7 rules across 3 dimensions, median 2 exemplars each").

Explicit non-goals: full optimizer × codebook matrix, extensive ablations, human-baseline comparisons, significance tests. Those belong in a follow-up research paper.

---

## System availability

| Asset | Plan |
|---|---|
| Hosted demo URL | Render.com or Fly.io, one-click reset every 24h |
| Source code | github repo (MIT) |
| Install | `docker compose up` → localhost:8080 |
| Demo video | ≤ 2.5 min, 1080p, narrated |
| Demo credentials | anonymous — no login required |
| Sample data | self-disclosure agreed subset + test_v1/v2 + GoEmotions reproducibility sample, all pre-loaded |
| Public reproducibility example | `examples/goemotions/` with README, UI path, CLI sweep path, and `fetch_real.py` to swap in the full dataset |
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
| GoEmotions preset + 30-item reproducibility sample + seed registration | — |
| Editorial palette across all pages (Geist Sans + Geist Mono, cream / ink) | — |
| Failure-catching (16-point defense at parse / LLM / transport / DB layers) | — |
| 3-way split with explicit leakage guard (test never enters optimizer) | — |
| Live per-round progress streaming (backend callback → DB → UI polling) | — |

### Remaining for the paper

1. Hosted deploy (Render or Fly, ~1 day).
2. Flagship eval — self-disclosure 3 dims × zero-shot vs ReflectAgent on `gpt-5.4-mini` (~3 hours LLM, ~$10).
3. GoEmotions reproducibility eval — one target label × 3 models (~3 hours LLM, ~$15); confirm the bundled example runs in the 20-minute target.
4. Model sweep on the flagship dimension (~2 hours LLM, ~$20).
5. Record demo video (~1 day including retakes).
6. Screenshot pack (~0.5 day).
7. Paper draft (~4 days).
8. Internal review + polish (~2 days).

Total remaining: ~10–11 working days.

---

## Demo-track risk register

1. **Hosted URL dies at review time** — double-host (cloud + local docker compose) and include the fallback URL in the paper; check weekly.
2. **Demo video is weak or confusing** — storyboard the seven steps above before recording; add narration and captioned callouts.
3. **Paper reads like underpowered research** — keep eval to two tables and lead with system, not method.
4. **Too little concrete system detail** — screenshots + architecture figure occupy ~1.5 pages; don't shrink them.
5. **Overclaiming ReflectAgent novelty** — frame as "online reflective prompt repair with holdout-gated rollback," a named technique, not a universal improvement claim.
6. **Reviewer can't tell who would use it tomorrow** — Section 1 opens with a concrete persona: an HCI researcher with ~1000 AI-companion dialogues and a half-written coding manual.

---

## References (systems + techniques we position against)

- Demszky, D. et al. (2020). *GoEmotions: A Dataset of Fine-Grained Emotions.* ACL 2020.
- CrowdAgent: Multi-Agent Managed Multi-Source Annotation System. EMNLP 2025 Demo. https://aclanthology.org/2025.emnlp-demos.72/
- EvoAgentX: An Automated Framework for Evolving Agentic Workflows. EMNLP 2025 Demo. https://aclanthology.org/2025.emnlp-demos.47/
- MASA: LLM-Driven Multi-Agent Systems for Autoformalization. EMNLP 2025 Demo. https://aclanthology.org/2025.emnlp-demos.44/
- MCPEval: Automatic MCP-based Deep Evaluation for AI Agent Models. EMNLP 2025 Demo. https://arxiv.org/abs/2507.12806
- Agrawal, L. et al. (2025). *GEPA: Reflective Prompt Evolution.*
- Opsahl-Ong, K. et al. (2024). *MIPROv2: Multi-Prompt Instruction Optimization.* DSPy.
- Yang, C. et al. (2024). *Large Language Models as Optimizers (OPRO).*
