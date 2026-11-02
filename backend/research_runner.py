"""One OS-locked worker; each version owns its complete filesystem namespace."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import runpy
import traceback
from contextlib import contextmanager
from pathlib import Path

from research_store import Store, now

BASE = Path(__file__).resolve().parent


def version_workspace(root, version_id):
    # UUID remains globally unique; omit the redundant experiment UUID from the path.
    # Existing versions continue to use their persisted artifact_paths unchanged.
    return Path(root) / 'jobs' / version_id


@contextmanager
def worker_lock(root, name='worker.lock'):
    with (Path(root) / name).open('a+b') as lock:
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                yield False
                return
        else:
            import fcntl
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
        try:
            yield True
        finally:
            lock.seek(0)
            if os.name == 'nt':
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def sha(path):
    with Path(path).open('rb') as f:
        h = hashlib.sha256()
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def command(script, args, workspace, version):
    env = os.environ.copy()
    env.update(WEAVE_WORK_DIR=str(workspace), WEAVE_ANALYSIS_ID=version['version_id'],
               WEAVE_EXPERIMENT_TYPE=version.get('experiment_type', ''),
               WEAVE_RUN_ID=str(version['version_number']), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    # Preserve the existing Retrieve CA-bundle configuration without reading secrets.
    env.update(PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    temporary = None
    try:
        if script == 'Retrieve.py':
            from pipeline import create_retrieve_ca_bundle
            bundle, disposable = create_retrieve_ca_bundle()
            for key in ('SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'GRPC_DEFAULT_SSL_ROOTS_FILE_PATH'):
                env[key] = bundle
            temporary = bundle if disposable else None
        with (workspace / 'execution.log').open('a', encoding='utf-8') as log:
            argv = [sys.executable, str(BASE / 'research_runner.py'), '--stage', str(workspace.parent.parent), script, *args]
            log.write(json.dumps({'python': sys.executable, 'cwd': str(workspace), 'script': script,
                'argv': argv, 'environment': {k: env[k] for k in ('WEAVE_WORK_DIR', 'WEAVE_ANALYSIS_ID', 'WEAVE_RUN_ID', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'PYTHONIOENCODING', 'PYTHONUTF8')}}) + '\n')
            log.flush()
            try:
                subprocess.run(argv, cwd=workspace, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=7200)
            except subprocess.CalledProcessError as error:
                log.write(json.dumps({'script': script, 'exit_code': error.returncode}) + '\n')
                raise
            else:
                log.write(json.dumps({'script': script, 'exit_code': 0}) + '\n')
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def run_version(store, version, execute=command, summary_dispatch=None):
    from runtime_profile import new_profile
    profile = new_profile()
    total_started = time.perf_counter()
    original_execute = execute
    def execute(script, args, workspace, version):
        started = time.perf_counter()
        row = {'stage': 'preprocess' if script.startswith('preprocess/') else 'retrieve' if script == 'Retrieve.py' else 'student', 'status': 'failed'}
        try:
            result = original_execute(script, args, workspace, version)
            row['status'] = 'succeeded'
            return result
        finally:
            row['seconds'] = time.perf_counter() - started
            profile['stages'].append(row)
    def saved_profile():
        profile['total_verification_seconds'] = time.perf_counter() - total_started
        try:
            calls = [json.loads(line) for line in (workspace / 'output/runtime_calls.jsonl').read_text(encoding='utf-8').splitlines()]
            profile['external_sdk_call_count'] = sum(r.get('event') == 'started' for r in calls)
            profile['api_calls'] = calls
        except (OSError, ValueError):
            profile['external_sdk_call_count'] = None
            profile['api_calls'] = []
        return profile
    eid, vid = version['experiment_id'], version['version_id']
    exp = store.experiment(eid)
    workspace = version_workspace(store.root, vid)
    active_step = None
    events = []
    def stage(name):
        events.append({'stage': name, 'at': now()})
        store.update(eid, vid, stage=name, events=list(events))
    store.update(eid, vid, status='running', started_at=now(), artifact_paths={'workspace': str(workspace)})
    try:
        workspace.parent.mkdir(exist_ok=True)
        workspace.mkdir(exist_ok=False)
        (workspace / 'output').mkdir()
        frame_directory = workspace / 'preprocess_output' / 'frames' / exp['video_asset_id']
        if os.name == 'nt' and len(str(frame_directory)) >= 248:
            raise OSError('Windows frame directory is too long; configure WEAVE_RESEARCH_ROOT to a shorter private path')
        ablation = version['experiment_type'] == 'evidence_ablation'
        aware = version['experiment_type'] == 'source_aware_baseline'
        selected_news = version['experiment_type'] == 'selected_news'
        grounded = version['experiment_type'] in ('source_grounded_baseline','source_aware_baseline','selected_news')
        manifest_key = 'selected_news_manifest' if selected_news else 'source_aware_manifest' if aware else 'source_grounded_manifest'
        if ablation or grounded:
            from evidence_ablation import effective_retrieve, parent_fields
            if grounded:
                from source_grounded import effective_retrieve
                if aware:
                    from source_aware import effective_retrieve
                if selected_news:
                    from selected_news import effective_retrieve
            parent = store.version(eid, version['parent_version_id'])
            correction = None
            original = Path(parent['artifact_paths']['workspace']) / 'preprocess_output'
            shutil.copytree(original, workspace / 'preprocess_output')
            merged = read(workspace / 'preprocess_output/all.json')
            retrieved = effective_retrieve(parent, version)
            if retrieved.get('vid') != exp['video_asset_id'] or merged.get('vid') != exp['video_asset_id']:
                raise ValueError('Ablation parent video identity mismatch')
            (workspace / 'output/retrieve.jsonl').write_text(json.dumps(retrieved, ensure_ascii=False) + '\n', encoding='utf-8')
            # No Retrieve call occurred in this version. The parent retains its raw trace.
            (workspace / 'output/retrieve_sent.jsonl').write_text('', encoding='utf-8')
            conditions = {'rerun_stages': ['Student'], 'reused_stages': ['Preprocess', 'Retrieve (parent inventory only)'],
                          'reused_artifacts': [{'path': str(p.relative_to(original)), 'sha256': sha(p), 'parent_version_id': parent['version_id']}
                                               for p in original.rglob('*') if p.is_file()],
                          'excluded_input_fields': ['K_ext'], 'regenerated_fields': [],
                          'retrieve_parent_version_id': parent['version_id']}
            if grounded:
                conditions.update(excluded_input_fields=[],replaced_input_fields=['K_ext'],
                                  **{manifest_key+'_hash':version[manifest_key]['manifest_hash']})
                write(workspace / ('output/'+manifest_key+'.json'), version[manifest_key])
            if ablation and version.get('ablation_mode') == 'source_level':
                conditions.update(excluded_input_fields=[], replaced_input_fields=['K_ext'])
                write(workspace / 'output/ablation_manifest.json', version['ablation_manifest'])
            store.update(eid, vid, execution_conditions=conditions)
        else:
            correction = version['correction_payload']
            reused = []
            if correction:
                parent = store.version(eid, version['parent_version_id'])
                original = Path(parent['artifact_paths']['workspace']) / 'preprocess_output'
                shutil.copytree(original, workspace / 'preprocess_output')
                reused = [{'path': str(p.relative_to(original)), 'sha256': sha(p), 'parent_version_id': parent['version_id']}
                          for p in original.rglob('*') if p.is_file()]
                merged = read(workspace / 'preprocess_output/all.json')
                if correction['field'] == 'transcript':
                    merged['transcript'] = correction['after']
                    write(workspace / 'preprocess_output/all.json', merged)
                    reused = [item for item in reused if item['path'] != 'all.json']
                else:
                    prior = parent['output_snapshot']['retrieve']
                    overrides = {key: prior[key] for key in ('Rc', 'Rv')}
                    overrides[correction['field']] = correction['after']
                    write(workspace / 'input_overrides.json', overrides)
                stage('preprocess_reused')
            else:
                stage('preprocess')
                # Same original stages, serialized to avoid competing GPU allocations.
                for script in ('1.Video2Wav.py', '1.Extract_Frames.py', '1.VLM.py', '2.Wav2Transcript.py', '4.Data_Merge.py'):
                    active_step = 'preprocess/' + script
                    execute('preprocess/' + script, [exp['video_path']], workspace, version)
            merged = read(workspace / 'preprocess_output/all.json')
            if merged.get('vid') != exp['video_asset_id']:
                raise ValueError('Preprocess video identity mismatch')
            conditions = {'rerun_stages': ['Retrieve', 'Student'] if correction else ['Preprocess', 'Retrieve', 'Student'],
                          'reused_artifacts': reused,
                          'regenerated_fields': ['K_int', 'K_ext'] if correction and correction['field'] != 'transcript' else ['Rc', 'Rv', 'K_int', 'K_ext'],
                          'override_policy': 'frozen_Rc_Rv_before_retrieval' if correction and correction['field'] != 'transcript' else None}
            store.update(eid, vid, input_snapshot={'preprocess': merged, 'correction': correction}, execution_conditions=conditions)
            stage('retrieve')
            active_step = 'Retrieve.py'
            execute('Retrieve.py', [], workspace, version)
            lines = (workspace / 'output/retrieve.jsonl').read_text(encoding='utf-8').splitlines()
            retrieved = json.loads([line for line in lines if line.strip()][-1])
            if retrieved.get('analysis_id') != vid or retrieved.get('vid') != exp['video_asset_id']:
                raise ValueError('Retrieve identity mismatch')
            if correction and correction['field'] in ('Rc', 'Rv') and retrieved.get(correction['field']) != correction['after']:
                raise ValueError('User correction was not preserved')
            try:
                from automatic_summaries import dispatch
                dispatch(store.root, version, retrieved, summary_dispatch)
            except Exception as summary_error:
                # Even an optional summarizer import/dependency failure cannot fail V1.
                import logging
                logging.getLogger(__name__).warning('Automatic summaries unavailable (%s)', type(summary_error).__name__)
        store.update(eid, vid, input_snapshot={'preprocess': merged, 'correction': correction,
                     'student_fields': {k: retrieved[k] for k in ('Rc', 'Rv', 'K_int', 'K_ext')}})
        stage('student')
        active_step = 'run_student.py'
        if version.get('retry_snapshot'):
            from source_aware_retry import verify
            verify(version,{k:retrieved[k] for k in ('Rc','Rv','K_int','K_ext')})
        execute('run_student.py', [], workspace, version)
        student = read(workspace / 'output/final_result.json')
        if student.get('analysis_id') != vid or student.get('vid') != exp['video_asset_id'] or student.get('pred_label') not in (0, 1):
            raise ValueError('Student output invalid or belongs to another version')
        trace = read(workspace / 'output/student_trace.json')
        if version.get('retry_snapshot'):
            verify(version,trace.get('fields'),trace)

        if ablation:
            expected = parent_fields(parent)
            expected['K_ext'] = version.get('ablation_manifest', {}).get('k_ext', '')
            if version.get('ablation_mode') == 'source_level':
                ids = trace.get('effective_input_ids')
                formatted = '- '+expected['K_ext'] if expected['K_ext'] else '無'
                if formatted not in trace.get('formatted_prompt','') or not ids or not isinstance(trace.get('max_length'),int) or len(ids[0]) >= trace['max_length']:
                    raise ValueError('Source ablation input coverage/formatter audit failed')
            if trace.get('fields') != expected:
                raise ValueError('Ablation Student effective input audit mismatch')
            if version.get('ablation_mode') == 'source_level':
                store.update(eid, vid, contamination_audit={**version['contamination_audit'], 'student_input_verified': True, 'scope': 'actual_Student_trace_and_manifest'})
            store.update(eid, vid, rerun_stage_records=[{'stage': 'Student', 'status': 'succeeded',
                         'started_at': events[-1]['at'], 'finished_at': now()}])
        if grounded:
            expected=parent_fields(parent);expected['K_ext']=version[manifest_key]['k_ext']
            formatted = '- '+expected['K_ext'] if expected['K_ext'] else '無'
            if trace.get('fields')!=expected or formatted not in trace.get('formatted_prompt',''):
                raise ValueError('Source-grounded Student input/formatter trace mismatch')
            ids=trace.get('effective_input_ids')
            if not ids or not isinstance(trace.get('max_length'),int) or len(ids[0])>=trace['max_length']:
                raise ValueError('Cannot establish full source input coverage: missing trace or possible token truncation')
            store.update(eid,vid,rerun_stage_records=[{'stage':'Student','status':'succeeded','started_at':events[-1]['at'],'finished_at':now()}])
        sent = [json.loads(x) for x in (workspace / 'output/retrieve_sent.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
        raw_responses = {p.name: p.read_text(encoding='utf-8') for p in (workspace / 'output/retrieve_receive').glob('*.txt')}
        snapshot = {'retrieve': retrieved, 'student': student, 'preprocess': merged, 'student_trace': trace,
                    'retrieve_trace': sent, 'retrieve_raw_responses': raw_responses}
        if ablation and version.get('ablation_manifest'):
            snapshot['ablation_manifest'] = version['ablation_manifest']
        if grounded:
            snapshot[manifest_key]=version[manifest_key]
        provenance = {'human_locked_at': exp['human_locked_at'], 'video_sha256': exp['video_sha256'],
                      'files': {str(p.relative_to(workspace)): sha(p) for p in workspace.rglob('*') if p.is_file()}}
        write(workspace / 'snapshot.json', snapshot)
        store.update(eid, vid, status='succeeded', stage='done', finished_at=now(), output_snapshot=snapshot, provenance=provenance, runtime_profile=saved_profile())
    except Exception as error:
        # Detailed private error stays with artifacts; public message contains no model output.
        try:
            write(workspace / 'failure.json', {'type': type(error).__name__, 'message': str(error),
                  'step': active_step, 'traceback': traceback.format_exc()})
        except OSError:
            pass  # A disk failure must still become a durable failed job if SQLite works.
        if version['experiment_type'] in ('evidence_ablation','source_grounded_baseline','source_aware_baseline','selected_news'):
            store.update(eid, vid, rerun_stage_records=[{'stage': active_step or 'setup', 'status': 'failed', 'finished_at': now()}])
        failed_stage = events[-1]['stage'] if events else 'setup'
        store.update(eid, vid, status='failed', finished_at=now(),
                     error=f'Analysis failed at {active_step or failed_stage}; diagnostic details are saved in the private version workspace',
                     failed_stage=failed_stage, failed_step=active_step, stage='error', runtime_profile=saved_profile())


def drain(store, execute=command, summary_dispatch=None):
    with worker_lock(store.root) as acquired:
        if not acquired:
            return
        with store.transaction() as db:
            rows = [json.loads(r[0]) for r in db.execute('SELECT data FROM versions ORDER BY rowid')]
        for v in rows:
            if v['status'] == 'running':
                store.update(v['experiment_id'], v['version_id'], status='failed', stage='error', finished_at=now(), error='Worker interrupted; incomplete version preserved')
        while True:
            with store.transaction() as db:
                pending = [json.loads(r[0]) for r in db.execute('SELECT data FROM versions ORDER BY rowid') if json.loads(r[0])['status'] == 'pending']
            if not pending:
                return
            run_version(store, pending[0], execute, summary_dispatch)


if __name__ == '__main__':
    if sys.argv[1] == '--stage':
        root, script, args = sys.argv[2], sys.argv[3], sys.argv[4:]
        # This lock lives in the actual model process, surviving a Flask/worker crash.
        # A new worker cannot overlap with an orphaned prior model stage.
        deadline = time.monotonic() + 7200
        while True:
            with worker_lock(root, 'model.lock') as acquired:
                if acquired:
                    sys.argv = [str(BASE / script), *args]
                    if script == 'Retrieve.py':
                        from runtime_profile import observe_gemini
                        with observe_gemini(Path(os.environ['WEAVE_WORK_DIR'])):
                            runpy.run_path(str(BASE / script), run_name='__main__')
                    else:
                        runpy.run_path(str(BASE / script), run_name='__main__')
                    break
            if time.monotonic() >= deadline:
                raise TimeoutError('Model execution lock timeout')
            time.sleep(0.2)
    else:
        def launch_summaries(root):
            from automatic_summaries import launch
            launch(root)
        drain(Store(sys.argv[1]), summary_dispatch=launch_summaries)
