# AnnotAgent — paper plan

## Paper Claims

AnnotAgent is a **multi-agent system** for codebook-driven annotation. It covers the same surface area as a general-purpose labeling tool (LabelLLM, Prodigy, Doccano) and adds two **self-evolving** agents that learn interpretable rules from labeled items, carry those rules across sessions, and use them either to keep improving on gold-labeled data or to propose adjudications when human annotators disagree. The paper makes two claims:

**C1 (proposed). Adjudication-as-data-cleaning loop.** One contribution with two halves that depend on each other. *First half — the mechanism.* When two or more human annotators have already labeled data and they disagree on some subset of items, the disputed items are adjudicated by an LLM that has first learned rules from the items the same annotators agreed on. The LLM emits a verdict together with the rules it cited; a human reviews and accepts, overrides, or skips. *Second half — the payoff.* Hold the model and the initial prompt fixed and run C2 twice on the same dimension: first on the agreed-only subset, then on the full corpus after the adjudication step above. Overlay the two validation curves. The first plateaus; the second climbs past it. The gap is the value of cleaning the labels, measured in held-out test accuracy with everything else held constant, and a matched-size control rules out the trivial "more data is better" reading. The two halves are pitched as one contribution because each is incomplete on its own: the mechanism without the overlay does not show that adjudication-via-LLM is worth doing, and the overlay without the mechanism has nothing to demonstrate. The empirical bet behind the first half — that rules mined from the agreed (easy) subset transfer usefully to the disputed (hard) subset — is unverified at the time of writing and will be tested in a verification spike on Fiona's `Level` dimension before the paper is committed to print.

**C2 (built).** A ReflectAgent loop runs failure-driven prompt optimization on a leakage-guarded train/val/test split, distilling failures into interpretable rules and rolling back rule updates that regress held-out validation. Rules persist across sessions in a versioned Memory table: each run on a dimension seeds from the last run's rule library. This is what is built today, and the evaluation tables for self-disclosure annotation will exercise it. We can further integrate prompt optimization techniques like DSPy, GEPA here.

The paper is framed as a system demonstration rather than a controlled study. The evaluation shows the system works on a representative hard case (a low-IAA codebook for AI-companion conversation analysis). It is not a benchmark sweep across optimizers, model backbones, or codebook domains.

---

## Why annotation at production scale is broken

A trained human coder reading a multi-turn AI-companion dialogue and applying a six-dimension codebook spends thirty to ninety seconds per item. Multiply by a hundred thousand items per release cycle and the budget is measured in person-months. The data-centric AI literature (Ng, 2021; Northcutt et al., 2021) frames this scale problem as the central constraint of modern AI engineering: model quality is bottlenecked by label quality, and label quality is bottlenecked by human time.

The cost problem is compounded by drift. Conversational-AI products ship new model versions; user populations turn over; codebooks evolve as researchers discover new failure modes. Each drift invalidates a slice of the existing gold set. Re-labeling at production cadence is the friction that kills longitudinal projects, and it is the friction that a static "LLM pre-fills, human accepts" tool like LabelLLM does nothing to ease. The LLM's pre-fill prompt was set on the old data distribution and does not update as the human's accept/edit signal accumulates.

The third problem is disagreement. On subtle dimensions like *intimacy*, *depth*, or *emotional valence*, trained coders agree only 60–70% of the time. Standard inter-annotator agreement metrics — Cohen's κ for two raters, Fleiss' κ for three or more, Krippendorff's α when raters miss items — let researchers quantify the gap, but the same data can yield κ from below zero to above 0.6 depending on which pair of raters one picks. The disputed slice is where the codebook actually lives: the boundary cases tell you what the distinctions mean. It is also the slice that is most expensive to adjudicate. The standard practice is a single senior coder making silent calls behind the scenes, with no audit trail.

A growing line of work argues that disagreement is not always error. On tasks like sarcasm or toxicity, the right answer is often a distribution over labels rather than a single label, and soft labels with annotator-specific models capture more signal than forced consensus does. AnnotAgent does not contest this view. For codebooks where downstream analysis genuinely requires a single label per item (per-class F1, downstream model training, manuscript findings), we offer an auditable alternative to silent senior-coder adjudication. For codebooks where the right answer is a distribution, we recommend a soft-label workflow elsewhere.

LLM-as-judge offers a partial way out. The standard recipe (Zheng et al., 2023; Shankar et al., 2024) is to write a judge prompt, split labeled data into train/dev/test, iteratively refine the prompt, and measure true-positive and true-negative rates against human labels. The recipe works for evaluating LLM outputs; transplanting it to production *annotation* surfaces three concerns. LLM verdicts are sensitive to prompt wording and carry biases — position, verbosity, self-preference — that interact unpredictably with subtle codebooks. The verdicts are not naturally interpretable: a human coder can explain her label, a black-box LLM cannot. And a tool that ignores the multi-annotator workflows labeling teams already use is a tool that asks for replacement, not adoption.

AnnotAgent is built on the bet that wiring failure-driven rule extraction, multi-annotator workflows, and a shared persistent rule library together yields a system a small team can use to keep a production annotation pipeline calibrated against a moving data distribution. The rest of this document argues that bet section by section.

---

## What AnnotAgent does

The system is composed of four LLM-backed agents and two shared persistent artifacts. The four agents are `CodebookAgent`, which ingests user-supplied codebook materials and produces a structured schema; `AutoPromptGenerator`, which drafts one annotation prompt per dimension in parallel; `Annotator`, which applies a prompt to items; and `ReflectAgent`, which mines rules from labeled items and updates the Annotator's prompt subject to a held-out validation check. The two shared artifacts are the **Rule Library**, a versioned set of interpretable rules with positive and negative cues per label, and the **Memory**, a per-dimension log of rule library versions that lets the next session seed from the previous session.

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
              │  3. Annotator                                          │   ◀── Flow A entry:
              │  Batch (Flows B + C): pipeline runner, per-dim or      │       interactive single-
              │     all-together, async, pause/cancel/resume, WS prog. │       item labeling with
              │  Interactive (Flow A): per-item pre-fill on demand,    │       LLM pre-fill +
              │     drives the Cold-start Labeling page                │       shadow ReflectAgent
              └───────────────────────────────────────────────────────┘
                                    │  predictions + per-class metrics    ◀── C1 entry:
                                    ▼                                        rule-augmented run on
              ┌───────────────────────────────────────────────────────┐      disputed items, store
              │  4. ReflectAgent (the shared engine)                   │      verdict + cited rules
              │  PatternExtractor:                                     │
              │    • rules from failures (C2 + shadow / Flow A)        │   ◀── C1 entry:
              │    • rules from agreed items (C1 / Flow B)             │       PatternExtractor
              │  Annotator role: labels items with current prompt+rules│       on agreed subset
              │  Governor: holdout-gated rollback                       │
              │  Held-out test scored ONCE at end (leakage guard)      │
              └───────────────────────────────────────────────────────┘
                                    │  rule library + optimized prompt
                                    ▼
              ┌───────────────────────────────────────────────────────┐
              │  5. Memory (cross-session)                             │   ◀── C3 entry:
              │  ReflectMemoryVersion table, versioned per (project,   │       re-seed Run 2
              │  dimension). Each run seeds from the latest version.   │       from same v0 prompt
              │  Editable, exportable, accumulates across sessions.    │       after corpus update
              │  Shadow runs in Flow A write Memory mid-session.       │
              └───────────────────────────────────────────────────────┘
```

`CodebookAgent` does three jobs inside one agent. The Ingestor parses the upload (PDF, DOCX, XLSX, CSV, JSON, or plain text), normalizing messy spreadsheets along the way: multiple sheets, continuation rows, `&`-separated multi-label cells. The Drafter produces a structured `CodebookDef` with single-label or multi-label inferred per dimension. The Critic flags ambiguities for the user. The user then edits the draft in a wizard before committing, and the wizard outputs an analysis-friendly `cleaned_data.json` side-artifact for any downstream tool that wants a flat view of the items.

`AutoPromptGenerator` uses a Jinja meta-prompt (`auto_prompt_generator.jinja`) to write one annotation prompt per dimension in parallel. Each prompt is versioned on disk under `workspace/project_<id>/prompts/<dim>/auto_v00N`, so the user can roll back or compare. A separate deterministic generator, `prompt_generator.jinja`, remains in place for the gallery and preset codebooks where reproducibility outweighs adaptiveness.

`Annotator` runs in two modes. Batch mode handles full datasets with bounded concurrency, WebSocket progress updates, and pause/cancel/resume; the per-dimension sub-mode runs one step per dim and avoids cross-dimensional interference, while the all-together sub-mode covers every dim in one LLM call per item and is cheaper but noisier. Interactive mode handles one item at a time and drives the cold-start labeling page (Flow A below).

`ReflectAgent` is the shared engine for both improvement loops. The PatternExtractor distills a batch of items into interpretable rules (positive cues, negative cues, target labels, plain-English boundary). The same role is invoked with two different batch compositions: in C2 it consumes failure cases mined from the current prompt's wrong predictions on the training slice; in C1 it consumes items where every human annotator agreed, treating the convergence itself as positive evidence of how the codebook resolves a given decision. The Governor scores each candidate prompt on a held-out validation slice and rolls back any rule update that regresses validation accuracy by more than a small epsilon. A held-out test slice is scored exactly once at the end, and the train/val/test partition is asserted disjoint by object identity before any run starts.

`Memory` writes a new `ReflectMemoryVersion` row after every successful run, indexed by `(project, dimension)`. The next run on the same dimension reads the latest version's rules as its starting library; trajectory chart round zero shows `action: baseline_seeded` whenever this happens. Memory is editable in the UI: the user can manually add, edit, or retire rules, and the audit log persists.

---

## Three user flows

Different projects walk in at different stages of labeling maturity. The same four agents serve all three flows; what changes is which agents activate, in what order, and what artifact they write.

**Flow A — cold start.** The user has a codebook (or wants help drafting one) and raw data. They want to label item by item with LLM assistance, the way LabelLLM and Prodigy support today. AnnotAgent covers this case: CodebookAgent ingests the codebook, AutoPromptGenerator drafts a starting prompt per dimension, and the Annotator runs in interactive mode. Each accepted or edited verdict becomes a gold-label row. Once the dimension accumulates roughly twenty accepted items, a background ReflectAgent run mines rules from the accepted set and updates the pre-fill prompt for the rest of the session. A small badge on the labeling page tells the user the pre-fill improved and which revision is active.

**Flow B — resolving disagreement.** The user has labels from two or more coders on the same items. CodebookAgent ingests the codebook; the dataset wizard joins the annotator files on item index; the system computes IAA per dimension (Krippendorff's α by default, Cohen's κ for the N=2 pairwise case, Fleiss' κ when N≥3 with no missing values). Per the chosen agreement mode (unanimous, majority, or plurality), items split into agreed and disputed subsets per dimension. ReflectAgent runs on the agreed subset, producing a rule library that encodes how the codebook resolves the easy cases. The Annotator labels each disputed item with the rule-augmented prompt and emits a verdict together with the IDs of the rules it cited. The user reviews each disputed item in a queue: every annotator's label sits in a horizontal strip next to the LLM verdict, the reasoning, and the cited rules (clickable, navigates to the rule). Accepted or overridden verdicts move into the agreed corpus and bump the rule library version. This flow embodies C1, which is unverified.

**Flow C — gold-label optimization.** The user has gold-labeled data already adjudicated, or has accumulated enough cold-start labels through Flow A. AutoPromptGenerator drafts the starting prompts; ReflectAgent runs failure-driven optimization with held-out validation; Memory writes a new version. Subsequent runs on the same dimension seed from the latest version, and rules compound across sessions.

The three flows are not isolated. Flow A's accepted labels feed Flow C the moment the user wants to switch to batch optimization. Flow B's adjudicated verdicts upgrade a partially-labeled corpus into a fully-labeled one, which is then the natural input for Flow C. C1's second half lives precisely in this composition: run Flow C twice from the same starting prompt, once before and once after Flow B's adjudication step, and overlay the validation curves.

---

## The two contributions in depth

### C1 (proposed): adjudication-as-data-cleaning loop

C1 has two halves. The first half resolves disagreement by adding an LLM third voice with cited rules and human re-judgment. The second half re-runs the optimizer from the same starting prompt on the post-adjudication corpus and overlays the curve against the pre-adjudication run. The first half is the mechanism; the second half is the measurement. Neither half stands alone in the paper: a mechanism with no measurement asks the reader to trust that the adjudication is worth doing, and a measurement with no mechanism has nothing to attribute the lift to.

**The mechanism.** Two trained coders disagree on a disputed item. The traditional resolution is silent: a senior coder reads the item and chooses a label, the record reflects only the final answer. We propose to add a third voice. ReflectAgent first mines rules from the items the same coders agreed on for the same dimension, producing a rule library that encodes the codebook's resolved decisions. The Annotator then applies the rule-augmented prompt to each disputed item and emits a verdict with cited rules. The user sees every annotator's label, the LLM's verdict, and the rules the LLM relied on, and clicks accept, override, or skip. The mechanism is unusual in *which* items the LLM sees rules from. The LLM trains on agreement and is consulted on disagreement; the rules carry the codebook's already-resolved cases into the unresolved ones. The Disagreement Review queue then logs the human re-judgment, so the resolution is auditable in a way silent senior adjudication is not.

**The measurement.** The data-centric AI thesis (Ng, 2021) says model performance is bottlenecked by data quality more often than by model architecture or prompt design. The second half of C1 instantiates that thesis inside our system on a single overlay figure with two curves on the same axes, plus an appendix control curve.

```
       val accuracy
         │
   high  │            ╭───── Run 2: full corpus
         │           ╱      (post-adjudication via C1, same prompt, same model)
         │         ╱
   mid   │       ╱╮
         │      ╱ │
         │    ╱   ╰─────── Run 1: agreed-only subset
         │  ╱       (plateaus — data is the ceiling, not the prompt)
         │╱
         └────────────────────► round
```

Run 1 trains ReflectAgent on the subset where humans agreed. Items that two annotators independently labeled the same way are by construction the *unambiguous* items, and a modest set of rules handles them. The validation slice is drawn from the same distribution, so once the rule library captures the easy patterns, additional rounds yield diminishing returns. Run 1 plateaus. Run 2 trains on the same starting prompt and the same model, but on the full corpus after Flow B has resolved the disputed items. The adjudicated-disputed items are the boundary cases — each one encodes a decision the annotators could not resolve in isolation. Mixing them into the training corpus exposes the PatternExtractor to the boundary cases the easy items hid. Run 2 climbs past Run 1. The gap between the curves is the value of cleaning labels, measured in held-out test accuracy with everything else held constant.

A reviewer might read Figure 4 as "more data is better" and discount the contribution. The matched-N control curve rules that reading out. Run 3 trains on a size-matched random slice of the post-adjudication corpus, equal in item count to the agreed-only set. The composition of Run 3 is a mix of agreed and adjudicated-disputed items in roughly the natural ratio of the full corpus. The comparison between Run 1 and Run 3 isolates the label-quality lift at matched corpus size. Run 3 lives in the appendix and is referenced from a footnote in the eval section.

**The empirical risks and the verification spike.** The empirical premise behind the mechanism is that rules mined from the agreed subset transfer usefully to the disputed subset. The premise might fail in at least three ways. The disputed items might live in a region of the codebook the agreed rules never cover, so the LLM's `cited_rules` field comes back empty and the verdict falls back to zero-shot behavior. The rules might fire but resolve disputes the way the *majority annotator* would rather than the way an external adjudicator would; that is empirically distinguishable from a true calibration signal. Or what looks like agreement might be coordinated annotator bias, in which case the rules re-encode the bias and the verdict is wrong in the same way the agreed labels are wrong. The empirical risk behind the measurement is independent of these: even if the mechanism works, the lift between Run 1 and Run 2 might be small, noisy, or absorbed by the matched-N control — in which case the data-centric story does not survive Figure 4.

The verification spike resolves the mechanism's risks. On Fiona's `Level` dimension we build the agreed/disputed split, run ReflectAgent on the agreed subset, apply the rule-augmented prompt to the disputed items, and compare the LLM verdicts to the eventually-adjudicated labels we have on hand from Fiona's senior-coder pass. Three measurements fall out. The grounded-rate counts disputed items where `cited_rules` is non-empty; if this is below 50%, the rules do not transfer. The accuracy with rules versus zero-shot tells us whether the rule library actually lifts performance on the hard items. And the bias check correlates the LLM verdict with each individual annotator's labels on the disputed items; if the LLM behaves like a copy of one specific annotator, the rules absorbed that annotator's idiosyncratic patterns. The measurement's risk is checked end-to-end by Figure 4 itself: if the gap between Run 1 and Run 3 is within noise, we report it that way.

If the spike comes back positive and Figure 4 shows a real lift, C1 ships as written. If the spike fails, C1 becomes a useful negative result in the same section, supported by the same numbers: rules from agreement do not transfer to disagreement on this codebook, and here is why. The Disagreement Review UI itself ships either way; making adjudication visible is a contribution to codebook research workflows even without the LLM verdict button.

### C2: a self-evolving annotator with cross-session memory

Existing prompt optimizers — GEPA, MIPROv2, OPRO — return a single optimized prompt from a fixed training set and keep no persistent artifact. ReflectAgent does the analogous job inside our system but produces an inspectable rule library and a Memory log that carries forward across sessions on the same dimension.

Each round of optimization runs a small loop. The PatternExtractor takes failure cases from the current prompt's predictions on the training slice and distills them into candidate rules; it is forbidden from quoting failure sentences verbatim and must abstract the boundary it sees. The Annotator labels the validation slice with the candidate rule set. The Governor compares validation accuracy before and after; if the candidate regresses by more than `rollback_epsilon`, the round rolls back. The trajectory chart makes rollbacks visible as small dips that get undone.

The held-out test slice is scored exactly once, at the end of optimization, on the final rule library. The asserts in `api/optimizers.py::_execute_run` verify the three sets are disjoint by object identity before any round starts. This is the standard rule from LLM-as-judge prompt development — validation and test items never enter the prompt — and it is the line we hold.

Memory is the part that compounds across sessions. After each successful run on a dimension, the final rule library writes a new `ReflectMemoryVersion` row. The next run on the same dimension reads the latest version's rules as its starting library; the trajectory shows `baseline_seeded` at round zero and the prompt arrives at the loop already richer than it started. Over enough sessions a dimension reaches saturation: the rule library stops growing because the PatternExtractor cannot find new failure patterns to abstract.

---

## How the system is built

### The rule library

Each rule is a structured object with the following fields:

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

Rules are versioned. Each `ReflectMemoryVersion` row stores the full ordered list of rules active at the time, with `created_at` and the ID of the optimizer run that produced it. New runs may add, modify, or retire individual rule IDs, and rule deletion is soft (the row stays, marked `retired_at`) so audit trails survive.

### Mining rules: from failures and from agreement

The PatternExtractor role is invoked with different input batches and different system prompts in C2 versus C1, but it produces the same rule schema either way.

| | C2 — failure mining | C1 — agreement mining |
|---|---|---|
| Input batch | Items where the current prompt produced a wrong label, with `(sentence, prefix, gold, predicted, reasoning)` | Items where every human annotator chose the same label, with `(sentence, prefix, agreed_label)` |
| What the extractor produces | Rules that would have prevented this batch of failures | Rules that explain why the codebook resolves this batch the way it does |
| Implicit "boundary" signal | The gap between gold and predicted | The convergence itself: every annotator chose the same label |
| Source-quoting | Forbidden from quoting source sentences verbatim | Same |
| Governor check | Candidate must not regress validation accuracy on gold | Candidate must not regress prediction-vs-agreed-label accuracy on a held-out validation slice of the agreed subset |

Both flavors share the same prompt scaffold; the differences are the system prompt header and the input batch. The Governor's leakage and rollback guards apply identically in both.

### Verdict format and the Disagreement Review queue

When the Annotator labels a disputed item in Flow B, it emits a structured object the UI can render:

```json
{
  "item_id": 4271,
  "dimension": "Level",
  "verdict": "Low",
  "confidence": 0.78,
  "reasoning": "The speaker names a personal preference (\"I prefer to keep things to myself\"), which is a first-person anchor with a stated opinion. Per Rule level-2025-05-14-001 this is Low, not No.",
  "cited_rules": ["level-2025-05-14-001"],
  "human_labels": {"annotator_A": "No", "annotator_B": "Low"}
}
```

The `cited_rules` list drives clickable in-place rule popovers in the Review queue. If the Annotator returns a non-default verdict with an empty `cited_rules`, the verdict is flagged in yellow and the user sees "ungrounded — manual review recommended." This is the mechanism that surfaces failure mode (1) from the C1 verification plan: when rules from the agreed subset cover none of the disputed items, the user sees yellow on most of the queue and knows to distrust the LLM voice on this batch.

### Multi-annotator ingest and IAA

The current `Dataset` model stores one `gold_labels` dict per item. Flow B needs every annotator's label intact, so `DataItem` gains a `labels_by_annotator` field keyed by annotator ID:

```python
labels_by_annotator: dict[str, dict[str, str | list[str]]]
# Three annotators:
# {"A": {"Level": "Low"},
#  "B": {"Level": "No"},
#  "C": {"Level": "Low"}}
# Multi-label dimensions use list values:
# {"A": {"AI_behaviors": ["validate", "advise"]},
#  "B": {"AI_behaviors": ["validate"]}}
```

Annotator IDs are user-provided strings (display names like `Fiona` or `Chang`). Missing values are allowed: an annotator may have rated some items but not others, which is the common real-world case. The wizard joins on item index or on a user-selected key column.

Defining "agreed" for two raters is unambiguous. For three or more, the system surfaces a choice and defaults to the strictest variant. Under `unanimous` mode (the default) an item is agreed only when every annotator who rated it chose the same label. Under `majority`, a strict majority suffices. Under `plurality`, the most common label wins as long as it has strictly more votes than any other. The default is unanimous because the training-data quality matters more for the rule library than the sample size; Researcher mode exposes the toggle.

The system computes and reports inter-annotator agreement per dimension at three levels of generality:

| Metric | Preconditions | When AnnotAgent reports it |
|---|---|---|
| Cohen's κ | Exactly two raters, no missing data, nominal scale | Pairwise, when N=2, or for any selected pair when N>2. Useful for catching one outlier rater |
| Fleiss' κ | N raters, all rate all items, nominal | Reported when N≥3 with no missing data |
| Krippendorff's α | Any N, missing data permitted, any scale | Default report; always shown. Handles the common case where coverage is incomplete |

Interpretation thresholds appear inline next to each value: < 0.00 "no agreement," 0.21–0.40 "fair," 0.41–0.60 "moderate," and so on per Landis & Koch (1977); for α, > 0.80 "reliable," 0.67–0.80 "tentative," < 0.67 "revisit guidelines" per Krippendorff. The UI does not editorialize beyond the standard thresholds.

Per-dimension IAA is computed on ingest and recomputed whenever the Review queue moves an item from disputed to agreed. A small delta arrow shows the lift.

### The matched-N protocol

Let A be the number of agreed items for the flagship dimension and D be the number of disputed items. The three Run-1/Run-2/Run-3 curves in Figure 4 differ only in which dataset rows the optimizer sees as its `gold_dataset_id`:

| Run | Training corpus | Labels |
|---|---|---|
| Run 1 (`agreed-only`) | A items where annotators converged | Consensus labels |
| Run 2 (`full-post-adjudication`) | A + D items after Flow B resolved the disputed slice | Consensus for the A; accepted or overridden verdict for the D |
| Run 3 (`matched-N`) | A items sampled at random (fixed seed) from the A + D corpus | Mixed composition: roughly A·(A/(A+D)) agreed and A·(D/(A+D)) adjudicated |

All three runs use the same model, the same starting prompt (`auto_v001` from AutoPromptGenerator), the same optimizer (`reflect_agent`), and the same hyperparameters. The held-out test slice is the same for all three, drawn before any of the three runs starts and never visible to the optimizer.

Reading the figure: the Run 1 → Run 2 gap is the combined effect of label quality and corpus size. The Run 1 → Run 3 gap is the label-quality lift at matched size — the number the paper headlines. The Run 3 → Run 2 gap is the marginal effect of size at fixed label quality.

### A worked example: Fiona, dimension `Level`

To make the pipeline concrete, here is the trace we expect on the flagship dimension.

The Fiona dataset has two annotators on five hundred items. Joined on utterance ID, the agreed/disputed split for `Level` comes to 412 agreed and 88 disputed. Cohen's κ on the dimension is about 0.51 (fair). ReflectAgent runs on the 412 agreed items and, after roughly five rounds, the rule library stabilizes at around twelve rules. Validation accuracy on the held-out slice of the agreed subset reaches roughly 92%.

The rule-augmented Annotator then labels each of the 88 disputed items. For each item the system records the verdict, the confidence, the reasoning, and the cited rules. We then compare the verdicts to the eventually-adjudicated labels from Fiona's senior-coder pass.

The user opens the Disagreement Review queue and decides each disputed item: accept the LLM, override to a different label, or skip. Accepted and overridden items move to the agreed corpus and bump the rule library version.

ReflectAgent runs again, this time from the same `auto_v001` starting prompt but on the full five-hundred-item corpus. Validation accuracy climbs past Run 1's plateau. The matched-N variant, sampled uniformly from the full corpus at A = 412 items, runs separately for the appendix and is expected to land between Run 1 and Run 2.

---

## Walkthroughs

The walkthroughs below describe what a user sees in the UI for each of the three flows plus the overlay run that completes C1's second half. Each one corresponds to a labeled segment of the demo video and to a screenshot in the paper.

### W0 — cold-start labeling

A user with a fresh codebook and unlabeled data lands on the Setup page. CodebookAgent ingests the upload, drafts a structured codebook, and shows an editable preview; the user tweaks dimension names and label definitions, then commits. The user then uploads raw data and lands on the Annotate page, which now renders one item at a time. AutoPromptGenerator has already drafted one prompt per dimension in parallel. For each item, the Annotator pre-fills every dimension with a predicted label and a one-line reasoning, and the user clicks Accept, edits a single dimension, or rejects entirely. After about twenty accepted items on a dimension, a shadow ReflectAgent run mines rules from the accepted set and silently updates the Annotator's prompt. A "Pre-fill improved (rev 2)" badge appears at the top of the page. The session ends when the user is satisfied; the accumulated labels and the rule library are ready for batch annotation on the rest of the corpus.

### W1 — adjudicating disputed items (Flow B, C1 mechanism)

The user uploads N annotator spreadsheets on the Setup page; the wizard joins on item index and produces a single dataset with `labels_by_annotator` populated. Missing values are tolerated. The system computes IAA per dimension and the agreed/disputed split under the current agreement mode. The Improve page shows a panel: "Dim `Level`, three raters: 412 agreed (unanimous), 88 disputed. α = 0.49, fair." Researcher mode exposes the agreement mode toggle; the split recomputes live. The user clicks "Learn from the agreed items." ReflectAgent runs on the agreed subset, and the rule library populates the Memory section.

The user then opens the Disagreement Review page. Disputed items sit in a queue. Each row shows the text, every annotator's verdict in a horizontal strip, the LLM verdict with reasoning, and the rules the LLM cited (clickable). The user clicks Accept LLM, Override to a specific label, or Skip per item. Accepted and overridden items move into the agreed corpus, the dimension's IAA recomputes (the LLM is treated as an additional rater for the resolved item), and the rule library version bumps on the next pass.

### W2 — annotating unseen data (Flow C, C2)

The user lands on the Improve page. For a user-uploaded codebook, AutoPromptGenerator has already drafted one prompt per dimension in parallel, and the cards appear under "Current prompts." The user clicks "Improve from examples." The trajectory chart shows validation accuracy and macro F1 climbing round by round; rollbacks appear as small dips that get undone. The Memory section then shows a versioned rule library with plain-English boundaries and positive and negative cues per rule. The user navigates to the Annotate page, picks the test set, and clicks Run annotation. The Results page shows per-class precision, recall, and F1; a confusion matrix; and CSV and JSON export. A second improvement run on the same dimension reads the latest Memory version, so round zero shows `action: baseline_seeded` and the prompt already carries the rules from the prior session.

### W3 — the data-centric overlay (Flow B + Flow C composition, C1 measurement)

After W1, the user has a cleaned, fully-labeled corpus. The Improve page now offers a "Compare runs" toggle. The user picks the earlier agreed-only run and the new full-corpus run, both seeded from the same `auto_v001` prompt. The trajectory chart overlays both curves on the same axes. Annotations on the chart point out: Run 1 plateaus at round 4; Run 2 climbs past it; same prompt, same model, only the labels differ. A small panel below shows the matched-N variant for the appendix, so the user can see the size confound is not the explanation.

---

## Evaluation plan

### Flagship dataset

The evaluation centers on a single hard codebook: AI-companion conversation analysis, with user-side self-disclosure (five dimensions, single-label) and AI-side behavior (three themes, multi-label), annotated on adjudicated dialogues. Two annotator datasets are available with per-annotator columns intact. *Fiona* has multiple coders, raw cell-level labels per coder, and an IAA on `Level` near 68.6% (κ ≈ 0.5, fair). *Chang* has multiple coders on the same codebook and provides cross-coder consistency for an external validation of Flow B. The flagship is the hardest case in our hands; nothing in the system is dialogue-specific.

### Table A — per-dimension self-disclosure (C2)

A three-way split (train 15% / val 42% / test 43%) with test items held out from the optimizer. Five dimensions, one flagship model (`gpt-5.4-mini`), zero-shot versus ReflectAgent:

| Dimension | n_labeled | Zero-shot test | + ReflectAgent test | Δ pp |
|---|---|---|---|---|
| Level of disclosure | 118 | (run) | (run) | +X.X |
| Depth of disclosure | 62 | (run) | (run) | +X.X |
| Disclosure as confession | 104 | (run) | (run) | +X.X |
| Intimacy of self-disclosure | 24 | (run) | (run) | +X.X |
| Temporality | 12 | n/a (< 15-item gate) | — | — |

### Table B — adjudication metrics (C1 mechanism)

Per dimension, on the disputed-items subset:

| Metric | Without rules | With rules from agreed subset |
|---|---|---|
| LLM verdict matches eventually-adjudicated label | (run) | (run) |
| Tie-broken IAA on dimension `d` (3-way: A, B, LLM) | (run) | (run) |
| Human acceptance rate of LLM verdict (Review UI) | n/a | (run, small sample) |
| Mean review time per disputed item (s) | n/a | (run, demo sample) |

The headline result we expect: rules learned from the agreed subset make the LLM verdict materially better than zero-shot on disputed items, and humans accept it often enough that adjudication time falls without rubber-stamping. If the verification spike comes back negative, Table B reports those numbers honestly as a negative result.

### Figure 4 — the data-centric overlay (C1 measurement)

Two trajectories on one chart for the flagship dimension, same model, same `auto_v001` initial prompt, same optimizer budget. Run 1 is agreed-only; Run 2 is agreed plus adjudicated-disputed (full corpus, post-W1). The appendix adds Run 3, the matched-N control. The text frames the gap between Run 1 and Run 2 as "data quality lift" and the gap between Run 1 and Run 3 as "data quality lift controlling for size."

### Supporting context

End-to-end annotation throughput in items per minute on the flagship model. Raw IAA on the gold source (68.6% on `Level`, 24.6% on `Topic`) to motivate why this codebook is hard. Memory growth across sessions on the flagship dimension: number of rules after each session, until saturation.

### What we deliberately do not evaluate

We do not run a full optimizer × codebook × model matrix. We do not compare against human-only baselines in a user study. We do not run multi-seed significance tests on any of the headline numbers. Those analyses belong in a research follow-up. The rigor bar for this submission is system demonstration: the system works on a representative hard case and produces inspectable artifacts.

---

## Related work

### Closest neighbors and how AnnotAgent relates

| Prior work | What it does | How AnnotAgent relates |
|---|---|---|
| **LabelLLM** (OpenDataLab, open source; no dedicated paper) — and other general-purpose labeling tools (Prodigy, Doccano) | Open-source human-annotation platforms with task management, multi-format ingest, per-item labeling UI, and "AI-assisted pre-annotation" where an LLM proposes and humans correct | Feature baseline AnnotAgent matches and extends. Flow A (cold-start labeling) provides the same per-item labeling surface with LLM pre-fill. On top of that surface, AnnotAgent adds three agentic capabilities these tools do not have: a `CodebookAgent` that ingests messy codebook materials into a structured editable schema; a `ReflectAgent` that runs shadow-style to learn from the user's accept/edit signal mid-session and update the pre-fill prompt; and the Flow B disputed-item review queue. LabelLLM's pre-fill is static; ours self-evolves. LabelLLM has no concept of inter-annotator agreement; we treat it as a first-class signal |
| **CrowdAgent** (EMNLP 2025 Demo) | Multi-agent system that routes fresh annotation tasks across LLMs, SLMs, and human experts under joint quality/cost management | CrowdAgent allocates *who labels what*. AnnotAgent assumes humans already labeled and focuses on resolving the disputed subset with rules mined from the agreed subset |
| **EvoAgentX** (EMNLP 2025 Demo) | Platform for evolving multi-agent workflow topology; integrates TextGrad, AFlow, MIPRO; benchmarks on HotPotQA / MBPP / MATH / GAIA | EvoAgentX evolves workflow topology on general benchmarks. AnnotAgent evolves a single annotator prompt anchored in a codebook with disagreement signal |
| **Shankar et al., UIST 2024** (*Who Validates the Validators?*, EvalGen) | Mixed-initiative tool that helps users align LLM-generated evaluators with human grades; surfaces "criteria drift" | Their LLM scores LLM outputs against user-elicited criteria. Our LLM annotates the underlying data as a third labeler when two humans disagree; it is not validating any model, and its rules are mined from human agreement |
| **Cleanlab / Confident Learning** (Northcutt et al., JAIR 2021) | Estimates joint distribution of noisy vs. true labels via model probabilities; flags suspected label errors at scale | Cleanlab flags suspected errors on items where humans agreed. AnnotAgent operates on items known to be disputed and produces a verdict with cited rules; disagreement signal is given, not inferred |
| **Dawid–Skene (1979); MACE** (Hovy et al., NAACL 2013) | EM / Bayesian crowd-aggregation models that recover ground truth from redundant labels by jointly estimating annotator competence | Dawid–Skene and MACE produce an inferred latent label from disagreement statistics. They emit no reasoning, no rule traceability, and no human re-judge. AnnotAgent's output is an LLM verdict with cited rules and a human re-judgment, turning adjudication into an auditable artifact |
| **Lapras** (Wang et al., CHI 2024 — *Human–LLM Collaborative Annotation Through Effective Verification of LLM Labels*) | LLM labels everything; a learned verifier scores LLM labels; humans re-annotate the low-confidence subset | Closest spirit-neighbor. The disagreement signal in Lapras is LLM-vs-verifier; humans enter to fix the LLM. In AnnotAgent the disagreement signal is human-vs-human; the LLM enters to break human ties. Inverse roles, different loop |
| **GEPA** (Agrawal et al., 2025), **MIPROv2** (Opsahl-Ong et al., EMNLP 2024), **OPRO** (Yang et al., ICLR 2024) | Offline batch prompt optimizers; each returns a single optimized prompt | Batch, one-shot, no cross-session artifact. ReflectAgent runs online and accumulates a rule library across sessions |
| **Ni et al., EACL 2026** (*Can Reasoning Help LLMs Capture Human Annotator Disagreement?*) | Studies whether LLMs can predict human disagreement distributions; finds RLVR-style reasoning hurts, verbalized distributions help | Orthogonal task. We cite the paper as evidence that LLM behavior on disagreement is an open problem |

### Position vs "Disagreement is signal"

A growing line of work argues that disagreement should be preserved rather than resolved: keep soft labels, train annotator-specific models, report full distributions. The premise — that disagreement often reflects genuine ambiguity rather than annotator error — is correct, and on tasks like sarcasm or toxicity we agree. AnnotAgent's contribution is for the subset of projects where downstream analysis genuinely requires a single label per item: per-class F1, downstream model training, manuscript findings. For those projects we offer an auditable alternative to silent senior-coder adjudication, not a rebuttal of the soft-label view. The methodological choice between preserving and resolving is the researcher's; the system is honest about which choice it serves.

### Existential check and an honest caveat

Across the searches we ran (LabelLLM, CrowdAgent, EvoAgentX, EvalGen, Cleanlab, Dawid–Skene / MACE, Lapras, GEPA / MIPROv2 / OPRO, Ni et al.), no published paper combines (i) LLM as third labeler trained on the human-agreed subset, (ii) cross-session rule accumulation, and (iii) a data-centric re-run loop that overlays training curves to attribute lift to label quality. Lapras is the nearest neighbor and solves the inverse problem.

Two caveats. First, the absence of a published combination is not the same as the combination being a good idea — specifically, C1's two halves are both unverified at the time of writing. If the verification spike on Fiona shows that rules from agreed items do not transfer to disputed items, or if Figure 4 shows no measurable lift after the matched-N control, the right story is "C2 stands; C1 was a useful negative result," not "the combined contribution works." Second, the multi-agent umbrella (cold-start labeling, multi-annotator workflows, gold-label optimization) overlaps with the surface of LabelLLM, Prodigy, and Doccano. What is new is the self-evolving rule library that ties the flows together, not the labeling UI itself.

---

## Limitations

C1 carries two empirical bets that must both clear for the contribution to land as a positive result. The mechanism's bet is that rules mined from the agreed subset transfer usefully to disputed items; the verification spike on Fiona's `Level` dimension tests this. The measurement's bet is that the gap between Run 1 (agreed-only) and Run 2 (full post-adjudication) is large enough to survive the matched-N control; Figure 4 itself tests this. Either failure has a publishable form: if the mechanism fails, we report rules from agreement do not transfer on this codebook; if the measurement fails, we report no data-centric lift was detectable at the scales we ran. If both fail, the section becomes "C2 stands; C1 was a useful negative result on both halves."

The flagship evaluation runs on a single dataset, so we do not claim cross-domain generalization in this paper. The system runs end-to-end on a hard codebook and produces inspectable artifacts; cross-domain claims require a separate evaluation.

C1 emits one verdict per disputed item. Codebooks where the right answer is genuinely a distribution (sarcasm, toxicity) are better served by a soft-label workflow. The scope choice is methodological, not a system limitation per se, but it matters to say out loud.

The system is designed to make adjudication cheaper, not to eliminate it. The Accept LLM button still requires a human to read the verdict and the cited rules. We have no story for fully automated adjudication, and we do not claim one.

There is no fine-tuning. Domain adaptation happens through the rule library and the prompt, not through model weights. For codebooks whose ceiling truly requires fine-tuning, AnnotAgent is the wrong tool.

---

## References

- LabelLLM (OpenDataLab). https://github.com/opendatalab/LabelLLM
- He, C. et al. (2024). *OpenDataLab: Empowering General AI with Open Datasets.* arXiv:2407.13773.
- CrowdAgent: Multi-Agent Managed Multi-Source Annotation System. EMNLP 2025 Demo. https://aclanthology.org/2025.emnlp-demos.72/
- EvoAgentX: An Automated Framework for Evolving Agentic Workflows. EMNLP 2025 Demo. https://aclanthology.org/2025.emnlp-demos.47/
- Shankar, S. et al. (2024). *Who Validates the Validators? Aligning LLM-Assisted Evaluation of LLM Outputs with Human Preferences.* UIST 2024. arXiv:2404.12272.
- Northcutt, C. et al. (2021). *Confident Learning: Estimating Uncertainty in Dataset Labels.* JAIR. arXiv:1911.00068. https://github.com/cleanlab/cleanlab
- Dawid, A. P. and Skene, A. M. (1979). *Maximum Likelihood Estimation of Observer Error-Rates Using the EM Algorithm.* Applied Statistics 28(1), 20–28.
- Hovy, D., Berg-Kirkpatrick, T., Vaswani, A., and Hovy, E. (2013). *Learning Whom to Trust with MACE.* NAACL 2013. https://aclanthology.org/N13-1132/
- Wang, X. et al. (2024). *Human–LLM Collaborative Annotation Through Effective Verification of LLM Labels* (Lapras). CHI 2024. https://dl.acm.org/doi/10.1145/3613904.3641960
- Ni, J. et al. (2025). *Can Reasoning Help LLMs Capture Human Annotator Disagreement?* arXiv:2506.19467.
- Agrawal, L. et al. (2025). *GEPA: Reflective Prompt Evolution.* arXiv:2507.19457.
- Opsahl-Ong, K. et al. (2024). *Optimizing Instructions and Demonstrations for Multi-Stage Language Model Programs* (MIPROv2). EMNLP 2024. arXiv:2406.11695.
- Yang, C. et al. (2024). *Large Language Models as Optimizers* (OPRO). ICLR
  2024. arXiv:2309.03409.
- Zheng, L. et al. (2023). *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena.* NeurIPS 2023. arXiv:2306.05685.
- Landis, J. R. and Koch, G. G. (1977). *The Measurement of Observer Agreement for Categorical Data.* Biometrics 33(1), 159–174.
- Krippendorff, K. *Content Analysis: An Introduction to Its Methodology.*
- Ng, A. (2021). *MLOps: Model-Centric to Data-Centric AI.* Talk.
- Ouyang, L. et al. (2022). *Training Language Models to Follow Instructions with Human Feedback* (InstructGPT). NeurIPS 2022.
