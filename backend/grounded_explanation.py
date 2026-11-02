"""Post-hoc Student reason checks, restricted to frozen approved input sources."""
import re
from dataclasses import replace
from evidence_assessment import text_hash, assessment_content
from evidence_ablation import content_hash
from version_assessment import describe as assess
from source_summarization import RULE, eligible
from source_summarization_poc import validate_input
from grounded_alignment import RULE as ALIGNMENT_RULE, INSTRUCTION as ALIGNMENT_INSTRUCTION, validate as validate_alignment


def decompose(reason):
    """Literal clause boundaries only: no subject rewriting or generated claims."""
    claims=[];excluded=[]
    for match in re.finditer(r'[^，,；;。！？.!?\n]+',reason):
        text=match.group().strip()
        start=match.start()+len(match.group())-len(match.group().lstrip())
        provenance=dict(field='reason',start=start,end=start+len(text),original_fragment=text,original_reason=reason,offset_unit='unicode_code_points')
        if not text: continue
        if re.match(r'^(因此|所以|故|綜上|Therefore\b|Thus\b)',text,re.I) or len(text)<8:
            excluded.append(dict(text=text,provenance=provenance,reason='conclusion_or_short_fragment'));continue
        cid='atomic-'+text_hash(str(start)+text)[:20]
        claims.append(dict(claim_id=cid,reason_id=cid,claim_text=text,claim_provenance=provenance,
            unresolved_subject=bool(re.match(r'^(旨在|意在|並且|並提供|且提供|which\b|designed to\b)',text,re.I)),
            specific_video_origin=bool(re.search(r'(影片|短影音|video).*(源自|來自|originat|from)',text,re.I))))
    return claims,excluded


def prepare(version, config):
    manifest = version.get('source_aware_manifest') or {}
    if manifest.get('rule') != RULE or manifest.get('manifest_hash') != content_hash({k:v for k,v in manifest.items() if k != 'manifest_hash'}):
        raise ValueError('需要具有已核准摘要 manifest 的 Source-aware 版本')
    value = manifest['summary_input']
    validate_input(value)
    fields = version.get('input_snapshot', {}).get('student_fields', {})
    units = manifest['units']
    assembled = '\n'.join('['+u['source_id']+'] '+u['evidence_text'] for u in units)
    if not units or assembled != manifest['k_ext'] or fields.get('K_ext') != assembled:
        raise ValueError('來源 manifest 與版本有效 K_ext 不一致')
    student = version['output_snapshot']['student']
    reason = student.get('reason')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('Student 原始理由不可用')
    claims, excluded = decompose(reason)
    if not claims: raise ValueError('沒有可核查的 Student 理由片段')
    sources=[]
    for unit in units:
        sid=unit['source_id']
        source=next(s for s in value['sources'] if s['source_id']==sid)
        row=next(r for r in manifest['validation']['summaries'] if r['source_id']==sid)
        if (manifest['review_snapshot'].get(sid,{}).get('decision')!='approved' or not eligible(manifest['validation'],row)
            or row['summary']!=unit['evidence_text'] or source['article_text_hash']!=unit['article_text_hash']):
            raise ValueError('來源未核准或摘要與保存正文不一致')
        s=dict(source,source_url=source['url'],resolved_url=source['url'],article_title=source['title'],
               retrieval_status='fetched',source_aliases=[sid],assessment_article_id=source['article_text_hash'])
        if not assessment_content(s)[1]: raise ValueError('來源缺少可核對正文')
        sources.append(s)
    evidence=dict(analysis_id=version['version_id'],student_verdict=student.get('pred_label'),student_rationale=reason,
        alignment_rule=ALIGNMENT_RULE,input_manifest_hash=manifest['manifest_hash'],decomposition_rule='literal-clauses-v2',excluded_segments=excluded,claims=claims[:3],sources=sources,
        reasons=[dict(reason_id=c['claim_id'],reason_text=c['claim_text']) for c in claims[:3]])
    plan=dict(claim_count=min(3,len(claims)),omitted_claims=max(0,len(claims)-3),article_count=len(sources),
        pair_count=min(3,len(claims))*len(sources),max_calls=config.max_calls,max_cost_usd=config.max_cost_usd,
        model_name=config.model_name,max_source_chars=config.max_source_chars,max_output_tokens=config.max_output_tokens)
    return evidence,plan


def describe(version,root,config,provider=None,execute=False,retry_of=None):
    config=replace(config,max_sources=3,max_source_chars=min(3000,config.max_source_chars),chunk_chars=3000)
    transport=provider
    if provider:
        def transport(payload,**kwargs):
            # Context is untrusted and is never substituted for the article evidence.
            manifest=version['source_aware_manifest']
            unit=next(u for u in manifest['units'] if u['source_id']==payload['source_id'])
            student=version['output_snapshot']['student']
            payload['system_instruction'] += '\n'+ALIGNMENT_INSTRUCTION
            payload['grounded_alignment_rule']=ALIGNMENT_RULE
            payload['unverified_student_context']={'verdict':student.get('pred_label'),'rationale':student.get('reason'),
                'approved_ai_summary_not_evidence':unit['evidence_text']}
            return provider(payload,**kwargs)
    try:
        result=assess(version,root,config,transport,execute,prepare_fn=prepare,retry_of=retry_of,response_validator=validate_alignment)
    except (ValueError,KeyError,StopIteration,TypeError):
        return dict(available=False,status='unavailable',explanation='需要已核准、正文可核對且與有效 K_ext 一致的 Source-aware 版本。',items=[])
    claims={c['claim_id']:c for c in result['claims']}
    sources={s['source_id']:s for s in result['sources']}
    items=[]
    for row in (result.get('assessment') or {}).get('records',[]):
        source=sources[row['source_id']]; claim=claims.get(row.get('claim_id') or row['reason_id'])
        restricted = claim.get('unresolved_subject') or (claim.get('specific_video_origin') and row.get('source_scope')!='specific_video')
        direct=not restricted and row.get('quote_validation')=='verified' and row['relation'] in ('supports','refutes')
        relation=('Support' if row['relation']=='supports' else 'Contradict') if direct else 'Insufficient Evidence'
        items.append(dict(source_id=source['source_id'],title=source['article_title'],url=source['source_url'],
            claim_id=claim['claim_id'],claim=claim['claim_text'],claim_provenance=claim['claim_provenance'],unresolved_subject=claim.get('unresolved_subject',False),relation=relation,quote=row.get('verbatim_excerpt') if direct else None,
            excerpt_provenance=row.get('excerpt_provenance'),article_text_hash=source['article_text_hash'],
            explanation=row.get('explanation'),assessment_status=row['assessment_status'],coverage=row.get('coverage'),
            content_quality=source['content_quality'],failure_reason=row.get('failure_reason'),validation_error=row.get('validation_error'),semantic_relation=row.get('semantic_relation','Insufficient'),quote_verification=row.get('quote_verification','validation_failed'),evidence_coverage=row.get('evidence_coverage','insufficient'),quote_match=row.get('quote_match'),quote_reasoning=row.get('quote_reasoning'),semantic_limitation=row.get('semantic_limitation')))
    supported={i['claim_id'] for i in items if i['relation']=='Support'}
    result['support_summary']=dict(supported_claims=len(supported),evaluated_claims=len(claims),partial=bool(supported),notice='部分主張獲支持；不代表整段 Student Rationale 已驗證' if supported else '尚無足夠來源支持此判斷理由')
    result['items']=items
    result['student']=version['output_snapshot']['student']
    return result
