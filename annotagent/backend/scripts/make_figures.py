"""Generate result figures for the paper from saved experiment artifacts.

Outputs (vector PDF) into paper_draft/latex/figures/:
  - results.pdf      : per-dimension gain for each coder (bar chart).
  - improve_run.pdf  : one ReflectAgent run on Confession (Coder A) drawn from
    exp_result_fig2_confession_fiona.json: the per-round validation trajectory,
    the held-out test before/after, and the rule-library growth.

Run (from annotagent/backend): ./.venv/bin/python scripts/make_figures.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parents[3]
FIG = REPO / "paper_draft" / "latex" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
    "axes.linewidth": 0.8, "figure.dpi": 150,
})

BLUE, ORANGE, GREY = "#2b6cb0", "#c05621", "#777777"


# ---- results.pdf : per-dimension gain over zero-shot, per coder ----
fig, ax = plt.subplots(1, 1, figsize=(3.4, 2.7))
dims = ["Level", "Confession", "Depth", "Intimacy"]
coder_a = [1.9, 29.4, -2.3, 23.3]
coder_b = [14.9, 0.5, 3.1, 11.0]
x = range(len(dims)); w = 0.38
ax.bar([i - w / 2 for i in x], coder_a, w, label="Coder A", color=BLUE)
ax.bar([i + w / 2 for i in x], coder_b, w, label="Coder B", color=ORANGE)
ax.axhline(0, color="#444", lw=0.8)
ax.set_xticks(list(x)); ax.set_xticklabels(dims, rotation=20, ha="right")
ax.set_ylabel("gain over zero-shot (pp)")
ax.set_title("Gains land on different dimensions per coder", fontsize=9)
ax.legend(fontsize=7, frameon=False)
ax.grid(axis="y", lw=0.4, alpha=0.4)
fig.tight_layout()
fig.savefig(FIG / "results.pdf", bbox_inches="tight")
print(f"wrote {FIG / 'results.pdf'}")


# ---- improve_run.pdf : one reflection run, drawn from the saved artifact ----
run = json.loads((REPO / "exp_result_fig2_confession_fiona.json").read_text())
steps = [e for e in run["trajectory"]
         if e["action"] in ("baseline", "accept", "val_consolidation")]
xs = list(range(len(steps)))
val = [e["val_acc"] * 100 for e in steps]
rules = [e["n_rules"] for e in steps]
xlabels = ["base", "R1", "R2", "R3", "consol.", "R5", "R6"][:len(steps)]
t0 = run["test"]["initial_score"] * 100
t1 = run["test"]["final_score"] * 100
dpp = run["test"]["delta"] * 100

fig, ax = plt.subplots(figsize=(3.4, 2.6))
ax.plot(xs, val, "-o", color=BLUE, lw=1.6, ms=4.5, label="validation")
# the held-out test is scored once, at the start and after the final round
ax.plot([xs[0], xs[-1]], [t0, t1], "--s", color=ORANGE, lw=1.4, ms=6,
        label="held-out test")
ax.annotate(f"{t0:.1f}", (xs[0], t0), textcoords="offset points",
            xytext=(6, -11), fontsize=7.5, color=ORANGE)
ax.annotate(f"{t1:.1f}  (+{dpp:.1f}pp)", (xs[-1], t1), textcoords="offset points",
            xytext=(-6, -13), fontsize=7.5, color=ORANGE, ha="right")
# rule-library size grows along the validation curve (light labels)
for xi, vi, ri in zip(xs, val, rules):
    ax.annotate(f"{ri}", (xi, vi), textcoords="offset points", xytext=(0, 6),
                fontsize=6, color=GREY, ha="center")
ax.set_xticks(xs); ax.set_xticklabels(xlabels)
ax.set_xlabel("optimization round  (grey = rules learned)")
ax.set_ylabel("accuracy (%)")
ax.set_ylim(44, 88)
ax.legend(fontsize=7, frameon=False, loc="upper left")
ax.grid(axis="y", lw=0.4, alpha=0.4)
fig.tight_layout()
fig.savefig(FIG / "improve_run.pdf", bbox_inches="tight")
print(f"wrote {FIG / 'improve_run.pdf'}")
