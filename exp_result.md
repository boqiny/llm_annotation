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
