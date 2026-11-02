<script setup>
import { computed, ref, watch } from 'vue'
import EvidenceSourceCard from './EvidenceSourceCard.vue'
const props = defineProps({ version: Object, busy: Boolean, locale: String, request: Function, versions: Array })
const emit = defineEmits(['submit', 'select'])
const mode = ref('external_knowledge'), confirmed = ref(false)
const tr = (zh,en) => props.locale === 'en' ? en : zh
const capabilities = computed(() => props.version?.ablation_capabilities)
const selected = ref([]), preview = ref(null), previewError = ref(''), loading = ref(false)
let generation = 0
const eligibleVersions = computed(() => (props.versions || []).filter(v => v.version_id !== props.version?.version_id && v.status === 'succeeded' && v.ablation_capabilities?.source_level?.available === true))
const units = computed(() => capabilities.value?.source_level?.units || [])
const existing = computed(() => [...(props.versions || [])].reverse().find(v => v.parent_version_id === props.version?.version_id && v.ablation_mode === 'source_level' && v.ablation_manifest?.manifest_hash === preview.value?.ablation_manifest?.manifest_hash))
const available = computed(() => mode.value === 'external_knowledge' ? capabilities.value?.external_knowledge?.available === true : capabilities.value?.source_level?.available === true && !!preview.value && !loading.value && !['pending','running'].includes(existing.value?.status))
watch(selected, async () => {
  const ticket = ++generation
  preview.value = null; confirmed.value = false; previewError.value = ''
  if (!selected.value.length || !props.request) { loading.value = false; return }
  loading.value = true
  try {
    const data = await props.request(`/versions/${props.version.version_id}/source-ablation-preview`, {method:'POST',body:JSON.stringify({excluded_unit_ids:selected.value})})
    if(ticket === generation) preview.value = data
  } catch(error) { if(ticket === generation) previewError.value = error.message }
  finally { if(ticket === generation) loading.value = false }
})
function submit() {
  if (!available.value || !confirmed.value || props.busy) return
  emit('submit', {parent_version_id:props.version.version_id, ablation_mode:mode.value, excluded_source_ids:[], ...(mode.value === 'source_level' ? {excluded_unit_ids:[...selected.value], manifest_hash:preview.value.ablation_manifest.manifest_hash, confirm:true, ...(existing.value?.status === 'failed' ? {retry_of_version_id:existing.value.version_id} : {})} : {})})
}
const sources = computed(() => props.version?.output_snapshot?.retrieve?.evidence?.sources || (props.version?.output_snapshot?.retrieve?.uri || []).filter(v => typeof v === 'string').map((url,i) => ({source_id:`legacy-${i}`,source_url:url})))
watch([() => props.version?.version_id, mode], () => { confirmed.value = false; generation++; selected.value = []; preview.value = null; loading.value = false; previewError.value = '' })
</script>
<template>
  <article class="ablation-panel">
    <p v-if="version" class="active-operation-version">{{ tr('目前操作版本／重跑父版本','Active experiment / rerun parent') }}：V{{ version.version_number }} · {{ version.experiment_type }} · {{ version.version_id }}</p>
    <p v-if="version?.status !== 'succeeded'">{{ tr('請先選取成功的分析版本。','Select a successful analysis version first.') }}</p>
    <template v-else>
      <label>{{ tr('排除模式','Ablation mode') }}
        <select v-model="mode" :disabled="busy">
          <option value="external_knowledge">External Knowledge · {{ tr('外部知識通道','External input channel') }}</option>
          <option value="source_level">Source-level · {{ capabilities?.source_level?.available ? '可用 / available' : 'unavailable' }}</option>
        </select>
      </label>
      <template v-if="mode === 'source_level'">
        <template v-if="capabilities?.source_level?.available">
          <p>只移除選取新聞的完整輸入單位；保留 Rc、Rv、K_int，只重跑 Student。這不會消除模型預訓練知識或其他欄位的重疊資訊。</p>
          <label v-for="unit in units" :key="unit.evidence_unit_id"><input v-model="selected" type="checkbox" :value="unit.evidence_unit_id" :disabled="busy" /> 排除 {{ unit.article_title || unit.resolved_url }} · {{ unit.article_id }}</label>
          <p v-if="loading">正在核對排除預覽…</p><p v-if="previewError" role="alert">{{ previewError }}</p>
          <template v-if="preview">
            <p>保留來源：{{ preview.retained_evidence_units.map(u => u.article_title || u.resolved_url).join('、') || '無；空 K_ext，與此父版本的 Mode B 可能具有相同有效輸入。' }}</p>
            <details><summary>將送入 Student 的完整 K_ext（{{ preview.ablation_manifest.k_ext_length }} 字元）</summary><pre>{{ preview.ablation_manifest.k_ext || '（空內容）' }}</pre></details>
            <p v-if="existing">既有版本 V{{ existing.version_number }}：{{ existing.status }}。{{ existing.error || '' }}</p>
          </template>
          <details><summary>未進入 K_ext 的來源與原因（不可排除）</summary><p v-for="record in version.source_grounded_manifest.selection_records.filter(r => r.selection_status !== 'selected')" :key="record.source_id">{{ record.source_id }}：{{ record.selection_reason }}</p></details>
        </template>
        <div v-else>
          <p>{{ tr('有正文不代表已進入目前版本的 K_ext。請選取成功且來源 lineage 通過驗證的 Source-grounded Baseline。','An article body does not imply it entered this version’s K_ext. Select a successful, verified source-grounded baseline.') }}</p>
          <p v-if="!capabilities && version.source_grounded_manifest">{{ tr('目前 API 未提供 Mode A 能力資料；請重啟更新後的後端並重新整理，不能僅憑 manifest 強制啟用。','The API did not provide Mode A capabilities. Restart the updated backend and refresh; a manifest alone cannot enable selection.') }}</p>
          <button v-for="candidate in eligibleVersions" :key="candidate.version_id" type="button" :disabled="busy" @click="emit('select', candidate.version_id)">V{{ candidate.version_number }} · Source-grounded Baseline · {{ tr('以此版本進行實驗','Use this version for experiments') }}</button>
        </div>
        <p v-if="!capabilities?.source_level?.available">{{ capabilities?.source_level?.reason || tr('目前 K_ext 為混合生成內容，缺乏可驗證的單篇來源 lineage；此模式不可用。','K_ext is mixed generated content without verified source-to-input lineage. This mode is unavailable.') }}</p>
        <details v-if="!capabilities?.source_level?.available"><summary>{{ tr('來源可追蹤性','Source traceability') }} ({{ sources.length }})</summary>
          <div v-for="(source,i) in sources" :key="`${version.version_id}-${source.source_id}-${i}`">
            <label><input type="checkbox" disabled /> {{ version.source_grounded_manifest ? tr('目前版本尚未通過 Mode A 能力核對；請查看上方原因','This version has not passed Mode A capability validation; see the reason above') : tr('無法追蹤至 Student 有效輸入，不能單篇排除','Cannot trace to effective Student input; individual exclusion unavailable') }}</label>
            <EvidenceSourceCard :source="source" :locale="locale" :unlinked="true" />
          </div>
        </details>
      </template>
      <template v-else>
        <p>{{ tr('確認摘要：以選取版本為父版本，清空 Student 的 K_ext，保留 Rc、Rv、K_int；只重新執行 Student，不執行 Retrieve。','Summary: clear Student K_ext from the selected parent, preserve Rc/Rv/K_int, rerun Student only. No Retrieve call.') }}</p>
        <p>{{ tr('這不會消除預訓練知識，也不能保證其他欄位未包含外部資訊。來源卡片仍保留為研究紀錄。','This does not erase pretrained knowledge or guarantee other fields contain no external information. Source cards remain as research records.') }}</p>
        <p v-if="!available">{{ capabilities?.external_knowledge?.reason || tr('尚無可驗證的有效輸入。','Verified effective input is unavailable.') }}</p>
      </template>
      <label><input v-model="confirmed" type="checkbox" :disabled="busy || !available" /> {{ mode === 'source_level' ? (existing?.status === 'failed' ? '確認重試' : '確認來源與 K_ext') : tr('確認建立新的通道排除實驗','Confirm a new input-channel ablation experiment') }}</label>
      <button type="button" :disabled="busy || !available || !confirmed" @click="submit">{{ busy ? tr('執行中','Running') : mode === 'source_level' && existing?.status === 'succeeded' ? '查看既有成功版本（不重跑）' : tr('建立新版本並重新判斷','Create version and rerun Student') }}</button>
    </template>
  </article>
</template>
<style scoped>
pre { white-space:pre-wrap; overflow-wrap:anywhere; max-height:300px; overflow:auto; } .ablation-panel { min-width:0; overflow-wrap:anywhere; } label, details { display:block; margin:12px 0; } select { max-width:100%; } button { padding:10px 14px; } :focus-visible { outline:3px solid #2968ad; outline-offset:2px; }
</style>
