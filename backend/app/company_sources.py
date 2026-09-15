"""Public company records with source identity and provenance."""

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Literal

import httpx
from pydantic import BaseModel


class Company(BaseModel):
    id: str
    name: str
    description: str = ""
    source: Literal["GLEIF", "SEC EDGAR", "Wikidata", "AI"]
    verification: Literal["source_record", "community", "unverified"]
    country_code: str
    source_url: str | None = None
    jurisdiction: str | None = None
    headquarters_country: str | None = None
    lei: str | None = None
    cik: str | None = None
    registration_number: str | None = None
    entity_status: str | None = None
    lei_status: str | None = None
    source_updated_at: str | None = None
    retrieved_at: str


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def matches(query: str, *names: str) -> bool:
    return any(query.casefold() in name.casefold() for name in names)


async def get_json(client: httpx.AsyncClient, url: str, **kwargs) -> dict:
    response = await client.get(url, **kwargs)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or "error" in data or "errors" in data:
        raise ValueError("Invalid provider response")
    return data


async def gleif(client: httpx.AsyncClient, country_code: str, query: str) -> list[Company]:
    # A country-scoped name search also finds the main entity when the global
    # autocomplete's first ten suggestions are all foreign subsidiaries.
    direct = await get_json(client, "https://api.gleif.org/api/v1/lei-records", params={
        "filter[entity.names]": query, "filter[entity.jurisdiction]": country_code,
        "filter[entity.category]": "GENERAL", "filter[entity.status]": "ACTIVE", "page[size]": 50,
    })
    companies = _gleif_records(direct["data"], country_code, query)
    if companies:
        return companies
    # Autocomplete supports fulltext but does NOT filter by country. Resolve
    # suggested IDs before checking incorporation, rather than address country.
    suggestions = await get_json(client, "https://api.gleif.org/api/v1/autocompletions",
                                 params={"field": "fulltext", "q": query})
    ids = []
    for item in suggestions["data"]:
        lei = item.get("relationships", {}).get("lei-records", {}).get("data", {}).get("id", "")
        if re.fullmatch(r"[A-Z0-9]{20}", lei) and lei not in ids:
            ids.append(lei)
    if not ids:
        return []
    records = await get_json(client, "https://api.gleif.org/api/v1/lei-records", params={
        "filter[lei]": ",".join(ids[:20]), "page[size]": 20,
    })
    return _gleif_records([r for r in records["data"] if r.get("id") in ids], country_code, query)


def _gleif_records(records: list[dict], country_code: str, query: str) -> list[Company]:
    companies = []
    seen = set()
    for record in records:
        try:
            attributes = record["attributes"]
            entity = attributes["entity"]
            registration = attributes["registration"]
            lei = record["id"]
            name = entity["legalName"]["name"]
            jurisdiction = entity.get("jurisdiction") or ""
            aliases = [n["name"] for n in
                       (entity.get("otherNames") or []) + (entity.get("transliteratedOtherNames") or [])]
            if (lei in seen or not re.fullmatch(r"[A-Z0-9]{20}", lei)
                    or jurisdiction.split("-")[0] != country_code
                    or entity.get("status") != "ACTIVE"
                    or entity.get("category") != "GENERAL"
                    or registration.get("status") in {"DUPLICATE", "ANNULLED", "RETIRED"}
                    or not matches(query, name, *aliases)):
                continue
            seen.add(lei)
            companies.append(Company(
                id=f"gleif:{lei}", name=name, source="GLEIF", verification="source_record",
                country_code=country_code, jurisdiction=jurisdiction, lei=lei,
                source_url=f"https://search.gleif.org/#/record/{lei}",
                headquarters_country=entity.get("headquartersAddress", {}).get("country"),
                registration_number=entity.get("registeredAs"),
                entity_status=entity["status"], lei_status=registration.get("status"),
                source_updated_at=registration.get("lastUpdateDate"), retrieved_at=timestamp(),
                description=f"Incorporated in {jurisdiction}",
            ))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    # Stable sort preserves provider relevance among equivalent name matches.
    companies.sort(key=lambda c: (c.name.casefold() != query.casefold(),
                                 not c.name.casefold().startswith(query.casefold())))
    return companies


async def wikidata(client: httpx.AsyncClient, country_code: str, query: str) -> list[Company]:
    search = await get_json(client, "https://www.wikidata.org/w/api.php", params={
        "action": "wbsearchentities", "search": query, "language": "en",
        "uselang": "en", "type": "item", "limit": 20, "format": "json",
    })
    candidates = {item["id"]: item for item in search["search"]
                  if re.fullmatch(r"Q[0-9]+", item.get("id", ""))}
    if not candidates:
        return []
    # Bounded ID filtering, not global SPARQL regex search. P17 remains a
    # community country claim, so these records are not labelled verified.
    values = " ".join(f"wd:{qid}" for qid in candidates)
    sparql = f'''
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
PREFIX wikibase: <http://wikiba.se/ontology#>
SELECT DISTINCT ?item ?code WHERE {{
  VALUES ?item {{ {values} }}
  ?item wdt:P31/wdt:P279* wd:Q4830453; p:P17 ?statement.
  ?statement ps:P17 ?country; wikibase:rank ?rank.
  ?country wdt:P297 ?code.
  FILTER(?code = "{country_code}")
  FILTER(?rank != wikibase:DeprecatedRank)
  FILTER NOT EXISTS {{ ?statement pq:P582 ?end. FILTER(?end <= NOW()) }}
  FILTER NOT EXISTS {{ ?statement pq:P580 ?start. FILTER(?start > NOW()) }}
  FILTER NOT EXISTS {{ ?item wdt:P576 ?dissolved. FILTER(?dissolved <= NOW()) }}
}} LIMIT 20'''
    records = await get_json(client, "https://query.wikidata.org/sparql",
                             params={"query": sparql, "format": "json"})
    companies = []
    seen = set()
    for row in records["results"]["bindings"]:
        qid = row["item"]["value"].rsplit("/", 1)[-1]
        if qid not in candidates or qid in seen or row["code"]["value"] != country_code:
            continue
        item = candidates[qid]
        name = item.get("label", "")
        alias = item.get("match", {}).get("text", "")
        if not name or not matches(query, name, alias):
            continue
        seen.add(qid)
        companies.append(Company(
            id=f"wikidata:{qid}", name=name, description=item.get("description", ""),
            source="Wikidata", verification="community", country_code=country_code,
            source_url=f"https://www.wikidata.org/wiki/{qid}", retrieved_at=timestamp(),
        ))
    return companies


# A US listing/address does not establish incorporation. Check state/DC codes.
US_STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())
_sec_index: tuple[float, dict] | None = None


async def sec(client: httpx.AsyncClient, country_code: str, query: str, user_agent: str) -> list[Company]:
    global _sec_index
    if country_code != "US" or not user_agent:
        return []
    headers = {"User-Agent": user_agent}
    if _sec_index is None or time.monotonic() - _sec_index[0] > 86400:
        index = await get_json(client, "https://www.sec.gov/files/company_tickers.json", headers=headers)
        _sec_index = (time.monotonic(), index)
    candidates = [item for item in _sec_index[1].values()
                  if isinstance(item, dict) and matches(query, item.get("title", ""), item.get("ticker", ""))]
    candidates.sort(key=lambda item: (item.get("ticker", "").casefold() != query.casefold(), len(item["title"])))
    companies = []
    for item in candidates[:8]:
        await asyncio.sleep(0.15)
        cik = str(item["cik_str"]).zfill(10)
        if not re.fullmatch(r"[0-9]{10}", cik):
            continue
        profile = await get_json(client, f"https://data.sec.gov/submissions/CIK{cik}.json", headers=headers)
        state = profile.get("stateOfIncorporation")
        if state not in US_STATES or str(profile.get("cik", "")).zfill(10) != cik:
            continue
        companies.append(Company(
            id=f"sec:{cik}", name=profile["name"], source="SEC EDGAR", verification="source_record",
            country_code="US", jurisdiction=f"US-{state}", cik=cik, retrieved_at=timestamp(),
            source_url=f"https://www.sec.gov/edgar/browse/?CIK={cik}",
            description=f"{item.get('ticker', '')} · Incorporated in US-{state}",
        ))
    return companies
