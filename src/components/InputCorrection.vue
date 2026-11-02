<script setup>
import { computed, reactive, ref, watch } from 'vue'
import EvidenceText from './EvidenceText.vue'
const props = defineProps({ version:Object, busy:Boolean, locale:String, translations:Object })
const emit=defineEmits(['submit'])
const fields=['Rc','Rv','transcript']
const originals=reactive({}), drafts=reactive({})
const confirmed=ref(false),sending=ref(false),copyMessage=ref('')
const ui=(zh,en)=>props.locale==='en'?en:zh
function initialize(){
 for(const key of fields){
  const value=key==='transcript'?props.version?.output_snapshot?.preprocess?.transcript:props.version?.output_snapshot?.retrieve?.[key]
  originals[key]=typeof value==='string'?value:null;drafts[key]=originals[key]??''
 }
 confirmed.value=false;sending.value=false;copyMessage.value=''
}
watch(()=>props.version?.version_id,initialize,{immediate:true})
// A selected pending version may acquire its first saved values without changing ID.
watch(()=>[props.version?.output_snapshot?.retrieve?.Rc,props.version?.output_snapshot?.retrieve?.Rv,props.version?.output_snapshot?.preprocess?.transcript],()=>{if(!changed.value.length)initialize()})
watch(()=>fields.map(k=>drafts[k]),()=>{confirmed.value=false})
const changed=computed(()=>fields.filter(k=>originals[k]!==null && drafts[k]!==originals[k]))
const availableFields=computed(()=>['Rc','Rv'].filter(k=>typeof originals[k]==='string' && originals[k].trim()))
const hasInput=computed(()=>availableFields.value.length || !!originals.transcript?.trim())
const editable=k=>props.version?.status==='succeeded' && typeof originals[k]==='string' && !!originals[k].trim()
const valid=computed(()=>{
 const key=changed.value[0]
 return changed.value.length===1 && editable(key) && drafts[key].trim() && drafts[key].length<=100000 && drafts[key].trim()!==originals[key].trim() && !props.busy && !sending.value
})
function restore(key){for(const k of key?[key]:fields)drafts[k]=originals[k]??'';confirmed.value=false}
function submit(){
 if(!valid.value)return
 sending.value=true
 const field=changed.value[0]
 emit('submit',{parent_version_id:props.version.version_id,field,value:drafts[field]})
}
function canLeave(){
 if(!changed.value.length)return true
 return typeof window.confirm==='function' && window.confirm(ui('有未儲存的 Rc／Rv／轉錄修正。切換版本將捨棄這些草稿，是否繼續？','Unsaved Rc/Rv/transcript edits will be discarded when switching versions. Continue?'))
}
function submitted(payload){
 if(payload.parent_version_id===props.version?.version_id && drafts[payload.field]===payload.value)restore(payload.field)
}
async function copy(key){
 const id=props.version?.version_id
 try{await navigator.clipboard.writeText(originals[key]||'');if(id===props.version?.version_id)copyMessage.value=ui('已複製','Copied')}
 catch{if(id===props.version?.version_id)copyMessage.value=ui('無法複製，請手動選取原文。','Copy unavailable; select the original manually.')}
}
defineExpose({canLeave,submitted,finishSubmission:()=>{sending.value=false}})
</script>
<template>
 <article class="correction-panel">
  <template v-if="hasInput">
  <div v-for="key in availableFields" :key="key" class="inline-field">
   <label :for="`draft-${key}`"><strong>{{ key }} · {{ key==='Rc'?ui('文字內容','Text Content'):ui('影像描述','Visual Description') }}</strong> · {{ ui('可編輯草稿','Editable draft') }}</label>
   <textarea :id="`draft-${key}`" v-model="drafts[key]" :disabled="!editable(key) || busy || sending" rows="6" maxlength="100000" :aria-label="key" />
   <p v-if="!editable(key)">{{ ui('此版本無可修正的已完成文字資料。','No editable completed text for this version.') }}</p>
   <button type="button" class="secondary" :disabled="busy || sending || drafts[key]===(originals[key]??'')" @click="restore(key)">{{ ui('還原此欄','Restore field') }}</button>
   <details><summary>{{ ui('保存原文／翻譯（唯讀）','Saved original / translation (read only)') }}</summary><EvidenceText :text="originals[key]||''" :locale="locale" /><button type="button" class="secondary" :disabled="!originals[key]" @click="copy(key)">{{ ui('複製原始內容','Copy original text') }}</button><EvidenceText v-if="locale==='en' && translations?.[key]" :text="translations[key]" :locale="locale" /></details>
  </div>
  <details v-if="originals.transcript" class="transcript-correction"><summary>{{ ui('原始語音轉錄 transcript 修正','Original transcript correction') }}</summary><textarea v-model="drafts.transcript" :disabled="!editable('transcript') || busy || sending" rows="6" maxlength="100000" aria-label="transcript" /><EvidenceText :text="originals.transcript||''" :locale="locale" /><button type="button" class="secondary" :disabled="busy || sending" @click="restore('transcript')">{{ ui('還原轉錄','Restore transcript') }}</button></details>
  <p role="status">{{ changed.length?ui('未提交修正：','Unsaved edits: ')+changed.join(', '):ui('沒有未提交修正','No unsaved edits') }}</p>
  <p v-if="changed.length>1" role="alert">{{ ui('既有流程每次只接受一個欄位。請還原其他欄位，再提交；不會自動建立多個版本。','The existing workflow accepts one field per version. Restore the other fields before submitting; no versions are created automatically.') }}</p>
  <p>{{ ui('修正由使用者提供，未經獨立驗證。重新執行 Retrieve 與 Student；保留原版本。','User corrections are not independently verified. Reruns Retrieve and Student and preserves the original version.') }}</p>
  <details v-if="changed.length"><summary>{{ ui('差異預覽：修正前／修正後','Change preview: before / after') }}</summary><div v-for="key in changed" :key="key"><strong>{{ key }}</strong><pre>{{ originals[key] }}</pre><pre>{{ drafts[key] }}</pre></div></details>
  <button type="button" class="correction-submit" :disabled="!valid" @click="submit">{{ busy || sending?ui('執行中','Running'):ui('建立新版本並重新分析','Create version and rerun') }}</button>
  <button type="button" class="secondary" :disabled="busy || sending || !changed.length" @click="restore()">{{ ui('還原所有草稿','Restore all drafts') }}</button>
  <span role="status">{{ copyMessage }}</span>
 </template>
 </article>
</template>
<style scoped>
.correction-panel{min-width:0}.inline-field{margin-bottom:16px}label,details{display:block;margin:8px 0}textarea{display:block;width:100%;box-sizing:border-box;font:inherit;min-height:9em;resize:vertical;white-space:pre-wrap;overflow-wrap:anywhere;padding:10px;border:1px solid #c9c1db;border-radius:6px}pre{white-space:pre-wrap;overflow-wrap:anywhere}button{padding:8px 12px}.secondary{padding:3px 7px;font-size:.85em;background:transparent;border:1px solid #c9c1db;border-radius:5px;margin:4px}p,span{overflow-wrap:anywhere}:focus-visible{outline:3px solid #2968ad;outline-offset:2px}
.correction-submit{background:#7050b1;color:white;border:0;border-radius:10px;padding:14px 20px;font:inherit;font-weight:600;min-height:46px}button:disabled{opacity:.55;cursor:not-allowed}
</style>
