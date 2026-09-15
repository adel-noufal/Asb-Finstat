import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pymupdf

from app.config import settings
from app.pipeline.runner import run_pipeline


class TranslationTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_english_pdf_translates_then_extracts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pdf = root / "french.pdf"
            with pymupdf.open() as doc:
                doc.new_page().insert_text((50, 50), "Compte de resultat")
                doc.new_page()
                doc.new_page().insert_text((50, 50), "Bilan consolide")
                doc.save(pdf)
            translations = [
                "Consolidated income statement\nRevenue  100  90\nProfit  20  10",
                "Consolidated balance sheet\nAssets  200  190\nLiabilities  100  90",
            ]
            with patch("app.pipeline.runner.find_statements", AsyncMock(return_value=[{"path": pdf, "year": 2025}])), \
                 patch("app.pipeline.runner.check_language", AsyncMock(return_value={"language": "French", "is_english": False})), \
                 patch("app.pipeline.translate.translate_to_english", side_effect=translations) as translator, \
                 patch.object(settings, "extract_use_llm", False), \
                 patch.object(settings, "extraction_dir", root / "artifacts"):
                emit = AsyncMock()
                await run_pipeline({"name": "Demo"}, "France", emit)
            final = emit.await_args_list[-1].args
            self.assertEqual(final[:2], ("pipeline", "done"))
            result = final[3]["results"][0]
            self.assertEqual(translator.call_args.args[1], "fr")
            self.assertEqual(Path(result["file"]).read_text(encoding="utf-8").split("\f"),
                             [translations[0], "", translations[1]])
            statements = result["statements"]["statements"]
            self.assertEqual(statements["Balance Sheet"]["source_pages"], [3])
            self.assertIn(["Revenue", "100", "90"], statements["IncomeStatement"]["rows"])
            self.assertTrue(any(call.args[:2] == ("translate", "done") for call in emit.await_args_list))
