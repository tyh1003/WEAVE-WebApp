import { safeUrl, searchSources } from './evidence.js'

export const fieldNames = ['Rc', 'Rv', 'K_int', 'K_ext']
const pick = (object, keys) => Object.fromEntries(keys.filter(k => object?.[k] != null).map(k => [k, object[k]]))

// Private execution logs, environment, filesystem manifests and SDK response envelopes
// are intentionally outside the display projection. Scrub incidental secrets in saved text.
export function displayText(value) {
  if (value == null) return ''
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  return text.replace(/\bBearer\s+[\w.+/=:-]+|AIza[\w-]{20,}/gi, '[redacted]')
    .replace(/((?:api[_-]?key|access[_-]?token|authorization|password|secret|signature)["']?\s*[:=]\s*["']?)[^\s"&,}']+/gi, '$1[redacted]')
    .replace(/(?:[A-Za-z]:[\\/]|\\\\)[^\r\n"'<>]+|\/(?:Users|home|private|tmp|root|mnt|var|opt)\/[^\s"',}]+/g, '[private path]')
}
export function sourceLink(s) {
  for (const raw of [s.resolved_url,s.source_url,s.original_url,s.url]) {
    const url = safeUrl(raw)
    if (url && displayText(url) === url) return url
  }
  return null
}
export function inspectVersion(v = {}) {
  const out = v.output_snapshot || {}, r = out.retrieve, st = out.student_trace || {}
  const trace = Array.isArray(out.retrieve_trace) ? out.retrieve_trace : []
  const inventoryRecorded = [r?.sources,r?.evidence?.sources,r?.uri,out.student?.sources,out.student?.evidence?.sources].some(Array.isArray)
  const sources = searchSources({sources:[]},r,r)
  const inventory = searchSources({sources},out.student,null)
  const inventorySaved = inventoryRecorded || inventory.length > 0
  const config = {retrieve:trace.map(t=>pick(t,['model','temperature','token','tools','image_count','max_output_tokens'])),
    student:pick(st,['model','generation','truncation','max_length'])}
  const fields = Object.fromEntries(fieldNames.map(k=>[k, st.fields?.[k] ?? v.input_snapshot?.student_fields?.[k] ?? r?.[k]]))
  const fallback = r?.supplemental_grounding
  const grounding = pick(fallback,['status','attempts','model','policy','response_diagnostic','error_type','k_ext_updated','k_ext_reason','chunk_to_source'])
  const versionRecords = pick(v,['correction_payload','ablation_mode','excluded_source_ids','effective_input_diff','contamination_audit','rerun_stage_records','retry_of_version_id','known_limitations','input_provenance'])
  const manifest = v.selected_news_manifest || v.source_aware_manifest || v.ablation_manifest || v.source_grounded_manifest
  const provenance = inventory.map(s=>({...pick(s,['source_id','article_id','article_text_hash','grounding_origin','retrieval_status','extraction_status','content_quality','date_source','redirect_chain']),url:sourceLink(s)}))
  const compare = { ...fields, 'Retrieve prompt':trace.length?trace.map(t=>pick(t,['system_prompt','prompt'])):undefined,
    'Correction':v.correction_payload, 'Sources':inventorySaved?provenance.map(s=>[s.source_id,s.url]):undefined,
    'Student input':st.formatted_prompt, 'Student output':out.student && pick(out.student,['pred_label','reason']),
    'Runtime (s)':v.runtime_profile?.total_verification_seconds, 'Model settings':trace.length||st.model?config:undefined }
  return {out,r,st,trace,fields,inventory,inventorySaved,grounding,config,provenance,versionRecords,manifest,compare}
}
export function stageRows(v, data) {
  const rows=v.runtime_profile?.stages || [], events=v.events || []
  return ['preprocess','retrieve','student'].map(stage=>{
    const timings=rows.filter(r=>r.stage===stage)
    const event=events.find(e=>e.stage===stage)
    const reused=v.execution_conditions?.reused_stages?.some(s=>s.toLowerCase().startsWith(stage)) ||
      events.some(e=>e.stage===stage+'_reused')
    const output={preprocess:data.out.preprocess,retrieve:data.r,student:data.out.student}[stage]
    let status='not_recorded'
    if(v.failed_stage===stage || timings.some(r=>r.status==='failed'))status='failed'
    else if(reused)status='reused'
    else if(v.stage===stage && v.status==='running')status='running'
    else if(timings.length && timings.every(r=>r.status==='succeeded') || v.status==='succeeded' && output && event)status='succeeded'
    else if(output)status='output_saved'
    else if(v.status==='pending')status='pending'
    const seconds=timings.length && timings.every(t=>Number.isFinite(t.seconds))?timings.reduce((n,t)=>n+t.seconds,0):null
    return {stage,status,seconds,at:event?.at, timings}
  })
}
