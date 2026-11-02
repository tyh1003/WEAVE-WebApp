import copy
import unittest
from test_source_grounded import parent
from source_grounded import plan as grounded_plan, effective_retrieve
from source_ablation import plan, validated_manifest
from evidence_ablation import capabilities


def grounded():
    p=parent()
    sources=p['output_snapshot']['retrieve']['evidence']['sources']
    sources.append({**sources[0],'source_id':'alias','resolved_url':'https://z.example/alias'})
    m=grounded_plan(p)
    v=dict(version_id='grounded',version_number=2,status='succeeded',experiment_type='source_grounded_baseline',source_grounded_manifest=m)
    data=effective_retrieve(p,v)
    v['output_snapshot']=dict(retrieve=data,source_grounded_manifest=copy.deepcopy(m),student_trace={'fields':{k:data[k] for k in ('Rc','Rv','K_int','K_ext')}})
    return v


class SourceAblationTests(unittest.TestCase):
    def test_remove_each_all_aliases_and_deterministic_preview(self):
        p=grounded(); original=copy.deepcopy(p); units=p['source_grounded_manifest']['units']
        for unit in units:
            result=plan(p,[unit['evidence_unit_id']])
            self.assertEqual(len(result['retained_evidence_units']),1)
            self.assertNotIn(unit['evidence_text'],result['ablation_manifest']['k_ext'])
            self.assertEqual(set(result['excluded_source_ids']),set(unit['article_source_ids']))
        ids=[u['evidence_unit_id'] for u in units]
        self.assertEqual(plan(p,ids),plan(p,list(reversed(ids))+ids))
        self.assertEqual(plan(p,ids)['ablation_manifest']['k_ext'],'')
        self.assertEqual(p,original)
        self.assertTrue(capabilities(p)['source_level']['available'])
        self.assertFalse(capabilities(parent())['source_level']['available'])

    def test_invalid_ids_and_corrupted_manifest_rejected(self):
        p=grounded()
        for ids in ([],['unknown'],None,{'id':1}):
            with self.assertRaises(ValueError):plan(p,ids)
        for target in ('k_ext','manifest_hash'):
            bad=copy.deepcopy(p);bad['source_grounded_manifest'][target]='tampered'
            with self.assertRaises(ValueError):validated_manifest(bad)
        p['output_snapshot']['retrieve']['evidence']['sources'][0]['article_text']='changed'
        with self.assertRaises(ValueError):validated_manifest(p)
