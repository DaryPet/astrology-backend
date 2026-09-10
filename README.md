# Astrology Backend

FastAPI backend for an astrology app: natal charts, synastry, transits,
secondary progressions, progressed synastry, a sports-match daily forecast,
and LLM-based interpretations grounded in a RAG corpus of astrology books.
This repo is the **backend only** — the frontend lives in a separate
repository.

## Features

- ✨ Natal chart calculation (planet positions, signs, houses, ascendant/MC, Pars Fortuna)
- 🔮 Aspects between planets, with orb and applying/separating detail
- 🤝 Synastry between two charts, plus a relationship-type breakdown
- 🌊 Transits, secondary progressions and progressed synastry
- 🎾 Daily forecast for sports matches — event-chart method (John Frawley,
  *Sports Astrology*) with a hybrid dignity layer; the result card is built
  deterministically from the calculation, without an LLM call
- 🎯 LLM interpretation of every chart type, backed by RAG search over a
  corpus of astrology books (chunked, embedded, searched per query)
- 🛡️ Post-generation checks: planet signs, houses and aspect types named in
  the LLM text are compared against the calculated chart, and invented
  positions are corrected or logged (`app/services/text_verification.py`)
- 💬 Chat with an "astrologer" grounded in a specific chart (natal, synastry,
  progressions, progressed synastry)
- 📡 Streaming responses (Server-Sent Events) for the analysis endpoints
- 🌐 Output languages: English, Russian, Ukrainian
- 📍 City autocomplete and timezone lookup for birth/event locations

## Tech stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.9 |
| API framework | FastAPI + Pydantic v2 |
| Astrology engine | pyswisseph (Swiss Ephemeris) |
| Database / storage / vector search | Supabase (Postgres) |
| Auth | Supabase Auth — bearer token checked in `app/auth.py` |
| LLM interpretation | Provider-agnostic adapter (`app/services/llm_adapter.py`) — DeepSeek in production, OpenRouter as fallback |
| RAG book ingestion | PyMuPDF / python-docx / EbookLib / BeautifulSoup / pytesseract (parsing) + sentence-transformers (embeddings) |
| Geocoding | LocationIQ (autocomplete/search) + timezonefinder |
| Rate limiting | slowapi |

## LLM providers

The provider is chosen with `LLM_PROVIDER` in `.env`:

| `LLM_PROVIDER` | Adapter | Notes |
|---|---|---|
| `deepseek` | `DeepSeekAdapter` | Used in production. Needs `DEEPSEEK_API_KEY`. |
| `openrouter` | `OpenRouterAdapter` | Any OpenRouter model; default model from `OPENROUTER_MODEL`. |
| `claude` | `ClaudeAdapter` | Needs `ANTHROPIC_API_KEY` and the `anthropic` package (not in `requirements.txt`). |
| `gemini` | `GeminiAdapter` | Needs `GEMINI_API_KEY` and the Google Generative AI package (not in `requirements.txt`). |
| `ollama` | `OllamaAdapter` | Local Ollama at `OLLAMA_BASE_URL`. |

**Fallback:** when `LLM_PROVIDER=deepseek` and `OPENROUTER_API_KEY` is set,
DeepSeek is wrapped in `FallbackAdapterWrapper`. If DeepSeek raises or
returns an empty/`Error:` response, the request is retried on OpenRouter with
`openai/gpt-5.6-luna` (`FALLBACK_MODEL`). For streaming, the fallback only
kicks in if the very first chunk fails.

**Set `LLM_PROVIDER` explicitly.** The default in `app/core/config.py` is
`openai`, which has no adapter — every LLM call then returns the
"LLM not configured" stub.

## Running locally

Requires Python 3.9.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in the variables listed below
uvicorn app.main:app --reload
```

API: http://localhost:8000/api
Swagger UI: http://localhost:8000/docs

`ephe/` holds the Swiss Ephemeris asteroid data (`seas_*.se1`, used for
Chiron). `app/swephelper.py` points pyswisseph at this folder on import and
prints a warning if the folder is missing.

## Environment variables (`.env`)

All settings are read by `app/core/config.py`:

```env
PROJECT_NAME="Astrology API"

# Supabase: database, book storage, vector search, auth
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-key

# LLM
LLM_PROVIDER=deepseek              # deepseek | openrouter | claude | gemini | ollama
DEEPSEEK_API_KEY=...
OPENROUTER_API_KEY=...             # also enables the OpenRouter fallback
OPENROUTER_MODEL=anthropic/claude-sonnet-4.5
ANTHROPIC_API_KEY=...              # only for LLM_PROVIDER=claude
GEMINI_API_KEY=...                 # only for LLM_PROVIDER=gemini
OLLAMA_BASE_URL=http://localhost:11434

# Geocoding (city autocomplete / place search)
LOCATIONIQ_ACCESS_TOKEN=...
```

## API endpoints

All routes are mounted under `/api` (`app/main.py`).

- 🔒 = requires `Authorization: Bearer <Supabase access token>`; without a
  header the API returns 403, with an invalid token 401.
- **Stream** = accepts `"stream": true` in the body and then responds with
  Server-Sent Events (`text/event-stream`) instead of plain JSON.

### Calculation (no LLM)

| Method | Path | Auth | Rate limit | Description |
|---|---|---|---|---|
| POST | `/api/chart/calculate` | — | — | Natal chart |
| POST | `/api/synastry/direct` | — | — | Synastry between two sets of birth data |
| POST | `/api/progressions` | 🔒 | 15/min | Secondary progressions |
| POST | `/api/transits` | 🔒 | 20/min | Transits for a target date |
| POST | `/api/progressed-synastry` | 🔒 | 15/min | Progressed synastry for two partners |
| POST | `/api/daily-forecast` | 🔒 | 5/min | Sports-match forecast from the event chart (time + place of the match start) |

### Interpretation (LLM + RAG)

| Method | Path | Auth | Rate limit | Stream | Description |
|---|---|---|---|---|---|
| POST | `/api/analysis/full` | — | — | ✅ | Full natal chart analysis |
| POST | `/api/analysis/planet` | 🔒 | 10/min | ✅ | Analysis of a single planet |
| POST | `/api/analysis/query` | 🔒 | 10/min | — | Free-form astrology question |
| POST | `/api/analysis/query-with-chart` | 🔒 | 10/min | — | Free-form question with chart context |
| POST | `/api/analysis/chat` | 🔒 | 20/min | ✅ | Chat grounded in a chart (`chart_data.type` selects natal / synastry / progressions / progressed synastry) |
| POST | `/api/analysis/synastry/full` | 🔒 | 5/min | ✅ | Full synastry analysis |
| POST | `/api/synastry/aspect` | 🔒 | 15/min | ✅ | Analysis of one synastry aspect |
| POST | `/api/synastry/relationship-types` | 🔒 | 10/min | ✅ | Relationship-type percentages from a finished synastry analysis |
| POST | `/api/analysis/progressions` | 🔒 | 5/min | ✅ | Progressions analysis |
| POST | `/api/analysis/transits` | 🔒 | 5/min | ✅ | Transits analysis |
| POST | `/api/analysis/progressed-synastry` | 🔒 | 5/min | ✅ | Progressed synastry analysis |
| POST | `/api/analysis/progressed-synastry/aspect` | 🔒 | 15/min | ✅ | Analysis of one progressed synastry aspect |
| POST | `/api/generate-summary` | — | — | — | Short (~500 characters) summary of an analysis text |

### Other

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/api/geocode/autocomplete?q=&lang=` | — | City autocomplete (LocationIQ) |
| GET | `/api/geocode/coordinates?lat=&lon=` | — | Timezone for coordinates |
| POST | `/api/books/process?filename=` | — | Ingest a book: download from Supabase storage, parse, chunk, embed, save |
| GET | `/api/auth/me` | 🔒 | Current user (id, email) |

`language` in request bodies accepts `en`, `ru` or `uk`; any other value
falls back to English. Most analysis requests default to `ru` when
`language` is omitted.

Full request/response shapes: `/docs` (Swagger UI) once the server is running.

If a frontend build exists at `../../frontend/dist` relative to `app/`, the
app also serves it (`/assets` plus an SPA catch-all); otherwise `GET /`
returns `{"message": "Astrology API"}`.

## Project structure

```
.
├── app/
│   ├── main.py                  # FastAPI app: CORS, rate limiter, routers, SPA fallback
│   ├── auth.py                  # Supabase bearer-token check, /auth/me
│   ├── swephelper.py            # Swiss Ephemeris initialisation (ephe/ path)
│   ├── api/endpoints.py         # All /api routes
│   ├── core/config.py           # Settings loaded from .env
│   ├── schemas/                 # Pydantic request/response models
│   ├── services/
│   │   ├── analysis_service/    # Natal, progressions, transits, progressed synastry,
│   │   │                        # chat, query and summary pipelines (RAG + LLM + streaming)
│   │   ├── synastry_service.py              # Synastry analysis, aspect analysis, synastry chat
│   │   ├── synastry_relationship_service.py # Relationship-type breakdown
│   │   ├── daily_forecast_service.py        # Sports-match event-chart forecast
│   │   ├── llm_adapter.py                   # LLM providers + OpenRouter fallback
│   │   ├── prompt_templates/                # Prompt texts per chart type (en/ru/uk)
│   │   ├── prompt_labels.py                 # Localised labels used inside prompts
│   │   ├── text_verification.py             # Checks LLM text against the calculated chart
│   │   ├── search_service.py                # RAG search (embeddings + Supabase hybrid search)
│   │   └── book_parser.py, book_processor.py, chunker.py  # Book ingestion
│   └── utils/
│       ├── astrology_v2.py      # Astrology math: positions, houses, aspects, synastry,
│       │                        # progressions, transits, progressed synastry
│       └── horary_tables.py     # Rulerships, dignities, antiscia (used by the daily forecast)
├── ephe/                        # Swiss Ephemeris data files (do not hand-edit)
├── tests/                       # pytest suite + standalone synastry evaluation scripts
├── scripts/                     # Git hook helpers
├── Dockerfile                   # Container build — see "Running with Docker"
├── .dockerignore                # Keeps venv/tests/docs out of the build context
├── pytest.ini
└── requirements.txt
```

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

The API is then on http://localhost:8080/api (Swagger UI at `/docs`).

Without `--env-file .env` the container still starts and serves chart
calculation, but anything touching Supabase, an LLM or geocoding will fail —
those read their keys from the environment.

### Inspect and stop

```bash
docker logs -f astro           # follow logs
docker stats --no-stream astro # memory/CPU usage
docker exec -it astro bash     # shell inside the container

docker stop astro              # stop
docker start astro             # start again
docker rm -f astro             # stop and delete the container
docker rmi astrology-backend   # delete the image
```

### What the image does and why

- **The embedding model is baked in at build time.** `search_service.py` and
  `book_processor.py` load `paraphrase-multilingual-MiniLM-L12-v2` via
  sentence-transformers. If it were not in the image, every cold start would
  download it from HuggingFace first.
- **`HF_HUB_OFFLINE=1` is set** so sentence-transformers never calls
  huggingface.co at runtime. Without it the container phones home to check
  for model updates on every start, and fails outright when HuggingFace is
  unreachable.
- **torch is installed from the CPU wheel index.** The default wheel pulls in
  CUDA (~2 GB), which is dead weight without a GPU.
- **tesseract-ocr is kept in the image** — `pytesseract` shells out to it for
  scanned book pages that have no text layer.
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
Memory                  2 GiB
CPU                     1
Request timeout         900     # default 300 cuts long analyses off mid-generation
Max concurrent/instance 8       # default 80 overloads one container
Min instances           0
```

## Testing

### Running tests

Run the default suite (unit + integration + functional; performance tests
are excluded by default, see below):

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

The API tests block real outbound network calls (`tests/conftest.py`), so
they don't hit Supabase, LocationIQ or an LLM provider.

### Reading the output

Without `-v`, pytest prints one character per test: `.` = passed, `F` =
failed, `E` = error before/around the test itself (e.g. a fixture broke, not
necessarily the logic under test). The final summary line looks like:

```
79 passed, 3 deselected, 1 failed in 7.30s
```

- **passed** — every `assert` in the test held.
- **failed** — an `assert` didn't match reality; pytest prints the file:line
  and the expected-vs-actual values right above the summary.
- **deselected** — a test exists but wasn't run on purpose (this is how the
  `perf` marker works — it stays out of the default run).
- **error** — something failed outside the test body (setup/fixture), not a
  failed assertion.

With `-v`, each line is `tests/file.py::test_name PASSED/FAILED`, so it's
immediately clear which test, in which file, broke.

### Test types in this repo

| File | Type | What it checks |
|---|---|---|
| `test_text_verification.py`, `test_natal_chart_reference.py`, `test_geocode_*.py` | Unit | One function, called directly |
| `test_api_deterministic_routes.py` | Integration | Non-LLM routes (chart calculation, synastry, geocoding) |
| `test_api_llm_routes.py` | Integration | LLM-backed routes, with the LLM replaced by a fake adapter — checks the contract (status code, response shape, prompt built from real data), never real generated text |
| `test_api_functional_flows.py` | Functional | Chains of several requests in sequence, the way the frontend calls the API |
| `test_perf.py` | Performance | Math timing budgets (natal chart, progressed synastry) and a 50-concurrent-request load check on `/api/chart/calculate` |

`tests/eval_synastry*.py`, `tests/judge_synastry.py` and
`tests/check_aspect_coverage.py` are standalone evaluation scripts for
synastry output; pytest does not collect them.

### Performance tests specifically

These don't run with a plain `pytest tests/` — they're marked `perf` and
excluded via `pytest.ini`. Run them explicitly:

```bash
venv/bin/python -m pytest tests/test_perf.py -m perf -v -s
```

A failure reports the actual measured number next to the budget, e.g.:

```
AssertionError: calculate_planet_positions median 0.412s exceeds budget 0.3s over 20 runs — possible perf regression
```

so you get the concrete timing that tripped the threshold, not just pass/fail.

## License

MIT
