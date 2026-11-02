<script setup>
import {ref,watch,onBeforeUnmount} from 'vue'
const props=defineProps({version:Object,request:Function,busy:Boolean,locale:String})
const emit=defineEmits(['submit'])
const preview=ref(null),error=ref(''),confirmed=ref(false),costConfirmed=ref(false),loading=ref(false)
const tr=(zh,en)=>props.locale==='en'?en:zh
let generation=0,timer=null
onBeforeUnmount(()=>{generation++;clearTimeout(timer)})
async function load(action='',body=null) {
 const epoch=generation,id=props.version?.version_id
 if(!id || props.version?.status!=='succeeded' || loading.value)return
 loading.value=true;error.value='';clearTimeout(timer)
 try{
  const data=await props.request(`/versions/${id}/${action || 'source-aware-preview'}`,body?{method:'POST',body:JSON.stringify(body)}:{})
  if(epoch!==generation)return
  preview.value=data;confirmed.value=false
  if(action==='source-summaries')costConfirmed.value=false
  if(data.summary_status==='running')timer=setTimeout(()=>load(),2500)
 }catch(e){if(epoch===generation)error.value=e.message}
 finally{if(epoch===generation)loading.value=false}
}
async function generate() {
 if(!costConfirmed.value)return
 const retry=preview.value.retry_available
 await load('source-summaries',{confirm_cost:true,cache_key:preview.value.cache_key,
   ...(retry?{retry_of:preview.value.attempt_id,acknowledge_retry_cost:true}:{})})
}
async function review(card,decision) {
 await load('source-summary-review',{source_id:card.source_id,decision,attempt_id:preview.value.attempt_id,review_revision:preview.value.review_revision})
}
watch(()=>props.version?.version_id,()=>{
 generation++;clearTimeout(timer);preview.value=null;confirmed.value=false;costConfirmed.value=false;error.value='';loading.value=false;load()
},{immediate:true})
</script>
<template>
 <article class="source-aware-panel">
  <p v-if="preview?.plan">{{ preview.plan.model }} · {{ preview.plan.article_count }} {{ tr('篇保存正文；一次批次請求，不搜尋或重新擷取。','saved articles; one batch request, no search or refetch.') }}</p>
  <p role="status">{{ loading ? tr('處理中','Processing') : preview?.summary_status }} {{ error || preview?.error }}</p>
  <button type="button" :disabled="loading" @click="load()">{{ tr('重新讀取已保存結果（不呼叫模型）','Reload saved results (no model call)') }}</button>
  <template v-if="preview?.generation_available && (preview.summary_status==='not_generated' || preview.retry_available)">
   <label><input v-model="costConfirmed" type="checkbox" :disabled="busy || loading" />{{ tr('確認生成摘要','Confirm summary generation') }}</label>
   <button type="button" :disabled="!costConfirmed || busy || loading" @click="generate">{{ preview.retry_available ? tr('重試摘要','Retry summaries') : tr('生成逐篇摘要（一次 Gemini 呼叫）','Generate summaries (one Gemini call)') }}</button>
  </template>
  <div v-for="card in preview?.manifest?.news_cards || []" :key="card.source_id" class="news-card">
   <strong>{{ card.source_id }} · {{ card.title || tr('標題未提供','Title unavailable') }}</strong>
   <p>{{ card.summary || tr('摘要不可用：尚未生成或驗證失敗。','Summary unavailable: not generated or validation failed.') }}</p>
   <p>{{ tr('AI 生成，尚未完成事實驗證','AI generated, not independently fact-verified') }} · {{ card.quote_validation?.status || 'unavailable' }} · {{ card.review?.decision || 'manual_review_required' }}</p>
   <p v-if="card.content_quality==='partial_article'">{{ tr('僅依據已保存的部分正文','Based only on saved partial article text') }}</p>
   <a v-if="card.url_valid" :href="card.url" target="_blank" rel="noopener noreferrer">{{ tr('開啟來源','Open source') }}</a>
   <details v-if="card.quote_validation?.source_excerpt || card.quote_validation?.model_quote"><summary>{{ tr('核對原文引文','Inspect supporting quote') }}</summary>
    <blockquote>{{ card.quote_validation.source_excerpt || card.quote_validation.model_quote }}</blockquote>
    <pre>{{ JSON.stringify(card.quote_validation,null,2) }}</pre>
   </details>
   <button type="button" :disabled="!card.can_review || loading || busy" @click="review(card,'approved')">{{ tr('核准此摘要','Approve this summary') }}</button>
   <button type="button" :disabled="!preview?.attempt_id || loading || busy" @click="review(card,'excluded')">{{ tr('排除此摘要','Exclude this summary') }}</button>
  </div>
  <details v-if="preview?.fallback_cards?.length"><summary>{{ tr('其他 Grounding News Cards（無合格正文或未選入）','Other Grounding News Cards (no eligible body or not selected)') }} ({{ preview.fallback_cards.length }})</summary>
   <div v-for="card in preview.fallback_cards" :key="card.source_id" class="news-card"><strong>{{ card.title || tr('標題未提供','Title unavailable') }}</strong>
    <p>{{ tr('摘要不可用，未納入此摘要實驗。','Summary unavailable; not part of this summary experiment.') }}</p>
    <a v-if="card.url_valid" :href="card.url" target="_blank" rel="noopener noreferrer">{{ tr('開啟 Grounding 來源','Open Grounding source') }}</a>
   </div>
  </details>
  <details v-if="preview?.manifest"><summary>{{ tr('已核准 K_ext 預覽與來源 manifest','Approved K_ext preview and source manifest') }}</summary><pre>{{ preview.manifest.k_ext || tr('尚無核准摘要','No approved summaries') }}</pre><pre>{{ JSON.stringify(preview.manifest,null,2) }}</pre></details>
  <label><input v-model="confirmed" type="checkbox" :disabled="!preview?.available || busy || loading" />{{ tr('確認已核准摘要與 K_ext','Confirm approved summaries and K_ext') }}</label>
  <button type="button" :disabled="!preview?.available || !confirmed || busy || loading" @click="emit('submit',{experiment_type:'source_aware_baseline',parent_version_id:version.version_id,manifest_hash:preview.manifest.manifest_hash,confirm:true})">{{ tr('建立 Source-aware 版本並重新判斷','Create Source-aware version and rerun') }}</button>
 </article>
</template>
<style scoped>
.source-aware-panel{margin-top:20px;min-width:0;overflow-wrap:anywhere}.news-card{border-top:1px solid #dbe3ec;padding:12px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:400px;overflow:auto}blockquote{white-space:pre-wrap;overflow-wrap:anywhere}label{display:block;margin:10px 0}button{padding:10px;margin:4px}:focus-visible{outline:3px solid #7657d6}
</style>
