# Annotation Demo

A lightweight backend for LLM-based annotation with versioned prompts and run tracking.

This project is designed as a **research-friendly annotation tool** for prototyping and evaluating annotation workflows. It provides:

* Project-level workspace management
* Versioned prompt generation from codebooks
* LLM-based annotation
* Run-level tracking and reproducibility

---

## 🧠 Design Overview

Each annotation project is treated as a **self-contained workspace**:

```text
workspace/
  project_0/
    inputs/
    prompts/
    runs/
    logs/
```

Core principles:

* **LLM as a primitive**: a unified interface for all model calls
* **Prompt = policy**: prompts are versioned and tracked
* **Run = execution**: each run records inputs, prompt version, and outputs
* **Filesystem-based tracking**: simple, transparent, reproducible

---

## 📦 Setup

### 1. Create virtual environment

```bash
cd annotation_demo

python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install --upgrade pip
pip install -e .
```

---

## 🔑 Environment Variables

Create a `.env` file from the template:

```bash
cp .env.example .env
```

Set your API key:

```env
OPENAI_API_KEY=your_key_here
```

---

## 📁 Project Structure

```text
annotation_demo/
  src/annotation_demo/
    core/        # LLM + core primitives
    prompts/     # Jinja templates + renderer
    tasks/       # prompt generation + annotation
    workflows/   # end-to-end project execution

  workspace/     # runtime project data (ignored by git)
  scripts/       # local run scripts
```

---

## 🚀 Running a Demo

### 1. Prepare inputs

Create a project directory:

```text
workspace/project_0/inputs/
  codebook.v001.json
  items.v001.json
  task_config.v001.yaml
```

Example `task_config.v001.yaml`:

```yaml
task_type: multi_label_classification
provider: openai
model: gpt-4o-mini
temperature: 0.0
max_tokens: 1024
```

---

### 2. Run workflow

```bash
python scripts/run_project_workflow.py
```

---

## 📊 Outputs

After running, the system will create:

```text
workspace/project_0/
  prompts/
    v001.jinja
    v001.meta.yaml

  runs/
    run_001/
      annotations.json
      meta.yaml

  logs/
    runs.jsonl
```

---

## 🔁 Versioning

The system tracks:

* Input versions (`codebook.v001`, `items.v001`, `task_config.v001`)
* Prompt versions (`v001`, `v002`, ...)
* Runs (`run_001`, `run_002`, ...)

Each run records exactly which inputs and prompt were used.

---

## 🧪 Development Notes

* Uses a `src/` layout with editable install
* Workspace data is **not committed to git**
* Designed to be minimal but extensible

---

## 📌 Roadmap

Planned improvements:

* Reflective prompt updates (memory / rule induction)
* Concurrent annotation execution
* Basic evaluation metrics
* Frontend integration

---

## 🧾 License

TBD

---
