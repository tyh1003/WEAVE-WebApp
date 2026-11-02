"""Source-aware assembly: reviewed article summaries plus legacy Grounding fallback.
No network/LLM calls. Ambiguous Grounding segments remain unavailable.
"""
import copy
import re
from evidence import public_url
from evidence_ablation import parent_fields, content_hash
from evidence_assessment import text_hash

RULE = 'source-aware-grounding-v1'

def plan(parent):
    if parent.get('status') != 'succeeded':
        raise ValueError('A successful parent is required')
    fields = parent_fields(parent)
    retrieve = parent['output_snapshot']['retrieve']
    sources = retrieve.get('sources') or []
    supports = retrieve.get('grounding_supports') or []
    # A replaced K_ext cannot inherit the original Retrieve attribution.
    original = parent.get('experiment_type') in ('baseline', 'input_correction')
    cards, units, lines = [], [], []
    seen_urls = {}
    for source in sources:
        sid, url = source.get('source_id'), source.get('source_url')
        if not isinstance(url,str): continue
        if url in seen_urls:
            seen_urls[url]['grounding_source_ids'].append(sid)
            continue
        card = dict(source_id='S'+str(len(cards)+1), title=source.get('source_title'), url=url,
                    grounding_source_ids=[sid], summary=None, summary_status='unavailable',
                    limitation='No unambiguous complete K_ext sentence attributed to this source.',
                    summary_origin='gemini_grounding_synthesis_not_article_text', url_valid=public_url(url))
        seen_urls[url]=card;cards.append(card)
    for card in cards:
        if not original or not card['url_valid']: continue
        chosen=[]
        for index, support in enumerate(supports):
            refs=support.get('source_ids') or []
            matches=[s for s in sources if s.get('source_id') in refs]
            if not refs or any(sum(s.get('source_id')==ref for s in sources)!=1 for ref in refs):continue
            if {s.get('source_url') for s in matches}!={card['url']}:continue
            text=support.get('text') or ''
            kext=fields['K_ext']
            if not isinstance(text,str) or len(text.strip())<12 or len(text)>1200 or kext.count(text)!=1:continue
            start=kext.index(text);end=start+len(text)
            if start and kext[:start].rstrip()[-1:] not in '.!?。！？':continue
            if not re.search(r'[.!?。！？]$',text.rstrip()):continue
            if re.search(r'\[S\d+\]|"(?:Rc|Rv|K_int|K_ext)"\s*:',text):continue
            if any(u['evidence_text']==text for u in chosen):continue
            chosen.append(dict(source_id=card['source_id'],evidence_text=text,
                evidence_text_hash=text_hash(text),provenance={'field':'K_ext','start':start,'end':end,
                'support_index':index,'grounding_source_ids':refs,'offset_unit':'unicode_code_points'},
                evidence_text_origin='gemini_grounding_synthesis_not_article_text'))
        # One complete attributed segment per card; no generated replacement summary.
        if chosen and len(units)<4:
            unit=chosen[0];line='['+card['source_id']+'] '+unit['evidence_text']
            if sum(len(x)+1 for x in lines)+len(line)>4000:continue
            unit['evidence_unit_id']='summary-'+content_hash([parent['version_id'],unit])
            lines.append(line);units.append(unit)
            card.update(summary=unit['evidence_text'],summary_status='grounding_attributed',
                        limitation='Model synthesis with a single-source citation; not verbatim news or fact verification.')
    kext='\n'.join(lines)
    manifest=dict(schema_version=1,rule=RULE,parent_version_id=parent['version_id'],
        parent_student_fields_hash=content_hash(fields),original_k_ext_hash=text_hash(fields['K_ext']),
        news_cards=cards,units=units,k_ext=kext,k_ext_hash=text_hash(kext),k_ext_length=len(kext),
        limitations=['Grounding attribution does not establish truth or causal source contribution.',
                    'No additional Gemini summary call; ambiguous, partial or cross-field segments are omitted.',
                    'Source-level article ablation is not enabled for model-generated summaries.'])
    manifest['manifest_hash']=content_hash(manifest)
    return manifest

def effective_retrieve(parent,version):
    saved=version['source_aware_manifest']
    if saved.get('rule')=='source-aware-reviewed-summaries-v1':
        from source_summarization import frozen_manifest
        manifest=frozen_manifest(parent,saved)
    else:
        manifest=plan(parent)  # Retain execution compatibility for historical pending manifests.
    if manifest!=version['source_aware_manifest'] or not manifest['units']:
        raise ValueError('Source-aware manifest unavailable or changed')
    data=copy.deepcopy(parent['output_snapshot']['retrieve'])
    data.update(parent_fields(parent))
    data.update(K_ext=manifest['k_ext'],original_K_ext=parent_fields(parent)['K_ext'],
                news_cards=manifest['news_cards'],analysis_id=version['version_id'],run_id=version['version_number'])
    data.pop('source_grounded_origin',None)
    if isinstance(data.get('evidence'),dict):
        data['evidence'].update(analysis_id=version['version_id'],run_id=version['version_number'])
        data['evidence'].pop('assessment',None)
    return data
