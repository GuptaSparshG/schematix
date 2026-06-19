# CLAUDE.md — Schematix

A FastAPI + vanilla JS dashboard that hosts two services:

1. **Circuit Analyzer** — Gemini Vision identifies every component in a schematic image, then optionally web-grounds real prices from 6 sourcing sites.
2. **Draft Studio** — Renders 3D STL meshes into 2D engineering drawings (Front / Side / Top / Isometric + title block).

## Project layout

```
circuit-analyser/
├── analyser-ui/                    # Frontend (HTML / CSS / JS, no Python)
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── server/                         # FastAPI backend
│   ├── __init__.py                 # exports analyze_image, estimate_costs, etc.
│   ├── __main__.py                 # `python -m server` entry point
│   ├── main.py                     # FastAPI app + Circuit Analyzer routes
│   ├── config.py                   # paths, model name, prompt, key loader
│   ├── analyzer.py                 # Gemini Vision call + JSON repair
│   ├── pricing.py                  # cost analysis (grounded or estimated)
│   ├── history.py                  # circuit-analysis history (last 20)
│   ├── exporters.py                # CSV / JSON writers
│   └── draft_studio/               # Self-contained STL → 2D service
│       ├── __init__.py             # exports `router`
│       ├── renderer.py             # matplotlib + shapely pipeline
│       ├── history.py              # STL drawing history (last 20)
│       └── routes.py               # /api/stl/* APIRouter
├── analyze.py                      # CLI entry point (terminal version)
├── input/                          # Sample circuit images (CLI testing)
├── output/                         # Runtime data
│   ├── *.json                      # per-analysis exports
│   ├── .history.json               # circuit analysis history
│   └── stl/
│       ├── *.png                   # generated drawings
│       └── .history.json           # STL drawing history
├── deploy/
│   ├── nginx.conf                  # reverse proxy + TLS
│   └── schematix.service           # systemd unit
├── Dockerfile                      # multi-stage prod image
├── docker-compose.yml              # one-command run
├── .env.example                    # env vars template
├── DEPLOY.md                       # production deployment guide
├── requirements.txt
└── CLAUDE.md                       # this file
```

## Tech stack

- **Backend:** Python 3.11+ · FastAPI · uvicorn · pydantic
- **AI:** `google-generativeai` (analyze) + `google-genai` (search grounding)
- **STL render:** `numpy-stl` · `matplotlib` (headless `Agg`) · `shapely`
- **Frontend:** Bootstrap 5 + Bootstrap Icons · vanilla JS · Inter font
- **Deploy:** Docker / docker-compose / nginx / systemd (all included)

## API surface

| Method | Route | Service |
|---|---|---|
| GET  | `/api/health`               | health check |
| POST | `/api/analyze`              | Circuit Analyzer · image → components |
| POST | `/api/cost-analysis`        | Circuit Analyzer · BOM → pricing |
| POST | `/api/export/csv`           | Circuit Analyzer · BOM → CSV |
| GET  | `/api/history`              | Circuit Analyzer · list last 20 |
| GET  | `/api/history/{id}`         | Circuit Analyzer · load entry |
| DEL  | `/api/history` / `…/{id}`   | Circuit Analyzer · clear / delete |
| POST | `/api/stl/generate`         | Draft Studio · STL upload → drawing |
| GET  | `/api/stl/output/{file}`    | Draft Studio · serve PNG (or download) |
| GET  | `/api/stl/history`          | Draft Studio · list last 20 |
| GET  | `/api/stl/history/{id}`     | Draft Studio · load entry |
| DEL  | `/api/stl/history` / `…/{id}` | Draft Studio · clear / delete |

## Configuration

`.env` (copy from `.env.example`):

```
GEMINI_API_KEY=...          # required; or GOOGLE_API_KEY
HOST=0.0.0.0
PORT=8000
ALLOWED_ORIGINS=*           # comma list, or '*' for dev
NO_BROWSER=1                # skip auto-open in browser
```

## Run

```bash
# Local dev
./circuit-venv/bin/python -m server
# → http://localhost:8000

# Docker
docker compose up -d --build

# CLI (no UI)
./circuit-venv/bin/python analyze.py input/circuit-1.webp --export csv
```

See `DEPLOY.md` for production deployment with HTTPS.

## Key design decisions

- **Two services, one app.** Both live under the same FastAPI process for simpler ops, but `server/draft_studio/` is self-contained — could be split into its own service later without touching Circuit Analyzer code.
- **History per service.** Circuit history at `output/.history.json`, STL history at `output/stl/.history.json`. Each capped at 20 entries.
- **No API-key UI.** Server reads `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) from environment / `.env` only. Frontend never sees or sends a key.
- **Greedy decoding** (`temperature=0, top_k=1`) for circuit analysis so repeat runs on the same image are essentially deterministic.
- **Real prices via Gemini Google-Search grounding.** Falls back to Gemini estimation if grounding fails or returns 503. The `source` field tells the UI which mode produced the result.
- **CORS is env-driven.** `ALLOWED_ORIGINS=https://your-domain.com` in prod; `*` in dev.

## Common tasks

| Want to | Touch |
|---|---|
| Change Gemini model | `server/config.py` → `MODEL_NAME` |
| Adjust the analysis prompt | `server/config.py` → `PROMPT` |
| Change which sites are priced | `server/pricing.py` → `PRICING_SITES` |
| Switch to estimation-only cost | `server/main.py` → `CostRequest.grounded = False` |
| Restyle UI | `analyser-ui/styles.css` |
| Add a third service | New `server/<service>/` package with `routes.py` exporting `router`, then `app.include_router(...)` in `server/main.py` |