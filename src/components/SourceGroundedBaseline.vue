<script setup>
import {ref,watch,onBeforeUnmount} from 'vue'
const props=defineProps({version:Object,request:Function,busy:Boolean,locale:String})
const emit=defineEmits(['submit'])
const preview=ref(null),loading=ref(false),error=ref(''),confirmed=ref(false)
const tr=(zh,en)=>props.locale==='en'?en:zh
let generation=0
onBeforeUnmount(()=>generation++)
watch(()=>props.version?.version_id,async()=>{
  const epoch=++generation;preview.value=null;error.value='';confirmed.value=false;loading.value=false
  if(props.version?.status!=='succeeded')return
  loading.value=true
  try{const result=await props.request(`/versions/${props.version.version_id}/source-grounded-preview`);if(epoch===generation)preview.value=result}
  catch(e){if(epoch===generation)error.value=e.message}
  finally{if(epoch===generation)loading.value=false}
},{immediate:true})
</script>
<template>
  <article class="source-grounded-panel">
    <h3>{{ tr('建立 Source-grounded Baseline','Create Source-grounded Baseline') }}</h3>
    <p v-if="loading">{{ tr('讀取來源預覽中','Loading source preview') }}</p>
    <p v-if="preview?.manifest">{{ tr('合格去重文章','Eligible unique articles') }}: {{ preview.manifest.eligible_article_count }} · {{ tr('選入','Selected') }}: {{ preview.manifest.units.length }} · K_ext: {{ preview.manifest.k_ext_length }} {{ tr('字元','characters') }}</p>
    <ul v-if="preview?.manifest"><li v-for="s in preview.manifest.selection_records" :key="s.source_index">{{ s.article_title || s.resolved_url || s.source_id }} · {{ s.selection_status }} · {{ s.selection_reason }}</li></ul>
    <details v-if="preview?.manifest"><summary>{{ tr('正文範圍、K_ext 預覽與組裝 manifest','Article ranges, K_ext preview and assembly manifest') }}</summary>
      <p v-for="u in preview.manifest.units" :key="u.evidence_unit_id">{{ u.source_id }} · article_text[{{ u.provenance.start }}:{{ u.provenance.end }}] / {{ u.provenance.article_length }}</p>
      <pre>{{ preview.manifest.k_ext }}</pre><pre>{{ JSON.stringify(preview.manifest,null,2) }}</pre>
    </details>
    <p v-if="!preview?.available && !loading">{{ error || preview?.error || tr('不可建立：需要成功父版本及可驗證正文。','Unavailable: requires a successful parent and verified article text.') }}</p>
    <label><input v-model="confirmed" type="checkbox" :disabled="busy || loading || !preview?.available" />{{ tr('確認來源與範圍','Confirm sources and ranges') }}</label>
    <button type="button" :disabled="busy || loading || !preview?.available || !confirmed" @click="emit('submit',{parent_version_id:version.version_id,manifest_hash:preview.manifest.manifest_hash,confirm:true})">{{ busy ? tr('版本執行中','Version running') : tr('建立 Source-grounded Baseline 並重新判斷','Create Source-grounded Baseline and rerun') }}</button>
  </article>
</template>
<style scoped>
.source-grounded-panel{margin-top:20px;min-width:0;overflow-wrap:anywhere;}label{display:block;margin:10px 0;}button{padding:10px;}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:400px;overflow:auto;}:focus-visible{outline:3px solid #7657d6;}
</style>
