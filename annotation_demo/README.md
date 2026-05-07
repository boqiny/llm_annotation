# Annotation Demo

A lightweight backend for LLM-based text annotation with versioned prompts, concurrent execution, feedback-driven reflection, and run tracking.

This project is a **research prototype** for experimenting with automated annotation pipelines. It is designed to be simple, inspectable, and extensible — not production-scale.

---

## Architecture Overview

Each annotation project is a self-contained **workspace directory**:

```text
workspace/
  <project_id>/
    inputs/       # versioned codebooks, item lists, task configs
    prompts/      # versioned annotation prompts + metadata
    runs/         # one directory per annotation run
    memory/       # versioned reflection memory (accumulated rules)
    logs/         # lightweight JSONL run index
```

Core design principles:

- **LLM as a primitive** — a unified async/sync interface behind `BaseLLM`; swap providers without changing task logic
- **Prompt = policy** — prompts are generated from codebooks, versioned, and stored; every run records which prompt version was used
- **Run = reproducible execution** — each run directory contains inputs, outputs, prompt reference, LLM config, and evaluation results
- **Memory = learned rules** — the reflection agent distills human corrections into compact reusable rules, stored as versioned memory snapshots
- **Filesystem-based tracking** — no database required; all state is plain JSON/YAML/JSONL files

---

## Module Map

```text
src/annotation_demo/
  core/
    llm.py            # BaseLLM abstraction; OpenAILLM, AnthropicLLM, make_llm()
    evaluation.py     # micro/macro F1, precision, recall for single- and multi-label tasks

  prompts/
    renderer.py       # Jinja2 template loader with strict undefined checking
    templates/
      annotator.jinja         # wraps annotation_prompt + item for LLM annotation
      prompt_generator.jinja  # instructs LLM to write an annotation prompt from a codebook
      reflect_agent.jinja     # instructs LLM to induce reusable rules from feedback

  tasks/
    prompt_generator.py  # generate_annotation_prompt() (sync), agenerate_annotation_prompt() (async)
    annotator.py         # annotate_items() (sync), annotate_items_async() (async, concurrent, with retry)

  agents/
    reflect_agent.py     # ReflectAgent: induce_rules(), update_memory(), build_prompt_with_memory()

  workflows/
    workflow.py          # ProjectWorkflow: run() (async annotation), run_reflection()

  queue/
    job_queue.py         # InMemoryJobQueue: async background job execution with progress tracking

  utils/
    storage.py           # filesystem helpers: JSON/YAML/JSONL I/O, versioning, run directories
```

---

## Setup

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

### 3. Environment variables

```bash
cp .env.example .env
```

Set API keys in `.env`:

```env
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key   # optional

# Optional: override default models
OPENAI_MODEL=gpt-4o-mini
ANTHROPIC_MODEL=claude-sonnet-4-5
```

---

## Core Concepts

### LLM interface

```python
from annotation_demo.core.llm import make_llm

llm = make_llm(provider="openai", model="gpt-4o-mini", temperature=0.0)

# Synchronous
response = llm.generate(messages=[{"role": "user", "content": "..."}])

# Asynchronous
response = await llm.agenerate(messages=[{"role": "user", "content": "..."}])

# response.raw       str
# response.parsed    dict | None  (populated when json_mode=True)
# response.usage     LLMUsage(input_tokens, output_tokens, total_tokens)
```

### Prompt versioning

Prompts are generated from a codebook + task type via the `prompt_generator` task and saved as:

```text
prompts/
  v001.jinja        # the prompt text
  v001.meta.yaml    # created_at, source, task_type, llm config, input versions
```

A new version is created on every `workflow.run()` call.

### Annotation runs

Each call to `workflow.run()` creates:

```text
runs/run_001/
  annotations.json   # list of {item, prediction, raw_output} — failed items include "error"
  meta.yaml          # run_id, prompt version, llm config, timestamps, item count
  eval.json          # present only if gold_labels were provided
```

A lightweight summary line is also appended to `logs/runs.jsonl`.

### Reflection memory

The `ReflectAgent` reads human correction examples and induces compact reusable rules. Memory is versioned and cumulative:

```text
memory/
  memory.v001.json   # {version, rules: [{id, title, rule, rationale, applies_to, confidence}]}
  memory.v002.json   # previous rules + new rules from next feedback session
```

Rules are injected into the annotation prompt before the next run via `build_prompt_with_memory()`.

---

## Workflow Usage

### Annotation run

```python
import asyncio
from annotation_demo.core.llm import make_llm
from annotation_demo.workflows.workflow import ProjectWorkflow

llm = make_llm(provider="openai", model="gpt-4o-mini")
workflow = ProjectWorkflow(project_id="project_0", llm=llm)

codebook = {
    "labels": {"positive": "...", "negative": "...", "neutral": "..."}
}
items = [
    {"item_id": "1", "text": "Great product!"},
    {"item_id": "2", "text": "Doesn't work at all."},
]
task_config = {"task_type": "sentiment_classification"}

# Optional: gold labels for automatic evaluation
gold_labels = [
    {"item_id": "1", "label": "positive"},
    {"item_id": "2", "label": "negative"},
]

result = asyncio.run(
    workflow.run(
        codebook=codebook,
        items=items,
        task_config=task_config,
        gold_labels=gold_labels,   # omit to skip evaluation
        concurrency=5,             # concurrent LLM calls
    )
)

# result.run_id, result.prompt_version, result.annotations_path
# result.eval_result   # dict with accuracy, micro/macro F1, per-label metrics
```

Annotation is concurrent (`concurrency` controls parallelism). Each item is retried up to 2 times with exponential backoff on failure; a failed item is recorded with `prediction: null` and an `"error"` key rather than aborting the batch.

### Reflection loop

After collecting human corrections on annotation results:

```python
feedback_examples = [
    {
        "item": {"item_id": "3", "text": "Not bad, could be better"},
        "model_prediction": "negative",
        "correct_label": "neutral",
        "reason": "Mixed sentiment should default to neutral",
    },
]

reflection = workflow.run_reflection(
    annotation_prompt=open(result.prompt_path).read(),
    feedback_examples=feedback_examples,
    # memory_version="memory.v001"  # pin to a specific version; defaults to latest
)

# reflection.memory_version    "memory.v001"
# reflection.num_new_rules      int
# reflection.enhanced_prompt    annotation prompt with memory rules appended
```

Use `reflection.enhanced_prompt` as the annotation prompt for the next run to incorporate the learned rules.

### Background job queue

For async API contexts where annotation should run in the background:

```python
from annotation_demo.queue.job_queue import InMemoryJobQueue

queue = InMemoryJobQueue(max_workers=2)
await queue.start()

async def factory(on_progress):
    result = await workflow.run(
        codebook=codebook,
        items=items,
        task_config=task_config,
        on_progress=on_progress,   # called with float in [0, 1] as items complete
    )
    return result.to_dict()

state = await queue.submit(project_id="project_0", coro_factory=factory)
# state.job_id, state.status ("queued" | "running" | "succeeded" | "failed")
# state.progress  float 0.0–1.0, updated per item
# state.result    dict (WorkflowResult fields) on success
# state.error     str on failure
```

Poll `queue.get_status(state.job_id)` from a frontend to track progress.

---

## Workspace Layout After a Full Run

```text
workspace/project_0/
  inputs/
    codebook.v001.json
    items.v001.json
    task_config.v001.yaml

  prompts/
    v001.jinja           # generated annotation prompt
    v001.meta.yaml       # provenance metadata

  runs/
    run_001/
      annotations.json   # [{item, prediction, raw_output}, ...]
      meta.yaml          # full run record
      eval.json          # if gold_labels provided

  memory/
    memory.v001.json     # rules induced from first feedback session
    memory.v002.json     # cumulative rules after second session

  logs/
    runs.jsonl           # one line per run, for quick history queries
```

---

## Evaluation Metrics

When `gold_labels` are passed to `workflow.run()`, the system computes:

| Metric | Description |
|---|---|
| `accuracy` | Exact-match accuracy |
| `micro_f1` | F1 pooled across all label instances |
| `macro_f1` | F1 averaged across label classes |
| `per_label` | Precision, recall, F1, support for each label |

Supports both single-label and multi-label classification.

---

## Development Notes

- Uses a `src/` layout with editable install (`pip install -e .`)
- `workspace/` is not committed to git
- `workflow.run()` is fully async — prompt generation and annotation both use `agenerate`
- `workflow.run_reflection()` is synchronous — it calls `llm.generate_json()` (blocking); call it outside an event loop or wrap with `asyncio.to_thread` if needed
- The sync `generate_annotation_prompt` / `annotate_items` are preserved for script use outside async contexts
- Requires Python ≥ 3.10

---

## License

TBD
