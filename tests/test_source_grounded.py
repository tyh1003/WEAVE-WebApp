"""Source-grounded assembly fixtures; no network, models or production records."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from source_grounded import plan, effective_retrieve, RULE
from evidence_assessment import text_hash


def parent():
    fields={'Rc':'original rc','Rv':'original rv','K_int':'original internal','K_ext':'old untraceable synthesis'}
    sources=[{'source_id':f's{i}','source_url':f'https://news.example/{i}','resolved_url':f'https://news.example/{i}',
              'retrieval_status':'fetched','article_title':f'Article {i}','article_text':f'Exact original article {i}. '*100,
              'article_text_hash':text_hash(f'Exact original article {i}. '*100)} for i in range(2)]
    return {'version_id':'parent','status':'succeeded','output_snapshot':{'student_trace':{'fields':copy.deepcopy(fields)},'retrieve':{**fields,'vid':'video','evidence':{'sources':sources}}}}


class SourceGroundedTests(unittest.TestCase):
    def test_units_manifest_ranges_hashes_and_reproducibility(self):
        p=parent();before=copy.deepcopy(p);m=plan(p)
        self.assertEqual(m,plan(p));self.assertEqual(p,before);self.assertEqual(len(m['units']),2)
        cursor=0
        for segment in m['segments']:
            self.assertEqual(segment['start'],cursor);cursor=segment['end']
            self.assertEqual(text_hash(m['k_ext'][segment['start']:cursor]),segment['text_hash'])
            self.assertEqual(segment['origin'],'publisher_text' if segment['kind']=='article_text' else 'assembler')
        self.assertEqual(cursor,len(m['k_ext']));self.assertEqual(text_hash(m['k_ext']),m['k_ext_hash'])
        for unit in m['units']:
            s=next(s for s in p['output_snapshot']['retrieve']['evidence']['sources'] if s['source_id']==unit['source_id'])
            self.assertEqual(s['article_text'][unit['provenance']['start']:unit['provenance']['end']],unit['evidence_text'])
            self.assertEqual(text_hash(unit['evidence_text']),unit['evidence_text_hash'])
            self.assertLessEqual(len(unit['evidence_text']),RULE['max_article_chars'])
        self.assertLessEqual(len(m['k_ext']),RULE['max_k_ext_chars'])
        child={'version_id':'child','version_number':2,'source_grounded_manifest':m}
        data=effective_retrieve(p,child)
        for key in ['Rc','Rv','K_int']:self.assertEqual(data[key],p['output_snapshot']['retrieve'][key])
        self.assertNotIn('old untraceable synthesis',data['K_ext']);self.assertEqual(p,before)
        child['source_grounded_manifest']=copy.deepcopy(m);child['source_grounded_manifest']['k_ext']='tampered'
        with self.assertRaises(ValueError):effective_retrieve(p,child)

    def test_dedup_and_unavailable_selection_records(self):
        p=parent();sources=p['output_snapshot']['retrieve']['evidence']['sources']
        sources.append({**sources[0],'source_id':'duplicate','source_url':'https://mirror.example/article','resolved_url':'https://mirror.example/article'})
        for i,delta in enumerate([{'article_text':None},{'retrieval_status':'access_denied','retrieval_error':'http_403'},{'retrieval_status':'access_denied','retrieval_error':'http_429'},{'source_kind':'youtube'},{'article_text_hash':'wrong'},{'resolved_url':'https://www.google.com/sorry/index'}]):
            sources.append({**sources[0],**delta,'source_id':f'bad{i}'})
        m=plan(p);self.assertEqual(len(m['units']),2);self.assertEqual(len(m['selection_records']),9)
        self.assertEqual(sum(s['selection_status']=='unavailable' for s in m['selection_records']),6)
        self.assertTrue(any(len(u['source_aliases'])==2 for u in m['units']))
        for s in sources:s['retrieval_status']='access_denied'
        self.assertEqual(plan(p)['units'],[])

    def test_canonical_dedup_limits_and_stable_order(self):
        p=parent();sources=p['output_snapshot']['retrieve']['evidence']['sources']
        sources[0]['canonical_url']='https://news.example/story';sources[1]['canonical_url']='https://news.example/story'
        self.assertEqual(len(plan(p)['units']),1)
        sources[1].pop('canonical_url');sources[0].pop('canonical_url')
        for i in range(2,5):
            sources.append({**sources[0],'source_id':f's{i}','resolved_url':f'https://news.example/{i}','article_text':f'Body {i}', 'article_text_hash':text_hash(f'Body {i}')})
        a=plan(p);sources.reverse();b=plan(p)
        self.assertEqual(a['k_ext'],b['k_ext']);self.assertEqual(len(a['units']),2)
        self.assertEqual(sum(r['selection_reason']=='Article count limit' for r in a['selection_records']),3)
