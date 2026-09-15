"""Sophie's connection check, using the application's shared OpenRouter client.

Run from backend with: python -m app.check_openrouter
This makes one small API call using MODEL_COMPANY_SEARCH.
"""

import asyncio
import sys

from .config import settings
from .openrouter import chat


async def main() -> int:
    if not settings.openrouter_api_key:
        print("Set OPENROUTER_API_KEY in backend/.env before running this check.", file=sys.stderr)
        return 2
    try:
        message = await chat(
            settings.model_company_search,
            [{"role": "user", "content": "Reply with exactly: connection verified"}],
            max_tokens=8,
        )
    except Exception as exc:
        print(f"OpenRouter connection failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    if not message:
        print("OpenRouter returned no message content.", file=sys.stderr)
        return 1
    print("OpenRouter connection verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
