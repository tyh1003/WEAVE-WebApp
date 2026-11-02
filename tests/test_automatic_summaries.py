"""Automatic path is always injected with offline providers; no network/model calls."""
import copy
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from test_source_summarization_poc import fixture
import automatic_summaries as auto
import source_summarization as manual
import source_summarization_poc as poc
from research_store import Store


class AutomaticSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        Store(self.root)
        self.parent = fixture()
        self.retrieved = self.parent['output_snapshot']['retrieve']

    def enqueue(self):
        return auto.enqueue(self.root, self.parent, self.retrieved)

    def state(self):
        return auto.state(self.root, self.parent['experiment_id'], self.parent['version_id'])

    def test_all_articles_dedup_skips_persistence_and_no_mutation(self):
        sources = self.retrieved['evidence']['sources']
        for i in range(2, 6):
            body = 'Distinct saved article '+str(i)+'. '*200
            sources.append({**sources[0], 'source_id': 's'+str(i), 'source_url': 'https://news.example/'+str(i),
                            'resolved_url': 'https://news.example/'+str(i), 'article_text': body,
                            'article_text_hash': poc.digest(body)})
        sources.extend([{**sources[0], 'source_id':'dup', 'resolved_url':'https://mirror.example/a'},
                        {'source_id':'missing', 'source_url':'https://missing.example/a'},
                        {**sources[0], 'source_id':'large', 'article_text':'a'*13000, 'article_text_hash':poc.digest('a'*13000)},
                        {**sources[0], 'source_id':'youtube', 'source_type':'youtube'}])
        before = copy.deepcopy(self.parent)
        provider = Mock(side_effect=poc.mock_provider)
        self.enqueue(); auto.process(self.root, provider)
        self.assertEqual(provider.call_count, 6)
        current = self.state()
        self.assertEqual(current['status'], 'completed')
        self.assertEqual(len(current['records']), 10)
        self.assertEqual(sum(r['status']=='skipped' for r in current['records']), 4)
        self.assertTrue(all(r['reason'] for r in current['records'] if r['status']=='skipped'))
        self.assertEqual(self.parent, before)
        self.assertNotIn('inputs', current)
        self.assertTrue(all('article_text' not in r.get('source_manifest', {}) for r in current['records']))
        self.enqueue(); auto.process(self.root, provider)
        self.assertEqual(provider.call_count, 6)
        self.assertEqual(current, self.state())

    def test_cache_across_versions_and_changed_body(self):
        provider = Mock(side_effect=poc.mock_provider)
        self.enqueue(); auto.process(self.root, provider)
        self.parent['version_id']='next'
        self.enqueue(); auto.process(self.root, provider)
        self.assertEqual(provider.call_count, 2)
        self.parent['version_id']='changed'
        s=self.retrieved['evidence']['sources'][0]
        s['article_text']+='New saved content.';s['article_text_hash']=poc.digest(s['article_text'])
        self.enqueue(); auto.process(self.root, provider)
        self.assertEqual(provider.call_count, 3)
        self.parent['experiment_id']='other'
        self.parent['version_id']='other'
        self.enqueue(); auto.process(self.root, provider)
        self.assertEqual(provider.call_count, 5)

    def test_partial_failure_keeps_success_no_automatic_paid_retry(self):
        calls=[]
        def provider(value):
            calls.append(value)
            if len(calls)==1: raise TimeoutError('secret credential')
            return poc.mock_provider(value)
        self.enqueue();auto.process(self.root, provider)
        state=self.state()
        self.assertEqual(state['status'],'partial')
        self.assertEqual([r['status'] for r in state['records']], ['failed','completed'])
        self.assertNotIn('secret credential',json.dumps(state))
        self.enqueue();auto.process(self.root, provider)
        self.assertEqual(len(calls),2)
        self.assertTrue(state['records'][1]['summary'])

    def test_malformed_json_wrong_quote_and_provider_failure(self):
        for provider in [lambda v: ('invalid',{}), lambda v: (json.dumps({'summaries':[{
                'source_id':'S1','summary':'測試摘要','supporting_quote':'invented quote'}]}),{}),
                Mock(side_effect=RuntimeError('rate limit'))]:
            with tempfile.TemporaryDirectory() as tmp:
                Store(tmp);auto.enqueue(tmp,self.parent,self.retrieved);auto.process(tmp,provider)
                state=auto.state(tmp,'exp','parent')
                self.assertEqual(state['status'],'failed')
                self.assertTrue(all(not r.get('summary') for r in state['records']))

    def test_manual_approved_summary_reused_without_overwrite(self):
        current=manual.state(self.parent,self.root)
        current=manual.generate(self.parent,self.root,{'confirm_cost':True,'cache_key':current['cache_key']},poc.mock_provider)
        manual.review(self.parent,self.root,dict(source_id='S1',decision='approved',attempt_id=current['attempt_id'],review_revision=current['review_revision']))
        before=manual.state(self.parent,self.root)
        provider=Mock(side_effect=AssertionError('Must reuse valid manual summaries'))
        self.enqueue();auto.process(self.root,provider)
        provider.assert_not_called()
        self.assertEqual(before,manual.state(self.parent,self.root))
        self.assertTrue(all(r.get('reused_manual_attempt') for r in self.state()['records']))
        self.assertTrue(all(not r['human_approved'] and not r['semantic_verified'] for r in self.state()['records']))

    def test_concurrent_workers_do_not_duplicate_calls(self):
        entered=threading.Event();release=threading.Event();calls=[]
        def provider(value):
            calls.append(value);entered.set();release.wait(5);return poc.mock_provider(value)
        self.enqueue()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(auto.process,self.root,provider)
            self.assertTrue(entered.wait(3))
            self.enqueue();second=pool.submit(auto.process,self.root,provider)
            try:self.assertEqual(self.state()['status'],'running')
            finally:release.set()
            first.result();second.result()
        self.assertEqual(len(calls),2)

    def test_no_articles_and_interrupted_request(self):
        self.retrieved['evidence']['sources']=[]
        self.enqueue();provider=Mock()
        auto.process(self.root,provider);provider.assert_not_called()
        self.assertEqual(self.state()['status'],'ineligible')
        self.parent=fixture();self.parent['version_id']='interrupted'
        self.retrieved=self.parent['output_snapshot']['retrieve']
        job=self.enqueue()
        with manual.transaction(self.root) as db:
            for key in job['inputs']:
                db.execute('INSERT INTO automatic_summary_cache VALUES (?,?)',(key,json.dumps({'status':'running'})))
        auto.process(self.root,provider);provider.assert_not_called()
        self.assertEqual(self.state()['status'],'failed')

    def test_dispatch_failure_isolated_and_recorded(self):
        auto.dispatch(self.root,self.parent,self.retrieved,Mock(side_effect=OSError('cannot launch')))
        self.assertEqual(self.state()['status'],'failed')
        with patch.object(auto,'enqueue',side_effect=OSError('disk')):
            auto.dispatch(self.root,self.parent,self.retrieved)

    def test_dispatch_is_nonblocking_and_uses_existing_interpreter(self):
        with patch.object(auto.subprocess,'Popen') as start:
            auto.dispatch(self.root,self.parent,self.retrieved,auto.launch)
            start.assert_called_once()
            self.assertEqual(start.call_args.args[0][0],auto.sys.executable)
            start.return_value.wait.assert_not_called()
            start.return_value.communicate.assert_not_called()
            self.assertEqual(self.state()['status'],'pending')


class AutomaticRunnerTests(unittest.TestCase):
    def test_retrieve_integration_and_student_unchanged_even_when_launch_fails(self):
        from test_research import ResearchTests
        from research_runner import drain, read, write
        case=ResearchTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.setup_research();case.lock()
        version=case.post('/versions',{'experiment_type':'baseline'}).json
        path=f"/experiments/{case.eid}/versions/{version['version_id']}/automatic-summaries"
        self.assertEqual(case.client.get(path,headers=case.headers).status_code,409)
        fields={}
        def execute(script,args,work,v):
            if script=='run_student.py':
                self.assertEqual(auto.state(case.store.root,case.eid,version['version_id'])['status'],'failed')
            case.fake_execute(script,args,work,v)
            if script=='Retrieve.py':
                data=json.loads((work/'output/retrieve.jsonl').read_text().strip())
                data['evidence']=fixture()['output_snapshot']['retrieve']['evidence']
                (work/'output/retrieve.jsonl').write_text(json.dumps(data)+'\n',encoding='utf-8')
                fields.update({k:data[k] for k in ('Rc','Rv','K_int','K_ext')})
        launch=Mock(side_effect=OSError('mock launch unavailable'))
        drain(case.store,execute,summary_dispatch=launch)
        launch.assert_called_once()
        saved=case.store.version(case.eid,version['version_id'])
        self.assertEqual(saved['status'],'succeeded')
        self.assertEqual(saved['output_snapshot']['student_trace']['fields'],fields)
        response=case.client.get(path,headers=case.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['status'],'failed')
        self.assertEqual(case.client.get(path).status_code,401)

