"""Standalone PoC tests: fixtures and injected providers only."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import source_summarization_poc as poc
from test_source_grounded import parent


def fixture():
    v=parent();v['experiment_id']='exp'
    for s in v['output_snapshot']['retrieve']['evidence']['sources']:s['content_quality']='partial_article'
    return v

class SummarizationPoCTests(unittest.TestCase):
    def test_fixed_ids_hashes_quality_dedup_and_no_mutation(self):
        v=fixture();ss=v['output_snapshot']['retrieve']['evidence']['sources'];ss.append({**ss[0],'source_id':'duplicate'})
        ss.append({**ss[0],'source_id':'bad','content_quality':'page_text_only'})
        before=copy.deepcopy(v);data=poc.select(v)
        self.assertEqual([s['source_id'] for s in data['sources']],['S1','S2']);self.assertEqual(v,before)
        self.assertEqual(data,poc.select(v))
        self.assertTrue(any(r['selection']=='Duplicate article' for r in data['selection_records']))
        data['sources'][0]['article_text']='tampered'
        with self.assertRaises(ValueError):poc.validate_input(data)

    def test_limits_do_not_silently_truncate(self):
        v=fixture()
        for s in v['output_snapshot']['retrieve']['evidence']['sources']:
            s['article_text']='a'*(poc.MAX_ARTICLE_CHARS+1);s['article_text_hash']=poc.digest(s['article_text'])
        with self.assertRaises(ValueError):poc.select(v)

    def test_output_schema_ids_blank_and_wrong_source_quotes(self):
        data=poc.select(fixture());raw,_=poc.mock_provider(data)
        self.assertEqual(poc.validate_output(raw,data)['status'],'structural_and_quote_checks_passed')
        good=json.loads(raw)
        variations=['not json',json.dumps({'summaries':[]})]
        for change in [{'source_id':'S99'},{'source_id':'S2'},{'summary':'   '},{'summary':42},{'supporting_quote':'Invented quote'},{'supporting_quote':data['sources'][1]['article_text'][:70]},{'extra':'forbidden'}]:
            bad=copy.deepcopy(good);bad['summaries'][0].update(change);variations.append(json.dumps(bad))
        for invalid in variations:self.assertEqual(poc.validate_output(invalid,data)['status'],'validation_failed')

    def test_one_batch_artifacts_no_overwrite_and_failure_record(self):
        value=poc.select(fixture());before=copy.deepcopy(value)
        with tempfile.TemporaryDirectory() as temp:
            provider=Mock(side_effect=poc.mock_provider);out=Path(temp)/'mock'
            result=poc.run(value,out,provider,'mock');provider.assert_called_once()
            self.assertEqual(result['mode'],'mock');self.assertFalse(result['semantic_verified'])
            self.assertEqual(json.loads((out/'input.json').read_text(encoding='utf-8')),value)
            self.assertTrue((out/'raw_output.txt').exists());self.assertTrue((out/'request.json').exists())
            with self.assertRaises(FileExistsError):poc.run(value,out,provider,'mock')
            provider=Mock(side_effect=TimeoutError('fixture'))
            result=poc.run(value,Path(temp)/'failure',provider,'mock')
            self.assertEqual(result['error_type'],'TimeoutError');provider.assert_called_once()
            self.assertEqual(value,before)
    def test_live_transport_is_one_mocked_sdk_call_without_search(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        data=poc.select(fixture());raw,_=poc.mock_provider(data)
        client=Mock();client.models.generate_content.return_value=SimpleNamespace(text=raw,model_dump=lambda **kw:{'text':raw})
        with patch.dict('os.environ',{'GEMINI_API_KEY':'fixture-not-real'}),patch('dotenv.load_dotenv'),patch('google.genai.Client',return_value=client) as factory:
            result=poc.live_provider(data)
        client.models.generate_content.assert_called_once();client.close.assert_called_once()
        self.assertEqual(factory.call_args.kwargs['http_options'].retry_options.attempts,1)
        args=client.models.generate_content.call_args.kwargs
        self.assertIsNone(args['config'].tools)
        self.assertEqual(len(json.loads(args['contents'])['articles']),2)
        self.assertEqual(result[0],raw)

    def test_live_cli_requires_confirmation_before_provider(self):
        from unittest.mock import patch
        value=poc.select(fixture())
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'input.json';poc.save(path,value)
            with patch('sys.argv',['poc','run','--input',str(path),'--output',str(Path(temp)/'live'),'--mode','live']),patch.object(poc,'live_provider') as provider:
                with self.assertRaises(SystemExit):poc.main()
                provider.assert_not_called()
                self.assertFalse(path.with_suffix('.live-attempt.lock').exists())
    def test_normalization_is_narrow_and_preserves_original_positions(self):
        body='prefix A\n\tB "quoted" and \'single\' suffix'
        quote='A B “quoted” and ‘single’'
        match=poc.match_quote(quote,body)
        self.assertEqual(match['status'],'normalized_match')
        self.assertEqual(match['model_quote'],quote)
        self.assertEqual(body[match['quote_start']:match['quote_end']],match['source_excerpt'])
        self.assertEqual(poc.normalize_quote(match['source_excerpt'])[0],poc.normalize_quote(quote)[0])
        self.assertTrue(match['normalization']['source_excerpt_changes'])
        self.assertTrue(match['normalization']['model_quote_changes'])
        self.assertEqual(poc.match_quote('A\n\tB',body)['status'],'exact_match')
        for invalid in ['a B "quoted"','A B quoted','A B "rewritten"','A...B']:
            self.assertEqual(poc.match_quote(invalid,body)['status'],'no_match')
        self.assertEqual(poc.match_quote('A B','A\nB A\tB')['status'],'ambiguous_normalized_match')

    def test_per_source_failures_do_not_hide_other_results(self):
        data=poc.select(fixture());raw,_=poc.mock_provider(data);obj=json.loads(raw)
        obj['summaries'][0]['supporting_quote']='invented quotation'
        result=poc.validate_output(json.dumps(obj),data)
        self.assertEqual(result['status'],'validation_failed')
        self.assertEqual(result['format_validation']['status'],'passed')
        self.assertEqual([r['quote_validation']['status'] for r in result['summaries']],['no_match','exact_match'])
        obj['summaries'][0]['summary']=42
        result=poc.validate_output(json.dumps(obj),data)
        self.assertEqual(result['format_validation']['status'],'failed')
        self.assertEqual(result['summaries'][1]['format_status'],'passed')
        self.assertEqual(result['summaries'][1]['quote_validation']['status'],'exact_match')
        self.assertFalse(result['semantic_verified'])

    def test_live01_saved_output_regression_read_only(self):
        import os
        root=Path(os.environ.get('WEAVE_POC_LIVE01',str(Path.home()/'.codex/visualizations/2026/10/23/01a1662b-aae0-7c81-8e6a-e34415db2757/source-summary-poc-20261030/live-01')))
        if not (root/'raw_output.txt').exists():self.skipTest('Saved private live-01 fixture not available')
        before={p.name:poc.digest(p.read_text(encoding='utf-8')) for p in root.iterdir() if p.is_file()}
        value=json.loads((root/'input.json').read_text(encoding='utf-8'));raw=(root/'raw_output.txt').read_text(encoding='utf-8')
        result=poc.validate_output(raw,value)
        self.assertEqual(result['format_validation']['status'],'passed')
        self.assertEqual(result['source_id_validation']['status'],'passed')
        self.assertEqual([r['source_id'] for r in result['summaries']],['S1','S2','S3'])
        self.assertEqual([r['quote_validation']['status'] for r in result['summaries']],['normalized_match','exact_match','normalized_match'])
        self.assertFalse(result['semantic_verified'])
        for row in result['summaries']:
            self.assertFalse(row['semantic_verified']);self.assertEqual(row['semantic_status'],'manual_review_required')
            source=next(s for s in value['sources'] if s['source_id']==row['source_id'])
            q=row['quote_validation'];self.assertEqual(source['article_text'][q['quote_start']:q['quote_end']],q['source_excerpt'])
        # Known old semantic problems remain in the record, not silently rewritten/approved.
        self.assertIn('官方已證實',result['summaries'][0]['summary'])
        self.assertIn('2021 年 7 月 1 日',result['summaries'][1]['summary'])
        self.assertEqual(before,{p.name:poc.digest(p.read_text(encoding='utf-8')) for p in root.iterdir() if p.is_file()})

    def test_prompt_retains_historical_and_attribution_constraints(self):
        for phrase in ('不得將媒體報導的結論改寫成官方聲明','不得合併','不得把歷史說法轉為現在','逐字複製','不得從其他文章'):
            self.assertIn(phrase,poc.PROMPT)
