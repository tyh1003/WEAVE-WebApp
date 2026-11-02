"""Conservative input-channel ablation; never infer source-level lineage."""
import copy
import hashlib
import json

FIELDS = ('Rc', 'Rv', 'K_int', 'K_ext')
SOURCE_UNAVAILABLE = '目前 K_ext 為混合生成內容，缺乏可驗證的單篇來源 lineage。'
LIMITATIONS = [
    '僅排除 Student 的 K_ext 輸入通道，不消除模型預訓練知識。',
    'Rc、Rv、K_int 與 K_ext 由同次 Retrieve 產生；無法證明其他欄位完全沒有外部資訊，因此不宣稱完全隔離。',
    '保留的來源卡片是父版本搜尋紀錄，不是本版本送入 Student 的文章或直接證據。',
]


def content_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def has_content(value):
    # Match StudentBot's original knowledge formatter (blank/list/None become 無).
    if isinstance(value, list):
        return any(str(item).strip() for item in value)
    return bool(value and str(value).strip())


def parent_fields(parent):
    snapshot = parent.get('output_snapshot') or {}
    recorded = (snapshot.get('student_trace') or {}).get('fields')
    retrieved = snapshot.get('retrieve') or {}
    if not isinstance(recorded, dict) or set(recorded) != set(FIELDS):
        raise ValueError('Parent lacks a verified four-field Student input trace')
    if any(recorded[key] != retrieved.get(key) for key in FIELDS):
        raise ValueError('Parent Student trace and effective Retrieve fields differ')
    return copy.deepcopy(recorded)


def capabilities(parent):
    reason = None
    try:
        if parent.get('status') != 'succeeded':
            raise ValueError('Requires a successful parent version')
        if not has_content(parent_fields(parent)['K_ext']):
            raise ValueError('K_ext has no effective content to exclude')
    except ValueError as error:
        reason = str(error)
    try:
        from source_ablation import validated_manifest
        manifest = validated_manifest(parent)
        source_cap = {'available': True, 'reason': None, 'units': manifest['units']}
    except (ValueError, KeyError, TypeError) as error:
        source_cap = {'available': False, 'reason': str(error)}
    return {'source_level': source_cap,
            'external_knowledge': {'available': reason is None, 'reason': reason},
            'external_input_fields': ['K_ext'], 'limitations': LIMITATIONS}


def plan(parent, mode, source_ids):
    if mode == 'source_level':
        from source_ablation import plan as source_plan
        return source_plan(parent, source_ids)
    if mode != 'external_knowledge':
        raise ValueError(SOURCE_UNAVAILABLE if mode == 'source_level' else 'Unknown ablation mode')
    if source_ids:
        raise ValueError('Channel ablation does not claim exclusion of individual sources')
    fields = parent_fields(parent)
    if not has_content(fields['K_ext']):
        raise ValueError('K_ext has no effective content to exclude')
    return dict(ablation_mode=mode, excluded_source_ids=[],
                excluded_evidence_units=[{'unit_id': 'student.K_ext', 'field': 'K_ext',
                                          'content_sha256': content_hash(fields['K_ext']), 'lineage': 'input_channel_only'}],
                effective_input_diff={'K_ext': {'before': fields['K_ext'], 'after': ''}},
                input_provenance={'parent_version_id': parent['version_id'],
                                  'parent_student_fields_sha256': content_hash(fields),
                                  'unchanged_fields': ['Rc', 'Rv', 'K_int'], 'source_level_lineage': 'unavailable'},
                known_limitations=LIMITATIONS, rerun_stage_records=[])


def effective_retrieve(parent, version):
    fields = parent_fields(parent)
    if version.get('ablation_mode') == 'source_level':
        expected = plan(parent, 'source_level', version['excluded_unit_ids'])
        if expected['ablation_manifest'] != version['ablation_manifest']:
            raise ValueError('Frozen ablation manifest mismatch')
        fields['K_ext'] = expected['ablation_manifest']['k_ext']
    else:
        fields['K_ext'] = ''
    data = copy.deepcopy(parent['output_snapshot']['retrieve'])
    data.update(fields)
    data.update(analysis_id=version['version_id'], run_id=version['version_number'])
    data['ablation'] = {'mode': version.get('ablation_mode', 'external_knowledge'), 'parent_version_id': parent['version_id'],
                        'excluded_input_fields': ['K_ext'], 'sources_role': 'parent_research_inventory_not_student_input'}
    if version.get('ablation_mode') == 'source_level':
        data['ablation'].update(excluded_input_fields=[], replaced_input_fields=['K_ext'], sources_role='retained_units_in_manifest_only', manifest_hash=version['ablation_manifest']['manifest_hash'])
    evidence = data.get('evidence')
    if isinstance(evidence, dict):
        evidence.update(analysis_id=version['version_id'], run_id=version['version_number'])
        evidence['retrieval_parent_version_id'] = parent['version_id']
        for source in evidence.get('sources', []):
            if version.get('ablation_mode') == 'source_level':
                units = version['retained_evidence_units']
                source['student_input_evidence_units'] = [u['evidence_unit_id'] for u in units if source['source_id'] in u['article_source_ids']]
                source['student_input_status'] = 'manifest_prefix_in_K_ext' if source['student_input_evidence_units'] else 'excluded_or_parent_inventory_only'
            else:
                source['student_input_status'] = 'not_passed_as_article; K_ext_channel_excluded'
    return data
