<script setup>
import { ref, watch } from 'vue'
const props=defineProps({versionId:String,request:Function,locale:String})
const data=ref(null),error=ref(''),busy=ref(false)
let generation=0
const ui=(zh,en)=>props.locale==='en'?en:zh
watch(()=>props.versionId,()=>{generation++;data.value=null;error.value='';busy.value=false})
async function load(){
 if(busy.value || !props.versionId)return
 const scope=generation;busy.value=true;error.value=''
 try{const value=await props.request(`/versions/${encodeURIComponent(props.versionId)}/runtime-profile`);if(scope===generation)data.value=value}
 catch{if(scope===generation)error.value=ui('無法讀取執行紀錄','Runtime profile unavailable')}
 finally{if(scope===generation)busy.value=false}
}
const seconds=v=>typeof v==='number'?`${v.toFixed(2)} s`:'—'
function download(format){
 const rows=[['metric','value']]
 function flatten(value,key=''){if(value && typeof value==='object' && !Array.isArray(value)){for(const [k,v] of Object.entries(value))flatten(v,key?`${key}.${k}`:k)}else rows.push([key,value==null?'':JSON.stringify(value)])}
 flatten(data.value)
 const content=format==='json'?JSON.stringify(data.value,null,2):rows.map(row=>row.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n')
 const url=URL.createObjectURL(new Blob([content],{type:format==='json'?'application/json':'text/csv;charset=utf-8'}))
 const link=document.createElement('a');link.href=url;link.download=`WEAVE-${props.versionId}-runtime.${format}`;link.click();URL.revokeObjectURL(url)
}
</script>
<template>
 <details><summary>{{ ui('單案例執行效能','Single-case runtime profile') }}</summary>
  <button type="button" :disabled="busy || !versionId" @click="load">{{ busy?ui('讀取中','Loading'):ui('讀取／更新紀錄','Load / refresh profile') }}</button>
  <p v-if="error" role="alert">{{ error }}</p>
  <template v-if="data">
   <p v-if="data.availability!=='recorded'">{{ ui('此歷史版本未記錄效能資料。','Profiling was not recorded for this historical version.') }}</p>
   <p>Preprocess {{ seconds(data.latency_seconds?.preprocess) }} · Retrieve {{ seconds(data.latency_seconds?.retrieve) }} · Student {{ seconds(data.latency_seconds?.student) }}</p>
   <p>{{ ui('驗證總時間','Verification total') }}: {{ seconds(data.total_verification_seconds) }} · {{ ui('獨立摘要處理','Separate summarization') }}: {{ seconds(data.automatic_summarization?.processing_seconds) }}</p>
   <small>{{ ui('階段時間包含模型載入；未取得的數值顯示 —。','Stage time includes model loading. Missing measurements show —.') }}</small>
   <div><button @click="download('json')">JSON</button><button @click="download('csv')">CSV</button></div>
   <details><summary>{{ ui('硬體、呼叫數與 token 詳細資料','Hardware, call counts and token details') }}</summary><pre>{{ JSON.stringify(data,null,2) }}</pre></details>
  </template>
 </details>
</template>
<style scoped>pre{white-space:pre-wrap;overflow-wrap:anywhere}button{margin:6px;padding:6px 10px}p{line-height:1.6;overflow-wrap:anywhere}</style>
