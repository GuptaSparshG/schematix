"""History for the STL → 2D drawing service.

Independent from circuit-analysis history. Stored in `output/stl/.history.json`.
Saves last 20 generated drawings with metadata; the rendered PNG already lives
in `output/stl/<file>.png` and is referenced by path.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from server.draft_studio.renderer import STL_OUT_DIR

HISTORY_FILE = STL_OUT_DIR / ".history.json"
MAX_ENTRIES = 20


def _load() -> dict:
    if not HISTORY_FILE.exists():
        return {"entries": []}
    try:
        return json.loads(HISTORY_FILE.read_text())
    except Exception:
        return {"entries": []}


def _save(store: dict) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(store))


def add_entry(stl_filename: str, output_filename: str, params: dict) -> dict:
    store = _load()
    entry = {
        "id": uuid.uuid4().hex[:12],
        "timestamp": time.time(),
        "stl_filename": stl_filename,            # original filename uploaded
        "output_filename": output_filename,      # rendered PNG filename in output/stl/
        "preview_url":  f"/api/stl/output/{output_filename}",
        "drawn_by":   params.get("drawn_by", "Engineer"),
        "line_width": params.get("line_width", 1.0),
        "dpi":        params.get("dpi", 250),
    }
    store["entries"].insert(0, entry)
    store["entries"] = store["entries"][:MAX_ENTRIES]
    _save(store)
    return entry


def list_entries() -> list[dict]:
    return _load().get("entries", [])


def get_entry(entry_id: str) -> dict | None:
    for e in list_entries():
        if e.get("id") == entry_id:
            return e
    return None


def delete_entry(entry_id: str) -> bool:
    store = _load()
    target = next((e for e in store["entries"] if e.get("id") == entry_id), None)
    if not target:
        return False
    store["entries"] = [e for e in store["entries"] if e.get("id") != entry_id]
    _save(store)
    # Best-effort delete the PNG too
    try:
        png = STL_OUT_DIR / target.get("output_filename", "")
        if png.exists():
            png.unlink()
    except OSError:
        pass
    return True


def clear_all() -> None:
    for e in list_entries():
        try:
            png = STL_OUT_DIR / e.get("output_filename", "")
            if png.exists():
                png.unlink()
        except OSError:
            pass
    _save({"entries": []})
