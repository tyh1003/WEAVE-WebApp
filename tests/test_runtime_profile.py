"""Offline telemetry and language contract tests; no inference or external services."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_research
import test_automatic_summaries as test_auto
import automatic_summaries as auto
import source_summarization_poc as poc
from runtime_profile import observe_gemini, report, as_csv


class RuntimeTests(unittest.TestCase):
    def test_sdk_observation_preserves_calls_errors_and_redacts_payloads(self):
        response = SimpleNamespace(usage_metadata={'prompt_token_count': 7, 'total_token_count': 10})
        class Models:
            def generate_content(self, **kwargs):
                if kwargs.get('fail'): raise ValueError('original failure')
                return response
            def count_tokens(self, **kwargs): return SimpleNamespace(total_tokens=7)
        original = Models.generate_content
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp);(work/'output').mkdir()
            with patch.dict(sys.modules, {'google.genai.models': SimpleNamespace(Models=Models)}):
                with observe_gemini(work):
                    self.assertIs(Models().generate_content(contents='PRIVATE', api_key='SECRET'), response)
                    self.assertEqual(Models().count_tokens().total_tokens,7)
                    with self.assertRaisesRegex(ValueError,'original failure'):
                        Models().generate_content(fail=True)
            self.assertIs(Models.generate_content,original)
            raw=(work/'output/runtime_calls.jsonl').read_text()
            self.assertNotIn('PRIVATE',raw);self.assertNotIn('SECRET',raw)
            records=[json.loads(line) for line in raw.splitlines()]
            self.assertEqual(sum(r['event']=='started' for r in records),3)
            self.assertEqual(records[1]['token_usage']['total_token_count'],10)
            self.assertEqual(records[-1]['status'],'failed')

    def test_version_scoped_profile_exports_and_history(self):
        c=test_research.ResearchTests();c.setUp();self.addCleanup(c.doCleanups)
        c.setup_research();version=c.baseline()
        path=c.base+'/versions/'+version['version_id']+'/runtime-profile'
        self.assertEqual(c.client.get(path).status_code,401)
        response=c.client.get(path,headers=c.headers)
        self.assertEqual(response.status_code,200)
        data=response.json
        self.assertEqual(data['availability'],'recorded')
        self.assertTrue(all(v>=0 for v in data['latency_seconds'].values()))
        self.assertIsNone(data['external_sdk_call_count']) # mocked subprocess, not a measured API call
        self.assertIsNone(data['estimated_api_cost'])
        self.assertNotIn('reason',json.dumps(data))
        csv=c.client.get(path+'?format=csv',headers=c.headers)
        self.assertEqual(csv.status_code,200);self.assertIn('total_verification_seconds',csv.text)
        self.assertEqual(c.store.version(c.eid,version['version_id']),version)
        old=report({'experiment_id':'e','version_id':'v','status':'succeeded'})
        self.assertEqual(old['availability'],'unavailable_for_historical_version')
        self.assertIsNone(old['latency_seconds']['student'])

    def test_ten_articles_remain_independent_and_cache_adds_no_calls(self):
        c=test_auto.AutomaticSummaryTests();c.setUp();self.addCleanup(c.doCleanups)
        sources=c.retrieved['evidence']['sources']
        for i in range(2,10):
            body=('Article '+str(i)+' unique fact. ')*40
            sources.append({**sources[0],'source_id':'extra'+str(i),
                'source_url':'https://news.example/'+str(i),'resolved_url':'https://news.example/'+str(i),
                'article_text':body,'article_text_hash':poc.digest(body)})
        provider=Mock(side_effect=poc.mock_provider)
        c.enqueue();auto.process(c.root,provider)
        self.assertEqual(provider.call_count,10)
        job=c.state();self.assertEqual(job['runtime_profile']['external_sdk_call_count'],10)
        self.assertTrue(job['runtime_profile']['processing_seconds']>=0)
        c.parent['version_id']='cached-child'
        c.enqueue();auto.process(c.root,provider)
        self.assertEqual(provider.call_count,10)
        self.assertEqual(c.state()['runtime_profile']['external_sdk_call_count'],0)

    def test_translation_target_contract_without_provider_calls(self):
        c=test_research.ResearchTests();c.setUp();self.addCleanup(c.doCleanups)
        c.setup_research()
        zh=Mock(return_value={'explanation':'繁體中文理由'})
        with patch.dict(sys.modules,{'translator':SimpleNamespace(translate_to_language=zh)}):
            response=c.client.post('/translate',json={'texts':{'explanation':'Original reason'},'target_language':'zh'})
        self.assertEqual(response.status_code,200)
        zh.assert_called_once_with({'explanation':'Original reason'},'zh')
        self.assertEqual(c.client.post('/translate',json={'texts':{'x':'text'},'target_language':'invalid'}).status_code,400)


if __name__=='__main__': unittest.main()
