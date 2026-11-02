"""Separate semantic entailment from auditable, unique quote location. No API calls."""
import json
import re
from evidence_assessment import validate_response
from source_summarization_poc import match_quote

RULE='grounded-semantic-quote-v3'
INSTRUCTION='''Compare the literal claim semantically across languages, synonyms and sentence forms, not by word overlap. Do not weaken a claim, substitute a rumor for a video, or replace an official announcement with a staff opinion. One historical denial cannot establish never/always claims. Partial compound support is not full support. Return relevance and stance as usual, plus evidence_coverage (full/partial/insufficient): does the quoted passage itself establish the ENTIRE target assertion, not merely the topic? Return quote_reasoning explaining that entailment, scope, dates and limitations. This is an independent sufficiency check of your selected quote, not a repetition of the verdict. Use insufficient when uncertain. Copy a short contiguous original evidence excerpt; preserve whitespace and punctuation. Backend locates it. excerpt_start/end may be omitted or null; never guess offsets. Other input/context is not evidence.'''


def locate(quote,body):
    if isinstance(quote,str) and quote and body.find(quote)>=0 and body.find(quote,body.find(quote)+1)>=0:
        return dict(status='ambiguous_exact_match',model_quote=quote,source_excerpt=None,quote_start=None,quote_end=None)
    return match_quote(quote,body)


def validate(raw,text,start,field,source,claims):
    obj=json.loads(raw) if isinstance(raw,str) else raw
    if not isinstance(obj,dict):raise ValueError('invalid_response_object')
    # Reuse schema and semantic guards without treating a failed quote as a semantic result.
    semantic=validate_response({**obj,'relevance':'insufficient','verbatim_excerpt':'','excerpt_start':None,'excerpt_end':None},text,start,field,source,claims)
    if obj.get('relevance') not in ('direct','contextual','unrelated','insufficient'):
        raise ValueError('invalid_enum')
    reported={'supports':'Support','refutes':'Contradict'}.get(obj.get('stance'),'Insufficient')
    claim=next((c for c in claims if c['claim_id']==obj.get('claim_id')), {})
    coverage=obj.get('evidence_coverage')
    if coverage not in ('full','partial','insufficient'):coverage='insufficient'
    reasoning=obj.get('quote_reasoning')
    sufficient=(coverage=='full' and isinstance(reasoning,str) and bool(reasoning.strip()) and obj.get('target_scope')=='single' and obj.get('relevance')=='direct' and bool(claim))
    limit=None
    if re.search(r'從未|永遠|任何.*都|\bnever\b|\balways\b',claim.get('claim_text',''),re.I) and reported=='Support':
        sufficient=False;limit='absolute_claim_not_established_by_bounded_article'
    if claim.get('unresolved_subject') or (claim.get('specific_video_origin') and obj.get('source_scope')!='specific_video'):
        sufficient=False;limit='unresolved_subject_or_video_scope'
    match=locate(obj.get('verbatim_excerpt'),source[field])
    verified=match['status'] in ('exact_match','normalized_match')
    if verified and not (start<=match['quote_start']<match['quote_end']<=start+len(text)):
        match={**match,'status':'outside_evaluated_chunk'};verified=False
    relation=reported if sufficient else 'Insufficient'
    semantic.update(semantic_relation=relation,model_reported_relation=reported,evidence_coverage=coverage,
        quote_verification='validated' if verified else 'validation_failed',quote_match=match,
        model_offsets={'start':obj.get('excerpt_start'),'end':obj.get('excerpt_end')},
        quote_reasoning=reasoning,semantic_limitation=limit or (None if sufficient else 'quote_entailment_not_established'),
        alignment_rule=RULE,explanation=str(obj.get('explanation') or '')[:1000])
    if verified:
        corrected={**obj,'verbatim_excerpt':match['source_excerpt'],'excerpt_start':match['quote_start']-start,'excerpt_end':match['quote_end']-start}
        checked=validate_response(corrected,text,start,field,source,claims)
        if checked['stance'] not in ('supports','refutes'):relation='Insufficient'
        semantic.update(checked)
        semantic.update(semantic_relation=relation,quote_verification='validated')
        if relation=='Insufficient':semantic.update(stance='not_established')
    else:
        semantic.update(assessment_status='validation_failed',failure_reason=match['status'],validation_error=match['status'])
    # No quote is required to report semantic insufficiency, but it is not verified evidence.
    if not obj.get('verbatim_excerpt') and reported=='Insufficient':
        semantic.update(assessment_status='validated',failure_reason=None)
    return semantic
