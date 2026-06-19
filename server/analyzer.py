"""Gemini call + JSON parsing (with repair for truncated responses)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import google.generativeai as genai
from PIL import Image

from server.config import MODEL_NAME, PROMPT, is_retryable_error, load_api_keys


def _repair_truncated_json(text: str) -> str:
    """Close a JSON object/array that got truncated mid-stream."""
    in_string = False
    escape = False
    stack: list[str] = []
    last_safe = -1
    for i, c in enumerate(text):
        if escape:
            escape = False
            continue
        if in_string:
            if c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]":
            if stack:
                stack.pop()
        elif c == "," and stack:
            last_safe = i
    if not stack:
        return text
    truncated = text[:last_safe] if last_safe > 0 else text
    if in_string:
        truncated += '"'
    return truncated + "".join(reversed(stack))


def parse_response(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    candidate = match.group(0) if match else cleaned
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    return json.loads(_repair_truncated_json(candidate))


def analyze_image(image_path: Path, api_key: str = "") -> dict:
    """Run vision analysis. Tries keys in order; rolls over on quota / 503."""
    # Build the key list: explicit arg first, then env-configured chain.
    keys: list[str] = []
    for k in [api_key, *load_api_keys()]:
        if k and k not in keys:
            keys.append(k)
    if not keys:
        raise RuntimeError("No API key configured.")

    img = Image.open(image_path)
    last_err: Exception | None = None

    for i, key in enumerate(keys):
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel(MODEL_NAME)
            response = model.generate_content(
                [PROMPT, img],
                generation_config={
                    "temperature": 0.0, "top_p": 1.0, "top_k": 1,
                    "max_output_tokens": 16384,
                    "response_mime_type": "application/json",
                },
            )
            try:
                return parse_response(response.text)
            except (ValueError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"Failed to parse response: {exc}\n--- raw ---\n{response.text[:1000]}"
                ) from exc
        except Exception as exc:
            last_err = exc
            if is_retryable_error(exc) and i < len(keys) - 1:
                print(f"[analyzer] key #{i+1} failed (retryable) — trying next of {len(keys)}")
                continue
            raise

    if last_err:
        raise last_err
    raise RuntimeError("No keys configured.")