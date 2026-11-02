"""Frozen, explicit retry preparation. Never executes Student or modifies its configuration."""
import json
from pathlib import Path
import yaml
from evidence_ablation import content_hash

BASE=Path(__file__).resolve().parent
FILES=('student_bot.py','run_student.py','config/student_bot_config.yaml')

def current_contract():
    return {name:content_hash((BASE/name).read_text(encoding='utf-8')) for name in FILES}

def prepare(failed,parent,root):
    if failed['status']!='failed' or failed['experiment_type']!='source_aware_baseline':
        raise ValueError('Only failed Source-aware versions can be retried')
    work=Path(failed['artifact_paths']['workspace']).resolve()
    if not work.is_relative_to(Path(root).resolve()):raise ValueError('Retry workspace is outside private research root')
    trace=json.loads((work/'output/student_trace.json').read_text(encoding='utf-8'))
    data=json.loads((work/'output/retrieve.jsonl').read_text(encoding='utf-8').splitlines()[-1])
    from source_aware import effective_retrieve
    expected=effective_retrieve(parent,failed)
    fields={k:data[k] for k in ('Rc','Rv','K_int','K_ext')}
    if trace.get('fields')!=fields or fields!={k:expected[k] for k in fields}:raise ValueError('Failed input trace mismatch')
    if trace.get('config')!=yaml.safe_load((BASE/'config/student_bot_config.yaml').read_text(encoding='utf-8')):
        raise ValueError('Current model configuration differs from failed version; controlled retry refused')
    if not trace.get('effective_input_ids') or not trace.get('generation'):raise ValueError('Incomplete failed Student trace')
    return dict(retry_of_version_id=failed['version_id'],source_aware_manifest=failed['source_aware_manifest'],
        retry_snapshot=dict(student_trace=trace,student_fields=fields,implementation_hashes=current_contract(),
            source_files={name:content_hash((work/name).read_text(encoding='utf-8')) for name in ('output/retrieve.jsonl','output/student_trace.json','execution.log')},
            original_error=failed.get('error')),rerun_stage_records=[],
        input_provenance={'retry_of_version_id':failed['version_id'],'parent_version_id':parent['version_id'],'unchanged_fields':list(fields)},
        effective_input_diff={})

def verify(version,fields,trace=None):
    saved=version['retry_snapshot']
    if current_contract()!=saved['implementation_hashes'] or fields!=saved['student_fields']:
        raise ValueError('Controlled retry input or implementation changed')
    if trace is not None:
        keys=('fields','config','model','generation','formatted_prompt','effective_input_ids','effective_attention_mask','max_length','truncation')
        if any(trace.get(k)!=saved['student_trace'].get(k) for k in keys):
            raise ValueError('Controlled retry actual Student trace differs from failed execution')
