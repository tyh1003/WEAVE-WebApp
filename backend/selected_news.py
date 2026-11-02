"""Frozen, server-validated automatic summaries for a Student-only experiment."""
import copy
import json
from automatic_summaries import prepare
from evidence import public_url
from evidence_assessment import assessment_content
from evidence_ablation import parent_fields, content_hash
from source_summarization_poc import digest, match_quote


def assemble(units):
    return '\n\n'.join('['+u['source_id']+'] '+u['title']+'\n'+u['url']+'\n'+u['summary'] for u in units)


def plan(parent, selected, db):
    fields=parent_fields(parent)
    if not isinstance(selected,list) or any(not isinstance(s,dict) or set(s)!={'source_id','article_text_hash','cache_key'} for s in selected):
        raise ValueError('Expected selected source identifiers only')
    units=[]
    if selected:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='automatic_summary_jobs'").fetchone():
            raise ValueError('No saved automatic summaries for this parent')
        row=db.execute('SELECT data FROM automatic_summary_jobs WHERE version=? AND experiment=?',(parent['version_id'],parent['experiment_id'])).fetchone()
        if not row:raise ValueError('No saved automatic summaries for this parent')
        job=json.loads(row[0]);fresh=prepare(parent,parent['output_snapshot']['retrieve'])
        seen=set()
        for identity in selected:
            matches=[r for r in fresh['records'] if all(r.get(k)==v for k,v in identity.items()) and r.get('cache_key')]
            if len(matches)!=1:raise ValueError('Invalid, foreign, stale or ineligible source')
            source=matches[0];key=source['cache_key']
            if key in seen:raise ValueError('Duplicate source selection')
            seen.add(key)
            saved=[r for r in job['records'] if all(r.get(k)==v for k,v in identity.items())]
            if len(saved)!=1 or saved[0]['status']!='completed':raise ValueError('Source summary is not completed')
            saved=saved[0]
            if saved.get('source_manifest')!=source['source_manifest']:raise ValueError('Saved source provenance changed')
            cached=db.execute('SELECT data FROM automatic_summary_cache WHERE key=?',(key,)).fetchone()
            cached=json.loads(cached[0]) if cached else {}
            summary=saved.get('summary')
            if not isinstance(summary,str) or not summary.strip() or cached.get('status')!='completed' or cached.get('summary')!=summary:
                raise ValueError('Missing or stale saved summary')
            q=saved.get('quote_validation') or {}
            body=source['source_manifest']['article_text']
            checked=match_quote(q.get('model_quote'),body)
            if checked['status'] not in ('exact_match','normalized_match') or checked!=q:
                raise ValueError('Saved quote provenance failed validation')
            url=source.get('original_url') if public_url(source.get('original_url')) else source['url']
            if not public_url(url):raise ValueError('Source URL unavailable')
            originals=[s for s in parent['output_snapshot']['retrieve']['evidence']['sources'] if s.get('source_id')==source['source_id']]
            if len(originals)!=1:raise ValueError('Parent source identity ambiguous')
            original=originals[0]
            units.append(dict(identity,title=source.get('title') or original.get('source_title') or '文章標題未提供',url=url,
                summary=summary,summary_hash=digest(summary),source_manifest=source['source_manifest'],quote_validation=q,
                semantic_verified=False,human_approved=False))
    manifest=dict(rule='selected-automatic-news-v1',parent_version_id=parent['version_id'],
        parent_fields_hash=content_hash(fields),units=units,k_ext=assemble(units),
        order='explicit selected identifiers in displayed card order',semantic_verified=False)
    manifest['manifest_hash']=content_hash(manifest)
    return manifest


def effective_retrieve(parent, version):
    m=version['selected_news_manifest']
    if m['manifest_hash']!=content_hash({k:v for k,v in m.items() if k!='manifest_hash'}) or m['k_ext']!=assemble(m['units']):
        raise ValueError('Frozen selected-news manifest mismatch')
    fields=parent_fields(parent)
    if m['parent_version_id']!=parent['version_id'] or m['parent_fields_hash']!=content_hash(fields):raise ValueError('Parent input mismatch')
    for unit in m['units']:
        matches=[s for s in parent['output_snapshot']['retrieve']['evidence']['sources'] if s.get('source_id')==unit['source_id']]
        if len(matches)!=1:raise ValueError('Parent source identity ambiguous')
        _,body=assessment_content(matches[0])
        if not body or digest(body)!=unit['article_text_hash'] or digest(unit['summary'])!=unit['summary_hash']:
            raise ValueError('Frozen source content mismatch')
    data=copy.deepcopy(parent['output_snapshot']['retrieve'])
    fields['K_ext']=m['k_ext'];data.update(fields,analysis_id=version['version_id'],run_id=version['version_number'])
    data.pop('source_grounded_origin',None)
    if isinstance(data.get('evidence'),dict):
        data['evidence'].update(analysis_id=version['version_id'],run_id=version['version_number'],retrieval_parent_version_id=parent['version_id'])
        data['evidence'].pop('assessment',None)
    return data
