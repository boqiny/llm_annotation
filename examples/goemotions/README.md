# GoEmotions — 20-minute reproducibility example

This example lets a reviewer reproduce AnnotAgent's core loop end-to-end on an **open-data** classification task, without any private data or API-key sharing beyond their own OpenAI / Anthropic credentials.

**Task**: multi-label emotion classification over short English comments.
**Labels**: 9 emotions curated from the GoEmotions label scheme (Demszky et al., 2020, Apache 2.0).
**Sample size**: 30 items, shipped in `data/cleaned/goemotions_sample.json`.

## Prerequisites

- Docker + Docker Compose
- An `OPENAI_API_KEY` (the sweep also accepts `ANTHROPIC_API_KEY` for cross-vendor)

## Path A · UI walkthrough (~10 minutes)

```bash
cd annotagent
cp .env.example .env        # drop your OPENAI_API_KEY into .env
docker compose up --build
```

Browse to http://localhost:8080 and follow:

1. **New project** → call it `goemotions-demo`.
2. **Setup · Section 01 · Codebook** → Door C → pick `goemotions` → **Load preset → Accept**.
3. **Setup · Section 02 · Datasets** → click **Load** next to `GoEmotions · reproducibility sample (public)`. This registers it as the gold dataset.
4. **Generate pipeline** → a single-step multi-label pipeline appears on the Pipeline page.
5. **Prompt Lab**:
   - Optimizer: `reflect_agent`
   - Dimension: `Emotion`
   - Gold dataset: `GoEmotions · reproducibility sample (public)`
   - Split: 15 / 42 / 43 (defaults)
   - Budget: 3–5 rounds
   - Click **Launch optimizer run**
6. Watch the trajectory stream live; when done, inspect the **held-out test** row in the header and the Rule Library panel.

What a reviewer sees in under 10 minutes: messy input → clean codebook → predictions with rules → measurable test-set Δ → inspectable rule artifact.

## Path B · CLI multi-model sweep (~10 additional minutes)

The sweep runs the same configuration across 3 models and writes a CSV comparing test-set accuracy and cost — the exact table reviewers see in Section 4 Table B of the paper.

```bash
cd annotagent/backend
python -m scripts.sweep_models \
    --codebook goemotions \
    --dimension Emotion \
    --gold ../../data/cleaned/goemotions_sample.json \
    --optimizer reflect_agent \
    --models openai:gpt-5.4-mini openai:gpt-5.4 anthropic:claude-sonnet-4-5 \
    --budget 4 \
    --out sweep_goemotions.csv
```

Expected shape of the output CSV:

```
model,optimizer,n_train,n_val,n_test,zero_shot_test_acc,reflected_test_acc,delta_pp,val_initial,val_final,total_tokens,total_cost_usd,wall_seconds
openai:gpt-5.4-mini,reflect_agent,5,13,12,0.6250,0.7500,12.50,0.5385,0.6923,15842,0.0214,84.3
openai:gpt-5.4,reflect_agent,5,13,12,0.7500,0.8333,8.33,0.6923,0.7692,14120,0.1876,76.1
anthropic:claude-sonnet-4-5,reflect_agent,5,13,12,0.7083,0.7917,8.34,0.6154,0.7308,16033,0.2104,91.7
```

(Numbers above are illustrative — actual values will depend on the model and the sample split seed.)

## Leakage guarantees

- The 30 items are shuffled deterministically with a seed derived from `(gold_dataset_id, dimension_name)` — same inputs, same split.
- `testset` items are never passed to the optimizer. The optimizer only sees `trainset` (failure-pattern mining) and `valset` (Governor rollback).
- After optimization completes, both the initial and optimized prompts are evaluated on the held-out `testset` — the reported "test final" is the honest number.

## Replacing the sample with real GoEmotions

Our shipped sample is synthetic-but-representative (30 items originally written for this demo, labeled using the GoEmotions scheme). To run on the real dataset:

```python
# Quick-start with Hugging Face datasets
from datasets import load_dataset
import json

ds = load_dataset("google-research-datasets/go_emotions", "simplified", split="test[:200]")
# GoEmotions labels are integer indices; map through ds.features['labels'].feature.names
names = ds.features["labels"].feature.names
items = []
for i, row in enumerate(ds):
    labels = [names[ix] for ix in row["labels"]]
    # Keep only labels we actually ship in our 9-label preset
    keep = {"gratitude","admiration","joy","anger","sadness","fear","curiosity","disapproval","neutral"}
    labels = [l for l in labels if l in keep] or ["neutral"]
    items.append({"sentence": row["text"], "labels": {"Emotion": labels}})

json.dump({"items": items}, open("goemotions_real.json", "w"), indent=2)
```

Then upload `goemotions_real.json` via **Setup · Upload your own · Gold standard**.

## Citations

If you use this example in published work, please cite:
- Demszky, D. et al. (2020). *GoEmotions: A Dataset of Fine-Grained Emotions.* ACL 2020. https://arxiv.org/abs/2005.00547
- (AnnotAgent citation will be added after acceptance.)
