"""FastAPI routes for the Draft Studio service (STL → 2D drawings)."""

from __future__ import annotations

import traceback
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from server.draft_studio import history
from server.draft_studio.renderer import STL_OUT_DIR, generate_drawing

router = APIRouter(prefix="/api/stl", tags=["draft-studio"])


@router.post("/generate")
async def stl_generate(
    file: UploadFile = File(...),
    drawn_by: str = Form("Engineer"),
    line_width: float = Form(1.0),
    dpi: int = Form(250),
):
    if not file.filename.lower().endswith(".stl"):
        raise HTTPException(400, "Only .stl files are supported.")

    blob = await file.read()
    base_name = Path(file.filename).stem
    try:
        out_path = generate_drawing(
            blob, name=base_name, drawn_by=drawn_by,
            dpi=int(dpi), line_width=float(line_width),
        )
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(500, f"STL rendering failed: {exc}") from exc

    try:
        entry = history.add_entry(
            stl_filename=file.filename,
            output_filename=out_path.name,
            params={"drawn_by": drawn_by, "line_width": float(line_width), "dpi": int(dpi)},
        )
    except Exception as exc:
        print(f"[draft-studio] history save failed: {exc}")
        entry = None

    return {
        "filename":     out_path.name,
        "preview_url":  f"/api/stl/output/{out_path.name}",
        "download_url": f"/api/stl/output/{out_path.name}?download=1",
        "history_id":   entry["id"] if entry else None,
    }


@router.get("/output/{filename}")
def stl_output(filename: str, download: int = 0):
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    path = STL_OUT_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Not found")
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'} if download else {}
    return FileResponse(path, headers=headers)


@router.get("/history")
def history_list() -> list[dict]:
    return history.list_entries()


@router.get("/history/{entry_id}")
def history_get(entry_id: str):
    e = history.get_entry(entry_id)
    if not e:
        raise HTTPException(404, "Not found")
    return e


@router.delete("/history/{entry_id}")
def history_delete(entry_id: str):
    if not history.delete_entry(entry_id):
        raise HTTPException(404, "Not found")
    return {"deleted": entry_id}


@router.delete("/history")
def history_clear():
    history.clear_all()
    return {"cleared": True}
