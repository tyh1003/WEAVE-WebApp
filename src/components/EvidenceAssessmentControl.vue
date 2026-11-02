<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import EvidenceSourceCard from './EvidenceSourceCard.vue'
import { assessedCards } from '../evidence.js'
const selectedClaim=ref('')
const cards=computed(()=> {
 const a=state.value?.assessment
 return a ? assessedCards({...a, assessment:a, sources:state.value.sources || [], claims:a.claims || []}, {reason_id:selectedClaim.value}) : []
})
const props = defineProps({ versionId:String, request:Function, locale:String })
const emit = defineEmits(['assessment'])
const state=ref(null), busy=ref(false), confirmed=ref(false), error=ref('')
const tr=(zh,en)=>props.locale==='en'?en:zh
let generation=0
onBeforeUnmount(()=>{generation++})
async function load(execute=false) {
  const id=props.versionId, epoch=generation
  if (!id || busy.value) return
  busy.value=true;error.value=''
  try {
    const response=await props.request(`/versions/${id}/evidence-assessment`,execute?{method:'POST',body:JSON.stringify({confirm_cost:true})}:{})
    if(epoch!==generation)return
    state.value=response; if (!response.claims?.some(c=>c.claim_id===selectedClaim.value)) selectedClaim.value=response.claims?.[0]?.claim_id || '';emit('assessment',response.assessment)
  } catch(e) {if(epoch===generation)error.value=e.message}
  finally {if(epoch===generation)busy.value=false}
}
watch(()=>props.versionId,()=>{generation++;state.value=null;busy.value=false;confirmed.value=false;error.value='';emit('assessment',null);load()}, {immediate:true})
</script>
<template>
  <section class="assessment-control" aria-label="Evidence assessment">
    <p>{{ tr('獨立 AI 來源語意評估，不改變 Student 判斷。','Independent AI evidence assessment; Student judgment is unchanged.') }}</p>
    <p v-if="state?.plan">{{ tr('待核查理由／主張','Reason segments / claims') }} {{ state.plan.claim_count }} · {{ tr('去重且有可驗證正文的文章','Unique verified articles') }} {{ state.plan.article_count }} · {{ tr('預計配對','Planned pairs') }} {{ state.plan.pair_count }} · {{ tr('最多呼叫','Maximum calls') }} {{ state.plan.max_calls }}</p>
    <details v-if="state?.plan"><summary>{{ tr('評估範圍','Assessment scope') }}</summary><p>{{ tr('每次交錯選取 Rc／Rv／K_ext 最多 3 段待核查原文、2 篇文章；非自動確認的事實，也不代表涵蓋全部主張或全文。','Up to 3 unverified Rc/Rv/K_ext segments and 2 articles; claims and full articles may not be fully covered.') }}</p>
    <p v-if="state?.plan?.model_name">{{ state.plan.model_name }} · {{ tr('每篇最多評估字元','Maximum reviewed characters per article') }} {{ state.plan.max_source_chars }} · {{ tr('每次輸出 token 上限','Output token limit per call') }} {{ state.plan.max_output_tokens }}</p></details>
    <p v-if="state && !state.available">{{ tr('評估設定不可用。','Assessment configuration unavailable.') }}</p>
    <label><input v-model="confirmed" type="checkbox" :disabled="!state?.available || busy" />{{ tr('確認執行評估','Confirm assessment') }}</label>
    <button type="button" :disabled="busy || !confirmed || !state?.available" @click="load(true)">{{ busy ? tr('讀取／評估中','Loading / assessing') : tr('分析來源與理由關聯','Assess sources against reasons') }}</button>
    <p v-if="state" role="status">{{ state.status }}</p><p v-if="error" role="alert">{{ error }}</p>
    <label v-if="state?.claims?.length">{{ tr('待核查原文主張（未確認與 Student 理由直接對應）','Unverified field claim (not mapped to a Student reason)') }}
      <select v-model="selectedClaim"><option v-for="claim in state.claims" :key="claim.claim_id" :value="claim.claim_id">{{ claim.claim_provenance.field }} · {{ claim.claim_text }}</option></select>
    </label>
    <p v-if="state?.assessment && !cards.some(c=>c.assessment.assessment_status==='validated' && ['supports','refutes'].includes(c.assessment.stance))">{{ tr('目前沒有已驗證的直接支持／反駁來源。','No verified direct support or refutation currently available.') }}</p>
    <EvidenceSourceCard v-for="(card,index) in cards" :key="`${selectedClaim}-${card.source_id}-${index}`" :source="card" :locale="locale" />
    <details v-if="state?.assessment"><summary>{{ tr('評估紀錄與限制','Assessment records and limits') }}</summary><pre>{{ JSON.stringify(state.assessment,null,2) }}</pre></details>
  </section>
</template>
<style scoped>
select {max-width:100%; width:100%;} .assessment-control { margin:12px 0; overflow-wrap:anywhere; } label {display:block;margin:8px 0;} button {padding:10px;} pre {white-space:pre-wrap;overflow-wrap:anywhere;max-height:400px;overflow:auto;} :focus-visible{outline:3px solid #7657d6;}
</style>
