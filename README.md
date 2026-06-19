# Schematix

An engineering toolkit dashboard that hosts two services in one web app:

| Service | What it does |
|---|---|
| **Circuit Analyzer** | Upload a circuit schematic → Gemini Vision identifies every component (label, value, type), groups them by category, and can web-search real prices from Digi-Key · Mouser · Amazon · AliExpress · RS Components · IndiaMART |
| **Draft Studio** | Upload an STL mesh → get a clean 2D engineering drawing with Front / Side / Top / Isometric views and a title block (matplotlib + shapely pipeline) |

Each service has its own history (last 20 runs auto-saved, click-to-reload).

## Quick start

```bash
git clone <repo> schematix && cd schematix
python3 -m venv circuit-venv
./circuit-venv/bin/pip install -r requirements.txt

# Gemini API key
cp .env.example .env
echo 'GEMINI_API_KEY=your-key-from-aistudio.google.com/apikey' >> .env

# Run
./circuit-venv/bin/python -m server
# → opens http://localhost:8000
```

## Docker

```bash
docker compose up -d --build
```

## Deploy to production

See [DEPLOY.md](DEPLOY.md) for the full guide (Docker or systemd, with nginx + Let's Encrypt).

## CLI

For terminal use without the web UI:

```bash
./circuit-venv/bin/python analyze.py input/circuit-1.webp --export csv
```

## Project layout

See [CLAUDE.md](CLAUDE.md) for the architectural overview and the code map.