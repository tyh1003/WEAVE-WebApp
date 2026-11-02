"""Research lifecycle and real orchestration wiring; model subprocesses are mocked."""
import io
import importlib.util
import json
import os
import runpy
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_deployment
from research_store import Store, ResearchError
from research_runner import drain, run_version, worker_lock, write, read, sha, version_workspace


class ResearchTests(unittest.TestCase):
    setUp = test_deployment.DeploymentTests.setUp
    load_app = test_deployment.DeploymentTests.load_app

    def test_source_aware_controlled_retry(self):
        import copy, shutil, yaml
        from source_aware_retry import BASE
        self.test_source_aware_student_rerun_and_parent_immutable()
        original=self.store.versions(self.eid)[-1]
        failed=copy.deepcopy(original);failed.update(version_id='mock-failed',version_number=3,status='failed',error='Invalid Student output',request_key='mock-failed')
        target=self.store.root/'jobs'/'mock-failed'
        shutil.copytree(Path(original['artifact_paths']['workspace']),target)
        failed['artifact_paths']['workspace']=str(target)
        trace=read(target/'output/student_trace.json')
        trace.update(config=yaml.safe_load((BASE/'config/student_bot_config.yaml').read_text(encoding='utf-8')),generation={'max_new_tokens':256,'do_sample':False},raw_response='1, 1 YNYN')
        write(target/'output/student_trace.json',trace)
        (target/'execution.log').write_text('mock failed execution',encoding='utf-8')
        with self.store.transaction() as db:
            db.execute('INSERT INTO versions VALUES (?,?,?,?,?)',(failed['version_id'],self.eid,3,'mock-failed',json.dumps(failed)))
        hashes={str(p):sha(p) for p in target.rglob('*') if p.is_file()}
        request={'experiment_type':'source_aware_baseline','retry_of_version_id':'mock-failed','confirm':True}
        self.assertEqual(self.post('/versions',{**request,'confirm':False}).status_code,400)
        response=self.post('/versions',request);self.assertEqual(response.status_code,201)
        retry=response.json
        self.assertEqual(self.post('/versions',request).json['version_id'],retry['version_id'])
        calls=[]
        def execute(script,args,work,v):
            calls.append(script);self.assertEqual(script,'run_student.py')
            self.fake_execute(script,args,work,v)
            fresh={**trace,'raw_response':'{"pred_label":1,"reason":"new mock output"}'}
            write(work/'output/student_trace.json',fresh)
        drain(self.store,execute)
        result=self.store.version(self.eid,retry['version_id'])
        self.assertEqual(result['status'],'succeeded');self.assertEqual(calls,['run_student.py'])
        self.assertEqual(result['output_snapshot']['student_trace']['fields'],trace['fields'])
        self.assertEqual(result['source_aware_manifest'],failed['source_aware_manifest'])
        self.assertEqual(hashes,{str(p):sha(p) for p in target.rglob('*') if p.is_file()})
        self.assertEqual(self.store.version(self.eid,'mock-failed')['status'],'failed')

    def test_source_aware_student_rerun_and_parent_immutable(self):
        from test_source_aware import fixture as source_fixture
        from source_summarization import state
        from source_summarization_poc import mock_provider
        self.setup_research();self.lock()
        first=self.post('/versions',{'experiment_type':'baseline'}).json
        def baseline_execute(script,args,work,v):
            self.fake_execute(script,args,work,v)
            if script=='Retrieve.py':
                data=read(work/'output/retrieve.jsonl')
                fixture=source_fixture()['output_snapshot']['retrieve']
                data.update({k:fixture[k] for k in ('K_ext','sources','grounding_supports')})
                data['evidence']=fixture['evidence']
                for source in data['evidence']['sources']:source['content_quality']='partial_article'
                third={**data['evidence']['sources'][0],'source_id':'third','resolved_url':'https://news.example/third','article_text':'Third saved body for independent summarization.'}
                from source_summarization_poc import digest
                third['article_text_hash']=digest(third['article_text'])
                data['evidence']['sources'].append(third)
                (work/'output/retrieve.jsonl').write_text(json.dumps(data),encoding='utf-8')
        drain(self.store,baseline_execute)
        v1=self.store.version(self.eid,first['version_id']);original=json.dumps(v1,sort_keys=True)
        path=Path(v1['artifact_paths']['workspace']);hashes={str(p):sha(p) for p in path.rglob('*') if p.is_file()}
        preview_url=self.base+'/versions/'+v1['version_id']+'/source-aware-preview'
        self.assertEqual(self.client.get(preview_url).status_code,401)
        preview=self.client.get(preview_url,headers=self.headers).json
        self.assertFalse(preview['available']);self.assertEqual(len(preview['manifest']['units']),0)
        provider=Mock(side_effect=mock_provider)
        self.module.app.config['SOURCE_SUMMARIZATION_PROVIDER']=provider
        route='/versions/'+v1['version_id']
        request={'confirm_cost':True,'cache_key':preview['cache_key']}
        self.assertEqual(self.post(route+'/source-summaries',{**request,'confirm_cost':False}).status_code,400)
        provider.assert_not_called()
        preview=self.post(route+'/source-summaries',request).json
        self.assertEqual(preview['summary_status'],'succeeded');self.assertFalse(preview['available'])
        self.assertEqual(len(preview['manifest']['news_cards']),3)
        self.assertTrue(all(c['quote_validation']['status']=='exact_match' for c in preview['manifest']['news_cards']))
        self.post(route+'/source-summaries',request);provider.assert_called_once()
        for sid in ('S1','S2'):
            preview=self.post(route+'/source-summary-review',{'source_id':sid,'decision':'approved',
                'attempt_id':preview['attempt_id'],'review_revision':preview['review_revision']}).json
        self.assertTrue(preview['available']);self.assertEqual(len(preview['manifest']['units']),2)
        self.assertEqual(self.client.get(preview_url,headers=self.headers).json['manifest'],preview['manifest'])
        payload={'experiment_type':'source_aware_baseline','parent_version_id':v1['version_id'],'confirm':True,'manifest_hash':preview['manifest']['manifest_hash']}
        self.assertEqual(self.post('/versions',{**payload,'confirm':False}).status_code,400)
        self.assertEqual(self.post('/versions',{**payload,'manifest_hash':'stale'}).status_code,409)
        v2=self.post('/versions',payload).json
        self.assertEqual(self.post('/versions',payload).json['version_id'],v2['version_id'])
        def student_execute(script,args,work,v):
            self.assertEqual(script,'run_student.py')
            self.fake_execute(script,args,work,v)
            trace=read(work/'output/student_trace.json')
            trace.update(formatted_prompt='mock prompt\n- '+trace['fields']['K_ext'],effective_input_ids=[[1,2,3]],max_length=5000)
            write(work/'output/student_trace.json',trace)
        drain(self.store,student_execute)
        child=self.store.version(self.eid,v2['version_id'])
        self.assertEqual(child['status'],'succeeded');self.assertEqual(child['execution_conditions']['rerun_stages'],['Student'])
        fields=child['output_snapshot']['student_trace']['fields']
        self.assertEqual(fields['K_ext'],preview['manifest']['k_ext'])
        for k in ('Rc','Rv','K_int'):self.assertEqual(fields[k],v1['output_snapshot']['student_trace']['fields'][k])
        self.assertEqual(child['output_snapshot']['source_aware_manifest'],state(v1,self.store.root)['manifest'])
        from dataclasses import replace
        from version_assessment import CONFIG
        evaluator=Mock(side_effect=lambda p,**kw: dict(claim_id=p['claims'][0]['claim_id'],relevance='insufficient',stance='not_established',target_scope='single',verbatim_excerpt='',excerpt_start=None,excerpt_end=None,explanation='Not established'))
        self.module.app.config['EVIDENCE_ASSESSMENT_PROVIDER']=evaluator
        self.module.app.config['EVIDENCE_ASSESSMENT_CONFIG']=replace(CONFIG,model_name='mock')
        endpoint='/versions/'+child['version_id']+'/grounded-explanation'
        self.assertEqual(self.client.get(self.base+endpoint).status_code,401)
        self.assertEqual(self.post(endpoint,{}).status_code,400)
        self.assertEqual(self.client.get(self.base+endpoint,headers=self.headers).status_code,200)
        evaluator.assert_not_called()
        evaluated=self.post(endpoint,{'confirm_cost':True})
        self.assertEqual(evaluated.status_code,200)
        self.assertTrue(evaluated.json['assessment'])
        calls=evaluator.call_count
        self.assertEqual(self.client.get(self.base+endpoint,headers=self.headers).json['status'],'cached')
        self.assertEqual(evaluator.call_count,calls)

        # Re-reviewing the same approved content must not create another paid Student version.
        for decision in ('excluded','approved'):
            preview=self.post(route+'/source-summary-review',{'source_id':'S2','decision':decision,
                'attempt_id':preview['attempt_id'],'review_revision':preview['review_revision']}).json
        duplicate=self.post('/versions',{**payload,'manifest_hash':preview['manifest']['manifest_hash']})
        self.assertEqual(duplicate.status_code,200)
        self.assertEqual(duplicate.json['version_id'],v2['version_id'])
        self.assertEqual(json.dumps(self.store.version(self.eid,v1['version_id']),sort_keys=True),original)
        self.assertEqual({str(p):sha(p) for p in path.rglob('*') if p.is_file()},hashes)

    def test_source_summary_routes_require_auth_and_successful_disclosure(self):
        self.setup_research();self.lock()
        first=self.post('/versions',{'experiment_type':'baseline'}).json
        provider=Mock();self.module.app.config['SOURCE_SUMMARIZATION_PROVIDER']=provider
        for suffix in ('source-summaries','source-summary-review'):
            url=self.base+'/versions/'+first['version_id']+'/'+suffix
            self.assertEqual(self.client.post(url,json={}).status_code,401)
            self.assertEqual(self.client.post(url,json={},headers=self.headers).status_code,409)
        provider.assert_not_called()

    def test_source_grounded_baseline_real_student_entrypoint_and_parent_immutable(self):
        from test_source_grounded import parent as source_fixture
        from source_grounded import plan
        self.setup_research();self.lock()
        first=self.post('/versions',{'experiment_type':'baseline'}).json
        def baseline_execute(script,args,work,v):
            self.fake_execute(script,args,work,v)
            if script=='Retrieve.py':
                data=read(work/'output/retrieve.jsonl')
                data['evidence']={'schema_version':1,'video_id':data['vid'],'analysis_id':data['analysis_id'],'run_id':1,
                    'sources':source_fixture()['output_snapshot']['retrieve']['evidence']['sources']}
                (work/'output/retrieve.jsonl').write_text(json.dumps(data),encoding='utf-8')
        drain(self.store,baseline_execute)
        v1=self.store.version(self.eid,first['version_id']);original=json.dumps(v1,sort_keys=True)
        path=Path(v1['artifact_paths']['workspace']);hashes={str(p):sha(p) for p in path.rglob('*') if p.is_file()}
        preview_url=self.base+'/versions/'+v1['version_id']+'/source-grounded-preview'
        self.assertEqual(self.client.get(preview_url).status_code,401)
        preview=self.client.get(preview_url,headers=self.headers).json
        self.assertTrue(preview['available']);self.assertEqual(len(preview['manifest']['units']),2)
        payload={'experiment_type':'source_grounded_baseline','parent_version_id':v1['version_id'],'confirm':True,'manifest_hash':preview['manifest']['manifest_hash']}
        self.assertEqual(self.post('/versions',{**payload,'confirm':False}).status_code,400)
        self.assertEqual(self.post('/versions',{**payload,'manifest_hash':'stale'}).status_code,409)
        v2=self.post('/versions',payload).json
        self.assertEqual(self.post('/versions',payload).json['version_id'],v2['version_id'])
        def student_execute(script,args,work,v):
            self.assertEqual(script,'run_student.py')
            self.fake_execute(script,args,work,v)
            trace=read(work/'output/student_trace.json')
            trace.update(formatted_prompt='mock prompt\n- '+trace['fields']['K_ext'],effective_input_ids=[[1,2,3]],max_length=5000)
            write(work/'output/student_trace.json',trace)
        drain(self.store,student_execute)
        child=self.store.version(self.eid,v2['version_id'])
        self.assertEqual(child['status'],'succeeded');self.assertEqual(child['execution_conditions']['rerun_stages'],['Student'])
        fields=child['output_snapshot']['student_trace']['fields']
        self.assertEqual(fields['K_ext'],preview['manifest']['k_ext'])
        for k in ('Rc','Rv','K_int'):self.assertEqual(fields[k],v1['output_snapshot']['student_trace']['fields'][k])
        self.assertEqual(child['output_snapshot']['source_grounded_manifest'],plan(v1))
        self.assertEqual(json.dumps(self.store.version(self.eid,v1['version_id']),sort_keys=True),original)
        self.assertEqual({str(p):sha(p) for p in path.rglob('*') if p.is_file()},hashes)
        # Mode A uses the successful grounded child, not original mixed V1.
        units=child['source_grounded_manifest']['units']
        child_hashes={str(p):sha(p) for p in Path(child['artifact_paths']['workspace']).rglob('*') if p.is_file()}
        def ablation_execute(script,args,work,v):
            student_execute(script,args,work,v)
            trace=read(work/'output/student_trace.json')
            if not trace['fields']['K_ext']:
                trace['formatted_prompt']='mock prompt 無'
                write(work/'output/student_trace.json',trace)
        for selected in ([units[0]['evidence_unit_id']],[units[1]['evidence_unit_id']],[u['evidence_unit_id'] for u in units]):
            suffix='/versions/'+child['version_id']+'/source-ablation-preview'
            preview_a=self.post(suffix,{'excluded_unit_ids':selected}).json
            request_a=dict(experiment_type='evidence_ablation',parent_version_id=child['version_id'],ablation_mode='source_level',excluded_unit_ids=selected,confirm=True,manifest_hash=preview_a['ablation_manifest']['manifest_hash'])
            self.assertEqual(self.post('/versions',{**request_a,'manifest_hash':'stale'}).status_code,409)
            with ThreadPoolExecutor(max_workers=3) as pool:
                concurrent=list(pool.map(lambda _:self.store.create_version(self.eid,request_a),range(3)))
            self.assertEqual(len({v['version_id'] for v,created in concurrent}),1)
            created=concurrent[0][0]
            self.assertEqual(self.post('/versions',request_a).json['version_id'],created['version_id'])
            # First attempt fails durably; explicit retry creates a new immutable record.
            if len(selected)==2:
                drain(self.store,lambda *args: (_ for _ in ()).throw(RuntimeError('mock API failure')))
                failed_a=self.store.version(self.eid,created['version_id'])
                self.assertEqual(failed_a['status'],'failed')
                self.assertFalse(failed_a['contamination_audit']['student_input_verified'])
                self.assertEqual(self.post('/versions',request_a).json['version_id'],created['version_id'])
                retry={**request_a,'retry_of_version_id':created['version_id']}
                created=self.post('/versions',retry).json
                self.assertNotEqual(created['version_id'],failed_a['version_id'])
                self.assertEqual(self.post('/versions',retry).json['version_id'],created['version_id'])
                self.assertEqual(self.store.version(self.eid,failed_a['version_id']),failed_a)
            drain(self.store,ablation_execute)
            actual=self.store.version(self.eid,created['version_id'])
            self.assertEqual(actual['status'],'succeeded',actual.get('error'))
            self.assertEqual(actual['output_snapshot']['student_trace']['fields']['K_ext'],preview_a['ablation_manifest']['k_ext'])
            for key in ('Rc','Rv','K_int'):
                self.assertEqual(actual['output_snapshot']['student_trace']['fields'][key],fields[key])
            self.assertEqual(actual['execution_conditions']['rerun_stages'],['Student'])
            self.assertTrue(actual['contamination_audit']['removed_unit_ids_absent'])
            self.assertTrue(actual['contamination_audit']['student_input_verified'])
            self.assertEqual(self.post('/versions',request_a).json['version_id'],created['version_id'])
        self.assertEqual(self.post(suffix,{'excluded_unit_ids':['invalid']}).status_code,400)
        self.assertEqual(self.store.version(self.eid,child['version_id']),child)
        self.assertEqual(child_hashes,{str(p):sha(p) for p in Path(child['artifact_paths']['workspace']).rglob('*') if p.is_file()})
        self.assertEqual({str(p):sha(p) for p in path.rglob('*') if p.is_file()},hashes)

        # A frozen manifest must be audited against the actual Student input trace.
        next_payload={**payload,'parent_version_id':child['version_id'],'manifest_hash':plan(child)['manifest_hash']}
        v3=self.post('/versions',next_payload).json
        def wrong_trace(script,args,work,v):
            student_execute(script,args,work,v)
            trace=read(work/'output/student_trace.json');trace['fields']['K_ext']='old untraceable synthesis'
            write(work/'output/student_trace.json',trace)
        drain(self.store,wrong_trace)
        failed=self.store.version(self.eid,v3['version_id'])
        self.assertEqual(failed['status'],'failed');self.assertIsNone(failed['output_snapshot'])
        self.assertTrue((Path(failed['artifact_paths']['workspace'])/'output/student_trace.json').exists())
        self.assertEqual(self.store.version(self.eid,child['version_id']),child)

    def test_source_grounded_no_body_rejected(self):
        self.setup_research();v1=self.baseline()
        response=self.post('/versions',{'experiment_type':'source_grounded_baseline','parent_version_id':v1['version_id'],'confirm':True,'manifest_hash':'unused'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(len(self.store.versions(self.eid)),1)

    def test_invalid_student_response_is_durable_failed_not_success(self):
        self.setup_research();self.lock()
        version=self.post('/versions',{'experiment_type':'baseline'}).json
        def execute(script,args,work,v):
            if script != 'run_student.py':
                return self.fake_execute(script,args,work,v)
            bot=Mock()
            bot.predict.return_value=(-1,'1, 1\nMalformed model prose\nYNYN')
            bot.last_trace={'raw_response':bot.predict.return_value[1]}
            with patch.dict(os.environ,{'WEAVE_WORK_DIR':str(work)}), patch.dict(sys.modules,{'student_bot':SimpleNamespace(StudentBot=lambda **kwargs:bot)}):
                runpy.run_path(str(test_deployment.BACKEND/'run_student.py'))
        drain(self.store,execute)
        failed=self.store.version(self.eid,version['version_id'])
        self.assertEqual(failed['status'],'failed');self.assertEqual(failed['failed_stage'],'student')
        self.assertIsNone(failed.get('output_snapshot'))
        work=Path(failed['artifact_paths']['workspace'])
        self.assertEqual(read(work/'output/student_output_error.json')['error_code'],'invalid_student_output')
        self.assertIn('Invalid Student output',read(work/'failure.json')['traceback'])
        self.assertFalse((work/'output/final_result.json').exists())

    def test_stage_command_logs_exit_code_and_safe_environment(self):
        import research_runner as runner
        import subprocess
        work=self.root/'job';work.mkdir()
        for code in (0,1):
            with patch.object(runner.subprocess,'run',side_effect=subprocess.CalledProcessError(code,['mock']) if code else None) as run:
                if code:
                    with self.assertRaises(subprocess.CalledProcessError):
                        runner.command('run_student.py',[],work,{'version_id':'v','version_number':1})
                else:runner.command('run_student.py',[],work,{'version_id':'v','version_number':1})
                self.assertEqual(run.call_args.kwargs['cwd'],work)
        records=[json.loads(line) for line in (work/'execution.log').read_text().splitlines()]
        self.assertEqual([r['exit_code'] for r in records if 'exit_code' in r],[0,1])
        self.assertEqual(records[0]['argv'][0],sys.executable)
        self.assertEqual(set(records[0]['environment']),{'WEAVE_WORK_DIR','WEAVE_ANALYSIS_ID','WEAVE_RUN_ID','HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','PYTHONIOENCODING','PYTHONUTF8'})

    def test_assessment_api_requires_disclosure_confirmation_and_preserves_version(self):
        self.setup_research(); self.lock()
        v=self.post('/versions',{'experiment_type':'baseline'}).json
        suffix='/versions/'+v['version_id']+'/evidence-assessment'
        self.assertEqual(self.client.get(self.base+suffix).status_code,401)
        self.assertEqual(self.client.get(self.base+suffix,headers=self.headers).status_code,409)
        drain(self.store,self.fake_execute)
        before=self.store.version(self.eid,v['version_id'])
        preview=self.client.get(self.base+suffix,headers=self.headers)
        self.assertEqual(preview.status_code,200);self.assertEqual(preview.json['status'],'unavailable')
        self.assertEqual(self.post(suffix,{}).status_code,400)
        self.assertEqual(self.post(suffix,{'confirm_cost':True}).json['status'],'unavailable')
        self.assertEqual(before,self.store.version(self.eid,v['version_id']))
        self.assertFalse((self.store.root/'evidence_assessments').exists())
        from evidence_assessment import AssessmentConfig
        provider=Mock()
        self.module.app.config.update(EVIDENCE_ASSESSMENT_CONFIG=AssessmentConfig(enabled=True,model_name='mock'),EVIDENCE_ASSESSMENT_PROVIDER=provider)
        self.client.get(self.base+suffix,headers=self.headers);provider.assert_not_called()
        assessed=self.post(suffix,{'confirm_cost':True})
        self.assertEqual(assessed.status_code,200)
        self.assertIn('assessment',assessed.json)
        self.assertEqual(self.post(suffix,{'confirm_cost':True}).json['status'],'cached')
        provider.assert_not_called()  # Baseline fixture has no verified article body.
        self.assertEqual(before,self.store.version(self.eid,v['version_id']))

    def test_external_ablation_student_only_input_diff_and_immutable_versions(self):
        self.setup_research(); v1 = self.baseline()
        fields = v1['output_snapshot']['student_trace']['fields']
        original_dir = Path(v1['artifact_paths']['workspace'])
        hashes = {str(p):sha(p) for p in original_dir.rglob('*') if p.is_file()}
        payload = {'experiment_type':'evidence_ablation','parent_version_id':v1['version_id'], 'ablation_mode':'external_knowledge'}
        response = self.post('/versions', payload)
        self.assertEqual(response.status_code, 201)
        vid = response.json['version_id']
        self.assertEqual(self.post('/versions', payload).json['version_id'], vid)
        drain(self.store, self.fake_execute)
        v2 = self.store.version(self.eid, vid)
        self.assertEqual(v2['status'], 'succeeded')
        self.assertEqual([script for version,script in self.calls if version == vid], ['run_student.py'])
        trace = v2['output_snapshot']['student_trace']
        self.assertEqual(trace['fields'], {**fields, 'K_ext':''})
        self.assertNotIn(fields['K_ext'], trace['formatted_prompt'])
        self.assertEqual(v2['effective_input_diff'], {'K_ext':{'before':fields['K_ext'], 'after':''}})
        self.assertEqual(v2['output_snapshot']['retrieve']['uri'], v1['output_snapshot']['retrieve']['uri'])
        self.assertEqual(v2['output_snapshot']['retrieve_trace'], [])
        self.assertEqual(v2['excluded_source_ids'], [])
        self.assertEqual(v2['rerun_stage_records'][0]['stage'], 'Student')
        self.assertNotEqual(v1['output_snapshot']['student']['pred_label'], v2['output_snapshot']['student']['pred_label'])
        self.assertEqual(self.post('/versions', {**payload,'parent_version_id':vid}).status_code,400)
        child_hashes = {str(p):sha(p) for p in Path(v2['artifact_paths']['workspace']).rglob('*') if p.is_file()}
        # Feature 8 can still branch from an ablation version, regenerating its knowledge.
        v3 = self.post('/versions', {'experiment_type':'input_correction','parent_version_id':vid,'field':'Rc','value':'Correction after ablation'}).json
        drain(self.store, self.fake_execute)
        self.assertEqual(self.store.version(self.eid,v3['version_id'])['status'],'succeeded')
        self.assertEqual(self.store.version(self.eid,v1['version_id']),v1)
        self.assertEqual(self.store.version(self.eid,vid),v2)
        self.assertTrue(all(sha(p)==digest for p,digest in hashes.items()))
        self.assertTrue(all(sha(p)==digest for p,digest in child_hashes.items()))
        with self.assertRaises(ResearchError): self.store.update(self.eid,vid,status='pending')

    def test_source_ablation_unavailable_and_unknown_student_channels_fail_closed(self):
        from evidence_ablation import capabilities, plan, effective_retrieve
        self.setup_research(); parent = self.baseline()
        self.assertFalse(capabilities(parent)['source_level']['available'])
        self.assertTrue(capabilities(parent)['external_knowledge']['available'])
        parent['output_snapshot']['retrieve']['evidence'] = {'analysis_id':parent['version_id'], 'sources':[{'source_id':'s0','source_url':'https://example.test/article','source_text':'Actual saved fixture text'}]}
        unchanged = json.dumps(parent,sort_keys=True)
        effective = effective_retrieve(parent,{'version_id':'child','version_number':2})
        self.assertEqual(effective['evidence']['analysis_id'],'child')
        self.assertEqual(effective['evidence']['sources'][0]['source_text'],'Actual saved fixture text')
        self.assertEqual(effective['evidence']['sources'][0]['student_input_status'],'not_passed_as_article; K_ext_channel_excluded')
        self.assertEqual(json.dumps(parent,sort_keys=True),unchanged)
        for mode in ('source_level', 'invented'):
            self.assertEqual(self.post('/versions', {'experiment_type':'evidence_ablation','parent_version_id':parent['version_id'],'ablation_mode':mode,'excluded_source_ids':['s0']}).status_code,400)
        # Unvalidated metadata cannot enable source-level exclusion.
        parent['output_snapshot']['retrieve']['source_lineage'] = {'s0':['K_ext']}
        self.assertFalse(capabilities(parent)['source_level']['available'])
        with self.assertRaises(ValueError): plan(parent,'external_knowledge',['s0'])
        parent['output_snapshot']['student_trace']['fields']['external_article'] = 'unknown channel'
        self.assertFalse(capabilities(parent)['external_knowledge']['available'])
        with self.assertRaises(ValueError): plan(parent,'external_knowledge',[])
        for empty in ('', '  ', None, []):
            fresh = self.store.version(self.eid,parent['version_id'])
            fresh['output_snapshot']['retrieve']['K_ext'] = empty
            fresh['output_snapshot']['student_trace']['fields']['K_ext'] = empty
            with self.assertRaises(ValueError): plan(fresh,'external_knowledge',[])

    def test_ablation_failure_keeps_diff_and_cross_experiment_parent_rejected(self):
        self.setup_research(); parent = self.baseline()
        payload = {'experiment_type':'evidence_ablation','parent_version_id':parent['version_id'],'ablation_mode':'external_knowledge'}
        child = self.post('/versions',payload).json
        def fail(script,*args):
            self.assertEqual(script,'run_student.py')
            raise TimeoutError('mock Student failure')
        drain(self.store,fail)
        failed = self.store.version(self.eid,child['version_id'])
        self.assertEqual(failed['status'],'failed')
        self.assertIsNone(failed['output_snapshot'])
        self.assertEqual(failed['input_snapshot']['student_fields']['K_ext'],'')
        self.assertEqual(failed['rerun_stage_records'][0]['status'],'failed')
        other = self.client.post('/experiments',data={'video':(io.BytesIO(b'other'),'other.mp4')}).json
        eid = other['experiment']['experiment_id']; headers={'Authorization':'Bearer '+other['access_token']}
        self.client.post(f'/experiments/{eid}/human-judgment',json={'vote':'true'},headers=headers)
        self.assertEqual(self.client.post(f'/experiments/{eid}/versions',json=payload,headers=headers).status_code,409)
        self.assertNotIn('correct_answer_label',self.client.get(f'/experiments/{eid}',headers=headers).json)

    def test_ablation_rejects_success_when_actual_student_trace_keeps_external_input(self):
        self.setup_research(); parent = self.baseline()
        child = self.post('/versions',{'experiment_type':'evidence_ablation','parent_version_id':parent['version_id'],'ablation_mode':'external_knowledge'}).json
        def wrong_trace(script,args,work,version):
            self.fake_execute(script,args,work,version)
            trace = read(work / 'output/student_trace.json')
            trace['fields']['K_ext'] = 'Unexpected retained knowledge'
            write(work / 'output/student_trace.json',trace)
        drain(self.store,wrong_trace)
        value = self.store.version(self.eid,child['version_id'])
        self.assertEqual(value['status'],'failed')
        self.assertIsNone(value['output_snapshot'])

    def test_first_real_failure_windows_path_and_stage_projection(self):
        # Reproduce the exact deployment path lengths without touching its records.
        from pathlib import PureWindowsPath
        root = PureWindowsPath(r'C:\Users\user\Desktop\Refine-Retrieve-Reason-FakeNews-WebApp-main\Refine-Retrieve-Reason-FakeNews-WebApp-main\backend\research_data')
        eid, vid, asset = '81d15ae50ff14cc89c20e3da4712b28f', '4566751817084701ba8ae48eeecbf2a2', 'a647169e8ec54365bb22b2ee162cc157'
        old = root / eid / vid / 'preprocess_output/frames' / asset
        new = PureWindowsPath(str(version_workspace(str(root), vid))) / 'preprocess_output/frames' / asset
        self.assertEqual(len(str(old)), 255)
        self.assertLess(len(str(new)), 248)
        self.assertLess(len(str(new / 'frame_0015.png')), 260)
        self.setup_research(); self.lock()
        version, _ = self.store.create_version(self.eid, {})
        def failure(script, *args):
            if script == 'preprocess/1.Extract_Frames.py':
                raise FileNotFoundError(206, 'Filename too long')
        drain(self.store, failure)
        failed = self.store.version(self.eid, version['version_id'])
        self.assertEqual(failed['failed_stage'], 'preprocess')
        self.assertEqual(failed['failed_step'], 'preprocess/1.Extract_Frames.py')
        self.assertIn('FileNotFoundError', read(Path(failed['artifact_paths']['workspace']) / 'failure.json')['traceback'])
        historical = dict(failed)
        historical.pop('failed_stage'); historical.pop('failed_step')
        before = json.dumps(historical, sort_keys=True)
        public = self.store.public_version(historical, False)
        self.assertEqual(public['failed_stage'], 'preprocess')
        self.assertNotIn('output_snapshot', public)
        self.assertNotIn('traceback', public)
        self.assertEqual(json.dumps(historical, sort_keys=True), before)

    def setup_research(self):
        self.module = self.load_app()
        self.dispatch = Mock()
        self.module.app.config.update(RESEARCH_ROOT=str(self.root / 'research'), RESEARCH_DISPATCH=self.dispatch)
        self.module.answer_index = {'fake-sample': 1}
        self.client = self.module.app.test_client()
        self.store = Store(self.root / 'research')
        created = self.client.post('/experiments', data={'video': (io.BytesIO(b'fixture'), 'fake-sample.mp4')})
        self.assertEqual(created.status_code, 201)
        self.exp = created.json['experiment']
        self.eid = self.exp['experiment_id']
        self.base = '/experiments/' + self.eid
        self.headers = {'Authorization': 'Bearer ' + created.json['access_token']}
        self.calls = []

    def post(self, suffix, data):
        return self.client.post(self.base + suffix, json=data, headers=self.headers)

    def lock(self):
        return self.post('/human-judgment', {'vote': 'true', 'reason': ''})

    def baseline(self):
        self.lock()
        version = self.post('/versions', {'experiment_type': 'baseline'}).json
        drain(self.store, self.fake_execute)
        return self.store.version(self.eid, version['version_id'])

    def fake_execute(self, script, args, work, version):
        """Run the actual run_student entrypoint, mock only the heavy StudentBot."""
        self.calls.append((version['version_id'], script))
        asset = self.store.experiment(self.eid)['video_asset_id']
        if script == 'preprocess/4.Data_Merge.py':
            (work / 'preprocess_output').mkdir()
            write(work / 'preprocess_output/all.json', {'vid': asset, 'transcript': 'Original spoken words', 'description': 'Original visual observation'})
        elif script == 'Retrieve.py':
            merged = read(work / 'preprocess_output/all.json')
            override = read(work / 'input_overrides.json') if (work / 'input_overrides.json').exists() else {}
            retrieved = {'vid': asset, 'analysis_id': version['version_id'], 'run_id': version['version_number'],
                         'Rc': override.get('Rc', 'Extracted ' + merged['transcript']), 'Rv': override.get('Rv', merged['description']),
                         'K_int': 'new internal ' + version['version_id'], 'K_ext': 'new external ' + version['version_id'],
                         'uri': ['https://example.test/' + version['version_id']]}
            (work / 'output/retrieve.jsonl').write_text(json.dumps(retrieved), encoding='utf-8')
            (work / 'output/retrieve_sent.jsonl').write_text(json.dumps({'prompt': 'mock retrieval request', 'override': override}), encoding='utf-8')
        elif script == 'run_student.py':
            class Bot:
                def __init__(self, **kwargs):
                    pass
                def predict(self, **fields):
                    self.last_trace = {'fields': fields, 'raw_response': 'mock response', 'formatted_prompt': 'mock template ' + json.dumps(fields)}
                    return (0 if version['version_number'] == 1 else 1), 'Fresh reason: ' + fields['Rc'] + ' / ' + fields['Rv']
            with patch.dict(sys.modules, {'student_bot': SimpleNamespace(StudentBot=Bot)}), patch.dict(os.environ, {'WEAVE_WORK_DIR': str(work)}):
                runpy.run_path(str(test_deployment.BACKEND / 'run_student.py'))

    def test_upload_does_not_run_neutral_metadata_token_and_legacy_guards(self):
        self.setup_research()
        self.dispatch.assert_not_called()
        self.assertNotIn('fake-sample', json.dumps(self.exp))
        self.assertNotIn('correct_answer', self.exp)
        self.assertNotIn('ground_truth_label', self.exp)
        self.assertEqual(self.exp['dataset_match_status'], 'filename_only_content_unverified')
        for route in ('', '/versions', '/video', '/versions/unknown/result'):
            self.assertEqual(self.client.get(self.base + route).status_code, 401)
            self.assertEqual(self.client.get(self.base + route, headers={'Authorization': 'Bearer wrong'}).status_code, 404)
        for route in ('/status', '/result', '/student_result', '/static/output/final_result.json'):
            self.assertIn(self.client.get(route).status_code, (404, 410))
        self.assertEqual(self.client.post('/upload').status_code, 410)
        self.assertEqual(self.post('/versions', {}).status_code, 409)
        response = self.client.get(self.base + '/video', headers=self.headers)
        self.assertEqual(response.data, b'fixture')
        response.close()

    def test_initial_lock_atomic_idempotent_persistent_and_separate_from_votes(self):
        self.setup_research()
        def lock(vote):
            try:
                return self.store.lock_human(self.eid, vote, '')['human_judgment']
            except ResearchError:
                return 'rejected'
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lock, ['true', 'false'] * 8))
        saved = self.store.experiment(self.eid)
        self.assertTrue(all(x in (saved['human_judgment'], 'rejected') for x in results))
        self.assertEqual(Store(self.store.root).experiment(self.eid), saved)
        self.assertEqual(lock(saved['human_judgment']), saved['human_judgment'])
        self.assertEqual(self.post('/human-judgment', {'vote': 'unsure'}).status_code, 400)
        self.assertEqual(self.client.get('/vote/statistics?video_id=' + self.exp['video_asset_id']).json['total'], 0)

    def test_baseline_idempotent_and_reveal_only_after_success(self):
        self.setup_research(); self.lock()
        def create(_):
            return self.store.create_version(self.eid, {})[0]['version_id']
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(create, range(8)))
        self.assertEqual(len(set(ids)), 1)
        for suffix in ('', '/versions', '/versions/' + ids[0] + '/status', '/versions/' + ids[0] + '/result'):
            text = self.client.get(self.base + suffix, headers=self.headers).get_data(as_text=True)
            self.assertNotIn('ground_truth_label', text)
            self.assertNotIn('output_snapshot', text)
            self.assertNotIn('correct_answer', text)
        drain(self.store, self.fake_execute)
        exp = self.client.get(self.base, headers=self.headers).json
        self.assertEqual(exp['correct_answer_label'], 1)
        v1 = self.store.version(self.eid, ids[0])
        self.assertEqual(v1['status'], 'succeeded')
        with self.assertRaises(ResearchError):
            self.store.update(self.eid, ids[0], output_snapshot={'fake': 'overwrite'})

    def test_rc_rv_transcript_rerun_v3_parent_and_immutable_v1(self):
        self.setup_research(); v1 = self.baseline()
        original = json.dumps(v1, sort_keys=True)
        parent = v1
        filesystem_snapshots = {}
        def remember(version):
            directory = Path(version['artifact_paths']['workspace'])
            filesystem_snapshots[str(directory)] = {str(p.relative_to(directory)):sha(p) for p in directory.rglob('*') if p.is_file()}
        remember(v1)
        for field in ('Rc', 'Rv', 'transcript'):
            payload = {'experiment_type': 'input_correction', 'parent_version_id': parent['version_id'], 'field': field, 'value': 'USER corrected ' + field}
            response = self.post('/versions', payload)
            self.assertEqual(response.status_code, 201)
            vid = response.json['version_id']
            self.assertEqual(self.post('/versions', payload).json['version_id'], vid)
            drain(self.store, self.fake_execute)
            new = self.store.version(self.eid, vid)
            self.assertEqual(new['status'], 'succeeded')
            self.assertEqual(new['parent_version_id'], parent['version_id'])
            fields = new['output_snapshot']['student_trace']['fields']
            if field == 'transcript':
                self.assertEqual(fields['Rc'], 'Extracted USER corrected transcript')
            else:
                self.assertEqual(fields[field], payload['value'])
            self.assertNotEqual(fields['K_ext'], parent['output_snapshot']['retrieve']['K_ext'])
            self.assertNotEqual(new['output_snapshot']['student']['reason'], parent['output_snapshot']['student']['reason'])
            self.assertEqual([script for v, script in self.calls if v == vid], ['Retrieve.py', 'run_student.py'])
            self.assertNotIn('ground_truth', json.dumps(fields))
            self.assertNotIn('human_judgment', json.dumps(fields))
            remember(new)
            parent = new
        for directory, hashes in filesystem_snapshots.items():
            self.assertEqual({str(p.relative_to(directory)):sha(p) for p in Path(directory).rglob('*') if p.is_file()}, hashes)
        self.assertEqual(json.dumps(self.store.version(self.eid, v1['version_id']), sort_keys=True), original)
        self.assertEqual(len(self.store.versions(self.eid)), 4)

    def test_no_change_empty_invalid_field_and_unavailable_transcript(self):
        self.setup_research(); v1 = self.baseline()
        for field, value in [('Rc', ''), ('Rc', v1['output_snapshot']['retrieve']['Rc']), ('ground_truth_label', '0'), ('K_ext', 'rewrite')]:
            self.assertEqual(self.post('/versions', {'experiment_type': 'input_correction', 'parent_version_id': v1['version_id'], 'field': field, 'value': value}).status_code, 400)
        self.assertEqual(len(self.store.versions(self.eid)), 1)
        # A real absent transcript is rejected, not fabricated (separate fixture baseline).
        self.store = Store(self.root / 'empty')
        from werkzeug.datastructures import FileStorage
        exp, _ = self.store.create(FileStorage(stream=io.BytesIO(b'x'), filename='empty.mp4'), None, 'empty')
        self.store.lock_human(exp['experiment_id'], 'false', '')
        v, _ = self.store.create_version(exp['experiment_id'], {})
        self.store.update(exp['experiment_id'], v['version_id'], status='succeeded', output_snapshot={'preprocess': {}, 'retrieve': {}})
        with self.assertRaises(ResearchError):
            self.store.create_version(exp['experiment_id'], {'experiment_type':'input_correction', 'parent_version_id':v['version_id'], 'field':'transcript', 'value':'fake'})

    def test_failed_correction_preserves_input_and_original_and_restart_failure(self):
        self.setup_research(); v1 = self.baseline()
        v2 = self.post('/versions', {'experiment_type':'input_correction', 'parent_version_id':v1['version_id'], 'field':'Rc', 'value':'Changed'}).json
        def failure(script, *args):
            if script == 'run_student.py':
                raise TimeoutError('private failure')
            self.fake_execute(script, *args)
        drain(self.store, failure)
        failed = self.store.version(self.eid, v2['version_id'])
        self.assertEqual(failed['status'], 'failed')
        self.assertIsNone(failed['output_snapshot'])
        self.assertEqual(failed['input_snapshot']['student_fields']['Rc'], 'Changed')
        self.assertEqual(self.store.version(self.eid, v1['version_id']), v1)
        third, _ = self.store.create_version(self.eid, {'experiment_type':'input_correction', 'parent_version_id':v1['version_id'], 'field':'Rv', 'value':'Third'})
        self.store.update(self.eid, third['version_id'], status='running')
        drain(Store(self.store.root), self.fake_execute)
        self.assertEqual(self.store.version(self.eid, third['version_id'])['status'], 'failed')

    def test_same_filename_experiments_isolated_and_os_lock(self):
        self.setup_research()
        other = self.client.post('/experiments', data={'video': (io.BytesIO(b'other'), 'fake-sample.mp4')}).json
        self.assertNotEqual(self.exp['video_asset_id'], other['experiment']['video_asset_id'])
        self.assertNotEqual(self.exp['video_sha256'], other['experiment']['video_sha256'])
        self.assertEqual(self.client.get('/experiments/' + other['experiment']['experiment_id'], headers=self.headers).status_code, 404)
        with worker_lock(self.store.root) as acquired:
            self.assertTrue(acquired)
            with worker_lock(self.store.root) as second:
                self.assertFalse(second)

    def test_actual_retrieve_override_request_and_effective_output(self):
        work = self.root / 'retrieve-test'
        frames = work / 'preprocess_output/frames/neutral'
        frames.mkdir(parents=True)
        for i in range(16):
            (frames / f'frame_{i:04d}.png').write_bytes(b'mock-image')
        write(work / 'preprocess_output/all.json', {'vid':'neutral','transcript':'spoken','description':'visual'})
        write(work / 'input_overrides.json', {'Rc':'User claim','Rv':'User visual claim'})
        types = SimpleNamespace(Part=SimpleNamespace(from_bytes=lambda **kw: kw))
        genai = SimpleNamespace(types=types)
        spec = importlib.util.spec_from_file_location('retrieve_override_test', test_deployment.BACKEND / 'Retrieve.py')
        retrieve = importlib.util.module_from_spec(spec)
        env = {'WEAVE_WORK_DIR':str(work), 'WEAVE_ANALYSIS_ID':'version-test', 'WEAVE_RUN_ID':'2', 'GEMINI_API_KEY':'mock-not-a-secret'}
        with patch.dict(os.environ, env), patch('dotenv.load_dotenv'), patch.dict(sys.modules, {'google':SimpleNamespace(genai=genai), 'google.genai':genai, 'google.genai.types':types}):
            spec.loader.exec_module(retrieve)
            generated = {'Rc':'Model attempted replacement','Rv':'Model visual replacement','K_int':'New knowledge','K_ext':'New search knowledge','query':[], 'uri':[]}
            with patch.object(retrieve, 'count_input_tokens', return_value=10), patch.object(retrieve, 'generate_with_retry', return_value=(generated, 'raw')) as model, patch.object(retrieve, 'prepare_evidence', return_value=None):
                retrieve.main()
        contents = model.call_args.args[0]
        self.assertIn('User claim', contents[-1])
        self.assertIn('User visual claim', contents[-1])
        self.assertIn('Regenerate K_int', contents[-1])
        output = json.loads((work / 'output/retrieve.jsonl').read_text())
        self.assertEqual(output['Rc'], 'User claim')
        self.assertEqual(output['Rv'], 'User visual claim')
        self.assertEqual(output['generated_fields_before_override']['Rc'], generated['Rc'])
        self.assertEqual(output['K_ext'], generated['K_ext'])
        sent = json.loads((work / 'output/retrieve_sent.jsonl').read_text(encoding='utf-8'))
        self.assertEqual(sent['system_prompt'], retrieve.SYSTEM_PROMPT)
        self.assertEqual(sent['prompt'], contents[-1])
        self.assertEqual(sent['temperature'], 0.0)
        self.assertNotIn('human_judgment', sent['prompt'])

    def test_worker_never_marks_missing_student_or_bad_override_success(self):
        self.setup_research(); v1 = self.baseline()
        v, _ = self.store.create_version(self.eid, {'experiment_type':'input_correction','parent_version_id':v1['version_id'],'field':'Rc','value':'New correction'})
        def wrong_override(script, args, work, version):
            self.fake_execute(script, args, work, version)
            if script == 'Retrieve.py':
                data = read(work / 'output/retrieve.jsonl'); data['Rc'] = 'overwritten'
                (work / 'output/retrieve.jsonl').write_text(json.dumps(data), encoding='utf-8')
        drain(self.store, wrong_override)
        self.assertEqual(self.store.version(self.eid,v['version_id'])['status'],'failed')
        self.assertNotIn((v['version_id'],'run_student.py'),self.calls)

    def test_actual_student_predict_records_exact_tokens_and_failure_input(self):
        class Tensor(list):
            shape = (1, 2)
            def detach(self): return self
            def cpu(self): return self
            def tolist(self): return list(self)
            def __getitem__(self, key):
                value = super().__getitem__(key)
                return Tensor(value) if isinstance(key, slice) else value
        class Inputs(dict):
            def to(self, device): return self
        class Tokenizer:
            eos_token_id, pad_token_id = 2, 0
            def apply_chat_template(self, messages, **kwargs): return 'CHAT:' + messages[0]['content']
            def __call__(self, prompt, **kwargs): return Inputs(input_ids=Tensor([[10,11]]), attention_mask=Tensor([[1,1]]))
            def decode(self, ids, **kwargs): return '{"pred_label":1,"reason":"Original mock reason"}'
        module_spec = importlib.util.spec_from_file_location('student_trace_test', test_deployment.BACKEND / 'student_bot.py')
        student = importlib.util.module_from_spec(module_spec)
        stubs = {'yaml': SimpleNamespace(safe_load=lambda _: {}), 'torch': SimpleNamespace(no_grad=nullcontext),
                 'transformers':SimpleNamespace(AutoTokenizer=None, AutoModelForCausalLM=None, BitsAndBytesConfig=None),
                 'peft':SimpleNamespace(PeftModel=None)}
        with patch.dict(sys.modules, stubs):
            module_spec.loader.exec_module(student)
        bot = student.StudentBot.__new__(student.StudentBot)
        bot.config = {'USER_PROMPT_TEMPLATE':'Rc:{Rc}\nRv:{Rv}\nKint:{K_int}\nKext:{K_ext}'}
        bot.system_prompt, bot.max_length, bot.base_model_name = 'original system', 5000, 'mock-model'
        bot.tokenizer = Tokenizer()
        bot.model = SimpleNamespace(device='cpu', generate=Mock(return_value=[Tensor([10,11,12,13])]))
        (self.root / 'output').mkdir()
        with patch.dict(os.environ, {'WEAVE_WORK_DIR':str(self.root)}):
            self.assertEqual(bot.predict('corrected Rc','corrected Rv','ki','ke'), (1,'Original mock reason'))
            self.assertIn('corrected Rc', bot.last_trace['formatted_prompt'])
            self.assertEqual(bot.last_trace['effective_input_ids'], [[10,11]])
            self.assertEqual(bot.last_trace['generated_ids'], [12,13])
            self.assertEqual(bot.model.generate.call_args.kwargs['max_new_tokens'],256)
            self.assertFalse(bot.model.generate.call_args.kwargs['do_sample'])
            bot.predict('corrected Rc','corrected Rv','ki','')
            self.assertIn('Kext:無',bot.last_trace['formatted_prompt'])
            self.assertNotIn('Kext:- ke',bot.last_trace['formatted_prompt'])
            malformed = '1, 1\n\nOriginal model prose.\nYN\n' + 'YN' * 100
            bot.tokenizer.decode = Mock(return_value=malformed)
            (self.root / 'output/retrieve.jsonl').write_text(json.dumps({'vid':'fixture','analysis_id':'fixture-run',
                'Rc':'rc','Rv':'rv','K_int':'ki','K_ext':'ke'}),encoding='utf-8')
            with patch.dict(sys.modules, {'student_bot':SimpleNamespace(StudentBot=lambda **kwargs:bot)}):
                with self.assertRaisesRegex(ValueError, 'Invalid Student output'):
                    runpy.run_path(str(test_deployment.BACKEND / 'run_student.py'))
            diagnostic = read(self.root / 'output/student_output_error.json')
            self.assertEqual(diagnostic['pred_label'], -1)
            self.assertEqual(diagnostic['raw_response'], malformed)
            self.assertEqual(diagnostic['parse_error']['type'], 'JSONDecodeError')
            self.assertEqual(diagnostic['parse_error']['message'], 'Extra data: line 1 column 2 (char 1)')
            self.assertFalse((self.root / 'output/final_result.json').exists())
            self.assertEqual(read(self.root / 'output/student_trace.json')['raw_response'], malformed)
            bot.model.generate.side_effect = RuntimeError('mock GPU failure')
            with self.assertRaises(RuntimeError):
                bot.predict('failed correction','rv','ki','ke')
        trace = read(self.root / 'output/student_trace.json')
        self.assertEqual(trace['fields']['Rc'], 'failed correction')
        self.assertIsNone(trace['raw_response'])


if __name__ == '__main__':
    unittest.main()
