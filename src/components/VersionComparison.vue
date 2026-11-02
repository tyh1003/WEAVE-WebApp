<script setup>
import { ref } from 'vue'
import EvidenceText from './EvidenceText.vue'
const props = defineProps({ versions: Array, selected: String, locale: String, human: String, groundTruth: String, busy: Boolean })
defineEmits(['select','retry'])
const retryConfirmed=ref({})
function differences(version) {
  const parent = props.versions.find(v => v.version_id === version.parent_version_id)
  if (!parent?.output_snapshot || !version.output_snapshot) return null
  const before = parent.output_snapshot.retrieve, after = version.output_snapshot.retrieve
  const urls = value => new Set([...(value.uri || []).filter(v => typeof v === 'string'), ...(value.evidence?.sources || []).map(s => s.source_url).filter(Boolean)])
  const previous = urls(before), current = urls(after)
  return {
    compared_to_version: parent.version_number,
    fields: Object.fromEntries(['Rc','Rv','K_int','K_ext'].filter(k => JSON.stringify(before[k]) !== JSON.stringify(after[k])).map(k => [k, {before:before[k], after:after[k]}])),
    source_urls_added: [...current].filter(url => !previous.has(url)),
    source_urls_removed: [...previous].filter(url => !current.has(url)),
  }
}
</script>
<template>
  <div class="version-list">
    <p>Human Judgment: {{ human || '—' }} · Ground Truth: {{ groundTruth || '未提供 / Not available' }}</p>
    <article v-for="version in versions" :key="version.version_id">
      <button type="button" :aria-pressed="selected === version.version_id" :disabled="version.status !== 'succeeded'" @click="$emit('select', version.version_id)">V{{ version.version_number }} · {{ version.experiment_type }} · {{ version.status }} · {{ selected === version.version_id ? (locale === 'en' ? 'Current experiment version' : '目前操作版本') : (locale === 'en' ? 'Use this version for experiments' : '以此版本進行實驗') }}</button>
      <p>{{ version.created_at }} → {{ version.finished_at || '…' }}</p>
      <p v-if="version.retry_of_version_id">受控重試來源：{{ version.retry_of_version_id }}；凍結沿用四欄輸入及設定，只重跑 Student。</p>
      <div v-if="version.status==='failed' && version.experiment_type==='source_aware_baseline'">
        <p>相同輸入與確定性生成可能再次失敗；此操作不修正或猜測非法輸出。</p>
        <template v-if="!versions.some(v=>v.retry_of_version_id===version.version_id)">
          <label><input type="checkbox" v-model="retryConfirmed[version.version_id]" :disabled="busy" />確認只重跑 Student，建立新版本並保留失敗紀錄。</label>
          <button type="button" :disabled="busy || !retryConfirmed[version.version_id]" @click="$emit('retry',{experiment_type:'source_aware_baseline',retry_of_version_id:version.version_id,confirm:true});retryConfirmed[version.version_id]=false">建立受控重試版本</button>
        </template>
        <p v-else>已建立重試版本，請查看下方對應版本狀態。</p>
      </div>
      <details v-if="version.retry_snapshot"><summary>重試前原始生成、設定與輸入 trace</summary><pre>{{ JSON.stringify(version.retry_snapshot,null,2) }}</pre></details>

      <div v-if="version.experiment_type === 'source_grounded_baseline'">
        <p>{{ locale === 'en' ? 'New source-grounded research baseline; not original V1 and not source-level ablation.' : '新的來源可追蹤研究基準；不是原始 V1，也不是單篇來源排除。' }}</p>
        <details><summary>{{ locale === 'en' ? 'Source manifest and effective K_ext' : '來源 manifest 與有效 K_ext' }}</summary><pre>{{ JSON.stringify({manifest:version.source_grounded_manifest,actual_K_ext:version.input_snapshot?.student_fields?.K_ext,rerun_stage_records:version.rerun_stage_records,input_provenance:version.input_provenance},null,2) }}</pre></details>
      </div>
      <div v-if="version.experiment_type === 'source_aware_baseline'">
        <p>{{ locale === 'en' ? 'Source-aware model synthesis; citation is not fact verification. Original baseline is preserved.' : 'Source-aware 模型整理；引用不等於事實驗證，原始 Baseline 保留。' }}</p>
        <details><summary>Source-aware K_ext / News Cards / manifest</summary><pre>{{ JSON.stringify({manifest:version.source_aware_manifest,actual_K_ext:version.input_snapshot?.student_fields?.K_ext,rerun_stage_records:version.rerun_stage_records},null,2) }}</pre></details>
      </div>
      <details v-if="version.experiment_type === 'selected_news'"><summary>Selected News：選取來源、有效 K_ext 與執行紀錄</summary><p>保存摘要的選取實驗，不等於人工核准或事實驗證；空選取使用空白 K_ext。</p><pre>{{ JSON.stringify({manifest:version.selected_news_manifest,effective_input_diff:version.effective_input_diff,actual_K_ext:version.input_snapshot?.student_fields?.K_ext,input_provenance:version.input_provenance,rerun_stage_records:version.rerun_stage_records},null,2) }}</pre></details>
      <div v-if="version.experiment_type === 'evidence_ablation'">
        <p v-if="version.ablation_mode !== 'source_level'">{{ locale === 'en' ? 'Requested exclusion' : '排除設定' }} · Evidence Ablation · {{ version.ablation_mode }} · K_ext → {{ locale === 'en' ? 'empty input (formatted as 無)' : '空內容（Prompt 格式化為「無」）' }}</p>
        <p v-if="version.ablation_mode !== 'source_level'">{{ locale === 'en' ? 'Source-level unavailable: no verified per-source input lineage.' : '單篇來源排除不可用：尚無來源到模型輸入的可靠 lineage。' }}</p>
        <div v-if="version.ablation_mode === 'source_level'"><p>Source-level Ablation · 父版本 {{ version.parent_version_id }}</p><p>排除：{{ version.excluded_evidence_units?.map(u => `${u.article_title || u.resolved_url} (${u.article_id})`).join('、') }}</p><p>保留：{{ version.retained_evidence_units?.map(u => u.article_title || u.resolved_url).join('、') || '無（空 K_ext）' }}</p><p>測量移除指定來源輸入後的結果差異，不代表模型不再知道該資訊。</p><details><summary>組裝 manifest 與 contamination audit</summary><pre>{{ JSON.stringify({manifest:version.ablation_manifest,audit:version.contamination_audit},null,2) }}</pre></details></div>
        <details><summary>{{ locale === 'en' ? 'Exclusion, effective input changes and limitations' : '排除單位、有效輸入差異與限制' }}</summary><pre>{{ JSON.stringify({mode:version.ablation_mode,excluded_source_ids:version.excluded_source_ids,excluded_evidence_units:version.excluded_evidence_units,effective_input_diff:version.effective_input_diff,input_provenance:version.input_provenance,rerun_stage_records:version.rerun_stage_records,limitations:version.known_limitations}, null, 2) }}</pre></details>
      </div>
      
      <template v-if="version.output_snapshot">
        <p>AI Judgment: {{ version.output_snapshot.student.pred_label === 0 ? 'Real / 真' : 'Fake / 假' }}</p>
        <EvidenceText :text="version.output_snapshot.student.reason" :locale="locale" />
      </template>
      <details v-if="differences(version)"><summary>{{ locale === 'en' ? 'Changes from parent: model inputs and source URLs' : '相較父版本：模型輸入與來源網址差異' }}</summary><pre>{{ JSON.stringify(differences(version), null, 2) }}</pre></details>
      <details><summary>{{ locale === 'en' ? 'Inputs, changes, sources and execution record' : '輸入、差異、來源與執行紀錄' }}</summary><pre>{{ JSON.stringify({ error: version.error, status:version.status, parent_version_id: version.parent_version_id, correction: version.correction_payload, execution: version.execution_conditions, inputs: version.input_snapshot, sources: version.output_snapshot?.retrieve?.evidence?.sources, provenance: version.provenance, trace: version.output_snapshot?.student_trace, retrieve_trace: version.output_snapshot?.retrieve_trace, retrieve_raw_responses: version.output_snapshot?.retrieve_raw_responses }, null, 2) }}</pre></details>
    </article>
  </div>
</template>
<style scoped>
article { border-top:1px solid #dbe3ec; padding:16px 0; min-width:0; } button { padding:10px; } button[aria-pressed=true] { outline:2px solid #2968ad; } pre { white-space:pre-wrap; overflow-wrap:anywhere; max-height:600px; overflow:auto; } p { overflow-wrap:anywhere; } :focus-visible { outline:3px solid #2968ad; }
</style>
