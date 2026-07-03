# CALICO

**Codebook-Aligned LLM-assisted Iterative Coding and Optimization.**

CALICO is a human-centered, codebook-aligned workflow for LLM-assisted annotation. It helps researchers build, inspect, and refine annotation pipelines from researcher-defined codebooks. CALICO treats the codebook as the task specification and the prompt as an editable, versioned artifact rather than hidden backend configuration. Within one project workspace, users can parse codebooks, generate dimension-specific prompts, run annotation, review outputs, provide feedback, improve prompts, and export final labels.

> Project page for an EMNLP 2026 System Demonstrations submission.

## Links

- Paper: coming soon
- Demo video: coming soon
- Live demo: coming soon
- Code: [GitHub repository](https://github.com/boqiny/llm_annotation)

## Why CALICO?

Many LLM annotation workflows begin with a hand-written prompt. CALICO begins with a more familiar artifact for qualitative, social-science, and domain-expert annotation: the **codebook**. The system parses codebook materials into a structured schema, drafts prompts from that schema, and keeps the resulting prompts visible and editable.

CALICO is designed around three principles:

- **Codebook alignment.** Dimensions, labels, definitions, examples, and labeling constraints are grounded in the accepted codebook version.
- **Human control.** Codebook drafts, prompts, feedback rules, optimization outputs, and annotation runs remain inspectable.
- **Iterative refinement.** Users can improve prompts through free-text human feedback, labeled examples, or supervised prompt optimizers while preserving version history.

## Workflow

![CALICO workflow](https://raw.githubusercontent.com/boqiny/llm_annotation/main/annotagent/assets/figures/workflow.svg)

1. **Create a project.** Configure the provider/model and organize codebooks, prompts, data, annotation runs, feedback, and prompt versions in one workspace.
2. **Parse a codebook.** Upload a file, paste text, select a preset, or revise an existing codebook. CALICO drafts an editable structured schema before activation.
3. **Generate prompts.** The accepted codebook is converted into dimension-specific prompts that users can inspect, edit, copy, and apply.
4. **Run annotation.** Apply the active prompt pipeline to a dataset and monitor progress, estimated cost, token usage, and results.
5. **Review outputs.** Inspect predictions, compare with available reference labels, export CSV/JSON results, and reopen completed runs.
6. **Refine prompts.** Use cold-start human feedback when labeled data is unavailable, or run supervised prompt optimization when labeled examples are available.

## System Components

### Codebook Parsing Agent

The Codebook Parsing Agent converts raw codebook materials into an editable structured schema. It supports PDF, DOCX, XLSX, CSV, JSON, Markdown, and plain-text inputs, with format-specific preprocessing for heterogeneous layouts. The resulting draft schema contains dimensions, labels, definitions, task instructions, optional examples, and dimension-level labeling modes such as single-label or multi-label. Before activation, CALICO applies checks for common issues such as missing labels, duplicate labels, large flat label sets, and missing definitions. Accepting the draft creates a new project codebook version.

### Prompt Generator

The Prompt Generator converts the accepted codebook schema into executable annotation prompts. For each dimension, CALICO assembles the dimension name, label set, label definitions, annotation instructions, optional examples, and output-format constraints into a prompt. These prompts are exposed in the Prompt Hub as versioned artifacts, so users can inspect, revise, copy, replace, and apply prompts before running annotation at scale.

### Human-in-the-Loop Feedback

CALICO supports cold-start refinement when users have a codebook and unlabeled data but not enough labeled examples for supervised optimization. Users inspect model-generated annotations and write free-text feedback about systematic errors, boundary cases, or preferred labeling behavior. CALICO converts this feedback into structured calibration rules, stores them as versioned memory scoped by project, codebook version, and dimension, and previews the prompt diff before any update is applied.

### Prompt Optimizers

When labeled examples are available, CALICO supports supervised prompt optimization through a shared optimizer interface. The current system includes GEPA, MIPROv2, OPRO, and ReflectAgent. ReflectAgent mines model failures into general calibration rules, uses validation performance to accept or roll back candidate updates, and stores the resulting rule library as reusable memory. Optimizer runs use deterministic stratified train/validation/test splits and report held-out accuracy, macro-F1, weighted-F1, per-class metrics, token usage, and a leakage audit.

## Highlights

- Codebook-first project setup with editable parsed drafts.
- One active prompt per annotation dimension in the Prompt Hub.
- Cold-start feedback loop for projects without gold labels.
- Versioned memory tied to the active codebook version.
- Labeled-data prompt optimization with held-out evaluation.
- Persistent annotation runs with CSV/JSON export.
- OpenAI and Anthropic provider support for downstream annotation and optimization.

## Running Locally

Backend:

```bash
cd annotagent/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

If you use Conda or another environment manager, activate that environment before installing the backend requirements.

Frontend:

```bash
cd annotagent/frontend
npm install
npm run dev
```

Then open `http://localhost:5173`.

## Citation

```bibtex
@inproceedings{calico2026,
  title     = {CALICO: Codebook-Aligned LLM-assisted Iterative Coding and Optimization},
  author    = {Anonymous},
  booktitle = {Proceedings of the 2026 Conference on Empirical Methods in Natural Language Processing: System Demonstrations},
  year      = {2026}
}
```
