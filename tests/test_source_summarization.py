"""No live model calls: transactional cache, independent reviews, frozen manifests."""
import copy
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock
from test_source_summarization_poc import fixture
import source_summarization as ss
import source_summarization_poc as poc
from source_aware import effective_retrieve
from research_store import Store

class SourceSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);Store(self.root);self.parent=fixture()
    def generate(self,provider=poc.mock_provider,extra=None):
        state=ss.state(self.parent,self.root)
        return ss.generate(self.parent,self.root,{'confirm_cost':True,'cache_key':state['cache_key'],**(extra or {})},provider)
    def decide(self,state,sid,decision):
        return ss.review(self.parent,self.root,dict(source_id=sid,decision=decision,attempt_id=state['attempt_id'],review_revision=state['review_revision']))

    def test_cache_review_persistence_frozen_input_and_parent_unchanged(self):
        before=copy.deepcopy(self.parent);provider=Mock(side_effect=poc.mock_provider)
        state=self.generate(provider);self.assertFalse(state['available']);provider.assert_called_once()
        self.generate(provider);provider.assert_called_once()
        self.assertEqual(state['manifest']['k_ext'],'')
        state=self.decide(state,'S1','approved');self.assertTrue(state['available'])
        state=self.decide(state,'S2','excluded')
        manifest=state['manifest'];self.assertEqual([u['source_id'] for u in manifest['units']],['S1'])
        self.assertEqual(ss.state(self.parent,self.root)['manifest'],manifest)
        child={'version_id':'child','version_number':2,'source_aware_manifest':manifest}
        fields=effective_retrieve(self.parent,child)
        self.assertEqual(fields['K_ext'],manifest['k_ext']);self.assertNotIn('[S2]',fields['K_ext'])
        for key in ('Rc','Rv','K_int'):self.assertEqual(fields[key],self.parent['output_snapshot']['retrieve'][key])
        # Future review changes do not alter a frozen child queued earlier.
        self.decide(state,'S1','excluded')
        self.assertEqual(effective_retrieve(self.parent,child)['K_ext'],fields['K_ext'])
        self.assertEqual(self.parent,before);self.assertFalse(manifest['semantic_verified'])
        altered=copy.deepcopy(child);altered['source_aware_manifest']['k_ext']='tampered'
        with self.assertRaises(ValueError):effective_retrieve(self.parent,altered)

    def test_quote_failure_approval_rejected_explicit_retry_saved(self):
        def invalid(value):
            raw,full=poc.mock_provider(value);obj=json.loads(raw);obj['summaries'][0]['supporting_quote']='invented';return json.dumps(obj),full
        state=self.generate(invalid);self.assertEqual(state['summary_status'],'validation_failed')
        with self.assertRaises(ValueError):self.decide(state,'S1','approved')
        provider=Mock(side_effect=poc.mock_provider);self.generate(provider);provider.assert_not_called()
        retried=self.generate(provider,{'retry_of':state['attempt_id'],'acknowledge_retry_cost':True})
        provider.assert_called_once();self.assertEqual(len(retried['attempt_history']),2)
        self.assertFalse(retried['available']);self.assertNotEqual(retried['attempt_id'],state['attempt_id'])
        with self.assertRaises(ValueError):self.decide(state,'S2','approved')

    def test_provider_failure_persisted_no_secret_and_no_auto_retry(self):
        provider=Mock(side_effect=RuntimeError('secret-key-do-not-expose'))
        state=self.generate(provider);self.assertEqual(state['summary_status'],'failed')
        self.generate(provider);provider.assert_called_once()
        self.assertNotIn('secret-key-do-not-expose',json.dumps(state))
        with ss.transaction(self.root) as db:
            data=db.execute('SELECT data FROM source_summary_attempts').fetchone()[0]
            self.assertNotIn('secret-key-do-not-expose',data)
            self.assertIn('input',json.loads(data))

    def test_concurrent_posts_only_one_batch_and_read_only_get(self):
        entered=threading.Event();release=threading.Event();calls=[]
        def provider(value):calls.append(1);entered.set();release.wait(5);return poc.mock_provider(value)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first=executor.submit(self.generate,provider)
            self.assertTrue(entered.wait(3))
            try:
                current=self.generate(provider);self.assertEqual(current['summary_status'],'running')
                self.assertEqual(ss.state(self.parent,self.root)['summary_status'],'running')
                self.assertEqual(len(calls),1)
            finally:release.set()
            self.assertEqual(first.result()['summary_status'],'succeeded')

    def test_cache_reused_but_reviews_isolated_across_parent_versions(self):
        provider=Mock(side_effect=poc.mock_provider);state=self.generate(provider);self.decide(state,'S1','approved')
        other=copy.deepcopy(self.parent);other['version_id']='other'
        current=ss.state(other,self.root);self.assertEqual(current['summary_status'],'succeeded');self.assertFalse(current['available'])
        ss.generate(other,self.root,{'confirm_cost':True,'cache_key':current['cache_key']},provider);provider.assert_called_once()
        other['experiment_id']='different-experiment';self.assertEqual(ss.state(other,self.root)['summary_status'],'not_generated')
        other=copy.deepcopy(self.parent);s=other['output_snapshot']['retrieve']['evidence']['sources'][0]
        s['article_text']+=' Changed body.';s['article_text_hash']=poc.digest(s['article_text'])
        self.assertEqual(ss.state(other,self.root)['summary_status'],'not_generated')

    def test_no_body_fallback_and_schema_failure(self):
        self.parent['output_snapshot']['retrieve']['sources']=[{'source_id':'g','source_url':'https://news.example/missing','source_title':'Grounding source'}]
        self.parent['output_snapshot']['retrieve']['evidence']['sources']=[]
        state=ss.state(self.parent,self.root);self.assertFalse(state['generation_available']);self.assertEqual(len(state['fallback_cards']),1)
        self.parent=fixture();state=self.generate(lambda value:('not json',{'raw':'not json'}))
        self.assertEqual(state['summary_status'],'validation_failed')
        self.assertFalse(any(c['can_review'] for c in state['manifest']['news_cards']))
