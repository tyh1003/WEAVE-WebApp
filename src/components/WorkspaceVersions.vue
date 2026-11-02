<script setup>
const props=defineProps({versions:{type:Array,default:()=>[]},selected:String,locale:{type:String,default:'en'}})
const ui=(zh,en)=>props.locale==='en'?en:zh
const status=s=>({succeeded:ui('完成','Completed'),running:ui('執行中','Running'),pending:ui('等待','Waiting'),failed:ui('失敗','Failed')})[s]||s
defineEmits(['select'])
const verdict=v=>v.output_snapshot?.student?.pred_label===0?'Real':v.output_snapshot?.student?.pred_label===1?'Fake':'—'
</script>
<template>
 <section class="workspace-versions" aria-label="Version History">
  <h2>{{ ui('版本紀錄','Version History') }}</h2>
  <p v-if="!versions.length">—</p>
  <div class="version-row">
   <article v-for="v in versions" :key="v.version_id">
    <button type="button" :aria-pressed="selected===v.version_id" @click="$emit('select',v.version_id)">
     <strong>V{{ v.version_number }} · {{ verdict(v) }}</strong><span>{{ v.experiment_type }}</span><span>{{ status(v.status) }}</span>
    </button>
    <details><summary>ID / metadata</summary><p>{{ v.version_id }}</p><p>Parent: {{ v.parent_version_id || '—' }}</p><p v-if="v.error">{{ v.error }}</p></details>
   </article>
  </div>
 </section>
</template>
<style scoped>
.workspace-versions{min-width:0}.version-row{display:flex;gap:12px;overflow-x:auto;padding:4px 4px 12px}.version-row article{flex:0 0 230px;min-width:0}button{display:grid;gap:6px;width:100%;text-align:left;font:inherit;border:1px solid #dbe3ec;border-radius:8px;padding:12px;background:transparent;color:inherit;cursor:pointer}button[aria-pressed=true]{outline:2px solid #2968ad}span,p{overflow-wrap:anywhere}details{margin-top:8px}button:focus-visible,summary:focus-visible{outline:3px solid #7657d6}
.version-row article:nth-child(5n+1) button{background:#fcebf1}.version-row article:nth-child(5n+2) button{background:#fcf5dc}.version-row article:nth-child(5n+3) button{background:#e8f6ed}.version-row article:nth-child(5n+4) button{background:#eaf1fc}.version-row article:nth-child(5n+5) button{background:#f0e9fa}button[aria-pressed=true]{outline:3px solid #7050b1;box-shadow:0 3px 12px #7050b122}button{color:#211e29;border-radius:14px}button:hover{border-color:#7050b1}
</style>
