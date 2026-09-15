# Extraction fixtures

`inputs/` contains Sophie's Carrefour sample PDF. The extraction regression test
checks the consolidated income statement on page 18, balance sheet on page 19,
and cash flow statement on page 20.

`reference_outputs/` preserves her original JSON and Excel examples. These are
historical examples, not expected test results: the original page-selection
heuristic chose narrative pages for some statements. Tests assert the corrected
source pages and generate fresh outputs in temporary directories.
