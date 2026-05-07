# AnnotAgent — repo guide for Claude

EMNLP 2026 System Demonstrations target. Codebook-driven LLM annotation
framework with a React frontend and FastAPI backend. Demo-ability matters more
than feature breadth — keep the golden-path UX working.

## Where things live

- `annotagent/` — **the live system.** All real work happens here.
  - `backend/` — FastAPI (`app.main:app`) + SQLAlchemy async + SQLite
  - `frontend/` — React + Vite + TS, talks to the backend over `/api/*` and `/ws/*`
  - `seed/` — sample codebooks + datasets used in demos
- `legacy/` — old self-disclosure prototype scripts, eval data, results, and
  visualizations. **Don't touch unless asked.** Not on the live path. The
  earlier `annotation_demo/` package was deleted; its net-new value (Jinja
  rendering, versioned filesystem helpers, auto-prompt-from-codebook, micro F1,
  cross-session memory) is now inside `annotagent/`.
- `README.md` — repo-level user docs (run instructions, architecture).

## Run commands

Docker (preferred for end-to-end):
```bash
cd annotagent && cp .env.example .env && docker compose up --build
# Frontend: http://localhost:8080  Backend: http://localhost:8000
```

Local dev:
```bash
# Terminal 1
cd annotagent/backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# Terminal 2
cd annotagent/frontend && npm install && npm run dev
```

## Architecture rules

- **DB is canonical.** SQLite via SQLAlchemy async. All persistent state
  (projects, codebooks, datasets, jobs, results, memory) lives here.
- **Filesystem is a mirror, not a source of truth.** Prompt versions and run
  snapshots written via `app/utils/storage.py` to
  `annotagent/backend/workspace/project_<id>/{prompts,runs,logs,memory}/`
  exist for human inspection / audit only — never read them back as
  authoritative.
- **Match existing async-SQLAlchemy patterns** in `app/api/*.py`: `db: AsyncSession = Depends(get_db)`,
  `await db.get(...)`, `selectinload` for nested relationships, explicit
  `await db.commit()`.
- **Pydantic schemas** for shared request/response shapes go in
  `app/schemas/schemas.py`. One-off endpoint-local schemas can be inline in
  the route module (see `auto-prompt` in `api/codebooks.py` for the pattern).

## Prompt generation — two paths

- **Deterministic Jinja** (`app/engine/prompt_generator.py` →
  `templates/{dimension,step}.jinja`): used for preset/gallery codebooks. Output
  is byte-equivalent to the prior f-string version — **smoke tests in commit
  fc37371 verify this; don't break it without re-verifying**.
- **LLM-generated** (`app/engine/auto_prompt_generator.py` →
  `templates/auto_prompt_generator.jinja`): used for a user's *custom*
  codebook. Endpoint: `POST /api/projects/{pid}/codebooks/{cid}/auto-prompt`.

## Frontend ↔ backend contract

- Frontend calls live in `frontend/src/lib/api.ts`. WS in `frontend/src/lib/ws.ts`.
- When adding/changing an endpoint, update `api.ts` (and any caller pages
  in `frontend/src/pages/`).
- The frontend expects the existing endpoint shapes — don't rename or restructure
  paths in `app/api/*` casually.

## Optimizer 3-way split (train / val / test) — leakage rules

Every optimizer run takes a gold dataset and splits it deterministically (seed
derived from `(gold_dataset_id, dimension_name)`) into **train / val / test**.
The split is enforced by `api/optimizers.py::_execute_run` with an assert-level
leakage guard before the optimizer is invoked.

| Split | Used for | Sees model output? | Influences final prompt? |
|---|---|---|---|
| **train** | optimizer-specific (see below) | yes | yes |
| **val** | governor signal — accept/rollback decisions per round | yes | yes (selection signal) |
| **test** | held-out final score, evaluated once after `optimize()` returns | no — never passed to optimizer | **no** |

What `train` actually does, per optimizer:

- **ReflectAgent (`optimizers/reflect_agent.py`)**: train is for **failure mining**, NOT few-shot demos. Each round, the current prompt is run on train, mistakes are collected, and the failures (gold + pred + sentence prefix) are fed to a `PatternExtractor` LLM that is *forbidden from quoting full failure sentences verbatim* — it must abstract them into rules. Rules go in the prompt, not raw train sentences.
- **MIPROv2 (`optimizers/mipro.py`)**: train IS used as candidate few-shot demos via DSPy's compile. MIPROv2's whole job is to jointly search instructions + demos.
- **GEPA (`optimizers/gepa.py`)**: train is the search corpus for DSPy's evolutionary loop.
- **OPRO (`optimizers/opro.py`)**: train as exemplar pool for the meta-prompt.

What's enforced (do not break this):

- The optimizer's `optimize(initial_prompt, dimension, valid_labels, trainset, valset)` signature receives only train + val. Test is held by the executor.
- After `optimize()` returns, `_execute_run` calls `evaluate_prompt(result.optimized_prompt, testset, ...)` exactly once. The numbers in `artifact.test.{initial,final}_score` are the **honest, leak-free** scores.
- The asserts at lines `~276–278` of `api/optimizers.py` verify the three sets are disjoint by object identity. Don't remove them.

If you add a new optimizer, it MUST honor this contract: don't read test, don't add testset to any prompt, don't peek at testset.gold for any selection decision. Anything else counts as cheating and the held-out test number stops meaning anything.

## Style notes

- Global Karpathy guidelines apply (see `~/.claude/CLAUDE.md`): think before
  coding, simplicity first, surgical changes, goal-driven execution.
- Prefer extending an existing module over creating a new one — the backend has
  ~12 API modules already; new functionality usually fits in one of them.
- For UI changes, run the dev server and click through the flow before
  declaring done. Type checks aren't enough.
