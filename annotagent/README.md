# AnnotAgent

Codebook-driven LLM annotation framework with a React frontend and FastAPI backend. Demo paper target: EMNLP 2026 System Demonstrations.

## Architecture

- **Backend**: FastAPI + SQLAlchemy + SQLite (async)
- **Frontend**: React + TypeScript + Tailwind CSS + Recharts
- **LLM Support**: OpenAI and Anthropic APIs

## Quick Start

### Backend

```bash
cd annotagent/backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend

```bash
cd annotagent/frontend
npm install
npm run dev
```

### Docker (one-command)

```bash
cd annotagent
cp .env.example .env   # (optional) add OPENAI_API_KEY / ANTHROPIC_API_KEY
docker compose up --build
```

Frontend: http://localhost:8080 · Backend: http://localhost:8000/api/health

Sample codebooks are loaded automatically via presets (`self_disclosure`, `sentiment`). Sample datasets with gold labels live in [`seed/`](./seed):

- `seed/self_disclosure_demo.json` — 10-item multi-dimensional self-disclosure sample
- `seed/sentiment_demo.json` — 10-item sentiment sample

Upload either one in the UI's Project Setup page to try the full pipeline end-to-end in under a minute.

## Workflow

1. **Create Project** - Name your annotation project and configure LLM settings
2. **Upload Codebook** - Upload a JSON codebook or select a preset (e.g., Self-Disclosure, Sentiment)
3. **Upload Dataset** - Upload CSV/JSON data to annotate (optionally upload gold standard)
4. **Generate Pipeline** - The decomposition agent splits dimensions into ordered steps
5. **Run Annotation** - Execute the pipeline with real-time WebSocket progress monitoring
6. **View Results** - Accuracy charts, confusion matrices, per-dimension metrics
7. **Calibrate** - Compare against gold, mine error patterns, generate calibration rules

## Codebook Format

```json
{
  "name": "My Codebook",
  "description": "Description",
  "dimensions": [
    {
      "name": "Sentiment",
      "type": "single_label",
      "labels": [
        {"name": "Positive", "definition": "...", "examples": []},
        {"name": "Negative", "definition": "...", "examples": []}
      ],
      "instructions": "Additional guidance..."
    }
  ],
  "decomposition_hints": {
    "groups": [["Dim1"], ["Dim2", "Dim3"]],
    "order": ["Step1", "Step2"]
  }
}
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/projects` | List projects |
| POST | `/api/projects` | Create project |
| POST | `/api/projects/:id/codebooks` | Upload codebook |
| POST | `/api/projects/:id/datasets` | Upload dataset |
| POST | `/api/projects/:id/pipelines/decompose` | Generate pipeline |
| POST | `/api/projects/:id/jobs` | Start annotation job |
| GET | `/api/projects/:id/jobs/:jid/results` | Get results |
| GET | `/api/projects/:id/jobs/:jid/results/metrics` | Get metrics |
| GET | `/api/projects/:id/jobs/:jid/results/export` | Export CSV/JSON |
| WS | `/ws/jobs/:jid` | Real-time progress |

## Presets

- **self_disclosure** - 6-dimension self-disclosure analysis (Topic, Level, Depth, Intimacy, Confession, Temporality)
- **sentiment** - 3-class sentiment classification (Positive, Neutral, Negative)
