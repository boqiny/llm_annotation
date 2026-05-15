A horizontal, two-tier figure for the paper. Sized for two-column width (~17 cm) at a reasonable height (~9–10 cm). One figure, no legend, no badge boxes, no callout numbers. Reviewer-friendly: the top tier is scannable in five seconds; the bottom tier zooms in on the labeling stage where the contributions live.

This file describes one figure. Other paper figures (the overlay curve at full size for the eval section, the Disagreement Review screenshot) live elsewhere.

---

## Overall layout

Two stacked horizontal strips of roughly equal height, separated by a thin hairline rule.

**Top tier — pipeline overview.** A single left-to-right row of five boxes, connected by arrows. Reads as: what the user brings → builds a codebook → drafts prompts → labels data → keeps improving. The fourth box ("Labeling") carries a small downward triangle indicating that the bottom tier zooms in on it.

**Bottom tier — labeling stage zoom-in.** Three vertical columns side by side, each showing one of the three labeling paths. The columns are not equal in width: the middle column (Flow B / C1 proposed) takes about 45% of the strip because it carries both halves of the merged C1 contribution (mechanism plus measurement); the left and right columns take about 27% each. Faint vertical rules separate the three columns.

A small downward triangle on the top-tier "Labeling" box visually anchors the reader to the bottom-tier zoom.

---

## Visual conventions

Two shape types and three edge types.

Shapes. Agents render as rounded rectangles. Data and artifacts render as sharp rectangles. User actions render as pills with rounded ends.

Edges. Solid arrows for data flow. Dashed arrows for shadow / reference / asynchronous links. Curved arrows for backward seeds (the Memory seed loop, the cold-start shadow loop).

Color. One muted palette throughout. Slate text on near-white fill for nodes; neutral gray hairlines; one accent color (deep teal) reserved for the primary path arrows; a single warm tint (pale amber) applied only to the middle column of the bottom tier to mark the proposed C1 contribution. No other color tinting anywhere in the figure.

Text density. Each node carries at most five words of title plus an optional one-line italic sub-line. Stage titles use sentence case in bold.

Typography. Sans-serif throughout. Node titles semibold; sub-text and edge labels in italic at a slightly lighter weight. No 3D, no gradients, no drop shadows.

---

## Top tier — pipeline overview

Five horizontal boxes, equally sized, left to right. Arrows between adjacent boxes are short and labeled with the artifact that flows.

**Box 1 — User inputs.** A pill stack inside the box showing four small horizontal pills (one above the next) with the four possible starting positions:

- "An idea"
- "Raw data"
- "Codebook materials"
- "Annotator files (N ≥ 2)"

A small italic sub-line below the stack reads "any combination, not exclusive."

Arrow out → labeled "user inputs."

**Box 2 — CodebookAgent.** Rounded rectangle. Internal text: "CodebookAgent" (semibold) with italic sub-line "Ingestor · Drafter · Critic." A tiny inner annotation "draft-from-description supported" indicates the no-codebook starting case is handled.

Arrow out → labeled "CodebookDef."

**Box 3 — AutoPromptGenerator.** Rounded rectangle. Internal text: "AutoPromptGenerator" (semibold) with italic sub-line "one prompt per dimension, in parallel."

Arrow out → labeled "starting prompts."

**Box 4 — Labeling.** Rounded rectangle, drawn slightly taller than the others. Internal text: "Labeling" (semibold) with italic sub-line "three paths · see zoom-in below." A small downward triangle sits on the bottom edge of this box pointing into the bottom tier.

Arrow out → labeled "labeled data + Rule Library."

**Box 5 — ReflectAgent + Memory.** Rounded rectangle. Internal text: "ReflectAgent + Memory" (semibold) with italic sub-line "failure mining · cross-session rule library." A small curved arrow drawn inside the box loops back on itself, indicating the per-round optimization loop. A second, longer curved arrow exits the right side of the box, loops below the entire top tier, and re-enters at Box 3 (AutoPromptGenerator), labeled in italic "next session seeds from latest version."

---

## Bottom tier — labeling stage zoom-in

The downward triangle from Box 4 connects to a thin horizontal title strip at the top of the bottom tier: "Labeling — the user picks the path that matches what they have." Below the strip, three columns sit side by side. Each column has a small column header (semibold) and runs top-to-bottom with short arrows between nodes.

### Column A — Cold start (left, narrow column)

Column header: "A · Cold start" with italic sub-line "no labels yet."

Top: user pill "Upload raw data."

Below the pill: rounded rectangle "Annotator (interactive)" with italic sub-line "per-item pre-fill with reasoning."

Below: user pill "Accept · Edit · Reject."

Below: sharp rectangle "Committed labels (n = …)."

A dashed curved arrow leaves the Committed-labels box, loops up and to the left, and re-enters the Annotator box, labeled in italic "shadow ReflectAgent · pre-fill improved (rev N)." This is the only dashed loop in the column.

Bottom of column: sharp rectangle "Growing gold set."

### Column B — Disputed items (middle, wide column, pale amber tint)

Column header: "B · Disputed items" with italic sub-line "N ≥ 2 annotators · C1 proposed."

This column has two halves stacked top to bottom, separated by a single horizontal hairline labeled "the same starting prompt, two runs ↓" at roughly two-thirds of the way down.

**Upper half — the mechanism.** A compact horizontal sub-flow drawn left-to-right inside the column's top two-thirds:

  Top: user pill "Upload annotator files."

  Below: rounded box "IAA computation" with italic "Cohen's κ · Fleiss' κ · α."

  Below: split into two branches arranged horizontally —

  - Left branch: sharp rectangle "Agreed subset (n_agreed)" → arrow down to rounded box "ReflectAgent · mine rules from agreement" → arrow down-right to a small sharp rectangle "Rule Library."

  - Right branch: sharp rectangle "Disputed subset (n_disputed)" → arrow down to rounded box "Annotator · rule-augmented" (with the Rule Library box drawing a horizontal arrow into it labeled "rules in") → arrow down to sharp rectangle "LLM verdict + cited rules" → arrow down to user pill "Review queue · accept · override · skip" → arrow down to sharp rectangle "Adjudicated corpus."

  A dashed feedback arrow from "Adjudicated corpus" loops upward and back to "Agreed subset," labeled "resolved items rejoin agreed corpus; IAA recomputed."

**Lower half — the measurement.** Below the horizontal hairline that reads "the same starting prompt, two runs ↓":

  Two short parallel horizontal lanes:

  - Lane 1: small label "Run 1 (agreed-only)" → tiny rounded box "ReflectAgent" → tiny sharp rectangle "val curve 1."
  - Lane 2: small label "Run 2 (full post-adjudication)" → tiny rounded box "ReflectAgent" → tiny sharp rectangle "val curve 2."

  Both tiny "val curve" boxes feed rightward into a compact framed inline plot occupying the bottom-right of the middle column:

  ```
  val acc
    │       ╭── Run 2
    │     ╱╮
    │   ╱  ╰── Run 1
    └──────► round
  ```

  Italic caption directly below the plot, sized small: "same prompt, same model; the gap is the value of adjudication. Matched-N control in appendix."

### Column C — Gold labels (right, narrow column)

Column header: "C · Gold labels" with italic sub-line "already adjudicated."

Top: user pill "Upload gold-labeled data."

Below: sharp rectangle "Train / Val / Test split" with italic sub-line "leakage-guarded."

Below: a clearly-bordered sub-region drawn with a thin dashed enclosing rectangle labeled "ReflectAgent loop · per round" containing four compact nodes in a vertical flow:

  PatternExtractor → Candidate rules → Annotator (rule-augmented) → Governor

A short curved arrow goes from Governor back up to PatternExtractor, labeled "next round."

Below the dashed sub-region: sharp rectangle "Held-out test scored once."

Below: sharp rectangle "Memory · new version."

---

## Connections between top and bottom tiers

The downward triangle on top-tier Box 4 ("Labeling") connects only visually to the bottom tier — there is no explicit arrow because the bottom tier *is* the zoom-in of that box. A reader's eye follows the triangle and lands on the bottom-tier title strip.

The outputs of the three bottom-tier columns conceptually merge back into the top tier's "labeled data + Rule Library" arrow that flows from Box 4 to Box 5. The figure does not draw this explicitly because doing so adds clutter; the bottom-tier title strip and the top-tier arrow label do the work jointly.

---

## What to omit deliberately

No legend. Shape conventions and edge conventions are picked up from context.

No badge boxes. The "C1 proposed" label appears only as italic sub-text in the middle column's header.

No "Flow A," "Flow B," "Flow C" cross-references in arrow labels. The column headers ("A · Cold start," "B · Disputed items," "C · Gold labels") carry the naming and nothing else needs it.

No agent toolbar repeating CodebookAgent, AutoPromptGenerator, Annotator, ReflectAgent at the top of the figure. Each agent appears in the box where it does work.

No callout numbers, no ① ② ③ markers, no inset boxes other than the small inline plot in the middle column.
