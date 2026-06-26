# CLAIR

## What this is

CLAIR is an open-source, codebook-driven system for LLM-assisted text
annotation. A small research team feeds it a codebook and raw text; the system
ingests the codebook into a structured schema, drafts one annotation prompt per
dimension, labels items with bounded-concurrency batch runs, and closes a
failure-driven improvement loop that refines each prompt against the team's own
labeled examples. The whole pipeline runs behind a React UI with a FastAPI
backend, and every artifact it produces (the parsed codebook, each prompt
version, the learned rules, the per-class metrics) is inspectable and
exportable.

This is a **system demonstration**, framed for the EMNLP System Demonstrations
track. The paper documents a working, deployable system rather than a controlled
study. The evaluation, required by the track, is deliberately compact: it shows
that the improvement loop does the one thing the system claims, on a hard
subjective codebook, with honest held-out numbers.

## The claim

Most LLM-assisted labeling tools pre-fill a label with a fixed prompt and ask a
human to accept or correct it. The prompt is written once, against an assumed
notion of the "right" label, and it does not move as the team's own decisions
accumulate. On subjective codebooks this is the wrong default, because there is
often no single right label: two trained coders applying the same codebook to
the same text agree only part of the time, and each one is internally
consistent in a different way.

CLAIR's contribution is a labeling pipeline whose improvement loop
**calibrates the annotator to a chosen target rater**. Point the loop at coder
A's labels and it learns to label the way A labels; point it at coder B and it
learns B. The system does not force the two coders into one consensus before it
can help. It treats each coder's labels as a legitimate target and raises
agreement with whichever target the team selects. For teams that do want a
single resolved label, the multi-annotator review UI is still there as a
feature; it is no longer the headline.

The rest of this document describes the system, then reports a per-target
alignment evaluation on a four-dimension self-disclosure codebook with two
independent annotators.

![CLAIR pipeline: messy inputs flow through CodebookAgent, AutoPromptGenerator, the labeling stage, and the ReflectAgent improvement loop with cross-session Memory. The labeling stage exposes three entry paths: cold-start interactive labeling, multi-annotator review, and target-aligned optimization.](assets/workflow_v1.png)

*(Figure to be refreshed for the system-demo framing: the current asset still
labels the old adjudication contribution.)*

---

## Why codebook annotation needs this

A trained coder reading a multi-turn dialogue and applying a six-dimension
codebook spends thirty to ninety seconds per item. At a hundred thousand items
per release cycle, the budget is person-months. The data-centric AI literature
(Ng, 2021; Northcutt et al., 2021) frames this as a central constraint: model
quality is bounded by label quality, and label quality is bounded by human
time. A tool that pre-fills labels and lets a human correct them removes some of
that time, and several open tools do exactly this.

Two problems remain that a static pre-fill tool does not touch.

The first is drift. Conversational-AI products ship new model versions, user
populations turn over, and codebooks evolve as researchers discover new failure
modes. Each shift invalidates a slice of the existing gold set. A pre-fill
prompt written on the old distribution does not update as the human's
accept-and-edit signal accumulates, so the tool's assistance decays exactly when
re-labeling cost is highest.

The second is subjectivity. On dimensions like intimacy, depth, or emotional
valence, trained coders agree only 60 to 70 percent of the time. Inter-annotator
agreement metrics (Cohen's kappa for two raters, Fleiss' kappa for more,
Krippendorff's alpha when coverage is incomplete) quantify the gap, but they do
not tell you whose label to imitate. The standard fix is to adjudicate
disagreements into one consensus label, usually by a senior coder making silent
calls. That throws away a real signal: a growing line of work argues that
disagreement reflects genuine ambiguity rather than error, and that
annotator-specific targets carry information a forced consensus destroys.

CLAIR takes the second view seriously inside a usable tool. It does not
assume a single ground truth exists. It lets the team pick a target rater and
calibrates the LLM annotator to that target. Where a team genuinely needs one
resolved label, the disagreement-review UI supports that workflow too, but the
system's default stance is that the target is a choice, not a given.

LLM-as-judge offers a partial precedent. The standard recipe (Zheng et al.,
2023; Shankar et al., 2024) writes a judge prompt, splits labeled data into
train, dev, and test, refines the prompt, and measures agreement with human
labels. CLAIR borrows the leakage-guarded split and the iterate-against-
held-out-data discipline, and applies them to production annotation with an
interpretable rule library and a target rater rather than an assumed gold
standard.

---

## What CLAIR does

The system is four LLM-backed agents and two shared persistent artifacts. The
agents are `CodebookAgent`, which ingests codebook materials into a structured
schema; `AutoPromptGenerator`, which drafts one annotation prompt per dimension
in parallel; `Annotator`, which applies a prompt to items; and `ReflectAgent`,
which mines interpretable rules from labeled items and updates the Annotator's
prompt under a held-out validation check. The shared artifacts are the **Rule
Library**, a versioned set of rules with positive and negative cues per label,
and the **Memory**, a per-dimension log of rule-library versions that lets the
next session seed from the previous one.

```
              ┌───────────────────────────────────────────────────────┐
  messy ─────▶│  1. CodebookAgent                                     │
  input       │  Ingestor → Drafter → Critic                          │
              │  PDF/DOCX/XLSX/CSV/JSON/TXT, auto mode-inference      │
              │  Editable draft preview before commit                 │
              └───────────────────────────────────────────────────────┘
                                    │  CodebookDef (validated)
                                    ▼
              ┌───────────────────────────────────────────────────────┐
              │  2. AutoPromptGenerator                                │
              │  LLM drafts a starting prompt PER DIMENSION in         │
              │  parallel (asyncio.gather). Versioned on disk.         │
              └───────────────────────────────────────────────────────┘
                                    │  one prompt per dim
                                    ▼
              ┌───────────────────────────────────────────────────────┐
              │  3. Annotator                                          │
              │  Batch: pipeline runner, per-dim or all-together,      │
              │     async, pause/cancel/resume, WebSocket progress.    │
              │  Interactive: per-item pre-fill for cold-start label.  │
              └───────────────────────────────────────────────────────┘
                                    │  predictions + per-class metrics
                                    ▼
              ┌───────────────────────────────────────────────────────┐
              │  4. ReflectAgent (improvement loop)                    │
              │  PatternExtractor: abstract rules from failures        │
              │  Annotator role: label with current prompt + rules     │
              │  Governor: held-out-gated rollback                     │
              │  Test scored ONCE at the end (leakage guard)           │
              └───────────────────────────────────────────────────────┘
                                    │  rule library + optimized prompt
                                    ▼
              ┌───────────────────────────────────────────────────────┐
              │  5. Memory (cross-session)                             │
              │  Versioned per (project, dimension). Each run seeds     │
              │  from the latest version. Editable, exportable.        │
              └───────────────────────────────────────────────────────┘
```

`CodebookAgent` does three jobs in one agent. The Ingestor parses the upload
(PDF, DOCX, XLSX, CSV, JSON, or plain text) and normalizes messy spreadsheets:
multiple sheets, continuation rows, `&`-separated multi-label cells. The Drafter
produces a structured `CodebookDef` with single-label or multi-label inferred
per dimension. The Critic flags ambiguities. The user edits the draft in a
wizard before committing, and the wizard emits an analysis-friendly
`cleaned_data.json` side-artifact for downstream tools.

`AutoPromptGenerator` uses a Jinja meta-prompt to write one annotation prompt
per dimension in parallel. Each prompt is versioned on disk under
`workspace/project_<id>/prompts/<dim>/auto_v00N`, so the user can roll back or
compare. A deterministic generator stays in place for the gallery and preset
codebooks where reproducibility matters more than adaptiveness.

`Annotator` runs in two modes. Batch mode handles full datasets with bounded
concurrency, WebSocket progress, and pause, cancel, or resume; the per-dimension
sub-mode runs one step per dimension to avoid cross-dimensional interference,
while the all-together sub-mode covers every dimension in one call per item and
is cheaper but noisier. Interactive mode handles one item at a time and drives
the cold-start labeling page.

`ReflectAgent` is the improvement loop. The PatternExtractor distills a batch of
mislabeled items into interpretable rules (positive cues, negative cues, target
labels, a plain-English boundary); it is forbidden from quoting failure
sentences verbatim and must abstract the boundary it sees. The Annotator labels
the validation slice with the candidate rule set. The Governor compares
validation accuracy before and after and rolls back any update that regresses by
more than `rollback_epsilon`. A held-out test slice is scored exactly once at
the end, and the train, validation, and test partitions are asserted disjoint by
object identity before any round starts.

`Memory` writes a new `ReflectMemoryVersion` row after each successful run,
indexed by `(project, dimension)`. The next run on the same dimension reads the
latest version's rules as its starting library; the trajectory chart shows
`baseline_seeded` at round zero. Memory is editable in the UI, and the audit log
persists. This is a convenience that lets a dimension's rules compound across
sessions, not a claim about open-ended self-improvement.

---

## Three user flows

Different projects walk in at different stages of labeling maturity. The same
four agents serve all three flows; what changes is which agents activate and
what artifact they write.

**Flow A, cold start.** The user has a codebook (or wants help drafting one) and
raw data, and wants to label item by item with LLM assistance. CodebookAgent
ingests the codebook, AutoPromptGenerator drafts a starting prompt per
dimension, and the Annotator runs interactively. Each accepted or edited verdict
becomes a labeled row. Once a dimension accumulates roughly twenty accepted
items, a background ReflectAgent run mines rules from the accepted set and
updates the pre-fill prompt for the rest of the session. A badge tells the user
the pre-fill improved and which revision is active.

**Flow B, multiple annotators.** The user has labels from two or more coders on
the same items. CodebookAgent ingests the codebook; the dataset wizard joins the
annotator files on item index; the system computes IAA per dimension
(Krippendorff's alpha by default, Cohen's kappa for the two-rater case, Fleiss'
kappa when three or more rate every item). The user can inspect where coders
diverge and, per dimension, pick a **target rater** to calibrate toward, or, for
a team that needs one resolved label, work the disputed items in a review queue
where every annotator's label sits next to the LLM verdict and its cited rules.
The target-rater path feeds Flow C; the review path produces a single resolved
corpus. Both are supported; the system does not force the choice.

**Flow C, target-aligned optimization.** The user has labeled data for a chosen
target (a single coder's labels, an adjudicated corpus, or accumulated
cold-start labels). AutoPromptGenerator drafts the starting prompts; ReflectAgent
runs failure-driven optimization with held-out validation against that target;
Memory writes a new version. Subsequent runs on the same dimension seed from the
latest version and the rules compound.

The flows compose. Flow A's accepted labels become a target for Flow C the
moment the user switches to batch optimization. Flow B's per-rater split hands
Flow C a target without any forced consensus. This composition is exactly what
the evaluation exercises: take each annotator as a separate target and run Flow C
against that target alone.

---

## The improvement loop in depth

Existing prompt optimizers (GEPA, MIPROv2, OPRO) return a single optimized
prompt from a fixed training set and keep no persistent artifact. ReflectAgent
does the analogous job inside the system but produces an inspectable rule library
and a Memory log that carries forward across sessions on the same dimension. The
loop is the engine behind the per-target alignment the system claims.

Each round runs a small loop. The PatternExtractor takes failure cases from the
current prompt's predictions on the training slice and distills them into
candidate rules. The Annotator labels the validation slice with the candidate
rule set. The Governor compares validation accuracy before and after; if the
candidate regresses by more than `rollback_epsilon`, the round rolls back. The
trajectory chart renders rollbacks as small dips that get undone.

The held-out test slice is scored exactly once, at the end, on the final rule
library. The asserts in `api/optimizers.py::_execute_run` verify the three sets
are disjoint by object identity before any round starts. Validation and test
items never enter the prompt. This is the standard discipline from LLM-as-judge
prompt development, and it is what makes the reported alignment numbers honest.

### The rule library

Each rule is a structured object:

```json
{
  "id": "level-2025-05-14-001",
  "dimension": "Level",
  "boundary": "Generic agreement / non-personal reaction vs. minimal personal content",
  "target_labels": ["No", "Low"],
  "positive_cues": [
    "names a personal preference (\"I like X\")",
    "narrates a first-person event, however brief",
    "expresses an opinion grounded in personal experience"
  ],
  "negative_cues": [
    "purely generic agreement (\"yeah\", \"true\", \"makes sense\")",
    "abstract or third-person commentary with no I/me/my anchor"
  ],
  "rule": "If the utterance contains any first-person anchor or names a personal preference, opinion, or experience, label Low. Reserve No for truly empty agreements with zero personal content."
}
```

Rules are versioned. Each `ReflectMemoryVersion` row stores the full ordered list
of active rules with `created_at` and the optimizer run that produced it. New
runs may add, modify, or retire rule IDs; deletion is soft (the row stays, marked
`retired_at`) so the audit trail survives. Because the rules are explicit text,
the prompt the system calibrates to a given rater is readable: a reviewer can see
*how* the system learned to label like coder A, not just that it did.

### Multi-annotator ingest and IAA

`DataItem` carries a `labels_by_annotator` field keyed by annotator ID, so every
coder's label stays intact:

```python
labels_by_annotator: dict[str, dict[str, str | list[str]]]
# {"Fiona": {"Level": "Low"},
#  "Chang": {"Level": "No"}}
```

Annotator IDs are user-provided display names. Missing values are allowed: a
coder may rate some items and not others, the common real-world case. The wizard
joins on item index or a user-selected key column. The system computes and
reports IAA per dimension with the standard metrics and interpretation
thresholds (Landis and Koch, 1977; Krippendorff). IAA here is a diagnostic that
tells the team how much the choice of target rater matters, not a gate that must
be cleared before the system will help.

---

## Walkthroughs

Each walkthrough corresponds to a segment of the demo video and a screenshot in
the paper.

**W0, cold-start labeling.** A user with a fresh codebook and unlabeled data
lands on Setup. CodebookAgent drafts a structured codebook and shows an editable
preview; the user tweaks dimension names and label definitions, then commits.
The user uploads raw data and lands on the Annotate page, which renders one item
at a time with a pre-filled label and one-line reasoning per dimension. The user
accepts, edits one dimension, or rejects. After about twenty accepted items on a
dimension, a background ReflectAgent run mines rules from the accepted set and
updates the pre-fill prompt; a "Pre-fill improved (rev 2)" badge appears.

**W1, multiple annotators and target selection.** The user uploads two annotator
spreadsheets on Setup; the wizard joins on item index and populates
`labels_by_annotator`. The system computes IAA per dimension and shows where the
coders diverge. The user picks a target rater (or opens the review queue to
resolve disputes into one corpus). Picking a target hands that rater's labels to
Flow C.

**W2, target-aligned optimization.** On the Improve page, AutoPromptGenerator has
already drafted one prompt per dimension. The user clicks "Improve from
examples." The trajectory chart shows validation accuracy and macro F1 climbing
round by round against the chosen target; rollbacks appear as small dips that get
undone. The Memory section shows the versioned rule library with plain-English
boundaries and per-label cues. The user runs annotation on the held-out test
set; the Results page shows per-class precision, recall, and F1, a confusion
matrix, and CSV and JSON export.

---

## Evaluation plan

The evaluation answers one question: does the improvement loop raise agreement
with a chosen target rater, and is the lift specific to that rater rather than a
generic prompt improvement? The track requires an evaluation; this one is sized
to demonstrate the claimed capability, not to sweep optimizers, backbones, or
domains.

### Dataset and why it is hard

The flagship codebook is AI-companion self-disclosure, four single-label
dimensions: Level of disclosure, Disclosure as confession, Depth of disclosure,
and Intimacy of self-disclosure. Two coders, **Fiona** and **Chang**, labeled it
independently. Fiona labeled 333 utterances, Chang 330, with 177 utterances in
common.

The two coders apply the same codebook in measurably different ways, which is the
point. On the 177 shared utterances their raw agreement is 67.4% on Level, 62.7%
on Confession, 69.7% on Depth, and 34.8% on Intimacy. Their label-space usage
diverges too: Fiona uses a `No` class on Level (42 items) that Chang never uses;
on Confession, Fiona calls 271 No against 45 Yes while Chang is nearly balanced
at 156 No against 173 Yes; on Depth and Intimacy, Fiona almost never uses the
`Peripheral` class (5 and 3 items) while Chang uses it about 80 times each. A
single consensus target would erase these differences. Per-target alignment
preserves them.

### Table 1, per-target alignment (the headline)

For each annotator and each dimension, split that annotator's labeled items
deterministically into train, validation, and test (seed derived from
`(annotator, dimension)`, test held out from the optimizer). Baseline is the
zero-shot starting prompt (`auto_v001`); treatment is the prompt after
ReflectAgent optimizes against that annotator's train slice under validation
gating. Agreement is accuracy against the same annotator's held-out test labels.
One flagship model (`gpt-5.4-mini`), no per-class tuning.

| Target | Dimension | n_labeled | n_test | Zero-shot agree | + ReflectAgent agree | Δ pp |
|---|---|---|---|---|---|---|
| Fiona | Level of disclosure | 323 | (run) | (run) | (run) | +X.X |
| Fiona | Disclosure as confession | 316 | (run) | (run) | (run) | +X.X |
| Fiona | Depth of disclosure | 166 | (run) | (run) | (run) | +X.X |
| Fiona | Intimacy of self-disclosure | 124 | (run) | (run) | (run) | +X.X |
| Chang | Level of disclosure | 330 | (run) | (run) | (run) | +X.X |
| Chang | Disclosure as confession | 329 | (run) | (run) | (run) | +X.X |
| Chang | Depth of disclosure | 330 | (run) | (run) | (run) | +X.X |
| Chang | Intimacy of self-disclosure | 330 | (run) | (run) | (run) | +X.X |

Macro-F1 deltas accompany each row in an appendix table, since agreement
(accuracy) can flatter a skewed dimension such as Fiona's Confession. The
expected reading: each annotator's own optimized prompt agrees with that
annotator better than the zero-shot prompt does, on held-out items.

### Table 2, the specificity control (is alignment real?)

A reviewer could read Table 1 as "the optimizer makes the prompt better in
general." The specificity control rules that out. Take the prompt optimized for
Fiona and the prompt optimized for Chang, and evaluate each against both
annotators' held-out test sets. The diagonal (own target) should beat the
off-diagonal (other target). The gap is the personalization the system claims.

| Dimension | Prompt→Fiona on Fiona-test | Prompt→Chang on Fiona-test | Prompt→Fiona on Chang-test | Prompt→Chang on Chang-test |
|---|---|---|---|---|
| Level of disclosure | (run, diag) | (run, off) | (run, off) | (run, diag) |
| Disclosure as confession | (run, diag) | (run, off) | (run, off) | (run, diag) |
| Depth of disclosure | (run, diag) | (run, off) | (run, off) | (run, diag) |
| Intimacy of self-disclosure | (run, diag) | (run, off) | (run, off) | (run, diag) |

If the diagonal beats the off-diagonal, the loop learned each rater's idiosyncrasy
rather than a shared notion of correctness. On dimensions where the two coders
already agree (Depth at 69.7%) the gap will be small; on Intimacy (34.8%) it
should be large. That dependence is itself evidence the effect is real.

### Supporting context

End-to-end annotation throughput in items per minute on the flagship model. The
shared-item agreement numbers above, reported as the motivation for per-target
alignment. Memory growth across sessions on one dimension: number of rules after
each session, until the PatternExtractor stops finding new failure patterns.

### What we deliberately do not evaluate

We do not run a full optimizer-by-codebook-by-model matrix. We do not run a human
user study of the labeling UI. We do not run multi-seed significance tests on the
headline numbers. We do not claim cross-domain generalization from a single
codebook. Those analyses belong in a research follow-up; the bar for this
submission is a working system demonstration with an honest, held-out alignment
result.

---

## Related work

| Prior work | What it does | How CLAIR relates |
|---|---|---|
| **LabelLLM** (OpenDataLab), and other general-purpose labeling tools (Prodigy, Doccano) | Open-source human-annotation platforms with task management, multi-format ingest, per-item labeling, and static LLM pre-annotation | Feature baseline CLAIR matches and extends. Flow A provides the same per-item surface with LLM pre-fill; on top, CLAIR adds codebook ingestion into a structured schema, an improvement loop that learns from the team's own labels, and multi-annotator IAA as a first-class signal. Their pre-fill is fixed; ours calibrates to a target rater |
| **CrowdAgent** (EMNLP 2025 Demo) | Multi-agent system that routes fresh annotation tasks across LLMs, SLMs, and human experts under joint quality and cost management | CrowdAgent allocates who labels what. CLAIR assumes humans already labeled and calibrates the LLM to a chosen rater's labels |
| **EvoAgentX** (EMNLP 2025 Demo) | Platform for evolving multi-agent workflow topology; integrates TextGrad, AFlow, MIPRO | EvoAgentX evolves workflow topology on general benchmarks. CLAIR refines a single annotator prompt anchored in a codebook and a target rater |
| **Shankar et al., UIST 2024** (EvalGen) | Mixed-initiative tool that aligns LLM-generated evaluators with human grades; surfaces criteria drift | Their LLM scores LLM outputs against user criteria. Our LLM annotates the underlying data and is tuned to a specific human's labels |
| **Cleanlab / Confident Learning** (Northcutt et al., JAIR 2021) | Estimates noisy-vs-true label distribution; flags suspected label errors | Cleanlab assumes a single latent true label and flags deviations. CLAIR does not assume one true label; it tunes to a chosen target |
| **Dawid-Skene (1979); MACE** (Hovy et al., NAACL 2013) | Crowd-aggregation models that recover one latent label from redundant annotations | They collapse disagreement into one inferred label with no reasoning trace. CLAIR keeps each rater as a separate target and produces inspectable rules per target |
| **Lapras** (Wang et al., CHI 2024) | LLM labels everything; a learned verifier scores LLM labels; humans re-annotate low-confidence items | Closest spirit-neighbor on the human-LLM loop, but it pursues one correct label. CLAIR pursues alignment with a chosen rater |
| **GEPA** (Agrawal et al., 2025), **MIPROv2** (Opsahl-Ong et al., EMNLP 2024), **OPRO** (Yang et al., ICLR 2024) | Offline batch prompt optimizers; each returns one optimized prompt, no persistent artifact | ReflectAgent runs online inside the tool, accumulates an inspectable rule library across sessions, and optimizes against a target rater |
| **Ni et al., 2025** (Reasoning and annotator disagreement) | Studies whether LLMs can predict human disagreement distributions | We cite it as evidence that LLM behavior under disagreement is an open problem, and we take the practical stance of aligning to one chosen rater rather than predicting the full distribution |

### Position vs "disagreement is signal"

A growing line of work argues that disagreement should be preserved rather than
resolved: keep soft labels, train annotator-specific models, report full
distributions. CLAIR sits inside that view rather than against it. Where a
forced consensus would discard the difference between Fiona and Chang, the system
keeps both as targets and calibrates to whichever the team picks. For teams that
do require one resolved label, the review queue supports that path too, but the
default is to respect the annotator-specific signal, not erase it.

### Honest caveat

Across the tools we surveyed, none combines a codebook-ingestion agent, an
online improvement loop with a cross-session rule library, and per-target
alignment in one deployable system. That a combination is unpublished does not
make it important; the demonstration's job is to show it works and is usable. The
labeling UI itself overlaps with LabelLLM, Prodigy, and Doccano. What is new is
the improvement loop that calibrates to a chosen rater and the inspectable rules
it produces.

---

## Limitations

The flagship evaluation runs on a single codebook and two annotators, so we make
no cross-domain or large-population claim. Per-target alignment is demonstrated
for n=2 targets; whether it holds across many raters or for raters whose labels
are internally inconsistent is future work.

The system aligns to a target rater's labels as given. If those labels encode a
bias, the calibrated prompt will reproduce that bias. This is a property of the
chosen target, not a defect the system can detect on its own, and the inspectable
rules are the mitigation: a reviewer can read what the system learned to imitate.

The system improves a prompt and a rule library, not model weights. There is no
fine-tuning. For codebooks whose ceiling truly requires weight updates,
CLAIR is the wrong tool.

The improvement loop assumes enough labeled items per dimension to form a
train, validation, and test split; dimensions below the gate are labeled
zero-shot and not optimized.

---

## References

- LabelLLM (OpenDataLab). https://github.com/opendatalab/LabelLLM
- He, C. et al. (2024). *OpenDataLab: Empowering General AI with Open Datasets.* arXiv:2407.13773.
- CrowdAgent: Multi-Agent Managed Multi-Source Annotation System. EMNLP 2025 Demo. https://aclanthology.org/2025.emnlp-demos.72/
- EvoAgentX: An Automated Framework for Evolving Agentic Workflows. EMNLP 2025 Demo. https://aclanthology.org/2025.emnlp-demos.47/
- Shankar, S. et al. (2024). *Who Validates the Validators? Aligning LLM-Assisted Evaluation of LLM Outputs with Human Preferences.* UIST 2024. arXiv:2404.12272.
- Northcutt, C. et al. (2021). *Confident Learning: Estimating Uncertainty in Dataset Labels.* JAIR. arXiv:1911.00068. https://github.com/cleanlab/cleanlab
- Dawid, A. P. and Skene, A. M. (1979). *Maximum Likelihood Estimation of Observer Error-Rates Using the EM Algorithm.* Applied Statistics 28(1), 20-28.
- Hovy, D., Berg-Kirkpatrick, T., Vaswani, A., and Hovy, E. (2013). *Learning Whom to Trust with MACE.* NAACL 2013. https://aclanthology.org/N13-1132/
- Wang, X. et al. (2024). *Human-LLM Collaborative Annotation Through Effective Verification of LLM Labels* (Lapras). CHI 2024. https://dl.acm.org/doi/10.1145/3613904.3641960
- Ni, J. et al. (2025). *Can Reasoning Help LLMs Capture Human Annotator Disagreement?* arXiv:2506.19467.
- Agrawal, L. et al. (2025). *GEPA: Reflective Prompt Evolution.* arXiv:2507.19457.
- Opsahl-Ong, K. et al. (2024). *Optimizing Instructions and Demonstrations for Multi-Stage Language Model Programs* (MIPROv2). EMNLP 2024. arXiv:2406.11695.
- Yang, C. et al. (2024). *Large Language Models as Optimizers* (OPRO). ICLR 2024. arXiv:2309.03409.
- Zheng, L. et al. (2023). *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena.* NeurIPS 2023. arXiv:2306.05685.
- Landis, J. R. and Koch, G. G. (1977). *The Measurement of Observer Agreement for Categorical Data.* Biometrics 33(1), 159-174.
- Krippendorff, K. *Content Analysis: An Introduction to Its Methodology.*
- Ng, A. (2021). *MLOps: Model-Centric to Data-Centric AI.* Talk.
