"""Gemini call + JSON parsing (with repair for truncated responses)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import google.generativeai as genai
from PIL import Image

from server.config import MODEL_NAME, PROMPT


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


def analyze_image(image_path: Path, api_key: str) -> dict:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(MODEL_NAME)
    img = Image.open(image_path)
    response = model.generate_content(
        [PROMPT, img],
        generation_config={
            "temperature": 0.0,           # greedy
            "top_p": 1.0,
            "top_k": 1,                   # always pick the top token
            "max_output_tokens": 16384,
            "response_mime_type": "application/json",
        },
    )
    try:
        return parse_response(response.text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"{exc}\n--- raw model response ---\n{response.text[:1000]}"
        ) from exc