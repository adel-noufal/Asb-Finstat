"""Public records first; AI only after all configured sources are exhausted."""

import asyncio
import logging
import time
from collections import OrderedDict

import httpx
from pydantic import BaseModel, Field

from .. import company_sources
from ..company_sources import Company, matches, timestamp
from ..config import settings
from ..openrouter import chat_json

logger = logging.getLogger(__name__)

# Also accept the original country-name websocket contract.
COUNTRIES = {
    "AT": "Austria", "BE": "Belgium", "BR": "Brazil", "CA": "Canada", "CN": "China",
    "CZ": "Czech Republic", "DK": "Denmark", "EG": "Egypt", "FI": "Finland", "FR": "France",
    "DE": "Germany", "GR": "Greece", "IN": "India", "ID": "Indonesia", "IE": "Ireland",
    "IT": "Italy", "JP": "Japan", "JO": "Jordan", "KW": "Kuwait", "LU": "Luxembourg",
    "MY": "Malaysia", "MX": "Mexico", "NL": "Netherlands", "NO": "Norway", "OM": "Oman",
    "PL": "Poland", "PT": "Portugal", "QA": "Qatar", "RU": "Russia", "SA": "Saudi Arabia",
    "SG": "Singapore", "ZA": "South Africa", "KR": "South Korea", "ES": "Spain", "SE": "Sweden",
    "CH": "Switzerland", "TR": "Turkey", "AE": "United Arab Emirates",
    "GB": "United Kingdom", "US": "United States",
}


class SearchResult(BaseModel):
    companies: list[Company] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


_cache: OrderedDict[tuple[str, str], tuple[float, SearchResult]] = OrderedDict()


async def _ai(country: str, country_code: str, query: str) -> list[Company]:
    result = await chat_json(settings.model_company_search, [{"role": "user", "content": (
        f"You are a company-name autocomplete. The user typed {query!r}. Suggest up to 8 real, "
        f"notable companies whose headquarters legal entity is incorporated in {country}. "
        "Use that entity's country of incorporation, not where it sells products, has an office, "
        "or trades on an exchange. Names must contain the typed text, case-insensitive. "
        'Return only JSON: [{"name": "...", "description": "one short line"}]. '
        "Return [] if unsure. These suggestions will be labelled unverified."
    )}])
    if not isinstance(result, list):
        raise ValueError("Invalid AI response")
    companies = []
    seen = set()
    for item in result:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 300:
            continue
        name = name.strip()
        if not matches(query, name) or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        description = item.get("description", "")
        companies.append(Company(
            id=f"ai:{country_code}:{name.casefold()}", name=name,
            description=description[:500] if isinstance(description, str) else "",
            source="AI", verification="unverified", country_code=country_code, retrieved_at=timestamp(),
        ))
    return companies[:8]


async def search_companies(country: str, query: str, country_code: str | None = None) -> SearchResult:
    if not isinstance(country, str) or not isinstance(query, str):
        raise ValueError("Country and query must be text")
    if country_code is None:
        country_code = next((code for code, name in COUNTRIES.items() if name == country), "")
    if not isinstance(country_code, str):
        raise ValueError("Invalid country code")
    country_code = country_code.upper()
    if COUNTRIES.get(country_code) != country:
        raise ValueError("Select a supported country")
    query = " ".join(query.split())
    if len(query) < 2:
        return SearchResult()
    if len(query) > 100:
        raise ValueError("Company search is limited to 100 characters")
    key = (country_code, query.casefold())
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        _cache.move_to_end(key)
        return cached[1].model_copy(deep=True)

    warnings = []
    async with httpx.AsyncClient(timeout=6, headers={"User-Agent": "ASBFinstat/0.1 (company lookup)"}) as client:
        providers = [("GLEIF", lambda: company_sources.gleif(client, country_code, query))]
        if country_code == "US" and settings.sec_user_agent:
            providers.append(("SEC EDGAR", lambda: company_sources.sec(client, country_code, query, settings.sec_user_agent)))
        providers.append(("Wikidata", lambda: company_sources.wikidata(client, country_code, query)))
        for label, provider in providers:
            try:
                async with asyncio.timeout(8):
                    companies = await provider()
                if companies:
                    result = SearchResult(companies=companies[:8], warnings=warnings)
                    if not warnings:
                        _remember(key, result, 600)
                    return result
            except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError, AttributeError) as exc:
                logger.warning("Company provider %s failed: %s", label, type(exc).__name__)
                warnings.append(f"{label} is temporarily unavailable; tried the next source.")

    try:
        async with asyncio.timeout(25):
            companies = await _ai(country, country_code, query)
    except Exception as exc:
        logger.warning("AI company fallback failed: %s", type(exc).__name__)
        return SearchResult(warnings=warnings + ["AI fallback is unavailable. Try again or enter a longer company name."])
    result = SearchResult(companies=companies, warnings=warnings)
    # Retry public sources after outages instead of caching degraded results.
    if not warnings:
        _remember(key, result, 60)
    return result


def _remember(key: tuple[str, str], result: SearchResult, ttl: int) -> None:
    _cache[key] = (time.monotonic() + ttl, result.model_copy(deep=True))
    _cache.move_to_end(key)
    while len(_cache) > 256:
        _cache.popitem(last=False)
