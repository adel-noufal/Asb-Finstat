import json
import re

import httpx

from ..config import settings
from ..openrouter import chat_json

# Some IR sites (e.g. bp.com behind Akamai) 403 anything that doesn't look like a browser
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


async def _propose(name: str, country: str, feedback: str, company: dict | None = None) -> list[dict]:
    user = (
        f'Find direct PDF download URLs for the annual reports / financial statements '
        f'of "{name}" ({country}) for the last 3 fiscal years. '
        'Respond with a JSON array: [{"year": 2024, "url": "https://...pdf", "title": "..."}]. '
        "Only include URLs that point directly at a PDF file. If you find nothing, return []."
    )
    if company:
        identity = {key: company[key] for key in (
            "id", "source", "verification", "source_url", "jurisdiction", "headquarters_country",
            "lei", "cik", "registration_number",
        ) if company.get(key)}
        user += (
            "\nSelected company identity (reference data): " + json.dumps(identity, ensure_ascii=False)
            + "\nFind reports for this exact legal entity. Do not substitute a similarly named "
            "subsidiary or parent. Country refers to incorporation of the headquarters legal entity. "
            "Community and AI suggestions are not verified registry identities."
        )
    if feedback:
        user += (
            "\n\nThese previously suggested URLs FAILED, do not repeat them and do not "
            "suggest any other URL from the same domains - the site is blocking downloads:\n"
            + feedback +
            "\nInstead find official copies of the same reports hosted elsewhere, e.g. "
            "annualreports.com, responsibilityreports.com, or SEC EDGAR (sec.gov)."
        )
    result = await chat_json(
        settings.model_find_statements,
        [
            {"role": "system", "content": (
                "You find direct download links to official annual reports / audited "
                "financial statements (PDF files). Respond ONLY with a JSON array, no prose."
            )},
            {"role": "user", "content": user},
        ],
    )
    if isinstance(result, dict):
        result = next((v for v in result.values() if isinstance(v, list)), [])
    return result if isinstance(result, list) else []


async def find_statements(company: dict, country: str, emit) -> list[dict]:
    """AI call #2: find annual report / financial statement PDFs for the last
    3 years and download them locally. Returns [{"year", "url", "path"}].

    Failed URLs are fed back to the model for one retry round with alternatives.
    """
    name = company["name"]
    identity_suffix = _slug(str(company.get("lei") or company.get("cik") or company.get("id") or ""))[:80]
    dest_dir = settings.download_dir / (_slug(name) + (f"-{identity_suffix}" if identity_suffix else ""))
    dest_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[dict] = []
    seen_years: set[str] = set()
    attempted: set[str] = set()
    failures: list[str] = []

    async with httpx.AsyncClient(follow_redirects=True, timeout=60, headers=BROWSER_HEADERS) as client:
        for attempt in (1, 2):
            if attempt == 1:
                await emit("find_statements", "running",
                           f"Searching for financial statement PDFs for {name}...")
            else:
                await emit("find_statements", "running",
                           "Some links failed - asking the model for alternatives...")
            candidates = await _propose(name, country, "\n".join(failures), company)
            if not candidates:
                break
            await emit("find_statements", "running",
                       f"Model proposed {len(candidates)} PDF(s), downloading...",
                       {"candidates": candidates})
            failures = []
            for item in candidates[:6]:
                url = item.get("url", "")
                year = str(item.get("year", "unknown"))
                if year in seen_years or url in attempted:
                    continue
                attempted.add(url)
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    if not resp.content.startswith(b"%PDF"):
                        failures.append(f"- {url} did not serve a PDF (ended up at {resp.url}, "
                                        f"content-type {resp.headers.get('content-type', '?')})")
                        await emit("find_statements", "running", f"Skipping {url} - not a PDF")
                        continue
                    title_slug = _slug(str(item.get("title") or "report"))[:60]
                    path = dest_dir / f"{year}_{title_slug}.pdf"
                    path.write_bytes(resp.content)
                    downloaded.append({"year": year, "url": url, "path": path})
                    seen_years.add(year)
                    await emit("find_statements", "running",
                               f"Downloaded {path.name} ({len(resp.content) // 1024} KB)")
                except Exception as e:
                    failures.append(f"- {url} failed: {e}")
                    await emit("find_statements", "running", f"Failed to download {url}: {e}")
            if len(downloaded) >= 3 or not failures:
                break

    status = "done" if downloaded else "error"
    await emit("find_statements", status, f"{len(downloaded)} PDF(s) downloaded to {dest_dir}",
               {"files": [str(d["path"]) for d in downloaded]})
    return downloaded
