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
