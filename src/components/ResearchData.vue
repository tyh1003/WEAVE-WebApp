<template>
  <div class="research-data">
    <article v-for="field in visibleFields" :key="field.key">
      <h3>{{ field.key }} · {{ locale === 'en' ? field.en : field.zh }}</h3>
      <p v-if="field.key === 'K_ext'" class="note">{{ tr('模型整理的外部背景知識，不等於每一句都有已核實來源。', 'Model synthesis of external knowledge; individual statements are not necessarily source-verified.') }}</p>
      <p v-if="field.key === 'K_int'" class="note">{{ tr('模型背景知識，非外部證據。', 'Model background knowledge, not external evidence.') }}</p>
      <EvidenceText v-if="original(field.key)" :text="original(field.key)" :locale="locale" />
      <p v-else>{{ tr('資料未提供', 'Data not provided') }}</p>
      <button type="button" :disabled="!original(field.key)" @click="copy(field.key)">{{ tr('複製原始內容', 'Copy original text') }}</button>
      <span role="status">{{ messages[field.key] }}</span>
      <details v-if="locale === 'en' && translations?.[field.key]">
        <summary>English translation · original preserved above</summary>
        <EvidenceText :text="translations[field.key]" :locale="locale" />
      </details>
    </article>
  </div>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import EvidenceText from './EvidenceText.vue'
const props = defineProps({ data: Object, translations: Object, locale: String, fieldKeys: Array })
const fields = [
  { key: 'Rc', zh: '語音／文字內容', en: 'Speech / textual content' },
  { key: 'Rv', zh: '視覺內容描述', en: 'Visual description' },
  { key: 'K_int', zh: '內部知識', en: 'Internal Knowledge' },
  { key: 'K_ext', zh: '外部知識', en: 'External Knowledge' },
]
const visibleFields = computed(() => fields.filter(f => !props.fieldKeys || props.fieldKeys.includes(f.key)))
const tr = (zh, en) => props.locale === 'en' ? en : zh
const original = key => typeof props.data?.[key] === 'string' ? props.data[key] : props.data?.[key] == null ? '' : JSON.stringify(props.data[key], null, 2)
const messages = ref({})
let generation = 0
watch(() => [props.data, props.locale], () => { generation++; messages.value = {} })
async function copy(key) {
  const batch = generation
  try {
    await navigator.clipboard.writeText(original(key))
    if (batch === generation) messages.value[key] = tr('已複製', 'Copied')
  } catch {
    if (batch === generation) messages.value[key] = tr('無法存取剪貼簿，請展開全文並手動複製。', 'Clipboard unavailable; expand and copy the text manually.')
  }
}
</script>
<style scoped>
.research-data { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; }
article { min-width: 0; border-top: 2px solid #e0e3ec; padding-top: 16px; }
h3 { font-size: 17px; margin: 0 0 12px; }
small, .note { color: #606676; font-weight: normal; }
p, span, summary { overflow-wrap: anywhere; line-height: 1.7; }
button { font: inherit; padding: 6px 10px; border: 1px solid #c9c1db; border-radius: 6px; background: #fff; color: #4c3a72; cursor: pointer; }
button:disabled { opacity: .5; cursor: default; }
button:focus-visible, summary:focus-visible { outline: 3px solid #7657d6; outline-offset: 3px; }
span { margin-left: 10px; }
details { margin-top: 12px; }
@media (max-width: 820px) { .research-data { grid-template-columns: minmax(0, 1fr); } }
</style>
