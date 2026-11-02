"""Offline V1 search recovery. Network and model dependencies are injected."""
import importlib.util
import json
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, Mock, patch

import test_research
from baseline_grounding import supplement, apply_verified_passages
from evidence import prepare_evidence
from evidence_assessment import text_hash
from research_runner import BASE, drain


QUOTE = 'The original event took place in June.'
URL = 'https://news.example/story'


def fields():
    return dict(run_id=1, Rc='claim', Rv='observation', K_int='internal',
                K_ext='initial external', sources=[], uri=[], query=[], grounding_supports=[])


def response():
    metadata = NS(web_search_queries=['event in June'], grounding_chunks=[
        NS(web=NS(uri=url, title='fixture')) for url in (URL, URL, 'http://127.0.0.1/test')],
        grounding_supports=[NS(segment=NS(text=QUOTE), grounding_chunk_indices=[1])])
    return NS(candidates=[NS(grounding_metadata=metadata)], text=QUOTE)


class BaselineGroundingTests(unittest.TestCase):
    def test_initial_grounding_no_extra_call(self):
        row = fields()
        row['uri'] = [URL]
        search = Mock()
        supplement(row, 'baseline', search, 'model')
        search.assert_not_called()
        self.assertEqual(row['supplemental_grounding']['attempts'], 0)
        self.assertEqual(row['K_ext'], 'initial external')

    def test_no_v2_or_legacy_call(self):
        for kind, number in [('input_correction', 2), ('', 1), ('baseline', 2)]:
            row = dict(fields(), run_id=number)
            search = Mock()
            supplement(row, kind, search, 'model')
            search.assert_not_called()
            self.assertNotIn('supplemental_grounding', row)

    def test_empty_and_error_are_valid_zero_source_results(self):
        for search, status in [(Mock(return_value=NS(candidates=[], text='invented URL')),
                                'no_usable_grounding_chunks'), (Mock(side_effect=TimeoutError()), 'supplement_failed')]:
            row = fields()
            supplement(row, 'baseline', search, 'model')
            apply_verified_passages(row)
            search.assert_called_once()
            self.assertEqual(row['supplemental_grounding']['status'], status)
            self.assertEqual(row['sources'], [])
            self.assertEqual(row['K_ext'], 'initial external')

    def test_links_without_corroborating_body_preserve_original_fields(self):
        row = fields()
        supplement(row, 'baseline', lambda _: response(), 'model')
        row['evidence'] = prepare_evidence(row, '', fetcher=lambda _: {'retrieval_status':'access_denied'})
        apply_verified_passages(row)
        self.assertFalse(row['supplemental_grounding']['k_ext_updated'])
        self.assertEqual(row['uri'], [URL])
        self.assertEqual(row['K_ext'], 'initial external')

    def test_real_retrieve_save_student_input_and_immutable_snapshot(self):
        c = test_research.ResearchTests(); c.setUp(); self.addCleanup(c.doCleanups)
        c.setup_research(); c.lock()
        vid = c.post('/versions', {'experiment_type':'baseline'}).json['version_id']
        body = 'Fixture article. ' + QUOTE
        client = MagicMock()
        generate = client.return_value.__enter__.return_value.models.generate_content
        generate.return_value = response()
        def execute(script, args, workspace, version):
            if script != 'Retrieve.py':
                return c.fake_execute(script, args, workspace, version)
            env = dict(WEAVE_WORK_DIR=str(workspace), WEAVE_ANALYSIS_ID=vid, WEAVE_RUN_ID='1',
                       WEAVE_EXPERIMENT_TYPE='baseline', GEMINI_API_KEY='offline')
            spec = importlib.util.spec_from_file_location('offline_v1_retrieve', BASE/'Retrieve.py')
            module = importlib.util.module_from_spec(spec)
            with patch.dict(os.environ, env), patch('dotenv.load_dotenv'):
                spec.loader.exec_module(module)
                initial = fields()
                initial['sources'] = [dict(source_id='s0',source_url='http://localhost')]
                def fetch(url):
                    self.assertEqual(url, URL)
                    return dict(retrieval_status='fetched', content_quality='full_article',
                                article_text=body, article_text_hash=text_hash(body))
                with patch.object(module, 'prepare_inputs', return_value=('t','v','p',['fixture'],['frame'])), \
                     patch.object(module, 'count_input_tokens', return_value=1), \
                     patch.object(module, 'generate_with_retry', return_value=(initial,'raw')), \
                     patch.object(module.genai, 'Client', client), \
                     patch.object(module,'prepare_evidence',side_effect=lambda row,t:prepare_evidence(row,t,fetcher=fetch)):
                    module.main()
        drain(c.store, execute)
        v = c.store.version(c.eid, vid)
        self.assertEqual(v['status'], 'succeeded', v['error'])
        generate.assert_called_once()
        args = generate.call_args.kwargs
        self.assertEqual(json.loads(args['contents']), {'Rc':'claim','Rv':'observation'})
        self.assertIsNotNone(args['config'].tools[0].google_search)
        self.assertEqual(client.call_args.kwargs['http_options'].retry_options.attempts, 1)
        snapshot = v['output_snapshot']
        row = snapshot['retrieve']
        rec = row['supplemental_grounding']
        self.assertEqual(rec['attempts'], 1)
        self.assertEqual(row['uri'], [URL])
        self.assertEqual(rec['chunk_to_source'], {'s0':'s1','s1':'s1'})
        self.assertEqual(rec['original_fields']['K_ext'], 'initial external')
        unit, = rec['additions']
        self.assertEqual(body[unit['start']:unit['end']], QUOTE)
        self.assertEqual(unit['article_text_hash'], text_hash(body))
        self.assertEqual(snapshot['student_trace']['fields'], {
            'Rc':'claim','Rv':'observation','K_int':'internal','K_ext':'initial external\n[s1] '+QUOTE})
