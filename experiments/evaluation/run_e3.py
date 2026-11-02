"""Offline E3 scenarios. Reuses real API/store/runner and existing isolated fixtures.

Run with exmrd311 Python: python -B experiments/evaluation/run_e3.py
No live inference; socket connections are prohibited for the entire test run.
"""
import contextlib
import copy
import csv
import hashlib
import io
import json
import platform
import re
import socket
import sqlite3
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'backend')]
from test_selected_news import SelectedNewsTests
from test_research import ResearchTests
from research_store import Store, ResearchError
from research_runner import drain, read, write, sha
from selected_news import assemble


class Scenarios(SelectedNewsTests):
    def correction(self, field, value, parent=None):
        response = self.c.post('/versions', dict(experiment_type='input_correction',
            parent_version_id=(parent or self.parent)['version_id'], field=field, value=value))
        self.assertEqual(response.status_code, 201, response.json)
        drain(self.c.store, self.c.fake_execute)
        result = self.c.store.version(self.c.eid, response.json['version_id'])
        self.assertEqual(result['status'], 'succeeded', result.get('error'))
        return result

    def selected(self, ids):
        response = self.c.post('/versions', self.payload(ids))
        self.assertEqual(response.status_code, 201, response.json)
        calls = []
        expected = self.c.store.version(self.c.eid, response.json['version_id'])['selected_news_manifest']['k_ext']
        def execute(script, args, workspace, version):
            calls.append(script)
            self.c.fake_execute(script, args, workspace, version)
            trace = read(workspace / 'output/student_trace.json')
            trace.update(formatted_prompt=('- ' + expected) if expected else '無',
                         effective_input_ids=[[1, 2]], max_length=100)
            write(workspace / 'output/student_trace.json', trace)
        drain(self.c.store, execute)
        result = self.c.store.version(self.c.eid, response.json['version_id'])
        self.assertEqual(result['status'], 'succeeded', result.get('error'))
        self.assertEqual(calls, ['run_student.py'])
        return result

    def rc(self):
        value = '修正 Rc\nUnicode café — exact text  '
        child = self.correction('Rc', value)
        self.assertEqual(child['output_snapshot']['retrieve']['Rc'], value)
        self.assertEqual(child['input_snapshot']['student_fields']['Rc'], value)
        self.assertEqual(child['correction_payload']['after'], value)
        self.assertEqual(child['parent_version_id'], self.parent['version_id'])
        self.assertEqual(self.c.store.version(self.c.eid, self.parent['version_id']), self.parent)

    def rv(self):
        value = '修正視覺\nMultiple lines 🎥'
        child = self.correction('Rv', value)
        self.assertEqual(child['output_snapshot']['retrieve']['Rv'], value)
        self.assertEqual(child['input_snapshot']['student_fields']['Rv'], value)
        self.assertEqual(child['parent_version_id'], self.parent['version_id'])
        self.assertEqual(self.c.store.version(self.c.eid, self.parent['version_id']), self.parent)

    def foreign(self):
        # A second real temporary experiment, not a fabricated unknown identifier.
        other = self.c.client.post('/experiments', data={'video': (io.BytesIO(b'other'), 'other.mp4')}).json
        eid = other['experiment']['experiment_id']
        self.c.store.lock_human(eid, 'true', '')
        parent, _ = self.c.store.create_version(eid, {})
        # Fixture output only; all subsequent validation uses the real Store/API.
        self.c.store.update(eid, parent['version_id'], status='succeeded',
                            output_snapshot=copy.deepcopy(self.parent['output_snapshot']))
        request = {**self.payload(self.ids), 'parent_version_id': parent['version_id']}
        response = self.c.client.post('/experiments/' + eid + '/versions', json=request,
            headers={'Authorization': 'Bearer ' + other['access_token']})
        self.assertEqual(response.status_code, 400, response.json)
        self.assertEqual(len(self.c.store.versions(eid)), 1)
        self.assertNotEqual(self.c.post('/versions', request).status_code, 201)
        denied = self.c.client.get('/experiments/' + eid + '/versions', headers=self.c.headers)
        self.assertIn(denied.status_code, (401, 404))

    def lineage(self):
        v2 = self.correction('Rc', 'branch two')
        v3 = self.correction('Rv', 'branch three')
        v4 = self.correction('Rc', 'descendant four', v2)
        versions = self.c.store.versions(self.c.eid)
        self.assertEqual([v['version_number'] for v in versions], [1, 2, 3, 4])
        self.assertEqual(len({v['version_id'] for v in versions}), 4)
        self.assertTrue(all(v['experiment_id'] == self.c.eid for v in versions))
        self.assertEqual([v['parent_version_id'] for v in (v2, v3, v4)],
                         [self.parent['version_id'], self.parent['version_id'], v2['version_id']])
        self.assertEqual(self.c.store.version(self.c.eid, v3['version_id']), v3)

    def concurrent(self):
        request = self.payload(self.ids[:1])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.c.store.create_version(self.c.eid, request), range(8)))
        self.assertEqual(len({v['version_id'] for v, _ in results}), 1)
        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(len(self.c.store.versions(self.c.eid)), 2)

    def isolation(self):
        def fingerprint(v):
            work = Path(v['artifact_paths']['workspace'])
            return {str(p.relative_to(work)): sha(p) for p in work.rglob('*') if p.is_file()}
        original = fingerprint(self.parent)
        v2 = self.correction('Rc', 'new Rc only')
        second = fingerprint(v2)
        self.assertEqual(v2['output_snapshot']['retrieve']['Rv'], self.parent['output_snapshot']['retrieve']['Rv'])
        v3 = self.correction('Rv', 'new Rv only', v2)
        self.assertEqual(v3['output_snapshot']['retrieve']['Rc'], 'new Rc only')
        self.assertEqual(fingerprint(self.parent), original)
        self.assertEqual(fingerprint(v2), second)
        for v in (self.parent, v2):
            self.assertEqual(self.c.store.version(self.c.eid, v['version_id']), v)
            with self.assertRaises(ResearchError):
                self.c.store.update(self.c.eid, v['version_id'], output_snapshot={'overwrite': True})

    def failure(self):
        v2 = self.correction('Rc', 'successful second')
        before = {v['version_id']: {str(p): sha(p) for p in Path(v['artifact_paths']['workspace']).rglob('*') if p.is_file()}
                  for v in (self.parent, v2)}
        response = self.c.post('/versions', self.payload(self.ids[:1]))
        self.assertEqual(response.status_code, 201)
        def fail(*args):
            raise TimeoutError('E3 injected inference timeout')
        drain(self.c.store, fail)
        failed = self.c.store.version(self.c.eid, response.json['version_id'])
        self.assertEqual(failed['status'], 'failed')
        self.assertIsNone(failed['output_snapshot'])
        self.assertTrue((Path(failed['artifact_paths']['workspace']) / 'failure.json').is_file())
        for v in (self.parent, v2):
            self.assertEqual(self.c.store.version(self.c.eid, v['version_id']), v)
            self.assertEqual(before[v['version_id']], {str(p): sha(p) for p in Path(v['artifact_paths']['workspace']).rglob('*') if p.is_file()})

    def comparison(self):
        rc = self.correction('Rc', 'comparison Rc')
        rv = self.correction('Rv', 'comparison Rv')
        news = self.selected(self.ids[:1])
        response = self.c.client.get(self.c.base + '/versions', headers=self.c.headers)
        self.assertEqual(response.status_code, 200)
        versions = response.json['versions']
        for child in (rc, rv, news):
            fetched = self.c.client.get(self.c.base + '/versions/' + child['version_id'] + '/result', headers=self.c.headers)
            self.assertEqual(fetched.status_code, 200)
            self.assertEqual(fetched.json['output_snapshot'], child['output_snapshot'])
        code = (ROOT / 'src/components/VersionComparison.vue').read_text(encoding='utf-8')
        function = re.search(r'function differences\(version\) \{[\s\S]*?\n\}', code)
        self.assertIsNotNone(function, 'Existing comparison function extraction changed')
        script = "let raw='';for await(const c of process.stdin)raw+=c;const props=JSON.parse(raw);" + function[0] + ';console.log(JSON.stringify(props.versions.map(differences)));'
        proc = subprocess.run(['node', '--input-type=module', '-e', script], input=json.dumps({'versions': versions}),
                              encoding='utf-8', capture_output=True, check=True, timeout=30)
        diffs = json.loads(proc.stdout)
        self.assertIsNone(diffs[0])
        for i, key in ((1, 'Rc'), (2, 'Rv'), (3, 'K_ext')):
            self.assertEqual(diffs[i]['compared_to_version'], 1)
            for field, change in diffs[i]['fields'].items():
                self.assertEqual(change['before'], versions[0]['output_snapshot']['retrieve'][field])
                self.assertEqual(change['after'], versions[i]['output_snapshot']['retrieve'][field])
            self.assertIn(key, diffs[i]['fields'])
        self.assertEqual(set(diffs[3]['fields']), {'K_ext'})

    def provenance(self):
        child = self.selected(self.ids[::-1])
        m = child['selected_news_manifest']
        self.assertEqual([u['source_id'] for u in m['units']], [r['source_id'] for r in self.ids[::-1]])
        self.assertEqual(child['input_snapshot']['student_fields']['K_ext'], assemble(m['units']))
        for u in m['units']:
            self.assertEqual(hashlib.sha256(u['source_manifest']['article_text'].encode()).hexdigest(), u['article_text_hash'])
            self.assertEqual(hashlib.sha256(u['summary'].encode()).hexdigest(), u['summary_hash'])
            self.assertFalse(u['semantic_verified'])
            self.assertFalse(u['human_approved'])
        work = Path(child['artifact_paths']['workspace'])
        for name, digest in child['provenance']['files'].items():
            self.assertEqual(sha(work / name), digest)
        self.assertEqual(read(work / 'snapshot.json'), child['output_snapshot'])
        fresh = Store(self.c.store.root)
        self.assertEqual(fresh.versions(self.c.eid), self.c.store.versions(self.c.eid))
        self.assertEqual(fresh.version(self.c.eid, child['version_id']), child)


# Each row is a distinct scenario, not a count of individual assertions.
CASES = [
 ('A01', 'A', Scenarios, 'rc', 'Corrected multiline Rc reaches saved input/output; V1 and parent link preserved.', 'new'),
 ('A02', 'A', Scenarios, 'rv', 'Corrected multiline Rv reaches saved input/output; V1 and parent link preserved.', 'new'),
 ('A03', 'A', ResearchTests, 'test_no_change_empty_invalid_field_and_unavailable_transcript', 'Reject invalid/no-op corrections without new versions.', 'existing'),
 ('B01', 'B', SelectedNewsTests, 'test_selected_and_empty_student_only_parent_immutable_and_idempotent', 'Selected and empty K_ext reach Student-only runner; manifest/order/other inputs and parent preserved.', 'existing'),
 ('B02', 'B', SelectedNewsTests, 'test_reject_invalid_stale_foreign_duplicate_and_arbitrary_text', 'Reject duplicate, unknown, stale identities and arbitrary input before dispatch.', 'existing'),
 ('B03', 'B', SelectedNewsTests, 'test_failed_or_missing_summary_rejected', 'Reject failed or empty saved summaries.', 'existing'),
 ('B04', 'B', Scenarios, 'foreign', 'Reject source records from another experiment even with copied evidence; enforce API ownership.', 'new'),
 ('C01', 'C', Scenarios, 'lineage', 'Unique ordered IDs, consistent experiment, correct sibling and descendant parent links.', 'new'),
 ('C02', 'C', Scenarios, 'concurrent', 'Eight concurrent identical requests create exactly one pending child.', 'new'),
 ('D01', 'D', Scenarios, 'isolation', 'V3 preserves V1/V2 records and all workspace hashes; unedited input remains unchanged.', 'new'),
 ('D02', 'D', Scenarios, 'failure', 'Failed Student rerun retains diagnostics without corrupting successful V1/V2.', 'new'),
 ('E01', 'E', Scenarios, 'comparison', 'Authenticated API snapshots and actual Vue comparison function report correct parent/field differences.', 'new'),
 ('E02', 'E', Scenarios, 'provenance', 'Selected source/body/summary hashes and file provenance survive Store reload.', 'new'),
 ('E03', 'E', SelectedNewsTests, 'test_frontend_preview_equals_server_assembly', 'Actual frontend preview equals backend assembly for nonempty and empty selection.', 'existing'),
]


def main():
    records = []
    with patch.object(socket.socket, 'connect', side_effect=RuntimeError('E3 network prohibited')), \
         patch.object(socket.socket, 'connect_ex', side_effect=RuntimeError('E3 network prohibited')):
        for ident, category, cls, method, expected, origin in CASES:
            result = unittest.TestResult()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                cls(method).run(result)
            failures = result.failures + result.errors
            status = 'Fail' if failures else 'Skip' if result.skipped else 'Pass'
            reason = '\n'.join(detail for _, detail in failures) or '; '.join(reason for _, reason in result.skipped)
            source = 'experiments/evaluation/run_e3.py' if cls is Scenarios else 'tests/' + cls.__module__ + '.py'
            records.append(dict(test_id='E3-' + ident, category='E3-' + category, expected=expected,
                actual='Scenario assertions completed successfully.' if status == 'Pass' else reason,
                status=status, test_function=source + ':' + method, origin=origin, reason=reason))
            print('E3-' + ident + ': ' + status)
    def metrics(rows):
        counts = {s.lower(): sum(r['status'] == s for r in rows) for s in ('Pass', 'Fail', 'Skip')}
        executed = counts['pass'] + counts['fail']
        return dict(total=len(rows), executed=executed, passed=counts['pass'], failed=counts['fail'],
                    skipped=counts['skip'], pass_rate=round(100 * counts['pass'] / executed, 2) if executed else None)
    totals = metrics(records)
    categories = {c: metrics([r for r in records if r['category'] == c]) for c in sorted({r['category'] for r in records})}
    regression = None
    out = Path(__file__).resolve().parent
    if '--regression' in sys.argv:
        modules = ('test_research', 'test_selected_news', 'test_automatic_summaries')
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in modules)
        with (out / 'e3_regression.log').open('w', encoding='utf-8') as log, \
             contextlib.redirect_stdout(log), contextlib.redirect_stderr(log), \
             patch.object(socket.socket, 'connect', side_effect=RuntimeError('E3 network prohibited')), \
             patch.object(socket.socket, 'connect_ex', side_effect=RuntimeError('E3 network prohibited')):
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
        regression = dict(modules=modules, run=result.testsRun, failures=len(result.failures),
                          errors=len(result.errors), skipped=len(result.skipped), success=result.wasSuccessful())
        regression['passed'] = result.testsRun - regression['failures'] - regression['errors'] - regression['skipped']
    tracked = ['backend/research_store.py', 'backend/research_runner.py', 'backend/research_api.py',
               'backend/selected_news.py', 'backend/automatic_summaries.py', 'src/components/VersionComparison.vue',
               'src/workspaceNews.js', 'tests/test_research.py', 'tests/test_selected_news.py',
               'experiments/evaluation/run_e3.py']
    report = dict(evaluation='E3 Interactive Verification & Version Integrity',
        generated_at=datetime.now(timezone.utc).isoformat(),
        environment=dict(python=sys.version, executable=sys.executable, platform=platform.platform(), sqlite=sqlite3.sqlite_version,
                         node=subprocess.check_output(['node', '--version'], text=True).strip()),
        command='python -B experiments/evaluation/run_e3.py' + (' --regression' if regression else ''),
        regression=regression, totals=totals, categories=categories, checks=records,
        source_sha256={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in tracked})
    (out / 'e3_version_integrity.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    with (out / 'e3_version_integrity.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0])); writer.writeheader(); writer.writerows(records)
    lines = ['# E3 — Interactive Verification & Version Integrity', '',
        '## Objective and methodology',
        'Evaluate input correction, evidence selection, immutable versions, lineage and provenance using actual Flask routes, SQLite Store, version runner and saved files. Each check is a scenario (not an assertion count). All fixtures use temporary directories/databases. Socket connections are blocked. Preprocess/Retrieve outputs and StudentBot inference are mocked; the real run_student.py entrypoint is exercised. No production records are loaded or changed.', '',
        f"Environment: Python {platform.python_version()}, SQLite {sqlite3.sqlite_version}, Node {report['environment']['node']}; {platform.platform()}.",
        'Reproduce from repository root: `' + report['command'] + '` (exmrd311).',
        'This sandbox required TEMP and TMP to point to the allowed external visualization workspace. The initial default-temp run failed during fixture setup (Windows access denied); it is not an integrity result. Two initial new-test failures were due to the mock formatted prompt omitting the runner-required list prefix; only the fixture was corrected. Production code and existing tests were not changed.',
        'Exact PowerShell invocation used for the final run:',
        '```powershell',
        "$env:TEMP = 'C:\\Users\\user\\.codex\\visualizations\\2026\\10\\23\\01a1662b-aae0-7c81-8e6a-e34415db2757'",
        '$env:TMP = $env:TEMP',
        "& 'C:\\Users\\user\\anaconda3\\envs\\exmrd311\\python.exe' -B experiments/evaluation/run_e3.py --regression",
        '```',
        'Existing tests are reused without modification; new scenarios reuse their isolated fixtures. Comparison executes the existing Vue differences function in Node, not a browser. Source hashes and detailed check outcomes are in JSON/CSV.', '',
        '| Category | Total | Executed | Passed | Failed | Skipped | Pass rate |', '|---|---:|---:|---:|---:|---:|---:|']
    for name, m in [*categories.items(), ('Overall', totals)]:
        lines.append(f"| {name} | {m['total']} | {m['executed']} | {m['passed']} | {m['failed']} | {m['skipped']} | {m['pass_rate']}% |")
    lines += ['', f"Existing scenarios: {sum(r['origin']=='existing' for r in records)}; new scenarios: {sum(r['origin']=='new' for r in records)}.",
        'Version Integrity Pass Rate = passed / (passed + failed) × 100%; skips are excluded.', '', '## Failed or skipped checks']
    lines += [r['test_id'] + ': ' + r['reason'] for r in records if r['status'] != 'Pass'] or ['None.']
    lines += ['', '## Implementation paths inspected',
        '- `backend/research_api.py`: authorized POST /experiments/<eid>/versions, GET versions and GET versions/<vid>/result.',
        '- `backend/research_store.py`: create_version validation, parent lookup, transactional request deduplication, unique version IDs/order, terminal-version update guard; SQLite experiments/versions JSON records.',
        '- `backend/research_runner.py`: isolated version workspaces, correction overrides, selected-news Student-only routing, input/output snapshots, failure records and file hashes.',
        '- `backend/selected_news.py`: plan, assemble and effective_retrieve verify saved summaries, body hashes, source identity and frozen manifest.',
        '- `backend/automatic_summaries.py`: saved summary fixtures and cache; mock provider only.',
        '- `src/components/VersionComparison.vue`: differences; `src/workspaceNews.js`: actual preview assembly (read and executed in Node; not edited).',
        '', '## Existing regression tests (reported separately, not added to E3 denominator)',
        json.dumps(regression, ensure_ascii=False) if regression else 'Not requested in this run.',
        'Detailed unittest results: `e3_regression.log` when --regression is used. Reused E3 scenarios overlap this suite; do not add their counts together as independent coverage.']
    lines += ['', '## Limitations',
        'This deterministic fixture evaluation measures software integrity, not model accuracy, news truth, human usability, production-scale concurrency or live provider reliability. Concurrent testing covers eight identical Store requests in one process. Reload tests reopen SQLite through a fresh Store, not an OS reboot. The cross-experiment test uses a separately created fixture experiment. Browser rendering is not tested. Mock inference cannot establish real tokenization, GPU behavior or generated reasoning quality.', '',
        '## Demo Paper Results (English)',
        f"In an offline integration evaluation of WEAVE’s interactive version-management workflow, {totals['passed']} of {totals['executed']} executed scenario checks passed (Version Integrity Pass Rate: {totals['pass_rate']}%; {totals['failed']} failed, {totals['skipped']} skipped). The scenarios exercised input correction, selected-news input construction, parent–child lineage, version isolation, and comparison/provenance retrieval through the implementation’s persistence and API logic. External inference was mocked and isolated temporary databases were used. These results characterize integrity under the tested conditions, rather than model accuracy or end-to-end live-system reliability.", '',
        '## 繁體中文解讀',
        f"本次 E3 實際執行 {totals['executed']} 個情境檢查，通過 {totals['passed']} 個、失敗 {totals['failed']} 個、跳過 {totals['skipped']} 個，版本完整性通過率為 {totals['pass_rate']}%。評估使用真實 API、SQLite 與版本執行器，外部推論以 mock 取代；結果僅代表受測情境的資料完整性，不代表真實模型正確率或瀏覽器操作驗收。", '']
    (out / 'e3_summary.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(totals))
    if regression:
        print('Regression: ' + json.dumps(regression))
    return 1 if totals['failed'] or (regression and not regression['success']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
