<template>
  <section class="evidence-panel" :key="batchKey" aria-label="WEAVE evidence">
    <div v-if="!recordsOnly" class="reason-workspace">
    <aside class="reason-selector">
    <h3>{{ tr('主要判斷理由', 'Main reasons') }}</h3>
    <p class="notice">{{ tr('選擇一項理由，查看影片內容、來源及原始判斷。', 'Select a reason to review the video, sources and original judgment.') }}</p>
    <p v-if="!reasons.length" class="notice">{{ tr("尚未提供判斷理由。", "No reasoning was provided.") }}</p>
    <ol class="reason-options">
      <li v-for="(reason, index) in reasons" :key="reason.reason_id">
        <button type="button" :aria-pressed="selected?.reason_id === reason.reason_id" @click="selectReason(reason)">
          <strong>{{ tr('理由', 'Reason') }} {{ index + 1 }}</strong>
          <span>{{ textPreview(reason.reason_text, 150) }}</span>
          <small v-if="selected?.reason_id === reason.reason_id">{{ tr('已選取', 'Selected') }}</small>
        </button>
      </li>
    </ol>
    </aside>
    <div class="evidence-columns" :key="selected?.reason_id || 'unselected'" aria-live="polite">
      <p v-if="!selected" class="notice">{{ tr("選取左側理由以查看 A／C；仍可查看本次搜尋來源。", "Select a reason for A/C; search sources remain available below.") }}</p>
      <section v-if="selected">
        <h4>{{ tr('A. 影片說了什麼', 'A. What the video says') }}</h4>
        <button v-if="timestamp !== null && videoUrl" type="button" @click="$emit('seek', timestamp)">{{ tr("跳至已對齊的影片位置", "Go to aligned video position") }}</button>
        <p v-if="timestamp !== null">{{ tr('對應時間', 'Linked time') }}：{{ timestamp }} s</p>
        <p v-else class="notice">{{ tr('未建立精確時間對應，無法定位此理由的影片片段。', 'No precise time alignment; this reason cannot be located in the video.') }}</p>
        <div v-for="item in observation.items" :key="item.kind">
          <strong>{{ observationLabel(item.kind) }}</strong>
          <p v-if="!item.related" class="notice">{{ tr('未確認直接對應：以下為可用的原始輸入，僅供人工核對，不代表已定位此理由。', 'Direct correspondence unconfirmed: available original input is provided for manual review, not as a located match to this reason.') }}</p>
          <p v-else class="notice">{{ tr('依既有文字對應顯示，仍需以影片核對。', 'Shown using an existing text mapping; verify against the video.') }}</p>
          <EvidenceText :text="item.text" :locale="locale" />
        </div>
        <p v-if="!observation.items.length" class="notice">{{ tr('未確認直接對應：原始影片觀察未提供；可展開下方原始分析資料。', 'Direct correspondence unconfirmed: original video observation unavailable; original analysis is available below.') }}</p>
        <p class="notice">{{ tr('轉錄與影片描述可能有辨識錯誤，請以影片核對。', 'Transcript and video descriptions may contain recognition errors; check the video.') }}</p>
      </section>
      <section>
        <h4>{{ tr('B. 外部來源提供什麼', 'B. What external sources provide') }}</h4>
        <div v-for="claim in selectedClaims" :key="claim.claim_id" class="claim">
          <strong>{{ categoryLabel(claim) }}</strong>
          <EvidenceText :text="claim.claim_text" :locale="locale" />
        </div>
        <p class="evidence-status">{{ !sources.length
          ? tr('本次未取得外部來源。', 'No external sources were obtained for this analysis.')
          : cards.some(card => ['supports','refutes'].includes(card.assessment?.stance))
            ? tr('以下為 AI 語意評估，並非人工確認或影片真偽的獨立驗證。', 'AI semantic assessment, not human confirmation or independent verification of video authenticity.')
          : tr('目前沒有已驗證的直接支持／反駁來源；尚無已確認的外部證據。', 'No confirmed external evidence; no verified direct support/refutation sources.') }}</p>
        <p v-if="data.assessment && !semanticCards.length" class="notice">{{ data.assessment.targets ? tr('欄位主張評估請見上方；尚未建立與此 Student 理由的直接對應。', 'See field claim assessments above; no direct mapping to this Student reason is established.') : tr('AI 語意評估尚未完成或尚未啟用；來源仍可查閱。', 'AI semantic assessment is not completed or enabled; sources remain available.') }} ({{ data.assessment.status }})</p>
        <template v-if="cards.length">
          <p v-if="!data.assessment?.schema_version" class="notice">{{ tr('以下保留既有文字對應供核對，尚未確認語意關聯。', 'Existing text mappings are shown for review; semantic relationships remain unconfirmed.') }}</p>
          <EvidenceSourceCard v-for="(card, index) in cards" :key="`${card.source_id}-${index}`" :source="card" :locale="locale" />
        </template>
        <div v-if="backgroundSources.length" class="background-sources">
          <h4>{{ tr('背景相關／待核對正文（不是直接證據）','Context / unassessed articles (not direct evidence)') }}</h4>
          <EvidenceSourceCard v-for="source in backgroundSources" :key="source.source_id" :source="source" :locale="locale" :unlinked="true" />
        </div>
        <details v-if="otherSources.length" class="other-sources">
          <summary>{{ tr('查看其他搜尋來源', 'Other search sources') }}（{{ otherSources.length }}）</summary>
          <p class="notice">{{ tr('以下包含背景相關、無關、未確認或原文未取得的來源，僅供人工查閱。', 'Background, unrelated, unassessed or unavailable sources are retained for manual review.') }}</p>
          <EvidenceSourceCard v-for="(source, index) in otherSources" :key="`${batchKey}-other-${index}`" :source="source" :locale="locale" :unlinked="true" />
        </details>
        <details v-if="sources.length"><summary>{{ tr('全部來源紀錄與引用識別（含重複）','All source records and references (including duplicates)') }}</summary><pre>{{ JSON.stringify(data.sources, null, 2) }}</pre></details>
      </section>
      <section v-if="selected">
        <h4>{{ tr('C. WEAVE 如何判斷', 'C. WEAVE’s judgment') }}</h4>
        <p class="notice">{{ tr('模型推論 · 原始判斷理由', 'Model inference · original reasoning') }}</p>
        <EvidenceText :text="selected.reason_text" :locale="locale" :limit="600" />
      </section>
    </div>
    </div>
    <details v-if="data.claims?.length" class="unmapped">
      <summary>{{ tr('全部主張與影片觀察', 'All claims and video observations') }} · {{ data.claims.length }}</summary>
      <article v-for="claim in data.claims" :key="claim.claim_id" class="evidence-card">
        <strong>{{ categoryLabel(claim) }}</strong>
        <EvidenceText :text="claim.claim_text" :locale="locale" />
        <details v-if="claim.evidence?.length">
          <summary>{{ tr('既有來源對應（未確認語意）', 'Existing source mappings (semantics unconfirmed)') }}</summary>
          <EvidenceSourceCard v-for="(card, index) in reasonCards(data, { claim_ids: [claim.claim_id] })" :key="`${card.source_id}-${index}`" :source="card" :locale="locale" />
        </details>
      </article>
    </details>

  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import EvidenceText from './EvidenceText.vue'
import EvidenceSourceCard from './EvidenceSourceCard.vue'
import { evidenceView, reasonCards, reliableTimestamp, claimCategory, observationFor, textPreview, searchSources, otherSearchSources, assessedCards } from '../evidence.js'
const props = defineProps({ result: Object, retrieve: Object, assessment: Object, videoUrl: String, locale: String, recordsOnly: Boolean })
const selectedId = ref(null)
defineEmits(['seek'])
const tr = (zh, en) => props.locale === 'en' ? en : zh
const batchKey = computed(() => JSON.stringify([props.result?.vid, props.result?.analysis_id, props.result?.run_id, props.videoUrl]))
const data = computed(() => {
  const original = evidenceView(props.result, props.retrieve), a=props.assessment
  return a && a.analysis_id===original.analysis_id && a.video_id===original.video_id && (a.run_id??null)===(original.run_id??null)
    ? {...original,assessment:a,claims:[...(original.claims||[]),...(a.claims||[])]} : original
})
const reasons = computed(() => data.value.reasons || [])
const selected = computed(() => reasons.value.find(r => r.reason_id === selectedId.value))
const selectedClaims = computed(() => (data.value.claims || []).filter(c => selected.value?.claim_ids?.includes(c.claim_id) && claimCategory(c) !== 'observation'))
const observation = computed(() => observationFor(data.value, selected.value, props.retrieve, props.result))
const semanticCards = computed(() => assessedCards(data.value, selected.value))
const cards = computed(() => data.value.assessment?.schema_version === 1
  ? uniqueArticles(semanticCards.value.filter(card => card.assessment.relevance === 'direct' && card.assessment.assessment_status === 'validated' && ['supports','refutes'].includes(card.assessment.stance)))
  : [])
const sources = computed(() => searchSources(data.value, props.result, props.retrieve))
function uniqueArticles(items) {
  const seen=new Set()
  return items.filter(s=>{const key=s.article_text_hash||s.article_text_sha256||s.article_id||s.source_id; if(seen.has(key))return false;seen.add(key);return true})
}
const remainingSources = computed(() => uniqueArticles(otherSearchSources(sources.value, cards.value).map(source => {
  const assessments = semanticCards.value.filter(card => card.source_id === source.source_id)
  return assessments.length ? { ...source, ...assessments[0], assessment_records: assessments.map(card => card.assessment),
    assessment: assessments[0].assessment } : source
})).filter(s=>!cards.value.some(c=>(c.article_text_hash||c.article_text_sha256||c.article_id||c.source_id)===(s.article_text_hash||s.article_text_sha256||s.article_id||s.source_id))))
const backgroundSources = computed(()=>remainingSources.value.filter(s=>{
  let host='';try{host=new URL(s.resolved_url||s.source_url).hostname}catch{}
  return s.retrieval_status==='fetched' && s.article_text && s.source_kind!=='youtube' && !['search_page','youtube'].includes(s.source_type) && !['google.com','www.google.com','consent.google.com','vertexaisearch.cloud.google.com','youtube.com','www.youtube.com','youtu.be'].includes(host)
}).sort((a,b)=>(a.assessment?.relevance==='contextual'?0:a.assessment?2:1)-(b.assessment?.relevance==='contextual'?0:b.assessment?2:1)))
const otherSources = computed(()=>remainingSources.value.filter(s=>!backgroundSources.value.includes(s)))
const timestamp = computed(() => reliableTimestamp(selected.value))
watch(batchKey, () => { selectedId.value = null }, { flush: 'sync' })
function selectReason(reason) {
  selectedId.value = reason.reason_id
}
function categoryLabel(claim) {
  return ({ observation: tr('影片觀察（模型整理）', 'Video observation (model refinement)'),
    claim: tr('待查核主張（模型整理）', 'Claim to check (model refinement)'),
    model: tr('模型背景知識（非外部證據）', 'Model background (not external evidence)'),
    synthesis: tr('搜尋資訊的模型整理（非來源原文）', 'Model synthesis of search (not source text)') })[claimCategory(claim)] || tr('類別尚未確認', 'Category unconfirmed')
}
function observationLabel(kind) {
  return ({ visual: tr('影片觀察（模型整理的影像描述）', 'Video observation (model-generated visual description)'),
    transcript: tr('影片觀察（語音轉錄，非字幕辨識）', 'Video observation (speech transcript, not subtitle recognition)'),
    input: tr('原始模型輸入（整理後文字）', 'Original model input (refined text)') })[kind]
}
</script>

<style scoped>
.evidence-panel { margin-top: 16px; padding: 14px; border: 1px solid #c4b5fd; border-radius: 8px; background: #f2f7ff; color: #323545; }
.reason-options { display: grid; gap: 8px; margin: 12px 0; padding: 0; list-style: none; }
.reason-options li { min-width: 0; }
.reason-options button { display: grid; gap: 6px; width: 100%; min-width: 0; overflow-wrap: anywhere; }
button { text-align: left; white-space: pre-wrap; padding: 12px; border: 1px solid #bca8ff; border-radius: 8px; background: white; color: #4c3a72; cursor: pointer; font: inherit; }
button[aria-pressed="true"] { background: #ede7ff; border-color: #7657d6; }
button:focus-visible, a:focus-visible, summary:focus-visible { outline: 3px solid #7657d6; outline-offset: 2px; }
.evidence-columns { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr) minmax(0, 1fr); gap: 14px; }
.evidence-columns > section, .evidence-card { min-width: 0; background: #ffffffb8; padding: 12px; border: 1px solid #c4b5fd; border-radius: 8px; }
.evidence-card { margin-top: 10px; }
p, blockquote { line-height: 1.65; overflow-wrap: anywhere; margin: 8px 0; }
.original, blockquote { white-space: pre-wrap; }
.notice { font-size: 13px; color: #666073; }
.evidence-status { margin: 12px 0; padding: 12px; border: 1px solid #c4b5fd; border-radius: 8px; background: #f3edff; overflow-wrap: anywhere; }
a { color: #4c1d95; font-weight: 700; overflow-wrap: anywhere; }
video { width: 100%; max-height: 300px; }
h4 { margin: 0 0 12px; }
.badge { display: inline-block; border-radius: 8px; background: #ede7ff; padding: 3px 8px; font-size: 13px; }
blockquote { border-left: 3px solid #7657d6; padding-left: 10px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 220px; overflow: auto; font-size: 12px; }
.hash { overflow-wrap: anywhere; font-size: 11px; }
.unmapped { margin-top: 12px; }
summary { cursor: pointer; }
@media (max-width: 820px) { .evidence-columns { grid-template-columns: minmax(0, 1fr); } }
.evidence-panel { margin: 0; padding: 0; border: 0; background: transparent; }
.reason-workspace { display: grid; grid-template-columns: minmax(220px, 0.85fr) minmax(0, 2fr); gap: 28px; align-items: start; }
.reason-selector { min-width: 0; }
.evidence-columns { grid-template-columns: minmax(0, 1fr); gap: 20px; }
.evidence-columns > section { border: 0; border-bottom: 1px solid #e0e3ec; border-radius: 0; padding: 0 0 20px; background: transparent; }
.reason-options button { border-color: #d8dce6; }
.reason-options button[aria-pressed="true"] { border-color: #7657d6; }
.evidence-status { background: #f8f6ef; border-color: #dfd5b6; padding: 8px 10px; font-size: 13px; }
.other-sources { margin-top: 16px; min-width: 0; }
.other-sources > summary { font-weight: 700; color: #4c3a72; padding: 10px 0; overflow-wrap: anywhere; }
@media (max-width: 820px) { .reason-workspace { grid-template-columns: minmax(0, 1fr); } }
</style>
