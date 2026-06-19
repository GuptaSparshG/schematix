"""Schematix FastAPI app.

Hosts two services under one HTTP API:
  • Circuit Analyzer  — /api/analyze, /api/cost-analysis, /api/history*, /api/export/csv
  • Draft Studio      — /api/stl/*   (routes live in server/draft_studio/)

Plus:
  GET  /                    serves the SPA from analyser-ui/
  GET  /<file>              static frontend assets
  GET  /api/health          liveness probe

Run with:
    python -m server                            # opens browser at http://localhost:8000
    HOST=0.0.0.0 PORT=8080 python -m server
"""

from __future__ import annotations

import base64
import csv
import io
import os
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from server.draft_studio import router as draft_studio_router

from server import (
    OUTPUT_DIR,
    PROJECT_ROOT,
    analyze_image,
    estimate_costs,
    export_json,
    load_api_key,
)
from server import history
from server.config import WEB_DIR

app = FastAPI(title="Schematix", version="1.0.0")

_origins_raw = os.environ.get("ALLOWED_ORIGINS", "*").strip()
_allowed_origins = ["*"] if _origins_raw == "*" else [o.strip() for o in _origins_raw.split(",") if o.strip()]

# Default cost-analysis mode — configurable via .env (COST_GROUNDED=true/false).
# true  → real Google-Search prices, ~20–40s
# false → fast estimation from Gemini training data, ~5–8s
COST_GROUNDED_DEFAULT = os.environ.get("COST_GROUNDED", "true").lower() in ("true", "1", "yes", "on")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- static frontend (analyser-ui/) -------------------------------------

@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


# Catch-all for static files (must come after all /api routes are declared).
def _register_static_route() -> None:
    @app.get("/{filename:path}", include_in_schema=False)
    def static_files(filename: str):
        if filename.startswith("api/"):
            raise HTTPException(404)
        target = WEB_DIR / filename
        if target.exists() and target.is_file():
            return FileResponse(target)
        raise HTTPException(404)


# --- API: health --------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# --- API: analyze --------------------------------------------------------

class AnalyzeRequest(BaseModel):
    sample: Optional[str] = None
    image_b64: Optional[str] = None
    filename: Optional[str] = None
    api_key: Optional[str] = None


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    api_key = (req.api_key or "").strip() or load_api_key()
    if not api_key:
        raise HTTPException(
            400,
            "No API key. Set GEMINI_API_KEY / GOOGLE_API_KEY in .env or paste a key.",
        )

    if req.sample:
        if ".." in req.sample or "/" in req.sample:
            raise HTTPException(400, "Invalid sample name")
        path = INPUT_DIR / req.sample
        if not path.exists():
            raise HTTPException(404, f"Sample not found: {req.sample}")
        return _run(path, api_key)

    if req.image_b64:
        try:
            blob = base64.b64decode(req.image_b64.split(",", 1)[-1])
        except Exception as exc:
            raise HTTPException(400, f"Bad base64: {exc}") from exc
        suffix = Path(req.filename or "upload.png").suffix or ".png"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fh:
            fh.write(blob)
            tmp_path = Path(fh.name)
        try:
            save_stem = Path(req.filename or "upload").stem
            return _run(tmp_path, api_key, save_stem=save_stem)
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    raise HTTPException(400, "Provide either 'sample' or 'image_b64' in body.")


def _run(image_path: Path, api_key: str, save_stem: Optional[str] = None) -> JSONResponse:
    import traceback
    started = time.time()
    try:
        data = analyze_image(image_path, api_key)
    except Exception as exc:
        traceback.print_exc()
        msg = str(exc)
        if "503" in msg or "UNAVAILABLE" in msg or "overload" in msg.lower():
            msg = "Gemini is overloaded right now (503). Please try again in a few seconds."
        return JSONResponse({"error": msg}, status_code=500)
    elapsed = round(time.time() - started, 2)
    data["_meta"] = {"elapsed_s": elapsed, "image": image_path.name}

    try:
        stem = save_stem or image_path.stem
        out = OUTPUT_DIR / f"{stem}.json"
        export_json(data, out)
        data["_meta"]["saved_to"] = str(out.relative_to(PROJECT_ROOT))
    except Exception:
        pass

    # Persist to history (last 20)
    try:
        entry = history.add_entry(image_path, data)
        data["_meta"]["history_id"] = entry["id"]
    except Exception as exc:
        print(f"[history] save failed: {exc}")

    return JSONResponse(data)


# --- API: history --------------------------------------------------------

@app.get("/api/history")
def history_list() -> list[dict]:
    return history.list_entries()


@app.get("/api/history/{entry_id}")
def history_get(entry_id: str):
    entry = history.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "History entry not found")
    return entry


@app.delete("/api/history/{entry_id}")
def history_delete(entry_id: str):
    ok = history.delete_entry(entry_id)
    if not ok:
        raise HTTPException(404, "History entry not found")
    return {"deleted": entry_id}


@app.delete("/api/history")
def history_clear():
    history.clear_all()
    return {"cleared": True}


# --- API: cost analysis --------------------------------------------------

class CostRequest(BaseModel):
    components: list[dict] = []
    api_key: Optional[str] = None
    grounded: bool = COST_GROUNDED_DEFAULT   # default set by COST_GROUNDED in .env
    history_id: Optional[str] = None         # if present, cost is saved into that history entry


@app.post("/api/cost-analysis")
def cost_analysis(req: CostRequest):
    api_key = (req.api_key or "").strip() or load_api_key()
    if not api_key:
        raise HTTPException(400, "No API key.")
    if not req.components:
        raise HTTPException(400, "No components — run an analysis first.")

    import traceback
    started = time.time()
    try:
        result = estimate_costs(req.components, api_key, grounded=req.grounded)
    except Exception as exc:
        traceback.print_exc()
        msg = str(exc)
        if "503" in msg or "UNAVAILABLE" in msg or "overload" in msg.lower():
            msg = "Gemini is overloaded right now (503). Please try again in a few seconds."
        return JSONResponse({"error": msg}, status_code=500)
    result["_meta"] = {"elapsed_s": round(time.time() - started, 2)}

    # Persist into the matching history entry, if any
    if req.history_id:
        try:
            history.update_cost(req.history_id, result)
        except Exception as exc:
            print(f"[history] cost save failed: {exc}")

    return JSONResponse(result)


# --- API: export ---------------------------------------------------------

@app.post("/api/export/csv")
def export_csv_route(payload: dict):
    components = payload.get("components", [])
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Category", "Label", "Value", "Type/Notes"])
    for cat in components:
        cname = cat.get("category", "")
        for item in cat.get("items", []):
            writer.writerow([cname, item.get("label", ""), item.get("value", ""), item.get("type", "")])
    meta = payload.get("_meta", {})
    base = Path(meta.get("image", "bom")).stem or "bom"
    filename = f"{base}.csv"
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Mount the Draft Studio service (its own routes live in server/draft_studio/)
app.include_router(draft_studio_router)

# Register the static catch-all AFTER all /api/* routes.
_register_static_route()


# --- entrypoint ----------------------------------------------------------

def _open_browser(url: str, delay: float = 1.2) -> None:
    def _open() -> None:
        time.sleep(delay)
        webbrowser.open(url)
    threading.Thread(target=_open, daemon=True).start()


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    url = f"http://{host}:{port}"
    print(f"\n  🌐  Circuit Analyzer UI: {url}\n")
    if os.environ.get("NO_BROWSER") != "1":
        _open_browser(url)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
