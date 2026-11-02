import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from dataclasses import replace
from test_source_summarization_poc import fixture
import source_summarization as ss
import source_summarization_poc as poc
from research_store import Store
from grounded_explanation import describe, prepare, decompose
from version_assessment import CONFIG


class GroundedExplanationTests(unittest.TestCase):
    def test_literal_atomic_mapping_and_partial_support(self):
        reason='該短影音內容源自惡作劇產生器 Channel 45 News，旨在製作虛假標題以吸引讀者，且Mojang官方已證實 Minecraft 並未關閉，因此該內容為誤導性資訊。'
        claims,excluded=decompose(reason)
        self.assertEqual(len(claims),3);self.assertEqual(len(excluded),1)
        self.assertTrue(claims[0]['specific_video_origin']);self.assertTrue(claims[1]['unresolved_subject'])
        for c in claims:
            p=c['claim_provenance'];self.assertEqual(reason[p['start']:p['end']],c['claim_text'])
        self.v['output_snapshot']['student']['reason']=reason
        result=describe(self.v,self.root,self.config,self.provider(),True)
        self.assertEqual([i['relation'] for i in result['items']],['Insufficient Evidence','Insufficient Evidence','Support'])
        self.assertEqual(result['support_summary']['supported_claims'],1)
        self.assertIn('部分主張',result['support_summary']['notice'])

    def test_retry_append_only_and_duplicate_retry_reused(self):
        bad=self.provider(quote_valid=False)
        first=describe(self.v,self.root,self.config,bad,True)
        self.assertTrue(first['retry_available'])
        self.assertEqual(first['items'][0]['validation_error'],'no_match')
        old_files={p:p.read_bytes() for p in (self.root/'grounded_explanations').glob('*.json')}
        good=self.provider()
        second=describe(self.v,self.root,self.config,good,True,retry_of=first['attempt_id'])
        self.assertNotEqual(second['attempt_id'],first['attempt_id'])
        third=describe(self.v,self.root,self.config,good,True,retry_of=first['attempt_id'])
        self.assertEqual(third['attempt_id'],second['attempt_id']);good.assert_called_once()
        for path,data in old_files.items():self.assertEqual(path.read_bytes(),data)
        self.assertEqual(describe(self.v,self.root,self.config,good)['attempt_id'],second['attempt_id'])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);Store(self.root)
        parent=fixture();s=ss.state(parent,self.root)
        s=ss.generate(parent,self.root,dict(confirm_cost=True,cache_key=s['cache_key']),poc.mock_provider)
        s=ss.review(parent,self.root,dict(source_id='S1',decision='approved',attempt_id=s['attempt_id'],review_revision=s['review_revision']))
        self.v=copy.deepcopy(parent);self.v.update(version_id='child',source_aware_manifest=s['manifest'],input_snapshot={'student_fields':{'K_ext':s['manifest']['k_ext']}})
        self.v['output_snapshot']['student']={'pred_label':1,'reason':'The shutdown report came from a hoax website.'}
        self.config=replace(CONFIG,model_name='mock',max_sources=3)

    def provider(self,stance='supports',quote_valid=True):
        def respond(payload,**kwargs):
            text=payload['source_text']
            return dict(claim_id=payload['claims'][0]['claim_id'],relevance='direct',stance=stance,target_scope='single',source_scope='original_event',
                verbatim_excerpt=text if quote_valid else 'fabricated quote',excerpt_start=0,excerpt_end=len(text),explanation='Mock relation',evidence_coverage='full',quote_reasoning='The quote establishes the entire target assertion.')
        return Mock(side_effect=respond)

    def test_support_contradict_insufficient_cache_and_immutability(self):
        original=copy.deepcopy(self.v)
        for stance,valid,expected in [('supports',True,'Support'),('refutes',True,'Contradict'),('not_established',True,'Insufficient Evidence'),('supports',False,'Insufficient Evidence')]:
            with tempfile.TemporaryDirectory() as root:
                provider=self.provider(stance,valid)
                state=describe(self.v,root,self.config,provider);provider.assert_not_called()
                result=describe(self.v,root,self.config,provider,True)
                self.assertEqual(result['items'][0]['relation'],expected)
                self.assertEqual(result['items'][0]['source_id'],'S1')
                if not valid:self.assertIsNone(result['items'][0]['quote'])
                cached=describe(self.v,root,self.config,provider,True)
                self.assertEqual(cached['status'],'cached');provider.assert_called_once()
        self.assertEqual(original,self.v)

    def test_no_manifest_wrong_input_missing_text_and_cgi(self):
        provider=self.provider()
        for key in ('source_aware_manifest','input_snapshot'):
            bad=copy.deepcopy(self.v);bad.pop(key)
            self.assertEqual(describe(bad,self.root,self.config,provider,True)['status'],'unavailable')
        provider.assert_not_called()
        bad=copy.deepcopy(self.v)
        bad['source_aware_manifest']['summary_input']['sources'][0]['article_text']=''
        self.assertEqual(describe(bad,self.root,self.config,provider,True)['status'],'unavailable')
        provider.assert_not_called()
        self.v['output_snapshot']['student']['reason']='This particular video was edited using CGI.'
        result=describe(self.v,self.root,self.config,provider,True)
        self.assertEqual(result['items'][0]['relation'],'Insufficient Evidence')

    def test_api_error_persisted_and_version_cache_separate(self):
        provider=Mock(side_effect=RuntimeError('secret'))
        result=describe(self.v,self.root,self.config,provider,True)
        self.assertEqual(result['items'][0]['assessment_status'],'api_error')
        self.assertNotIn('secret',str(result))
        self.assertEqual(describe(self.v,self.root,self.config,provider)['status'],'cached')
        self.v['version_id']='different'
        self.assertNotEqual(describe(self.v,self.root,self.config,provider)['status'],'cached')
