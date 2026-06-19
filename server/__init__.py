"""Backend service for the Circuit Diagram Analyzer.

Importable surface (used by analyze.py CLI and server.main FastAPI app):
    from server import analyze_image, export_csv, export_json, load_api_key, ...
"""

from server.analyzer import analyze_image, parse_response
from server.config import (
    INPUT_DIR,
    KEY_FILE,
    MODEL_NAME,
    OUTPUT_DIR,
    PROJECT_ROOT,
    PROMPT,
    friendly_error,
    is_retryable_error,
    load_api_key,
    load_api_keys,
    save_key,
)
from server.exporters import export_csv, export_json
from server.pricing import estimate_costs

__all__ = [
    "analyze_image",
    "parse_response",
    "export_csv",
    "export_json",
    "load_api_key",
    "save_key",
    "INPUT_DIR",
    "OUTPUT_DIR",
    "KEY_FILE",
    "MODEL_NAME",
    "PROMPT",
    "PROJECT_ROOT",
]