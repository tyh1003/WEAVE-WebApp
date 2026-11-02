"""Durable research records. All mutations serialize through SQLite transactions."""
import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class ResearchError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'research.sqlite3'
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS experiments (id TEXT PRIMARY KEY, token TEXT NOT NULL, data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS versions (id TEXT PRIMARY KEY, experiment TEXT NOT NULL, number INTEGER NOT NULL, request_key TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(experiment,number), UNIQUE(experiment,request_key))')
            from source_summarization import initialize
            initialize(db)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.db, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, file, label, dataset_id):
        eid, asset, token = uuid4().hex, uuid4().hex, secrets.token_urlsafe(32)
        suffix = Path(file.filename or '').suffix.lower()
        if suffix not in {'.mp4', '.mov', '.webm', '.avi', '.mkv', '.m4v'}:
            raise ResearchError('Unsupported video extension', 400)
        directory = self.root / eid
        directory.mkdir()
        path = directory / (asset + suffix)
        file.save(path)
        sha = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                sha.update(chunk)
        data = dict(experiment_id=eid, video_asset_id=asset, original_filename=file.filename,
                    safe_display_filename='Video-' + asset[:8] + suffix, video_sha256=sha.hexdigest(),
                    video_path=str(path), video_bytes=path.stat().st_size, dataset_video_id=dataset_id,
                    dataset_match_status='filename_only_content_unverified' if label in (0, 1) else 'not_found',
                    ground_truth_label=label, human_judgment=None, human_reason=None,
                    human_locked_at=None, created_at=now())
        with self.transaction() as db:
            db.execute('INSERT INTO experiments VALUES (?,?,?)', (eid, digest(token), json.dumps(data)))
        return data, token

    def experiment(self, eid, token=None):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM experiments WHERE id=?', (eid,)).fetchone()
        if not row or (token is not None and not secrets.compare_digest(row['token'], digest(token))):
            raise ResearchError('Experiment not found or access denied', 404)
        return json.loads(row['data'])

    def lock_human(self, eid, vote, reason):
        if vote not in ('true', 'false') or not isinstance(reason, str) or len(reason) > 10000:
            raise ResearchError('Expected true/false and a bounded text reason', 400)
        with self.transaction() as db:
            item = json.loads(db.execute('SELECT data FROM experiments WHERE id=?', (eid,)).fetchone()[0])
            if item['human_locked_at']:
                if vote != item['human_judgment'] or reason != item['human_reason']:
                    raise ResearchError('Initial judgment is locked')
                return item
            item.update(human_judgment=vote, human_reason=reason, human_locked_at=now())
            db.execute('UPDATE experiments SET data=? WHERE id=?', (json.dumps(item), eid))
        return item

    def versions(self, eid):
        with self.transaction() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT data FROM versions WHERE experiment=? ORDER BY number', (eid,))]

    def version(self, eid, vid):
        with self.transaction() as db:
            row = db.execute('SELECT data FROM versions WHERE experiment=? AND id=?', (eid, vid)).fetchone()
        if not row:
            raise ResearchError('Version not found', 404)
        return json.loads(row[0])

    def create_version(self, eid, payload):
        with self.transaction() as db:
            exp = json.loads(db.execute('SELECT data FROM experiments WHERE id=?', (eid,)).fetchone()[0])
            if not exp['human_locked_at']:
                raise ResearchError('Lock Human Judgment before starting V1')
            rows = [json.loads(r[0]) for r in db.execute('SELECT data FROM versions WHERE experiment=? ORDER BY number', (eid,))]
            kind = payload.get('experiment_type', 'baseline')
            extra = {}
            if kind == 'baseline':
                if rows:
                    return rows[0], False
                key, parent, correction = 'baseline', None, None
            elif kind == 'selected_news':
                from selected_news import plan
                parent=next((r for r in rows if r['version_id']==payload.get('parent_version_id')),None)
                if not rows or rows[0]['status']!='succeeded' or not parent or parent['status']!='succeeded':
                    raise ResearchError('A successful baseline and parent are required')
                if payload.get('confirm') is not True:raise ResearchError('Explicit Student rerun confirmation required',400)
                if set(payload)-{'experiment_type','parent_version_id','selected_sources','confirm'}:
                    raise ResearchError('Only saved source identifiers may be submitted',400)
                try:manifest=plan(parent,payload.get('selected_sources'),db)
                except (ValueError,KeyError,TypeError) as error:raise ResearchError(str(error),400) from error
                correction=None
                extra=dict(selected_news_manifest=manifest,effective_input_diff={'K_ext':{'before':parent['output_snapshot']['retrieve']['K_ext'],'after':manifest['k_ext']}},
                    input_provenance={'parent_version_id':parent['version_id'],'unchanged_fields':['Rc','Rv','K_int'],'manifest_hash':manifest['manifest_hash']},rerun_stage_records=[])
                key=digest(json.dumps([kind,parent['version_id'],manifest['manifest_hash']]))
                duplicate=next((r for r in rows if r['request_key']==key),None)
                if duplicate:return duplicate,False
            elif kind == 'input_correction':
                parent = next((r for r in rows if r['version_id'] == payload.get('parent_version_id')), None)
                if not rows or rows[0]['status'] != 'succeeded' or not parent or parent['status'] != 'succeeded':
                    raise ResearchError('A successful baseline and parent are required')
                field, after = payload.get('field'), payload.get('value')
                if field not in ('transcript', 'Rc', 'Rv') or not isinstance(after, str) or not after.strip() or len(after) > 100000:
                    raise ResearchError('Invalid correction', 400)
                snapshot = parent['output_snapshot']
                before = snapshot['preprocess'].get(field) if field == 'transcript' else snapshot['retrieve'].get(field)
                if not isinstance(before, str) or not before.strip():
                    raise ResearchError('Original field is unavailable', 400)
                if after.strip() == before.strip():
                    raise ResearchError('Correction has no change', 400)
                correction = dict(field=field, before=before, after=after, origin='user_unverified')
                key = digest(json.dumps([parent['version_id'], field, after], ensure_ascii=False))
                duplicate = next((r for r in rows if r['request_key'] == key), None)
                if duplicate:
                    return duplicate, False
            elif kind == 'source_grounded_baseline':
                from source_grounded import plan
                parent = next((r for r in rows if r['version_id'] == payload.get('parent_version_id')), None)
                if not rows or rows[0]['status'] != 'succeeded' or not parent or parent['status'] != 'succeeded':
                    raise ResearchError('A successful baseline and parent are required')
                if payload.get('confirm') is not True:
                    raise ResearchError('Explicit source-grounded baseline confirmation required', 400)
                try:
                    manifest=plan(parent)
                except ValueError as error:
                    raise ResearchError(str(error),400) from error
                if not manifest['units']:
                    raise ResearchError('No eligible saved article body; source-grounded baseline unavailable',400)
                if payload.get('manifest_hash') != manifest['manifest_hash']:
                    raise ResearchError('Preview no longer matches; review the source manifest again',409)
                extra=dict(source_grounded_manifest=manifest,
                    effective_input_diff={'K_ext':{'before':parent['output_snapshot']['retrieve']['K_ext'],'after':manifest['k_ext']}},
                    input_provenance={'parent_version_id':parent['version_id'],'unchanged_fields':['Rc','Rv','K_int'],'manifest_hash':manifest['manifest_hash']},
                    rerun_stage_records=[])
                correction=None
                key=digest(json.dumps([kind,parent['version_id'],manifest['manifest_hash']]))
                duplicate=next((r for r in rows if r['request_key']==key),None)
                if duplicate:return duplicate,False
            elif kind == 'source_aware_baseline' and payload.get('retry_of_version_id'):
                failed=next((r for r in rows if r['version_id']==payload['retry_of_version_id']),None)
                if not failed or payload.get('confirm') is not True:
                    raise ResearchError('Explicit failed-version retry confirmation required',400)
                parent=next((r for r in rows if r['version_id']==failed.get('parent_version_id')),None)
                if not rows or rows[0]['status']!='succeeded' or not parent or parent['status']!='succeeded':
                    raise ResearchError('Successful original parent required',409)
                key=digest('source-aware-retry:'+failed['version_id'])
                duplicate=next((r for r in rows if r['request_key']==key),None)
                if duplicate:return duplicate,False
                from source_aware_retry import prepare
                try:extra=prepare(failed,parent,self.root)
                except (ValueError,KeyError,OSError) as error:raise ResearchError('Cannot safely retry: '+str(error),409) from error
                correction=None
            elif kind == 'source_aware_baseline':
                from source_summarization import state
                parent = next((r for r in rows if r['version_id'] == payload.get('parent_version_id')), None)
                if not rows or rows[0]['status'] != 'succeeded' or not parent or parent['status'] != 'succeeded':
                    raise ResearchError('A successful baseline and parent are required')
                if payload.get('confirm') is not True:
                    raise ResearchError('Explicit source-aware baseline confirmation required', 400)
                try:
                    manifest=state(parent,self.root,db)['manifest']
                except ValueError as error:
                    raise ResearchError(str(error),400) from error
                if not manifest['units']:
                    raise ResearchError('No approved validated summary; source-aware baseline unavailable',400)
                if payload.get('manifest_hash') != manifest['manifest_hash']:
                    raise ResearchError('Preview no longer matches; review the source manifest again',409)
                extra=dict(source_aware_manifest=manifest,
                    effective_input_diff={'K_ext':{'before':parent['output_snapshot']['retrieve']['K_ext'],'after':manifest['k_ext']}},
                    input_provenance={'parent_version_id':parent['version_id'],'unchanged_fields':['Rc','Rv','K_int'],'manifest_hash':manifest['manifest_hash']},
                    rerun_stage_records=[])
                correction=None
                key=digest(json.dumps([kind,parent['version_id'],manifest['k_ext_hash'],[(u['source_id'],u['article_text_hash'],u['evidence_text_hash']) for u in manifest['units']]]))
                duplicate=next((r for r in rows if r['request_key']==key),None)
                if duplicate:return duplicate,False
            elif kind == 'evidence_ablation':
                from evidence_ablation import plan
                parent = next((r for r in rows if r['version_id'] == payload.get('parent_version_id')), None)
                if not rows or rows[0]['status'] != 'succeeded' or not parent or parent['status'] != 'succeeded':
                    raise ResearchError('A successful baseline and parent are required')
                try:
                    extra = plan(parent, payload.get('ablation_mode'), payload.get('excluded_unit_ids', []) if payload.get('ablation_mode') == 'source_level' else payload.get('excluded_source_ids', []))
                except ValueError as error:
                    raise ResearchError(str(error), 400) from error
                correction = None
                key = digest(json.dumps(['evidence_ablation', parent['version_id'], extra['ablation_mode']]))
                if extra['ablation_mode'] == 'source_level':
                    if payload.get('confirm') is not True or payload.get('manifest_hash') != extra['ablation_manifest']['manifest_hash']:
                        raise ResearchError('Confirm the current source-ablation preview',409)
                    key = digest(json.dumps([key, extra['excluded_unit_ids'], extra['ablation_manifest']['manifest_hash'], extra['input_provenance'] ],sort_keys=True))
                    extra['ablation_request_hash'] = key
                    matches = [r for r in rows if r.get('ablation_request_hash') == key]
                    if matches:
                        latest = matches[-1]
                        if latest['status'] != 'failed' or payload.get('retry_of_version_id') != latest['version_id']:
                            return latest, False
                        key = digest(key + latest['version_id'])
                duplicate = next((r for r in rows if r['request_key'] == key), None)
                if duplicate:
                    return duplicate, False
            else:
                raise ResearchError('Unsupported experiment type', 400)
            vid = uuid4().hex
            version = dict(version_id=vid, experiment_id=eid, version_number=len(rows)+1,
                           parent_version_id=parent['version_id'] if parent else None,
                           experiment_type=kind, request_key=key, status='pending', stage='queued',
                           created_at=now(), started_at=None, finished_at=None, error=None,
                           correction_payload=correction, execution_conditions={},
                           input_snapshot={'video_asset_id': exp['video_asset_id'], 'video_sha256': exp['video_sha256'], 'correction': correction},
                           output_snapshot=None, artifact_paths={}, provenance={'human_locked_at': exp['human_locked_at']}, events=[])
            version.update(extra)
            db.execute('INSERT INTO versions VALUES (?,?,?,?,?)', (vid, eid, version['version_number'], key, json.dumps(version)))
        return version, True

    def update(self, eid, vid, **fields):
        with self.transaction() as db:
            row = db.execute('SELECT data FROM versions WHERE experiment=? AND id=?', (eid, vid)).fetchone()
            item = json.loads(row[0])
            if item['status'] in ('succeeded', 'failed'):
                raise ResearchError('Terminal version is immutable')
            if fields.get('status') == 'succeeded' and not fields.get('output_snapshot'):
                raise ResearchError('Success requires output snapshot')
            item.update(fields)
            db.execute('UPDATE versions SET data=? WHERE id=?', (json.dumps(item, ensure_ascii=False), vid))
        return item

    def reveal(self, eid):
        rows = self.versions(eid)
        return bool(rows and rows[0]['status'] == 'succeeded')

    def public_experiment(self, exp):
        hidden = {'original_filename', 'dataset_video_id', 'ground_truth_label', 'video_path'}
        data = {k: v for k, v in exp.items() if k not in hidden}
        data['results_revealed'] = self.reveal(exp['experiment_id'])
        if data['results_revealed']:
            label = exp['ground_truth_label']
            data.update(correct_answer_label=label, correct_answer_vote={0:'true', 1:'false'}.get(label),
                        correct_answer={0:'真', 1:'假'}.get(label, '找不到對應答案'))
        return data

    def public_version(self, version, revealed):
        # Project historical stage information without mutating immutable failed rows.
        version = dict(version)
        events = version.get('events', [])
        if version['status'] == 'failed' and not version.get('failed_stage'):
            version['failed_stage'] = events[-1].get('stage') if events else None
        if revealed:
            from evidence_ablation import capabilities
            version['ablation_capabilities'] = capabilities(version)
            return version
        # Partial model outputs, prompts, filenames and logs remain private until V1 succeeds.
        keys = ('version_id', 'experiment_id', 'version_number', 'parent_version_id', 'experiment_type',
                'status', 'stage', 'created_at', 'started_at', 'finished_at', 'error', 'correction_payload')
        data = {k: version[k] for k in keys}
        data['failed_stage'] = version.get('failed_stage')
        data['failed_step'] = version.get('failed_step')
        return data
