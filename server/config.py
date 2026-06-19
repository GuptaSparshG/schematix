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


def load_api_key() -> str:
    env = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if env:
        return env.strip()
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip()
    return ""


def save_key(key: str) -> None:
    KEY_FILE.write_text(key.strip())
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass
