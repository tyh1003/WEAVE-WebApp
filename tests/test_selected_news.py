"""Selected-news API and Student-only orchestration, fixtures only."""
import copy
import json
import unittest
from pathlib import Path
import test_research
from test_source_summarization_poc import fixture
from research_runner import drain, read, write, sha
import automatic_summaries as auto
import source_summarization_poc as poc

class SelectedNewsTests(unittest.TestCase):
    def setUp(self):
        self.c=test_research.ResearchTests();self.c.setUp();self.addCleanup(self.c.doCleanups)
        self.c.setup_research();self.c.lock()
        first=self.c.post('/versions',{'experiment_type':'baseline'}).json
        def execute(script,args,work,v):
            self.c.fake_execute(script,args,work,v)
            if script=='Retrieve.py':
                r=json.loads((work/'output/retrieve.jsonl').read_text(encoding='utf-8'))
                r['evidence']=fixture()['output_snapshot']['retrieve']['evidence']
                (work/'output/retrieve.jsonl').write_text(json.dumps(r),encoding='utf-8')
        drain(self.c.store,execute)
        self.parent=self.c.store.version(self.c.eid,first['version_id'])
        self.assertEqual(self.parent['status'],'succeeded')
        auto.process(self.c.store.root,poc.mock_provider)
        rows=auto.state(self.c.store.root,self.c.eid,first['version_id'])['records']
        self.ids=[{k:r[k] for k in ('source_id','article_text_hash','cache_key')} for r in rows]
        self.rows=rows
    def payload(self,ids):return dict(experiment_type='selected_news',parent_version_id=self.parent['version_id'],selected_sources=ids,confirm=True)

    def test_saved_v1_inventory_and_child_results_stay_version_scoped(self):
        parent_id = self.parent['version_id']
        child = self.c.post('/versions', dict(experiment_type='input_correction',
            parent_version_id=parent_id, field='Rc', value='New fixture claim'))
        self.assertEqual(child.status_code, 201)
        drain(self.c.store, self.c.fake_execute)
        def get(vid, endpoint):
            res = self.c.client.get(f'{self.c.base}/versions/{vid}/{endpoint}', headers=self.c.headers)
            self.assertEqual(res.status_code, 200)
            return res.json
        saved = get(parent_id, 'result')['output_snapshot']['retrieve']['evidence']['sources']
        self.assertTrue(saved)
        self.assertEqual(saved, self.parent['output_snapshot']['retrieve']['evidence']['sources'])
        self.assertEqual(get(parent_id, 'automatic-summaries')['records'], self.rows)
        child_id = child.json['version_id']
        self.assertEqual(get(child_id, 'result')['output_snapshot']['retrieve']['analysis_id'], child_id)
        self.assertEqual(get(child_id, 'automatic-summaries')['records'], [])
    def test_selected_and_empty_student_only_parent_immutable_and_idempotent(self):
        before=copy.deepcopy(self.parent);work=Path(before['artifact_paths']['workspace'])
        hashes={str(p):sha(p) for p in work.rglob('*') if p.is_file()}
        for ids in [self.ids[::-1],[]]:
            request=self.payload(ids);response=self.c.post('/versions',request)
            self.assertEqual(response.status_code,201,response.json)
            self.assertEqual(self.c.post('/versions',request).json['version_id'],response.json['version_id'])
            child=self.c.store.version(self.c.eid,response.json['version_id'])
            units=child['selected_news_manifest']['units'];expected='\n\n'.join('['+u['source_id']+'] '+u['title']+'\n'+u['url']+'\n'+u['summary'] for u in units)
            self.assertEqual(child['selected_news_manifest']['k_ext'],expected)
            self.assertEqual([u['source_id'] for u in units],[s['source_id'] for s in ids])
            if not ids:self.assertEqual(expected,'')
            calls=[]
            def execute(script,args,workspace,v):
                calls.append(script);self.assertEqual(script,'run_student.py')
                self.c.fake_execute(script,args,workspace,v)
                t=read(workspace/'output/student_trace.json')
                self.assertEqual(t['fields']['K_ext'],expected)
                for k in ('Rc','Rv','K_int'):self.assertEqual(t['fields'][k],before['output_snapshot']['retrieve'][k])
                t.update(formatted_prompt=('- '+expected if expected else '無'),effective_input_ids=[[1,2]],max_length=100)
                write(workspace/'output/student_trace.json',t)
            drain(self.c.store,execute)
            saved=self.c.store.version(self.c.eid,child['version_id'])
            self.assertEqual(saved['status'],'succeeded',saved.get('error'));self.assertEqual(calls,['run_student.py'])
            self.assertEqual(saved['parent_version_id'],before['version_id'])
        self.assertEqual(self.c.store.version(self.c.eid,before['version_id']),before)
        self.assertEqual(hashes,{str(p):sha(p) for p in work.rglob('*') if p.is_file()})
    def test_reject_invalid_stale_foreign_duplicate_and_arbitrary_text(self):
        for ids in [[{**self.ids[0],'source_id':'foreign'}],[{**self.ids[0],'article_text_hash':'stale'}],[{**self.ids[0],'cache_key':'stale'}],[self.ids[0],self.ids[0]],None]:
            self.assertEqual(self.c.post('/versions',self.payload(ids)).status_code,400)
        self.assertEqual(self.c.post('/versions',{**self.payload([]),'K_ext':'injected'}).status_code,400)
        self.assertNotEqual(self.c.post('/versions',{**self.payload([]),'parent_version_id':'foreign'}).status_code,201)
        self.assertEqual(len(self.c.store.versions(self.c.eid)),1)
        self.c.dispatch.reset_mock()
        self.c.post('/versions',self.payload([{'source_id':'bad','article_text_hash':'bad','cache_key':'bad'}]))
        self.c.dispatch.assert_not_called()
    def test_failed_or_missing_summary_rejected(self):
        with self.c.store.transaction() as db:
            row=db.execute('SELECT data FROM automatic_summary_jobs WHERE version=?',(self.parent['version_id'],)).fetchone()
            job=json.loads(row[0]);job['records'][0]['status']='failed'
            db.execute('UPDATE automatic_summary_jobs SET data=? WHERE version=?',(json.dumps(job),self.parent['version_id']))
        self.assertEqual(self.c.post('/versions',self.payload([self.ids[0]])).status_code,400)
        with self.c.store.transaction() as db:
            job['records'][0].update(status='completed',summary='')
            db.execute('UPDATE automatic_summary_jobs SET data=? WHERE version=?',(json.dumps(job),self.parent['version_id']))
        self.assertEqual(self.c.post('/versions',self.payload([self.ids[0]])).status_code,400)
    def test_student_failure_retained(self):
        response=self.c.post('/versions',self.payload([]));self.assertEqual(response.status_code,201)
        def fail(*args):raise RuntimeError('offline Student failure')
        drain(self.c.store,fail)
        v=self.c.store.version(self.c.eid,response.json['version_id'])
        self.assertEqual(v['status'],'failed');self.assertTrue((Path(v['artifact_paths']['workspace'])/'failure.json').exists())
        self.assertEqual(self.c.store.version(self.c.eid,self.parent['version_id']),self.parent)

    def test_frontend_preview_equals_server_assembly(self):
        import subprocess
        from selected_news import plan
        module=(Path(__file__).resolve().parents[1]/'src/workspaceNews.js').as_uri()
        script="""import {unifiedNews,newsSelection,newsPreview} from MODULE;
let raw='';for await(const chunk of process.stdin)raw+=chunk;
const input=JSON.parse(raw),cards=unifiedNews(input.sources,[],{records:input.records}).reverse();
const keys=input.empty?[]:cards.map(newsSelection).map(s=>s.key).filter(Boolean);
console.log(JSON.stringify({preview:newsPreview(cards,keys),ids:cards.map(newsSelection).filter(s=>keys.includes(s.key)).map(s=>s.identity)}));""".replace('MODULE',json.dumps(module))
        for empty in (False,True):
            response=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps({'sources':self.parent['output_snapshot']['retrieve']['evidence']['sources'],'records':self.rows,'empty':empty}),text=True,encoding='utf-8',capture_output=True,check=True)
            frontend=json.loads(response.stdout)
            with self.c.store.transaction() as db:manifest=plan(self.parent,frontend['ids'],db)
            self.assertEqual(frontend['preview'],manifest['k_ext'])
