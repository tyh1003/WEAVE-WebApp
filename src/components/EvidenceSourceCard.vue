<template>
  <article class="evidence-card">
    <a v-if="url" :href="url" target="_blank" rel="noopener noreferrer">{{ displayTitle || tr('文章標題未提供', 'Article title not provided') }}</a>
    <strong v-else>{{ displayTitle || tr('文章標題未提供', 'Article title not provided') }}</strong>
    <p>{{ tr('網站／網域（未驗證出版機構）', 'Site / domain (publisher unverified)') }}：{{ isGoogleIntermediary ? tr('Google 存取限制／中介頁，非新聞發布網站', 'Google access restriction / intermediary, not a news publisher') : source.publisher_name || source.source_site || tr('網站未提供', 'Site unavailable') }} · {{ source.published_date || tr('日期未提供', 'Date not provided') }}</p>
    <p class="notice">{{ tr('外部來源 · ', 'External source · ') }}{{ source.retrieval_status === 'fetched' ? tr('已取得網頁文字', 'Page text retrieved') : tr('原文尚未取得', 'Original text not retrieved') }}</p>
    <p v-if="unlinked && !source.assessment" class="notice">{{ tr("與目前理由的關聯未確認", "Relationship to the current reason is unconfirmed") }}</p>
    <p v-if="!source.assessment" class="notice">{{ tr('語意關聯尚未確認；文字對應不代表支持或反駁。', 'Semantic relationship unconfirmed; text matching does not establish support or contradiction.') }}</p>
    <p v-if="source.assessment" class="assessment-label">{{ tr('AI 語意評估（非人工確認）', 'AI semantic assessment (not human confirmation)') }}：{{ relevanceLabel(source.assessment.relevance) }} · {{ stanceLabel(source.assessment.stance) }}</p>
    <p v-if="source.assessment?.coverage === 'partial'" class="notice">{{ tr('僅評估部分文字，不代表全文結論。', 'Partial text coverage; not a conclusion about the whole source.') }}</p>
    <p v-if="source.assessed_claim_text" class="notice">{{ tr('評估主張', 'Assessed claim') }}：{{ source.assessed_claim_text }}</p>
    <p v-if="source.assessment?.relation">{{ source.assessment.relation }} · {{ source.assessment.assessment_status }} · {{ source.assessment.quote_validation }}</p>
    <p v-if="source.assessment?.explanation">{{ source.assessment.explanation }}</p>
    <p v-if="isYouTube && source.transcript_status !== 'obtained'" class="notice">{{ tr('尚未取得 YouTube 字幕／逐字稿；網頁不是影片語音內容。', 'YouTube captions/transcript unavailable; page HTML is not spoken video content.') }}</p>
    <blockquote v-if="quote"><EvidenceText :text="quote" :locale="locale" /></blockquote>
    <template v-else-if="articlePreview">
      <p class="notice">{{ tr('保存正文預覽（未確認與理由直接相關）', 'Saved article preview (direct relationship unconfirmed)') }}</p>
      <blockquote><EvidenceText :text="articlePreview" :locale="locale" /></blockquote>
    </template>
    <p v-else-if="source.retrieval_status === 'fetched'" class="notice">{{ tr('尚無可直接核對的摘錄。', 'No directly verifiable excerpt available.') }}</p>
    <p v-if="!source.assessment" class="notice">{{ tr('支持／反駁關係：證據不足，尚未確認。', 'Support / contradiction: insufficient evidence, unconfirmed.') }}</p>
    <a v-if="url" :href="url" target="_blank" rel="noopener noreferrer">{{ tr('開啟保存的來源連結', 'Open saved source link') }}</a>
    <p v-else class="notice">{{ tr('來源網址缺失、無效或未通過安全檢查。', 'Source URL missing, invalid or blocked by safety checks.') }}</p>
    <details>
      <summary>{{ tr('取得狀態與核對細節', 'Retrieval and verification details') }}</summary>
      <p>{{ statusLabel(source.retrieval_status) }}</p>
      <p v-if="source.retrieval_error">{{ source.retrieval_error }}</p>
      <p v-if="source.extraction_error">{{ source.extraction_error }}</p>
      <p v-if="source.duplicate_of">{{ tr('同批重複來源', 'Duplicate source in this batch') }}: {{ source.duplicate_of }}</p>
      <pre v-if="source.redirect_chain">{{ JSON.stringify({original_url:source.original_url,resolved_url:source.resolved_url,canonical_url:source.canonical_url,redirect_chain:source.redirect_chain,article_text_hash:source.article_text_hash}, null, 2) }}</pre>
      <p v-if="source.title_provenance">{{ tr('標題來源', 'Title provenance') }}：{{ source.title_provenance }}</p>
      <p v-if="source.date_provenance">{{ tr('日期來源', 'Date provenance') }}：{{ source.date_provenance }}</p>
      <pre v-if="source.assessment">{{ JSON.stringify(source.assessment_records || [source.assessment], null, 2) }}</pre>
      <details v-if="source.article_text || source.transcript_text"><summary>{{ tr('保存的正文／字幕', 'Saved article / transcript') }}</summary><EvidenceText :text="source.article_text || source.transcript_text" :locale="locale" /></details>
      <p v-if="source.match_basis">{{ tr('對應依據：既有文字／引用區段連結', 'Mapping basis: existing text / citation segment link') }}</p>
      <p v-if="source.evidence_relation">{{ tr('原始關係標記', 'Original relationship label') }}：{{ relationLabel(source.evidence_relation) }}</p>
      <template v-if="source.excerpt_provenance">
        <p>{{ tr('保存文字位置', 'Saved text offsets') }}：{{ source.excerpt_provenance.start }}–{{ source.excerpt_provenance.end }}</p>
      </template>
      <p v-if="source.fetched_at">{{ tr('取得時間', 'Retrieved at') }}：{{ source.fetched_at }}</p>
      <p v-if="source.content_sha256" class="hash">SHA-256: {{ source.content_sha256 }}</p>
      <details v-if="source.source_text">
        <summary>{{ tr('保存的來源文字', 'Saved source text') }}</summary>
        <EvidenceText :text="source.source_text" :locale="locale" />
      </details>
    </details>
  </article>
</template>
<script setup>
import { computed } from 'vue'
import EvidenceText from './EvidenceText.vue'
import { safeUrl, verifiedExcerpt } from '../evidence.js'
const props = defineProps({ source: Object, locale: String, unlinked: Boolean })
const tr = (zh, en) => props.locale === 'en' ? en : zh
const isYouTube = computed(() => {
  if (props.source.source_kind === 'youtube' || ['youtube.com', 'www.youtube.com', 'youtu.be'].includes(props.source.source_title)) return true
  try { const host = new URL(props.source.resolved_url || props.source.source_url).hostname; return host === 'youtu.be' || host === 'youtube.com' || host.endsWith('.youtube.com') } catch { return false }
})
const displayTitle = computed(() => sourceTitle(props.source))
const isGoogleIntermediary = computed(() => {
  try { const u = new URL(props.source.resolved_url); return ['google.com','www.google.com','consent.google.com'].includes(u.hostname) } catch { return false }
})
const articlePreview = computed(() => !isYouTube.value && !isGoogleIntermediary.value && props.source.retrieval_status === 'fetched' && props.source.article_text ? props.source.article_text.slice(0, 600) : null)
function sourceTitle(source) {
  if (source.article_title) return source.article_title
  const title = source.source_title || ''
  return /^(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}$/i.test(title.trim()) ? null : title
}
function relevanceLabel(value) {
  return ({ direct: tr('直接相關', 'Direct'), contextual: tr('僅背景相關', 'Contextual'), unrelated: tr('無關', 'Unrelated'), insufficient: tr('資訊不足', 'Insufficient') })[value] || tr('未確認', 'Unconfirmed')
}
function stanceLabel(value) {
  return ({ supports: tr('支持', 'Supports'), refutes: tr('反駁', 'Refutes'), mixed: tr('混合', 'Mixed'), not_established: tr('尚未建立支持／反駁關係', 'Stance not established') })[value] || tr('資訊不足', 'Insufficient')
}
const quote = computed(() => verifiedExcerpt(props.source))
const url = computed(() => props.source.retrieval_status === 'blocked_url' ? null : (isGoogleIntermediary.value ? safeUrl(props.source.source_url) : safeUrl(props.source.resolved_url)) || safeUrl(props.source.source_url))
function relationLabel(value) {
  return ({ supports: tr('支持', 'Supports'), refutes: tr('反駁', 'Refutes'), background: tr('僅提供背景', 'Background only'), insufficient: tr('證據不足', 'Insufficient evidence') })[value] || tr('尚未確認', 'Unconfirmed')
}
function statusLabel(value) {
  return ({ redirect_unresolved: tr('Grounding 轉址未解析至原始文章', 'Grounding redirect did not resolve to an article'), content_unavailable: tr('影片字幕／逐字稿未取得', 'Video transcript unavailable'), fetched: tr('已取得網頁文字', 'Page text retrieved'), timeout: tr('來源擷取逾時', 'Source timed out'),
    blocked_url: tr('來源網址未通過安全檢查', 'Source URL blocked by safety checks'),
    access_denied: tr('來源拒絕存取或限制擷取', 'Access denied or rate limited'), unavailable: tr('來源失效或無法存取', 'Source unavailable'),
    too_large: tr('網頁超過擷取大小限制', 'Page exceeds size limit'), budget_exceeded: tr('本次擷取數量已達上限', 'Retrieval budget reached'),
    unsupported_content: tr('無法擷取此來源格式', 'Unsupported source format'), unextractable: tr('無法擷取網頁文字', 'Page text unavailable'),
    redirect_limit: tr('來源重新導向過多', 'Too many redirects') })[value] || tr('取得狀態未提供', 'Retrieval status unavailable')
}
</script>
<style scoped>
.evidence-card { min-width: 0; margin-top: 10px; padding: 12px; border: 1px solid #c4b5fd; border-radius: 8px; background: #ffffffb8; }
p, a, strong, summary { overflow-wrap: anywhere; line-height: 1.65; }
p { margin: 8px 0; }
a { color: #4c1d95; font-weight: 700; }
.notice { font-size: 13px; color: #666073; }
blockquote { margin: 8px 0; border-left: 3px solid #7657d6; padding-left: 10px; }
.hash { font-size: 11px; }
summary { cursor: pointer; }
a:focus-visible, summary:focus-visible { outline: 3px solid #7657d6; outline-offset: 2px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 260px; overflow: auto; font-size: 12px; }
.assessment-label { font-weight: 700; }
</style>
