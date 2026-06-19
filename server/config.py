"""Paths, model config, prompt, and API-key helpers."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "input"
OUTPUT_DIR = PROJECT_ROOT / "output"
WEB_DIR = PROJECT_ROOT / "analyser-ui"
KEY_FILE = Path.home() / ".circuit-analyzer-key"

MODEL_NAME = "gemini-2.5-flash-lite"

CATEGORIES = [
    "Resistors", "Capacitors", "Diodes", "Transistors", "ICs",
    "Transformers", "LEDs", "Switches", "Zener Diodes", "Potentiometers",
    "Inductors", "Connectors", "Fuses", "Relays", "Crystals", "Other",
]

PROMPT = """You are an expert electronics engineer analyzing a circuit diagram image.

Identify EVERY component visible in the diagram. Be thorough — count each instance,
even when components are repeated. Read labels and values carefully (e.g. "R1 = 10kΩ",
"C3 100nF", "Q2 BC547").

Return ONLY a JSON object (no prose, no markdown fences) with this exact structure:

{
  "title": "<short circuit name>",
  "description": "<one-sentence description of what the circuit does>",
  "components": [
    {
      "category": "<one of: Resistors, Capacitors, Diodes, Transistors, ICs, Transformers, LEDs, Switches, Zener Diodes, Potentiometers, Inductors, Connectors, Fuses, Relays, Crystals, Other>",
      "items": [
        {"label": "<reference designator e.g. R1>", "value": "<value e.g. 10kΩ or empty string>", "type": "<part type/notes e.g. carbon film or empty string>"}
      ]
    }
  ],
  "total_count": <integer total of all items>,
  "summary": "<2-3 sentence technical summary of the circuit's operation>"
}

Rules:
- Include a category only if at least one item is present.
- Every item must have label, value, and type fields (use empty string if unknown).
- total_count must equal the sum of items across all categories.
- Output valid JSON only. No markdown, no commentary."""


def load_api_keys() -> list[str]:
    """Return every configured API key — primary first, then fallbacks.

    Sources (in order, deduplicated):
      • GEMINI_API_KEYS=key1,key2,key3   (comma-separated)
      • GEMINI_API_KEY / GOOGLE_API_KEY  (primary)
      • GEMINI_API_KEY_2 / _3 / _4 / _5  (numbered fallbacks)
      • GEMINI_API_KEY_FALLBACK
      • ~/.circuit-analyzer-key          (if nothing else set)
    """
    keys: list[str] = []

    def _add(val) -> None:
        if val and str(val).strip() and str(val).strip() not in keys:
            keys.append(str(val).strip())

    for part in os.environ.get("GEMINI_API_KEYS", "").split(","):
        _add(part)

    _add(os.environ.get("GEMINI_API_KEY"))
    _add(os.environ.get("GOOGLE_API_KEY"))
    for n in (2, 3, 4, 5):
        _add(os.environ.get(f"GEMINI_API_KEY_{n}"))
    _add(os.environ.get("GEMINI_API_KEY_FALLBACK"))

    if not keys and KEY_FILE.exists():
        _add(KEY_FILE.read_text())

    return keys


def load_api_key() -> str:
    """Return only the primary key (first in chain)."""
    keys = load_api_keys()
    return keys[0] if keys else ""


_RETRYABLE_TOKENS = (
    "429", "RESOURCE_EXHAUSTED", "quota",
    "503", "UNAVAILABLE", "overload",
)


def is_retryable_error(exc: BaseException) -> bool:
    """True if this error means 'try the next key'."""
    msg = str(exc).lower()
    return any(tok.lower() in msg for tok in _RETRYABLE_TOKENS)


def friendly_error(exc: BaseException) -> str:
    """Scrub provider/model names out and return a short user-facing message."""
    msg = str(exc)
    low = msg.lower()
    if "429" in low or "quota" in low or "resource_exhausted" in low:
        return "Daily request limit reached. Please try again later, or add a fallback key in .env."
    if "503" in low or "unavailable" in low or "overload" in low:
        return "Service is busy right now. Please try again in a few seconds."
    if "401" in low or "permission" in low or "api key not valid" in low or "invalid api key" in low:
        return "Invalid API key. Please check your .env configuration."
    if "timeout" in low or "deadline" in low:
        return "The request timed out. Please try again."
    # Generic fallback — keep it short, no model / provider / URLs.
    return "The request failed. Please try again."


def save_key(key: str) -> None:
    KEY_FILE.write_text(key.strip())
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass
