# Summary of all results

Model `gpt-5.4-mini` throughout; optimizer `reflect_agent`, budget 5. Per-run
detail (per-seed, trajectories, predictions, rules, cost) in the sections below
and the `exp_result_*.json` sidecars.

## A. Per-coder alignment, self-disclosure (multi-seed k=3, accuracy %, mean ± std)

| Dimension | Fiona ZS | Fiona +RA | Fiona Δ | Chang ZS | Chang +RA | Chang Δ |
|---|---|---|---|---|---|---|
| Level of disclosure | 68.1 ± 2.7 | 70.0 ± 1.7 | +1.9 | 61.7 ± 0.6 | 76.6 ± 5.1 | **+14.9** |
| Disclosure as confession | 52.6 ± 1.2 | 82.0 ± 8.7 | **+29.4** | 49.6 ± 3.8 | 50.1 ± 1.9 | +0.5 |
| Depth of disclosure | 61.0 ± 6.6 | 58.7 ± 2.4 | -2.3 | 58.2 ± 2.5 | 61.2 ± 7.2 | +3.1 |
| Intimacy of self-disclosure | 52.2 ± 3.2 | 75.5 ± 3.1 | **+23.3** | 54.9 ± 2.5 | 66.0 ± 3.5 | **+11.0** |
| **mean** | **58.5** | **71.5** | **+13.1** | **56.1** | **63.5** | **+7.4** |

Gains concentrate on different dimensions per coder (Fiona: Confession, Intimacy; Chang: Level, Intimacy).

## B. Multi-label alignment, AI behavior (micro-F1 %)

| Theme | #labels | Fiona ZS | Fiona +RA | Chang ZS | Chang +RA |
|---|---|---|---|---|---|
| Listening strategy (k=3) | 7 | 71.6 ± 4.5 | 73.2 ± 4.0 | 61.3 ± 3.4 | **68.8 ± 4.7** |
| Support type (k=1, Fiona only) | 2 | 80.6 | **92.1** | n/a | n/a |
| Interaction | 1 | n/a (1-label) | n/a | n/a | n/a |

Listening strategy delta: Chang **+7.4pp robust** (per-seed +7.6 / +9.1 / +5.7);
Fiona **+1.6pp within noise** (per-seed +7.7 / -4.9 / +1.8 — the single seed was
optimistic, multi-seed corrected it). Support type: Fiona only, single seed.
Interaction: 1 label, degenerate. Per-seed artifacts: `exp_result_ai_behavior_{fiona,chang}{,_s1,_s2}.json`.

## C. Cross-target specificity (is the alignment coder-specific?)

Semantic disagreement -> rules. **Intimacy** (k=3, mean accuracy % over 3 seeds, shared test n=35):

| Intimacy | vs Fiona labels | vs Chang labels |
|---|---|---|
| Fiona-tuned prompt | **75.2** | 41.0 |
| Chang-tuned prompt | 51.4 | **71.4** |

Diagonal advantage (mean ± std over 3 seeds): Fiona **+23.8 ± 7.5pp** (per-seed
34.3/20.0/17.1), Chang **+30.5 ± 10.8pp** (per-seed 45.7/22.9/22.9). The off-diagonal
never wins; coder-specificity survives multi-seeding. Sidecars:
`exp_result_specificity_intimacy{,_s1,_s2}.json`.

Base-rate disagreement -> calibration threshold. **Confession** (5 splits): learned
thresholds Fiona 0.95 / Chang 0.42 track base rates (20% / 52%); specificity Fiona
+21.7 ± 14.1pp, Chang -1.4 ± 1.4pp.

---

# Per-user alignment evaluation

Codebook: Self-Disclosure Analysis | model: `gpt-5.4-mini` (openai) | optimizer: `reflect_agent` (budget 5) | same defaults as the Improve tab.

Split: train 15% / val 42% / test 43%, stratified by gold class, seed from `(user, dimension)`. Test held out from the optimizer and scored once.

Generated 2026-06-22 17:41.

## Target: fiona

Agreement = accuracy against this annotator's own held-out labels.

| Dimension | n | train/val/test | Zero-shot agree | +ReflectAgent agree | Delta pp | ZS macro-F1 | +RA macro-F1 | rules |
|---|---|---|---|---|---|---|---|---|
| Level of disclosure | 323 | 48/136/139 | 69.1% | 69.1% | +0.0 | 0.581 | 0.598 | 15 |
| Disclosure as confession | 316 | 48/133/135 | 51.9% | 77.0% | +25.2 | 0.482 | 0.686 | 27 |
| Depth of disclosure | 166 | 25/70/71 | 63.4% | 59.2% | -4.2 | 0.569 | 0.549 | 9 |
| Intimacy of self-disclosure | 124 | 19/52/53 | 54.7% | 77.4% | +22.6 | 0.525 | 0.643 | 14 |
| **mean** | | | **59.8%** | **70.7%** | **+10.9** | | | |

Class distribution: Level of disclosure (High: 116, Low: 165, No: 42); Disclosure as confession (No, it's not a confession: 271, Yes, it's a confession: 45); Depth of disclosure (Central: 102, Intermediate: 59, Peripheral: 5); Intimacy of self-disclosure (Core: 29, Intermediate: 92, Peripheral: 3)

### Multi-seed (k=3), Fiona

Three split seeds (SHA-256 of `user|dim|k`), same budget 5 and split 0.15/0.42.
Mean ± std over seeds; raw per-seed numbers in `exp_result_multiseed.md`.

| Dimension | Zero-shot (mean ± std) | +ReflectAgent (mean ± std) | Delta pp |
|---|---|---|---|
| Level of disclosure | 68.1 ± 2.7 | 70.0 ± 1.7 | +1.9 |
| Disclosure as confession | 52.6 ± 1.2 | **82.0 ± 8.7** | **+29.4** |
| Depth of disclosure | 61.0 ± 6.6 | 58.7 ± 2.4 | -2.3 |
| Intimacy of self-disclosure | 52.2 ± 3.2 | **75.5 ± 3.1** | **+23.3** |
| **mean** | **58.5** | **71.5** | **+13.1** |

The gains concentrate on the subjective dimensions (Confession +29.4, Intimacy
+23.3); Level and Depth are flat within noise. The multi-seed mean (+13.1pp)
is consistent with and slightly above the single-seed +10.9pp above.

## Target: chang

Agreement = accuracy against this annotator's own held-out labels.

| Dimension | n | train/val/test | Zero-shot agree | +ReflectAgent agree | Delta pp | ZS macro-F1 | +RA macro-F1 | rules |
|---|---|---|---|---|---|---|---|---|
| Level of disclosure | 330 | 50/139/141 | 64.5% | 84.4% | +19.9 | 0.659 | 0.858 | 14 |
| Disclosure as confession | 329 | 49/139/141 | 46.8% | 53.2% | +6.4 | 0.457 | 0.529 | 21 |
| Depth of disclosure | 330 | 50/139/141 | 63.1% | 66.0% | +2.8 | 0.581 | 0.609 | 23 |
| Intimacy of self-disclosure | 330 | 49/139/142 | 57.0% | 69.0% | +12.0 | 0.532 | 0.611 | 16 |
| **mean** | | | **57.9%** | **68.1%** | **+10.3** | | | |

Class distribution: Level of disclosure (High: 185, Low: 145); Disclosure as confession (No, it's not a confession: 156, Yes, it's a confession: 173); Depth of disclosure (Central: 187, Intermediate: 64, Peripheral: 79); Intimacy of self-disclosure (Core: 190, Intermediate: 61, Peripheral: 79)

### Multi-seed (k=3), Chang

Three split seeds, budget 5, split 0.15/0.42. Trajectories saved in
`exp_result_multiseed_chang_trajectories.json`.

| Dimension | Zero-shot (mean ± std) | +ReflectAgent (mean ± std) | Delta pp |
|---|---|---|---|
| Level of disclosure | 61.7 ± 0.6 | **76.6 ± 5.1** | **+14.9** |
| Disclosure as confession | 49.6 ± 3.8 | 50.1 ± 1.9 | +0.5 |
| Depth of disclosure | 58.2 ± 2.5 | 61.2 ± 7.2 | +3.1 |
| Intimacy of self-disclosure | 54.9 ± 2.5 | **66.0 ± 3.5** | **+11.0** |
| **mean** | **56.1** | **63.5** | **+7.4** |

Cross-coder contrast: the loop's gains land on **different dimensions per coder**
(Fiona: Confession +29.4, Intimacy +23.3; Chang: Level +14.9, Intimacy +11.0),
consistent with aligning to each coder's own standard rather than a shared one.

Run tokens: 13,002,568 (exact, from the API). NOTE: the tool's dollar figure
($33.85) is an OVER-ESTIMATE. Cost is not from OpenAI billing; it is tokens x a
hardcoded price table (`app/utils/cost_tracker.py`) that prices `gpt-5.4-mini` at
gpt-4o rates ($2.50/$10 per 1M). Actual OpenAI console spend is ~3x lower. Trust
the token count, not the dollar estimate, until the price table is corrected.
Reproduce: `./.venv/bin/python scripts/run_per_user_eval.py --user fiona,chang --train-frac 0.15 --val-frac 0.42 --budget 5` (from annotagent/backend).

---

# Multi-label alignment (AI Behavior)

Separate pipe for multi-label dimensions: the model predicts a **set** of labels
per item, scored with set-based precision / recall / F1 (`compute_metrics_multilabel`).
Optimizer is config **B** (set-F1 Governor, rules mined from set errors: missed
label = recall error, extra label = precision error). Full artifact (prompts,
rules, per-round trajectory, every test prediction): `exp_result_ai_behavior_fiona.json`.

## Target: fiona, Listening strategy (multi-label, config B)

Split: train 116 / val 87 / test 88 items, seed from `(user, dimension)`, budget 5.

| Condition | micro-P | micro-R | micro-F1 | macro-F1 | exact-match |
|---|---|---|---|---|---|
| Zero-shot | 0.578 | 0.756 | 0.655 | 0.308 | 0.330 |
| + ReflectAgent (B) | 0.646 | 0.846 | **0.732** | 0.313 | **0.409** |
| Delta | +0.068 | +0.090 | **+0.077** | +0.005 | +0.079 |

Config B lifts micro precision, recall, F1, and exact-match on real-sized test
(n=88). macro-F1 is flat because the rare labels carry almost no support.

### Per-label F1 (test, sorted by support)

| Label | support | ZS P | ZS R | ZS F1 | B P | B R | B F1 |
|---|---|---|---|---|---|---|---|
| Question-asking | 61 | 0.97 | 0.92 | 0.94 | 0.95 | 0.95 | 0.95 |
| Offers advice, opinions, perspectives, … | 36 | 0.58 | 0.58 | 0.58 | 0.48 | 0.97 | 0.64 |
| Sympathetic responsiveness | 19 | 0.34 | 0.79 | 0.48 | 0.61 | 0.58 | 0.59 |
| Paraphrase | 7 | 0.17 | 0.14 | 0.15 | 0.00 | 0.00 | 0.00 |
| Back-channel response | 0 | n/a | n/a | n/a | n/a | n/a | n/a |
| Humor | 0 | n/a | n/a | n/a | n/a | n/a | n/a |
| Perspective-taking | 0 | n/a | n/a | n/a | n/a | n/a | n/a |

The micro lift comes from "Offers advice" (recall 0.58 → 0.97) and "Sympathetic
responsiveness" (precision 0.34 → 0.61). "Paraphrase" (support 7) drops to 0 under
B's stricter rule, which is why macro-F1 stays flat.

### Validation trajectory (set macro-F1 per round)

| round | val macro-F1 | action |
|---|---|---|
| 0 | 0.355 | baseline |
| 1 | 0.483 | accept (kept rules) |
| 2 | 0.389 | rollback |
| 3 | 0.461 | rollback |
| 4 | 0.452 | rollback |
| 5 | 0.438 | rollback |

### Rules learned by B

1. Label "Offers advice, opinions, perspectives, and personal experience" when the reply gives an opinion, reflection, explanation, suggestion, or emotional/experiential statement; do not require it to be explicitly framed as advice.
2. Use "Paraphrase" only for a clear restatement or summary of the other person's content; do not tag it for general reflection, supportive interpretation, or elaboration.
3. Use "Perspective-taking" and "Sympathetic responsiveness" only when the message explicitly shows understanding of the other person's feelings or viewpoint; do not infer them from warm or affectionate tone alone.
4. If a sentence includes a question, keep "Question-asking" even when it also contains supportive or advisory content; do not add extra labels unless their cues are explicit.

Reproduce: `./.venv/bin/python scripts/multilabel_diag.py --user fiona --dim "Listening strategy" --limit 0 --budget 5 --skip-a --out exp_result_ai_behavior_fiona.json` (from annotagent/backend).

## Target: chang, Listening strategy (multi-label, config B)

Split: train 92 / val 69 / test 70 items, budget 5, 16 rules. Artifact: `exp_result_ai_behavior_chang.json`.

| Condition | micro-P | micro-R | micro-F1 | macro-F1 | exact-match |
|---|---|---|---|---|---|
| Zero-shot | 0.588 | 0.698 | 0.638 | 0.331 | 0.386 |
| + ReflectAgent (B) | 0.650 | 0.792 | **0.714** | **0.460** | 0.400 |
| Delta | +0.062 | +0.094 | **+0.076** | **+0.129** | +0.014 |

Val trajectory (set macro-F1): 0.429 -> 0.516 over 5 rounds (4 accepts, 1 rollback).
Both coders show the same ~+0.076 micro-F1 lift from config B; Chang also gains
+0.129 macro-F1 (Fiona's macro was flat due to rare zero-support labels).

Reproduce: `./.venv/bin/python scripts/multilabel_diag.py --user chang --dim "Listening strategy" --limit 0 --budget 5 --skip-a --out exp_result_ai_behavior_chang.json` (from annotagent/backend).

---

# Cross-target specificity (is alignment coder-specific?)

Design: on items both coders labeled, hold out a shared test set, build a profile
per coder, score every profile against every coder's labels. Personalization
holds if diagonal (own coder) > off-diagonal.

## Semantic disagreement -> rules (Intimacy, raw agreement 34.8%)
`exp_result_specificity_intimacy.json`, shared test n=35:

| Intimacy (rules) | vs Fiona | vs Chang |
|---|---|---|
| Fiona-tuned prompt | **88.6** | 31.4 |
| Chang-tuned prompt | 54.3 | **77.1** |

Diagonal advantage: Fiona +34.3pp, Chang +45.7pp. Rule-tuning is strongly
coder-specific where coders disagree on label semantics. (single seed; multi-seed pending)

## Base-rate disagreement -> calibration threshold (Confession)
`exp_result_calibration.json`, shared n=166, 5 calibration splits. Fiona Yes-rate
20%, Chang 52%. Rule-tuning alone is NOT coder-specific here (null). A learned
per-coder decision threshold on a continuous confession score recovers it:

- Learned thresholds track base rates: Fiona 0.95, Chang 0.42.
- Specificity (own minus other): Fiona +21.7 +/- 14.1 pp; Chang -1.4 +/- 1.4 pp.
- Pooled diagonal advantage: +10.1 +/- 15.3 pp.

Takeaway: separating codebook clarification (rules, for semantic disagreement)
from coder calibration (thresholds, for base-rate disagreement) makes the
alignment coder-specific rather than generic.

---

# Figure 2 (Improve-page screenshot) run

The Improve-page screenshot in the paper is a real run: ReflectAgent on
"Disclosure as confession", gold = coder Fiona, budget 5. Held-out test rises
49.6% -> 62.2% (+12.6pp, n=135, leakage-guarded); 19 rules learned; 1,030,520 tokens (exact). The ~$2.71 figure is the tool's over-estimate at gpt-4o rates; actual cost is ~3x lower.
Full artifact (held-out test scores, splits, audit, rule library, trajectory):
`exp_result_fig2_confession_fiona.json`.

---

# GEPA baseline — implementation + smoke test (wiring only, not a result yet)

Status: the GEPA baseline optimizer is implemented and verified to run end-to-end.
This is a plumbing smoke test on a tiny subset; the real per-coder baseline numbers
for Table 1 are still TODO (run on the same train/val/test splits as ReflectAgent).

## Design decisions (chosen 2026-06-29)

- **Fair seed.** GEPA starts from the *same* initial per-dimension prompt ReflectAgent
  starts from, not a generic stub. (`make_classifier_module(..., initial_prompt=...)`
  in `app/optimizers/_dspy_shim.py`; MIPROv2 seeded the same way for parity.)
- **Feedback metric.** GEPA optimizes a `{score, feedback}` metric (`feedback_metric`,
  returns `dspy.Prediction(score, feedback)`), giving the reflective loop its intended
  signal rather than a scalar-only strawman. Score is identical to exact-match accuracy
  so it is comparable to ReflectAgent's.
- **reflection_lm = same model** (`gpt-5.4-mini`), for a controlled, single-model comparison.
- **Budget** `auto="light"` (DSPy's ~6-candidate budget).

Code: `app/optimizers/gepa.py` (thin `dspy.GEPA` wrapper, dspy 3.2.1), `_dspy_shim.py`.
Verified against the official DSPy GEPA API (overview + advanced docs) and the installed
`dspy.GEPA` signature.

## Smoke setup

- Dimension `Level of disclosure` (labels No / Low / High), data from
  `annotagent/seed/self_disclosure_demo.json`, split **6 train / 4 val**.
- Model `gpt-5.4-mini`, `auto="light"`.
- Script `annotagent/backend/scripts/smoke_gepa.py`; sidecar
  `scripts/smoke_gepa_result.json`; full log `scripts/smoke_gepa.log`.

## What the smoke test confirmed

GEPA ran the real reflective Genetic-Pareto loop (budget ~396 metric calls / 39.6 full
evals on train+val): it scored the seeded base program at val **0.75**, then across
iterations **proposed multiple new candidate instructions** (e.g. a reformatted
label-definition prompt), full-evaluated them, and maintained a Pareto front. No
candidate beat the seed on the 4-example valset, so GEPA correctly **returned the seed
program (index 0) as best** at 0.75. This is genuine GEPA behavior, not the
exception-fallback path (no compile error in the log).

| Field | Value |
|---|---|
| optimizer | gepa |
| dimension | Level of disclosure |
| base/initial val score | 0.75 |
| GEPA best valset score (internal) | 0.75 (seed kept; no candidate beat it on n=4) |
| final re-eval (harness) | 0.50 |
| harness eval tokens | 892 (the 8 baseline+final scoring calls only; GEPA-internal dspy calls not counted) |
| n_train / n_val | 6 / 4 |
| result | end-to-end PASS |

Caveats (why this is not a number to cite):
- **n_val = 4** is far too small to be meaningful. The `0.75 -> 0.50` final-eval drop is
  sampling noise (one of four items flipped at temperature > 0 when the harness re-scored
  the *same* prompt); GEPA's internal valset score for that prompt was a stable 0.75.
- Token/cost accounting only covers the shared eval harness; GEPA's internal reflection
  and candidate-eval calls go through `dspy.LM` and are not yet captured. Capture full
  `dspy`/litellm usage before reporting GEPA cost.

## First real run: Level of disclosure (Fiona, seed 0)

Same split as the ReflectAgent table (production `_stratified_split`,
seed = SHA-256(`fiona|Level of disclosure|0`)): n=323, train 48 / val 136 / test 139.
Both task and reflection LM = `gpt-5.4-mini`; GEPA `auto="light"`, 16 threads;
`EXPERIMENTAL_OPENAI_API_KEY`. Driver `scripts/run_gepa_baseline.py`, sidecar
`scripts/gepa_baseline_result.json`, log `scripts/gepa_baseline.log`.

| Metric | Zero-shot | GEPA | Δ |
|---|---|---|---|
| Test agreement (acc) | 69.1% | **75.5%** | **+6.5pp** |
| Test macro-F1 | 0.599 | 0.674 | +0.075 |
| Val (GEPA internal) | 0.654 | 0.699 | +0.045 |

- **Time:** 154.5s total at 16 threads (zero-shot eval 9.7s, GEPA optimize 134.1s,
  test eval 8.8s). GEPA evolved the prompt (`prompt_changed=true`).
- **Budget reality:** DSPy `light` issued **~924 metric calls (5.02 full evals on
  train+val)**, not the ~7,300 pre-estimate. Auto-light caps full-evals as the valset
  grows, so cost scales far more slowly than linear-in-n. Tokens ≈ 1.27M+ (196k eval
  harness + ~1.07M task-LM internal; reflection-LM calls are extra and not captured).

**Honest read (matters for the paper framing).** On *this* dimension and seed, GEPA
(75.5%, +6.5pp) **beats** the ReflectAgent table mean for the same cell
(Level of disclosure, Fiona: +RA 70.0%, +1.9pp). Caveats: this is a single seed vs a
3-seed mean, and the zero-shot here (69.1) is the seed-0 baseline, slightly above the
3-seed ZS mean (68.1). Importantly, **Level was ReflectAgent's weakest Fiona dimension**
(+1.9pp, its smallest gain), so GEPA winning here is consistent with the paper's actual
claim. The paper does NOT argue ReflectAgent beats GEPA on raw accuracy everywhere; it
argues comparable accuracy plus inspectable rules, cross-session memory, and per-coder
calibration. This result is evidence the comparison is being run honestly, and it says
the strong rows for the ReflectAgent story are the high-gain dimensions (Confession,
Intimacy) and the base-rate calibration on Confession, not Level.

For a clean same-seed comparison, run ReflectAgent on seed 0 too (cheap, budget 5) so the
table reports GEPA vs ReflectAgent on the identical split rather than GEPA-seed0 vs
ReflectAgent-3seed-mean.

### Prompt audit: memorization vs leakage

The 784-word optimized prompt is ~95% abstracted rules (High/Low/No definitions, a
decision checklist), but GEPA embedded **3 verbatim train sentences** as in-prompt
examples (2 under "Examples that should be High", 1 as a Low boundary case). Audit on the
same split:

| Split | Verbatim sentences (>=25 chars) embedded in the prompt |
|---|---|
| train (48) | **3** |
| val (136) | 0 |
| test (139) | 0 |

Production leakage auditor (`audit_prompt_for_leakage`): `val_leak_count=0,
test_leak_count=0, clean=True`.

- **No leakage.** All embedded sentences are from train; none from val/test. The held-out
  test (75.5%) is honest, not inflated by memorized test items.
- **Light overfitting to train**, not example-stuffing: ~5% of the prompt is verbatim
  train quotes. GEPA quotes its training failures into the instruction because it has no
  constraint against it.
- **Differentiator, demonstrable from this run:** GEPA memorizes raw train instances into
  the prompt; ReflectAgent's PatternExtractor is forbidden from quoting full failure
  sentences verbatim and must abstract them into rules. "Memorized instances vs abstracted
  rules" is now showable side by side, not just asserted.

## All four single-label dims (Fiona, seed 0)

Same setup for every dim (production `_stratified_split`, seed = SHA-256(`fiona|<dim>|0`),
both LMs `gpt-5.4-mini`, GEPA `auto="light"`, 16 threads, EXPERIMENTAL key). Per-dim
sidecars `scripts/gepa_<dim>.json`; log `scripts/gepa_3dims.log`. Each run ~130-167s.

| Dimension | ZS (seed 0) | GEPA (seed 0) | Δ pp | ZS->GEPA macro-F1 | train sents memorized | test leak |
|---|---|---|---|---|---|---|
| Level of disclosure | 69.1 | 75.5 | +6.5 | 0.599 -> 0.674 | 3 | none |
| Disclosure as confession | 55.6 | 79.3 | +23.7 | 0.515 -> 0.707 | 3 | none |
| Depth of disclosure | 66.2 | 69.0 | +2.8 | 0.584 -> 0.670 | 1 | none |
| Intimacy of self-disclosure | 56.6 | 81.1 | +24.5 | 0.543 -> 0.656 | 0 | none |
| **mean** | **61.9** | **76.2** | **+14.4** | | | |

Audit (verbatim sentences >=25 chars embedded in each prompt, same split): **0 test and
0 val leakage on all four**; train memorization 3/3/1/0. All four GEPA numbers are honest.
Intimacy's +24.5 came entirely from abstracted rules (0 memorized sentences).

### Caveat: do NOT read this as GEPA vs ReflectAgent

GEPA's **zero-shot** on seed 0 is higher than the ReflectAgent table's 3-seed-mean
zero-shot on every dimension (69.1>68.1, 55.6>52.6, 66.2>61.0, 56.6>52.2). The zero-shot
uses the identical initial prompt, so the difference is purely the split: **seed 0's test
set is easier than the 3-seed average.** Comparing GEPA-seed0 (mean 76.2) to the
ReflectAgent 3-seed mean (71.5) is therefore confounded and invalid. The only honest
cross-method statement right now is *within* seed 0: GEPA lifts zero-shot by +14.4pp mean,
cleanly and without leakage.

To compare the two methods, run **ReflectAgent on seed 0** for these four dims (cheap,
budget 5) so it is GEPA-seed0 vs RA-seed0 on the identical splits. Until then, GEPA is
established only as a strong, clean baseline that improves over zero-shot.

## MIPROv2 and OPRO baselines (Fiona, seed 0)

Same pipeline and splits as GEPA (production `_stratified_split`, seed = SHA-256(`fiona|<dim>|0`)),
both task and optimizer LM = `gpt-5.4-mini`, EXPERIMENTAL key, 16 threads. Driver
`scripts/run_optimizer_baseline.py`; per-dim sidecars `scripts/opt_<optimizer>_<dim>.json`.

Implementation notes (this run):
- **MIPROv2 needed `optuna`** (its Bayesian search backend); installed and added to
  `requirements.txt`. Without it, `compile()` throws and silently falls back to the initial
  prompt, so the earlier stub would have reported no-ops.
- **MIPRO demos now reach the eval.** MIPRO jointly optimizes instruction + few-shot demos;
  the old code extracted only the instruction and dropped the demos, under-powering it. Added
  `extract_prompt_with_demos` so the 4 bootstrapped demos are appended to the evaluated prompt
  in the harness's `Sentence: / Answer:` format. Also pass `requires_permission_to_run=False`
  (else `compile()` blocks on an interactive prompt) and `num_threads`.
- **OPRO** was already correct and fair (seeds the trajectory with the same initial prompt,
  keeps the best val candidate, no demos, cannot memorize data since its meta-prompt only sees
  prior prompts + scores).
- One MIPRO run (Depth) hung ~8h on an untimed LLM call in its instruction-proposal step; the
  sweep recovered on its own. Future sweeps wrap each run in `timeout` as a guard.

### Test accuracy, all optimizers (Fiona, seed 0, held-out test, scored once)

| Dimension | GEPA | MIPROv2 | OPRO | RA (3-seed mean) |
|---|---|---|---|---|
| Level of disclosure | 75.5 | 75.5 | 77.0 | 70.0 |
| Disclosure as confession | 79.3 | **90.4** | 56.3 (no gain) | 82.0 |
| Depth of disclosure | 69.0 | 69.0 | 67.6 (no gain) | 58.7 |
| Intimacy of self-disclosure | 81.1 | 73.6 | 62.3 | 75.5 |
| **mean** | **76.2** | **77.1** | **65.8** | **71.5** |

Per-optimizer lift over its own re-measured zero-shot (mean): GEPA +14.4, MIPRO +14.2,
OPRO +4.2. OPRO proposed 8 candidates/round but all scored below baseline on val for
Confession and Depth, so it kept the initial prompt (honest no-improvement, not an error).

### Leakage / memorization audit (verbatim sentences in each optimized prompt)

**Zero val or test leakage in all 8 runs.** Train memorization: MIPRO embeds its 4 few-shot
demos per dim (that is what few-shot is); GEPA 0-3 sentences; OPRO 0 (never sees data). So
every number is honest, but note MIPRO's prompt, like GEPA's, contains raw training instances;
only ReflectAgent's output is abstracted, editable rules.

### Honest read (matters for the paper)

- **On raw accuracy, the prompt optimizers are competitive with or stronger than ReflectAgent.**
  MIPRO (77.1) and GEPA (76.2) both exceed the RA 3-seed mean (71.5) on seed 0; only OPRO (65.8)
  is clearly weaker, and inconsistently so. Do not claim an accuracy win over these baselines.
- **Same seed-0 confound as before:** every optimizer's re-measured zero-shot on seed 0 is above
  RA's 3-seed-mean zero-shot, so seed 0's test is simply easier. GEPA/MIPRO/OPRO-seed0 vs
  RA-3seed-mean is not a valid comparison. Also, per-run zero-shot varies ~±2-3pp from eval
  sampling (temperature), so single-run deltas carry noise.
- **Confession is not a clean ReflectAgent win on Fiona:** MIPRO hit 90.4 with demos, above RA's
  82.0. The per-coder base-rate calibration advantage must be demonstrated on **Chang** (the
  conservative coder), where rule-tuning alone was not coder-specific, not on Fiona.
- **The durable differentiator survives all three:** GEPA, MIPRO, and OPRO all output an opaque
  prompt (MIPRO and GEPA with memorized train instances inside it). None produce inspectable,
  editable, versioned rules, cross-session memory, or a per-coder decision threshold. That is
  where the ReflectAgent / system story must live, not on the accuracy number.

## k=3 optimizer baselines (Fiona, seeds 0/1/2) — the clean comparison

Every optimizer now ran on **the same 3 split seeds as the ReflectAgent table**
(seed = SHA-256(`fiona|<dim>|k`), k=0,1,2, train 0.15 / val 0.42), so the seed-0
"easy split" confound is gone: this averages over identical splits. Driver
`scripts/run_optimizer_baseline.py`; aggregation `scripts/aggregate_k3.py` →
`scripts/k3_aggregate.json`; per-run sidecars `scripts/opt_<opt>_<dim>_s{0,1,2}.json`.
All 24 seed-1/2 runs completed (0 failures, 0 timeouts).

Test accuracy, mean ± std over 3 seeds:

| Dimension | GEPA | MIPROv2 | OPRO | ReflectAgent (k=3) |
|---|---|---|---|---|
| Level of disclosure | 74.8 ± 1.6 | 72.2 ± 3.0 | 72.4 ± 4.6 | 70.0 ± 1.7 |
| Disclosure as confession | 77.8 ± 5.5 | 85.2 ± 7.3 | 52.6 ± 2.6 | 82.0 ± 8.7 |
| Depth of disclosure | 64.8 ± 3.4 | 62.0 ± 5.0 | 58.7 ± 6.3 | 58.7 ± 2.4 |
| Intimacy of self-disclosure | 78.0 ± 2.4 | 76.1 ± 3.6 | 62.3 ± 4.6 | 75.5 ± 3.1 |
| **mean** | **73.8** | **73.9** | **61.5** | **71.5** |

Leakage/memorization: **0 val and 0 test leakage across all 36 runs** (12 seed-0 + 24
seed-1/2). MIPRO embeds its 4 few-shot demos per prompt; GEPA quotes 0-3 train sentences;
OPRO 0. Only ReflectAgent's output is abstracted, editable rules rather than a prompt
carrying raw train instances.

### Honest read (k=3, seed-confound resolved)

- **GEPA (73.8) and MIPROv2 (73.9) are statistically on par with ReflectAgent (71.5)** on
  raw accuracy; the error bars overlap on essentially every dimension. There is **no
  accuracy win for ReflectAgent, and no decisive loss either** — it is a wash on the number.
- **OPRO (61.5) is clearly the weakest**, dragged down by Confession, where its
  trajectory-conditioned proposals never beat the baseline (52.6, no gain), and by high
  variance elsewhere.
- **Confession is not a ReflectAgent win on Fiona**: MIPRO 85.2 vs RA 82.0 (overlapping),
  GEPA 77.8. The per-coder base-rate calibration advantage must be shown on **Chang** (the
  conservative coder), where rules alone were not coder-specific — not on Fiona.
- **Depth**: GEPA (64.8) and MIPRO (62.0) beat RA (58.7); this was RA's weak dim.
- Net: over identical seeds, the strong prompt optimizers match ReflectAgent on accuracy.
  The paper cannot lead with an accuracy claim; it must lead with what the optimizers
  structurally do not produce — inspectable/editable rules, cross-session memory, and the
  per-coder decision threshold.

## Next step (the actual baseline)

1. Run **ReflectAgent k=3 on Chang** and compute the same table; Chang/Confession is the
   one place the calibration threshold should give ReflectAgent a real accuracy edge that
   the prompt optimizers cannot reach.
2. Put GEPA/MIPRO (and optionally OPRO) into Table 1 of `acl_latex.tex` as baseline rows,
   reporting them as comparable-on-accuracy, and reframe the contribution around
   interpretability + memory + calibration (per the GEPA-vs-ReflectAgent discussion).
3. Optionally add the leakage/memorization contrast (optimizers embed raw train instances;
   ReflectAgent abstracts rules) as a small qualitative figure or column.
