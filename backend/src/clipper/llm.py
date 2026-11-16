"""OpenAI-compatible LLM client with JSON parsing and model fallback."""

from __future__ import annotations

import json
import re
from typing import TypeVar

from openai import APIStatusError, OpenAI
from pydantic import BaseModel, ValidationError

from clipper import config
from clipper.errors import ClipperError
from clipper.reporting import log

T = TypeVar("T", bound=BaseModel)

JSON_ONLY = "You reply with a single valid JSON object and nothing else."


def client() -> OpenAI:
    local = "localhost" in config.LLM_BASE_URL or "127.0.0.1" in config.LLM_BASE_URL
    if not config.LLM_API_KEY and not local:
        raise ClipperError("LLM_API_KEY is not set in backend/.env")
    return OpenAI(api_key=config.LLM_API_KEY or "none", base_url=config.LLM_BASE_URL,
                  max_retries=2, timeout=600)


def extract_json(text: str | None) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)   # reasoning models
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model response")
    return json.loads(text[start:end + 1])


def ask(llm: OpenAI, prompt: str, schema: type[T], temperature: float,
        system: str = JSON_ONLY) -> tuple[T, str]:
    """Try each configured model in turn until one returns valid JSON for `schema`.
    Returns (parsed_response, model_used)."""
    if not config.LLM_MODELS:
        raise ClipperError("LLM_MODEL is not set in backend/.env. Run `clipper --list-models` to pick one.")
    errors = []
    for model in config.LLM_MODELS:
        for use_json_mode in (True, False):
            try:
                kwargs = {"response_format": {"type": "json_object"}} if use_json_mode else {}
                resp = llm.chat.completions.create(
                    model=model, temperature=temperature,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": prompt}], **kwargs)
                return schema.model_validate(extract_json(resp.choices[0].message.content)), model
            except APIStatusError as e:
                # Some providers reject json mode -> retry once without it.
                if e.status_code == 400 and use_json_mode:
                    continue
                errors.append(f"{model}: HTTP {e.status_code} {str(e.message)[:200]}")
                log(f"  {model} failed (HTTP {e.status_code}); trying next model")
                break
            except (ValueError, ValidationError) as e:
                errors.append(f"{model}: bad JSON ({str(e)[:150]})")
                log(f"  {model} returned unusable JSON; {'retrying' if use_json_mode else 'trying next model'}")
    raise ClipperError("All models failed:\n  " + "\n  ".join(errors))


def list_models() -> list[tuple[str, int | str]]:
    """(model_id, context_length) for models at LLM_BASE_URL. On OpenRouter: free text models only."""
    models = client().models.list().data
    is_openrouter = "openrouter.ai" in config.LLM_BASE_URL
    rows = []
    for m in models:
        extra = m.model_extra or {}
        if is_openrouter:
            pricing = extra.get("pricing") or {}
            if not (m.id.endswith(":free") or (pricing.get("prompt") == "0" and pricing.get("completion") == "0")):
                continue
            outputs = (extra.get("architecture") or {}).get("output_modalities") or ["text"]
            if "text" not in outputs:  # music / image generators
                continue
        rows.append((m.id, extra.get("context_length") or extra.get("context_window") or ""))
    rows.sort(key=lambda r: -r[1] if isinstance(r[1], int) else 0)
    return rows
