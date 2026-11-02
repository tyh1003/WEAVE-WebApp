"""Version-scoped source summarization/review integration; no import-time API calls.
Uses the PoC prompt, schema, selector, provider and quote validator unchanged.
"""
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import source_summarization_poc as poc
from evidence import public_url
from evidence_ablation import parent_fields, content_hash

RULE='source-aware-reviewed-summaries-v1'
GENERATION_SETTINGS={'temperature':0,'thinking_level':'MINIMAL','timeout_ms':60000,'retry_attempts':1,'calls_per_attempt':1}

def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS source_summary_attempts (id TEXT PRIMARY KEY, cache_key TEXT NOT NULL, number INTEGER NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(cache_key,number))')
    db.execute('CREATE TABLE IF NOT EXISTS source_summary_reviews (id TEXT PRIMARY KEY, experiment TEXT NOT NULL, parent TEXT NOT NULL, attempt TEXT NOT NULL, source TEXT NOT NULL, decision TEXT NOT NULL, created_at TEXT NOT NULL)')

@contextmanager
def transaction(root):
    db=sqlite3.connect(Path(root)/'research.sqlite3',timeout=30)
    try:
        db.execute('BEGIN IMMEDIATE');initialize(db);yield db;db.commit()
    except Exception:db.rollback();raise
    finally:db.close()

def cache_key(value):
    # Reuse within an experiment across versions only when source input and settings match.
    return poc.digest({'experiment':value['experiment_id'],'sources':[{k:s[k] for k in ('source_id','article_text_hash','url','content_quality')} for s in value['sources']],
        'model':value['model'],'prompt':value['prompt'],'schema':value['response_schema'],
        'max_output_tokens':value['max_output_tokens'],'quote_rule':poc.QUOTE_RULE,'provider_settings':GENERATION_SETTINGS})

def latest(db,key):
    row=db.execute('SELECT data FROM source_summary_attempts WHERE cache_key=? ORDER BY number DESC LIMIT 1',(key,)).fetchone()
    return json.loads(row[0]) if row else None

def read_reviews(db,parent,attempt):
    records=db.execute('SELECT id,source,decision,created_at FROM source_summary_reviews WHERE experiment=? AND parent=? AND attempt=? ORDER BY rowid',
        (parent['experiment_id'],parent['version_id'],attempt)).fetchall()
    return {r[1]:dict(review_id=r[0],decision=r[2],created_at=r[3],reviewer='experiment_access_token_holder',semantic_verified=False) for r in records}

def eligible(result,row):
    return (result.get('format_validation',{}).get('status')=='passed' and
        result.get('source_id_validation',{}).get('status')=='passed' and row.get('format_status')=='passed' and
        row.get('source_id_status')=='passed' and row.get('quote_validation',{}).get('status') in ('exact_match','normalized_match'))

def assemble(parent,value,result,reviews,attempt_id):
    units=[];cards=[];lines=[]
    for source in value['sources']:
        sid=source['source_id'];row=next((r for r in result.get('summaries',[]) if r['source_id']==sid),{})
        checked=eligible(result,row);review=reviews.get(sid,{'decision':'manual_review_required'})
        card=dict(source_id=sid,title=source['title'],url=source['url'],url_valid=public_url(source['url']),
            summary=row.get('summary') if isinstance(row.get('summary'),str) else None,
            summary_status='ai_generated' if row.get('summary') else 'unavailable',
            quote_validation=row.get('quote_validation',{'status':'unavailable'}),
            content_quality=source['content_quality'],can_review=checked,review=review,semantic_verified=False)
        cards.append(card)
        if checked and review['decision']=='approved':
            text=row['summary'];unit=dict(source_id=sid,evidence_unit_id='summary-'+poc.digest([source['article_text_hash'],sid,text]),
                evidence_text=text,evidence_text_hash=poc.digest(text),article_text_hash=source['article_text_hash'],
                article_id=source['article_id'],url=source['url'],grounding_source_id=source['grounding_source_id'],
                evidence_text_origin='ai_generated_human_approved_not_fact_verified',quote_validation=row['quote_validation'],review=review)
            units.append(unit);lines.append('['+sid+'] '+text)
    text='\n'.join(lines)
    manifest=dict(rule=RULE,schema_version=1,parent_version_id=parent['version_id'],
        parent_student_fields_hash=content_hash(parent_fields(parent)),units=units,news_cards=cards,
        k_ext=text,k_ext_hash=poc.digest(text),k_ext_length=len(text),summary_attempt_id=attempt_id,
        summary_input=value,validation=result,review_snapshot=reviews,provider_settings=GENERATION_SETTINGS,
        limitations=['AI generated summaries; approval is a user review, not independent fact verification.',
                    'Only saved partial/full article text used; pretrained knowledge cannot be removed.',
                    'Source-level ablation remains unavailable for these summaries.'],semantic_verified=False)
    manifest['manifest_hash']=content_hash(manifest)
    return manifest

def frozen_manifest(parent,manifest):
    value=poc.select(parent)
    if value!=manifest['summary_input']:raise ValueError('Frozen summary input differs from parent')
    rebuilt=assemble(parent,value,manifest['validation'],manifest['review_snapshot'],manifest['summary_attempt_id'])
    if rebuilt!=manifest or not rebuilt['units']:raise ValueError('Frozen reviewed manifest mismatch')
    return rebuilt

def state(parent,root,db=None):
    if db is None:
        with transaction(root) as connection:return state(parent,root,connection)
    from source_aware import plan as legacy_plan
    fallback=legacy_plan(parent)['news_cards']
    try:value=poc.select(parent)
    except ValueError as error:
        return dict(available=False,generation_available=False,summary_status='unavailable',error=str(error),
            fallback_cards=fallback,manifest={'units':[],'news_cards':[],'k_ext':''})
    key=cache_key(value);attempt=latest(db,key)
    result=poc.validate_output(attempt['raw_output'],value) if attempt and 'raw_output' in attempt else {}
    reviews=read_reviews(db,parent,attempt['id']) if attempt else {}
    manifest=assemble(parent,value,result,reviews,attempt['id'] if attempt else None)
    selected_urls={s['original_url'] for s in value['sources']}
    selected_ids={s['grounding_source_id'] for s in value['sources']}
    fallback=[c for c in fallback if c['url'] not in selected_urls and not selected_ids.intersection(c['grounding_source_ids'])]
    return dict(available=bool(manifest['units']),generation_available=True,cache_key=key,
        summary_status=attempt['status'] if attempt else 'not_generated',attempt_id=attempt['id'] if attempt else None,
        retry_available=bool(attempt and (attempt['status'] in ('failed','validation_failed') or
            (attempt['status']=='running' and time.time()-attempt['started_epoch']>180))),
        error=attempt.get('error') if attempt else None,manifest=manifest,fallback_cards=fallback,
        review_revision=poc.digest(reviews),plan={'article_count':len(value['sources']),'article_chars':sum(len(s['article_text']) for s in value['sources']),
            'model':value['model'],'max_calls':1,'max_output_tokens':value['max_output_tokens'],
            'cost_note':'One additional paid model request; no Grounding or Student. Actual fees depend on token usage.'},
        attempt_history=[{'id':r[0],'status':r[1]} for r in db.execute('SELECT id,status FROM source_summary_attempts WHERE cache_key=? ORDER BY number',(key,))])

def generate(parent,root,payload,provider=None):
    if payload.get('confirm_cost') is not True:raise ValueError('Explicit Gemini cost confirmation required')
    value=poc.select(parent);key=cache_key(value)
    if payload.get('cache_key')!=key:raise ValueError('Source preview changed; reload before generating')
    with transaction(root) as db:
        old=latest(db,key)
        if old:
            can_retry=old['status'] in ('failed','validation_failed') or (old['status']=='running' and time.time()-old['started_epoch']>180)
            if not can_retry or payload.get('retry_of')!=old['id']:return state(parent,root,db)
            # Explicit retry acknowledges possible charge for a timed-out/interrupted prior request.
            if payload.get('acknowledge_retry_cost') is not True:raise ValueError('Explicit retry cost acknowledgement required')
        attempt=dict(id=uuid4().hex,cache_key=key,number=old['number']+1 if old else 1,status='running',
            input=value,parent_version_id=parent['version_id'],started_epoch=time.time(),semantic_verified=False,provider_settings=GENERATION_SETTINGS)
        db.execute('INSERT INTO source_summary_attempts VALUES (?,?,?,?,?)',(attempt['id'],key,attempt['number'],'running',json.dumps(attempt)))
    try:
        poc.validate_input(value)
        raw,response=(provider or poc.live_provider)(value)
        result=poc.validate_output(raw,value)
        attempt.update(raw_output=raw,model_response=response,validation=result,
            status='succeeded' if result['status']=='structural_and_quote_checks_passed' else 'validation_failed')
    except Exception as error:
        # Do not persist/display provider exception text, which can contain credentials or request URLs.
        attempt.update(status='failed',error='Summary provider failed: '+type(error).__name__)
    attempt['finished_at']=datetime.now(timezone.utc).isoformat()
    with transaction(root) as db:
        db.execute('UPDATE source_summary_attempts SET status=?,data=? WHERE id=?',
            (attempt['status'],json.dumps(attempt,ensure_ascii=False),attempt['id']))
        return state(parent,root,db)

def review(parent,root,payload):
    if payload.get('decision') not in ('approved','excluded'):raise ValueError('Expected approved or excluded')
    with transaction(root) as db:
        current=state(parent,root,db)
        if not current.get('attempt_id') or payload.get('attempt_id')!=current['attempt_id'] or payload.get('review_revision')!=current['review_revision']:
            raise ValueError('Review changed; reload this version')
        card=next((c for c in current['manifest']['news_cards'] if c['source_id']==payload.get('source_id')),None)
        if not card or (payload['decision']=='approved' and not card['can_review']):raise ValueError('Summary did not pass validation')
        if card['review']['decision']!=payload['decision']:
            db.execute('INSERT INTO source_summary_reviews VALUES (?,?,?,?,?,?,?)',(uuid4().hex,parent['experiment_id'],parent['version_id'],
                current['attempt_id'],card['source_id'],payload['decision'],datetime.now(timezone.utc).isoformat()))
        return state(parent,root,db)
