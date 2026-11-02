import copy
import unittest
from test_source_grounded import parent
from source_aware import plan,effective_retrieve


def fixture():
    p=parent();p['experiment_type']='baseline'
    r=p['output_snapshot']['retrieve'];r['K_ext']='The first event happened in 1990. The second event happened in 2000.'
    p['output_snapshot']['student_trace']['fields']['K_ext']=r['K_ext']
    r['sources']=[dict(source_id='s0',source_title='News A',source_url='https://news.example/a'),dict(source_id='s1',source_title='News B',source_url='https://news.example/b')]
    r['grounding_supports']=[dict(text='The first event happened in 1990.',source_ids=['s0']),dict(text='The second event happened in 2000.',source_ids=['s1'])]
    return p

class SourceAwareTests(unittest.TestCase):
    def test_attribution_without_article_download_and_parent_immutable(self):
        p=fixture();before=copy.deepcopy(p);m=plan(p)
        self.assertEqual(m['k_ext'],'[S1] The first event happened in 1990.\n[S2] The second event happened in 2000.')
        self.assertEqual(m['news_cards'][0]['url'],'https://news.example/a')
        self.assertEqual(plan(p),m)
        child=dict(version_id='child',version_number=2,source_aware_manifest=m)
        result=effective_retrieve(p,child)
        self.assertEqual(result['K_ext'],m['k_ext'])
        for field in ('Rc','Rv','K_int'):self.assertEqual(result[field],p['output_snapshot']['retrieve'][field])
        self.assertEqual(p,before)
        child['source_aware_manifest']={**m,'k_ext':'tampered'}
        with self.assertRaises(ValueError):effective_retrieve(p,child)

    def test_ambiguous_partial_cross_field_and_fabricated_ids_unavailable(self):
        for delta in [dict(source_ids=['s0','s1']),dict(source_ids=['invented']),dict(text='first event'),dict(text='"K_ext": "The first event happened in 1990."')]:
            p=fixture();p['output_snapshot']['retrieve']['grounding_supports']=[{**p['output_snapshot']['retrieve']['grounding_supports'][0],**delta}]
            m=plan(p);self.assertEqual(m['units'],[]);self.assertEqual(len(m['news_cards']),2)
        p=fixture();p['experiment_type']='source_grounded_baseline';self.assertFalse(plan(p)['units'])
        p=fixture();p['output_snapshot']['retrieve']['sources'][0]['source_url']='http://localhost/private'
        self.assertFalse(plan(p)['news_cards'][0]['url_valid'])

    def test_duplicate_urls_preserve_grounding_ids(self):
        p=fixture();r=p['output_snapshot']['retrieve'];r['sources'].append({**r['sources'][0],'source_id':'s2'})
        r['grounding_supports'][0]['source_ids']=['s0','s2']
        m=plan(p);self.assertEqual(len(m['news_cards']),2);self.assertEqual(m['news_cards'][0]['grounding_source_ids'],['s0','s2'])
        self.assertEqual(len(m['units']),2)
