"""Pipeline adapter for Sophie's financial statement extractor."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from uuid import uuid4

from ..config import settings
from .statement_extractor import EvidenceReader, Locator, extract_and_write

# PyMuPDF must not be accessed concurrently from multiple threads. All PDF and
# workbook work uses this one dedicated worker, keeping the websocket responsive.
_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="statement-extractor")


async def extract_statements(path: Path, emit) -> dict:
    """Read a PDF/translated text report and return statements plus JSON/XLSX links."""
    path = Path(path)
    loop = asyncio.get_running_loop()
    try:
        await emit("extract", "running", f"Reading {path.name} for financial statements...")
        evidence = await loop.run_in_executor(_worker, EvidenceReader(settings.extract_ocr_mode).read, path)
        if not any(page.strip() for page in evidence.pages):
            raise ValueError("No readable report text found. For scanned PDFs, install Tesseract OCR on PATH.")
        await emit("extract", "running", f"Locating statement tables in {len(evidence.pages)} pages...")
        locator = Locator(settings.model_extract, settings.extract_use_llm)
        locations = await locator.locate(evidence.pages)
        warnings = evidence.warnings + locator.warnings
        await emit("extract", "running", "Extracting source tables and writing JSON and Excel files...",
                   {"source_pages": locations, "warnings": warnings})
        out = settings.extraction_dir / uuid4().hex
        payload = await loop.run_in_executor(_worker, partial(
            extract_and_write, path, evidence, locations, out, warnings,
        ))
        found = sum(item["found"] for item in payload["statements"].values())
        await emit("extract", "done", f"{path.name}: recovered {found}/3 statement tables; JSON and Excel ready.", payload)
        return payload
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await emit("extract", "error", f"{path.name}: {type(exc).__name__}: {exc}")
        raise
