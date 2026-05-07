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

## Style notes

- Global Karpathy guidelines apply (see `~/.claude/CLAUDE.md`): think before
  coding, simplicity first, surgical changes, goal-driven execution.
- Prefer extending an existing module over creating a new one — the backend has
  ~12 API modules already; new functionality usually fits in one of them.
- For UI changes, run the dev server and click through the flow before
  declaring done. Type checks aren't enough.
