"""Supplementary Retrieve summaries. Separate records, sequential bounded requests.

No imports or reads trigger model calls. Production runner explicitly dispatches
this worker; tests inject a provider. Interrupted requests are never auto-retried.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import source_summarization as summaries
import source_summarization_poc as poc
from evidence_assessment import assessment_content
from research_store import now


def tables(db):
    db.execute('CREATE TABLE IF NOT EXISTS automatic_summary_jobs (version TEXT PRIMARY KEY, experiment TEXT NOT NULL, data TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS automatic_summary_cache (key TEXT PRIMARY KEY, data TEXT NOT NULL)')


def put_job(db, job):
    db.execute('INSERT OR REPLACE INTO automatic_summary_jobs VALUES (?,?,?)',
               (job['version_id'], job['experiment_id'], json.dumps(job, ensure_ascii=False)))


def prepare(version, retrieved):
    records = []
    inputs = {}
    seen = {}
    sources = (retrieved.get('evidence') or {}).get('sources', [])
    for index, source in enumerate(sorted(sources, key=lambda s: (
            s.get('canonical_url') or s.get('resolved_url') or s.get('source_url') or '', s.get('source_id') or ''))):
        _, body = assessment_content(source)
        url = source.get('canonical_url') or source.get('resolved_url') or source.get('source_url')
        row = dict(source_id=source.get('source_id'), record_id='record-'+str(index),
                   original_url=source.get('source_url'), url=url, title=source.get('article_title'),
                   article_id=source.get('article_id'), article_text_hash=poc.digest(body) if body else None,
                   status='skipped', reason=None, semantic_verified=False, human_approved=False)
        records.append(row)
        # Reuse the exact manual input/quality/length validation, one article at a time.
        parent = dict(version, status='succeeded', output_snapshot={'retrieve': {'evidence': {'sources': [source]}}})
        try:
            value = poc.select(parent)
        except ValueError:
            row['reason'] = ('Article exceeds input limit; not truncated' if len(body) > poc.MAX_ARTICLE_CHARS
                             else 'No usable quality-checked saved article body (status/hash/quality/input validation)')
            row['retrieval_status'] = source.get('retrieval_status')
            row['extraction_error'] = source.get('extraction_error')
            continue
        keys = [('body', poc.digest(body))]
        if url: keys.append(('url', url))
        if source.get('article_id'): keys.append(('article', source['article_id']))
        duplicate = next((seen[k] for k in keys if k in seen), None)
        if duplicate:
            row.update(reason='Duplicate article', duplicate_of=duplicate)
            continue
        key = summaries.cache_key(value)
        for k in keys: seen[k] = row['record_id']
        row.update(status='pending', cache_key=key, reason=None,
                   model=value['model'], summary_origin='ai_generated_not_verified',
                   prompt_hash=poc.digest(value['prompt']), quote_rule=poc.QUOTE_RULE,
                   provider_settings=summaries.GENERATION_SETTINGS,
                   source_manifest=value['sources'][0])
        inputs[key] = value
    return dict(version_id=version['version_id'], experiment_id=version['experiment_id'],
                status='pending' if inputs else 'ineligible', records=records, inputs=inputs,
                created_at=now(), semantic_verified=False, human_approved=False)


def enqueue(root, version, retrieved):
    job = prepare(version, retrieved)
    with summaries.transaction(root) as db:
        tables(db)
        old = db.execute('SELECT data FROM automatic_summary_jobs WHERE version=?', (version['version_id'],)).fetchone()
        if old: return json.loads(old[0])
        put_job(db, job)
    return job


def cached_manual(db, value):
    # Read-only reuse; never alter approval/review tables. Batch IDs may differ.
    target = value['sources'][0]
    for (data,) in db.execute('SELECT data FROM source_summary_attempts ORDER BY rowid DESC'):
        attempt = json.loads(data)
        prior = attempt.get('input', {})
        if prior.get('experiment_id') != value['experiment_id']: continue
        if any(prior.get(k) != value[k] for k in ('model', 'prompt', 'response_schema', 'max_output_tokens')): continue
        if attempt.get('provider_settings') != summaries.GENERATION_SETTINGS: continue
        if 'raw_output' not in attempt: continue
        result = poc.validate_output(attempt['raw_output'], prior)
        for source in prior.get('sources', []):
            if any(source.get(k) != target.get(k) for k in ('article_text_hash', 'url', 'content_quality')): continue
            row = next((r for r in result['summaries'] if r['source_id'] == source['source_id']), {})
            if summaries.eligible(result, row):
                return dict(status='completed', summary=row['summary'], quote_validation=row['quote_validation'],
                            reused_manual_attempt=attempt['id'], semantic_verified=False, human_approved=False)
    return None


def evaluate(root, key, value, provider):
    with summaries.transaction(root) as db:
        tables(db)
        old = db.execute('SELECT data FROM automatic_summary_cache WHERE key=?', (key,)).fetchone()
        if old:
            cached = json.loads(old[0])
            if cached['status'] == 'running':
                # Exclusive process lock is held: previous owner died, outcome unknown.
                cached.update(status='failed', error='Interrupted request; not retried automatically')
                db.execute('UPDATE automatic_summary_cache SET data=? WHERE key=?', (json.dumps(cached), key))
            return cached
        cached = cached_manual(db, value)
        record = cached or dict(status='running', input=value, started_at=now(),
                                 provider_settings=summaries.GENERATION_SETTINGS, quote_rule=poc.QUOTE_RULE)
        db.execute('INSERT INTO automatic_summary_cache VALUES (?,?)', (key, json.dumps(record)))
        if cached: return cached
    try:
        poc.validate_input(value)
        raw, response = provider(value)
        validation = poc.validate_output(raw, value)
        row = validation['summaries'][0] if validation['summaries'] else {}
        valid = summaries.eligible(validation, row)
        record.update(status='completed' if valid else 'failed', raw_output=raw,
                      model_response=response, validation=validation,
                      error=None if valid else 'Summary format, source ID or quote validation failed',
                      summary=row.get('summary') if valid else None, quote_validation=row.get('quote_validation'))
    except Exception as error:
        record.update(status='failed', error='Summary provider failed: '+type(error).__name__)
    record.update(finished_at=now(), semantic_verified=False, human_approved=False)
    with summaries.transaction(root) as db:
        db.execute('UPDATE automatic_summary_cache SET data=? WHERE key=?', (json.dumps(record, ensure_ascii=False), key))
    return record


def process(root, provider=None):
    from research_runner import worker_lock
    # One global summary worker, separate from model.lock and the Student worker.
    while True:
        with worker_lock(root, 'automatic-summaries.lock') as acquired:
            if acquired:
                _drain(root, provider or poc.live_provider)
                return
        time.sleep(.1)


def _drain(root, provider):
    while True:
        with summaries.transaction(root) as db:
            tables(db)
            jobs = [json.loads(r[0]) for r in db.execute('SELECT data FROM automatic_summary_jobs ORDER BY rowid')]
            job = next((j for j in jobs if j['status'] in ('pending', 'running')), None)
            if not job: return
            job['status'] = 'running'
            job.setdefault('runtime_profile', {'external_sdk_call_count': 0, 'provider_seconds': 0, 'calls': [], 'estimated_api_cost': None})
            put_job(db, job)
        started = time.perf_counter()
        def measured_provider(value):
            from runtime_profile import usage
            profile = job['runtime_profile']
            profile['external_sdk_call_count'] += 1
            with summaries.transaction(root) as db: put_job(db, job)
            call = {'status': 'failed', 'token_usage': {}}
            tick = time.perf_counter()
            try:
                raw, response = provider(value)
                call.update(status='succeeded', token_usage=usage(response))
                return raw, response
            finally:
                call['seconds'] = time.perf_counter() - tick
                profile['provider_seconds'] += call['seconds']
                profile['calls'].append(call)
        for row in job['records']:
            if row['status'] != 'pending': continue
            result = evaluate(root, row['cache_key'], job['inputs'][row['cache_key']], measured_provider)
            row.update({k: result[k] for k in ('status', 'summary', 'quote_validation', 'error', 'reused_manual_attempt') if k in result})
            with summaries.transaction(root) as db: put_job(db, job)
        states = [r['status'] for r in job['records'] if 'cache_key' in r]
        job['status'] = ('completed' if all(s == 'completed' for s in states) else
                         'partial' if 'completed' in states else 'failed')
        job['finished_at'] = now()
        job['runtime_profile']['processing_seconds'] = time.perf_counter() - started
        with summaries.transaction(root) as db: put_job(db, job)


def state(root, eid, vid):
    with summaries.transaction(root) as db:
        tables(db)
        row = db.execute('SELECT data FROM automatic_summary_jobs WHERE version=? AND experiment=?', (vid, eid)).fetchone()
    if not row: return dict(status='unavailable', records=[], reason='No automatic summary job for this version')
    job = json.loads(row[0])
    job.pop('inputs', None)
    for record in job['records']:
        manifest = record.get('source_manifest')
        if manifest: manifest.pop('article_text', None)
    return job


def launch(root):
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(Path(root).resolve())],
                     cwd=Path(__file__).resolve().parent, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, start_new_session=os.name != 'nt')


def dispatch(root, version, retrieved, launcher=None):
    """No supplementary failure may escape into the verification state machine."""
    try:
        enqueue(root, version, retrieved)
        if launcher: launcher(root)
    except Exception as error:
        import logging
        logging.getLogger(__name__).warning('Automatic summaries unavailable (%s)', type(error).__name__)
        try:
            with summaries.transaction(root) as db:
                tables(db)
                row = db.execute('SELECT data FROM automatic_summary_jobs WHERE version=?', (version['version_id'],)).fetchone()
                job = json.loads(row[0]) if row else dict(version_id=version['version_id'], experiment_id=version['experiment_id'], records=[])
                if job.get('status') not in ('completed', 'partial', 'ineligible'):
                    job.update(status='failed', error='Summary scheduling failed: '+type(error).__name__)
                    put_job(db, job)
        except Exception:
            pass  # Storage outage cannot be made durable; warning remains available.


if __name__ == '__main__':
    process(sys.argv[1])
