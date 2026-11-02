// Pure presentation helpers, shared with the evidence regression tests.
export function safeUrl(value) {
  try {
    const url = new URL(value)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null
    const host = url.hostname.toLowerCase()
    if (!host.includes('.') || /(^127\.|^10\.|^192\.168\.|^169\.254\.|^172\.(1[6-9]|2\d|3[01])\.|\.localhost$|\.local$|\.internal$)/.test(host)) return null
    return url.href
  } catch { return null }
}

export function reliableTimestamp(reason) {
  const time = reason?.video_timestamp
  return reason?.timing_status === 'aligned' && typeof time === 'number' && Number.isFinite(time) && time >= 0 ? time : null
}

export function evidenceView(result, retrieve) {
  const evidence = result?.evidence
  if (evidence?.schema_version === 1 && evidence.video_id === result.vid &&
      evidence.analysis_id && evidence.analysis_id === result.analysis_id) return evidence
  // Legacy results have no citation mapping. Never attach arbitrary sources to reasons.
  return {
    reasons: typeof result?.reason === 'string' ? result.reason.split(/(?<=[。！？])|\n/).filter(s => s.trim()).map((text, i) => ({ reason_id: `legacy-${i}`, reason_text: text, claim_ids: [], evidence: [] })) : [],
    claims: [], sources: [], original_input: {},
  }
}

export function reasonCards(data, reason) {
  if (!reason) return []
  const links = (data.claims || []).filter(c => reason.claim_ids?.includes(c.claim_id))
    .flatMap(c => (c.evidence || []).map(e => ({ ...e, claim_text: c.claim_text })))
  links.push(...(reason.evidence || []))
  const cards = links.flatMap(link => {
    const matches = (data.sources || []).filter(s => s.source_id === link.source_id)
    // An ambiguous ID cannot safely select the first source.
    const source = matches.length === 1 ? matches[0] : null
    if (!source) return []
    const p = link.excerpt_provenance
    const verified = verifiedExcerpt(source, link) !== null
    return [{ ...link, ...source, evidence_relation: link.evidence_relation,
      match_basis: link.match_basis, claim_text: link.claim_text,
      source_excerpt: verified ? link.source_excerpt : null,
      excerpt_provenance: verified ? p : null }]
  })
  // Same source can occur through both a claim and a reason. Preserve distinct
  // excerpts/claims, but suppress redundant cards with the same provenance.
  return cards.filter(card => card.claim_text || card.source_excerpt || !cards.some(other =>
    other.source_id === card.source_id && other.claim_text)).filter((card, i, unique) => unique.findIndex(other => other.source_id === card.source_id &&
    other.claim_text === card.claim_text && other.source_excerpt === card.source_excerpt) === i)
}

// Display inventory only: never add claims, reason links or relation labels.
// Source IDs are scoped to this batch; URL equality only suppresses duplicate UI cards.
export function searchSources(data, result, retrieve) {
  const sameBatch = result?.vid && retrieve?.vid === result.vid &&
    (retrieve.analysis_id || null) === (result.analysis_id || null) &&
    (retrieve.run_id ?? null) === (result.run_id ?? null)
  const inputs = [result, ...(sameBatch ? [retrieve] : [])].filter(Boolean)
  const candidates = [...(data.sources || [])]
  for (const input of inputs) {
    const nested = input.evidence
    if (nested?.schema_version === 1 && nested.video_id === input.vid &&
        nested.analysis_id && nested.analysis_id === input.analysis_id &&
        (nested.run_id ?? null) === (input.run_id ?? null)) candidates.push(...(nested.sources || []))
    if (Array.isArray(input.sources)) candidates.push(...input.sources.filter(s => s && typeof s === 'object'))
    // Legacy URL fields have no citation semantics, title, article text or download status.
    const append = value => {
      if (Array.isArray(value)) value.forEach(append)
      else if (typeof value === 'string' && value.trim()) candidates.push({ source_url: value,
        source_site: safeUrl(value) ? new URL(value).hostname : null })
    }
    for (const key of ['uri', 'uris', 'url', 'urls', 'link', 'links', 'source_url', 'source_urls']) append(input[key])
    if (typeof input.source === 'string') append(input.source)
    if (Array.isArray(input.sources)) input.sources.filter(s => typeof s === 'string').forEach(append)
  }
  const seen = new Set()
  return candidates.filter(source => {
    if (!source || typeof source !== 'object') return false
    const keys = sourceIdentity(source)
    if (keys.some(key => seen.has(key))) return false
    keys.forEach(key => seen.add(key))
    return true
  })
}

function sourceIdentity(source) {
  const urls = [source.source_url, source.resolved_url].filter(value => typeof value === 'string' && value)
  return urls.length ? urls.map(url => `url:${safeUrl(url) || url}`) :
    [source.source_id ? `id:${source.source_id}` : `record:${JSON.stringify(source)}`]
}

export function otherSearchSources(sources, cards) {
  const linked = new Set(cards.flatMap(sourceIdentity))
  return sources.filter(source => !sourceIdentity(source).some(key => linked.has(key)))
}

export function verifiedExcerpt(source, link = source) {
  const p = link.excerpt_provenance
  if (!['source_text', 'article_text', 'transcript_text'].includes(p?.field)) return null
  const value = source[p.field]
  const points = typeof value === 'string' ? Array.from(value) : []
  return Number.isInteger(p.start) && p.start >= 0 && Number.isInteger(p.end) &&
    p.end > p.start && p.end <= points.length && points.slice(p.start, p.end).join('') === link.source_excerpt
    ? link.source_excerpt : null
}

export function assessedCards(data, reason) {
  const assessment = data?.assessment
  if (!reason || assessment?.schema_version !== 1 || !data.analysis_id ||
      assessment.analysis_id !== data.analysis_id || assessment.video_id !== data.video_id ||
      (assessment.run_id ?? null) !== (data.run_id ?? null)) return []
  return (assessment.records || []).filter(row => row.reason_id === reason.reason_id).flatMap(row => {
    const matches = (data.sources || []).filter(s => s.source_id === row.source_id)
    if (matches.length !== 1) return []
    const source = matches[0]
    const claim = row.claim_id == null ? null : (data.claims || []).find(c => c.claim_id === row.claim_id)
    const link = { source_excerpt: row.verbatim_excerpt, excerpt_provenance: row.excerpt_provenance }
    const quote = verifiedExcerpt(source, link)
    const valid = source.retrieval_status === 'fetched' && !!source.article_text && (row.excerpt_provenance?.field === 'article_text' || (row.relevance === 'insufficient' && !row.verbatim_excerpt)) && source.source_kind !== 'youtube' && !['youtube','search_page'].includes(source.source_type) && row.assessment_status === 'validated' && row.model_name === assessment.model_name &&
      row.prompt_version === assessment.prompt_version && (row.claim_id == null || claim) &&
      ['direct', 'contextual', 'unrelated', 'insufficient'].includes(row.relevance) &&
      ['supports', 'refutes', 'mixed', 'not_established'].includes(row.stance) &&
      ((quote && row.excerpt_start === row.excerpt_provenance.start && row.excerpt_end === row.excerpt_provenance.end) || (row.relevance === 'insufficient' && !row.verbatim_excerpt))
    const safeAssessment = valid ? { ...row, stance: row.relevance !== 'direct' ||
      (row.target_scope !== 'single' && ['supports', 'refutes'].includes(row.stance)) ? 'not_established' : row.stance } :
      { ...row, relation: row.relation === 'unavailable' ? 'unavailable' : 'insufficient', relevance: 'insufficient', stance: 'not_established', assessment_status: row.assessment_status === 'validated' ? 'validation_failed' : row.assessment_status }
    return [{ ...source, source_excerpt: valid ? quote : null,
      excerpt_provenance: valid && quote ? row.excerpt_provenance : null,
      assessment: safeAssessment, assessed_claim_text: claim?.claim_text || null }]
  })
}

export function claimCategory(claim) {
  return ({ Rc: 'claim', Rv: 'observation', K_int: 'model', K_ext: 'synthesis', reason: 'claim' })[claim?.claim_provenance?.field] || 'unknown'
}

export function observationFor(data, reason, retrieve = {}, result = {}) {
  // Modality cues choose display order ONLY. They never create a reason link.
  const wording = reason?.reason_text || ''
  const visualCue = /影像|畫面|变形|變形|人物|動作|动作|場景|场景|視覺|视觉|肢體|肢体|\b(visual|image|frame|scene|movement|motion|distortion)\b/i.test(wording)
  const speechCue = /語音|语音|字幕|轉錄|转录|聲音|声音|旁白|口述|說話|说话|\b(speech|audio|subtitle|caption|transcript|voice|narration)\b/i.test(wording)
  // A legacy result may use legacy input, but never borrow a different run's data.
  const sameInput = result?.vid && retrieve?.vid === result.vid &&
    (retrieve.analysis_id || null) === (result.analysis_id || null) &&
    (retrieve.run_id || null) === (result.run_id || null)
  const input = sameInput ? retrieve : {}
  const observations = (data.claims || []).filter(c => claimCategory(c) === 'observation')
  const relatedVisual = observations.filter(c => reason?.claim_ids?.includes(c.claim_id))
  const visual = { kind: 'visual',
    text: relatedVisual.length ? relatedVisual.map(c => c.claim_text).join('\n') :
      (typeof input.Rv === 'string' ? input.Rv : observations.map(c => c.claim_text).join('\n')),
    related: relatedVisual.length > 0 }
  const speech = { kind: 'transcript', text: reason?.transcript_excerpt || data.original_input?.transcript || '',
    related: Boolean(reason?.transcript_excerpt) }
  let ordered
  if (visualCue && speechCue) ordered = [visual, speech]
  else if (visualCue) ordered = visual.text ? [visual] : [speech]
  else if (speechCue) ordered = speech.text ? [speech] : [visual]
  else if (visual.related || speech.related) ordered = [visual, speech].filter(item => item.related)
  else ordered = [visual, speech]
  const items = ordered.filter(item => typeof item.text === 'string' && item.text.length)
  if (!items.length && typeof input.Rc === 'string' && input.Rc) {
    items.push({ kind: 'input', text: input.Rc, related: false })
  }
  return { ...(items[0] || { kind: 'input', text: '', related: false }), items }
}

export function textPreview(text, limit = 240) {
  return typeof text === 'string' && text.length > limit ? text.slice(0, limit) + '…' : text || ''
}
