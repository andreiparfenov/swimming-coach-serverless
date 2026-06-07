# Swimming Coach

A serverless AI swimming coach that generates personalised multi-week training plans. Send a swimmer profile, get back a structured week-by-week plan with sessions broken into warmup, main set, and cooldown. The plan inclusdes pool lengths, coaching notes and technique cues for every session.

## How it works

The backend runs as a **Serverless CPU Endpoint** and implements a 3-step agentic pipeline:

```
POST /generate-plan
        │
        ▼
┌─────────────────────────┐
│  Step 1: Periodization  │  Designs the macro structure: week themes,
│  agent                  │  intensity curve, volume multipliers.
└──────────┬──────────────┘  One LLM call → JSON week plan.
           │
           ▼
┌─────────────────────────┐
│  Step 2: Session        │  Generates fully specified sessions per week:
│  generator agent        │  warmup / main set / cooldown in pool lengths,
└──────────┬──────────────┘  with reps, rest, and drill intent.
           │                 One LLM call per week.
           ▼
┌─────────────────────────┐
│  Step 3: Coaching notes │  Adds a personalised coaching note to each
│  agent                  │  session: dolphin kick cues, technique focus,
└──────────┬──────────────┘  level-appropriate feedback. One batch call.
           │
           ▼
     TrainingPlan JSON
```

LLM inference goes through Nebius Token Factory. No GPU quota needed for the endpoint itself.

## API

### `GET /health`

```json
{ "status": "ok" }
```

### `POST /generate-plan`

**Request body:**

| Field | Type | Values | Default |
|---|---|---|---|
| `level` | string | `beginner` / `intermediate` / `advanced` | required |
| `goal` | string | `endurance` / `speed` / `technique` / `race_prep` | required |
| `sessions_per_week` | int | 2–6 | required |
| `session_duration_minutes` | int | 30–120 | required |
| `pool_length` | int | `25` / `50` | `25` |
| `stroke_focus` | string | e.g. `freestyle`, `mixed` | `freestyle` |
| `weeks` | int | 1–12 | `4` |
| `notes` | string | free text | `""` |

**Example request:**

```bash
curl -X POST https://<your-endpoint>/generate-plan \
  -H "Content-Type: application/json" \
  -d '{
    "level": "intermediate",
    "goal": "endurance",
    "sessions_per_week": 3,
    "session_duration_minutes": 60,
    "pool_length": 25,
    "weeks": 4
  }'
```

**Response:** A `TrainingPlan` object with:
- `summary` — one-line plan description
- `weeks[]` — week-by-week breakdown, each with:
  - `theme` and `intensity`
  - `sessions[]` — each session has `warmup`, `main_set`, `cooldown` as lists of sets
  - Each set: `description`, `reps`, `lengths_per_rep`, `rest_seconds`, `intent`
  - `coaching_note` — personalised note for the session

Full schema available at `/docs` (Swagger UI).

## Run locally

```bash
# 1. Copy and fill in your credentials
cp env.example .env
# Edit .env: add NEBIUS_API_KEY

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the server
uvicorn app.main:app --reload
```

Then open [http://localhost:8000/docs](http://localhost:8000/docs) for the interactive API explorer.

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `NEBIUS_API_KEY` | Nebius Token Factory API key | required |
| `TOKENFACTORY_BASE_URL` | Token Factory endpoint URL | `https://api.tokenfactory.us-central1.nebius.com/v1` |
| `MODEL_ID` | Model to use for all pipeline steps | `meta-llama/Llama-3.3-70B-Instruct` |

## Project structure

```
├── app/
│   ├── main.py        # FastAPI app, routes
│   ├── models.py      # Pydantic types: SwimmerProfile → TrainingPlan
│   ├── pipeline.py    # 3-step agentic pipeline
│   └── llm.py         # TokenFactory client
├── Dockerfile
├── requirements.txt
└── env.example
```