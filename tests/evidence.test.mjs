import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick } from 'vue'
import { evidenceView, reasonCards, reliableTimestamp, safeUrl, claimCategory, observationFor, textPreview, searchSources, otherSearchSources, assessedCards } from '../src/evidence.js'

function fixture() {
  return { vid: 'v1', analysis_id: 'a1', reason: 'Original reason A。Original reason B。', evidence: {
    schema_version: 1, video_id: 'v1', analysis_id: 'a1',
    original_input: { transcript: 'Whole original transcript' },
    sources: [
      { source_id: 's1', source_title: 'Article A', source_site: 'a.example', source_url: 'https://a.example/a', source_text: 'First excerpt', retrieval_status: 'fetched' },
      { source_id: 's2', source_title: 'Article B', source_site: 'b.example', source_url: 'https://b.example/b', retrieval_status: 'access_denied' },
    ],
    claims: [
      { claim_id: 'c1', claim_text: 'Claim A', evidence: [{ source_id: 's1', source_excerpt: 'First excerpt', excerpt_provenance: { field: 'source_text', start: 0, end: 13 }, evidence_relation: 'insufficient' }] },
      { claim_id: 'c2', claim_text: 'Claim B', evidence: [{ source_id: 's2', evidence_relation: 'background' }] },
    ],
    reasons: [
      { reason_id: 'r1', reason_text: 'Original reason A', claim_ids: ['c1'], video_timestamp: 12, timing_status: 'aligned', transcript_excerpt: 'Segment A' },
      { reason_id: 'r2', reason_text: 'Original reason B', claim_ids: ['c2'], video_timestamp: null },
      { reason_id: 'r3', reason_text: 'No external evidence', claim_ids: [], video_timestamp: 40, timing_status: 'not_aligned' },
    ],
  } }
}

test('separate reasons, multiple claims and sources, verified excerpts only', () => {
  const result = fixture()
  const data = evidenceView(result)
  assert.equal(reasonCards(data, data.reasons[0])[0].source_title, 'Article A')
  assert.equal(reasonCards(data, data.reasons[1])[0].source_title, 'Article B')
  assert.equal(reasonCards(data, data.reasons[0])[0].source_excerpt, 'First excerpt')
  assert.equal(reasonCards(data, data.reasons[1])[0].source_excerpt, null)
  data.claims[0].evidence[0].source_excerpt = 'Fabricated quote'
  assert.equal(reasonCards(data, data.reasons[0])[0].source_excerpt, null)
  data.reasons[0].claim_ids.push('c2')
  assert.equal(reasonCards(data, data.reasons[0]).length, 2)
  data.claims[0].evidence.push({ source_id: 's2' })
  assert.equal(reasonCards(data, { claim_ids: ['c1'] }).length, 2)
})

test('only explicit reliable timestamps; old formats and wrong video/batch degrade safely', () => {
  const result = fixture()
  assert.equal(reliableTimestamp(result.evidence.reasons[0]), 12)
  assert.equal(reliableTimestamp(result.evidence.reasons[1]), null)
  assert.equal(reliableTimestamp(result.evidence.reasons[2]), null)
  assert.equal(reliableTimestamp({ timing_status: 'aligned', video_timestamp: -1 }), null)
  for (const field of ['video_id', 'analysis_id']) {
    const copy = structuredClone(result)
    copy.evidence[field] = 'different'
    assert.deepEqual(evidenceView(copy).sources, [])
  }
  assert.equal(evidenceView({ reason: 'Old reason。Second reason。' }).reasons.length, 2)
  assert.deepEqual(evidenceView(null).reasons, [])
  assert.equal(safeUrl('javascript:alert(1)'), null)
  assert.equal(safeUrl('http://127.0.0.1/a'), null)
  assert.equal(safeUrl('https://news.example/a'), 'https://news.example/a')
})

globalThis.Document = class Document {}
globalThis.ShadowRoot = class ShadowRoot {}
const componentUrls = new Map()
function componentUrl(filename) {
  if (componentUrls.has(filename.href)) return componentUrls.get(filename.href)
  const { descriptor } = parse(readFileSync(filename, 'utf8'))
  const compiled = compileScript(descriptor, { id: filename.pathname, inlineTemplate: true }).content
    .replace(/import.meta.env/g, '({})')
    .replace(/from ['"]vue['"]/g, `from ${JSON.stringify(import.meta.resolve('vue'))}`)
    .replace(/from ['"]([^'"]+\.vue)['"]/g, (_, path) => `from ${JSON.stringify(componentUrl(new URL(path, filename)))}`)
    .replace(/from ['"]([^'"]+\.js)['"]/g, (_, path) => `from ${JSON.stringify(new URL(path, filename).href)}`)
  const url = `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
  componentUrls.set(filename.href, url)
  return url
}
const Component = (await import(componentUrl(new URL('../src/components/EvidencePanel.vue', import.meta.url)))).default
const TextComponent = (await import(componentUrl(new URL('../src/components/EvidenceText.vue', import.meta.url)))).default
const AppComponent = (await import(componentUrl(new URL('../src/App.vue', import.meta.url)))).default

function element(type, text = '') { return { type, text, props: {}, children: [], duration: 60, currentTime: 0, tagName:type.toUpperCase(), get options() { return this.children.filter(n => n.type === 'option') }, getRootNode() { return {} }, addEventListener() {}, removeEventListener() {}, setAttribute() {}, removeAttribute() {}, pause() {} } }
const renderer = createRenderer({
  createElement: type => element(type), createText: text => element('#text', text), createComment: text => element('#comment', text),
  setText: (node, text) => { node.text = text }, setElementText: (node, text) => { node.text = text; node.children = [] },
  patchProp: (node, key, prev, next) => { node.props[key] = next },
  insert(node, parent, anchor = null) {
    if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
    node.parent = parent
    const i = anchor ? parent.children.indexOf(anchor) : -1
    if (i < 0) parent.children.push(node); else parent.children.splice(i, 0, node)
  },
  remove(node) { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1) },
  parentNode: node => node.parent,
  nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] || null,
})
const all = node => [node, ...node.children.flatMap(all)]
const text = node => all(node).filter(n => n.type !== '#comment').map(n => n.text).join(' ')

test('classifications follow provenance, visual input is reason-specific, and text is never rewritten', () => {
  const result = fixture()
  const data = result.evidence
  data.claims[0].claim_provenance = { field: 'Rv' }
  data.claims[1].claim_provenance = { field: 'Rc' }
  assert.equal(claimCategory(data.claims[0]), 'observation')
  assert.equal(claimCategory(data.claims[1]), 'claim')
  assert.equal(claimCategory({ claim_provenance: { field: 'K_int' } }), 'model')
  assert.equal(claimCategory({ claim_provenance: { field: 'K_ext' } }), 'synthesis')
  assert.equal(claimCategory({}), 'unknown')
  assert.equal(observationFor(data, data.reasons[0]).text, 'Claim A')
  assert.equal(observationFor(data, data.reasons[1]).items.find(item => item.kind === 'transcript').text, 'Whole original transcript')
  const long = 'Oh, my God! '.repeat(2000)
  assert.ok(textPreview(long).length < 250)
  assert.equal(long.length, 24000)
})

test('visual, speech, subtitle, mixed and unknown reasons select inputs without inventing links', () => {
  const result = fixture()
  const data = result.evidence
  const retrieve = { vid: 'v1', analysis_id: 'a1', Rv: '人物手部形狀改變，背景場景移動。', Rc: 'Refined input' }
  const select = wording => observationFor(data, { reason_text: wording, claim_ids: [] }, retrieve, result)
  for (const wording of ['影像變形與人物動作不自然', '場景有異常', 'Visual distortion in the scene']) {
    const view = select(wording)
    assert.equal(view.kind, 'visual')
    assert.equal(view.text, retrieve.Rv)
    assert.equal(view.related, false)
    assert.equal(view.items.length, 1)
  }
  for (const wording of ['語音內容不合理', '字幕聲稱某事', 'The audio narration is misleading']) {
    const view = select(wording)
    assert.equal(view.kind, 'transcript')
    assert.equal(view.text, data.original_input.transcript)
    assert.equal(view.related, false)
  }
  assert.deepEqual(select('畫面與語音字幕不一致').items.map(item => item.kind), ['visual', 'transcript'])
  assert.deepEqual(select('資訊仍有疑問').items.map(item => item.related), [false, false])
  const original = JSON.stringify(data)
  select('畫面與語音字幕不一致')
  assert.equal(JSON.stringify(data), original)
})

test('legacy inputs are available but different videos and batches are never borrowed', () => {
  const legacy = { vid: 'old', reason: '影像變形' }
  const data = evidenceView(legacy)
  const input = { vid: 'old', Rv: 'Original visual description' }
  assert.equal(observationFor(data, data.reasons[0], input, legacy).text, input.Rv)
  assert.equal(observationFor(data, data.reasons[0], input, legacy).related, false)
  for (const changed of [{ ...input, vid: 'other' }, { ...input, analysis_id: 'new-run' }, { ...input, run_id: 9 }]) {
    assert.deepEqual(observationFor(data, data.reasons[0], changed, legacy).items, [])
  }
  assert.deepEqual(observationFor(data, data.reasons[0], null, legacy).items, [])
  assert.equal(observationFor(data, data.reasons[0], { vid: 'old', Rc: 'Original refined input' }, legacy).kind, 'input')
})

test('mounted visual, speech and mixed reasons update A and C, with explicit empty evidence status', async () => {
  const result = fixture()
  result.evidence.sources = []
  result.evidence.claims = []
  result.evidence.original_input.transcript = 'Oh, my God! '.repeat(2000)
  result.evidence.reasons = ['影像變形', '語音有問題', '畫面與字幕不符', '無法分類'].map((reason_text, i) => ({ reason_id: `r${i}`, reason_text, claim_ids: [] }))
  const retrieve = { vid: 'v1', analysis_id: 'a1', Rv: '原始影像描述：人物的手部形狀改變。' }
  const root = element('root')
  renderer.render(h(Component, { result, retrieve, locale: 'zh' }), root)
  const buttons = () => all(root).filter(n => n.type === 'button' && 'aria-pressed' in n.props)
  const sections = () => all(root).find(n => n.props.class === 'evidence-columns').children.filter(n => n.type === 'section')
  for (let i = 0; i < 4; i++) {
    await buttons()[i].props.onClick()
    await nextTick()
    const [a, b, c] = sections()
    assert.match(text(a), /未確認直接對應/)
    assert.match(text(b), /本次未取得外部來源/)
    assert.ok(text(c).includes(result.evidence.reasons[i].reason_text))
    assert.equal(buttons()[i].props['aria-pressed'], true)
    if (i === 0) { assert.match(text(a), /手部形狀改變/); assert.doesNotMatch(text(a), /Oh, my God!/) }
    if (i === 1) { assert.match(text(a), /Oh, my God!/); assert.doesNotMatch(text(a), /手部形狀改變/) }
    if (i >= 2) { assert.match(text(a), /手部形狀改變/); assert.match(text(a), /Oh, my God!/) }
    assert.ok(text(a).length < 1000)
  }
  assert.ok(all(root).filter(n => n.type === 'details').every(n => !n.props.open))
  renderer.render(null, root)
})

test('source identity and provenance cannot be replaced by a link; redundant references do not duplicate cards', () => {
  const data = fixture().evidence
  data.reasons[0].evidence = [{ source_id: 's1', source_url: 'https://wrong.example', source_title: 'Wrong title' }]
  const cards = reasonCards(data, data.reasons[0])
  assert.equal(cards.length, 1)
  assert.equal(cards[0].source_title, 'Article A')
  data.sources.push({ ...data.sources[0], source_url: 'https://conflicting.example' })
  assert.deepEqual(reasonCards(data, data.reasons[0]), [])
})

test('long transcript collapses by default, expands losslessly, and resets for new content', async () => {
  const root = element('root')
  const long = 'Oh, my God! '.repeat(2000)
  const render = (value, locale = 'zh') => renderer.render(h(TextComponent, { text: value, locale }), root)
  render(long)
  assert.ok(text(root).length < 300)
  let button = all(root).find(n => n.type === 'button')
  assert.equal(button.props['aria-expanded'], false)
  await button.props.onClick()
  await nextTick()
  assert.ok(text(root).includes(long))
  render('Different content '.repeat(100), 'en')
  await nextTick()
  button = all(root).find(n => n.type === 'button')
  assert.equal(button.props['aria-expanded'], false)
  assert.match(text(button), /Read full text/)
  renderer.render(null, root)
})

test('English and Chinese disclosures, unconfirmed fetched sources, model knowledge and old results', async () => {
  const root = element('root')
  const result = fixture()
  result.evidence.sources.push({ source_id: 'other', source_title: 'Other article', retrieval_status: 'fetched', source_text: 'Original article' })
  result.evidence.claims.push({ claim_id: 'model', claim_text: 'Internal model knowledge', claim_provenance: { field: 'K_int' } })
  const render = (result, locale, recordsOnly = false) => renderer.render(h(Component, { result, locale, recordsOnly }), root)
  render(result, 'zh')
  assert.match(text(root), /其他搜尋來源|模型背景知識（非外部證據）/)
  assert.ok(all(root).filter(n => n.type === 'details').every(n => !n.props.open))
  assert.match(text(root), /語意關聯尚未確認/)
  render(result, 'en')
  await nextTick()
  assert.match(text(root), /Other search sources/)
  assert.match(text(root), /Model background \(not external evidence\)/)
  assert.match(text(root), /Semantic relationship unconfirmed/)
  render({ vid: 'legacy', reason: 'Legacy original reason' }, 'en', false)
  await nextTick()
  await all(root).find(n => n.type === 'button').props.onClick()
  await nextTick()
  assert.match(text(root), /Legacy original reason/)
  assert.doesNotMatch(text(root), /Article A|Other article/)
  renderer.render(null, root)
})

test('narrow-screen CSS and native keyboard controls remain explicit contracts (not browser layout verification)', () => {
  const panel = readFileSync(new URL('../src/components/EvidencePanel.vue', import.meta.url), 'utf8')
  assert.match(panel, /@media \(max-width: 820px\)/)
  assert.match(panel, /grid-template-columns: minmax\(0, 1fr\)/)
  assert.match(panel, /overflow-wrap: anywhere/)
  assert.match(panel, /<button type="button" :aria-pressed=/)
  assert.match(panel, /focus-visible/)
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  assert.ok(app.indexOf('<WorkspaceVersions') < app.indexOf('class="card workspace-result-row"'))
  const sections = ['<WorkspaceVersions', 'workspace-result-row', 'workspace-main-columns', '<details class="workspace-advanced"', 'data-category="evidence"', 'data-category="experiments"', 'data-category="data"', 'data-category="pipeline"'].map(marker => app.indexOf(marker))
  assert.ok(sections.every((position, index) => position >= 0 && (index === 0 || position > sections[index - 1])))
  assert.doesNotMatch(app, /08 ·|第 08 區|section 08/)
  assert.match(app, /const locale = ref\("zh"\)/)
  const ast = parse(app).descriptor.template.ast
  function visit(node, inDetails = false) {
    const inside = inDetails || node.tag === 'details'
    if (node.tag === 'InfoBlock') assert.equal(inside, true)
    for (const child of node.children || []) visit(child, inside)
  }
  visit(ast)
})

test('research upload, locked judgment, real-version polling, correction, selection and player isolation', async () => {
  const saved = {fetch:globalThis.fetch, window:globalThis.window, document:globalThis.document}
  const calls = []; const history = []; let scrolled = 0
  const groundedManifest={manifest_hash:'fixture-manifest',eligible_article_count:1,units:[{source_id:'s1',evidence_unit_id:'u1',provenance:{start:0,end:10,article_length:10}}],selection_records:[{source_index:0,source_id:'s1',selection_status:'selected',selection_reason:'Fixed prefix'}],k_ext:'[SOURCE:fixture]\nExact text',k_ext_length:27}
  const exp = {experiment_id:'exp1', video_asset_id:'sample', safe_display_filename:'Video-neutral.mp4', human_judgment:null, human_locked_at:null}
  const storage = new Map()
  globalThis.window = {setInterval:()=>1, clearInterval(){}, setTimeout:fn=>fn(), sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)}}
  globalThis.document = {getElementById:()=>({scrollIntoView:()=>scrolled++})}
  const output = id => {
    const result = fixture(); result.vid = result.evidence.video_id = 'sample'; result.pred_label = id === 'a1' ? 0 : 1
    result.analysis_id = result.evidence.analysis_id = id
    if (id !== 'a1') { result.reason = 'New corrected reason'; result.evidence.reasons = [{reason_id:'new',reason_text:result.reason,claim_ids:[]}]; result.evidence.sources=[] }
    return {student:result, retrieve:{vid:'sample',analysis_id:id,Rc:id === 'a1' ? 'Original claim' : 'User corrected claim',Rv:'Visual description',K_int:'Internal only',K_ext:'Search '+id},preprocess:{transcript:'Original transcript'}}
  }
  globalThis.fetch = async (url, options={}) => {
    calls.push({url:String(url),options}); let data
    if (url.endsWith('/video')) return {ok:true,blob:async()=>new Blob(['fixture'])}
    if (url.endsWith('/experiments')) data={experiment:{...exp},access_token:'token'}
    else if (url.endsWith('/human-judgment')) {Object.assign(exp,{human_judgment:'true',human_reason:'',human_locked_at:'locked'});data={...exp}}
    else if (url.endsWith('/versions') && options.method === 'POST') {
      const body=JSON.parse(options.body); const id='a'+(history.length+1)
      data={version_id:id,version_number:history.length+1,status:'running',stage:'retrieve',experiment_type:body.experiment_type,correction_payload:body}
      history.push(data)
    } else if (url.endsWith('/versions')) data={versions:structuredClone(history)}
    else if (url.endsWith('/experiments/exp1')) data={...exp,results_revealed:history[0]?.status === 'succeeded', ...(history[0]?.status === 'succeeded' ? {correct_answer:'真',correct_answer_vote:'true'}:{})}
    else if (url.endsWith('/automatic-summaries')) data={status:'unavailable',records:[]}
    else if (url.endsWith('/vote')) data={statistics:{total:1,true_percent:100,false_percent:0}}
    else if (url.endsWith('/translate')) data={success:true,translations:{...JSON.parse(options.body).texts,explanation:'Translated original reasoning'}}
    else if (url.endsWith('/source-grounded-preview')) data={available:true,manifest:groundedManifest}
    else if (url.endsWith('/source-ablation-preview')) {
      assert.ok(url.endsWith('/versions/a6/source-ablation-preview'))
      assert.deepEqual(JSON.parse(options.body).excluded_unit_ids,['prima-unit'])
      data={retained_evidence_units:[{evidence_unit_id:'ghost-unit',article_title:'GHOSTCAP'}],ablation_manifest:{manifest_hash:'ablation-preview',k_ext:'[SOURCE:ghost] GHOSTCAP saved body',k_ext_length:33}}
    }
    else throw new Error('Unexpected endpoint '+url)
    return {ok:true,json:async()=>data}
  }
  const root=element('root'); const settle=async()=>{for(let i=0;i<20;i++){await Promise.resolve();await nextTick()}}
  const button=label=>all(root).find(n=>n.type==='button' && text(n).includes(label))
  try {
    renderer.render(h(AppComponent),root); await settle()
    const file=new Blob(['fixture'],{type:'video/mp4'});file.name='fake-sample.mp4'
    await all(root).find(n=>n.type==='input'&&n.props.type==='file').props.onChange({target:{files:[file],value:'file'}});await settle()
    assert.doesNotMatch(text(root),/fake-sample/)
    assert.equal(calls.filter(c=>c.url.endsWith('/versions')&&c.options.method==='POST').length,0)
    assert.equal(button('開始判斷').props.disabled,true)
    assert.equal(all(root).filter(n=>n.type==='button'&&n.props.class==='judgment-choice').length,2)
    assert.doesNotMatch(text(root),/另行提交群體投票|Baseline Configuration|Video-neutral/)
    await button('真').props.onClick();await settle()
    const starting=button('開始判斷').props.onClick()
    await button('開始判斷').props.onClick()
    await starting;await settle()
    assert.equal(calls.filter(c=>c.url.endsWith('/human-judgment')).length,1)
    assert.equal(calls.filter(c=>c.url.endsWith('/versions')&&c.options.method==='POST').length,1)
    assert.ok(calls.findIndex(c=>c.url.endsWith('/human-judgment')) < calls.findIndex(c=>c.url.endsWith('/versions')&&c.options.method==='POST'))
    assert.deepEqual(JSON.parse(calls.find(c=>c.url.endsWith('/human-judgment')).options.body),{vote:'true',reason:''})
    assert.equal(calls.filter(c=>c.url.endsWith('/vote')).length,0)
    assert.match(text(all(root).find(n=>n.props.class==='compact-pipeline')),/執行中/)
    Object.assign(history[0],{status:'succeeded',stage:'done',output_snapshot:output('a1'),ablation_capabilities:{external_knowledge:{available:true}}})
    await button('更新分析結果').props.onClick();await settle()
    assert.match(text(root),/Original claim/);assert.equal(scrolled,1)
    const summaryCall=calls.find(c=>c.url.endsWith('/experiments/exp1/versions/a1/automatic-summaries'))
    assert.ok(summaryCall);assert.equal(summaryCall.options.method,'GET')
    assert.equal(summaryCall.options.headers.Authorization,'Bearer token')
    const player=all(root).find(n=>n.type==='video');player.currentTime=23
    const reasons=all(root).filter(n=>n.type==='button'&&'aria-pressed' in n.props&&!text(n).includes('baseline'))
    for(const reason of reasons){await reason.props.onClick();await settle();assert.equal(all(root).find(n=>n.type==='video'),player);assert.equal(player.currentTime,23)}
    const textarea=all(root).find(n=>n.type==='textarea')
    textarea.props['onUpdate:modelValue']('User corrected claim');await settle()
    assert.equal(button('建立新版本並重新分析').props.disabled,false)
    await button('建立新版本並重新分析').props.onClick();await settle()
    assert.equal(history.length,2);assert.match(text(root),/Original claim/)
    Object.assign(history[1],{status:'succeeded',stage:'done',output_snapshot:output('a2')})
    await button('更新分析結果').props.onClick();await settle()
    assert.equal(scrolled,2);assert.equal(all(root).find(n=>n.type==='video'),player)
    const research=all(root).find(n=>n.props.class==='correction-panel')
    assert.match(text(research),/User corrected claim/)
    const edit=()=>all(root).find(n=>n.type==='textarea'&&n.props['aria-label']==='Rc')
    edit().props['onUpdate:modelValue']('Unsaved Unicode 草稿\nline two');await settle()
    await button('更新分析結果').props.onClick();await settle()
    assert.equal(edit().value,'Unsaved Unicode 草稿\nline two')
    let warnings=0;window.confirm=()=>{warnings++;return false}
    await button('V1').props.onClick();await settle()
    assert.equal(button('V2').props['aria-pressed'],true);assert.equal(warnings,1)
    assert.equal(edit().value,'Unsaved Unicode 草稿\nline two')
    window.confirm=()=>true
    await button('V1').props.onClick();await settle()
    assert.equal(button('V1').props['aria-pressed'],true);assert.notEqual(edit().value,'Unsaved Unicode 草稿\nline two')
    await button('V2').props.onClick();await settle()

    assert.doesNotMatch(text(research),/Original claim/)
    const evidencePanel=all(root).find(n=>n.props.class==='evidence-panel')
    assert.doesNotMatch(text(evidencePanel),/Article A|Original reason A/)
    textarea.props['onUpdate:modelValue']('Correction that fails');await settle()
    assert.equal(all(all(root).find(n=>n.props.class==='correction-panel')).filter(n=>n.type==='input').length,0)
    await button('建立新版本並重新分析').props.onClick();await settle()
    Object.assign(history[2],{status:'failed',stage:'error',error:'Mock Student failure',failed_stage:'student'})
    await button('更新分析結果').props.onClick();await settle()
    assert.match(text(root),/Mock Student failure/)
    assert.doesNotMatch(text(all(root).find(n=>n.props.class==='compact-pipeline')),/等待|未知/)
    assert.doesNotMatch(text(root),/可變前端選項|mutable UI selection/)
    assert.doesNotMatch(text(root),/初始 Human Judgment 由後端鎖定/);assert.equal(exp.human_locked_at,'locked')
    assert.equal(scrolled,2)
    assert.equal(button('V1').props['aria-pressed'],true)
    renderer.render(null,root);renderer.render(h(AppComponent),root);await settle()
    assert.equal(button('V1').props['aria-pressed'],true)
    assert.match(text(root),/Original claim/)
    await button('V1').props.onClick();await settle()
    assert.equal(button('V1').props['aria-pressed'],true)
    const ablation=all(root).find(n=>n.props.class==='ablation-panel')
    const ablationButton=()=>all(ablation).find(n=>n.type==='button')
    assert.equal(ablationButton().props.disabled,true)
    all(ablation).find(n=>n.type==='input'&&n.props.type==='checkbox').props['onUpdate:modelValue'](true);await settle()
    await ablationButton().props.onClick();await settle()
    assert.equal(history[3].experiment_type,'evidence_ablation')
    assert.equal(history[3].correction_payload.ablation_mode,'external_knowledge')
    assert.equal(ablationButton().props.disabled,true)
    assert.match(text(root),/新版本執行中，結果尚未切換/)
    assert.match(text(all(root).find(n=>n.props.class==='compact-pipeline')),/目前／最新工作: V4/)
    assert.match(text(all(root).find(n=>n.props.class==='result-card')),/所選版本狀態: 完成/)
    const ablated=output('a4');ablated.retrieve.K_ext=''
    Object.assign(history[3],{status:'succeeded',stage:'done',output_snapshot:ablated,ablation_mode:'external_knowledge',effective_input_diff:{K_ext:{before:'Search a1',after:''}}})
    await button('更新分析結果').props.onClick();await settle()
    assert.equal(scrolled,3)
    assert.match(text(root),/此版本已排除 K_ext 輸入通道/)
    assert.match(text(root),/排除單位、有效輸入差異與限制/)
    await button('V1').props.onClick();await settle()
    all(ablation).find(n=>n.type==='input'&&n.props.type==='checkbox').props['onUpdate:modelValue'](true);await settle()
    await ablationButton().props.onClick();await settle()
    assert.equal(history[4].experiment_type,'evidence_ablation')
    Object.assign(history[4],{status:'failed',stage:'error',error:'Mock ablation Student timeout',failed_stage:'student'})
    await button('更新分析結果').props.onClick();await settle()
    assert.match(text(root),/Mock ablation Student timeout/)
    assert.match(text(all(root).find(n=>n.props.class==='compact-pipeline')),/V5.*失敗/)
    assert.match(text(all(root).find(n=>n.props.class==='result-card')),/所選版本狀態: 完成/)
    assert.equal(button('V1').props['aria-pressed'],true)
    assert.equal(scrolled,3)
    assert.doesNotMatch(text(root),/此版本已排除 K_ext 輸入通道/)
    const grounded=all(root).find(n=>n.props.class==='source-grounded-panel')
    const groundedButton=()=>all(grounded).find(n=>n.type==='button')
    assert.equal(groundedButton().props.disabled,true)
    all(grounded).find(n=>n.type==='input').props['onUpdate:modelValue'](true);await settle()
    await groundedButton().props.onClick();await settle()
    assert.equal(history[5].experiment_type,'source_grounded_baseline')
    assert.equal(history[5].correction_payload.manifest_hash,'fixture-manifest')
    assert.equal(groundedButton().props.disabled,true)
    const groundedOutput=output('a6');groundedOutput.retrieve.K_ext=groundedManifest.k_ext
    Object.assign(history[5],{status:'succeeded',stage:'done',output_snapshot:groundedOutput,source_grounded_manifest:groundedManifest,input_snapshot:{student_fields:{K_ext:groundedManifest.k_ext}}})
    await button('更新分析結果').props.onClick();await settle()
    assert.equal(scrolled,4);assert.match(text(root),/來源 manifest 與有效 K_ext/)
    assert.match(text(root),/新的來源可追蹤研究基準/)
    // Same operation version drives 02, 06, source preview and POST parent.
    const operationUnits=[{evidence_unit_id:'prima-unit',article_id:'prima',article_title:'Prima Games'},{evidence_unit_id:'ghost-unit',article_id:'ghost',article_title:'GHOSTCAP'}]
    history[5].source_grounded_manifest={...groundedManifest,units:operationUnits}
    history[5].ablation_capabilities={source_level:{available:true,units:operationUnits},external_knowledge:{available:true}}
    await button('更新分析結果').props.onClick();await settle()
    await button('V1').props.onClick();await settle()
    all(ablation).find(n=>n.type==='select').props['onUpdate:modelValue']('source_level');await settle()
    assert.equal(all(ablation).filter(n=>n.type==='input'&&n.props.value==='prima-unit').length,0)
    assert.match(text(all(root).find(n=>n.props.class==='result-card')),/目前操作版本 V1/)
    const comparison=all(root).find(n=>n.props.class==='version-list')
    const operationPlayer=all(root).find(n=>n.type==='video')
    const useV6=all(comparison).find(n=>n.type==='button'&&text(n).includes('V6'))
    assert.match(text(useV6),/以此版本進行實驗/)
    await useV6.props.onClick();await settle()
    assert.match(text(all(root).find(n=>n.props.class==='result-card')),/目前操作版本 V6/)
    assert.match(text(all(ablation).find(n=>n.props.class==='active-operation-version')),/V6.*a6/)
    assert.equal(all(ablation).find(n=>n.type==='input'&&n.props.value==='prima-unit').props.disabled,false)
    assert.equal(all(ablation).find(n=>n.type==='input'&&n.props.value==='ghost-unit').props.disabled,false)
    assert.ok(all(root).find(n=>n.type==='video') === operationPlayer)
    await button('V1').props.onClick();await settle()
    const shortcut=all(ablation).find(n=>n.type==='button'&&text(n).includes('以此版本進行實驗'))
    await shortcut.props.onClick();await settle()
    all(ablation).find(n=>n.type==='input'&&n.props.value==='prima-unit').props['onUpdate:modelValue'](['prima-unit']);await settle()
    assert.match(text(ablation),/GHOSTCAP saved body/)
    all(ablation).filter(n=>n.type==='input').at(-1).props['onUpdate:modelValue'](true);await settle()
    await all(ablation).find(n=>n.type==='button'&&text(n).includes('建立新版本')).props.onClick();await settle()
    assert.equal(history[6].correction_payload.parent_version_id,'a6')
    assert.deepEqual(history[6].correction_payload.excluded_unit_ids,['prima-unit'])
    assert.equal(history[6].correction_payload.manifest_hash,'ablation-preview')
    const historyRow=all(root).find(n=>n.props.class==='version-row')
    await all(historyRow).find(n=>n.type==='button'&&text(n).includes('V5')).props.onClick();await settle()
    assert.match(text(all(root).find(n=>n.props['data-category']==='pipeline')),/Mock ablation Student timeout/)
    assert.doesNotMatch(text(all(root).find(n=>n.props.class==='result-card')),/Original reason A/)
    assert.equal(all(root).find(n=>n.type==='video'),operationPlayer)
    await button('V1').props.onClick();await settle()
    const pollButton=button('更新分析結果')
    await button('English').props.onClick();await settle()
    assert.match(text(root),/Translated original reasoning/)
    const previousFetch=globalThis.fetch;let rejectOldPoll
    globalThis.fetch=(url,options)=>String(url).endsWith('/versions')?new Promise((_,reject)=>{rejectOldPoll=reject}):previousFetch(url,options)
    const oldPoll=pollButton.props.onClick();await settle()
    await button('V6').props.onClick();await settle()
    rejectOldPoll(new Error('Stale previous-version polling failure'));await oldPoll;await settle()
    assert.doesNotMatch(text(root),/Stale previous-version polling failure/)
    globalThis.fetch=previousFetch
    await button('Restart').props.onClick();await settle()
    assert.doesNotMatch(text(root),/Original reason A|Translated original reasoning|Article A/)
    assert.equal(storage.size,0)
    assert.ok(calls.some(c=>c.url.endsWith('/translate')))
    assert.ok(calls.filter(c=>c.url.includes('/experiments/')).every(c=>c.options.headers.Authorization==='Bearer token'))
  } finally {renderer.render(null,root);Object.assign(globalThis,saved)}
})

test('mounted Vue reason clicks change A/B/C, timestamp seek, missing evidence, and batch reset', async () => {
  const root = element('root')
  const result = fixture()
  const seeks = []
  const render = result => renderer.render(h(Component, { result, retrieve: {}, videoUrl: 'blob:test-only', locale: 'zh', onSeek: time => seeks.push(time) }), root)
  render(result)
  const buttons = () => all(root).filter(n => n.type === 'button' && 'aria-pressed' in n.props)
  const columns = () => all(root).find(n => n.props.class === 'evidence-columns')
  assert.ok(columns())
  assert.ok(buttons().every(b => b.props['aria-pressed'] === false))
  await buttons()[0].props.onClick()
  assert.match(text(columns()), /Article A/)
  assert.match(text(columns()), /Article B/) // available as an unconfirmed other source
  await nextTick()
  assert.equal(all(root).find(n => n.type === 'video'), undefined)
  assert.deepEqual(seeks, []) // selecting reasons must not interrupt playback
  await all(root).find(n => n.type === 'button' && text(n).includes('跳至')).props.onClick()
  assert.deepEqual(seeks, [12])
  await buttons()[1].props.onClick()
  await nextTick()
  assert.match(text(columns()), /Article B/)
  assert.match(text(columns()), /Article A/) // moves to other sources for reason B
  assert.match(text(columns()), /原文尚未取得/)
  assert.match(text(columns()), /未建立精確時間對應/)
  assert.match(text(columns()), /Original reason B/)
  await buttons()[2].props.onClick()
  await nextTick()
  assert.match(text(columns()), /尚無已確認的外部證據/)
  assert.match(text(columns()), /Article A/)
  assert.match(text(columns()), /Article B/)
  const next = fixture()
  next.analysis_id = next.evidence.analysis_id = 'a2'
  render(next)
  await nextTick()
  assert.ok(columns())
  assert.ok(buttons().every(b => b.props['aria-pressed'] === false))
  assert.ok(buttons().every(b => b.props["aria-pressed"] === false))
  renderer.render(null, root)
})

const DataComponent = (await import(componentUrl(new URL('../src/components/ResearchData.vue', import.meta.url)))).default
const SourceComponent = (await import(componentUrl(new URL('../src/components/EvidenceSourceCard.vue', import.meta.url)))).default

test('research cards preserve original text, expand, copy each field and handle clipboard failure', async () => {
  const root = element('root')
  const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  const copied = []
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { clipboard: { writeText: async value => copied.push(value) } } })
  const data = Object.fromEntries(['Rc', 'Rv', 'K_int', 'K_ext'].map(key => [key, `${key}: ` + 'Oh, my God! '.repeat(100)]))
  try {
    renderer.render(h(DataComponent, { data, locale: 'en', translations: { Rc: 'Translated only' } }), root)
    const articles = all(root).filter(n => n.type === 'article')
    assert.equal(articles.length, 4)
    for (const [i, article] of articles.entries()) {
      const key = Object.keys(data)[i]
      assert.ok(!text(article).includes(data[key]))
      await all(article).find(n => n.type === 'button' && 'aria-expanded' in n.props).props.onClick()
      await nextTick()
      assert.ok(text(article).includes(data[key]))
      await all(article).find(n => n.type === 'button' && text(n).includes('Copy')).props.onClick()
      await nextTick()
      assert.equal(copied[i], data[key])
    }
    globalThis.navigator.clipboard.writeText = async () => { throw Error('denied') }
    await all(articles[0]).find(n => n.type === 'button' && text(n).includes('Copy')).props.onClick()
    await nextTick()
    assert.match(text(root), /Clipboard unavailable/)
    renderer.render(h(DataComponent, { data: {}, locale: 'zh' }), root)
    await nextTick()
    assert.match(text(root), /資料未提供/)
    assert.ok(all(root).filter(n => n.type === 'button').every(n => n.props.disabled))
    assert.doesNotMatch(text(root), /Oh, my God!/)
  } finally {
    renderer.render(null, root)
    if (originalNavigator) Object.defineProperty(globalThis, 'navigator', originalNavigator)
    else delete globalThis.navigator
  }
})

test('source cards expose five fields without substituting titles, fabricated quotes or semantic certainty', async () => {
  const root = element('root')
  const source = { source_title: 'Real title', source_site: 'news.example', source_url: 'https://news.example/story', published_date: '2024-01-02', retrieval_status: 'fetched', source_text: 'Actual excerpt', source_excerpt: 'Actual excerpt', excerpt_provenance: { field: 'source_text', start: 0, end: 14 } }
  const render = source => renderer.render(h(SourceComponent, { source, locale: 'zh' }), root)
  render(source)
  for (const value of ['Real title', 'news.example', '2024-01-02', 'Actual excerpt', '支持／反駁關係：證據不足']) assert.ok(text(root).includes(value))
  assert.ok(all(root).filter(n => n.type === 'a').every(n => n.props.href === source.source_url))
  render({ ...source, source_title: null, published_date: null, source_excerpt: 'Fake quote' })
  await nextTick()
  assert.match(text(root), /文章標題未提供/)
  assert.match(text(root), /日期未提供/)
  assert.doesNotMatch(text(root), /Fake quote/)
  render({ source_url: 'javascript:invalid', retrieval_status: 'access_denied' })
  await nextTick()
  assert.match(text(root), /原文尚未取得/)
  assert.match(text(root), /來源網址缺失、無效/)
  assert.equal(all(root).filter(n => n.type === 'a').length, 0)
  renderer.render(null, root)
})

test('empty and single-reason results retain clear states without fabricated evidence', async () => {
  const root = element('root')
  renderer.render(h(Component, { result: { reason: '' }, locale: 'zh' }), root)
  assert.match(text(root), /尚未提供判斷理由/)
  renderer.render(h(Component, { result: { reason: 'Only original reason' }, locale: 'en' }), root)
  await nextTick()
  const buttons = all(root).filter(n => n.type === 'button' && 'aria-pressed' in n.props)
  assert.equal(buttons.length, 1)
  await buttons[0].props.onClick()
  await nextTick()
  assert.match(text(root), /No external sources/)
  assert.match(text(root), /Only original reason/)
  renderer.render(null, root)
})


test('display inventory includes legacy URLs only from the same video and batch without creating associations', () => {
  const result = { vid: 'legacy', reason: 'Original reason' }
  const retrieve = { vid: 'legacy', uri: ['https://a.example/a', 'https://a.example/a', 'bad-url'] }
  const data = evidenceView(result, retrieve)
  assert.equal(searchSources(data, result, retrieve).length, 2)
  assert.deepEqual(reasonCards(data, data.reasons[0]), [])
  for (const changed of [{ ...retrieve, vid: 'other' }, { ...retrieve, analysis_id: 'new' }, { ...retrieve, run_id: 2 }]) {
    assert.deepEqual(searchSources(data, result, changed), [])
  }
  const modern = fixture()
  const inventory = searchSources(evidenceView(modern), modern, null)
  assert.equal(inventory.length, 2)
  assert.equal(otherSearchSources(inventory, reasonCards(modern.evidence, modern.evidence.reasons[0]))[0].source_id, 's2')
  const duplicate = { ...modern.evidence.sources[0], source_id: 'another-chunk' }
  modern.evidence.sources.push(duplicate)
  assert.equal(searchSources(modern.evidence, modern).length, 2)
  assert.equal(otherSearchSources(searchSources(modern.evidence, modern), reasonCards(modern.evidence, modern.evidence.reasons[0])).length, 1)
})

test('B separates linked and other sources, updates per reason, and retains original links without fabricated quotes', async () => {
  const root = element('root')
  const result = fixture()
  result.evidence.sources.push({ source_id: 'missing', source_title: 'Missing URL' })
  result.evidence.sources.push({ source_id: 'invalid', source_url: 'javascript:invalid', source_title: 'Invalid URL' })
  const render = value => renderer.render(h(Component, { result: value, locale: 'zh' }), root)
  render(result)
  const buttons = () => all(root).filter(n => n.type === 'button' && 'aria-pressed' in n.props)
  const b = () => all(root).find(n => n.type === 'h4' && text(n).startsWith('B.')).parent
  const direct = () => b().children.filter(n => n.props.class === 'evidence-card')
  const other = () => all(b()).find(n => n.props.class === 'other-sources')
  await buttons()[0].props.onClick(); await nextTick()
  assert.equal(direct().length, 0) // Literal mapping is no longer direct semantic evidence.
  assert.match(text(other()), /查看其他搜尋來源（4）/)
  assert.match(text(other()), /Article A/)
  assert.match(text(other()), /Article B/)
  assert.match(text(other()), /原文尚未取得/)
  assert.match(text(other()), /來源網址缺失、無效/)
  assert.match(text(other()), /與目前理由的關聯未確認/)
  assert.ok(all(other()).some(n => n.type === 'a' && n.props.href === 'https://b.example/b'))
  await buttons()[1].props.onClick(); await nextTick()
  assert.equal(direct().length, 0)
  assert.match(text(other()), /Article B/)
  assert.match(text(other()), /Article A/)
  assert.match(text(other()), /尚無可直接核對的摘錄/)
  await buttons()[2].props.onClick(); await nextTick()
  assert.equal(direct().length, 0)
  assert.match(text(other()), /查看其他搜尋來源（4）/)
  assert.equal(all(other()).filter(n => n.props.class === 'evidence-card').length, 4)
  const empty = fixture(); empty.evidence.sources = []
  render(empty); await nextTick()
  assert.match(text(b()), /本次未取得外部來源/)
  assert.equal(other(), undefined)
  renderer.render(null, root)
})

test('legacy URLs remain visible in B without evidence, and stale retrieve URLs never appear', async () => {
  const root = element('root')
  const result = { vid: 'old', reason: 'Original reason' }
  renderer.render(h(Component, { result, retrieve: { vid: 'old', uri: ['https://legacy.example/article'] }, locale: 'zh' }), root)
  assert.match(text(root), /查看其他搜尋來源（1）/)
  assert.ok(all(root).some(n => n.type === 'a' && n.props.href === 'https://legacy.example/article'))
  assert.match(text(root), /文章標題未提供/)
  renderer.render(h(Component, { result, retrieve: { vid: 'old', analysis_id: 'different', uri: ['https://stale.example/article'] }, locale: 'zh' }), root)
  await nextTick()
  assert.doesNotMatch(text(root), /legacy.example|stale.example/)
  assert.match(text(root), /本次未取得外部來源/)
  renderer.render(null, root)
})

test('results workspace preserves controls and technical records after research consolidation', () => {
  const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  const at = marker => source.indexOf(marker)
  const between = (start, end) => source.slice(at(start), at(end))
  assert.match(source.slice(at('data-category="pipeline"'),source.indexOf('<script setup>')), /preprocessDisplaySteps|retrieveStatusText|studentStatusText/)
  assert.match(between('01 · Video', '02 · Verification'), /Full original reasoning \/ translation/)
  assert.match(between('01 · Video', '02 · Verification'), /@click="refreshOutputs"/)
  assert.match(between('01 · Video', '02 · Verification'), /@click="resetGame"/)
  assert.match(between('data-category="evidence"', 'data-category="experiments"'), /EvidencePanel/)
  assert.match(between('02 · Verification','03 · News'), /InputCorrection[\s\S]*@submit="submitCorrection"[\s\S]*ResearchData/)
  const technical = between('data-category="data"', 'data-category="pipeline"')
  for (const marker of ['studentPromptDisplayFields.system_prompt', 'studentPromptDisplayFields.user_prompt', 'statusStudentPrompt', 'retrieve: retrieveResult', 'result: studentResult', 'Prompts below are display text']) assert.ok(technical.includes(marker), marker)
  assert.doesNotMatch(source, /08 ·|records-only|第 08 區/)
})


test('validated AI assessments show direct evidence, contextual sources and original C without inventing links', async () => {
  const root = element('root')
  const result = fixture()
  const data = result.evidence
  data.sources[0].article_text = '😀 First excerpt'
  const record = { reason_id: 'r1', claim_id: 'c1', source_id: 's1', relevance: 'direct', stance: 'supports', target_scope: 'single', assessment_status: 'validated',
    verbatim_excerpt: 'First excerpt', excerpt_start: 2, excerpt_end: 15,
    excerpt_provenance: { field: 'article_text', start: 2, end: 15, offset_unit: 'unicode_code_points' },
    model_name: 'mock-only', prompt_version: 'test-v1', coverage: 'complete' }
  data.assessment = { schema_version: 1, video_id: 'v1', analysis_id: 'a1', model_name: 'mock-only', prompt_version: 'test-v1', status: 'complete', records: [record] }
  assert.equal(assessedCards(data, data.reasons[0])[0].source_excerpt, 'First excerpt')
  renderer.render(h(Component, { result, locale: 'zh' }), root)
  await all(root).find(n => n.type === 'button' && 'aria-pressed' in n.props).props.onClick()
  await nextTick()
  assert.match(text(root), /AI 語意評估（非人工確認）/)
  assert.match(text(root), /直接相關 · 支持/)
  assert.match(text(root), /Original reason A/)
  const changed = structuredClone(result)
  changed.evidence.assessment.records[0].relevance = 'contextual'
  renderer.render(h(Component, { result: changed, locale: 'zh' }), root)
  await nextTick()
  const other = all(root).find(n => n.props.class === 'background-sources')
  assert.match(text(other), /僅背景相關/)
  assert.match(text(other), /尚未建立支持／反駁關係/)
  assert.match(text(other), /First excerpt/)
  assert.equal(assessedCards(changed.evidence, changed.evidence.reasons[0])[0].assessment.stance, 'not_established')
  for (const delta of [{ verbatim_excerpt: 'invented' }, { source_id: 'missing' }, { claim_id: 'missing' }, { excerpt_start: 3 }, { model_name: 'wrong' }]) {
    const invalid = structuredClone(result.evidence)
    Object.assign(invalid.assessment.records[0], delta)
    assert.ok(assessedCards(invalid, invalid.reasons[0]).every(card => card.assessment.stance === 'not_established' && card.source_excerpt === null))
  }
  const stale = structuredClone(data); stale.assessment.analysis_id = 'other'
  assert.deepEqual(assessedCards(stale, stale.reasons[0]), [])
  renderer.render(null, root)
})

test('domain-only grounding titles and YouTube HTML are not presented as article titles or speech', () => {
  const root = element('root')
  renderer.render(h(SourceComponent, { source: { source_title: 'youtube.com', source_url: 'https://www.youtube.com/watch?v=abcdefghijk', retrieval_status: 'fetched', source_text: 'Page metadata' }, locale: 'zh' }), root)
  assert.match(text(root), /文章標題未提供/)
  assert.match(text(root), /尚未取得 YouTube 字幕／逐字稿/)
  renderer.render(null, root)
})


test('ablation panel exposes unavailable source lineage and requires explicit channel confirmation', async () => {
  const Ablation=(await import(componentUrl(new URL('../src/components/EvidenceAblation.vue',import.meta.url)))).default
  const root=element('root'), submissions=[]
  const version={version_id:'parent',status:'succeeded',output_snapshot:{retrieve:{evidence:fixture().evidence}},ablation_capabilities:{external_knowledge:{available:true},source_level:{available:false}}}
  renderer.render(h(Ablation,{version,locale:'zh',busy:false,onSubmit:p=>submissions.push(p)}),root);await nextTick()
  const button=()=>all(root).find(n=>n.type==='button')
  assert.equal(button().props.disabled,true)
  const selector=all(root).find(n=>n.type==='select')
  selector.props['onUpdate:modelValue']('source_level');await nextTick()
  assert.match(text(root),/缺乏可驗證的單篇來源 lineage/)
  assert.equal(all(root).filter(n=>n.type==='input'&&n.props.type==='checkbox'&&n.props.disabled!==undefined&&n.props.disabled!==false).length,3)
  assert.equal(button().props.disabled,true)
  selector.props['onUpdate:modelValue']('external_knowledge');await nextTick()
  all(root).find(n=>n.type==='input').props['onUpdate:modelValue'](true);await nextTick()
  assert.equal(button().props.disabled,false)
  button().props.onClick()
  assert.deepEqual(submissions,[{parent_version_id:'parent',ablation_mode:'external_knowledge',excluded_source_ids:[]}])
  renderer.render(h(Ablation,{version:{...version,version_id:'child',ablation_capabilities:{external_knowledge:{available:false,reason:'K_ext empty'}}},locale:'en',busy:false}),root);await nextTick()
  assert.equal(button().props.disabled,true)
  assert.match(text(root),/K_ext empty/)
  renderer.render(null,root)
})

test('saved article preview remains unconfirmed and Google challenge is not a publisher', async () => {
  const root=element('root')
  const source={source_id:'s0',source_url:'https://news.example/story',resolved_url:'https://news.example/story',article_title:'Saved title',published_date:'2026-10-24',retrieval_status:'fetched',article_text:'Exact saved article words.'}
  renderer.render(h(SourceComponent,{source,locale:'zh',unlinked:true}),root);await nextTick()
  assert.match(text(root),/Exact saved article words/)
  assert.match(text(root),/保存正文預覽（未確認與理由直接相關）/)
  renderer.render(h(SourceComponent,{source:{...source,source_url:'https://vertexaisearch.cloud.google.com/grounding-api-redirect/x',resolved_url:'https://www.google.com/sorry/index',retrieval_status:'access_denied'},locale:'zh',unlinked:true}),root);await nextTick()
  assert.match(text(root),/非新聞發布網站/)
  assert.equal(all(root).filter(n=>n.type==='blockquote').length,0)
  assert.ok(all(root).filter(n=>n.type==='a').every(n=>n.props.href.includes('grounding-api-redirect')))
  renderer.render(null,root)
})

test('assessment control only POSTs after confirmation and rejects late version responses', async () => {
  const Control=(await import(componentUrl(new URL('../src/components/EvidenceAssessmentControl.vue',import.meta.url)))).default
  const root=element('root'), calls=[], received=[]
  const ready={available:true,status:'ready',plan:{claim_count:2,article_count:1,pair_count:2,max_calls:6,max_cost_usd:0.06},assessment:null}
  let resolveOld
  const request=async (url,options={})=>{calls.push({url,options});if(options.method==='POST')return new Promise(r=>{resolveOld=r});return ready}
  const render=id=>renderer.render(h(Control,{versionId:id,request,locale:'zh',onAssessment:a=>received.push(a)}),root)
  const settle=async()=>{for(let i=0;i<8;i++){await Promise.resolve();await nextTick()}}
  render('v1');await settle()
  assert.equal(calls.length,1);assert.equal(calls[0].options.method,undefined)
  const button=()=>all(root).find(n=>n.type==='button')
  assert.equal(button().props.disabled,true)
  all(root).find(n=>n.type==='input').props['onUpdate:modelValue'](true);await settle()
  button().props.onClick();await settle()
  assert.equal(JSON.parse(calls[1].options.body).confirm_cost,true);assert.equal(button().props.disabled,true)
  render('v2');await settle();resolveOld({...ready,assessment:{version_id:'v1'}});await settle()
  assert.ok(!received.some(a=>a?.version_id==='v1'))
  assert.equal(button().props.disabled,true)
  renderer.render(null,root)
})

test('direct article cards deduplicate verified bodies while retaining raw source references', async () => {
  const root=element('root'), result=fixture(), data=result.evidence
  data.sources[0].article_text='First excerpt';data.sources[0].article_text_sha256='same-body-hash'
  data.sources.push({...data.sources[0],source_id:'duplicate-source'})
  const row={reason_id:'r1',claim_id:'c1',source_id:'s1',relevance:'direct',stance:'refutes',target_scope:'single',assessment_status:'validated',verbatim_excerpt:'First excerpt',excerpt_start:0,excerpt_end:13,excerpt_provenance:{field:'article_text',start:0,end:13},model_name:'mock',prompt_version:'test'}
  data.assessment={schema_version:1,video_id:'v1',analysis_id:'a1',model_name:'mock',prompt_version:'test',records:[row,{...row,source_id:'duplicate-source'}]}
  renderer.render(h(Component,{result,locale:'zh'}),root)
  await all(root).find(n=>n.type==='button'&&'aria-pressed' in n.props).props.onClick();await nextTick()
  const b=all(root).find(n=>n.type==='h4'&&text(n).startsWith('B.')).parent
  assert.equal(b.children.filter(n=>n.props.class==='evidence-card').length,1)
  assert.match(text(b),/直接相關 · 反駁/)
  assert.match(text(b),/duplicate-source/) // preserved in the collapsed raw records
  renderer.render(null,root)
})

test('source-grounded preview requires confirmation and ignores stale parent response', async()=>{
  const Control=(await import(componentUrl(new URL('../src/components/SourceGroundedBaseline.vue',import.meta.url)))).default
  const root=element('root'), submissions=[];let resolveOld
  const manifest={manifest_hash:'h',eligible_article_count:1,units:[{evidence_unit_id:'u',source_id:'s',provenance:{start:0,end:4,article_length:40}}],selection_records:[{source_index:0,source_id:'s',selection_status:'selected',selection_reason:'prefix'}],k_ext:'text',k_ext_length:4}
  const request=url=>url.includes('/old/')?new Promise(r=>{resolveOld=r}):Promise.resolve({available:false,error:'No eligible saved article body',manifest:{...manifest,units:[],eligible_article_count:0}})
  const render=id=>renderer.render(h(Control,{version:{version_id:id,status:'succeeded'},request,locale:'en',onSubmit:p=>submissions.push(p)}),root)
  const settle=async()=>{for(let i=0;i<8;i++){await Promise.resolve();await nextTick()}}
  render('old');await settle();render('new');await settle();resolveOld({available:true,manifest});await settle()
  assert.match(text(root),/No eligible saved article body/)
  assert.equal(all(root).find(n=>n.type==='button').props.disabled,true);assert.equal(submissions.length,0)
  renderer.render(null,root)
})


test('source-level selection previews server input, confirms, reuses success and resets on version switch', async () => {
  const Ablation=(await import(componentUrl(new URL('../src/components/EvidenceAblation.vue',import.meta.url)))).default
  const root=element('root'), submissions=[], requests=[]
  const units=[{evidence_unit_id:'prima',article_id:'a',article_title:'Prima Games'},{evidence_unit_id:'ghost',article_id:'b',article_title:'GHOSTCAP'}]
  const version={version_id:'grounded',status:'succeeded',source_grounded_manifest:{selection_records:[]},ablation_capabilities:{source_level:{available:true,units},external_knowledge:{available:true}}}
  const request=async (url,options)=>{requests.push([url,JSON.parse(options.body)]);return {retained_evidence_units:[units[1]],ablation_manifest:{manifest_hash:'hash',k_ext:'[SOURCE:b] GHOSTCAP body',k_ext_length:25}}}
  const props={version,request,versions:[],locale:'zh',onSubmit:p=>submissions.push(p)}
  renderer.render(h(Ablation,props),root);await nextTick()
  all(root).find(n=>n.type==='select').props['onUpdate:modelValue']('source_level');await nextTick()
  all(root).find(n=>n.type==='input'&&n.props.value==='prima').props['onUpdate:modelValue'](['prima'])
  await nextTick();await nextTick()
  assert.deepEqual(requests[0][1],{excluded_unit_ids:['prima']})
  assert.match(text(root),/GHOSTCAP body/)
  const button=()=>all(root).find(n=>n.type==='button')
  assert.equal(button().props.disabled,true)
  all(root).filter(n=>n.type==='input').at(-1).props['onUpdate:modelValue'](true);await nextTick()
  button().props.onClick()
  assert.deepEqual(submissions[0],{parent_version_id:'grounded',ablation_mode:'source_level',excluded_source_ids:[],excluded_unit_ids:['prima'],manifest_hash:'hash',confirm:true})
  renderer.render(h(Ablation,{...props,versions:[{parent_version_id:'grounded',version_id:'existing',version_number:3,status:'succeeded',ablation_mode:'source_level',ablation_manifest:{manifest_hash:'hash'}}]}),root);await nextTick()
  assert.match(text(root),/既有成功版本/)
  renderer.render(h(Ablation,{...props,version:{...version,version_id:'mixed',ablation_capabilities:{source_level:{available:false}}}}),root);await nextTick();await nextTick()
  assert.equal(button().props.disabled,true)
  assert.doesNotMatch(text(root),/GHOSTCAP body/)
  renderer.render(null,root)
})


test('source-ablation comparison shows retained units, input diff, audit and new model reason', async () => {
  const Compare=(await import(componentUrl(new URL('../src/components/VersionComparison.vue',import.meta.url)))).default
  const root=element('root')
  const parent={version_id:'p',version_number:2,status:'succeeded',output_snapshot:{retrieve:{K_ext:'Prima and Ghost'},student:{pred_label:0,reason:'Parent reason'}}}
  const child={version_id:'c',version_number:3,parent_version_id:'p',status:'succeeded',experiment_type:'evidence_ablation',ablation_mode:'source_level',excluded_evidence_units:[{article_id:'prima-id',article_title:'Prima Games'}],retained_evidence_units:[{article_id:'ghost-id',article_title:'GHOSTCAP'}],ablation_manifest:{k_ext:'Ghost only'},contamination_audit:{removed_unit_ids_absent:true},output_snapshot:{retrieve:{K_ext:'Ghost only'},student:{pred_label:1,reason:'New Student reason'}}}
  renderer.render(h(Compare,{versions:[parent,child],selected:'c',locale:'zh'}),root);await nextTick()
  assert.match(text(root),/Prima Games/);assert.match(text(root),/GHOSTCAP/)
  assert.match(text(root),/Ghost only/);assert.match(text(root),/Parent reason/);assert.match(text(root),/New Student reason/)
  assert.match(text(root),/removed_unit_ids_absent/)
  assert.doesNotMatch(text(root),/單篇來源排除不可用/)
  renderer.render(null,root)
})
test('field claim assessment selector keeps independent targets and evidence separate', async () => {
 const Control=(await import(componentUrl(new URL('../src/components/EvidenceAssessmentControl.vue',import.meta.url)))).default
 const root=element('root')
 const claims=[{claim_id:'field-a',claim_text:'Original event occurred.',claim_provenance:{field:'Rc'}},{claim_id:'field-b',claim_text:'Video is CGI.',claim_provenance:{field:'Rv'}}]
 const source={source_id:'s',source_title:'Saved article',retrieval_status:'fetched',article_text:'Original event occurred.'}
 const assessment={schema_version:1,analysis_id:'v',video_id:'video',model_name:'mock',prompt_version:'test',claims,records:claims.map((c,i)=>({reason_id:c.claim_id,claim_id:c.claim_id,source_id:'s',model_name:'mock',prompt_version:'test',assessment_status:'validated',target_scope:'single',relevance:i?'insufficient':'direct',stance:i?'not_established':'supports',verbatim_excerpt:i?null:source.article_text,excerpt_start:i?null:0,excerpt_end:i?null:source.article_text.length,excerpt_provenance:i?null:{field:'article_text',start:0,end:source.article_text.length}}))}
 const response={available:true,status:'cached',claims,sources:[source],assessment}
 let calls=0
 renderer.render(h(Control,{versionId:'v',locale:'zh',request:async()=>{calls++;return response}}),root)
 for(let i=0;i<8;i++){await Promise.resolve();await nextTick()}
 assert.match(text(root),/直接相關 · 支持/)
 all(root).find(n=>n.type==='select').props['onUpdate:modelValue']('field-b');await nextTick()
 assert.match(text(root),/目前沒有已驗證的直接支持／反駁來源/)
 assert.doesNotMatch(text(root).split('評估紀錄與限制')[0],/直接相關 · 支持/)
 assert.equal(calls,1)
 renderer.render(null,root)
})
test('source summaries require separate cost consent, persisted review and Student confirmation', async () => {
 const Control=(await import(componentUrl(new URL('../src/components/SourceAwareBaseline.vue',import.meta.url)))).default
 const root=element('root'), submitted=[],calls=[]
 const cards=['S1','S2','S3'].map((id,i)=>({source_id:id,title:'News '+id,url:'https://news.example/'+id,url_valid:true,summary:null,can_review:false,review:{decision:'manual_review_required'},quote_validation:{status:'unavailable'}}))
 let state={available:false,generation_available:true,summary_status:'not_generated',cache_key:'cache',review_revision:'r0',attempt_id:null,manifest:{manifest_hash:'hash',k_ext:'',units:[],news_cards:cards},fallback_cards:[{source_id:'g',title:'Missing article',url:'https://news.example/missing',url_valid:true}]}
 const request=async (url,options={})=>{
  calls.push({url,options})
  if(url.endsWith('/source-summaries')) {
   assert.equal(JSON.parse(options.body).confirm_cost,true)
   state={...state,summary_status:'succeeded',attempt_id:'attempt',manifest:{...state.manifest,news_cards:cards.map((c,i)=>({...c,summary:'AI summary '+c.source_id,can_review:true,quote_validation:{status:i===1?'normalized_match':'exact_match',source_excerpt:'Saved quote '+c.source_id}}))}}
  }
  if(url.endsWith('/source-summary-review')) {
   const body=JSON.parse(options.body);assert.equal(body.attempt_id,'attempt')
   const next=state.manifest.news_cards.map(c=>c.source_id===body.source_id?{...c,review:{decision:body.decision}}:c)
   const approved=next.filter(c=>c.review.decision==='approved')
   state={...state,review_revision:'r1',available:approved.length>0,manifest:{...state.manifest,news_cards:next,units:approved,k_ext:approved.map(c=>'['+c.source_id+'] '+c.summary).join('\n')}}
  }
  return structuredClone(state)
 }
 const render=id=>renderer.render(h(Control,{version:{version_id:id,status:'succeeded'},request,locale:'zh',onSubmit:p=>submitted.push(p)}),root)
 const settle=async()=>{for(let i=0;i<10;i++){await Promise.resolve();await nextTick()}}
 const button=phrase=>all(root).find(n=>n.type==='button'&&text(n).includes(phrase))
 render('v1');await settle()
 assert.equal(calls.length,1);assert.equal(calls[0].options.method,undefined)
 assert.equal(button('生成逐篇摘要').props.disabled,true)
 all(root).find(n=>n.type==='input').props['onUpdate:modelValue'](true);await settle()
 button('生成逐篇摘要').props.onClick();await settle()
 assert.equal(submitted.length,0);assert.equal(button('建立 Source-aware').props.disabled,true)
 assert.match(text(root),/exact_match/);assert.match(text(root),/normalized_match/);assert.match(text(root),/Missing article/)
 button('核准此摘要').props.onClick();await settle()
 assert.equal(button('建立 Source-aware').props.disabled,true)
 button('重新讀取').props.onClick();await settle();assert.match(text(root),/approved/)
 all(root).find(n=>n.type==='input').props['onUpdate:modelValue'](true);await settle()
 button('建立 Source-aware').props.onClick();await settle()
 assert.deepEqual(submitted[0],{experiment_type:'source_aware_baseline',parent_version_id:'v1',manifest_hash:'hash',confirm:true})
 assert.equal(state.manifest.k_ext,'[S1] AI summary S1')
 render('v2');await settle();assert.equal(button('建立 Source-aware').props.disabled,true)
 assert.equal(calls.filter(c=>c.url.endsWith('/source-summaries')).length,1)
 renderer.render(null,root)
})

test('reviewed source-aware comparison retains parent reason, actual input and review manifest', async () => {
 const Compare=(await import(componentUrl(new URL('../src/components/VersionComparison.vue',import.meta.url)))).default
 const root=element('root'),selected=[]
 const parent={version_id:'original',version_number:1,status:'succeeded',output_snapshot:{retrieve:{K_ext:'Original mixed knowledge'},student:{pred_label:0,reason:'Original reason'}}}
 const child={version_id:'reviewed',version_number:2,parent_version_id:'original',experiment_type:'source_aware_baseline',status:'succeeded',source_aware_manifest:{review_snapshot:{S1:{decision:'approved'}},semantic_verified:false},input_snapshot:{student_fields:{K_ext:'[S1] Approved summary'}},rerun_stage_records:[{stage:'student',status:'succeeded'}],output_snapshot:{retrieve:{K_ext:'[S1] Approved summary'},student:{pred_label:1,reason:'New independent reason'}}}
 renderer.render(h(Compare,{versions:[parent,child],selected:'reviewed',locale:'zh',onSelect:id=>selected.push(id)}),root);await nextTick()
 for(const phrase of ['Original reason','New independent reason','Original mixed knowledge','[S1] Approved summary','approved','semantic_verified','Real / 真','Fake / 假']) assert.ok(text(root).includes(phrase),phrase)
 all(root).find(n=>n.type==='button').props.onClick();assert.deepEqual(selected,['original'])
 renderer.render(null,root)
})

test('source summary controls reject late generation responses from another version', async () => {
 const Control=(await import(componentUrl(new URL('../src/components/SourceAwareBaseline.vue',import.meta.url)))).default
 const root=element('root');let finish
 const state={generation_available:true,summary_status:'not_generated',cache_key:'cache',manifest:{news_cards:[],units:[],k_ext:''}}
 const request=async (url,options={})=>options.method==='POST'?new Promise(r=>{finish=r}):state
 const render=id=>renderer.render(h(Control,{version:{version_id:id,status:'succeeded'},request,locale:'zh'}),root)
 const settle=async()=>{for(let i=0;i<10;i++){await Promise.resolve();await nextTick()}}
 render('old');await settle();all(root).find(n=>n.type==='input').props['onUpdate:modelValue'](true);await settle()
 all(root).find(n=>n.type==='button'&&text(n).includes('生成逐篇')).props.onClick();await settle()
 render('new');await settle();finish({...state,error:'STALE-OLD-VERSION'});await settle()
 assert.doesNotMatch(text(root),/STALE-OLD-VERSION/)
 renderer.render(null,root)
})

test('grounded explanation only runs after consent and keeps source relation distinct from verdict', async () => {
 const Control=(await import(componentUrl(new URL('../src/components/GroundedExplanation.vue',import.meta.url)))).default
 const root=element('root'),calls=[]
 const request=async(url,options={})=>{calls.push(options);return {available:true,status:options.method?'complete':'ready',plan:{max_calls:6},assessment:options.method?{}:null,items:options.method?[{source_id:'S1',title:'Saved news',url:'https://example.com/article',claim:'Historical event happened.',relation:'Support',quote:'Saved exact article quote',content_quality:'partial_article'}]:[]}}
 renderer.render(h(Control,{versionId:'v2',request}),root)
 for(let i=0;i<6;i++){await Promise.resolve();await nextTick()}
 assert.equal(calls.length,1);assert.equal(calls[0].method,undefined)
 assert.equal(all(root).find(n=>n.type==='button').props.disabled,true)
 all(root).find(n=>n.type==='input').props['onUpdate:modelValue'](true);await nextTick()
 all(root).find(n=>n.type==='button').props.onClick()
 for(let i=0;i<6;i++){await Promise.resolve();await nextTick()}
 assert.equal(JSON.parse(calls[1].body).confirm_cost,true)
 assert.match(text(root),/Saved exact article quote/);assert.match(text(root),/不是 Student 原始推理/)
 assert.equal(all(root).find(n=>n.type==='a').props.rel,'noopener noreferrer')
 renderer.render(null,root)
})

test('grounded explanation retry requires new consent and sends saved attempt identity', async () => {
 const Control=(await import(componentUrl(new URL('../src/components/GroundedExplanation.vue',import.meta.url)))).default
 const root=element('root'),calls=[]
 const request=async(url,options={})=>{calls.push(options);return {available:true,status:'partial',attempt_id:'first',retry_available:true,plan:{max_calls:6},assessment:{},items:[],support_summary:{supported_claims:1,evaluated_claims:3,notice:'部分主張獲支持'}}}
 renderer.render(h(Control,{versionId:'v3',request}),root)
 for(let i=0;i<6;i++){await Promise.resolve();await nextTick()}
 const button=()=>all(root).find(n=>n.type==='button'&&text(n).includes('重新評估'))
 assert.equal(button().props.disabled,true);assert.match(text(root),/部分主張獲支持/)
 all(root).find(n=>n.type==='input').props['onUpdate:modelValue'](true);await nextTick();button().props.onClick()
 for(let i=0;i<6;i++){await Promise.resolve();await nextTick()}
 assert.deepEqual(JSON.parse(calls[1].body),{confirm_cost:true,retry_of:'first'})
 assert.equal(button().props.disabled,true)
 renderer.render(null,root)
})

test('semantic support with failed provenance is not displayed as confirmed support', async () => {
 const Control=(await import(componentUrl(new URL('../src/components/GroundedExplanation.vue',import.meta.url)))).default
 const root=element('root')
 const request=async()=>({available:true,status:'partial',assessment:{},items:[{source_id:'S1',title:'News',url:'https://example.com',claim:'Claim',relation:'Insufficient Evidence',semantic_relation:'Support',quote_verification:'validation_failed',evidence_coverage:'full',validation_error:'no_match',quote:null}]})
 renderer.render(h(Control,{versionId:'v',request}),root)
 for(let i=0;i<6;i++){await Promise.resolve();await nextTick()}
 assert.match(text(root),/Semantic Relation/);assert.match(text(root),/引文未驗證/)
 assert.equal(all(root).filter(n=>n.type==='blockquote').length,0)
 assert.doesNotMatch(text(root),/的下列原文支持/)
 renderer.render(null,root)
})

test('failed source-aware retry requires confirmation and emits frozen version identity', async()=>{
 const C=(await import(componentUrl(new URL('../src/components/VersionComparison.vue',import.meta.url)))).default
 const root=element('root'),events=[],v={version_id:'failed',version_number:4,status:'failed',experiment_type:'source_aware_baseline'}
 renderer.render(h(C,{versions:[v],locale:'zh',onRetry:x=>events.push(x)}),root);await nextTick()
 const button=()=>all(root).find(n=>n.type==='button'&&text(n).includes('建立受控重試'))
 assert.equal(button().props.disabled,true)
 all(root).find(n=>n.type==='input').props['onUpdate:modelValue'](true);await nextTick();button().props.onClick();await nextTick()
 assert.deepEqual(events,[{experiment_type:'source_aware_baseline',retry_of_version_id:'failed',confirm:true}])
 renderer.render(h(C,{versions:[v,{version_id:'retry',retry_of_version_id:'failed',status:'running'}],locale:'zh'}),root);await nextTick()
 assert.equal(button(),undefined);assert.match(text(root),/已建立重試版本/)
 renderer.render(null,root)
})

test('workspace news renders arbitrary inventory, saved summaries and safe expandable sources without selection', async()=>{
 const C=(await import(componentUrl(new URL('../src/components/WorkspaceNews.vue',import.meta.url)))).default
 const root=element('root')
 const result={vid:'v',analysis_id:'a',run_id:1,sources:Array.from({length:5},(_,i)=>({source_id:'raw'+i,source_title:'Article '+i,source_url:'https://news.example/'+i,retrieval_status:'fetched',content_quality:'partial_article',article_text:'Saved body '+i}))}
 renderer.render(h(C,{result,retrieve:result,version:{source_aware_manifest:{news_cards:[{source_id:'S1',title:'AI article',url:'https://news.example/ai',summary:'Saved AI summary',review:{decision:'manual_review_required'}}]}},locale:'zh'}),root);await nextTick()
 assert.equal(all(root).filter(n=>n.type==='article').length,6)
 assert.doesNotMatch(text(root),/Saved AI summary/);assert.match(text(root),/Saved body 4/)
 assert.ok(all(root).filter(n=>n.type==='input').every(n=>n.props.disabled))
 assert.ok(all(root).filter(n=>n.type==='a').every(n=>n.props.rel==='noopener noreferrer'))
 renderer.render(h(C,{result:{vid:'other',analysis_id:'new'},retrieve:result,version:{},locale:'zh'}),root);await nextTick()
 assert.doesNotMatch(text(root),/Saved body|Saved AI summary/)
 renderer.render(null,root)
})

test('workspace history exposes actual status, absent verdicts and version selection', async()=>{
 const C=(await import(componentUrl(new URL('../src/components/WorkspaceVersions.vue',import.meta.url)))).default
 const root=element('root'),selected=[]
 renderer.render(h(C,{versions:[{version_id:'s',version_number:1,status:'succeeded',output_snapshot:{student:{pred_label:0}}},{version_id:'f',version_number:2,status:'failed',error:'Actual failure',parent_version_id:'s'}],selected:'s',onSelect:id=>selected.push(id)}),root);await nextTick()
 const buttons=all(root).filter(n=>n.type==='button')
 assert.equal(buttons[0].props['aria-pressed'],true);assert.match(text(buttons[1]),/—/)
 buttons[1].props.onClick();assert.deepEqual(selected,['f']);assert.match(text(root),/Actual failure/)
 renderer.render(null,root)
})

test('advanced research keeps one instance of each control and is collapsed by default',()=>{
 const app=readFileSync(new URL('../src/App.vue',import.meta.url),'utf8')
 const advanced=app.slice(app.indexOf('<details class="workspace-advanced">'),app.indexOf('<script setup>'))
 for(const name of ['GroundedExplanation','EvidenceAssessmentControl','EvidenceAblation','SourceGroundedBaseline','SourceAwareBaseline','VersionComparison','EvidencePanel']){
  assert.equal(app.split('<'+name+' ').length-1,1,name);assert.ok(advanced.includes('<'+name+' '),name)
 }
 assert.equal(app.split('<InputCorrection ').length-1,1)
 assert.doesNotMatch(advanced,/<InputCorrection /)
 assert.match(app,/@media\(max-width:900px\)/)
 assert.match(readFileSync(new URL('../src/components/WorkspaceVersions.vue',import.meta.url),'utf8'),/overflow-x:auto/)
 assert.match(readFileSync(new URL('../src/components/WorkspaceNews.vue',import.meta.url),'utf8'),/-webkit-line-clamp:3/)
})

test('Phase 1.1 video-first layout, compact pipeline and exactly four research categories',()=>{
 const app=readFileSync(new URL('../src/App.vue',import.meta.url),'utf8')
 const workspace=app.slice(app.indexOf('<section v-else class="page-stack research-workspace">'),app.indexOf('<script setup>'))
 const markers=['class="compact-pipeline"','01 · Video & Result','<video ','class="result-grid"','Full original reasoning / translation','02 · Verification','03 · News','Advanced Research']
 const positions=markers.map(x=>workspace.indexOf(x))
 assert.ok(positions.every((p,i)=>p>=0&&(!i||p>positions[i-1])))
 assert.equal((workspace.match(/<video /g)||[]).length,1)
 assert.equal((workspace.match(/v-for="stage in workspaceStages"/g)||[]).length,1)
 assert.doesNotMatch(workspace,/01 · Pipeline|04 ·|05 ·|06 ·|07 ·|class="pipeline-strip"/)
 const ast=parse(app).descriptor.template.ast
 const nodes=[];function walk(n){if(!n||typeof n!=='object')return;nodes.push(n);for(const c of [...(n.children||[]),...(n.branches||[])])walk(c)}walk(ast)
 const advanced=nodes.find(n=>n.tag==='details'&&n.props?.some(p=>p.name==='class'&&p.value?.content==='workspace-advanced'))
 const categories=advanced.children.filter(n=>n.tag==='details')
 assert.equal(categories.length,4)
 assert.deepEqual(categories.map(n=>n.props.find(p=>p.name==='data-category').value.content),['evidence','experiments','data','pipeline'])
 assert.ok(!advanced.props.some(p=>p.name==='open'))
 assert.ok(categories.every(n=>!n.props.some(p=>p.name==='open')))
 assert.match(app,/max-height:520px;object-fit:contain;margin-inline:auto/)
 assert.match(app,/workspace-result-row \{display:grid;grid-template-columns:minmax\(0,1fr\)/)
 assert.match(app,/Selected version status/)
 assert.match(app,/const pipelineJob = computed\(\(\) => versions.value.find/)
})

test('inline correction keeps exact local drafts, single-field submissions and restore behavior',async()=>{
 const C=(await import(componentUrl(new URL('../src/components/InputCorrection.vue',import.meta.url)))).default
 const root=element('root'),sent=[];let instance
 const version={version_id:'v1',status:'succeeded',output_snapshot:{retrieve:{Rc:'Original Rc',Rv:'Original Rv',K_int:'Internal',K_ext:'External'},preprocess:{transcript:'Transcript'}}}
 const before=JSON.stringify(version)
 const render=(v=version,busy=false)=>{renderer.render(h(C,{version:v,busy,locale:'zh',onSubmit:x=>sent.push(x)}),root);instance=root._vnode.component.exposed}
 const area=k=>all(root).find(n=>n.type==='textarea'&&n.props['aria-label']===k)
 const button=label=>all(root).find(n=>n.type==='button'&&text(n).includes(label))
 const confirm=()=>assert.equal(all(root).filter(n=>n.type==='input').length,0) // direct submit; no extra consent control
 const settle=async()=>{await nextTick();await nextTick()}
 render();await settle();assert.equal(area('Rc').value,'Original Rc');assert.equal(area('Rv').value,'Original Rv')
 assert.equal(all(root).filter(n=>n.type==='textarea'&&['K_int','K_ext'].includes(n.props['aria-label'])).length,0)
 const exact='  改寫 😀\n第二行  '
 area('Rc').props['onUpdate:modelValue'](exact);await settle();assert.equal(sent.length,0);assert.equal(JSON.stringify(version),before)
 render(structuredClone(version));await settle();assert.equal(area('Rc').value,exact)
 confirm();await settle();button('建立新版本').props.onClick();button('建立新版本').props.onClick();await settle()
 assert.deepEqual(sent,[{parent_version_id:'v1',field:'Rc',value:exact}])
 instance.finishSubmission();instance.submitted(sent[0]);await settle()
 area('Rv').props['onUpdate:modelValue']('New Rv');await settle();confirm();await settle();button('建立新版本').props.onClick();await settle()
 assert.equal(sent[1].field,'Rv');assert.equal(area('Rc').value,'Original Rc')
 instance.finishSubmission();await settle();button('還原所有草稿').props.onClick();await settle();assert.equal(button('建立新版本').props.disabled,true)
 area('Rc').props['onUpdate:modelValue']('Two Rc');area('Rv').props['onUpdate:modelValue']('Two Rv');await settle()
 assert.equal(button('建立新版本').props.disabled,true);assert.match(text(root),/每次只接受一個欄位/)
 button('還原所有草稿').props.onClick();await settle()
 area('Rc').props['onUpdate:modelValue'](' Original Rc ');await settle();confirm();await settle();assert.equal(button('建立新版本').props.disabled,true)
 render({...version,version_id:'failed',status:'failed'});await settle();assert.equal(area('Rc').props.disabled,true)
 renderer.render(null,root)
})

test('knowledge cards can be restricted to read-only K_int and K_ext without duplicate Rc/Rv',async()=>{
 const root=element('root')
 renderer.render(h(DataComponent,{data:{Rc:'Do not duplicate Rc',Rv:'Do not duplicate Rv',K_int:'Internal saved',K_ext:'External saved'},fieldKeys:['K_int','K_ext'],locale:'zh'}),root);await nextTick()
 assert.match(text(root),/Internal saved/);assert.match(text(root),/External saved/)
 assert.doesNotMatch(text(root),/Do not duplicate/);assert.equal(all(root).filter(n=>n.type==='textarea').length,0)
 renderer.render(null,root)
})

// Phase 2B: read-only summary inventory and bounded asynchronous status reads.
test('automatic news joins stable identities, retains aliases and rejects ambiguous title/ID matches', async()=>{
 const {unifiedNews}=await import('../src/workspaceNews.js')
 const raw=[{source_id:'a',article_id:'article',article_text_hash:'hash',source_url:'https://news.example/a'},
  {source_id:'alias',article_id:'article',article_text_hash:'hash',source_url:'https://mirror.example/a'},
  {source_id:'b',source_title:'Same title',source_url:'https://news.example/b'}]
 const before=JSON.stringify(raw)
 const cards=unifiedNews(raw,[{source_id:'S1',url:'https://news.example/a',summary:'Saved research'}],{records:[
  {record_id:'r1',source_id:'a',article_id:'article',article_text_hash:'hash',status:'completed',summary:'Automatic summary'},
  {record_id:'r2',source_id:'alias',duplicate_of:'r1',status:'skipped'},
  {record_id:'r3',source_id:'b',title:'Same title',url:'https://different.example/b',status:'failed'},
 ]})
 assert.equal(cards.length,3)
 assert.equal(cards[0].auto.summary,'Automatic summary')
 assert.equal(cards[0].sources.length,2)
 assert.equal(cards[0].saved.summary,'Saved research')
 assert.equal(JSON.stringify(raw),before)
 assert.equal(unifiedNews(raw,[],{records:[{source_id:'a',article_id:'article',article_text_hash:'changed',status:'completed',summary:'Changed'}]}).length,3)
})

test('mounted automatic summaries unify more than three cards with partial, body, provenance and historical fallback',async()=>{
 const C=(await import(componentUrl(new URL('../src/components/WorkspaceNews.vue',import.meta.url)))).default
 const root=element('root'),calls=[]
 const sources=Array.from({length:5},(_,i)=>({source_id:'s'+i,source_url:'https://news.example/'+i,source_title:'Article '+i,retrieval_status:i===4?'too_large':'fetched',content_quality:'partial_article',...(i===4?{}:{article_text:'Original '+i})}))
 const result={vid:'video',analysis_id:'v',sources}
 const job={experiment_id:'exp',version_id:'v',status:'partial',records:sources.map((s,i)=>({source_id:s.source_id,url:s.source_url,record_id:'r'+i,status:i===4?'skipped':i===3?'failed':'completed',summary:i<3?'自動摘要 '+i:null,reason:i===4?'Article exceeds input limit; not truncated':null,error:i===3?'TimeoutError':null,quote_validation:i<3?{status:'exact_match',source_excerpt:'Original '+i}:null}))}
 let response=job
 const request=async(path,options)=>{calls.push({path,options});return response}
 const render=(id='v')=>renderer.render(h(C,{experimentId:'exp',version:{version_id:id},result,retrieve:result,request,summaryEnabled:true,locale:'zh'}),root)
 const settle=async()=>{for(let i=0;i<8;i++){await Promise.resolve();await nextTick()}}
 render();await settle()
 assert.equal(calls[0].path,'/versions/v/automatic-summaries');assert.equal(calls[0].options.method,'GET')
 assert.equal(all(root).filter(n=>n.type==='article').length,5)
 assert.match(text(root),/自動摘要 0/);assert.match(text(root),/摘要部分完成/);assert.doesNotMatch(text(root),/摘要產生失敗/)
 const failed=all(root).filter(n=>n.type==='article').at(-1);assert.equal(text(failed).trim(),sources[4].source_url);assert.equal(all(failed).filter(n=>n.type==='a').length,1);assert.equal(all(failed).filter(n=>n.type==='details').length,0)
 assert.equal(all(root).filter(n=>n.type==='a').length,5)
 assert.ok(all(root).filter(n=>n.type==='input').every(n=>n.props.disabled))
 render();await settle();assert.equal(calls.length,1)
 response={status:'unavailable',records:[],reason:'No automatic summary job for this version'}
 render('historical');await settle()
 assert.doesNotMatch(text(root),/尚無自動摘要|自動摘要 0/);assert.match(text(root),/新聞原文摘錄/)
 assert.equal(all(root).filter(n=>n.type==='article').length,5)
 renderer.render(null,root)
})

test('summary reader isolates in-flight versions and experiments, cancels on unmount and never posts',async()=>{
 const {summaryReader}=await import('../src/workspaceNews.js')
 const timers=new Map(),calls=[],states=[];let n=0
 const reader=summaryReader({schedule:(fn,ms)=>{timers.set(++n,{fn,ms});return n},cancel:id=>timers.delete(id),onChange:s=>states.push(s),request:(path,options)=>new Promise(resolve=>calls.push({path,options,resolve}))})
 reader.start('exp','v1');reader.start('exp','v2')
 assert.equal(calls[0].options.signal.aborted,true)
 calls[1].resolve({experiment_id:'exp',version_id:'v2',status:'completed',records:[]})
 await new Promise(resolve=>setImmediate(resolve))
 calls[0].resolve({experiment_id:'exp',version_id:'v1',status:'completed',records:[{summary:'stale'}]})
 await new Promise(resolve=>setImmediate(resolve))
 assert.equal(states.at(-1).job.version_id,'v2');assert.equal(timers.size,0)
 reader.start('other','v2')
 calls[2].resolve({experiment_id:'exp',version_id:'v2',status:'completed',records:[{summary:'wrong experiment'}]})
 await new Promise(resolve=>setImmediate(resolve));assert.equal(states.at(-1).status,'error')
 reader.start('other','v3');reader.stop();calls[3].resolve({status:'running',records:[]})
 await new Promise(resolve=>setImmediate(resolve));assert.equal(timers.size,0)
 assert.ok(calls.every(c=>c.options.method==='GET'))
})

test('summary polling only runs for active jobs, is bounded, and stops on every terminal/error state',async()=>{
 const {summaryReader}=await import('../src/workspaceNews.js')
 for(const terminal of ['completed','partial','failed','ineligible','unavailable','error','running']) {
  const timers=new Map(),states=[];let n=0,calls=0
  const reader=summaryReader({maxRequests:3,schedule:(fn,ms)=>{timers.set(++n,{fn,ms});return n},cancel:id=>timers.delete(id),onChange:s=>states.push(s),request:async()=>{calls++;if(calls===3 && terminal==='error')throw new Error('offline');return {status:calls===1?'pending':calls===2?'running':terminal,records:[]}}})
  reader.start('exp','v')
  for(let i=0;i<3;i++) {
   await new Promise(resolve=>setImmediate(resolve))
   const timer=[...timers].find(([,t])=>t.ms===5000)
   if(timer){timers.delete(timer[0]);timer[1].fn()}
  }
  await new Promise(resolve=>setImmediate(resolve))
  assert.equal(calls,3);assert.equal(timers.size,0);assert.equal(states.at(-1).status,terminal)
  if(terminal==='running')assert.equal(states.at(-1).paused,true)
  reader.stop()
 }
})

test('news selection requires attributed completed body summaries and creates deterministic draft only',async()=>{
 const {newsSelection,newsPreview}=await import('../src/workspaceNews.js')
 const make=id=>({source:{source_title:'Title '+id},sources:[],auto:{source_id:id,title:'Title '+id,url:'https://news.example/'+id,status:'completed',summary:'摘要\n'+id,article_text_hash:'hash'+id,source_manifest:{article_text_hash:'hash'+id,content_quality:'partial_article'}}})
 const cards=[make('s1'),make('s2')],before=JSON.stringify(cards)
 const keys=cards.map(c=>newsSelection(c).key)
 assert.equal(newsPreview(cards,[keys[1],keys[0]]),'[s1] Title s1\nhttps://news.example/s1\n摘要\ns1\n\n[s2] Title s2\nhttps://news.example/s2\n摘要\ns2')
 assert.equal(newsPreview(cards,[]),'')
 for(const status of ['pending','failed','skipped'])assert.ok(newsSelection({...cards[0],auto:{...cards[0].auto,status}}).reason)
 for(const extra of [{summary:'  '},{source_id:null},{url:'javascript:bad'},{source_manifest:null},{article_text_hash:'wrong'}])assert.ok(newsSelection({...cards[0],auto:{...cards[0].auto,...extra}}).reason)
 assert.equal(JSON.stringify(cards),before)
})

test('mounted local selection selects all, clears, preserves same-version updates, drops ineligible and resets versions',async()=>{
 const C=(await import(componentUrl(new URL('../src/components/WorkspaceNews.vue',import.meta.url)))).default
 const root=element('root')
 const sources=[0,1].map(i=>({source_id:'s'+i,source_title:'Article '+i,source_url:'https://news.example/'+i,article_text:'body',article_text_hash:'hash'+i,retrieval_status:'fetched',content_quality:'partial_article'}))
 let result={vid:'video',analysis_id:'v',sources,K_ext:'Original immutable K_ext'}
 const initial=JSON.stringify(result)
 const request=async path=>({experiment_id:'exp',version_id:path.split('/')[2],status:'completed',records:sources.map((s,i)=>({...s,url:s.source_url,status:i?'failed':'completed',summary:i?null:'已保存自動摘要'}))})
 const render=(id='v')=>renderer.render(h(C,{experimentId:'exp',version:{version_id:id},result,retrieve:result,request,summaryEnabled:true}),root)
 const settle=async()=>{for(let i=0;i<10;i++){await Promise.resolve();await nextTick()}}
 const button=t=>all(root).find(n=>n.type==='button'&&text(n)===t)
 const box=()=>all(root).filter(n=>n.type==='input')
 const draft=()=>all(root).find(n=>n.props.class==='kext-preview')
 render();await settle()
 assert.equal(box()[0].props.disabled,false);assert.equal(box()[1].props.disabled,true)
 assert.match(text(draft()),/目前未選取新聞/)
 button('全選可用新聞').props.onClick();await settle();assert.match(text(draft()),/\[s0\] Article 0/)
 render();await settle();assert.match(text(draft()),/\[s0\]/)
 button('清除選取').props.onClick();await settle();assert.match(text(draft()),/目前未選取新聞/)
 box()[0].props['onUpdate:modelValue']([JSON.stringify(['s0','hash0','https://news.example/0'])]);await settle();assert.match(text(draft()),/\[s0\]/)
 result={...result,sources:sources.map(s=>({...s,retrieval_status:'too_large'}))};render();await settle()
 assert.match(text(draft()),/目前未選取新聞/)
 result={...result,sources};render();await settle();button('全選可用新聞').props.onClick();await settle()
 render('v2');await settle();assert.match(text(draft()),/目前未選取新聞/)
 assert.equal(JSON.stringify(result),initial);assert.equal(result.K_ext,'Original immutable K_ext')
 renderer.render(null,root)
})

test('selected news rerun directly sends identifiers only, prevents duplicates and preserves selection on error',async()=>{
 const C=(await import(componentUrl(new URL('../src/components/WorkspaceNews.vue',import.meta.url)))).default
 const root=element('root'),oldWindow=globalThis.window,calls=[],confirms=[]
 let accept=false,resolve,reject
 globalThis.window={confirm:message=>{confirms.push(message);return accept}}
 const source={source_id:'s',article_title:'News',source_url:'https://news.example/a',article_text:'body',article_text_hash:'h',retrieval_status:'fetched',content_quality:'partial_article'}
 const result={vid:'video',analysis_id:'v',sources:[source],K_ext:'unchanged'}
 const request=async()=>({experiment_id:'exp',version_id:'v',status:'completed',records:[{...source,url:source.source_url,status:'completed',summary:'保存摘要',cache_key:'cache'}]})
 const submit=payload=>{calls.push(payload);return new Promise((a,b)=>{resolve=a;reject=b})}
 const settle=async()=>{for(let i=0;i<10;i++){await Promise.resolve();await nextTick()}}
 const button=t=>all(root).find(n=>n.type==='button'&&text(n)===t)
 try{
  renderer.render(h(C,{experimentId:'exp',version:{version_id:'v',status:'succeeded'},result,retrieve:result,request,summaryEnabled:true,submit}),root);await settle()
  button('全選可用新聞').props.onClick();await settle()
  const first=button('使用選取新聞重新分析').props.onClick();await settle()
  await button('使用選取新聞重新分析').props.onClick();assert.equal(calls.length,1)
  assert.deepEqual(calls[0],{experiment_type:'selected_news',parent_version_id:'v',selected_sources:[{source_id:'s',article_text_hash:'h',cache_key:'cache'}],confirm:true})
  reject(new Error('Saved summary stale'));await first;await settle();assert.match(text(root),/Saved summary stale/)
  assert.match(text(all(root).find(n=>n.props.class==='kext-preview')),/\[s\] News/)
  button('清除選取').props.onClick();await settle()
  const second=button('使用選取新聞重新分析').props.onClick();await settle()
  assert.deepEqual(calls[1].selected_sources,[]);assert.equal(confirms.length,0)
  resolve({version_id:'child',status:'pending'});await second;await settle();assert.match(text(root),/已建立版本/)
  assert.equal(result.K_ext,'unchanged')
 }finally{renderer.render(null,root);globalThis.window=oldWindow}
})

test('selected-news preview uses its attributed source title, not a merged alias title',async()=>{
 const {newsSelection}=await import('../src/workspaceNews.js')
 const alias={source_id:'alias',source_title:'Wrong alias title'}
 const own={source_id:'s',source_title:'Actual attributed title'}
 const c={source:alias,sources:[alias,own],auto:{source_id:'s',status:'completed',summary:'保存摘要',url:'https://news.example/a',article_text_hash:'h',source_manifest:{article_text_hash:'h',content_quality:'full_article'}}}
 assert.equal(newsSelection(c).title,'Actual attributed title')
 c.sources=[alias];assert.equal(newsSelection(c).title,'文章標題未提供')
})

test('selected-news version comparison retains manifest, actual empty input and execution provenance',async()=>{
 const C=(await import(componentUrl(new URL('../src/components/VersionComparison.vue',import.meta.url)))).default
 const root=element('root')
 const version={version_id:'child',version_number:2,experiment_type:'selected_news',status:'failed',parent_version_id:'v1',selected_news_manifest:{units:[{source_id:'real-source',summary:'Frozen summary'}],k_ext:''},input_snapshot:{student_fields:{K_ext:''}},input_provenance:{parent_version_id:'v1'},rerun_stage_records:[{stage:'Student',status:'failed'}],error:'Actual mock failure'}
 renderer.render(h(C,{versions:[version],locale:'zh'}),root);await nextTick()
 assert.match(text(root),/real-source/);assert.match(text(root),/Frozen summary/);assert.match(text(root),/actual_K_ext/);assert.match(text(root),/Actual mock failure/)
 assert.equal(all(root).filter(n=>n.type==='summary'&&text(n).includes('Selected News')).length,1)
 renderer.render(null,root)
})


test('simplified start requires explicit binary choice, isolates failures and retries locked judgment in both languages',async()=>{
 const saved={fetch:globalThis.fetch,window:globalThis.window,document:globalThis.document}
 const root=element('root'),calls=[],storage=new Map()
 const exp={experiment_id:'simple',video_asset_id:'asset',human_judgment:null,human_locked_at:null}
 let failJudgment=true,failVersion=true
 globalThis.window={setInterval:()=>1,clearInterval(){},setTimeout:fn=>fn(),sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)}}
 globalThis.document={getElementById:()=>null}
 globalThis.fetch=async(url,options={})=>{
  calls.push({url:String(url),options})
  let data
  if(url.endsWith('/experiments'))data={experiment:{...exp},access_token:'mock'}
  else if(url.endsWith('/video'))return {ok:true,blob:async()=>new Blob(['fixture'])}
  else if(url.endsWith('/human-judgment')){
   if(failJudgment)return {ok:false,status:500,json:async()=>({error:'Judgment failed'})}
   Object.assign(exp,{human_locked_at:'locked',human_judgment:JSON.parse(options.body).vote,human_reason:''});data={...exp}
  }else if(url.endsWith('/versions')&&options.method==='POST'){
   if(failVersion)return {ok:false,status:500,json:async()=>({error:'Version failed'})}
   data={version_id:'new',version_number:1,status:'pending'}
  }else if(url.endsWith('/versions'))data={versions:[]}
  else if(url.endsWith('/experiments/simple'))data={...exp,results_revealed:false}
  else throw new Error('Unexpected request '+url)
  return {ok:true,json:async()=>data}
 }
 const settle=async()=>{for(let i=0;i<20;i++){await Promise.resolve();await nextTick()}}
 const button=label=>all(root).find(n=>n.type==='button'&&text(n).trim()===label)
 try{
  renderer.render(h(AppComponent),root);await settle()
  assert.equal(button('開始判斷').props.disabled,true)
  await button('English').props.onClick();await settle()
  assert.equal(button('Start Verification').props.disabled,true)
  const file=new Blob(['fixture'],{type:'video/mp4'});file.name='secret-name.mp4'
  await all(root).find(n=>n.type==='input'&&n.props.type==='file').props.onChange({target:{files:[file],value:'file'}});await settle()
  assert.ok(button('Real'));assert.ok(button('Fake'))
  assert.equal(all(root).filter(n=>n.type==='textarea').length,0)
  assert.doesNotMatch(text(root),/secret-name|Baseline Configuration|Vote Statistics|Submit a separate/)
  await button('Start Verification').props.onClick();assert.equal(calls.filter(c=>c.url.endsWith('/human-judgment')).length,0)
  await button('Fake').props.onClick();await settle()
  await button('Start Verification').props.onClick();await settle()
  assert.match(text(root),/Judgment failed/);assert.equal(calls.filter(c=>c.url.endsWith('/versions')&&c.options.method==='POST').length,0)
  failJudgment=false
  await button('Start Verification').props.onClick();await settle()
  assert.match(text(root),/Version failed/);assert.equal(button('Fake').props.disabled,true)
  assert.deepEqual(JSON.parse(calls.filter(c=>c.url.endsWith('/human-judgment')).at(-1).options.body),{vote:'false',reason:''})
  failVersion=false
  await button('Start Verification').props.onClick();await settle()
  assert.equal(calls.filter(c=>c.url.endsWith('/human-judgment')).length,2)
  assert.equal(calls.filter(c=>c.url.endsWith('/versions')&&c.options.method==='POST').length,2)
  assert.equal(calls.filter(c=>c.url.endsWith('/vote')).length,0)
  assert.match(text(root),/Pipeline Status/);assert.doesNotMatch(text(root),/Student 原始理由/)
 }finally{renderer.render(null,root);Object.assign(globalThis,saved)}
})

test('version cards localize actual states and retain selected identity',async()=>{
 const C=(await import(componentUrl(new URL('../src/components/WorkspaceVersions.vue',import.meta.url)))).default
 const root=element('root'),versions=[{version_id:'a',version_number:1,status:'failed'},{version_id:'b',version_number:2,status:'running'}]
 for(const locale of ['zh','en']){
  renderer.render(h(C,{versions,selected:'b',locale}),root);await nextTick()
  assert.match(text(root),locale==='zh'?/失敗/:/Failed/)
  assert.match(text(root),locale==='zh'?/執行中/:/Running/)
  assert.equal(all(root).filter(n=>n.type==='button'&&n.props['aria-pressed']===true).length,1)
 }
 renderer.render(null,root)
})


test('Phase 5B failed workspace hides empty forms, shows one concise pipeline alert, retains diagnostics and GET refresh',async()=>{
 const saved={fetch:globalThis.fetch,window:globalThis.window,document:globalThis.document}
 const root=element('root'),calls=[],storage=new Map([['weave-experiment',JSON.stringify({experiment_id:'failed-exp',access_token:'mock',selected_version_id:'failed-v'})]])
 const version={version_id:'failed-v',version_number:1,status:'failed',stage:'error',failed_stage:'retrieve',experiment_type:'baseline',error:'PRIVATE SAVED ERROR',created_at:'2026-11-01'}
 globalThis.window={setInterval:()=>1,clearInterval(){},setTimeout:fn=>fn(),sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)}}
 globalThis.document={getElementById:()=>null}
 globalThis.fetch=async(url,options={})=>{
  calls.push({url:String(url),options})
  if(url.endsWith('/video'))return {ok:true,blob:async()=>new Blob(['fixture'])}
  const data=url.endsWith('/versions')?{versions:[version]}:{experiment_id:'failed-exp',human_judgment:'false',human_locked_at:'locked',results_revealed:false,safe_display_filename:'Video.mp4'}
  return {ok:true,json:async()=>data}
 }
 const settle=async()=>{for(let i=0;i<30;i++){await Promise.resolve();await nextTick()}}
 const button=label=>all(root).find(n=>n.type==='button'&&text(n).trim()===label)
 try{
  renderer.render(h(AppComponent),root);await settle()
  assert.equal(all(root).filter(n=>n.type==='video').length,1)
  assert.equal(all(root).filter(n=>n.type==='textarea').length,0)
  assert.equal(all(root).filter(n=>n.props.class==='kext-preview').length,0)
  assert.match(text(root),/目前沒有可編輯的分析資料/);assert.match(text(root),/目前沒有可用的新聞來源/)
  assert.equal(all(root).filter(n=>n.props.role==='alert').length,1)
  assert.match(text(all(root).find(n=>n.props.role==='alert')),/Retrieve失敗/)
  assert.doesNotMatch(text(all(root).find(n=>n.props.role==='alert')),/PRIVATE SAVED ERROR/)
  assert.match(text(all(root).find(n=>n.props['data-category']==='pipeline')),/PRIVATE SAVED ERROR/)
  const experiments=all(root).find(n=>n.props['data-category']==='experiments')
  assert.doesNotMatch(text(experiments),/建立 Source-grounded|生成逐篇摘要/)
  assert.ok(all(experiments).some(n=>n.props.id==='version-comparison'))
  const before=calls.length;await button('更新分析結果').props.onClick();await settle()
  assert.ok(calls.length>before);assert.ok(calls.every(c=>!c.options.method||c.options.method==='GET'))
  await button('English').props.onClick();await settle()
  assert.match(text(root),/No editable analysis data is available/);assert.match(text(root),/No news sources are available/)
  assert.match(text(all(root).find(n=>n.props.role==='alert')),/Retrieve failed/)
  await button('Restart').props.onClick();await settle()
  assert.ok(button('Start Verification'));assert.equal(storage.has('weave-experiment'),false)
  assert.equal(calls.filter(c=>c.options.method==='POST').length,0)
 }finally{renderer.render(null,root);Object.assign(globalThis,saved)}
})

test('Phase 5B no-news controls stay hidden in both locales and summary errors remain distinguishable',async()=>{
 const C=(await import(componentUrl(new URL('../src/components/WorkspaceNews.vue',import.meta.url)))).default
 const root=element('root')
 for(const locale of ['zh','en']){
  renderer.render(h(C,{locale,version:{version_id:'empty',status:'failed'},result:null,retrieve:null,submit:()=>{throw new Error('Must not run')}}),root);await nextTick()
  assert.match(text(root),locale==='zh'?/目前沒有可用的新聞來源/:/No news sources are available/)
  assert.equal(all(root).filter(n=>n.type==='button'||n.type==='input'||n.props.class==='kext-preview').length,0)
 }
 renderer.render(null,root)
})

test('Phase 5B responsive layout, accordion defaults and first-page boundary',()=>{
 const source=readFileSync(new URL('../src/App.vue',import.meta.url),'utf8')
 const template=parse(source).descriptor.template.content
 const first=template.slice(template.indexOf('<section v-if="currentPage === 1"'),template.indexOf('<section v-else'))
 assert.equal((first.match(/@click="startVerification"/g)||[]).length,1)
 assert.match(first,/@change="handleFileUpload"/)
 const workspace=template.slice(template.indexOf('<section v-else'))
 assert.ok(workspace.indexOf('class="compact-pipeline"')<workspace.indexOf('class="workspace-video"'))
 assert.ok(workspace.indexOf('class="workspace-video"')<workspace.indexOf('class="result-grid"'))
 assert.equal((workspace.match(/@click="refreshOutputs"/g)||[]).length,1)
 assert.equal((workspace.match(/@click="resetGame"/g)||[]).length,1)
 assert.match(source,/workspace-main-columns \{grid-template-columns:repeat\(2,minmax\(0,1fr\)\);align-items:start/)
 assert.match(source,/@media\(max-width:900px\)\{.research-workspace .workspace-main-columns \{grid-template-columns:minmax\(0,1fr\)/)
 assert.equal((workspace.match(/class="experiment-tool"/g)||[]).length,3)
 assert.doesNotMatch(workspace,/<details open/)
})


test('Phase 5B unavailable news retains a distinct summary API error and retry',async()=>{
 const C=(await import(componentUrl(new URL('../src/components/WorkspaceNews.vue',import.meta.url)))).default
 const root=element('root');let requests=0
 renderer.render(h(C,{locale:'en',experimentId:'e',version:{version_id:'v',status:'succeeded'},summaryEnabled:true,request:async()=>{requests++;throw new Error('Summary read denied')}}),root)
 for(let i=0;i<15;i++){await Promise.resolve();await nextTick()}
 assert.match(text(root),/No news sources are available/)
 assert.match(text(root),/Summary read denied/)
 const retry=all(root).find(n=>n.type==='button'&&text(n)==='Reload summary status');assert.ok(retry)
 await retry.props.onClick();for(let i=0;i<15;i++){await Promise.resolve();await nextTick()}
 assert.equal(requests,2)
 assert.equal(all(root).filter(n=>n.props.class==='news-rerun').length,0)
 renderer.render(null,root)
})

test('full reasoning follows locale, caches translations, and ignores stale language responses',async()=>{
 const saved={fetch:globalThis.fetch,window:globalThis.window,document:globalThis.document}
 const root=element('root'),requests=[];let release
 const version={version_id:'language-v',version_number:1,status:'succeeded',stage:'done',experiment_type:'baseline',output_snapshot:{retrieve:{Rc:'Claim',Rv:'Visual',K_int:'Internal',K_ext:'External'},student:{pred_label:1,reason:'Original complete reason. '.repeat(60)}}}
 const original=JSON.stringify(version)
 globalThis.window={setInterval:()=>1,clearInterval(){},setTimeout:fn=>fn(),sessionStorage:{getItem:()=>JSON.stringify({experiment_id:'language-e',access_token:'fixture'}),setItem(){}}}
 globalThis.document={getElementById:()=>null}
 globalThis.fetch=async(url,options={})=>{
  if(url.endsWith('/video'))return {ok:true,blob:async()=>new Blob(['fixture'])}
  if(url.endsWith('/translate')){
   const body=JSON.parse(options.body);requests.push(body)
   if(body.target_language==='en')await new Promise(resolve=>{release=resolve})
   return {ok:true,json:async()=>({success:true,translations:{...body.texts,explanation:body.target_language==='zh'?'完整繁體中文理由。'.repeat(60):'Complete English reasoning. '.repeat(60)}})}
  }
  return {ok:true,json:async()=>url.endsWith('/versions')?{versions:[version]}:url.endsWith('/experiments/language-e')?{experiment_id:'language-e',human_judgment:'true',human_locked_at:'locked',results_revealed:true,correct_answer:'假',correct_answer_vote:'false'}:{status:'unavailable',records:[]}}
 }
 const settle=async()=>{for(let i=0;i<20;i++){await Promise.resolve();await nextTick()}}
 const button=label=>all(root).find(n=>n.type==='button'&&text(n).trim()===label)
 const reasoning=()=>text(all(root).find(n=>n.props.class==='full-student-reasoning'))
 try{
  renderer.render(h(AppComponent),root);await settle()
  assert.match(reasoning(),/完整繁體中文理由/);assert.ok(reasoning().length>400)
  const english=button('English').props.onClick();await settle()
  assert.match(reasoning(),/Original complete reason/)
  await button('中文').props.onClick();await settle()
  release();await english;await settle()
  assert.match(reasoning(),/完整繁體中文理由/);assert.doesNotMatch(reasoning(),/Complete English/)
  await button('English').props.onClick();await settle()
  assert.match(reasoning(),/Complete English reasoning/)
  assert.equal(requests.filter(r=>r.target_language==='en').length,1)
  assert.equal(requests.filter(r=>r.target_language==='zh').length,1)
  assert.equal(JSON.stringify(version),original)
 }finally{renderer.render(null,root);Object.assign(globalThis,saved)}
})


test('saved V1 sources render without a summary job and never inherit child news', async()=>{
 const C=(await import(componentUrl(new URL('../src/components/WorkspaceNews.vue',import.meta.url)))).default
 const root=element('root'),result=id=>({vid:'video',analysis_id:id,run_id:id==='baseline'?1:2,reason:'unchanged'})
 const parent={...result('baseline'),sources:[{source_id:'s1',source_url:'https://news.example/original',resolved_url:'https://publisher.example/story',retrieval_status:'access_denied'}]}
 const child={...result('child'),K_ext:'selected summary',sources:[{source_id:'s2',source_url:'https://other.example/story'}]}
 const render=(id,retrieve,extra={})=>renderer.render(h(C,{version:{version_id:id,output_snapshot:{retrieve},...extra},experimentId:'experiment',result:result(id),retrieve,summaryEnabled:true,request:async()=>({status:'unavailable',records:[]})}),root)
 render('baseline',parent);await nextTick()
 const card=()=>all(root).find(n=>n.type==='article')
 assert.equal(text(card()).trim(),'https://publisher.example/story');assert.equal(all(card()).filter(n=>n.type==='details'||n.type==='input').length,0)
 render('child',child,{experiment_type:'selected_news',parent_version_id:'corrected',selected_news_manifest:{parent_version_id:'corrected',k_ext:'selected summary',units:[{source_id:'s2',title:'Child article',url:'https://other.example/story',summary:'Child-only summary'}]}});await nextTick()
 assert.match(text(card()),/Child-only summary/);assert.doesNotMatch(text(card()),/publisher.example/)
 render('baseline',{...parent,sources:[]});await nextTick()
 assert.match(text(root),/目前沒有可用的新聞來源/);assert.doesNotMatch(text(root),/Child-only summary/)
 renderer.render(null,root)
})
