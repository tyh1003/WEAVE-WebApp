<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { unifiedNews, summaryReader, newsSelection, newsPreview } from '../workspaceNews.js'
import { evidenceView,searchSources,safeUrl,verifiedExcerpt } from '../evidence.js'
const props=defineProps({version:Object,result:Object,retrieve:Object,locale:String,experimentId:String,request:Function,summaryEnabled:Boolean,submit:Function,busy:Boolean,rerunError:String})
const ui=(zh,en)=>props.locale==='en'?en:zh
const sources=computed(()=>searchSources(evidenceView(props.result,props.retrieve),props.result,props.retrieve))
const summaries=computed(()=>{
 const saved=props.version?.source_aware_manifest?.news_cards || props.retrieve?.news_cards || []
 const manifest=props.version?.selected_news_manifest
 if(props.version?.experiment_type!=='selected_news' || !Array.isArray(manifest?.units) || manifest.parent_version_id!==props.version.parent_version_id || manifest.k_ext!==props.version.output_snapshot?.retrieve?.K_ext)return saved
 return [...manifest.units.map(unit=>({...unit,summary_origin:'selected_automatic_summary'})),...saved]
})
const summaryState=ref({status:'unavailable',job:null,error:null})
const reader=summaryReader({request:(...args)=>props.request(...args),onChange:value=>{summaryState.value=value}})
watch([()=>props.experimentId,()=>props.version?.version_id,()=>props.summaryEnabled],([eid,vid,enabled])=>reader.start(eid,vid,enabled && !!props.request),{immediate:true})
onBeforeUnmount(()=>reader.stop())
const refresh=()=>reader.start(props.experimentId,props.version?.version_id,props.summaryEnabled && !!props.request)
const cards=computed(()=>unifiedNews(sources.value,summaries.value,summaryState.value.job))
const selected=ref([])
const eligibleKeys=computed(()=>cards.value.map(newsSelection).map(s=>s.key).filter(Boolean))
watch([()=>props.experimentId,()=>props.version?.version_id],()=>{selected.value=[]}, {flush:'sync'})
watch(eligibleKeys,keys=>{selected.value=selected.value.filter(k=>keys.includes(k))})
const preview=computed(()=>newsPreview(cards.value,selected.value))
const submitting=ref(false),submissionError=ref(''),submissionStatus=ref('')
watch([()=>props.experimentId,()=>props.version?.version_id],()=>{submissionError.value='';submissionStatus.value='';submitting.value=false})
async function rerun(){
 if(submitting.value || props.busy || props.version?.status!=='succeeded' || !props.submit)return
 const scope=[props.experimentId,props.version.version_id].join('/')
 const picked=cards.value.map(newsSelection).filter(s=>s.key && selected.value.includes(s.key))
 submitting.value=true;submissionError.value='';submissionStatus.value=ui('提交中','Submitting')
 try{
  if(picked.some(s=>!s.identity.cache_key))throw new Error(ui('摘要快取識別不完整，請重新讀取摘要狀態','Summary cache identity is missing; reload summary status'))
  const v=await props.submit({experiment_type:'selected_news',parent_version_id:props.version.version_id,selected_sources:picked.map(s=>s.identity),confirm:true})
  if(scope!==[props.experimentId,props.version?.version_id].join('/'))return
  submissionStatus.value=v?.status==='failed'?ui('版本執行失敗','Version failed'):v?.status==='succeeded'?ui('版本已完成','Version completed'):ui('已建立版本，Student 執行中','Version created; Student is running')
  if(v?.error)submissionError.value=v.error
 }catch(error){if(scope===[props.experimentId,props.version?.version_id].join('/')){submissionError.value=error.message;submissionStatus.value=ui('提交失敗','Submission failed')}}
 finally{if(scope===[props.experimentId,props.version?.version_id].join('/'))submitting.value=false}
}
const statusLabel=s=>({completed:ui('摘要已完成','Summary completed'),pending:ui('摘要處理中','Summary processing'),running:ui('摘要處理中','Summary processing'),failed:ui('摘要產生失敗','Summary failed'),skipped:ui('摘要不可用','Summary unavailable'),partial:ui('摘要部分完成','Summaries partially completed'),ineligible:ui('無合格摘要文章','No eligible articles'),unavailable:ui('尚無自動摘要','No automatic summary'),loading:ui('讀取摘要狀態中','Loading summary status'),error:ui('摘要狀態讀取失敗','Could not load summary status')})[s] || ui('尚無自動摘要','No automatic summary')
const autoSummary=c=>c.auto?.status==='completed' ? c.auto.summary : c.saved?.summary_origin==='selected_automatic_summary' ? c.saved.summary : null
const title=c=>{const s=c.source;const value=s.article_title || c.auto?.title || c.saved?.title || s.source_title || s.title;return value && !/^(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}$/i.test(value.trim())?value:ui('文章標題未提供','Article title not provided')}
const url=s=>[s.resolved_url,s.source_url,s.original_url,s.url].map(safeUrl).find(Boolean)
const site=s=>s.source_site || (url(s)?new URL(url(s)).hostname:ui('未提供','Not provided'))
const date=s=>{const raw=s.published_date || s.published_at;if(!raw)return ui('日期未提供','Date not provided');const d=new Date(raw);return Number.isNaN(d.getTime())?raw:d.toLocaleDateString(props.locale==='en'?'en-GB':'zh-TW',{timeZone:'UTC',year:'numeric',month:'short',day:'numeric'})}
const body=s=>{if(s.retrieval_status!=='fetched' || !['full_article','partial_article'].includes(s.content_quality) || !s.article_text)return '';const excerpt=verifiedExcerpt(s);return excerpt && s.article_text.includes(excerpt)?excerpt:s.article_text}
const hasContent=c=>!!(autoSummary(c) || body(c.source))
const displayCards=computed(()=>cards.value.filter(c=>hasContent(c) || url(c.source)))
</script>
<template>
 <div class="workspace-news">
  <p v-if="!displayCards.length" class="news-empty">{{ ui('目前沒有可用的新聞來源。','No news sources are available.') }}</p>
  <template v-if="!displayCards.length && summaryState.error">
   <p role="alert">{{ summaryState.error }}</p>
   <button type="button" @click="refresh">{{ ui('重新讀取摘要狀態','Reload summary status') }}</button>
  </template>
  <template v-if="displayCards.length">
  <details class="source-notes"><summary>{{ ui('來源用途與限制','Source use and limitations') }}</summary>
   <p>{{ ui('搜尋來源不等於 Student 實際輸入，也不代表支持判斷。','Search sources are not necessarily Student inputs or supporting evidence.') }}</p>
   <p v-if="version?.parent_version_id">Parent: {{ version.parent_version_id }}</p>
  </details>
  <p v-if="!['unavailable','completed'].includes(summaryState.status)" class="summary-status" role="status">{{ statusLabel(summaryState.status) }}<span v-if="summaryState.paused">{{ ui(' · 已停止自動更新',' · Automatic refresh stopped') }}</span></p>
  <p v-if="summaryState.error" role="alert">{{ summaryState.error }}</p>
  <button v-if="summaryState.error || summaryState.paused" type="button" @click="refresh">{{ ui('重新讀取摘要狀態','Reload summary status') }}</button>

  <div v-if="eligibleKeys.length" class="selection-tools"><button type="button" :disabled="!eligibleKeys.length" @click="selected=[...new Set(eligibleKeys)]">{{ ui('全選可用新聞','Select all eligible news') }}</button> <button type="button" :disabled="!selected.length" @click="selected=[]">{{ ui('清除選取','Clear selection') }}</button></div>
  <article v-for="c in displayCards" :key="c.key" class="news-card">
   <template v-if="hasContent(c)">
    <label><input type="checkbox" :disabled="!newsSelection(c).key" v-model="selected" :value="newsSelection(c).key" :aria-label="ui('選取新聞','Select news')+': '+title(c)" />{{ ui(' 選取新聞',' Select news') }}</label>
    <h3>[{{ c.source.source_id || '—' }}] {{ title(c) }}</h3>
    <p>{{ site(c.source) }} · {{ date(c.source) }}</p>
    <template v-if="autoSummary(c)"><small>{{ ui('AI 自動摘要','AI automatic summary') }}</small><p class="full">{{ autoSummary(c) }}</p></template>
    <template v-else><small>{{ ui('新聞原文摘錄','Article excerpt') }}</small><p class="preview">{{ body(c.source).slice(0,450) }}</p></template>
    <a v-if="url(c.source)" :href="url(c.source)" target="_blank" rel="noopener noreferrer">{{ ui('閱讀原文','Read source') }}</a>
   </template>
   <a v-else :href="url(c.source)" target="_blank" rel="noopener noreferrer">{{ url(c.source) }}</a>
  </article>
  <details class="kext-preview"><summary>{{ ui('選取新聞產生的 K_ext 預覽','Selected-news K_ext preview') }}</summary>
   <pre v-if="preview">{{ preview }}</pre><p v-else>{{ ui('目前未選取新聞 · K_ext 為空','No news selected · empty K_ext') }}</p>
  </details>
  <button v-if="submit && version?.status==='succeeded'" type="button" class="news-rerun" :disabled="submitting || busy || version?.status!=='succeeded'" @click="rerun">{{ ui('使用選取新聞重新分析','Rerun with selected news') }}</button>
  <p v-if="submissionStatus || busy" role="status">{{ busy ? ui('研究版本執行中','Research version running') : submissionStatus }}</p>
  <p v-if="submissionError || rerunError" role="alert">{{ submissionError || rerunError }}</p>
 </template>
 </div>
</template>
<style scoped>
.workspace-news,article{min-width:0}article{border-top:1px solid #dbe3ec;padding:16px 0}p,h3,a,summary,blockquote{overflow-wrap:anywhere}.preview{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}.full,pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere}pre{max-height:400px;overflow:auto}h3{font-size:1rem}summary{cursor:pointer;margin-top:10px}:focus-visible{outline:3px solid #7657d6}
.news-rerun{display:block;background:#7050b1;color:white;border:0;border-radius:10px;padding:14px 20px;font:inherit;font-weight:600;margin-top:14px}button:disabled{opacity:.55;cursor:not-allowed}.selection-tools{display:flex;flex-wrap:wrap;gap:8px}.selection-tools button{padding:6px 10px;border:1px solid #ded8e7;border-radius:8px;background:#f7f5fa;color:#30283c}
</style>
