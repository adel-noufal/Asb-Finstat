import json
import re
from typing import Any

import httpx

from .config import settings


class OpenRouterError(RuntimeError):
    pass


async def chat(model: str, messages: list[dict], **kwargs: Any) -> str:
    """Single OpenRouter chat completion. `model` is always passed explicitly so
    every AI call in the pipeline can run on a different model (see config.py)."""
    if not settings.openrouter_api_key:
        raise OpenRouterError("OPENROUTER_API_KEY is not set (backend/.env)")
    payload = {"model": model, "messages": messages, **kwargs}
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(
            f"{settings.openrouter_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "X-Title": "asb-finstat",
            },
            json=payload,
        )
    if resp.status_code != 200:
        raise OpenRouterError(f"OpenRouter {resp.status_code}: {resp.text[:500]}")
    return resp.json()["choices"][0]["message"]["content"]


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


async def chat_json(model: str, messages: list[dict], **kwargs: Any) -> Any:
    """chat() + parse the response as JSON (tolerates ```json fences)."""
    content = await chat(model, messages, **kwargs)
    cleaned = _FENCE.sub("", content.strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise OpenRouterError(f"Model did not return valid JSON: {content[:300]}") from e
