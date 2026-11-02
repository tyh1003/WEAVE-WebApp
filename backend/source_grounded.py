"""Deterministic, verbatim external input assembly. No model or network calls."""
import copy
import json
from urllib.parse import urlsplit
from evidence import public_url
from evidence_assessment import source_content, text_hash
from evidence_ablation import parent_fields, content_hash

RULE = {'version':'source-grounded-v1', 'max_articles':2, 'max_article_chars':1200,
        'max_k_ext_chars':3000, 'offset_unit':'unicode_code_points',
        'selection':'Sort by resolved URL, body hash, source ID; first contiguous body prefix. No semantic assessments or Student stance used.'}


def plan(parent):
    if parent.get('status') != 'succeeded':
        raise ValueError('A successful parent is required')
    fields = parent_fields(parent)
    sources = (parent['output_snapshot']['retrieve'].get('evidence') or {}).get('sources', [])
    records, candidates = [], []
    for index, source in enumerate(sources):
        _, body = source_content(source)
        record = {k:source.get(k) for k in ('source_id','article_id','original_url','source_url','resolved_url','canonical_url','article_title','retrieval_status','extraction_status')}
        record.update(source_index=index, selection_status='unavailable', selection_reason='No verified article body', article_text_hash=text_hash(body) if body else None)
        records.append(record)
        if not body:
            continue
        if not source.get('source_id') or sum(s.get('source_id')==source['source_id'] for s in sources)!=1:
            record['selection_reason']='Missing or ambiguous source_id';continue
        url = source.get('resolved_url') or source.get('source_url')
        if not public_url(url):
            record['selection_reason']='No safe saved article URL';continue
        canonical = source.get('canonical_url')
        canonical = canonical if public_url(canonical) and urlsplit(canonical).hostname==urlsplit(url).hostname else None
        identity = (canonical or url).split('#',1)[0]
        keys = {'hash:'+text_hash(body), 'url:'+identity}
        if source.get('article_id'):
            keys.add('id:'+str(source['article_id']))
        candidates.append(dict(source=source,body=body,record=record,keys=keys,identity=identity))
    candidates.sort(key=lambda c:(c['identity'],text_hash(c['body']),c['source']['source_id']))
    # Union groups so different URLs and transitive canonical/body aliases deduplicate.
    groups=[]
    for candidate in candidates:
        matching=[g for g in groups if g['keys'] & candidate['keys']]
        merged={'keys':set(candidate['keys']), 'members':[candidate]}
        for group in matching:
            merged['keys'].update(group['keys']);merged['members'].extend(group['members']);groups.remove(group)
        merged['members'].sort(key=lambda c:(c['identity'],text_hash(c['body']),c['source']['source_id']))
        groups.append(merged)
    groups.sort(key=lambda g:(g['members'][0]['identity'],text_hash(g['members'][0]['body'])))
    units, segments, assembled = [], [], ''
    for group in groups:
        candidate=group['members'][0]; source=candidate['source'];body=candidate['body']
        article_id='article-'+text_hash(candidate['identity'])
        for member in group['members']:
            member['record'].update(selection_status='not_selected',selection_reason='Duplicate article; representative '+source['source_id'])
        record=candidate['record']
        if len(units)>=RULE['max_articles']:
            record['selection_reason']='Article count limit';continue
        separator='\n\n' if assembled else ''
        marker='[SOURCE:'+article_id+']\n'
        length=min(len(body),RULE['max_article_chars'],RULE['max_k_ext_chars']-len(assembled)-len(separator)-len(marker))
        excerpt=body[:max(0,length)].rstrip()
        if not excerpt:
            record['selection_reason']='Total length limit or empty prefix';continue
        uid='unit-'+content_hash([parent['version_id'],source['source_id'],text_hash(body),0,len(excerpt)])
        unit=dict(evidence_unit_id=uid,source_id=source['source_id'],article_id=article_id,
            source_aliases=[m['source']['source_id'] for m in group['members'] if m['body']==body],
            article_source_ids=[m['source']['source_id'] for m in group['members']],
            original_url=source.get('original_url') or source.get('source_url'), resolved_url=source.get('resolved_url'),
            canonical_url=source.get('canonical_url'),article_title=source.get('article_title'),
            article_text_hash=text_hash(body),evidence_text=excerpt,evidence_text_hash=text_hash(excerpt),
            evidence_text_origin='saved_article_text_verbatim',extraction_status=source.get('extraction_status') or 'saved_verified_article',
            selection_status='selected',selection_reason='Deterministic prefix under fixed limits',parent_version_id=parent['version_id'],
            provenance={'field':'article_text','start':0,'end':len(excerpt),'article_length':len(body),'offset_unit':'unicode_code_points',
                        'original_article_id':source.get('article_id'),'source_index':record['source_index']})
        for kind,text in [('separator',separator),('marker',marker),('article_text',excerpt)]:
            if not text:continue
            segments.append(dict(kind=kind,origin='publisher_text' if kind=='article_text' else 'assembler',
                evidence_unit_id=uid,start=len(assembled),end=len(assembled)+len(text),text_hash=text_hash(text)))
            assembled+=text
        units.append(unit);record.update(selection_status='selected',selection_reason=unit['selection_reason'],evidence_unit_id=uid)
    manifest=dict(schema_version=1,parent_version_id=parent['version_id'],rule=RULE,units=units,selection_records=records,
        eligible_article_count=len(groups),k_ext=assembled,k_ext_hash=text_hash(assembled),k_ext_length=len(assembled),segments=segments,
        student_formatter={'generated_prefix':'- ','origin':'Student knowledge-list formatter','raw_k_ext_offset_in_formatted_knowledge':2},
        parent_student_fields_hash=content_hash(fields),
        limitations=['A new research baseline, not retroactive V1 source attribution.',
                    'Rc/Rv/K_int are reused and may contain external information; no claim of complete source isolation.',
                    'Article prefixes may omit relevant context. Source-level ablation remains disabled.'])
    manifest['manifest_hash']=content_hash(manifest)
    return manifest


def effective_retrieve(parent, version):
    manifest=plan(parent)
    if manifest!=version['source_grounded_manifest'] or not manifest['units']:
        raise ValueError('Source-grounded manifest differs from frozen parent inputs')
    fields=parent_fields(parent);fields['K_ext']=manifest['k_ext']
    data=copy.deepcopy(parent['output_snapshot']['retrieve']);data.update(fields)
    data.update(analysis_id=version['version_id'],run_id=version['version_number'])
    data['source_grounded_origin']={'version_id':version['version_id'],'manifest_hash':manifest['manifest_hash']}
    data.pop('ablation',None)
    evidence=data.get('evidence')
    if isinstance(evidence,dict):
        evidence.update(analysis_id=version['version_id'],run_id=version['version_number'],retrieval_parent_version_id=parent['version_id'])
        evidence.pop('assessment',None)
        for source in evidence.get('sources',[]):
            source['student_input_evidence_units']=[u['evidence_unit_id'] for u in manifest['units'] if source['source_id'] in u['source_aliases']]
            source['student_input_status']='manifest_prefix_in_K_ext' if source['student_input_evidence_units'] else 'parent_inventory_only'
    return data
