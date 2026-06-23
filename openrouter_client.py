"""OpenRouter API client — modelled exactly on the request structure in example.txt.

example.txt POSTs to https://openrouter.ai/api/v1/chat/completions with an
Authorization: Bearer <KEY> header and a JSON body containing `model` and
`messages`, then reads choices[0].message.content. We mirror that here with
httpx.AsyncClient.
"""
import json
import re

import httpx
from fastapi import HTTPException

from config import settings

SYSTEM_PROMPT = """Du bist ein präziser Ernährungsberater-Bot. Analysiere den folgenden Text und extrahiere die Lebensmittel, deren geschätztes Gewicht, Kalorien (kcal) und Protein (g).
Antworte AUSSCHLIESSLICH im folgenden JSON-Format ohne Markdown-Wrapper:
{
  "items": [
    {"name": "Nudeln gekocht", "amount": "100g", "kcal": 130, "protein": 5.0},
    {"name": "Faschiertes vom Rind", "amount": "50g", "kcal": 125, "protein": 10.0}
  ],
  "total_kcal": 255,
  "total_protein": 15.0
}
Wenn keine Mengenangabe vorhanden ist, schätze eine realistische Standardportion."""


def _extract_json(content: str) -> dict:
    """Pull a JSON object out of the model response, tolerating markdown fences."""
    content = content.strip()
    # Strip ```json ... ``` fences if the model added them anyway.
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL)
    if fence:
        content = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", content, re.DOTALL)
        if brace:
            content = brace.group(0)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=502,
            detail="KI-Antwort konnte nicht als JSON gelesen werden.",
        )


def _normalize(data: dict) -> dict:
    """Coerce types and recompute totals defensively."""
    items = []
    for it in data.get("items", []) or []:
        try:
            kcal = int(round(float(it.get("kcal", 0) or 0)))
        except (TypeError, ValueError):
            kcal = 0
        try:
            protein = round(float(it.get("protein", 0) or 0), 1)
        except (TypeError, ValueError):
            protein = 0.0
        items.append(
            {
                "name": str(it.get("name", "Unbekannt")),
                "amount": str(it.get("amount", "")),
                "kcal": kcal,
                "protein": protein,
            }
        )
    total_kcal = sum(i["kcal"] for i in items)
    total_protein = round(sum(i["protein"] for i in items), 1)
    return {"items": items, "total_kcal": total_kcal, "total_protein": total_protein}


async def analyze_meal(raw_text: str) -> dict:
    headers = {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": raw_text},
        ],
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(settings.OPENROUTER_URL, headers=headers, json=body)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"OpenRouter-Fehler: {exc.response.status_code}",
            )
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="OpenRouter nicht erreichbar.")

    payload = resp.json()
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502, detail="Unerwartete KI-Antwortstruktur.")

    return _normalize(_extract_json(content))
