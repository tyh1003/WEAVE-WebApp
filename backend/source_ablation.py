"""Verified unit removal from a frozen source-grounded parent. No IO or models."""
import copy
from evidence_ablation import content_hash, parent_fields
from evidence_assessment import source_content, text_hash
from source_grounded import RULE


def assemble(units):
    text, segments = '', []
    for unit in units:
        for kind, value in [('separator', '\n\n' if text else ''), ('marker', '[SOURCE:'+unit['article_id']+']\n'), ('article_text', unit['evidence_text'])]:
            if not value: continue
            segments.append(dict(kind=kind, origin='publisher_text' if kind=='article_text' else 'assembler', evidence_unit_id=unit['evidence_unit_id'], start=len(text), end=len(text)+len(value), text_hash=text_hash(value)))
            text += value
    return text, segments


def validated_manifest(parent):
    if parent.get('status') != 'succeeded' or parent.get('experiment_type') != 'source_grounded_baseline':
        raise ValueError('Mode A requires a successful source_grounded_baseline')
    fields = parent_fields(parent)
    m = copy.deepcopy(parent.get('source_grounded_manifest') or {})
    digest = m.pop('manifest_hash', None)
    if digest != content_hash(m) or m.get('rule') != RULE or not m.get('units'):
        raise ValueError('Invalid or unsupported source manifest')
    m['manifest_hash'] = digest
    if parent['output_snapshot'].get('source_grounded_manifest') != m:
        raise ValueError('Snapshot manifest mismatch')
    units=m['units']
    if len({u['evidence_unit_id'] for u in units})!=len(units) or len({u['article_id'] for u in units})!=len(units):
        raise ValueError('Ambiguous evidence units')
    sources=parent['output_snapshot']['retrieve'].get('evidence',{}).get('sources',[])
    for u in units:
        matches=[s for s in sources if s.get('source_id')==u['source_id']]
        if len(matches)!=1: raise ValueError('Missing or ambiguous saved source')
        _, body=source_content(matches[0]); pos=u['provenance']
        if not body or text_hash(body)!=u['article_text_hash'] or body[pos['start']:pos['end']]!=u['evidence_text'] or text_hash(u['evidence_text'])!=u['evidence_text_hash']:
            raise ValueError('Evidence unit does not match saved article')
    text,segments=assemble(units)
    if text!=fields['K_ext'] or text!=m['k_ext'] or text_hash(text)!=m['k_ext_hash'] or segments!=m['segments']:
        raise ValueError('Parent effective input differs from manifest assembly')
    return m


def plan(parent, unit_ids):
    m=validated_manifest(parent)
    if not isinstance(unit_ids,list) or not unit_ids or any(not isinstance(x,str) for x in unit_ids):
        raise ValueError('Select at least one evidence unit')
    chosen=set(unit_ids); known={u['evidence_unit_id'] for u in m['units']}
    if not chosen<=known: raise ValueError('Unknown evidence unit ID')
    removed=[u for u in m['units'] if u['evidence_unit_id'] in chosen]
    retained=[u for u in m['units'] if u['evidence_unit_id'] not in chosen]
    text,segments=assemble(retained)
    fields=parent_fields(parent)
    manifest=dict(rule=m['rule'], parent_manifest_hash=m['manifest_hash'], parent_k_ext_hash=m['k_ext_hash'], units=retained, segments=segments, k_ext=text, k_ext_hash=text_hash(text), k_ext_length=len(text))
    manifest['manifest_hash']=content_hash(manifest)
    audit=dict(student_input_verified=False, scope='planned_manifest_until_Student_trace_verified', removed_unit_ids_absent=not chosen.intersection(u['evidence_unit_id'] for u in retained), exact_text_overlap=[dict(evidence_unit_id=u['evidence_unit_id'], fields=[k for k in ('Rc','Rv','K_int') if u['evidence_text'] in str(fields[k])], retained_K_ext=u['evidence_text'] in text) for u in removed], limitation='Unit removal does not erase pretrained knowledge or overlapping information in unchanged fields/retained articles.')
    return dict(ablation_mode='source_level',excluded_unit_ids=sorted(chosen), excluded_source_ids=sorted({s for u in removed for s in u['article_source_ids']}), excluded_evidence_units=removed, retained_evidence_units=retained, ablation_manifest=manifest, effective_input_diff={'K_ext':{'before':fields['K_ext'],'after':text}}, input_provenance={'parent_version_id':parent['version_id'],'parent_student_fields_sha256':content_hash(fields),'unchanged_fields':['Rc','Rv','K_int'],'parent_manifest_hash':m['manifest_hash']}, contamination_audit=audit, known_limitations=[audit['limitation']], rerun_stage_records=[])
