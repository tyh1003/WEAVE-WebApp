<template>
  <div class="app-shell">
    <main class="app-main">
      <div class="language-toolbar">
        <button
          type="button"
          class="language-button"
          :class="{ active: locale === 'en' }"
          @click="setLocale('en')"
        >
          English
        </button>

        <button
          type="button"
          class="language-button"
          :class="{ active: locale === 'zh' }"
          @click="setLocale('zh')"
        >
          中文
        </button>
      </div>
      <section v-if="currentPage === 1" class="page-stack">
        <header class="page-header">
          <h1 class="brand-title">WEAVE</h1>
          <p class="brand-subtitle">Video Misinformation Verification</p>
        </header>

        <section class="card upload-card">
          <div class="card-heading">
            <div>
              <h2>{{ t("uploadVideo") }}</h2>
              <p>{{ uploadInProgress ? t("uploading") : videoUrl ? ui("影片已就緒", "Video ready") : translateStatus(uploadMessage) }}</p>
            </div>
            
          </div>

          <input
            ref="fileInput"
            id="video-upload"
            type="file"
            accept="video/*"
            class="visually-hidden"
            :disabled="startSubmitting"
            @change="handleFileUpload"
          />

          <label for="video-upload" class="button secondary-button">
            {{ t("chooseVideo") }}
          </label>

          
          <p v-if="uploadError" class="error-text">{{ uploadError }}</p>

          <div v-if="videoUrl" class="video-frame">
            <video :key="videoUrl" :src="videoUrl" controls @loadedmetadata="readVideoMetadata"></video>
          </div>
          <p v-if="videoUrl" class="video-info">{{ videoInfoWithoutName }}</p>

        </section>

        <section v-if="videoUrl" class="card judgment-card">
          <h2>{{ t('yourPrediction') }}</h2>
          <div class="judgment-options" role="group" :aria-label="t('yourPrediction')">
            <button v-for="option in voteOptions" :key="option.value" type="button"
              class="judgment-choice" :aria-pressed="selectedVote === option.value"
              :disabled="startSubmitting || !!experiment?.human_locked_at"
              @click="selectVote(option.value)">{{ voteText(option.value) }}</button>
          </div>
        </section>
        <div class="start-action">
          <p v-if="voteError" role="alert" class="error-text">{{ voteError }}</p>
          <button type="button" class="button primary-button start-button"
            :disabled="!selectedVote || !experimentSession || uploadInProgress || !!uploadError || startSubmitting || researchBusy"
            @click="startVerification">{{ startSubmitting ? ui('啟動中…', 'Starting…') : ui('開始判斷', 'Start Verification') }}</button>
        </div>
      </section>



      <section v-else class="page-stack research-workspace">
        <header class="page-header compact"><h1 class="brand-title">WEAVE</h1><p class="brand-subtitle">Video Misinformation Verification</p></header>
        <WorkspaceVersions :versions="versions" :selected="selectedVersion" :locale="locale" @select="id => selectVersion(id, true)" />
        <p v-if="mainActionError" role="alert" class="error-text">{{ mainActionError }}</p>
          <div class="compact-pipeline" aria-label="Pipeline Status">
            <p><strong>{{ ui("分析流程", "Pipeline Status") }}</strong> · {{ ui("目前／最新工作", "Current / latest job") }}: {{ pipelineJob ? `V${pipelineJob.version_number} · ${localizedJobStatus(pipelineJob.status)}` : translateStatus(processStatus) }}</p>
            <ol><li v-for="stage in workspaceStages" :key="stage.name" :data-state="pipelineVisualState(stage)" :aria-current="stage.active ? 'step' : undefined"><strong>{{ stage.name }}</strong><span>{{ stage.status }}</span></li></ol>
            <p v-if="pipelineFailureSummary" role="alert" class="error-text">{{ pipelineFailureSummary }}</p>
          </div>
        <section class="card workspace-result-row">
          <h2>{{ ui("01 · 影片與結果", "01 · Video & Result") }}</h2>
        <div class="workspace-video">
          <video v-if="videoUrl" :key="videoUrl" ref="workspacePlayer" :src="videoUrl" controls preload="metadata" @loadedmetadata="readVideoMetadata" />
          <p v-else>{{ ui('本頁尚無可播放的影片，請重新上傳。', 'No playable video is available; upload the video again.') }}</p>
          <p class="video-info">{{ videoInfo }}</p>
        </div>
        <div class="result-card">
          <p v-if="currentVersion">{{ ui('目前操作版本', 'Active experiment version') }} V{{ currentVersion.version_number }} · {{ currentVersion.experiment_type }} · {{ currentVersion.version_id }}<span v-if="researchBusy"> · {{ ui('新版本執行中，結果尚未切換', 'A new version is running; displayed results remain unchanged') }}</span></p>
          <div class="result-grid">

            <div class="result-item">
              <span>{{ t("humanPrediction") }}</span>
              <strong :data-verdict="selectedVote">{{ voteText(selectedVote) }}</strong>
            </div>

            <div class="result-item">
              <span>{{ t("aiPrediction") }}</span>
              <strong :data-verdict="studentReady ? aiVote : null">
                {{ studentReady ? voteText(aiVote) : ui('尚無結果', 'Not available') }}
              </strong>
            </div>

            <div class="result-item">
              <span>{{ t("groundTruth") }}</span>
              <strong :data-verdict="systemAnswer">{{ voteText(systemAnswer) }}</strong>
            </div>

            <div class="result-item winner-item">
              <span>{{ t("comparison") }}</span>
              <strong>{{ winnerText }}</strong>
            </div>

          </div>




            <div class="full-student-reasoning" v-if="studentResult?.reason">
              <h3>{{ ui('完整判斷理由／翻譯', 'Full original reasoning / translation') }}</h3>
              <p>{{ translatedContent.explanation || studentResult.reason }}</p>
              <small v-if="!translatedContent.explanation">{{ translationLoading ? ui('翻譯中，暫顯示原文。', 'Translating; showing original temporarily.') : ui('翻譯不可用，顯示保存原文。', 'Translation unavailable; showing saved original.') }}</small>
            </div>

          <p v-if="currentVersion" role="status">{{ ui("所選版本狀態", "Selected version status") }}: {{ localizedJobStatus(currentVersion.status) }} · {{ currentVersion.stage || '—' }}</p>

          <div class="button-row workspace-actions"><button type="button" class="button primary-button" @click="refreshOutputs">{{ t('refresh') }}</button><button type="button" class="button ghost-button" @click="resetGame">{{ t('restart') }}</button></div>
        </div>
        </section>
        <div class="workspace-main-columns">
          <section class="card verification-chain">
            <h2>{{ ui("02 · 分析資料與修正", "02 · Verification Chain & Edit") }}</h2>
            <p v-if="!hasChainData" class="chain-empty">{{ ui("目前沒有可編輯的分析資料。", "No editable analysis data is available.") }}</p>
            <InputCorrection v-if="hasChainData" ref="correctionEditor" :version="currentVersion" :busy="researchBusy || correctionSubmitting" :locale="locale" :translations="translatedContent" @submit="submitCorrection" />
            <ResearchData v-if="hasChainData" :key="`${activeAnalysisId}-${uploadedVideoId}`" :data="retrieveResult" :translations="translatedContent" :locale="locale" :field-keys="['K_int','K_ext']" />
          </section>
          <section class="card news-evidence">
            <h2>{{ ui("03 · 新聞來源", "03 · News Evidence") }}</h2>
            <WorkspaceNews :key="`${experimentSession?.experiment_id}-${selectedVersion || activeAnalysisId}`" :version="currentVersion" :result="studentResult" :retrieve="retrieveResult" :locale="locale" :experiment-id="experimentSession?.experiment_id" :request="researchRequest" :summary-enabled="experiment?.results_revealed === true" :submit="submitSelectedNews" :busy="researchBusy || selectedNewsSubmitting" />
          </section>
        </div>
        <details class="workspace-advanced">
          <summary>{{ ui("進階研究", "Advanced Research") }}</summary>
          <ResearchInspector :key="experimentSession?.experiment_id" :versions="versions" :selected="selectedVersion" :request="researchRequest" :locale="locale" />
        </details>
      </section>
    </main>
    <footer class="project-footer"><a href="https://github.com/tyh1003/WEAVE-WebApp" target="_blank" rel="noopener noreferrer">WEAVE · GitHub</a></footer>
  </div>
</template>

<script setup>
import WorkspaceVersions from './components/WorkspaceVersions.vue'
import WorkspaceNews from './components/WorkspaceNews.vue'
import ResearchInspector from './components/ResearchInspector.vue'
import InputCorrection from './components/InputCorrection.vue'
import ResearchData from './components/ResearchData.vue'
import EvidenceText from './components/EvidenceText.vue'

import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"



const API_BASE = (
  import.meta.env.VITE_API_BASE_URL?.trim() ||
  (import.meta.env.DEV ? "http://127.0.0.1:5000" : "/api")
).replace(/\/+$/, "")

const RUNNING_TEXT = "執行中..."

const DONE_TEXT = "已完成"

const NOT_FOUND_TEXT = "未查到"

const experimentSession = ref(null), experiment = ref(null), versions = ref([])
const selectedVersion = ref(null), pendingVersion = ref(null), versionError = ref('')
let researchGeneration = 0
const researchBusy = computed(() => versions.value.some(v => ['pending','running'].includes(v.status)))
const currentVersion = computed(() => versions.value.find(v => v.version_id === selectedVersion.value))
async function researchRequest(suffix, options = {}) {
  const session = experimentSession.value
  if (!session) throw new Error('No experiment')
  return fetchJson(`/experiments/${session.experiment_id}${suffix}`, { ...options, headers: { 'Content-Type':'application/json', Authorization:`Bearer ${session.access_token}`, ...options.headers } })
}
async function restoreExperiment() {
  try {
    const saved = window.sessionStorage?.getItem('weave-experiment')
    if (!saved) return
    experimentSession.value = JSON.parse(saved)
    const scope = experimentSession.value.experiment_id
    const exp = await researchRequest('')
    if (scope !== experimentSession.value?.experiment_id) return
    experiment.value = exp; uploadedVideoId.value = exp.safe_display_filename; videoBytes.value = exp.video_bytes
    const response = await fetch(`${API_BASE}/experiments/${scope}/video`, { headers:{Authorization:`Bearer ${experimentSession.value.access_token}`} })
    if (!response.ok) throw new Error('Video unavailable')
    const blob = await response.blob()
    if (scope !== experimentSession.value?.experiment_id) return
    videoUrl.value = URL.createObjectURL(blob)
    await refreshOutputs()
    if (versions.value.length) currentPage.value = 2
  } catch (error) { versionError.value = error.message }
}
const correctionEditor = ref(null)
const correctionSubmitting = ref(false)
let inspectCachedTranslationsOnly = false
function selectVersion(id, inspectOnly = false) {
  const v = versions.value.find(v => v.version_id === id)
  if (!v) return
  if (id !== selectedVersion.value && correctionEditor.value?.canLeave() === false) return
  inspectCachedTranslationsOnly = inspectOnly
  researchGeneration++
  selectedVersion.value = id; activeAnalysisId.value = id
  if (experimentSession.value) {
    experimentSession.value.selected_version_id = id
    window.sessionStorage?.setItem('weave-experiment', JSON.stringify(experimentSession.value))
  }
  translatedContent.value = {}; lastTranslationKey.value = ''
  retrieveResult.value = v.output_snapshot?.retrieve || (v.input_snapshot?.student_fields ? { ...v.input_snapshot.student_fields, analysis_id: id } : null)
  studentResult.value = v.output_snapshot?.student ? normalizeStudentResult(v.output_snapshot.student) : null
  statusStudentPrompt.value = null
}
async function submitCorrection(payload) {
  if (researchBusy.value || correctionSubmitting.value) return
  correctionSubmitting.value = true
  const scope = experimentSession.value?.experiment_id
  try {
    versionError.value = ''
    const v = await researchRequest('/versions', { method:'POST', body:JSON.stringify({experiment_type:'input_correction', ...payload}) })
    if (scope !== experimentSession.value?.experiment_id) return
    correctionEditor.value?.submitted(payload)
    pendingVersion.value = v.version_id
    await refreshOutputs()
  } catch (error) { if (scope === experimentSession.value?.experiment_id) versionError.value = error.message }
  finally { correctionSubmitting.value=false;correctionEditor.value?.finishSubmission() }
}
const selectedNewsSubmitting = ref(false)
async function submitSelectedNews(payload) {
  if (researchBusy.value || selectedNewsSubmitting.value) { throw new Error('A research version is already running') }
  selectedNewsSubmitting.value=true
  const scope=experimentSession.value?.experiment_id
  try {
    versionError.value=''
    const v=await researchRequest('/versions',{method:'POST',body:JSON.stringify({...payload,experiment_type:'selected_news'})})
    if(scope!==experimentSession.value?.experiment_id)return
    pendingVersion.value=v.version_id
    await refreshOutputs()
    return v
  } finally { selectedNewsSubmitting.value=false }
}
const aggregateSubmitting = ref(false)
async function submitAggregateVote() {
  if (!experiment.value?.human_locked_at || aggregateSubmitting.value || experimentSession.value?.aggregate_submitted) return
  const scope = experimentSession.value?.experiment_id
  aggregateSubmitting.value = true
  try {
    const data = await fetchJson('/vote', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ video_id:experiment.value.video_asset_id, vote:experiment.value.human_judgment }) })
    if (scope !== experimentSession.value?.experiment_id) return
    updateVoteStats(data.statistics)
    experimentSession.value.aggregate_submitted = true
    window.sessionStorage?.setItem('weave-experiment', JSON.stringify(experimentSession.value))
  } catch (error) { if (scope === experimentSession.value?.experiment_id) voteError.value = error.message }
  finally { aggregateSubmitting.value = false }
}

const locale = ref("zh")

// ============================================================
// Language
// ============================================================


function toggleLocale() {
  locale.value = locale.value === "zh" ? "en" : "zh"
}
async function setLocale(lang) {
  inspectCachedTranslationsOnly = false
  locale.value = lang

  await translateDynamicContent()
}


// ============================================================
// UI Translations
// ============================================================

const translations = {
  zh: {
    projectLine1: "秒懂真偽：以低成本證據鏈驅動的多模態",
    projectLine2: "Refine–Retrieve–Reason 短影音假訊息偵測",

    uploadVideo: "上傳影片",
    chooseVideo: "選擇影片",
    yourPrediction: "你的判斷",
    currentVideo: "目前影片",
    noVideoName: "尚未取得影片名稱",

    reason: "原因",
    imageTextMismatch: "圖文不符",
    knowledgeError: "知識有誤",
    other: "其他",

    submit: "送出判斷",
    submitting: "送出中...",

    voteStatistics: "目前投票比例",
    totalVotes: "目前共有 {n} 人投票",

    viewAI: "查看 AI 分析",
    analysisPipeline: "分析流程",

    preprocessing: "前處理",
    running: "執行中...",
    completed: "已完成",
    notFound: "未查到",

    extractAudioFrames: "抽取音訊與影格",
    speechVLM: "語音轉文字與 VLM 分析",
    dataMerge: "Data Merge",

    retrieve: "Retrieve",
    studentAnalysis: "小模型分析",
    analysisComplete: "分析完成",

    externalSources: "查到的資料",
    source: "資料",

    studentModel: "小模型",
    systemPromptTitle: "System Prompt",
    userPromptTitle: "User Prompt",

    rc: "文字內容（Rc）",
    rv: "影像內容（Rv）",
    internalKnowledge: "內部背景知識（K_int）",
    externalKnowledge: "外部背景知識（K_ext）",

    finalResult: "最後結果",
    humanPrediction: "使用者判斷",
    aiPrediction: "AI 判斷",
    groundTruth: "正確答案",
    comparison: "Human–AI Comparison",
    aiExplanation: "AI Explanation",

    refresh: "更新分析結果",
    restart: "重新開始",

    real: "真",
    fake: "假",
    notSelected: "尚未選擇",
    analyzing: "分析中",
    unableCompare: "無法比對",

    humanWins: "使用者勝利",
    aiWins: "AI 勝利",
    bothCorrect: "平手，雙方都答對",
    bothWrong: "平手，雙方都未答對",

    waitingUpload: "等待上傳影片...",
    notStarted: "尚未開始",
    uploading: "上傳中...",
    uploadedReady: "影片已上傳，準備分析...",
    uploadedAnalyzing: "影片已上傳，分析中",
    uploadFailed: "上傳失敗",

    noAnswer: "找不到對應答案",
    noVideoSelected: "尚未選擇影片",
    backendUnavailable: "無法連接後端，請確認 Flask backend 已啟動",
    selectPredictionFirst: "請先選擇判斷結果",
    missingVideoId: "尚未取得影片 ID",
    voteFailed: "投票送出失敗",

    processingMedia: "正在進行音訊、影格與視覺內容分析...",
    transcribingAudio: "正在進行語音轉文字...",
    retrievingEvidence: "正在進行知識檢索與外部證據搜尋...",
    studentModelAnalysis: "正在進行 Student Model 分析...",

  },

  en: {
    projectLine1: "Understand Authenticity at a Glance: Multimodal",
    projectLine2: "Refine–Retrieve–Reason Short-Video Misinformation Detection",

    uploadVideo: "Upload Video",
    chooseVideo: "Choose Video",
    yourPrediction: "Human Prediction",
    currentVideo: "Current Video",
    noVideoName: "Video name unavailable",

    reason: "Reason",
    imageTextMismatch: "Visual–Text Mismatch",
    knowledgeError: "Incorrect Knowledge",
    other: "Other",

    submit: "Submit Prediction",
    submitting: "Submitting...",

    voteStatistics: "Vote Statistics",
    totalVotes: "{n} votes in total",

    viewAI: "View AI Analysis",
    analysisPipeline: "Analysis Pipeline",

    preprocessing: "Preprocessing",
    running: "Running...",
    completed: "Completed",
    notFound: "Not Found",
    uploadedReady: "Video Uploaded — Ready for Analysis",

    extractAudioFrames: "Extract Audio & Frames",
    speechVLM: "Speech-to-Text & VLM Analysis",
    dataMerge: "Data Merge",

    retrieve: "Retrieve",
    studentAnalysis: "Student Model Analysis",
    analysisComplete: "Analysis Complete",

    externalSources: "External Sources",
    source: "Source",

    studentModel: "Student Model",
    systemPromptTitle: "System Prompt",
    userPromptTitle: "User Prompt",

    rc: "Textual Content (Rc)",
    rv: "Visual Content (Rv)",
    internalKnowledge: "Internal Background Knowledge (K_int)",
    externalKnowledge: "External Background Knowledge (K_ext)",

    finalResult: "Final Result",
    humanPrediction: "Human Prediction",
    aiPrediction: "AI Prediction",
    groundTruth: "Ground Truth",
    comparison: "Human–AI Comparison",
    aiExplanation: "AI Explanation",

    refresh: "Refresh Analysis Results",
    restart: "Restart",

    real: "Real",
    fake: "Fake",
    notSelected: "Not Selected",
    analyzing: "Analyzing",
    unableCompare: "Unable to Compare",

    humanWins: "Human Wins",
    aiWins: "AI Wins",
    bothCorrect: "Tie — Both Correct",
    bothWrong: "Tie — Both Incorrect",

    waitingUpload: "Waiting for Video Upload...",
    notStarted: "Not Started",
    uploading: "Uploading...",
    uploadedAnalyzing: "Video Uploaded — Analysis in Progress",
    uploadFailed: "Upload Failed",

    noAnswer: "No Corresponding Answer Found",
    noVideoSelected: "No Video Selected",
    backendUnavailable:
      "Unable to connect to the backend. Please make sure the Flask backend is running.",
    selectPredictionFirst: "Please select a prediction first.",
    missingVideoId: "Video ID is unavailable.",
    voteFailed: "Failed to submit prediction.",

    processingMedia: "Analyzing audio, frames, and visual content...",
    transcribingAudio: "Transcribing audio...",
    retrievingEvidence:
      "Retrieving evidence and searching external knowledge...",
    studentModelAnalysis: "Running Student Model analysis...",
  },
}


// ============================================================
// Translation helper
// ============================================================

function t(key, params = {}) {
  let text = translations[locale.value]?.[key] ?? key

  Object.entries(params).forEach(([name, value]) => {
    text = text.replaceAll(`{${name}}`, String(value))
  })

  return text
}


// ============================================================
// System Prompt — display only
// 不影響 Backend 實際送給 Student Model 的 Prompt
// ============================================================

function voteText(vote) {
  if (vote === "true") return t("real")
  if (vote === "false") return t("fake")

  return t("notSelected")
}

function reasonText(reason) {
  const map = {
    "圖文不符": "imageTextMismatch",
    "知識有誤": "knowledgeError",
    "其他": "other",
  }

  return map[reason] ? t(map[reason]) : reason
}

function pipelineStepLabel(step) {
  const map = {
    "抽取音訊與影格": "extractAudioFrames",
    "語音轉文字與 VLM 分析": "speechVLM",
    "Data Merge": "dataMerge",
    "Retrieve": "retrieve",
    "小模型分析": "studentAnalysis",
    "分析完成": "analysisComplete",
  }

  return map[step] ? t(map[step]) : step
}

function translateStatus(text) {
  const map = {
    "等待上傳影片...": "waitingUpload",
    "尚未開始": "notStarted",
    "執行中...": "running",
    "已完成": "completed",
    "未查到": "notFound",
    "上傳中...": "uploading",
    "影片已上傳，分析中": "uploadedAnalyzing",
    "上傳失敗": "uploadFailed",
    "找不到對應答案": "noAnswer",
    "尚未選擇影片": "noVideoSelected",
    "正在進行音訊、影格與視覺內容分析...": "processingMedia",
    "正在進行語音轉文字...": "transcribingAudio",
    "正在進行知識檢索與外部證據搜尋...": "retrievingEvidence",
    "正在進行 Student Model 分析...": "studentModelAnalysis",
    "分析完成": "analysisComplete",
  }

  return map[text] ? t(map[text]) : text
}

const voteOptions = [

  { value: "true", label: "真", shortLabel: "TRUE" },

  { value: "false", label: "假", shortLabel: "FALSE" },

]



const reasonOptions = ["圖文不符", "知識有誤", "其他"]

const pipelineSteps = [
  "抽取音訊與影格",
  "語音轉文字與 VLM 分析",
  "Data Merge",
  "Retrieve",
  "小模型分析",
  "分析完成",
]



const preprocessDisplaySteps = computed(() => pipelineSteps.slice(0, 3))



const ui = (zh, en) => locale.value === 'en' ? en : zh
const workspacePlayer = ref(null)
const videoBytes = ref(null)
const videoDuration = ref(null)
const pipelineError = ref(null)
const failedPipelineStage = ref(null)
const videoInfo = computed(() => [uploadedVideoId.value,
  videoBytes.value !== null ? `${(videoBytes.value / 1024 / 1024).toFixed(2)} MB` : null,
  videoDuration.value !== null ? `${videoDuration.value.toFixed(1)} s` : null].filter(Boolean).join(' · '))
function readVideoMetadata(event) {
  const value = event.target.duration
  videoDuration.value = Number.isFinite(value) && value >= 0 ? value : null
}
function seekWorkspace(time) {
  const player = workspacePlayer.value
  if (typeof time === 'number' && Number.isFinite(time) && time >= 0 && player && Number.isFinite(player.duration) && time <= player.duration) player.currentTime = time
}
const pipelineJob = computed(() => versions.value.find(v => ['pending','running'].includes(v.status)) || versions.value.at(-1))
const workspaceStages = computed(() => {
  const job = pipelineJob.value
  const stage = job ? (job.status === 'failed' ? 'error' : job.stage) : currentStage.value
  const hasRetrieve = job ? !!job.output_snapshot?.retrieve : retrieveReady.value
  const hasStudent = job ? !!job.output_snapshot?.student : studentReady.value
  const failedStage = job ? job.failed_stage : failedPipelineStage.value
  const waiting = ui('等待／未知', 'Waiting / unknown')
  const done = ui('完成', 'Completed')
  const running = ui('執行中', 'Running')
  if (stage === 'error' && failedStage) {
    const names = ['Preprocess', 'Retrieve', 'Student', 'Result']
    const index = { preprocess:0, preprocess_reused:0, retrieve:1, student:2 }[failedStage]
    if (index === undefined) return names.map((name,i)=>({name,status:i===3?ui('失敗','Failed'):waiting}))
    return names.map((name, i) => ({ name, status: i === 3 || i === index ? ui('失敗', 'Failed') : i < index ? done : ui('未執行', 'Not Run') }))
  }
  return [
    { name: 'Preprocess', active: stage === 'preprocess', status: stage === 'preprocess' ? running : ['retrieve', 'student', 'done'].includes(stage) ? done : waiting },
    { name: 'Retrieve', active: stage === 'retrieve', status: stage === 'retrieve' ? running : ['student', 'done'].includes(stage) && hasRetrieve ? done : waiting },
    { name: 'Student', active: stage === 'student', status: stage === 'student' ? running : stage === 'done' && hasStudent ? done : waiting },
    { name: 'Result', status: stage === 'done' && hasStudent ? done : stage === 'error' ? ui('失敗', 'Failed') : waiting },
  ]
})

const mainActionError = computed(() => versions.value.some(v => v.error && v.error === versionError.value) ? '' : versionError.value)
const hasChainData = computed(() => ['Rc','Rv','K_int','K_ext'].some(key => typeof retrieveResult.value?.[key] === 'string' && retrieveResult.value[key].trim()))
const pipelineFailureSummary = computed(() => {
  const job = pipelineJob.value
  if (job?.status !== 'failed' && !pipelineError.value) return ''
  const stage = ({preprocess:'Preprocess',preprocess_reused:'Preprocess',retrieve:'Retrieve',student:'Student'})[job?.failed_stage || failedPipelineStage.value] || ui('分析','Analysis')
  const suffix = job?.output_snapshot?.student ? '' : ui('，尚未產生此版本的 AI 判斷。', '. No AI result is available for this version.')
  return `${job ? `V${job.version_number} · ` : ''}${stage}${ui('失敗',' failed')}${suffix}`
})
function localizedJobStatus(status) {
  return ({pending:ui('等待','Waiting'),running:ui('執行中','Running'),succeeded:ui('完成','Completed'),failed:ui('失敗','Failed')})[status] || status || ui('未知','Unknown')
}
function pipelineVisualState(stage) {
  if (stage.active) return 'running'
  if (stage.status === ui('完成','Completed')) return 'completed'
  if (stage.status === ui('失敗','Failed')) return 'failed'
  return 'waiting'
}
const videoInfoWithoutName = computed(() => [
  videoBytes.value !== null ? `${(videoBytes.value / 1024 / 1024).toFixed(2)} MB` : null,
  videoDuration.value !== null ? `${videoDuration.value.toFixed(1)} s` : null].filter(Boolean).join(' · '))
const startSubmitting = ref(false)
async function startVerification() {
  if (startSubmitting.value || !selectedVote.value || !experimentSession.value || uploadInProgress.value || uploadError.value || researchBusy.value) return
  startSubmitting.value = true
  voteError.value = ''
  const scope = experimentSession.value.experiment_id
  try {
    if (!experiment.value?.human_locked_at) {
      selectedReason.value = ''
      await submitVote()
    }
    if (scope === experimentSession.value?.experiment_id && experiment.value?.human_locked_at && !voteError.value) await nextPage()
  } finally { startSubmitting.value = false }
}
const currentPage = ref(1)

const videoUrl = ref(null)

const uploadedVideoId = ref("")
const activeAnalysisId = ref(null)

const selectedVote = ref(null)

const selectedReason = ref("")

const showVoteStats = ref(false)

const voteSubmitting = ref(false)

const voteError = ref("")

const uploadMessage = ref("尚未選擇影片")

const uploadError = ref("")

const processStatus = ref("等待上傳影片...")

const pipelineStep = ref("尚未開始")

const currentStage = ref("idle")

const retrieveResult = ref(null)

const studentResult = ref(null)

const statusStudentPrompt = ref(null)

const systemAnswer = ref(null)

const correctAnswerText = ref("找不到對應答案")

const fileInput = ref(null)

const translatedContent = ref({
  Rc: "",
  Rv: "",
  K_int: "",
  K_ext: "",
  userPrompt: "",
  explanation: "",
})

const translationLoading = ref(false)
const lastTranslationKey = ref("")



const voteStats = reactive({

  total: 0,

  true_count: 0,

  false_count: 0,

  true_percent: 0,

  false_percent: 0,

})



let pollTimer = null

let uploadAbortController = null

let uploadRequestSeq = 0

const uploadInProgress = ref(false)



const statisticsRows = computed(() => [
  { key: "true", label: t("real"), percent: voteStats.true_percent },
  { key: "false", label: t("fake"), percent: voteStats.false_percent },
])



const retrieveFields = computed(() => retrieveResult.value || {})

const retrieveReady = computed(() => hasMeaningfulData(retrieveFields.value))

const retrieveLinks = computed(() => collectRetrieveLinks(retrieveFields.value))

const studentReady = computed(() => Boolean(studentResult.value))

const retrieveNoResult = computed(() => {

  if (retrieveFields.value.not_found) return true

  if (currentStage.value === "error" && pipelineStep.value === "Retrieve") return true



  return ["student", "done"].includes(currentStage.value) && !retrieveReady.value

})

const retrieveStarted = computed(

  () =>

    currentStage.value === "retrieve" ||

    ["student", "done"].includes(currentStage.value) ||

    retrieveReady.value ||

    retrieveNoResult.value

)

const studentStarted = computed(

  () =>

    currentStage.value === "student" ||

    currentStage.value === "done" ||

    studentReady.value ||

    (currentStage.value === "error" && pipelineStep.value === "小模型分析")

)



const preprocessStatusText = computed(() => {

  if (["retrieve", "student", "done"].includes(currentStage.value)) return DONE_TEXT

  if (currentStage.value === "preprocess") return RUNNING_TEXT



  return ""

})



const retrieveStatusText = computed(() => {

  if (!retrieveStarted.value) return ""

  if (currentStage.value === "retrieve") return RUNNING_TEXT

  if (retrieveNoResult.value) return NOT_FOUND_TEXT

  if (["student", "done"].includes(currentStage.value) && retrieveReady.value) return DONE_TEXT



  return ""

})



const studentStatusText = computed(() => {

  if (!studentStarted.value) return ""

  if (currentStage.value === "student") return RUNNING_TEXT

  if (currentStage.value === "done" && studentReady.value) return DONE_TEXT

  if (currentStage.value === "done" || currentStage.value === "error") return NOT_FOUND_TEXT



  return ""

})



const retrieveDisplayFields = computed(() => {

  if (!retrieveStarted.value) return blankRetrieveFields()

  if (currentStage.value === "retrieve") return fillRetrieveFields(RUNNING_TEXT)

  if (retrieveNoResult.value) return fillRetrieveFields(NOT_FOUND_TEXT)



  return retrieveFields.value

})

const translatedRetrieveDisplayFields = computed(() => {
  const original = retrieveDisplayFields.value

  // 中文介面：直接顯示原始中文
  if (locale.value !== "en") {
    return original
  }

  // 英文介面：如果 API 已翻譯完成就顯示英文
  return {
    Rc: translatedContent.value.Rc || original.Rc,
    Rv: translatedContent.value.Rv || original.Rv,
    K_int: translatedContent.value.K_int || original.K_int,
    K_ext: translatedContent.value.K_ext || original.K_ext,
  }
})

const retrieveEmptyText = computed(() => {

  if (!retrieveStarted.value) return ""

  if (currentStage.value === "retrieve") return RUNNING_TEXT

  if (retrieveNoResult.value) return NOT_FOUND_TEXT



  return ""

})

const studentResultEmptyText = computed(() => {

  if (!studentStarted.value) return ""

  if (currentStage.value === "student") return RUNNING_TEXT

  if (currentStage.value === "done" || currentStage.value === "error") return NOT_FOUND_TEXT



  return ""

})



const activeStepIndex = computed(() => {

  const exactIndex = pipelineSteps.indexOf(pipelineStep.value)

  if (exactIndex >= 0) return exactIndex

  if (currentStage.value === "retrieve") return 3

  if (currentStage.value === "student") return 4

  if (currentStage.value === "done") return 5



  return -1

})



const aiVote = computed(() =>

  normalizeVote(studentResult.value?.ai_vote ?? studentResult.value?.pred_label)

)



const winnerText = computed(() => {
  if (!studentReady.value) return t("analyzing")

  const user = selectedVote.value
  const ai = aiVote.value
  const answer = systemAnswer.value

  if (!answer) return t("unableCompare")

  const userCorrect = user === answer
  const aiCorrect = ai === answer

  if (userCorrect && !aiCorrect) return t("humanWins")
  if (aiCorrect && !userCorrect) return t("aiWins")
  if (aiCorrect && userCorrect) return t("bothCorrect")

  return t("bothWrong")
})



onMounted(async () => {

  await restoreExperiment()
  await refreshOutputs()



  pollTimer = window.setInterval(() => {

    refreshOutputs()

  }, 3000)

})



onBeforeUnmount(() => {

  if (pollTimer) {

    window.clearInterval(pollTimer)

  }



  cancelActiveUpload()

  revokeVideoUrl()

})



async function fetchJson(path, options = {}) {

  const response = await fetch(`${API_BASE}${path}`, options)

  let data = null



  try {

    data = await response.json()

  } catch {

    data = null

  }



  if (!response.ok) {

    const error = new Error(data?.error || `HTTP ${response.status}`)

    error.status = response.status

    throw error

  }



  return data

}

const translationCache = new Map()
const translationPending = new Map()
const translationFailures = new Map()
let translationSequence = 0
async function translateDynamicContent() {
  const seq = ++translationSequence
  const batch = activeAnalysisId.value, upload = uploadRequestSeq, target = locale.value
  const texts = target === 'en' ? {
    Rc: retrieveResult.value?.Rc || '', Rv: retrieveResult.value?.Rv || '',
    K_int: retrieveResult.value?.K_int || '', K_ext: retrieveResult.value?.K_ext || '',
    explanation: studentResult.value?.reason || '',
  } : {explanation: studentResult.value?.reason || ''}
  const key = JSON.stringify([target, texts])
  if (!Object.values(texts).some(v => typeof v === 'string' && v.trim())) { translatedContent.value={}; return }
  const current = () => seq === translationSequence && batch === activeAnalysisId.value && upload === uploadRequestSeq && target === locale.value
  if (lastTranslationKey.value !== key) translatedContent.value = {}
  if (translationCache.has(key)) { translatedContent.value=translationCache.get(key);lastTranslationKey.value=key;translationLoading.value=false;return }
  if (inspectCachedTranslationsOnly) { translationLoading.value=false; return }
  if (Date.now()-(translationFailures.get(key)||0)<60000) {translationLoading.value=false;return}
  translationLoading.value=true
  try {
    if (!translationPending.has(key)) {
      const request = fetch(`${API_BASE}/translate`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({texts,target_language:target})})
        .then(async response => {
          if (!response.ok) throw new Error('Translation unavailable')
          const data=await response.json()
          if (!data.success || !data.translations || Object.keys(texts).some(k=>typeof data.translations[k]!=='string' || (texts[k].trim() && !data.translations[k].trim()))) throw new Error('Translation unavailable')
          translationCache.set(key,data.translations)
          if (translationCache.size>32) translationCache.delete(translationCache.keys().next().value)
          return data.translations
        }).finally(()=>translationPending.delete(key))
      translationPending.set(key,request)
    }
    const translated=await translationPending.get(key)
    if(current()){translatedContent.value=translated;lastTranslationKey.value=key}
  } catch { translationFailures.set(key,Date.now()) /* Saved original is the only fallback. */ }
  finally { if(current())translationLoading.value=false }
}
watch([locale, activeAnalysisId, ()=>studentResult.value?.reason], ()=>translateDynamicContent())

async function refreshOutputs() {
  if (!experimentSession.value || uploadInProgress.value) return
  const scope = experimentSession.value.experiment_id
  const generation = researchGeneration
  try {
    const [exp, history] = await Promise.all([researchRequest(''), researchRequest('/versions')])
    if (experimentSession.value?.experiment_id !== scope || generation !== researchGeneration) return
    experiment.value = exp
    selectedVote.value = exp.human_judgment || selectedVote.value
    selectedReason.value = exp.human_reason || selectedReason.value
    showVoteStats.value = !!exp.human_locked_at
    applyCorrectAnswerFields(exp)
    versions.value = history.versions
    const pending = versions.value.find(v => v.version_id === pendingVersion.value)
    if (pending?.status === 'succeeded') {
      selectVersion(pending.version_id)
      pendingVersion.value = null
      window.setTimeout(() => { const target=globalThis.document?.getElementById('version-comparison'); let panel=target?.closest?.('details'); while(panel){panel.open=true;panel=panel.parentElement?.closest?.('details')}  target?.scrollIntoView?.({ behavior: 'smooth' }) }, 0)
    } else if (pending?.status === 'failed') {
      versionError.value = pending.error
      pendingVersion.value = null
      const baseline = versions.value.find(v => v.version_number === 1 && v.status === 'succeeded')
      if (baseline) selectVersion(baseline.version_id)
    }
    if (!selectedVersion.value) {
      const first = versions.value.find(v => v.version_id === experimentSession.value?.selected_version_id && v.status === 'succeeded') || versions.value.filter(v => v.status === 'succeeded').at(-1)
      if (first) selectVersion(first.version_id)
    }
    const running = versions.value.find(v => ['pending', 'running'].includes(v.status))
    if (running && !pendingVersion.value) pendingVersion.value = running.version_id
    const viewed = running || versions.value.at(-1)
    if (viewed) {
      processStatus.value = viewed.status
      currentStage.value = viewed.stage === 'student' ? 'student' : viewed.stage === 'done' ? 'done' : viewed.stage === 'retrieve' ? 'retrieve' : viewed.stage === 'error' ? 'error' : viewed.stage === 'queued' ? 'uploaded' : 'preprocess'
      pipelineStep.value = viewed.stage
      pipelineError.value = viewed.error
      failedPipelineStage.value = viewed.failed_stage || null
    }
    if (studentResult.value) await translateDynamicContent()
  } catch (error) { if (experimentSession.value?.experiment_id === scope && generation === researchGeneration) versionError.value = error.message }
}


async function fetchStatus() {

  try {

    const data = await fetchJson("/status")

    if (!statusBelongsToCurrentVideo(data) || uploadInProgress.value) {

      return data

    }



    processStatus.value = data.status || "等待上傳影片..."

    pipelineStep.value = data.pipeline_step || "尚未開始"

    currentStage.value = data.current_stage || "idle"
    pipelineError.value = data.error || null



    if (hasMeaningfulData(data.retrieve_input)) {

      retrieveResult.value = data.retrieve_input

    }



    if (hasMeaningfulData(data.student_prompt)) {

      statusStudentPrompt.value = data.student_prompt

    }



    if (data.student_result) {

      studentResult.value = normalizeStudentResult(data.student_result)

    }



    applyCorrectAnswerFields(data)

    return data

  } catch (error) {

    if (!isPendingFetchError(error)) {

      console.error("failed to load status", error)

    }



    return null

  }

}



async function fetchRetrieveResult() {

  try {

    const data = await fetchJson("/result")

    if (resultBelongsToCurrentVideo(data)) {

      retrieveResult.value = data

    }

  } catch (error) {

    if (!isPendingFetchError(error)) {

      console.error("failed to load retrieve result", error)

    }

  }

}



async function fetchStudentResult() {

  try {

    const data = await fetchJson("/student_result")

    if (resultBelongsToCurrentVideo(data)) {

      studentResult.value = normalizeStudentResult(data)

    }

  } catch (error) {

    if (!isPendingFetchError(error)) {

      console.error("failed to load student result", error)

    }

  }

}



async function fetchVoteStatistics(videoId = uploadedVideoId.value) {

  if (!videoId) {

    resetVoteStats()

    return

  }



  try {

    const params = new URLSearchParams({ video_id: videoId })

    const data = await fetchJson(`/vote/statistics?${params.toString()}`)

    if (videoId === uploadedVideoId.value) {

      updateVoteStats(data)

    }

  } catch (error) {

    if (!isPendingFetchError(error)) {

      console.error("failed to load vote statistics", error)

    }

  }

}



async function handleFileUpload(event) {
  const file = event.target.files?.[0]
  if (!file) return
  event.target.value = ''
  resetGame()
  const seq = ++uploadRequestSeq
  uploadInProgress.value = true
  uploadAbortController = new AbortController()
  videoUrl.value = URL.createObjectURL(file)
  videoBytes.value = file.size
  uploadedVideoId.value = 'Video'
  const form = new FormData(); form.append('video', file)
  try {
    const data = await fetchJson('/experiments', { method:'POST', body:form, signal:uploadAbortController.signal })
    if (seq !== uploadRequestSeq) return
    experimentSession.value = { experiment_id:data.experiment.experiment_id, access_token:data.access_token }
    window.sessionStorage?.setItem('weave-experiment', JSON.stringify(experimentSession.value))
    experiment.value = data.experiment
    uploadedVideoId.value = data.experiment.safe_display_filename
    uploadMessage.value = '影片已上傳，尚未啟動分析'
  } catch (error) { if (seq === uploadRequestSeq) uploadError.value = error.message }
  finally { if (seq === uploadRequestSeq) { uploadInProgress.value = false; uploadAbortController = null } }
}


function selectVote(vote) {
  if (experiment.value?.human_locked_at) return

  selectedVote.value = vote

  voteError.value = ""



  if (vote !== "false") {

    selectedReason.value = ""

  }

}



async function submitVote() {
  if (!selectedVote.value || !experimentSession.value || voteSubmitting.value) return
  voteSubmitting.value = true; voteError.value = ''
  const scope = experimentSession.value.experiment_id
  try {
    const saved = await researchRequest('/human-judgment', { method:'POST', body:JSON.stringify({vote:selectedVote.value, reason:selectedReason.value}) })
    if (experimentSession.value?.experiment_id !== scope) return
    experiment.value = saved
    selectedVote.value = saved.human_judgment
    selectedReason.value = saved.human_reason
    showVoteStats.value = true
  } catch (error) { if (experimentSession.value?.experiment_id === scope) voteError.value = error.message }
  finally { voteSubmitting.value = false }
}


function updateVoteStats(data) {

  if (!data) return



  Object.assign(voteStats, {

    total: data.total ?? 0,

    true_count: data.true_count ?? 0,

    false_count: data.false_count ?? 0,

    true_percent: data.true_percent ?? 0,

    false_percent: data.false_percent ?? 0,

  })

}



function resetVoteStats() {

  updateVoteStats({

    total: 0,

    true_count: 0,

    false_count: 0,

    true_percent: 0,

    false_percent: 0,

  })

}



function blankRetrieveFields() {

  return {

    Rc: "",

    Rv: "",

    K_int: "",

    K_ext: "",

  }

}



function fillRetrieveFields(value) {

  return {

    Rc: value,

    Rv: value,

    K_int: value,

    K_ext: value,

  }

}



function blankStudentPromptFields() {

  return {

    system_prompt: "",

    user_prompt: "",

    Rc: "",

    Rv: "",

    K_int: "",

    K_ext: "",

  }

}



function fillStudentPromptFields(value) {

  return {

    system_prompt: value,

    user_prompt: value,

    Rc: value,

    Rv: value,

    K_int: value,

    K_ext: value,

  }

}



function shouldFetchRetrieveResult() {

  return ["student", "done"].includes(currentStage.value) && !retrieveReady.value

}



function shouldFetchStudentResult() {

  return currentStage.value === "done" && !studentReady.value

}



function normalizeVideoId(value) {

  const filename = String(value || "")

    .split(/[\\/]/)

    .pop()

    .trim()



  return filename.replace(/\.[^.]+$/, "")

}



function statusBelongsToCurrentVideo(data) {
  if (activeAnalysisId.value && data?.analysis_id !== activeAnalysisId.value) return false

  if (!data || !uploadedVideoId.value || !data.filename) return false



  return normalizeVideoId(data.filename) === normalizeVideoId(uploadedVideoId.value)

}



function resultBelongsToCurrentVideo(data) {
  if (uploadInProgress.value) return false
  if (activeAnalysisId.value && data?.analysis_id && data.analysis_id !== activeAnalysisId.value) return false

  if (!data || !uploadedVideoId.value || !data.vid) return false



  return normalizeVideoId(data.vid) === normalizeVideoId(uploadedVideoId.value)

}



function cancelActiveUpload() {

  uploadRequestSeq += 1



  if (uploadAbortController) {

    uploadAbortController.abort()

    uploadAbortController = null

  }



  uploadInProgress.value = false

}



async function nextPage() {
  const scope = experimentSession.value?.experiment_id
  if (!experiment.value?.human_locked_at || researchBusy.value) return
  try {
    const v = await researchRequest('/versions', { method:'POST', body:JSON.stringify({experiment_type:'baseline'}) })
    if (scope !== experimentSession.value?.experiment_id) return
    pendingVersion.value = v.version_id
    currentPage.value = 2
    await refreshOutputs()
  } catch (error) { voteError.value = error.message }
}


function resetGame() {
  researchGeneration++
  experimentSession.value = null; experiment.value = null
  versions.value = []; selectedVersion.value = null; pendingVersion.value = null
  versionError.value = ''
  window.sessionStorage?.removeItem('weave-experiment')

  cancelActiveUpload()

  revokeVideoUrl()

  resetAnalysisState()

  selectedVote.value = null

  selectedReason.value = ""

  uploadedVideoId.value = ""

  uploadMessage.value = "尚未選擇影片"

  uploadError.value = ""

  currentPage.value = 1



  if (fileInput.value) {

    fileInput.value.value = ""

  }

}



function resetAnalysisState() {
  pipelineError.value = null
  failedPipelineStage.value = null
  videoBytes.value = null
  videoDuration.value = null
  activeAnalysisId.value = null
  translatedContent.value = {}
  lastTranslationKey.value = ""

  showVoteStats.value = false

  resetVoteStats()

  retrieveResult.value = null

  studentResult.value = null

  statusStudentPrompt.value = null

  processStatus.value = "等待上傳影片..."

  pipelineStep.value = "尚未開始"

  currentStage.value = "idle"

  resetCorrectAnswer()

}



function revokeVideoUrl() {

  if (videoUrl.value) {

    URL.revokeObjectURL(videoUrl.value)

    videoUrl.value = null

  }

}



function stepStateClass(index) {

  if (activeStepIndex.value > index) return "step-done"

  if (activeStepIndex.value === index) return "step-active"



  return ""

}



function voteLabel(vote) {
  return voteText(vote)
}



function normalizeVote(value) {

  if (value === true) return "true"

  if (value === false) return "false"

  if (typeof value === "number") {

    if (value === 0) return "true"

    if (value === 1) return "false"

    return null

  }



  const normalized = String(value ?? "").trim().toLowerCase()

  if (["true", "real", "genuine", "0", "真"].includes(normalized)) return "true"

  if (["false", "fake", "1", "假"].includes(normalized)) return "false"



  return null

}



function normalizeStudentResult(data) {

  if (!data) return null



  const result = { ...data }

  result.ai_vote = normalizeVote(result.ai_vote ?? result.pred_label ?? result.label)



  if (typeof result.confidence === "undefined") {

    result.confidence = result.conf

  }



  return result

}


function applyCorrectAnswerFields(data) {

  if (!data || !Object.prototype.hasOwnProperty.call(data, "correct_answer")) {

    return

  }



  systemAnswer.value = data.correct_answer_vote || null

  correctAnswerText.value = data.correct_answer || "找不到對應答案"

}



function resetCorrectAnswer() {

  systemAnswer.value = null

  correctAnswerText.value = "找不到對應答案"

}



function hasMeaningfulData(value) {

  if (!value) return false

  if (Array.isArray(value)) return value.length > 0

  if (typeof value !== "object") return Boolean(value)



  return Object.values(value).some((item) => {

    if (Array.isArray(item)) return item.length > 0

    if (typeof item === "boolean") return item

    return item !== null && typeof item !== "undefined" && item !== ""

  })

}



function collectRetrieveLinks(data) {

  if (!data || typeof data !== "object") return []



  const links = []

  const linkKeys = [

    "uri",

    "uris",

    "url",

    "urls",

    "link",

    "links",

    "source",

    "sources",

    "source_url",

    "source_urls",

  ]



  linkKeys.forEach((key) => appendLinks(data[key], links))



  return Array.from(new Set(links)).slice(0, 12)

}

function sourceLabel(link) {
  const source = studentResult.value?.evidence?.sources?.find(item => item.source_url === link)
  if (source?.source_title) return source.source_title
  try { return new URL(link).hostname } catch { return t('source') }
}



function appendLinks(value, links) {

  if (!value) return



  if (Array.isArray(value)) {

    value.forEach((item) => appendLinks(item, links))

    return

  }



  if (typeof value === "object") {

    Object.values(value).forEach((item) => appendLinks(item, links))

    return

  }



  const matches = String(value).match(/https?:\/\/[^\s"'<>]+/g) || []

  matches.forEach((match) => {

    const cleaned = match.replace(/[),.;\]]+$/, "")

    if (cleaned) links.push(cleaned)

  })

}



function isPendingFetchError(error) {

  const message = String(error?.message || error || "")

  return (

    error?.status === 404 ||

    message.includes("Failed to fetch") ||

    message.includes("NetworkError") ||

    message.includes("Load failed")

  )

}



function formatValue(value) {

  if (value === null || typeof value === "undefined" || value === "") {

    return ""

  }



  if (Array.isArray(value)) {

    return value.length ? value.map((item) => `- ${item}`).join("\n") : ""

  }



  if (typeof value === "object") {

    return JSON.stringify(value, null, 2)

  }



  return String(value)

}

</script>



<style scoped>
.full-student-reasoning p{white-space:pre-wrap;overflow-wrap:anywhere;font-size:1.08rem;line-height:1.8}.project-footer{text-align:center;padding:18px;font-size:.85rem}.project-footer a{color:#655679}.research-category{line-height:1.6}.research-category button{margin:4px;max-width:100%}

.analysis-details summary, .reason-result summary, .result-source-section summary { cursor: pointer; color: #4c3a72; font-weight: 800; overflow-wrap: anywhere; }
.analysis-details[open] summary { margin-bottom: 12px; }
summary:focus-visible { outline: 3px solid #7657d6; outline-offset: 3px; }


:global(*) {

  box-sizing: border-box;

}



.app-shell {

  min-height: 100vh;

  overflow-x: hidden;

  background:

    radial-gradient(circle at top left, rgba(255, 224, 221, 0.75), transparent 32%),

    radial-gradient(circle at bottom right, rgba(207, 238, 244, 0.9), transparent 34%),

    #fffdf8;

  color: #24232c;

}



.app-main {

  width: min(1080px, calc(100% - 28px));

  margin: 0 auto;

  padding: 40px 0 56px;

}



.page-stack,

.flow-grid,

.field-list,

.stats-list {

  display: grid;

}



.page-stack {

  gap: 24px;

}



.flow-grid {
  display: grid;
  gap: 18px;
  min-width: 0 !important;
  width: 100% !important;
  /* 加上這行，確保 Grid 的欄位不會被內容撐開 */
  grid-template-columns: minmax(0, 1fr) !important; 
}



.card, .field-list {
  min-width: 0 !important;
  width: 100% !important;
}



.stats-list {

  gap: 16px;

}



.page-header {

  display: grid;

  gap: 10px;

  text-align: center;

}



.page-header.compact {

  gap: 8px;

}



.eyebrow {

  justify-self: center;

  width: fit-content;

  padding: 7px 13px;

  border: 1px solid #b9a7ff;

  border-radius: 999px;

  background: #f3edff;

  color: #5b21b6;

  font-size: 12px;

  font-weight: 900;

  letter-spacing: 0.1em;

  text-transform: uppercase;

}



h1,

h2,

h3,

p,

pre {

  margin: 0;

}



h1 {

  font-size: clamp(32px, 5vw, 56px);

  line-height: 1.15;

  letter-spacing: 0;

}



.project-title {

  font-size: clamp(24px, 3.3vw, 40px);

  line-height: 1.25;

}



.project-title span {

  display: block;

  white-space: nowrap;

}



h2 {

  font-size: 24px;

  line-height: 1.25;

}



h3 {

  font-size: 14px;

  letter-spacing: 0.08em;

  text-transform: uppercase;

}



.page-header p,

.card-heading p,

.flow-title p {

  color: #55515e;

  line-height: 1.65;

}



.card {

  min-width: 0;

  border: 1px solid rgba(59, 55, 70, 0.16);

  border-radius: 8px;

  background: rgba(255, 255, 255, 0.9);

  box-shadow: 0 14px 30px rgba(72, 50, 112, 0.07);

}



.upload-card,

.vote-card,

.stats-card,

.result-card {

  padding: clamp(20px, 3vw, 34px);

}



.result-card {

  border-color: #b9a7ff;

  background: #dae8fc;

}



.card-heading {

  display: flex;

  align-items: flex-start;

  justify-content: space-between;

  gap: 16px;

  margin-bottom: 18px;

}



.soft-badge {

  flex: 0 0 auto;

  border: 1px solid rgba(94, 77, 142, 0.25);

  border-radius: 999px;

  padding: 6px 10px;

  background: rgba(255, 255, 255, 0.78);

  color: #4c3a72;

  font-size: 12px;

  font-weight: 900;

}



.result-badge {
  border-color: #8FB1E8;  /* 外框 */
  background: #DDEBFF;    /* 底色 */
  color: #345B91;         /* Result 文字 */
}



.visually-hidden {

  position: absolute;

  width: 1px;

  height: 1px;

  padding: 0;

  overflow: hidden;

  clip: rect(0, 0, 0, 0);

  white-space: nowrap;

  border: 0;

}



.button {

  display: inline-flex;

  min-height: 44px;

  max-width: 100%;

  align-items: center;

  justify-content: center;

  border: 1px solid transparent;

  border-radius: 8px;

  padding: 0 18px;

  font-weight: 900;

  text-align: center;

  cursor: pointer;

  transition: transform 160ms ease, opacity 160ms ease;

}



.button:hover {

  transform: translateY(-1px);

}



.button:disabled {

  cursor: not-allowed;

  opacity: 0.5;

  transform: none;

}



.primary-button {

  background: #7657d6;

  color: #ffffff;

}



.secondary-button {

  background: #287f70;

  color: #ffffff;

}



.ghost-button {

  border-color: #7657d6;

  background: #ffffff;

  color: #5b21b6;

}



.video-frame {

  width: 100%;

  max-width: 100%;

  margin-top: 20px;

  overflow: hidden;

  border: 1px solid rgba(47, 44, 69, 0.28);

  border-radius: 8px;

  background: #15151f;

}



.video-frame video {

  display: block;

  width: 100%;

  max-width: 100%;

  aspect-ratio: 16 / 9;

}



.vote-grid {

  display: grid;

  grid-template-columns: repeat(2, minmax(0, 1fr));

  gap: 14px;

}



.vote-button {

  min-width: 0;

  min-height: 112px;

  border: 1px solid rgba(47, 44, 69, 0.2);

  border-radius: 8px;

  background: rgba(255, 255, 255, 0.78);

  color: #25223b;

  cursor: pointer;

  transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;

}



.vote-button:hover {

  transform: translateY(-1px);

  border-color: #7657d6;

}



.vote-button strong,

.vote-button span {

  display: block;

}



.vote-button strong {

  font-size: 30px;

  line-height: 1.2;

}



.vote-button span {

  margin-top: 5px;

  color: #666073;

  font-size: 11px;

  font-weight: 900;

  letter-spacing: 0.08em;

}



.vote-active-true {

  border-color: #478a40;

  background: #dff5d1;

}



.vote-active-false {

  border-color: #b44a44;

  background: #ffd2cf;

}



.reason-block {

  display: grid;

  gap: 10px;

  margin-top: 20px;

}



.reason-block p {

  color: #3d3656;

  font-weight: 900;

}



.reason-list,

.button-row {

  display: flex;

  flex-wrap: wrap;

  gap: 10px;

}



.reason-button {

  min-height: 38px;

  border: 1px solid #bca8ff;

  border-radius: 999px;

  padding: 0 14px;

  background: #ffffff;

  color: #4c3a72;

  font-weight: 800;

  cursor: pointer;

}



.reason-active {

  background: #ede7ff;

  color: #5b21b6;

}



.submit-button,

.stats-card .secondary-button {

  margin-top: 20px;

}



.error-text {

  margin-top: 12px;

  color: #a51e1e;

  font-weight: 800;

  line-height: 1.5;

  overflow-wrap: anywhere;

}



.stats-row {

  display: grid;

  gap: 8px;

}



.stats-label {

  display: flex;

  align-items: center;

  justify-content: space-between;

  gap: 12px;

  color: #334155;

  font-weight: 900;

}



.meter {

  height: 12px;

  overflow: hidden;

  border-radius: 999px;

  background: #eeeaf2;

}



.meter-fill {

  display: block;

  height: 100%;

  border-radius: inherit;

}



.meter-true {

  background: #5faa58;

}



.meter-false {

  background: #e36b65;

}



.flow-card {

  padding: 20px;

}



.preprocess-card {
  border-color: #D99A9A;
  background: #E7C2C0;
}



.retrieve-card {

  border-color: #afb17e;

  background: #fef1cc;

}



.student-card {

  border-color: #72b17a;

  background: #d5e8d4;

}



.flow-title {

  display: flex;

  gap: 14px;

  align-items: flex-start;

  margin-bottom: 18px;

}



.step-index {

  display: inline-grid;

  width: 38px;

  height: 38px;

  flex: 0 0 38px;

  place-items: center;

  border-radius: 8px;

  background: #7657d6;

  color: #ffffff;

  font-weight: 900;

}



.step-list {

  display: grid;

  gap: 10px;

  padding: 0;

  margin: 0;

  list-style: none;

}



.step-list li {

  display: flex;

  align-items: center;

  gap: 10px;

  min-height: 34px;

  border-radius: 8px;

  padding: 8px 10px;

  background: rgba(255, 255, 255, 0.65);

  color: #585b66;

  font-weight: 800;

  overflow-wrap: anywhere;

}



.step-list li span {

  width: 10px;

  height: 10px;

  flex: 0 0 10px;

  border: 2px solid #aca6b8;

  border-radius: 999px;

}



.step-list .step-active {
  color: #7A3030;
  background: #F1C6C3;
}

.step-list .step-active span {
  border-color: #B94F4F;
  background: #B94F4F;
}



.step-list .step-done {
  color: #8B4545;
  background: #F8E2E0;
}

.step-list .step-done span {
  border-color: #C96B6B;
  background: #C96B6B;
}



.info-block {
  display: grid;
  gap: 8px;
  min-width: 0 !important;
  width: 100% !important;
  padding: 12px;
  border: 1px solid rgba(59, 55, 70, 0.14);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.72);
  /* 讓卡片本身隱藏多餘部分，但這主要是防禦性設定 */
  overflow: hidden !important; 
}



.info-label {

  color: #4a435b;

  font-size: 12px;

  font-weight: 900;

  letter-spacing: 0.06em;

  text-transform: uppercase;

}



/* 尋找並修改成以下設定 */

.info-value {
  display: block;
  width: 100%;
  
  /* 徹底解放高度，有多少字就撐多高 */
  max-height: none !important; 
  
  /* 完美折行黃金組合 */
  white-space: pre-wrap;       /* 保留文字原本的換行符號（\n），同時自動折行 */
  word-break: break-all;       /* 遇到卡片邊界，管你是網址、中英文、特殊符號一律強制斷行 */
  overflow-wrap: anywhere;     /* 現代瀏覽器全面適用 */

  /* 基礎視覺樣式 */
  color: #2f2d36;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
}



.link-section {

  display: grid;

  gap: 10px;

  min-width: 0;

  margin-top: 16px;

}



.source-link-grid {

  display: grid;

  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));

  gap: 10px;

  min-width: 0;

}



.source-link-card {

  display: grid;

  gap: 7px;

  min-width: 0;

  padding: 13px;

  border: 1px solid #9bbdd4;

  border-radius: 8px;

  background: rgba(255, 255, 255, 0.78);

  color: #253f5c;

  text-decoration: none;

  transition: border-color 160ms ease, background 160ms ease;

}



.source-link-card:hover {

  border-color: #4d83b5;

  background: #ffffff;

}



.source-link-card strong {

  color: #214f7a;

  font-size: 13px;

}



.source-link-card span {

  color: #32465b;

  font-size: 12px;

  line-height: 1.5;

  overflow-wrap: anywhere;

}



.retrieve-card .source-link-card {

  border-color: #9ec58f;

  background: rgba(255, 255, 255, 0.74);

  color: #315b35;

}



.retrieve-card .source-link-card:hover {

  border-color: #5c9258;

  background: #ffffff;

}



.retrieve-card .source-link-card strong {

  color: #2f6a35;

}



.retrieve-card .source-link-card span {

  color: #3f5f42;

}



.empty-text {

  color: #6b7280;

  font-weight: 800;

}



.result-grid {

  display: grid;

  grid-template-columns: repeat(4, minmax(0, 1fr));

  gap: 12px;

}



.result-item {

  display: grid;

  gap: 8px;

  min-height: 112px;

  padding: 14px;

  border: 1px solid #c4b5fd;

  border-radius: 8px;

  background: #e7deff;

}



.result-item span {

  color: #4c3a72;

  font-size: 13px;

  font-weight: 900;

}



.result-item strong {

  color: #342159;

  font-size: 22px;

  line-height: 1.3;

  overflow-wrap: anywhere;

}



.result-item small {

  color: #5f4b83;

  font-weight: 800;

  overflow-wrap: anywhere;

}



.winner-item {
  border-color: #8FB1E8;
  background: #BDD3F8;
}



.reason-result {

  display: grid;

  gap: 10px;

  margin-top: 16px;

  padding: 14px;

  border: 1px solid #c4b5fd;

  border-radius: 8px;

  background: rgba(255, 255, 255, 0.65);

}



.reason-result p {

  color: #323545;

  line-height: 1.75;

  overflow-wrap: anywhere;

}



.result-source-section {

  padding: 14px;

  border: 1px solid #c4b5fd;

  border-radius: 8px;

  background: rgba(255, 255, 255, 0.65);

}



.result-source-section .source-link-card {

  border-color: #c4b5fd;

  color: #4c3a72;

}



.result-source-section .source-link-card strong {

  color: #4c1d95;

}

.prompt-text {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}


.button-row {

  margin-top: 20px;

}

/* 1. 使用者判斷－最淡藍 */
.result-item:nth-child(1) {
  background: #EAF3FF;
}

/* 2. AI 判斷－淡藍 */
.result-item:nth-child(2) {
  background: #EAF3FF;
}

/* 3. 正確答案－稍深藍 */
.result-item:nth-child(3) {
  background: #EAF3FF;
}

/* 4. 勝負－最深藍 */
.result-item:nth-child(4) {
  background: #bbc6dc;
}

/* 5. AI REASON－非常淡的藍 */
.reason-result {
  background: #F2F7FF;
}

.language-toolbar {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-bottom: 18px;
}

.language-button {
  min-height: 36px;
  border: 1px solid #b9a7ff;
  border-radius: 999px;
  padding: 0 14px;
  background: rgba(255, 255, 255, 0.86);
  color: #4c3a72;
  font-weight: 900;
  cursor: pointer;
}

.language-button.active {
  background: #7657d6;
  color: #ffffff;
}

@media (max-width: 820px) {

  .app-main {

    width: min(100% - 20px, 1080px);

    padding: 24px 0 40px;

  }



  .card-heading {

    display: grid;

  }



  .vote-grid,

  .result-grid {

    grid-template-columns: 1fr;

  }



  .vote-button {

    min-height: 88px;

  }



  .project-title span {

    white-space: normal;

  }

}

/* Stage A research workspace */
[data-verdict="true"] { color: #246b46; }
[data-verdict="false"] { color: #a43838; }
.research-note { max-width: 90ch; }

.app-main { width: calc(100% - 64px); max-width: 1800px; padding: 24px 0 48px; }
.app-shell { background: #f5f6fa; }
.card { background: #fff; border: 1px solid #e0e3ec; box-shadow: none; border-radius: 12px; padding: 24px; }
.page-header { text-align: left; margin: 0; }
.page-header h1 { font-size: clamp(26px, 3vw, 40px); line-height: 1.25; }
.page-stack { gap: 24px; }
.card h2 { font-size: 20px; margin: 0 0 18px; }
.card h3 { font-size: 17px; }
.card p, .card pre { overflow-wrap: anywhere; }
.card p { line-height: 1.7; }
.pipeline-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; padding: 0; list-style: none; }
.pipeline-strip li { display: grid; gap: 8px; border-left: 3px solid #8b79bb; padding-left: 12px; min-width: 0; }
.pipeline-strip span, .research-note, .video-info { color: #606676; font-size: 14px; }
.research-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; }
.research-grid article { min-width: 0; }
.workspace-video video, .video-frame video { width: 100%; max-height: 520px; background: #111; border-radius: 8px; }
.workspace-video video { display: block; }
.research-records pre { white-space: pre-wrap; max-height: 500px; overflow: auto; }
.research-records details { margin: 16px 0; }
.research-records .flow-card { background: #f8f9fc; }
button:focus-visible, summary:focus-visible, a:focus-visible, input:focus-visible + label { outline: 3px solid #6951a3; outline-offset: 3px; }
@media (max-width: 820px) {
  .app-main { width: calc(100% - 24px); padding-top: 16px; }
  .card { padding: 16px; }
  .research-grid { grid-template-columns: minmax(0, 1fr); }
  .pipeline-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

/* Results-only layout: no first-page or global theme changes. */
.research-workspace .workspace-main-columns {display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:24px;align-items:start;}
.research-workspace .workspace-result-row > *, .research-workspace .workspace-main-columns > * {min-width:0;}
.research-workspace .verification-chain :deep(.research-data) {grid-template-columns:minmax(0,1fr);}
.research-workspace .workspace-advanced > summary {cursor:pointer;padding:16px 0;font-weight:600;}
.research-workspace .workspace-advanced > section {margin-top:24px;}
.research-workspace .workspace-advanced pre {white-space:pre-wrap;overflow-wrap:anywhere;}
@media(max-width:900px){.research-workspace .workspace-result-row,.research-workspace .workspace-main-columns{grid-template-columns:minmax(0,1fr);}}

/* Phase 1.1: confined to the results workspace. */
.research-workspace .workspace-result-row {display:grid;grid-template-columns:minmax(0,1fr);gap:16px;}
.research-workspace .workspace-result-row .workspace-video video {width:auto;height:auto;max-width:min(100%,960px);max-height:520px;object-fit:contain;margin-inline:auto;}
.research-workspace .workspace-result-row .result-grid {gap:12px;}
.research-workspace .workspace-result-row .result-item {padding:12px;}
.research-workspace .compact-pipeline {border-top:1px solid #dbe3ec;margin-top:16px;padding-top:8px;}
.research-workspace .compact-pipeline p {margin:6px 0;}
.research-workspace .compact-pipeline ol {display:flex;flex-wrap:wrap;gap:8px 18px;list-style:none;padding:0;margin:8px 0;}
.research-workspace .compact-pipeline li {display:flex;gap:8px;align-items:baseline;}
.research-workspace .compact-pipeline li:not(:last-child)::after {content:'→';margin-left:10px;}
.research-workspace .compact-pipeline [aria-current=step] {text-decoration:underline;font-weight:600;}
.research-workspace .research-category {border-top:1px solid #dbe3ec;padding:12px 0;min-width:0;}
.research-workspace .research-category > summary {font-weight:600;cursor:pointer;}
.research-workspace .research-category > :not(summary) {margin-top:12px;}
.research-workspace .pipeline-diagnostics .flow-grid {gap:12px;}
.research-workspace .pipeline-diagnostics .flow-card {padding:12px;border:0;}
.research-workspace .verification-chain :deep(.research-data button) {padding:3px 7px;font-size:.85em;}

/* Phase 5A: shared pastel hierarchy, without changing research controls. */
.app-shell {background:transparent;color:#211e29;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;}
.page-header .brand-title {font-size:clamp(3rem,7vw,4.8rem);letter-spacing:.06em;line-height:1.1;color:#211e29;margin:0;}
.page-header .brand-subtitle {font-size:1rem;color:#514a60;margin:0;}
.card,.workspace-advanced {background:#fff;border:1px solid #e9e4ef;border-radius:20px;box-shadow:0 5px 22px #55437608;}
.button.primary-button {background:#7050b1;color:#fff;border:1px solid #7050b1;font-weight:700;min-height:46px;}
.button.primary-button:hover:not(:disabled) {background:#5d3e9b;color:#fff;}
.button.secondary-button,.button.ghost-button {background:#f5f3f8;color:#352e43;border:1px solid #ded8e7;}
button:disabled {opacity:.55;cursor:not-allowed;}
button:focus-visible,a:focus-visible,summary:focus-visible {outline:3px solid #7955bc;outline-offset:3px;}
.start-action {text-align:center;}.start-button {min-width:min(100%,320px);padding:18px 32px;font-size:1.15rem;}
.judgment-options {display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:18px;}
.judgment-choice {background:#faf9fc;border:2px solid #e3deeb;border-radius:14px;padding:22px;font:inherit;font-size:1.25rem;font-weight:700;color:#282130;cursor:pointer;}
.judgment-choice[aria-pressed=true] {background:#eee5fa;border-color:#7050b1;}
.research-workspace .result-item {background:#fff;}
.research-workspace .result-item:nth-child(2) {background:#eee7f8;border-color:#d9c9ef;}
.research-workspace .compact-pipeline {padding:16px 0;margin-top:18px;}
.research-workspace .compact-pipeline ol {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;}
.research-workspace .compact-pipeline li {position:relative;display:flex;flex-direction:column;gap:5px;padding:12px;border-radius:12px;background:#f3f2f6;border:1px solid #e3dfea;font-size:.9rem;}
.research-workspace .compact-pipeline li:not(:last-child)::after {position:absolute;right:-12px;top:22px;margin:0;color:#6b6178;}
.research-workspace .compact-pipeline [data-state=completed] {background:#edf7f1;border-color:#c4dfd0;}
.research-workspace .compact-pipeline [data-state=failed] {background:#fff0f1;border-color:#e8bfc6;}
.research-workspace .compact-pipeline [aria-current=step] {background:#efe8fa;border-color:#8665ba;text-decoration:none;animation:stage-pulse 2s ease-in-out infinite;}
@keyframes stage-pulse {50% {box-shadow:0 0 0 3px #8665ba25;}}
@media(prefers-reduced-motion:reduce) {.research-workspace .compact-pipeline [aria-current=step] {animation:none;}}
@media(max-width:560px) {.research-workspace .compact-pipeline ol {grid-template-columns:repeat(2,minmax(0,1fr));}.research-workspace .compact-pipeline li::after {display:none;}.start-button {width:100%;}}


.research-workspace .page-header.compact {text-align:center;justify-items:center;}
.page-stack:not(.research-workspace) > .page-header {justify-self:stretch;text-align:center;justify-items:center;}
.research-workspace > .compact-pipeline {background:#fff;border:1px solid #e9e4ef;padding:20px;margin:0;border-radius:18px;}
.research-workspace .workspace-actions {justify-content:center;gap:16px;flex-wrap:wrap;margin-top:24px;}
.research-workspace .workspace-actions .button {padding:14px 24px;font-size:1.05rem;min-height:48px;}
.research-workspace .workspace-main-columns {grid-template-columns:repeat(2,minmax(0,1fr));align-items:start;}
.research-workspace .verification-chain,.research-workspace .news-evidence {background:#fff;border:1px solid #e9e4ef;border-radius:20px;padding:24px;}
.research-workspace .experiment-tool {border-top:1px solid #e9e4ef;padding:12px 0;}
.research-workspace .experiment-tool > summary {font-weight:600;cursor:pointer;}
.research-workspace pre {white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%;}
@media(max-width:900px){.research-workspace .workspace-main-columns {grid-template-columns:minmax(0,1fr);}}
</style>
