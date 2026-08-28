# Astrology Backend

FastAPI backend for an astrology app: natal charts, synastry, transits,
progressions, solar returns, daily forecasts, and AI-powered interpretations
grounded in a RAG book corpus. This repo is the **backend only** — the
frontend lives in a separate repository.

## Features

- ✨ Natal chart calculation (planet positions, zodiac signs, houses, ascendant)
- 🔮 Aspects between planets, with orb/exactness/applying-separating detail
- 🤝 Synastry (compatibility between two charts) + relationship-type breakdown
- 🌊 Transits, progressions, and progressed synastry
- 🌙 Solar returns
- 🎾 Daily forecast for sports matches — event-chart method (John Frawley,
  *Sports Astrology*), see `app/services/AGENTS.md` for the scoring model
- 🎯 AI interpretation of any chart type, backed by a RAG corpus of
  astrology books (chunked, embedded, searched per-query)
- 💬 Freeform chat with an "astrologer" grounded in a specific chart
- 📍 Geocoding/autocomplete for birth/event locations

## Tech stack

| Component | Technology |
|-----------|------------|
| API framework | FastAPI + Pydantic v2 |
| Astrology engine | pyswisseph (Swiss Ephemeris) + ephem |
| Database | Supabase (Postgres) — SQLite (`astrology.db`) for local/legacy use |
| Auth | Supabase Auth (`app/auth.py`) |
| LLM interpretation | Multi-provider: Claude, DeepSeek, Gemini, OpenRouter, Ollama (`app/services/llm_adapter.py`) |
| RAG book ingestion | PyMuPDF / python-docx / EbookLib (parsing) + sentence-transformers (embeddings) + Supabase (storage/search) |
| Rate limiting | slowapi |

## Running locally

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in SUPABASE_URL / SUPABASE_KEY / OPENAI_API_KEY / an LLM provider key
uvicorn app.main:app --reload
```

API available at http://localhost:8000
Docs (Swagger UI): http://localhost:8000/docs

## Running with Docker

### Build

```bash
docker build -t astrology-backend .
```

First build takes ~5–10 minutes: it installs torch and bakes the embedding
model into the image. Later builds reuse cached layers and finish in seconds
unless `requirements.txt` changed.

### Run

```bash
docker run -d --name astro -p 8080:8080 -e PORT=8080 --env-file .env astrology-backend
```

The API is then on http://localhost:8080 (Swagger UI at `/docs`).

Without `--env-file .env` the container still starts and serves chart
calculation, but anything touching Supabase or an LLM will fail — those read
their keys from the environment.

### Inspect and stop

```bash
docker logs -f astro          # follow logs
docker stats --no-stream astro # memory/CPU usage
docker exec -it astro bash    # shell inside the container

docker stop astro             # stop
docker start astro            # start again
docker rm -f astro            # stop and delete the container
docker rmi astrology-backend  # delete the image
docker run -p 8080:8080 -e PORT=8080 --env-file .env astrology-backend 
```

### What the image does and why

- **The embedding model is baked in at build time.** `search_service.py` loads
  `paraphrase-multilingual-MiniLM-L12-v2` (~458 MB) via sentence-transformers.
  If it were not in the image, every cold start would download it from
  HuggingFace first.
- **`HF_HUB_OFFLINE=1` is set** so sentence-transformers never calls
  huggingface.co at runtime. Without it the container still phones home to check
  for model updates on every start, and fails outright when HuggingFace is
  unreachable. With it the model loads from the image in ~3s instead of ~10s.
- **torch is installed from the CPU wheel index.** The default wheel pulls in
  CUDA (~2 GB) which is dead weight without a GPU.
- **The server binds `$PORT`**, not a fixed 8080 — Cloud Run and most PaaS
  providers assign the port at runtime.

### Resource requirements (measured)

| | |
|---|---|
| Image size | ~1.75 GB |
| Memory, idle | ~320 MB |
| Memory, after the embedding model loads | ~820 MB |
| **Minimum memory limit** | **1 GiB (2 GiB recommended)** |
| Cold start to first response | ~5 s |

512 MB is not enough — the process is killed once the model loads.

### Deploying to Cloud Run

The image works as-is. Settings that are not defaults and matter:

```
Memory                 2 GiB
CPU                    1
Request timeout        900     # default 300 cuts long analyses off mid-generation
Max concurrent/instance 8      # default 80 overloads one container
Min instances          0
```

`DATABASE_URL` must point at the Supabase **connection pooler** (IPv4), not at
`db.<project>.supabase.co:5432` — the direct host is IPv6-only on the free plan
and Cloud Run cannot reach IPv6-only hosts.

## API endpoints (selected)

- `POST /chart/calculate` — natal chart calculation
- `POST /transits`, `POST /analysis/transits` — current/target-date transits
- `POST /progressions`, `POST /analysis/progressions` — secondary progressions
- `POST /synastry`, `POST /synastry/direct`, `POST /analysis/synastry/full`,
  `POST /synastry/relationship-types` — synastry + relationship analysis
- `POST /progressed-synastry`, `POST /analysis/progressed-synastry`
- `GET /charts/{chart_id}/solar-return`, `GET /charts/{chart_id}/transits`
- `POST /daily-forecast` — sports match event-chart forecast
- `POST /analysis/full`, `POST /analysis/planet`, `POST /analysis/query`,
  `POST /analysis/query-with-chart`, `POST /analysis/chat` — LLM-backed
  interpretation and chat
- `GET /books`, `POST /books/import`, `POST /books/process`,
  `POST /books/{book_id}/query` — RAG book corpus management/search
- `GET /geocode/autocomplete`, `GET /geocode/coordinates` — location lookup

Full request/response shapes: see `/docs` (Swagger) once the server is running.

## Project structure

```
.
├── app/
│   ├── api/            # FastAPI route handlers (endpoints.py)
│   ├── core/            # Settings/config
│   ├── db/              # Database setup
│   ├── models/           # SQLAlchemy models
│   ├── schemas/          # Pydantic request/response schemas
│   ├── services/          # Business logic: chart analysis, synastry,
│   │                       daily forecast, LLM adapters, RAG ingestion
│   │                       — see app/services/AGENTS.md
│   ├── utils/             # Astrology math (astrology_v2.py, horary_tables.py)
│   │                       — uses pyswisseph + ephe/ ephemeris data
│   ├── auth.py            # Supabase auth
│   └── main.py            # FastAPI app entrypoint
├── ephe/                  # Swiss Ephemeris data files (do not hand-edit)
├── openspec/               # Spec-driven change proposals (see AGENTS.md)
├── plans/                  # Standalone design docs for larger features
├── astrology.db             # Local/legacy SQLite DB (do not hand-edit)
├── Dockerfile               # Container build — see "Running with Docker"
├── .dockerignore            # Keeps venv/tests/docs out of the build context
└── requirements.txt
```

## Environment variables (`.env`)

```env
PROJECT_NAME="Astrology API"
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-service-role-key
OPENAI_API_KEY=your-openai-api-key
# Plus whichever LLM provider(s) you use for interpretation:
# ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / GEMINI_API_KEY / OPENROUTER_API_KEY
# LLM_PROVIDER=claude   # default provider if the frontend doesn't specify one
```

## For contributors / agents

Start with [`AGENTS.md`](AGENTS.md) — it points to `INSIGHTS.md` (rationale
behind non-obvious decisions), `openspec/` (spec-driven change proposals),
and per-folder guides like `app/services/AGENTS.md`.

## License

MIT

## Testing

### Running tests

Run everything (unit + integration + functional; performance tests are
excluded by default, see below):

```bash
venv/bin/python -m pytest tests/
```

Run with full logs — shows every test name, keeps `print()` output from the
code instead of hiding it, and prints a per-test timing table at the end:

```bash
venv/bin/python -m pytest tests/ -v -s --durations=0
```

Run one test type only:

```bash
# Unit — calls functions directly, no HTTP layer
venv/bin/python -m pytest tests/test_text_verification.py tests/test_natal_chart_reference.py tests/test_geocode_locationiq.py tests/test_geocode_timezone.py

# Integration — hits the FastAPI app through TestClient
venv/bin/python -m pytest tests/test_api_deterministic_routes.py tests/test_api_llm_routes.py

# Functional — multi-step scenarios chaining several endpoints
venv/bin/python -m pytest tests/test_api_functional_flows.py -m functional

# Performance — opt-in only, not part of the default run
venv/bin/python -m pytest tests/test_perf.py -m perf -v -s
```

### Reading the output

Without `-v`, pytest prints one character per test: `.` = passed, `F` =
failed, `E` = error before/around the test itself (e.g. a fixture broke, not
necessarily the logic under test). The final summary line looks like:

```
79 passed, 3 deselected, 1 failed in 7.30s
```

- **passed** — every `assert` in the test held.
- **failed** — an `assert` didn't match reality; pytest prints the file:line
  and the expected-vs-actual values right above the summary, which is
  usually enough to see what broke without extra digging.
- **deselected** — a test exists but wasn't run on purpose (this is how the
  `perf` marker works — it stays out of the default run, see above).
- **error** — something failed outside the test body (setup/fixture), not a
  failed assertion.

With `-v`, each line is `tests/file.py::test_name PASSED/FAILED` — makes it
immediate which test, in which file, broke.

### Test types in this repo

| File | Type | What it checks |
|---|---|---|
| `test_text_verification.py`, `test_natal_chart_reference.py`, `test_geocode_*.py` | Unit | One function, called directly |
| `test_api_deterministic_routes.py` | Integration | Non-LLM routes (chart calculation, synastry, geocoding) |
| `test_api_llm_routes.py` | Integration | LLM-backed routes, with the LLM replaced by a fake adapter — checks the contract (status code, response shape, prompt built from real data), never real generated text |
| `test_api_functional_flows.py` | Functional | Chains of several requests in sequence, the way the frontend actually calls the API |
| `test_perf.py` | Performance | Math timing budgets (natal chart, progressed synastry) and a 50-concurrent-request load check on `/api/chart/calculate` |

### Performance tests specifically

These don't run with a plain `pytest tests/` — they're marked `perf` and
excluded via `pytest.ini`. Run them explicitly:

```bash
venv/bin/python -m pytest tests/test_perf.py -m perf -v -s
```

A failure here reports the actual measured number next to the budget, e.g.:

```
AssertionError: calculate_planet_positions median 0.412s exceeds budget 0.3s over 20 runs — possible perf regression
```

so it's not just pass/fail — you get the concrete timing that tripped the
threshold. See `plans/testing-plan-minimum.md` for the full testing plan and
the reasoning behind the thresholds.
