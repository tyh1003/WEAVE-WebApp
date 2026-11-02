"""Explicit version-scoped postprocessing; never writes a version or model input."""
import copy
import json
import re
from dataclasses import asdict, replace
from pathlib import Path

from evidence_assessment import (AssessmentConfig, PROMPT_VERSION, assess_evidence,
                                 evidence_digest, assessment_content, text_hash)


CONFIG = AssessmentConfig(enabled=True, max_sources=2, max_calls=6, max_cost_usd=0.06)


def prepare(version, config=CONFIG):
    student = version['output_snapshot']['student']
    evidence = copy.deepcopy(student.get('evidence') or {})
    evidence.update(schema_version=1, video_id=student.get('vid'),
                    analysis_id=version['version_id'], run_id=student.get('run_id', evidence.get('run_id')))
    evidence.setdefault('sources', (version['output_snapshot']['retrieve'].get('evidence') or {}).get('sources', []))
    # Deterministic original-text candidates, not generated facts or Student verdicts.
    fields = version['output_snapshot'].get('retrieve') or {}
    candidates = []
    per_field = []
    for field in ('Rc','Rv','K_ext'):
        value = fields.get(field)
        values = value if isinstance(value,list) else [value]
        group = []
        for item_index, value in enumerate(values):
            if not isinstance(value,str): continue
            for match in re.finditer(r'[^。！？.!?\n]+[。！？.!?]?', value):
                text = match.group().strip()
                if len(text) < 8 or text.lower() in ('real','fake','true','false'): continue
                a = match.start()+len(match.group())-len(match.group().lstrip())
                cid = 'field-'+text_hash(json.dumps([field,item_index,a,text],ensure_ascii=False))[:20]
                group.append(dict(claim_id=cid,reason_id=cid,claim_text=text,version_id=version['version_id'],
                    claim_provenance=dict(field=field,start=a,end=a+len(text),item_index=item_index if isinstance(fields.get(field),list) else None,offset_unit='unicode_code_points'),
                    limitation='Unverified original field segment; atomicity is not established. Mixed assertions require insufficient, not a single verdict.'))
        per_field.append(group)
    # Give all three input fields a chance before taking additional sentences.
    for index in range(max((len(g) for g in per_field),default=0)):
        candidates.extend(g[index] for g in per_field if index<len(g))
    claims = candidates
    evidence['claims'] = claims
    evidence['reasons'] = [dict(reason_id=c['claim_id'],reason_text=c['claim_text']) for c in claims[:3]]
    groups = {}
    for source in evidence['sources']:
        _, text = assessment_content(source)
        # Identical verified bodies share one assessment; preserve all original IDs.
        key = text_hash(text) if text else 'unavailable:'+str(source.get('source_id'))
        groups.setdefault(key, []).append(source)
    sources = []
    for key, members in groups.items():
        source = copy.deepcopy(members[0])
        source['source_aliases'] = [s.get('source_id') for s in members]
        source['assessment_article_id'] = key
        sources.append(source)
    sources.sort(key=lambda s: (not bool(assessment_content(s)[1]), not bool(s.get('article_title')), not bool(s.get('published_date'))))
    evidence['sources'] = sources
    articles = sum(bool(assessment_content(s)[1]) for s in sources)
    # A cap is a selection budget, never a claim of semantic relevance.
    plan = dict(claim_count=len(claims), article_count=articles,
                pair_count=min(len(evidence['reasons']),3)*min(articles,config.max_sources),
                max_calls=config.max_calls, max_cost_usd=config.max_cost_usd,
                model_name=config.model_name, max_source_chars=config.max_source_chars, max_output_tokens=config.max_output_tokens,
                selection='Up to 3 unverified Rc/Rv/K_ext segments (interleaved fields), 2 saved articles; selection is not semantic evidence.',
                omitted_claims=max(0,len(claims)-3))
    return evidence, plan


def describe(version, root, config=CONFIG, provider=None, execute=False, prepare_fn=None, retry_of=None, response_validator=None):
    config = replace(config, max_sources=min(config.max_sources,3 if prepare_fn else 2), max_calls=min(config.max_calls,6),
                     max_cost_usd=min(config.max_cost_usd,0.06))
    evidence, plan = (prepare_fn or prepare)(version, config)
    key = text_hash(json.dumps(dict(experiment=version['experiment_id'], version=version['version_id'],
        digest=evidence_digest(evidence), config=asdict(config), prompt=PROMPT_VERSION),sort_keys=True))
    directory = Path(root)/('grounded_explanations' if prepare_fn else 'evidence_assessments')
    base_path = directory/(key+'.json')
    def attempts():
        return ([base_path] if base_path.exists() else []) + sorted(directory.glob(key+'.retry-*.json'), key=lambda p:int(p.stem.rsplit('-',1)[1]))
    history=attempts() if prepare_fn else ([base_path] if base_path.exists() else [])
    path=history[-1] if history else base_path
    previous=json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    retry=bool(prepare_fn and execute and retry_of==path.stem and previous and previous.get('status')!='complete')
    previous_path=path
    if retry: path=directory/(key+'.retry-'+str(len(history))+'.json')
    response = dict(plan=plan, available=bool(provider and config.model_name and config.enabled),
                    status='ready' if provider and config.model_name and config.enabled else 'unavailable',
                    explanation='Live assessment model and verified pricing are not configured.' if not provider or not config.model_name else None,
                    evidence_snapshot_hash=key, assessment=None, attempt_id=path.stem,
                    retry_available=bool(previous and previous.get('status')!='complete'), attempt_history=[p.stem for p in history],
                    claims=evidence['claims'][:3], sources=evidence['sources'],
                    pricing_note='USD reservation is a planning limit, not a provider billing guarantee.')
    if path.exists():
        response.update(status='cached', assessment=json.loads(path.read_text(encoding='utf-8')))
        return response
    if not execute or not response['available']:
        return response
    directory.mkdir(parents=True,exist_ok=True)
    lock = directory/(key+'.lock')
    try:
        handle = lock.open('x')
    except FileExistsError:
        return {**response, 'status':'running', 'explanation':'Assessment already running; if interrupted, operator review is required before retry.'}
    completed = False
    try:
        handle.close()
        # A stale/repeated retry request must reuse the completed successor.
        newer=attempts() if prepare_fn else []
        if retry and newer and newer[-1]!=previous_path:
            path=newer[-1]
            response['attempt_id']=path.stem
        if path.exists():
            completed = True
            return {**response, 'status':'cached', 'assessment':json.loads(path.read_text(encoding='utf-8'))}
        assessment = assess_evidence(evidence,config,provider,response_validator=response_validator)
        assessment.update(experiment_id=version['experiment_id'], version_id=version['version_id'],
            evidence_snapshot_hash=key, claims=evidence['claims'], targets=evidence['reasons'], source_aliases={s['source_id']:s['source_aliases'] for s in evidence['sources']})
        for row in assessment['records']:
            source = next(s for s in evidence['sources'] if s['source_id']==row['source_id'])
            row['article_id'] = source['assessment_article_id']
            row['evidence_snapshot_hash'] = key
            row['claim_id'] = row.get('claim_id') or row['reason_id']
            row['relation'] = ('unavailable' if not assessment_content(source)[1] else
                row['stance'] if row['assessment_status']=='validated' and row['stance'] in ('supports','refutes') else
                'background' if row['assessment_status']=='validated' and row['relevance']=='contextual' else 'insufficient')
            row['quote_validation'] = 'verified' if row.get('excerpt_provenance') else 'not_verified'
        # Exclusive cache write, immutable model snapshots remain untouched.
        temporary = path.with_suffix('.tmp')
        with temporary.open('x',encoding='utf-8') as out:
            json.dump(assessment,out,ensure_ascii=False,indent=2)
        temporary.rename(path)
        completed = True
        response.update(status=assessment['status'],assessment=assessment,retry_available=assessment['status']!='complete')
        return response
    finally:
        # Storage/process failure must not permit silent repeat billing.
        if completed:
            lock.unlink(missing_ok=True)
