import asyncio

from .extract import extract_statements
from .find_statements import find_statements
from .language_check import check_language
from .translate import translate_pdf


async def run_pipeline(company: dict, country: str, emit) -> None:
    """Orchestrates AI calls #2..#5 for one selected company, emitting
    step_update events over the websocket as it goes."""
    name = company.get("name", "?")
    try:
        await emit("pipeline", "running", f"Starting pipeline for {name} ({country})")
        pdfs = await find_statements(company, country, emit)
        if not pdfs:
            await emit("pipeline", "error", "No statements downloaded - nothing to process")
            return

        results = []
        for pdf in pdfs:
            path = pdf["path"]
            lang = await check_language(path, emit)
            if not lang["is_english"]:
                path = await translate_pdf(path, lang["language"], emit)
            statements = await extract_statements(path, emit)
            results.append({
                "year": pdf.get("year"),
                "file": str(path),
                "language": lang["language"],
                "statements": statements,
            })

        await emit("pipeline", "done", f"Processed {len(results)} statement(s) for {name}",
                   {"company": company, "results": results})
    except asyncio.CancelledError:
        raise
    except Exception as e:
        await emit("pipeline", "error", f"{type(e).__name__}: {e}")
