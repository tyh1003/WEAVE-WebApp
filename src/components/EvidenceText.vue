<template>
  <div class="evidence-text">
    <p v-if="!expanded">{{ textPreview(text, limit) }}</p>
    <p v-else>{{ text }}</p>
    <button v-if="text.length > limit" type="button" :aria-expanded="expanded" @click="expanded = !expanded">
      {{ locale === 'en' ? (expanded ? 'Collapse' : 'Read full text') : (expanded ? '收合全文' : '展開全文') }}
    </button>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue'
import { textPreview } from '../evidence.js'
const props = defineProps({ text: { type: String, default: '' }, locale: String, limit: { type: Number, default: 240 } })
const expanded = ref(false)
watch(() => props.text, () => { expanded.value = false })
</script>
<style scoped>
.evidence-text { min-width: 0; }
p { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.65; margin: 8px 0; }
button { font: inherit; color: #4c1d95; background: transparent; border: 1px solid #c4b5fd; border-radius: 6px; padding: 4px 8px; cursor: pointer; }
button:focus-visible { outline: 3px solid #7657d6; outline-offset: 2px; }
</style>
