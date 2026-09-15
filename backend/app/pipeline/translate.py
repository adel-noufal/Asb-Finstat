"""Connect Adel's PDF translation to the existing extraction pipeline."""

import asyncio
from pathlib import Path

from .extract import _worker
from .pdf_translation import LANGUAGE_NAMES, translate_to_english
from .statement_extractor import EvidenceReader


async def translate_pdf(path: Path, language: str, emit) -> Path:
    """Translate PDF pages to English text, preserving PDF page boundaries."""
    path = Path(path)
    source = next((code for code, name in LANGUAGE_NAMES.items()
                   if name.casefold() == language.casefold()), language.lower())
    source = {"chinese": "zh-cn", "mandarin": "zh-cn", "unknown": "auto"}.get(source, source)
    try:
        await emit("translate", "running", f"Translating {path.name} from {language} to English...")
        # Use the same PDF worker as extraction; PyMuPDF is not thread-safe.
        evidence = await asyncio.get_running_loop().run_in_executor(_worker, EvidenceReader().read, path)
        if not any(page.strip() for page in evidence.pages):
            raise ValueError("No readable PDF text to translate. Scanned PDFs require Tesseract OCR.")
        for warning in evidence.warnings:
            await emit("translate", "running", warning)
        pages = []
        for number, text in enumerate(evidence.pages, 1):
            if text.strip():
                await emit("translate", "running", f"Translating page {number}/{len(evidence.pages)} of {path.name}...")
                translated = await asyncio.to_thread(translate_to_english, text, source)
                if not translated:
                    raise RuntimeError(f"Translation failed on page {number}")
                pages.append(translated)
            else:
                pages.append("")
        output = path.with_name(f"{path.stem}_english.txt")
        await asyncio.to_thread(output.write_text, "\f".join(pages), encoding="utf-8")
        await emit("translate", "done", f"Translated {len(pages)} pages to English: {output.name}",
                   {"file": str(output), "pages": len(pages), "provider": "Google Translate / MyMemory"})
        return output
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await emit("translate", "error", f"{path.name}: {type(exc).__name__}: {exc}")
        raise
