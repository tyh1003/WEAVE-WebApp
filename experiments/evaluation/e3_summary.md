# E3 — Interactive Verification & Version Integrity

## Objective and methodology
Evaluate input correction, evidence selection, immutable versions, lineage and provenance using actual Flask routes, SQLite Store, version runner and saved files. Each check is a scenario (not an assertion count). All fixtures use temporary directories/databases. Socket connections are blocked. Preprocess/Retrieve outputs and StudentBot inference are mocked; the real run_student.py entrypoint is exercised. No production records are loaded or changed.

Environment: Python 3.11.16, SQLite 3.53.4, Node v24.16.0; Windows-10-10.0.26200-SP0.
Reproduce from repository root: `python -B experiments/evaluation/run_e3.py --regression` (exmrd311).
This sandbox required TEMP and TMP to point to the allowed external visualization workspace. The initial default-temp run failed during fixture setup (Windows access denied); it is not an integrity result. Two initial new-test failures were due to the mock formatted prompt omitting the runner-required list prefix; only the fixture was corrected. Production code and existing tests were not changed.
Exact PowerShell invocation used for the final run:
```powershell
$env:TEMP = 'C:\Users\user\.codex\visualizations\2026\10\23\01a1662b-aae0-7c81-8e6a-e34415db2757'
$env:TMP = $env:TEMP
& 'C:\Users\user\anaconda3\envs\exmrd311\python.exe' -B experiments/evaluation/run_e3.py --regression
```
Existing tests are reused without modification; new scenarios reuse their isolated fixtures. Comparison executes the existing Vue differences function in Node, not a browser. Source hashes and detailed check outcomes are in JSON/CSV.

| Category | Total | Executed | Passed | Failed | Skipped | Pass rate |
|---|---:|---:|---:|---:|---:|---:|
| E3-A | 3 | 3 | 3 | 0 | 0 | 100.0% |
| E3-B | 4 | 4 | 4 | 0 | 0 | 100.0% |
| E3-C | 2 | 2 | 2 | 0 | 0 | 100.0% |
| E3-D | 2 | 2 | 2 | 0 | 0 | 100.0% |
| E3-E | 3 | 3 | 3 | 0 | 0 | 100.0% |
| Overall | 14 | 14 | 14 | 0 | 0 | 100.0% |

Existing scenarios: 5; new scenarios: 9.
Version Integrity Pass Rate = passed / (passed + failed) × 100%; skips are excluded.

## Failed or skipped checks
None.

## Implementation paths inspected
- `backend/research_api.py`: authorized POST /experiments/<eid>/versions, GET versions and GET versions/<vid>/result.
- `backend/research_store.py`: create_version validation, parent lookup, transactional request deduplication, unique version IDs/order, terminal-version update guard; SQLite experiments/versions JSON records.
- `backend/research_runner.py`: isolated version workspaces, correction overrides, selected-news Student-only routing, input/output snapshots, failure records and file hashes.
- `backend/selected_news.py`: plan, assemble and effective_retrieve verify saved summaries, body hashes, source identity and frozen manifest.
- `backend/automatic_summaries.py`: saved summary fixtures and cache; mock provider only.
- `src/components/VersionComparison.vue`: differences; `src/workspaceNews.js`: actual preview assembly (read and executed in Node; not edited).

## Existing regression tests (reported separately, not added to E3 denominator)
{"modules": ["test_research", "test_selected_news", "test_automatic_summaries"], "run": 38, "failures": 0, "errors": 0, "skipped": 0, "success": true, "passed": 38}
Detailed unittest results: `e3_regression.log` when --regression is used. Reused E3 scenarios overlap this suite; do not add their counts together as independent coverage.

## Limitations
This deterministic fixture evaluation measures software integrity, not model accuracy, news truth, human usability, production-scale concurrency or live provider reliability. Concurrent testing covers eight identical Store requests in one process. Reload tests reopen SQLite through a fresh Store, not an OS reboot. The cross-experiment test uses a separately created fixture experiment. Browser rendering is not tested. Mock inference cannot establish real tokenization, GPU behavior or generated reasoning quality.

## Demo Paper Results (English)
In an offline integration evaluation of WEAVE’s interactive version-management workflow, 14 of 14 executed scenario checks passed (Version Integrity Pass Rate: 100.0%; 0 failed, 0 skipped). The scenarios exercised input correction, selected-news input construction, parent–child lineage, version isolation, and comparison/provenance retrieval through the implementation’s persistence and API logic. External inference was mocked and isolated temporary databases were used. These results characterize integrity under the tested conditions, rather than model accuracy or end-to-end live-system reliability.

## 繁體中文解讀
本次 E3 實際執行 14 個情境檢查，通過 14 個、失敗 0 個、跳過 0 個，版本完整性通過率為 100.0%。評估使用真實 API、SQLite 與版本執行器，外部推論以 mock 取代；結果僅代表受測情境的資料完整性，不代表真實模型正確率或瀏覽器操作驗收。
