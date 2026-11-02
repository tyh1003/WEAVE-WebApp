import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from grounded_alignment import validate, locate


class AlignmentTests(unittest.TestCase):
    def check(self,body='The rumor was a prank.',quote=None,claim='該傳聞是一場惡作劇',**changes):
        raw=dict(claim_id='c',relevance='direct',stance='supports',target_scope='single',source_scope='original_event',
            verbatim_excerpt=body if quote is None else quote,excerpt_start=999,excerpt_end=1000,
            explanation='跨語言語意等價',evidence_coverage='full',quote_reasoning='The quoted sentence establishes that the rumor was a prank.')
        raw.update(changes)
        return validate(raw,body,10,'article_text',{'article_text':'0123456789'+body},[{'claim_id':'c','claim_text':claim}])

    def test_cross_language_mock_exact_backend_offsets(self):
        r=self.check();self.assertEqual(r['semantic_relation'],'Support')
        self.assertEqual(r['quote_verification'],'validated');self.assertEqual(r['excerpt_start'],10)
        self.assertEqual(r['model_offsets']['start'],999)
        self.assertEqual(r['quote_match']['status'],'exact_match')

    def test_normalization_maps_original_quote(self):
        body='He said “not\n  closing”.'
        r=self.check(body, 'He said "not closing".')
        self.assertEqual(r['quote_match']['status'],'normalized_match')
        self.assertEqual(r['verbatim_excerpt'],body);self.assertEqual(r['excerpt_end'],10+len(body))
        self.assertTrue(r['quote_match']['normalization'])

    def test_failed_quote_preserves_semantic_relation(self):
        r=self.check(quote='Invented quote')
        self.assertEqual(r['semantic_relation'],'Support');self.assertEqual(r['quote_verification'],'validation_failed')
        self.assertEqual(r['stance'],'not_established');self.assertIsNone(r['excerpt_provenance'])

    def test_ambiguity_not_resolved_using_model_offset(self):
        self.assertEqual(locate('same','same same')['status'],'ambiguous_exact_match')
        self.assertEqual(locate('a b','a\nb a  b')['status'],'ambiguous_normalized_match')

    def test_topic_partial_and_absolute_not_supported(self):
        for changes in ({'relevance':'contextual'},{'evidence_coverage':'partial'},{'claim':'官方從未發布過關閉公告'}):
            r=self.check(**changes);self.assertEqual(r['semantic_relation'],'Insufficient');self.assertEqual(r['stance'],'not_established')
        self.assertEqual(self.check(stance='refutes')['semantic_relation'],'Contradict')

    def test_old_response_not_promoted_without_quote_entailment(self):
        r=self.check(evidence_coverage=None,quote_reasoning=None)
        self.assertEqual(r['quote_verification'],'validated');self.assertEqual(r['semantic_relation'],'Insufficient')

    def test_missing_quote_and_schema_failure(self):
        r=self.check(quote='',relevance='insufficient',stance='not_established',evidence_coverage='insufficient')
        self.assertEqual(r['semantic_relation'],'Insufficient');self.assertEqual(r['quote_verification'],'validation_failed')
        with self.assertRaises(ValueError):self.check(stance='invented')
