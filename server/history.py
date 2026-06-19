"""Persistent history of recent analyses.

Saves last 20 entries to `output/.history.json` with a tiny thumbnail so the
history view can show previews and reload prior runs.
"""

from __future__ import annotations

import base64
import io
import json
import time
import uuid
from pathlib import Path

from PIL import Image

from server.config import OUTPUT_DIR

HISTORY_FILE = OUTPUT_DIR / ".history.json"
MAX_ENTRIES = 20
THUMB_SIZE = (240, 160)


def _make_thumbnail(image_path: Path) -> str:
    """Return a data: URL thumbnail (~240×160) or empty string on failure."""
    try:
        img = Image.open(image_path).convert("RGB")
        img.thumbnail(THUMB_SIZE)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=72)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return ""


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


def add_entry(image_path: Path, result: dict) -> dict:
    store = _load()
    entry = {
        "id": uuid.uuid4().hex[:12],
        "timestamp": time.time(),
        "image_name": image_path.name,
        "thumbnail": _make_thumbnail(image_path),
        "title": result.get("title", "Circuit"),
        "description": result.get("description", ""),
        "total_count": result.get("total_count", 0),
        "category_count": len(result.get("components", [])),
        "elapsed_s": result.get("_meta", {}).get("elapsed_s"),
        "result": result,
    }
    # Newest first, capped at MAX_ENTRIES
    store["entries"].insert(0, entry)
    store["entries"] = store["entries"][:MAX_ENTRIES]
    _save(store)
    return entry


def list_entries() -> list[dict]:
    """Lightweight list (no full result payload)."""
    store = _load()
    return [
        {k: v for k, v in e.items() if k != "result"}
        for e in store.get("entries", [])
    ]


def get_entry(entry_id: str) -> dict | None:
    store = _load()
    for e in store.get("entries", []):
        if e.get("id") == entry_id:
            return e
    return None


def update_cost(entry_id: str, cost_data: dict) -> bool:
    """Attach a cost-analysis result to an existing history entry."""
    store = _load()
    for e in store.get("entries", []):
        if e.get("id") == entry_id:
            e["cost"] = cost_data
            _save(store)
            return True
    return False


def delete_entry(entry_id: str) -> bool:
    store = _load()
    before = len(store["entries"])
    store["entries"] = [e for e in store["entries"] if e.get("id") != entry_id]
    if len(store["entries"]) != before:
        _save(store)
        return True
    return False


def clear_all() -> None:
    _save({"entries": []})
