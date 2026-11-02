<script setup>
import { computed, ref, watch } from 'vue'
import RuntimeProfile from './RuntimeProfile.vue'
import { inspectVersion, stageRows, displayText, sourceLink } from '../researchInspector.js'
const props=defineProps({versions:Array,selected:String,locale:String,request:Function})
const ui=(zh,en)=>props.locale==='en'?en:zh
// Inspecting a snapshot must never invoke the workspace selection/translation workflow.
const inspected=ref(null)
watch(()=>props.selected || props.versions?.at(-1)?.version_id,id=>{inspected.value=id},{immediate:true})
const version=computed(()=>props.versions?.find(v=>v.version_id===inspected.value))
const d=computed(()=>inspectVersion(version.value))
const parent=computed(()=>props.versions?.find(v=>v.version_id===version.value?.parent_version_id))
const changes=computed(()=>{
 if(!parent.value)return []
 const before=inspectVersion(parent.value).compare
 return Object.entries(d.value.compare).filter(([k,v])=>v!==undefined && before[k]!==undefined && JSON.stringify(before[k])!==JSON.stringify(v)).map(([k,v])=>({key:k,before:before[k],after:v}))
})
const missing=()=>ui('未記錄','Not recorded')
const stageName={preprocess:'Preprocess',retrieve:'Refine / Retrieve',student:'Reason · Student'}
const status=s=>({reused:ui('沿用父版本','Reused from parent'),not_recorded:missing(),output_saved:ui('有保存輸出','Output saved'),succeeded:ui('完成','Completed'),failed:ui('失敗','Failed'),running:ui('執行中','Running'),pending:ui('等待','Pending')})[s] || s
const verdict=s=>s?.pred_label===0?'Real':s?.pred_label===1?'Fake':ui('尚無判斷','No judgment')
const fields=['Rc','Rv','K_int','K_ext']
const copyStatus=ref('')
watch(inspected,()=>{copyStatus.value=''})
async function copy(value){
 try{await navigator.clipboard.writeText(displayText(value));copyStatus.value=ui('已複製','Copied')}
 catch{copyStatus.value=ui('請選取文字複製','Select the text to copy')}
}
const prompts=computed(()=>{
 const rows=[]
 for(const [i,t] of d.value.trace.entries()){
  rows.push(['Retrieve '+(i+1)+' · System',t.system_prompt],['Retrieve '+(i+1)+' · '+ui('實際送出文字','Submitted text'),t.prompt])
 }
 rows.push(['Student · '+ui('保存的使用者模板','Saved user template'),d.value.st.config?.USER_PROMPT_TEMPLATE],['Student · '+ui('保存的系統指令','Saved system instruction'),d.value.st.config?.system_prompt],['Student · '+ui('格式化輸入','Formatted input'),d.value.st.formatted_prompt],['Student · '+ui('模型原始輸出','Raw model output'),d.value.st.raw_response])
 return rows.filter(([,v])=>typeof v==='string' && v.length)
})
const stageOutput=stage=>stage==='preprocess'?Object.fromEntries(['transcript','description','vision'].filter(k=>d.value.out.preprocess?.[k]!=null).map(k=>[k,d.value.out.preprocess[k]])):stage==='retrieve'?Object.fromEntries(fields.filter(k=>d.value.r?.[k]!=null).map(k=>[k,d.value.r[k]])):d.value.out.student && {pred_label:d.value.out.student.pred_label,reason:d.value.out.student.reason}
</script>
<template>
 <div class="inspector">
 <label>{{ ui('檢視保存版本','Inspect saved version') }}
  <select v-model="inspected"><option v-for="v in versions" :key="v.version_id" :value="v.version_id">V{{ v.version_number }} · {{ v.experiment_type }} · {{ status(v.status) }}</option></select>
 </label>
 <p v-if="!version">{{ ui('尚無可檢視的版本','No saved version to inspect') }}</p>
 <template v-else>
 <details data-category="pipeline"><summary>01 · {{ ui('流程總覽','Pipeline Overview') }}</summary>
  <details v-for="row in stageRows(version,d)" :key="row.stage"><summary>{{stageName[row.stage]}} · {{status(row.status)}} <span v-if="row.seconds!=null"> · {{row.seconds.toFixed(2)}} s</span></summary>
   <template v-if="row.stage==='preprocess' && d.out.preprocess">
    <details v-for="[k,label] in [['transcript',ui('語音轉錄','Audio transcript')],['description',ui('視覺描述','Visual description')]].filter(([k])=>d.out.preprocess[k]!=null)" :key="k"><summary>{{label}} · {{ui('保存輸出','Saved output')}}</summary><pre>{{displayText(d.out.preprocess[k])}}</pre></details>
   </template>
   <p v-if="row.stage==='retrieve' && d.inventorySaved">{{ui('保存來源','Saved sources')}} · {{d.inventory.length}} <span v-if="d.grounding.status"> · Fallback: {{d.grounding.status}}</span></p>
   <p v-if="row.stage==='student' && d.out.student">Student · {{verdict(d.out.student)}}</p>
   <p v-if="row.at">{{row.at}}</p>
   <p v-if="row.stage==='retrieve' && d.trace.length">{{displayText(d.trace.map(t=>t.model).filter(Boolean).join(', '))}}</p>
   <p v-if="row.stage==='student' && d.st.model">{{displayText(d.st.model)}}</p>
   <p v-if="version.failed_stage===row.stage">{{displayText(version.failed_step)}} · {{displayText(version.error)}}</p>
   <details v-if="row.stage!=='preprocess'"><summary>{{ui('解析後的階段輸出','Saved stage outputs')}}</summary><pre>{{Object.keys(stageOutput(row.stage)||{}).length?displayText(stageOutput(row.stage)):missing()}}</pre></details>
  </details>
 </details>
 <details data-category="retrieve"><summary>02 · {{ui('檢索與提示詞','Retrieve & Prompt Details')}}</summary>
  <details v-for="(k,i) in fields" :key="k"><summary>{{k}} · {{[ui('文字內容','Text content'),ui('視覺描述','Visual description'),ui('內部知識','Internal knowledge'),ui('外部知識','External knowledge')][i]}}</summary><pre>{{d.fields[k]==null?missing():d.fields[k]===''?ui('空字串','Empty string'):displayText(d.fields[k])}}</pre></details>
  <details><summary>{{ui('提示詞與原始輸出','Prompts and raw outputs')}}</summary>
   <p>{{ui('Rc／Rv 的 Refine 包含於 Retrieve；未另存獨立提示詞。','Rc/Rv refinement is part of Retrieve. No separate Refine prompt was recorded.')}}</p>
   <p v-if="!d.st.config?.USER_PROMPT_TEMPLATE">Student template · {{missing()}}</p>
   <p v-if="!d.trace.length">Retrieve · {{version.execution_conditions?.retrieve_parent_version_id?ui('本版未執行，請檢視父版本','Not run here; inspect parent version'):missing()}}</p>
   <p v-if="!d.st.formatted_prompt">Student · {{missing()}}</p>
   <details v-for="[label,value] in prompts" :key="label"><summary>{{label}}</summary><button type="button" @click="copy(value)">{{ui('複製','Copy')}}</button><pre>{{displayText(value)}}</pre></details>
   <small role="status">{{copyStatus}}</small>
   <p v-if="Object.keys(d.out.retrieve_raw_responses||{}).length">{{ui('已保存原始 Retrieve SDK 回應。含傳輸資訊的私有紀錄僅於版本工作目錄保留。','Raw Retrieve SDK response saved in the private version workspace.')}}</p>
  </details>
  <details><summary>Grounding · {{d.inventorySaved?d.inventory.length:missing()}}</summary>
   <p v-if="d.inventorySaved && !d.inventory.length">{{ui('本次未取得外部新聞來源','No external news sources retrieved.')}}</p>
   <p>{{ui('來源清單不代表 Student 採用或獨立驗證。','Source inventory does not establish Student reliance or independent verification.')}}</p>
   <ul><li v-for="s in d.inventory" :key="s.source_id || sourceLink(s)">{{s.source_id || '—'}} · <a v-if="sourceLink(s)" :href="sourceLink(s)" target="_blank" rel="noopener noreferrer">{{sourceLink(s)}}</a> · {{s.article_text?ui('有保存文字','Text saved'):ui('原文未取得','Article text unavailable')}} · {{s.retrieval_status || missing()}}</li></ul>
   <p v-if="d.grounding.status">Fallback · {{d.grounding.status}}</p>
  </details>
  <details><summary>{{ui('保存的模型設定','Recorded model settings')}}</summary><pre>{{Object.keys(d.config.student).length || d.trace.length?displayText(d.config):missing()}}</pre></details>
 </details>
 <details id="version-comparison" data-category="versions"><summary>03 · {{ui('版本分析','Version Analysis')}}</summary>
  <p>V{{version.version_number}} · {{version.experiment_type}} · {{status(version.status)}} · Student: {{verdict(d.out.student)}}</p>
  <p>{{version.version_id}} <span v-if="version.parent_version_id">← {{version.parent_version_id}}</span></p>
  <p>{{ui('來源數','Sources')}}: {{d.inventorySaved?d.inventory.length:missing()}} · {{ui('執行時間','Runtime')}}: {{version.runtime_profile?.total_verification_seconds!=null?version.runtime_profile.total_verification_seconds.toFixed(2)+' s':missing()}}</p>
  <details><summary>{{ui('Student 原始理由','Original Student reasoning')}}</summary><pre>{{displayText(d.out.student?.reason) || missing()}}</pre></details>
  <p v-if="parent">V{{parent.version_number}} → V{{version.version_number}} · {{ui('僅比較雙方已記錄欄位','Comparing fields recorded in both versions')}}</p>
  <p v-if="!changes.length">{{parent?ui('可比較欄位未見差異','No differences in comparable fields'):ui('無可比較的父版本','No parent available for comparison')}}</p>
  <details v-for="c in changes" :key="c.key"><summary>{{c.key}}</summary><strong>V{{parent.version_number}}</strong><pre>{{displayText(c.before)}}</pre><strong>V{{version.version_number}}</strong><pre>{{displayText(c.after)}}</pre></details>
 </details>
 <details data-category="records"><summary>04 · {{ui('執行紀錄','Execution Records')}}</summary>
  <p>Experiment · {{version.experiment_id || missing()}}<br>Version · {{version.version_id}}<br>{{version.started_at || missing()}} → {{version.finished_at || missing()}}</p>
  <p v-if="version.error">{{displayText(version.error)}}</p>
  <details v-for="[label,value] in [['Events',version.events],['Stage reuse',version.execution_conditions && {rerun_stages:version.execution_conditions.rerun_stages,reused_stages:version.execution_conditions.reused_stages,retrieve_parent_version_id:version.execution_conditions.retrieve_parent_version_id}],['Video SHA-256',version.provenance?.video_sha256],['Stage timings',version.runtime_profile?.stages],['Grounding',d.r?.initial_grounding_candidates],['Grounding parser',d.r?.grounding_parse_error],['Saved search queries',d.r?.query],['Fallback',d.grounding],['Source provenance',d.provenance],['Documented source mappings',d.r?.supplemental_grounding?.chunk_to_source],['Version records',d.versionRecords],['Manifest',d.manifest && {manifest_hash:d.manifest.manifest_hash,parent_version_id:d.manifest.parent_version_id,units:(d.manifest.units || d.manifest.news_cards || []).map(u=>({source_id:u.source_id,article_id:u.article_id,evidence_unit_id:u.evidence_unit_id,article_text_hash:u.article_text_hash}))}]].filter(([,v])=>v && Object.keys(v).length)" :key="label"><summary>{{label}}</summary><pre>{{displayText(value)}}</pre></details>
  <RuntimeProfile v-if="request" :key="version.version_id" :version-id="version.version_id" :request="request" :locale="locale"/>
 </details>
 </template>
 </div>
</template>
<style scoped>
.inspector{padding:0 1rem 1rem;color:#292532;min-width:0;overflow-wrap:anywhere}.inspector>label{display:flex;align-items:center;gap:.7rem;flex-wrap:wrap;margin:.5rem 0 1rem}select{max-width:100%;font:inherit}.inspector>details{border-top:1px solid #e7e2eb;padding:.45rem 0}details details{margin:.35rem 0 .35rem .65rem}summary{cursor:pointer;padding:.45rem;font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:24rem;overflow:auto;background:#f8f7fa;padding:.75rem}p,li{line-height:1.55}:focus-visible{outline:2px solid #7050b1}
</style>
