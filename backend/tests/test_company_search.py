import asyncio
import copy
import threading
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app import company_sources as sources
from app.main import app
from app.pipeline import company_search as search
from app.pipeline.find_statements import _propose


def company(source="GLEIF", country="DE"):
    return sources.Company(
        id="test:1", name="Siemens AG", source=source,
        verification="source_record" if source == "GLEIF" else "community",
        country_code=country, retrieved_at=sources.timestamp(),
    )


def record(lei="W38RGI023J3WT1HWRP32", jurisdiction="DE", hq="DE", **changes):
    entity = {
        "legalName": {"name": "Siemens Aktiengesellschaft"}, "jurisdiction": jurisdiction,
        "headquartersAddress": {"country": hq}, "legalAddress": {"country": hq},
        "category": "GENERAL", "status": "ACTIVE", "registeredAs": "HRB 123",
        "otherNames": [], "transliteratedOtherNames": [],
    }
    entity.update(changes)
    return {"id": lei, "attributes": {"entity": entity, "registration": {
        "status": "LAPSED", "lastUpdateDate": "2026-01-01T00:00:00Z",
    }}}


class SearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        search._cache.clear()
        self.providers = []
        for name in ("gleif", "wikidata", "sec"):
            mock = self.enterContext(patch.object(sources, name, new_callable=AsyncMock, return_value=[]))
            setattr(self, name, mock)
        self.ai = self.enterContext(patch.object(search, "chat_json", new_callable=AsyncMock, return_value=[]))
        self.enterContext(patch.object(search.settings, "sec_user_agent", ""))

    async def test_gleif_result_never_calls_other_sources_or_ai(self):
        self.gleif.return_value = [company()]
        result = await search.search_companies("Germany", "Siemens", "de")
        self.assertEqual(result.companies[0].source, "GLEIF")
        self.wikidata.assert_not_awaited()
        self.ai.assert_not_awaited()

    async def test_timeout_falls_through_to_wikidata_with_warning(self):
        self.gleif.side_effect = httpx.ReadTimeout("offline")
        self.wikidata.return_value = [company("Wikidata")]
        result = await search.search_companies("Germany", "Siemens")
        self.assertEqual(result.companies[0].verification, "community")
        self.assertIn("GLEIF", result.warnings[0])
        self.ai.assert_not_awaited()
        await search.search_companies("Germany", "Siemens")
        self.assertEqual(self.gleif.await_count, 2, "Outages must not cache degraded results")

    async def test_ai_is_last_and_untrusted_fields_cannot_claim_verification(self):
        order = []
        async def empty_gleif(*args):
            order.append("gleif")
            return []
        async def empty_wikidata(*args):
            order.append("wikidata")
            return []
        async def ai(*args):
            order.append("ai")
            return [None, {"name": 12}, {"name": "Unrelated"},
                    {"name": "Siemens AG", "source": "GLEIF", "lei": "fake", "description": {}},
                    {"name": "siemens ag"}]
        self.gleif.side_effect = empty_gleif
        self.wikidata.side_effect = empty_wikidata
        self.ai.side_effect = ai
        result = await search.search_companies("Germany", "sie")
        self.assertEqual(order, ["gleif", "wikidata", "ai"])
        self.assertEqual(len(result.companies), 1)
        self.assertEqual(result.companies[0].verification, "unverified")
        self.assertIsNone(result.companies[0].lei)
        self.assertIsNone(result.companies[0].source_url)

    async def test_optional_sec_runs_before_wikidata_for_us_only(self):
        self.sec.return_value = [company(country="US")]
        with patch.object(search.settings, "sec_user_agent", "Test contact@example.com"):
            await search.search_companies("United States", "Siemens", "US")
            self.sec.assert_awaited_once()
            self.wikidata.assert_not_awaited()
            await search.search_companies("Germany", "Siemens", "DE")
            self.assertEqual(self.sec.await_count, 1)

    async def test_cache_is_country_specific_and_returns_copies(self):
        self.gleif.return_value = [company()]
        first = await search.search_companies("Germany", " Siemens ", "DE")
        first.companies.clear()
        second = await search.search_companies("Germany", "siemens", "DE")
        self.assertEqual(len(second.companies), 1)
        self.assertEqual(self.gleif.await_count, 1)
        await search.search_companies("United States", "siemens", "US")
        self.assertEqual(self.gleif.await_count, 2)

    async def test_invalid_and_short_inputs_make_no_network_calls(self):
        self.assertEqual((await search.search_companies("Germany", "s")).companies, [])
        with self.assertRaises(ValueError):
            await search.search_companies("Germany", "Siemens", "US")
        with self.assertRaises(ValueError):
            await search.search_companies("Germany", "x" * 101)
        self.gleif.assert_not_awaited()
        self.ai.assert_not_awaited()

    async def test_cancellation_does_not_trigger_ai(self):
        self.gleif.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await search.search_companies("Germany", "Siemens")
        self.ai.assert_not_awaited()

    async def test_missing_ai_key_returns_actionable_warning(self):
        self.ai.side_effect = RuntimeError("OPENROUTER_API_KEY is not set")
        result = await search.search_companies("Germany", "Siemens")
        self.assertEqual(result.companies, [])
        self.assertIn("AI fallback is unavailable", result.warnings[-1])

    async def test_all_public_sources_down_still_returns_ai_suggestions(self):
        self.gleif.side_effect = httpx.ConnectError("offline")
        self.wikidata.side_effect = ValueError("malformed response")
        self.ai.return_value = [{"name": "Siemens AG"}]
        result = await search.search_companies("Germany", "Siemens")
        self.assertEqual(result.companies[0].source, "AI")
        self.assertEqual(len(result.warnings), 2)
        self.ai.assert_awaited_once()

    async def test_expired_cache_refreshes_public_records(self):
        self.gleif.return_value = [company()]
        await search.search_companies("Germany", "Siemens")
        key = ("DE", "siemens")
        search._cache[key] = (0, search._cache[key][1])
        await search.search_companies("Germany", "Siemens")
        self.assertEqual(self.gleif.await_count, 2)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_gleif_checks_incorporation_not_hq_and_keeps_lapsed_lei(self):
        foreign = record("529900QBVWXMWANH7H45", "US-DE", "DE")
        german = record(hq="US")
        inactive = record("529900LT6G2TUO3TZB94", status="INACTIVE")
        fund = record("5299005CHJZ14D4FDJ62", category="FUND")
        duplicate = copy.deepcopy(german)
        duplicate["attributes"]["registration"]["status"] = "DUPLICATE"
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"data": [foreign, inactive, fund, duplicate, german, german]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await sources.gleif(client, "DE", "Siemens")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].headquarters_country, "US")
        self.assertEqual(result[0].jurisdiction, "DE")
        self.assertEqual(result[0].lei_status, "LAPSED")
        self.assertEqual(result[0].registration_number, "HRB 123")
        self.assertEqual(calls[0].url.params["filter[entity.jurisdiction]"], "DE")

    async def test_partial_gleif_search_resolves_autocomplete_ids(self):
        lei = "W38RGI023J3WT1HWRP32"
        def handler(request):
            if request.url.path.endswith("autocompletions"):
                self.assertEqual(request.url.params["field"], "fulltext")
                return httpx.Response(200, json={"data": [{"relationships": {
                    "lei-records": {"data": {"id": lei}},
                }}]})
            if "filter[lei]" in request.url.params:
                self.assertEqual(request.url.params["filter[lei]"], lei)
                return httpx.Response(200, json={"data": [record()]})
            return httpx.Response(200, json={"data": []})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await sources.gleif(client, "DE", "sie")
        self.assertEqual(result[0].lei, lei)

    async def test_wikidata_filters_candidate_ids_and_country_and_marks_community(self):
        def handler(request):
            if request.url.path.endswith("api.php"):
                return httpx.Response(200, json={"search": [
                    {"id": "Q81230", "label": "Siemens", "description": "Company"},
                    {"id": "Q169893", "label": "siemens", "description": "Unit"},
                    {"id": "malicious }", "label": "Siemens"},
                ]})
            query = request.url.params["query"]
            self.assertIn("VALUES ?item { wd:Q81230 wd:Q169893 }", query)
            self.assertIn("wdt:P31/wdt:P279* wd:Q4830453", query)
            self.assertNotIn("malicious", query)
            self.assertIn('FILTER(?code = "DE")', query)
            self.assertIn("pq:P582", query)
            return httpx.Response(200, json={"results": {"bindings": [
                {"item": {"value": "http://www.wikidata.org/entity/Q81230"}, "code": {"value": "DE"}},
                {"item": {"value": "http://www.wikidata.org/entity/Q169893"}, "code": {"value": "US"}},
            ]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await sources.wikidata(client, "DE", "sie")
        self.assertEqual([c.name for c in result], ["Siemens"])
        self.assertEqual(result[0].verification, "community")
        self.assertIsNone(result[0].jurisdiction)

    async def test_sec_rejects_foreign_filer_with_us_office(self):
        sources._sec_index = None
        def handler(request):
            if request.url.path.endswith("company_tickers.json"):
                return httpx.Response(200, json={
                    "0": {"title": "Test Foreign", "ticker": "TF", "cik_str": 1},
                    "1": {"title": "Test US", "ticker": "TU", "cik_str": 2},
                })
            foreign = request.url.path.endswith("0000000001.json")
            return httpx.Response(200, json={
                "cik": 1 if foreign else 2, "name": "Test Foreign" if foreign else "Test US",
                "stateOfIncorporation": "X0" if foreign else "DE",
                "addresses": {"business": {"stateOrCountry": "NY"}},
            })
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await sources.sec(client, "US", "Test", "Test contact@example.com")
        self.assertEqual([c.name for c in result], ["Test US"])
        self.assertEqual(result[0].jurisdiction, "US-DE")
        sources._sec_index = None

    async def test_report_search_receives_selected_identity(self):
        with patch("app.pipeline.find_statements.chat_json", new_callable=AsyncMock, return_value=[]) as ai:
            await _propose("Siemens AG", "Germany", "", {
                "lei": "W38RGI023J3WT1HWRP32", "verification": "source_record", "jurisdiction": "DE",
            })
            messages = ai.call_args.args[1]
            prompt = messages[1]["content"]
            self.assertIn("W38RGI023J3WT1HWRP32", prompt)
            self.assertIn("exact legal entity", prompt)


class WebsocketTests(unittest.TestCase):
    def test_clearing_query_cancels_pending_search(self):
        started = threading.Event()
        cancelled = threading.Event()
        async def lookup(*args):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with patch("app.main.search_companies", side_effect=lookup):
            with TestClient(app).websocket_connect("/ws") as ws:
                ws.send_json({"type": "search_companies", "country": "Germany", "query": "old", "requestId": 1})
                self.assertTrue(started.wait(2))
                ws.send_json({"type": "cancel_search"})
                self.assertTrue(cancelled.wait(2))

    def test_new_search_cancels_old_search_and_preserves_provenance(self):
        started = threading.Event()
        cancelled = threading.Event()
        async def lookup(country, query, country_code=None):
            if query == "old":
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return search.SearchResult(companies=[company()])
        with patch("app.main.search_companies", side_effect=lookup):
            with TestClient(app).websocket_connect("/ws") as ws:
                ws.send_json({"type": "search_companies", "country": "Germany", "query": "old", "requestId": 1})
                self.assertTrue(started.wait(2))
                ws.send_json({"type": "search_companies", "country": "Germany", "query": "new", "requestId": 2})
                result = ws.receive_json()
                self.assertTrue(cancelled.wait(2))
                self.assertEqual(result["requestId"], 2)
                self.assertEqual(result["companies"][0]["source"], "GLEIF")


if __name__ == "__main__":
    unittest.main()
