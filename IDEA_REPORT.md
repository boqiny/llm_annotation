# AnnotAgent — EMNLP 2026 Demo Paper Plan

**Target**: EMNLP 2026 System Demonstrations (6-page limit, ≤2.5 min video, live demo, public repo)
**Status**: System working end-to-end. Frontend + backend integrated, optimizer + memory loop closed, per-dim auto-prompt path live. Remaining: eval runs, video, screenshots, paper draft. See `PROGRESS.md` for the live engineering checklist.

---

## Pitch

> **A multi-agent annotation workbench that learns from its own mistakes — and remembers across sessions.**

Extended: an end-to-end, runnable system that turns a researcher's messy codebook materials into a working LLM annotator, drafts a per-dimension prompt automatically, then quietly improves itself by reviewing its own errors against labeled examples. The improvements **accumulate across sessions** as a versioned, editable rule library.

**Audience the UI assumes:** an HCI / qualitative / social-science researcher with a coding manual and ~hundreds of items. Not an ML practitioner. The default surface uses plain English ("Improve from examples", "current prompts"); algorithmic names (ReflectAgent, GEPA, MIPROv2, OPRO) live behind a single **Researcher mode** toggle.

---

## Scope

**System applicability:** general single-label and multi-label classification over text with a codebook — any task where a human annotator would read a sentence (or short passage) and assign categorical labels along one or more dimensions.

**Flagship showcase:** AI-companion conversation analysis. User-side self-disclosure (5 dimensions, single-label) and AI-side behavior (3 themes, multi-label), annotated on adjudicated dialogues — chosen because it exposes the hardest case: subtle, multi-dimensional, low-IAA codebooks where adjudication is expensive.

---

## Paper shape — 6-page budget (references uncounted)

| Section | Pages | Contents |
|---|---|---|
| 1. Introduction | 1.0 | Problem + pitch + landing-page workflow figure + contributions |
| 2. System architecture | 1.5 | 5-stage figure · per-agent paragraph · stack summary |
| 3. Workflow & UI (flagship demo) | 1.5 | End-to-end walkthrough with 4–5 screenshots: messy XLSX → auto-prompts → improved → annotated data |
| 4. Evaluation | 1.125 | Table A (per-dim) · Table B (model sweep) · Table C (optimizer comparison) · throughput panel |
| 5. Related work | 0.375 | CrowdAgent · EvoAgentX · offline prompt-repair (GEPA/MIPROv2/OPRO) |
| 6. Availability & limitations | 0.5 | URL · repo · install · known limits |
| References | (free) | uncounted |
| **Total** | **6.0** | |

---

## System — five cooperating stages

```
              ┌───────────────────────────────────────────────────────┐
  messy ─────▶│  1. CodebookAgent                                      │
  input       │  Ingestor → Drafter → Critic                          │
              │  PDF/DOCX/XLSX/CSV/JSON/TXT, auto mode-inference       │
              │  Editable draft preview before commit                 │
              └───────────────────────────────────────────────────────┘
                                    │  CodebookDef (validated)
                                    ▼
              ┌───────────────────────────────────────────────────────┐
              │  2. AutoPromptGenerator                                │
              │  LLM drafts a starting annotation prompt PER DIMENSION │
              │  in parallel (asyncio.gather, return_exceptions)       │
              │  Versioned on disk: workspace/.../prompts/<dim>/auto_v00N
              └───────────────────────────────────────────────────────┘
                                    │  one prompt per dim
                                    ▼
              ┌───────────────────────────────────────────────────────┐
              │  3. Annotator                                          │
              │  Pipeline runner · per-dim or all-together mode        │
              │  Async with concurrency, pause/cancel/resume           │
              │  WebSocket progress to the UI                          │
              └───────────────────────────────────────────────────────┘
                                    │  predictions + per-class metrics
                                    ▼
              ┌───────────────────────────────────────────────────────┐
              │  4. ReflectAgent (the standout module)                 │
              │  Online, reflective (cf. batch GEPA · MIPRO · OPRO)    │
              │  PatternExtractor mines failure batch → rules          │
              │  Governor evaluates on held-out val; rolls back regress│
              │  Held-out test scored ONCE at end (leakage guard)      │
              └───────────────────────────────────────────────────────┘
                                    │  rule library + optimized prompt
                                    ▼
              ┌───────────────────────────────────────────────────────┐
              │  5. Memory (cross-session)                             │
              │  ReflectMemoryVersion table, versioned per (project,   │
              │  dimension). Each run seeds from the latest version.   │
              │  Editable, exportable, accumulates across sessions.    │
              └───────────────────────────────────────────────────────┘
```

### Per-agent roles

**CodebookAgent.** Three internal roles (Ingestor / Drafter / Critic) convert user-supplied materials — PDF, DOCX, XLSX, CSV, JSON, plain text — into a structured `CodebookDef` with automatic single- vs multi-label inference per dimension. Messy annotator spreadsheets (multiple sheets, continuation rows, `&`-separated multi-label cells) are normalized by a format-aware Ingestor that also produces an analysis-friendly `cleaned_data.json` side-artifact. **Drafts are editable** in the wizard before commit (codebook name, dimension instructions, label names + definitions, add/remove labels and dimensions).

**AutoPromptGenerator.** New stage from the merged `annotation_demo` PR. Given a `CodebookDef`, the LLM writes a fit-for-purpose annotation prompt for **each dimension in parallel**, via a Jinja meta-prompt (`auto_prompt_generator.jinja`). One prompt per dimension matches the per-dim pipeline architecture and lets each be optimized independently. The deterministic Jinja-from-codebook generator (`prompt_generator.jinja`) remains as the gallery/preset path; this LLM path is the default for user-uploaded codebooks. Each generation is versioned (`auto_v001`, `v002`, …) on the filesystem under `workspace/project_<id>/prompts/<dim>/`.

**Annotator.** Applies the codebook to new text via dependency-aware pipeline steps. The Decomposer offers two modes:
- *Per-dimension* (default): one step per dim, no cross-dimensional interference.
- *All-together*: single step covering every dim, one LLM call per item — cheaper but dims can confuse each other.
The user toggles modes on the **Annotate** page; clicking the toggle re-decomposes server-side and the strip redraws.

**ReflectAgent.** Our method. Three LLM roles cooperate over a persistent Rule Library:
- *PatternExtractor* — given a batch of failure cases, distils **generalizable rules** (not exemplars) with per-rule `id`, `boundary`, `target_labels`, `positive_cues`, `negative_cues`, `rule`. Forbidden from quoting failure sentences verbatim.
- *Annotator* — labels items with the current prompt plus active rules.
- *Governor* — scores candidate prompts on held-out validation; rolls back any rule update that regresses val accuracy by more than `rollback_epsilon`.

Rules are editable, versioned, and exportable. Held-out test is evaluated **exactly once** at the end on the final prompt (asserts in `_execute_run` enforce disjoint train/val/test by object identity).

**Memory (new from PR).** Cross-session accumulation. After each successful reflect_agent run, the final rule library is written as a new `ReflectMemoryVersion` row, versioned per `(project, dimension)`. The next run on the same dim **seeds** from the latest version, so improvements compound across sessions instead of restarting each time. The Memory section in the Improve page renders the version history with rules, source run id, dates, and `+new` deltas.

---

## Positioning

### Versus recent EMNLP demo systems

**CrowdAgent** (EMNLP'25) manages *who labels* — routing between LLMs, SLMs, and human experts with Bayesian quality control. AnnotAgent is orthogonal: a single LLM source, with an explicit prompt-quality and rule-distillation loop that CrowdAgent presumes complete. **EvoAgentX** (EMNLP'25) evolves general agentic workflows; we target one workflow (annotation) with an explicit, inspectable artifact (the Rule Library + cross-session Memory) and safety-gated rollback.

### Versus offline prompt-repair (GEPA / MIPROv2 / OPRO)

Returns a single optimized prompt from a fixed trainset, no persistent artifact. ReflectAgent is **online + reflective + cross-session**: per-round failure mining, rule distillation, holdout-gated rollback, and cumulative memory across runs. We include all three as baselines under Researcher mode.

---

## Flagship demo — two-minute video script

One continuous flow, narrated in plain English. Every screenshot doubles as a paper figure.

1. **Drop** the raw annotator spreadsheet (`Codes - Fiona.xlsx`) onto the Setup page. The wizard reads it, ingests + drafts a codebook, shows the structured editable preview.
2. The codebook appears: 6 dimensions, each with labels and definitions. The user can tweak names/definitions inline, then **Accept**.
3. Click **Generate pipeline** → land on the **Improve** page.
4. The system has already **auto-drafted a prompt for each of the 6 dimensions in parallel** — they appear as a stack of cards under "Current prompts."
5. Click **"Improve from examples."** Live trajectory chart shows val accuracy + macro F1 climbing round by round. Rollbacks are visible as small dips that get undone.
6. Open the resulting **Memory** section: the rule library is now versioned per dimension; each rule has a plain-English boundary + positive/negative cues.
7. Run it again on a different dim — the trajectory shows `baseline_seeded` at round 0 (rules carry over).
8. Switch to the **Annotate** page → click on "all together" or stay on "per dimension" → **Run annotation** on the unseen test set.
9. Results page: per-class precision/recall/F1, confusion matrix, exportable CSV/JSON.

What a reviewer sees in two minutes: messy spreadsheet → editable codebook → auto-drafted prompts → measurable improvement → inspectable rules → annotated unseen data — without touching a config file or seeing the words "optimizer" or "split."

---

## Evaluation — three small tables + a context panel

All three tables use the flagship private data; demo papers don't need public-reproducibility numbers.

### Table A · per-dimension breakdown — self-disclosure

3-way split: train 15% / val 42% / test 43%. Test items never enter the optimizer.

| Dimension (self-disclosure) | n_labeled | Zero-shot test | + ReflectAgent test | Δ pp |
|---|---|---|---|---|
| Level of disclosure | 118 | (run) | (run) | +X.X |
| Depth of disclosure | 62 | (run) | (run) | +X.X |
| Disclosure as confession | 104 | (run) | (run) | +X.X |
| Intimacy of self-disclosure | 24 | (run) | (run) | +X.X |
| Temporality | 12 | n/a (< 15-item gate) | — | — |

### Table B · model sweep on the flagship dimension

| Model | Zero-shot test | + ReflectAgent test | Δ pp | $/100 items |
|---|---|---|---|---|
| gpt-5.4-mini | (run) | (run) | +X.X | $X.XX |
| gpt-5.4 | (run) | (run) | +X.X | $X.XX |
| claude-sonnet-4-5 | (run) | (run) | +X.X | $X.XX |

### Table C · optimizer comparison on the flagship dimension

| Optimizer | Test acc | Δ pp vs zero-shot | Persistent artifact | Tokens (k) |
|---|---|---|---|---|
| Zero-shot | (run) | — | — | — |
| GEPA | (run) | +X.X | none | X |
| MIPROv2 | (run) | +X.X | none | X |
| OPRO | (run) | +X.X | none | X |
| **ReflectAgent (ours)** | (run) | +X.X | Rule Library + cross-session Memory | X |

### Context panel

End-to-end annotation throughput (items / min, gpt-5.4-mini). Raw IAA on the gold source (68.6% on Level, 24.6% on Topic — motivates why subtle codebooks are hard). Memory growth across sessions: e.g., "Dim X reached saturation after run 3 (no new rules accepted), final library: N rules."

Explicit non-goals: full optimizer × codebook matrix, ablations, human-baseline comparisons, significance tests — those belong in a follow-up research paper.

---

## System availability

| Asset | Plan |
|---|---|
| Hosted demo URL | Render.com or Fly.io, one-click reset every 24h |
| Source code | github repo (MIT) |
| Install | `cd annotagent && docker compose up` → localhost:8080 |
| Demo video | ≤ 2.5 min, 1080p, narrated |
| Demo credentials | anonymous — no login required |
| Sample data | self-disclosure agreed + Fiona + Chang + test_v1/v2, all bundled in `annotagent/assets/data/` |
| Screenshots pack | 8–10 PNGs for paper + repo README |

Mitigation for the "live link breaks at review" risk: double-host (cloud deploy + local `docker compose`) and include the fallback URL in the paper.

---

## Demo-track risk register

1. **Hosted URL dies at review time** — double-host (cloud + local docker compose) and include the fallback URL in the paper; check weekly.
2. **Demo video is weak or confusing** — storyboard the nine steps above before recording; add narration and captioned callouts.
3. **Paper reads like underpowered research** — keep eval to three small tables and lead with system, not method.
4. **Too little concrete system detail** — screenshots + architecture figure occupy ~1.5 pages; don't shrink them.
5. **Overclaiming ReflectAgent novelty** — frame as "online reflective prompt repair with cross-session memory and holdout-gated rollback," a named technique, not a universal improvement claim.
6. **Reviewer can't tell who would use it tomorrow** — Section 1 opens with a concrete persona: an HCI researcher with ~1000 AI-companion dialogues and a half-written coding manual.
7. **UI looks like an ML-researcher tool** — default surface hides optimizer names, split sliders, and token counters; one "Improve from examples" button does the right thing; Researcher mode is a single toggle.

---

## References (systems + techniques we position against)

- CrowdAgent: Multi-Agent Managed Multi-Source Annotation System. EMNLP 2025 Demo. https://aclanthology.org/2025.emnlp-demos.72/
- EvoAgentX: An Automated Framework for Evolving Agentic Workflows. EMNLP 2025 Demo. https://aclanthology.org/2025.emnlp-demos.47/
- MASA: LLM-Driven Multi-Agent Systems for Autoformalization. EMNLP 2025 Demo. https://aclanthology.org/2025.emnlp-demos.44/
- MCPEval: Automatic MCP-based Deep Evaluation for AI Agent Models. EMNLP 2025 Demo. https://arxiv.org/abs/2507.12806
- Agrawal, L. et al. (2025). *GEPA: Reflective Prompt Evolution.*
- Opsahl-Ong, K. et al. (2024). *MIPROv2: Multi-Prompt Instruction Optimization.* DSPy.
- Yang, C. et al. (2024). *Large Language Models as Optimizers (OPRO).*
