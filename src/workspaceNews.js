import { safeUrl } from './evidence.js'

export function newsSelection(card) {
  const a=card.auto, m=a?.source_manifest
  if(a?.status!=='completed')return {reason:'需等待自動摘要完成'}
  if(typeof a.summary!=='string' || !a.summary.trim())return {reason:'沒有可用自動摘要'}
  const id=a.source_id, bodyHash=a.article_text_hash || m?.article_text_hash
  const url=safeUrl(a.original_url) ? a.original_url : safeUrl(a.url) ? a.url : null
  if(!id || !url || !bodyHash)return {reason:'來源識別、網址或正文 hash 不完整'}
  const savedBody=(m?.article_text_hash===bodyHash && ['full_article','partial_article'].includes(m.content_quality)) ||
    card.sources.some(s=>(s.article_text_hash || s.article_text_sha256)===bodyHash && s.article_text?.trim() && s.retrieval_status==='fetched' && ['full_article','partial_article'].includes(s.content_quality))
  if(!savedBody)return {reason:'缺少可追溯的保存正文'}
  const original=card.sources.find(s=>s.source_id===id) || (card.source.source_id===id ? card.source : {})
  return {key:JSON.stringify([a.article_id || id,bodyHash,url]),sourceId:id,url,
    identity:{source_id:id,article_text_hash:bodyHash,cache_key:a.cache_key},
    title:a.title || original.article_title || original.source_title || '文章標題未提供',summary:a.summary}
}

export function newsPreview(cards, selected) {
  const used=new Set()
  return cards.map(newsSelection).filter(s=>s.key && selected.includes(s.key) && !used.has(s.key) && used.add(s.key))
    .map(s=>`[${s.sourceId}] ${s.title}\n${s.url}\n${s.summary}`).join('\n\n')
}

const urls = s => [s.canonical_url,s.resolved_url,s.source_url,s.original_url,s.url].map(safeUrl).filter(Boolean)
const hash = s => s.article_text_hash || s.article_text_sha256
function sameArticle(a,b,allowId=true) {
  if (hash(a) && hash(b) && hash(a)!==hash(b)) return false
  if (a.article_id && b.article_id) return a.article_id===b.article_id
  if (hash(a) && hash(b)) return hash(a)===hash(b)
  const au=urls(a),bu=urls(b)
  if (au.some(u=>bu.includes(u))) return true
  return allowId && a.source_id && a.source_id===b.source_id && (!au.length || !bu.length)
}

// Presentation only. Never alter evidence links, inputs, or research approval records.
export function unifiedNews(sources, savedSummaries=[], automatic=null) {
  const cards=[]
  function attach(source,kind) {
    const matches=cards.filter(c=>c.sources.some(s=>sameArticle(s,source,kind!=='saved')))
    const card=matches.length===1?matches[0]:{key:`news-${cards.length}`,sources:[],saved:[],automatic:[]}
    if (!matches.length || matches.length>1) cards.push(card)
    if(kind==='source') card.sources.push(source)
    else if(kind==='saved') {card.saved.push(source);if(!card.sources.length)card.sources.push(source)}
    else {card.automatic.push(source);if(!card.sources.length)card.sources.push(source)}
    return card
  }
  sources.forEach(s=>attach(s,'source'))
  savedSummaries.forEach(s=>attach(s,'saved'))
  const byRecord=new Map()
  for(const row of automatic?.records || []) {
    // Completed records are themselves version-scoped saved Retrieve provenance.
    const card=attach(row,'automatic')
    if(row.record_id)byRecord.set(row.record_id,card)
  }
  for(const row of automatic?.records || []) {
    const child=byRecord.get(row.record_id),parent=byRecord.get(row.duplicate_of)
    if(!child || !parent || child===parent)continue
    // Backend duplicate mapping is explicit; keep all aliases and original records.
    parent.sources.push(...child.sources);parent.automatic.push(...child.automatic);parent.saved.push(...child.saved)
    const index=cards.indexOf(child);if(index>=0)cards.splice(index,1)
    for(const [id,c] of byRecord)if(c===child)byRecord.set(id,parent)
  }
  return cards.map(c=>{
    const auto=c.automatic.find(s=>s.status==='completed' && s.summary) || c.automatic.find(s=>!s.duplicate_of)
    return {...c, source:c.sources.find(s=>s.article_text) || c.sources[0], auto,
      saved:c.saved.find(s=>s.summary) || c.saved[0]}
  })
}

// One request at a time, at most 60 requests per selection. GET never creates work.
export function summaryReader({request,onChange,schedule=setTimeout,cancel=clearTimeout,maxRequests=60,interval=5000}) {
  let generation=0,timer=null,deadline=null,controller=null
  function stop(){generation++;cancel(timer);cancel(deadline);controller?.abort();timer=null;deadline=null}
  function start(eid,vid,enabled=true) {
    stop();const scope=generation;let count=0,lastJob=null
    onChange({status:enabled?'loading':'unavailable',job:null,error:null})
    if(!enabled || !eid || !vid)return
    async function read(){
      if(scope!==generation)return
      controller=new AbortController();count++
      try{
        const response=await Promise.race([
          request(`/versions/${encodeURIComponent(vid)}/automatic-summaries`,{method:'GET',signal:controller.signal}),
          new Promise((_,reject)=>{deadline=schedule(()=>{controller?.abort();reject(new Error('摘要狀態讀取逾時'))},15000)})
        ])
        if(scope!==generation)return
        cancel(deadline)
        if(!response || typeof response.status!=='string')throw new Error('摘要狀態格式無效')
        if((response.experiment_id && response.experiment_id!==eid)||(response.version_id && response.version_id!==vid) ||
          (response.records?.length && (response.experiment_id!==eid || response.version_id!==vid)))throw new Error('摘要版本不符')
        const active=['pending','running'].includes(response.status)
        lastJob=response
        onChange({status:response.status,job:response,error:null,paused:active && count>=maxRequests})
        if(active && count<maxRequests)timer=schedule(read,interval)
      }catch(error){
        if(scope!==generation)return
        cancel(deadline);onChange({status:'error',job:lastJob,error:error.message})
      }
    }
    read()
  }
  return {start,stop}
}
