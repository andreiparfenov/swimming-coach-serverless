# Swimming Coach

A serverless AI swimming coach that generates personalised multi-week training plans. Send a swimmer profile, get back a structured week-by-week plan with sessions broken into warmup, main set, and cooldown. The plan includes pool lengths, coaching notes and technique cues for every session.

Built with two Nebius Serverless AI components:

- A **Serverless Job** (`job/`) that produces a curated swim-coaching knowledge base, used to ground the planning agent in real coaching practice instead of letting the model improvise volume and periodization from scratch.
- A **Serverless Endpoint** (`app/`) that serves the actual planning API and runs a 3-step agentic pipeline against that knowledge base.

## How it works

```
┌──────────────────────────────────────────────────────────────────┐
│  Nebius Serverless JOB  (job/process_training_data.py)           │
│  Runs once, to completion. Compute releases when it's done.      │
│                                                                    │
│  job/seed_data/training_principles.json (12 level×goal profiles) │
│           │                                                        │
│           ▼                                                        │
│  For each profile: 1 LLM call → compress into a coaching summary  │
│           │                                                        │
│           ▼                                                        │
│  knowledge_base.json  →  uploaded to Nebius Object Storage         │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  Nebius Serverless ENDPOINT  (app/main.py)                       │
│  Long-running HTTP service, stays up between requests.            │
│  Fetches knowledge_base.json from Object Storage on first use     │
│  after each container start (falls back to a bundled copy at      │
│  app/data/ if storage is unreachable or credentials are unset).   │
│                                                                    │
│  POST /generate-plan                                              │
│        │                                                            │
│        ▼                                                            │
│  Step 1: Periodization agent                                      │
│    profile + knowledge-base coaching summary → week themes,       │
│    intensity curve, volume multipliers. One LLM call.             │
│        │                                                            │
│        ▼                                                            │
│  Step 2: Session generator agent                                  │
│    macro structure → warmup/main set/cooldown in pool lengths,    │
│    grounded by the same coaching summary. One LLM call per week.  │
│        │                                                            │
│        ▼                                                            │
│  Step 3: Coaching notes agent                                     │
│    sessions → dolphin kick cues, technique focus, encouragement.  │
│    One batch LLM call.                                            │
│        │                                                            │
│        ▼                                                            │
│  TrainingPlan JSON                                                 │
└──────────────────────────────────────────────────────────────────┘
```

All LLM inference (Job and Endpoint) goes through Nebius Token Factory, the OpenAI-compatible managed inference API. No GPU quota needed for either component. Both run on CPU presets.

## API

### `GET /health`

```json
{ "status": "ok" }
```

### `POST /generate-plan`

**Request body:**

| Field                      | Type   | Values                                            | Default     |
| -------------------------- | ------ | ------------------------------------------------- | ----------- |
| `level`                    | string | `beginner` / `intermediate` / `advanced`          | required    |
| `goal`                     | string | `endurance` / `speed` / `technique` / `race_prep` | required    |
| `sessions_per_week`        | int    | 2–6                                               | required    |
| `session_duration_minutes` | int    | 30–120                                            | required    |
| `pool_length`              | int    | `25` / `50`                                       | `25`        |
| `stroke_focus`             | string | e.g. `freestyle`, `mixed`                         | `freestyle` |
| `weeks`                    | int    | 1–12                                              | `4`         |
| `notes`                    | string | free text                                         | `""`        |

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

## Data processing job

`job/process_training_data.py` runs as a **Nebius Serverless Job**. It:

1. Loads 12 hand-curated coaching profiles (one per `level` × `goal` combination) from `job/seed_data/training_principles.json` — volume ranges, intensity-zone distributions, periodization patterns, and key coaching principles per swimmer type.
2. For each profile, calls Token Factory once to compress the structured data into a 3–5 sentence coaching summary suitable for prompt injection.
3. Writes the result to `knowledge_base.json` and uploads it to a Nebius Object Storage bucket.

The Endpoint fetches that file from Object Storage itself, once per container lifetime (on first request after each start), and caches it in memory. A bundled copy at `app/data/knowledge_base.json` is kept as a fallback for local development or if Object Storage is briefly unreachable.

**Run it:**

```bash
cd job
export NEBIUS_API_KEY=<your-tokenfactory-key>
export S3_ACCESS_KEY=<your-static-access-key-id>
export S3_SECRET_KEY=<your-static-access-key-secret>
./deploy_job.sh
```

`deploy_job.sh` builds and pushes the job's Docker image, then makes sure that the target Object Storage bucket exists and that the access key's service account can write to it (creating an IAM group and granting `storage.editor` if needed, because Nebius Object Storage denies access by default until a bucket policy explicitly grants a role to a subject). Safe to re-run on every deploy.

Once it completes, the Endpoint picks up the new knowledge base the next time its container starts — no rebuild needed, since the file is fetched from storage rather than baked into the image:

```bash
nebius ai endpoint stop <endpoint-id>
nebius ai endpoint start <endpoint-id>
```

`stop`/`start` restarts the container (confirmed via the application logs showing a fresh startup sequence) while keeping the same public IP — a lighter operation than the `delete` + `create` cycle needed when the _code_ changes rather than just the data.

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

| Variable                | Description                                                                                                          | Default                                                                      |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `NEBIUS_API_KEY`        | Nebius Token Factory API key                                                                                         | required                                                                     |
| `TOKENFACTORY_BASE_URL` | Token Factory endpoint URL                                                                                           | `https://api.tokenfactory.nebius.com/v1/`                                    |
| `MODEL_ID`              | Model to use for all pipeline steps                                                                                  | `meta-llama/Llama-3.3-70B-Instruct`                                          |
| `S3_ACCESS_KEY`         | Nebius Object Storage static access key ID — used by both the Job (to upload) and the Endpoint (to fetch at startup) | optional for the Endpoint; falls back to the bundled knowledge base if unset |
| `S3_SECRET_KEY`         | Nebius Object Storage static access key secret                                                                       | optional for the Endpoint, same fallback                                     |
| `S3_BUCKET`             | Bucket holding `knowledge_base.json`                                                                                 | `swim-program`                                                               |
| `S3_ENDPOINT_URL`       | Object Storage endpoint                                                                                              | `https://storage.eu-north1.nebius.cloud`                                     |

## Hardware, runtime, and cost

| Component         | Platform | Preset       | Notes                                                                                                                               |
| ----------------- | -------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| Endpoint (`app/`) | `cpu-d3` | `8vcpu-32gb` | CPU only — no GPU needed, all inference goes through Token Factory. Stays running continuously; billed for uptime, not per-request. |
| Job (`job/`)      | `cpu-d3` | `4vcpu-16gb` | Runs to completion, then compute is released automatically — billed only for actual runtime.                                        |

**Approximate runtime:**

- Job: ~1–3 minutes total (12 sequential Token Factory calls, each capped at 200 output tokens, plus one upload to Object Storage).
- Endpoint, per `/generate-plan` request: each step is a sequential LLM call — 1 periodization + 1 per week + 1 batch coaching-notes call — so total latency scales with plan length. Measured end-to-end for a 4-week plan: **~3 minutes** (6 sequential calls, ~30s average each). A 2-week plan (4 calls) takes roughly half that. Plan for a few minutes per request, not seconds — this is the cost of correctness over a single giant prompt, not an inefficiency to optimise away lightly.

**Cost:** both components run on CPU-only presets, with the LLM cost coming from Token Factory's per-token pricing. The Job's cost is bounded by its few-minute one-time runtime, while the Endpoint's ongoing cost is the `8vcpu-32gb` preset's hourly rate for however long you keep it running, plus per-request Token Factory usage.

## Project structure

```
├── app/                          # Serverless Endpoint
│   ├── main.py                   # FastAPI app, routes
│   ├── models.py                 # Pydantic types: SwimmerProfile → TrainingPlan
│   ├── pipeline.py                # 3-step agentic pipeline
│   ├── llm.py                     # TokenFactory client
│   ├── knowledge.py                # Loads the curated knowledge base for prompt grounding
│   └── data/
│       └── knowledge_base.json       # Fallback copy; live data is fetched from Object Storage
├── job/                          # Serverless Job
│   ├── process_training_data.py    # Builds knowledge_base.json from seed data
│   ├── seed_data/
│   │   └── training_principles.json  # 12 curated level×goal coaching profiles
│   ├── Dockerfile.job
│   └── deploy_job.sh                # Build, push, bucket/IAM setup, submit job
├── frontend/                     # Static single-page UI
│   └── index.html
├── Dockerfile                    # Endpoint image
├── deploy.sh                     # Build, push, create/recreate the Endpoint
├── requirements.txt
└── env.example
```
