<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
const props=defineProps({versionId:String,request:Function})
const state=ref(null),busy=ref(false),confirmed=ref(false),error=ref('')
let epoch=0
onBeforeUnmount(()=>epoch++)
const safeUrl=url=>{try{const u=new URL(url);return ['http:','https:'].includes(u.protocol)?u.href:null}catch{return null}}
async function load(execute=false,retry=false){
 if(busy.value || (execute && !confirmed.value))return
 const token=epoch,id=props.versionId;busy.value=true;error.value=''
 try{const value=await props.request(`/versions/${id}/grounded-explanation`,execute?{method:'POST',body:JSON.stringify({confirm_cost:true,...(retry?{retry_of:state.value?.attempt_id}:{})})}:{});if(token===epoch){state.value=value;confirmed.value=false}}
 catch(e){if(token===epoch)error.value=e.message}
 finally{if(token===epoch)busy.value=false}
}
watch(()=>props.versionId,()=>{epoch++;state.value=null;busy.value=false;confirmed.value=false;load()},{immediate:true})
</script>
<template>
 <section class="grounded-explanation" aria-label="Evidence-grounded Explanation">
  <h3>Evidence-grounded Explanation · 證據支撐式解釋</h3>
  <p>獨立 Gemini 事後核對，不是 Student 原始推理，也不能證明 Student 實際依賴某篇新聞。Support／Contradict 針對下列主張，不代表影片真偽。</p>
  <details v-if="state?.plan"><summary>核對範圍</summary><p>最多核對 {{ state.plan.claim_count }} 個原始理由片段、{{ state.plan.article_count }} 篇已核准來源；最多 {{ state.plan.max_calls }} 次呼叫，每篇前 {{ state.plan.max_source_chars }} 字。複合主張及未涵蓋全文可能證據不足。略過理由：{{ state.plan.omitted_claims }}。</p></details>
  <p v-if="state?.explanation">{{ state.explanation }}</p>
  <label v-if="state?.available && (!state.assessment || state.retry_available)"><input type="checkbox" v-model="confirmed" :disabled="busy" />確認執行證據核對</label>
  <button v-if="!state?.assessment" type="button" :disabled="busy || !confirmed || !state?.available || state?.status==='running'" @click="load(true)">核對 Student 理由與新聞證據</button>
  <button v-if="state?.assessment && state.retry_available" type="button" :disabled="busy || !confirmed || !state.available" @click="load(true,true)">重新評估</button>
  <button type="button" :disabled="busy" @click="load()">讀取已保存結果</button>
  <p role="status">{{ busy ? '讀取／核對中' : state?.status }}</p><p v-if="error" role="alert">{{ error }}</p>
  <p v-if="state && !state.items?.some(i=>i.relation!=='Insufficient Evidence')">尚無足夠來源支持此判斷理由</p>
  <p v-if="state?.support_summary?.supported_claims">{{ state.support_summary.notice }}（{{ state.support_summary.supported_claims }}/{{ state.support_summary.evaluated_claims }} 個核對主張）。</p>
  <article v-for="(item,index) in state?.items || []" :key="index">
   <p>待核查主張：{{ item.claim }}</p><p v-if="item.unresolved_subject">原文省略主詞，未自行補寫：保守標示證據不足。</p>
   <p>[{{ item.source_id }}] <a v-if="safeUrl(item.url)" :href="safeUrl(item.url)" target="_blank" rel="noopener noreferrer">{{ item.title || '文章標題未提供' }}</a><span v-else>{{ item.title || '來源網址不可用' }}</span> · {{ item.relation }}</p>
   <p v-if="item.relation!=='Insufficient Evidence'">AI 核對結果：[{{ item.source_id }}] 的下列原文{{ item.relation==='Support'?'支持':'反駁' }}上述主張。</p>
   <p>Semantic Relation（獨立語意評估）：{{ item.semantic_relation || 'Insufficient' }} · Quote Verification：{{ item.quote_verification || '未驗證' }} · Evidence Coverage：{{ item.evidence_coverage || 'insufficient' }}</p>
   <p v-if="item.quote_verification==='validation_failed'">引文未驗證，不呈現為已確認支持／反駁。{{ item.validation_error }}</p>
   <p v-if="item.quote">{{ item.quote_reasoning }}</p>
   <blockquote v-if="item.quote">{{ item.quote }}</blockquote>
   <p>保存正文：{{ item.content_quality }} · 評估覆蓋：{{ item.coverage || 'none' }} · {{ item.assessment_status }}</p>
   <details><summary>AI 判斷說明與原文位置（不是原文事實驗證）</summary><p>{{ item.explanation }}</p><pre>{{ JSON.stringify(item,null,2) }}</pre></details>
  </article>
  <details v-if="state?.assessment"><summary>模型、輸入與完整評估紀錄</summary><pre>{{ JSON.stringify(state.assessment,null,2) }}</pre></details>
 </section>
</template>
<style scoped>
.grounded-explanation{margin:20px 0;min-width:0;overflow-wrap:anywhere}article{border-top:1px solid #dbe3ec;padding:12px 0}button{padding:8px;margin:6px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere;max-height:400px;overflow:auto}label{display:block}:focus-visible{outline:3px solid #7657d6}
</style>
