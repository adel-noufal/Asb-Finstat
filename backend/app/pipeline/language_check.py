import asyncio
from pathlib import Path

from pypdf import PdfReader

from ..config import settings
from ..openrouter import chat_json

SAMPLE_PAGES = 3
SAMPLE_CHARS = 4000


def _sample_text(path: Path) -> str:
    reader = PdfReader(path)
    if reader.is_encrypted:
        reader.decrypt("")
    parts = [page.extract_text() or "" for page in reader.pages[:SAMPLE_PAGES]]
    return "\n".join(parts).strip()[:SAMPLE_CHARS]


async def check_language(path: Path, emit) -> dict:
    """AI call #3: detect the language of a downloaded statement PDF.

    Returns {"language": "<English name>", "is_english": bool} - the runner sends
    non-English files to translate (#4), English ones straight to extract (#5).
    """
    path = Path(path)
    try:
        await emit("language_check", "running", f"Detecting the language of {path.name}...")
        sample = await asyncio.to_thread(_sample_text, path)
        if not sample:
            await emit("language_check", "error",
                       f"{path.name}: no extractable text (scanned PDF?) - assuming English")
            return {"language": "unknown", "is_english": True}

        result = await chat_json(settings.model_language_check, [{"role": "user", "content": (
            "Identify the main language of this document excerpt. Respond only with JSON: "
            '{"language": "<language name in English>", "is_english": true|false}\n\n'
            f"Excerpt:\n{sample}"
        )}])
        language = result.get("language") if isinstance(result, dict) else None
        if not isinstance(language, str) or not language.strip():
            raise ValueError(f"Invalid language detection response: {result}")
        language = language.strip()
        is_english = bool(result.get("is_english")) or language.casefold() == "english"

        await emit("language_check", "done", f"{path.name}: detected {language}",
                   {"language": language, "is_english": is_english})
        return {"language": language, "is_english": is_english}
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await emit("language_check", "error", f"{path.name}: {type(exc).__name__}: {exc}")
        raise
