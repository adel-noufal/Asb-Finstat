import asyncio
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pymupdf
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image

from app.config import settings
from app.main import app
from app.pipeline.extract import extract_statements
from app.pipeline.runner import run_pipeline
from app.pipeline.statement_extractor import EvidenceReader, Locator, NAMES, Statement, TableExtractor, Writer

SAMPLE = Path(__file__).resolve().parent / "fixtures/extraction/inputs/Press release Carrefour Q4+FY 2025.pdf"


class ExtractionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp)
        self.enterContext(patch.object(settings, "extraction_dir", self.root / "artifacts"))
        self.enterContext(patch.object(settings, "extract_use_llm", False))
        self.enterContext(patch.object(settings, "extract_ocr_mode", "off"))

    async def test_sophie_sample_through_real_extraction_and_downloads(self):
        emit = AsyncMock()
        payload = await extract_statements(SAMPLE, emit)
        expected = {"IncomeStatement": [18], "Balance Sheet": [19], "CashFlow": [20]}
        self.assertEqual(payload["missing_statements"], [])
        for name, pages in expected.items():
            self.assertEqual(payload["statements"][name]["source_pages"], pages)
            self.assertTrue(payload["statements"][name]["found"])
            self.assertGreater(len(payload["statements"][name]["rows"]), 2)
        self.assertEqual(emit.await_args_list[-1].args[1], "done")
        self.assertEqual(emit.await_args_list[-1].args[3], payload)
        with TestClient(app) as client:
            response = client.get(payload["artifacts"]["json"])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), payload)
            workbook_response = client.get(payload["artifacts"]["xlsx"])
            self.assertEqual(workbook_response.status_code, 200)
        workbook = load_workbook(BytesIO(workbook_response.content))
        self.assertEqual(set(workbook.sheetnames), set(NAMES))
        self.assertIn("[20]", workbook["CashFlow"]["A2"].value)
        workbook.close()

    async def test_translated_text_and_missing_tables(self):
        report = self.root / "translated.txt"
        report.write_text("Consolidated income statement\n(in USD millions)\nItem  2025  2024\nSales  100  90\nProfit  20  10\nNote 1: unaudited", encoding="utf-8")
        payload = await extract_statements(report, AsyncMock())
        self.assertEqual(payload["missing_statements"], ["CashFlow", "Balance Sheet"])
        income = payload["statements"]["IncomeStatement"]
        self.assertTrue(income["found"])
        self.assertEqual(income["currency_and_scale"], "(in USD millions)")
        self.assertEqual(income["footnotes"], ["Note 1: unaudited"])
        self.assertIn(["Sales", "100", "90"], income["rows"])

    async def test_plain_prose_is_evidence_not_a_recovered_table(self):
        report = self.root / "narrative.txt"
        report.write_text("Balance sheet\nWe discuss performance here.", encoding="utf-8")
        payload = await extract_statements(report, AsyncMock())
        balance = payload["statements"]["Balance Sheet"]
        self.assertFalse(balance["found"])
        self.assertTrue(balance["text_evidence"])
        self.assertEqual(len(payload["missing_statements"]), 3)

    async def test_unreadable_input_emits_error_and_stops_pipeline(self):
        report = self.root / "empty.txt"
        report.write_text("", encoding="utf-8")
        emit = AsyncMock()
        with self.assertRaisesRegex(ValueError, "No readable report text"):
            await extract_statements(report, emit)
        self.assertEqual(emit.await_args_list[-1].args[1], "error")

    async def test_pipeline_passes_extraction_payload_to_final_event(self):
        payload = {"source_pdf": "report.pdf", "statements": {}, "artifacts": {"json": "/artifacts/test/report.json"}}
        with patch("app.pipeline.runner.find_statements", new_callable=AsyncMock,
                   return_value=[{"path": Path("report.pdf"), "year": 2025}]), \
             patch("app.pipeline.runner.check_language", new_callable=AsyncMock,
                   return_value={"language": "English", "is_english": True}), \
             patch("app.pipeline.runner.extract_statements", new_callable=AsyncMock, return_value=payload):
            emit = AsyncMock()
            await run_pipeline({"name": "Sample"}, "France", emit)
        final = emit.await_args_list[-1].args
        self.assertEqual(final[0:2], ("pipeline", "done"))
        self.assertEqual(final[3]["results"][0]["statements"], payload)


class LocatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_title_with_numeric_table_wins_over_title_only(self):
        result = await Locator("unused", use_llm=False).locate([
            "Consolidated income statement 2025 vs 2024\nSee the financial statements below.",
            "Consolidated income statement\nRevenue  100  90\nProfit  20  10",
            "Notes to the consolidated financial statements\n"
            "Consolidated income statement\nAdjusting items  200  190",
        ])
        self.assertEqual(result["IncomeStatement"], [2])

    async def test_primary_group_titles_win_over_accounting_notes_and_parent(self):
        pages = [
            "Group income statement\nRevenue  100  90\nProfit  20  10",
            "Group balance sheet\nTotal assets  100  90\nNet assets  20  10",
            "Group cash flow statement\nOperating activities  100  90\nCash  20  10",
            "Notes to the Group financial statements continued\n"
            "recognised immediately in the Group income statement.\n"
            "The consolidated cash flow statement includes these transactions.\n"
            "The consolidated balance sheet records the amounts.",
            "Notes to the Group financial statements\nGroup income statement\nAdjusting items",
            "Parent Company balance sheet\nTotal assets  80  70\nNet assets  10  5",
            "Group cash flow statement\nThe table below shows the impact of adjusting items.",
        ]
        self.assertEqual(await Locator("unused", use_llm=False).locate(pages), {
            "IncomeStatement": [1], "Balance Sheet": [2], "CashFlow": [3],
        })

    async def test_accounting_prose_does_not_qualify_as_a_heading(self):
        result = await Locator("unused", use_llm=False).locate([
            "recognised immediately in the Group income statement.",
            "Our balance sheet remains strong.",
            "The consolidated cash flow statement includes these transactions.",
        ])
        self.assertEqual(result, {name: [] for name in NAMES})

    async def test_llm_can_reject_a_heuristic_table(self):
        pages = ["Cash flow statement\nNo table is present."]
        with patch.object(settings, "openrouter_api_key", "test"), \
             patch("app.pipeline.statement_extractor.chat_json", new_callable=AsyncMock,
                   return_value={name: [] for name in NAMES}) as ai:
            result = await Locator("test-model").locate(pages)
        self.assertEqual(result, {name: [] for name in NAMES})
        self.assertEqual(ai.call_args.args[0], "test-model")

    async def test_invalid_llm_pages_fall_back_with_warning(self):
        locator = Locator("test-model")
        with patch.object(settings, "openrouter_api_key", "test"), \
             patch("app.pipeline.statement_extractor.chat_json", new_callable=AsyncMock,
                   return_value={"CashFlow": [999], "Balance Sheet": [], "IncomeStatement": []}):
            result = await locator.locate(["Consolidated cash flow statement"])
        self.assertEqual(result["CashFlow"], [1])
        self.assertIn("heuristic", locator.warnings[0])

    async def test_separate_comprehensive_income_is_not_a_continuation(self):
        locator = Locator("test-model")
        with patch.object(settings, "openrouter_api_key", "test"), \
             patch("app.pipeline.statement_extractor.chat_json", new_callable=AsyncMock,
                   return_value={"CashFlow": [], "Balance Sheet": [], "IncomeStatement": [1, 2]}):
            result = await locator.locate([
                "Group income statement\nRevenue  100  90",
                "Group statement of comprehensive income/(loss)\nOther comprehensive income  20  10",
            ])
        self.assertEqual(result["IncomeStatement"], [1])
        self.assertTrue(locator.warnings)

    async def test_cancellation_does_not_fall_back_to_heuristics(self):
        with patch.object(settings, "openrouter_api_key", "test"), \
             patch("app.pipeline.statement_extractor.chat_json", new_callable=AsyncMock,
                   side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await Locator("test-model").locate(["Consolidated cash flow statement"])


class ReaderWriterTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def scanned_pdf(self):
        pdf = self.root / "scan.pdf"
        image_data = BytesIO()
        with Image.new("RGB", (200, 100), "white") as image:
            image.save(image_data, format="PNG")
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_image(page.rect, stream=image_data.getvalue())
            doc.save(pdf)
        return pdf

    def test_partial_numeric_grid_retains_labels_and_comparatives(self):
        self.check_partial_grid(merged=False)

    def test_merged_grid_retains_labels_and_comparatives_on_the_same_row(self):
        self.check_partial_grid(merged=True)

    def check_partial_grid(self, merged):
        pdf = self.root / "partial-grid.pdf"
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 50), "Group income statement")
            for y, label, current, previous in (
                (95, "", "2025", "2024"),
                (115, "Revenue", "100", "90"),
                (135, "Operating profit", "20", "10"),
                (155, "Net profit", "15", "8"),
            ):
                page.insert_text((50, y), label)
                page.insert_text((310, y), current)
                page.insert_text((380, y), previous)
            for x in ((40, 300, 370, 440) if merged else (300, 370, 440)):
                page.draw_line((x, 80), (x, 160))
            for y in (80, 100, 120, 140, 160):
                left = 40 if merged and y != 120 else 300
                right = 370 if merged and y == 120 else 440
                page.draw_line((left, y), (right, y))
            doc.save(pdf)
        evidence = EvidenceReader("off").read(pdf)
        with pymupdf.open(pdf) as doc:
            result = TableExtractor().extract(doc, evidence, "IncomeStatement", [1])
        revenue = next((row for row in result.rows if "Revenue" in row), [])
        self.assertIn("100", revenue, result.rows)
        self.assertIn("90", revenue, result.rows)

    def test_ocr_text_is_used_by_table_extraction(self):
        pdf = self.scanned_pdf()
        with patch("app.pipeline.statement_extractor.shutil.which", return_value="tesseract"), \
             patch("app.pipeline.statement_extractor.pytesseract.image_to_string",
                   return_value="Consolidated income statement\nItem  2025  2024\nSales  100  90\nProfit  20  10"):
            evidence = EvidenceReader().read(pdf)
        self.assertEqual(evidence.ocr_pages, [1])
        with pymupdf.open(pdf) as doc:
            result = TableExtractor().extract(doc, evidence, "IncomeStatement", [1])
        self.assertTrue(result.found)
        self.assertIn(["Sales", "100", "90"], result.rows)
        self.assertTrue(any("OCR" in warning for warning in result.warnings))

    def test_required_ocr_without_tesseract_fails_explicitly(self):
        pdf = self.scanned_pdf()
        with patch("app.pipeline.statement_extractor.shutil.which", return_value=None), \
             patch("app.pipeline.statement_extractor.Path.is_file", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "Tesseract"):
                EvidenceReader("required").read(pdf)

    def test_workbook_stores_pdf_formula_text_without_executing_it(self):
        items = {name: Statement(name) for name in NAMES}
        items["CashFlow"] = Statement("CashFlow", found=True, rows=[["=1+2", "100"]])
        out = self.root / ("a" * 32)
        Writer().write(Path("report.v2.pdf"), out, items, [])
        workbook = load_workbook(out / "report.xlsx", data_only=False)
        self.assertEqual(workbook["CashFlow"]["A5"].value, "=1+2")
        self.assertEqual(workbook["CashFlow"]["A5"].data_type, "s")
        workbook.close()
        self.assertEqual(json.loads((out / "report.json").read_text())["source_pdf"], "report.v2.pdf")

    def test_artifact_endpoint_rejects_unknown_ids_and_files(self):
        with patch.object(settings, "extraction_dir", self.root), TestClient(app) as client:
            for url in ("/artifacts/not-an-id/report.json", f"/artifacts/{'a' * 32}/secret.env",
                        f"/artifacts/{'a' * 32}/report.json"):
                self.assertEqual(client.get(url).status_code, 404)


if __name__ == "__main__":
    unittest.main()
