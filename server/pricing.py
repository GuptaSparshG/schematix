"""Cost analysis — REAL price lookup via Gemini Google-Search grounding.

For each component we ask Gemini (with the Google Search tool enabled) to look
up current retail prices on Digi-Key, Mouser, Amazon, AliExpress, RS Components
and IndiaMART. The model returns structured JSON which we aggregate into
per-site totals and per-component minimums.

If grounding fails (quota, model not available, tool unsupported), we fall
back to Gemini estimation from training data — clearly flagged as such.
"""

from __future__ import annotations

import json
import re

import google.generativeai as genai
from google import genai as new_genai
from google.genai import types as new_types

from server.config import MODEL_NAME

PRICING_SITES = [
    "Digi-Key", "Mouser", "Amazon", "AliExpress", "RS Components", "IndiaMART",
]

GROUNDED_MODEL = "gemini-2.5-flash"          # supports Google Search grounding

PRICING_PROMPT_GROUNDED = """You are an electronics-procurement assistant with Google Search.
For EACH component listed below, search Google for current retail unit prices
(quantity = 1, USD) at these sites:
- Digi-Key
- Mouser
- Amazon
- AliExpress
- RS Components
- IndiaMART  (prices in INR — convert to USD at ~83 INR/USD)

Use search queries like "BC547 transistor digikey price", "100nF capacitor mouser",
"BC547 indiamart". Use the most recent verifiable price you find. If a site doesn't
stock the part, give a best estimate based on equivalent listings (still mark the
site name).

Return ONLY a JSON object (no markdown fences, no prose):
{
  "components": [
    {
      "label": "<from input>",
      "value": "<from input>",
      "category": "<from input>",
      "sources": [
        {"site": "Digi-Key",       "price_usd": <number>, "url": "<optional source URL>"},
        {"site": "Mouser",         "price_usd": <number>, "url": "..."},
        {"site": "Amazon",         "price_usd": <number>, "url": "..."},
        {"site": "AliExpress",     "price_usd": <number>, "url": "..."},
        {"site": "RS Components",  "price_usd": <number>, "url": "..."},
        {"site": "IndiaMART",      "price_usd": <number>, "url": "..."}
      ]
    }
  ]
}

Every component MUST appear with all 6 sites priced. Numbers only (no "$"). URLs optional.

Components to price:
"""

PRICING_PROMPT_ESTIMATE = """You are an electronics procurement expert. For each component below,
estimate realistic current retail unit prices (USD, single quantity) at these 6 sites:
Digi-Key, Mouser, Amazon, AliExpress, RS Components, IndiaMART.

Use industry knowledge and typical pricing ranges:
- Common resistors:    $0.01 – $0.15
- Ceramic capacitors:  $0.05 – $0.50
- Electrolytic caps:   $0.10 – $1.50
- Signal diodes:       $0.05 – $0.30
- Power diodes:        $0.20 – $1.50
- LEDs:                $0.10 – $0.80
- BJT transistors:     $0.10 – $0.80
- MOSFETs:             $0.30 – $2.50
- Logic ICs:           $0.40 – $2.00
- Op-amps:             $0.30 – $3.00
- Microcontrollers:    $1.50 – $15.00
- Connectors:          $0.20 – $3.00
- Crystals:            $0.30 – $2.00
- Switches:            $0.50 – $3.00
- Potentiometers:      $0.40 – $2.50
- Transformers:        $2.00 – $15.00
- Relays:              $1.00 – $5.00

Site tendencies: AliExpress and IndiaMART are usually cheapest (volume-import pricing,
50–80% below distributors). Digi-Key/Mouser/RS Components are premium with stock guarantees.
Amazon sits in the middle.

Return ONLY valid JSON (no markdown, no commentary):
{
  "components": [
    {
      "label": "<from input>",
      "value": "<from input>",
      "category": "<from input>",
      "sources": [
        {"site": "Digi-Key",       "price_usd": <number>},
        {"site": "Mouser",         "price_usd": <number>},
        {"site": "Amazon",         "price_usd": <number>},
        {"site": "AliExpress",     "price_usd": <number>},
        {"site": "RS Components",  "price_usd": <number>},
        {"site": "IndiaMART",      "price_usd": <number>}
      ]
    }
  ]
}

Every component in the input MUST appear with all 6 sites priced.

Components to price:
"""


# ── JSON helpers ────────────────────────────────────────────────────────

def _repair_json(text: str) -> str:
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


def _parse(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    # Pull the first {...} block out (grounded responses may have prose around it)
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    candidate = m.group(0) if m else cleaned
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    return json.loads(_repair_json(candidate))


def _flatten_bom(components: list[dict]) -> list[dict]:
    flat: list[dict] = []
    for cat in components:
        cname = cat.get("category", "")
        for item in cat.get("items", []):
            flat.append({
                "label": item.get("label", ""),
                "value": item.get("value", ""),
                "category": cname,
                "type": item.get("type", ""),
            })
    return flat


# ── Gemini calls ────────────────────────────────────────────────────────

def _items_text(bom: list[dict]) -> str:
    return "\n".join(
        f"- {c['label']} | {c['value'] or '(no value)'} | {c['category']}"
        for c in bom
    )


def _try_grounded(bom: list[dict], api_key: str) -> dict | None:
    """Use the new google-genai SDK with the GoogleSearch tool.
    Returns parsed JSON on success, None on failure."""
    prompt = PRICING_PROMPT_GROUNDED + _items_text(bom)
    try:
        client = new_genai.Client(api_key=api_key)
        config = new_types.GenerateContentConfig(
            tools=[new_types.Tool(google_search=new_types.GoogleSearch())],
            temperature=0.1,
            max_output_tokens=32768,
        )
        response = client.models.generate_content(
            model=GROUNDED_MODEL,
            contents=prompt,
            config=config,
        )
        text = response.text or ""
        data = _parse(text)
        if data.get("components"):
            data["_source"] = "google_search_grounded"
            return data
        print(f"[pricing] grounded returned no components; raw head: {text[:200]}")
    except Exception as exc:
        print(f"[pricing] grounded lookup failed: {exc}")
    return None


def _estimate(bom: list[dict]) -> dict:
    """Non-grounded estimation from Gemini's training data."""
    model = genai.GenerativeModel(MODEL_NAME)
    response = model.generate_content(
        PRICING_PROMPT_ESTIMATE + _items_text(bom),
        generation_config={
            "temperature": 0.2,
            "max_output_tokens": 16384,
            "response_mime_type": "application/json",
        },
    )
    data = _parse(response.text)
    data["_source"] = "estimated"
    return data


def estimate_costs(components: list[dict], api_key: str, grounded: bool = False) -> dict:
    bom = _flatten_bom(components)
    if not bom:
        return {
            "components": [],
            "total_min_cost_usd": 0.0,
            "totals_by_site": {},
            "cheapest_site": None,
            "currency": "USD",
            "source": "empty",
        }

    genai.configure(api_key=api_key)

    # Default: fast estimation (~5s). Set grounded=True to do real web search (~30s).
    data = None
    expected = len(bom)
    if grounded:
        data = _try_grounded(bom, api_key)
        if data is not None:
            got = len(data.get("components", []))
            if got < expected:
                # Grounded response was truncated / partial. Fall back so the user
                # always sees every component, not just the few that made it.
                print(f"[pricing] grounded returned {got}/{expected} components — falling back to estimation")
                data = None
    if data is None:
        data = _estimate(bom)

    # Aggregate totals
    totals_by_site: dict[str, float] = {site: 0.0 for site in PRICING_SITES}
    total_min = 0.0
    for comp in data.get("components", []):
        sources = comp.get("sources", []) or []
        if sources:
            min_src = min(sources, key=lambda s: s.get("price_usd", float("inf")))
            comp["min_price_usd"] = round(float(min_src.get("price_usd", 0)), 4)
            comp["min_site"] = min_src.get("site", "—")
            total_min += comp["min_price_usd"]
            for s in sources:
                site = s.get("site", "")
                if site in totals_by_site:
                    totals_by_site[site] += float(s.get("price_usd", 0))
        else:
            comp["min_price_usd"] = 0.0
            comp["min_site"] = "—"

    cheapest = min(
        ((s, v) for s, v in totals_by_site.items() if v > 0),
        key=lambda kv: kv[1],
        default=(None, 0.0),
    )

    data["total_min_cost_usd"] = round(total_min, 2)
    data["totals_by_site"] = {k: round(v, 2) for k, v in totals_by_site.items()}
    data["cheapest_site"] = cheapest[0]
    data["currency"] = "USD"
    data["source"] = data.pop("_source", "estimated")
    return data
