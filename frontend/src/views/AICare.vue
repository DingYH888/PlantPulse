<script setup>
// AI 智能养护页（PRD 5.4 P4）
// 交互：
//   1. 纯文本提问：后端由大模型先从问题中解析植物名称，解析不到提示「请说明植物种类或名称」；
//   2. 图片 + 文本：品种以图片识别结果为准，再按文本问题检索知识库；
//   3. 仅图片：直接依据识别结果给出检索建议；
//   4. AI 回复以聊天卡片渲染（分节建议 / 来源角标 / 参考来源 / 反馈）；
//   5. 左侧历史会话按 session_id 分组，切换后可查看完整消息流并继续追问（多轮记忆）。
// 视觉：与植物记录 / 数据统计 / 个人中心一致，使用浅色绿主题（白卡片 + #3f8f47 主色）。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useMessage } from 'naive-ui'

import { uploadImage } from '@/api/upload'
import {
  clearAiSession,
  createCareAdviceStream,
  deleteAiSessionHistory,
  getAiSessionMessages,
  getAiSessions,
  sendAdviceFeedback,
} from '@/api/ai'
import AdviceCard from '@/components/ai/AdviceCard.vue'
import SessionList from '@/components/ai/SessionList.vue'

const message = useMessage()

const SESSION_KEY = 'plantpulse_ai_active_session'
// 示例问题必须自带植物名称：纯文本提问依赖问题中的植物名定位知识库
const QUICK_PROMPTS = ['绿萝叶子发黄怎么办？', '龟背竹多久浇一次水？', '发财树适合放在哪里养护？']

// ---- 会话与消息 ----
const sessions = ref([])
const sessionsLoading = ref(false)
const messages = ref([])
const messagesLoading = ref(false)
const activeSessionId = ref('')
const drawerVisible = ref(false)

// ---- 输入区 ----
const draft = ref('')
const attachedImage = ref('')
const uploading = ref(false)
const loading = ref(false)
const fileInput = ref(null)
const messagesEl = ref(null)
let controller = null
let lastRequest = null

const currentTitle = computed(() => {
  const current = sessions.value.find((item) => item.session_id === activeSessionId.value)
  return current?.title || '新对话'
})

// ---- 生命周期 ----
onMounted(async () => {
  await loadSessions()
  const saved = sessionStorage.getItem(SESSION_KEY)
  if (saved) {
    await loadSession(saved)
  }
  scrollToBottom()
})

onBeforeUnmount(() => {
  controller?.abort()
})

watch(
  () => messages.value.length,
  () => scrollToBottom()
)

// ---- 数据加载 ----
async function loadSessions() {
  sessionsLoading.value = true
  try {
    const data = await getAiSessions({ page: 1, page_size: 50 })
    sessions.value = data.items || []
  } catch (error) {
    message.error(error.message)
  } finally {
    sessionsLoading.value = false
  }
}

async function loadSession(sessionId) {
  if (!sessionId || loading.value) return
  messagesLoading.value = true
  try {
    const data = await getAiSessionMessages(sessionId)
    messages.value = (data.messages || []).map((item) =>
      item.role === 'user'
        ? {
            role: 'user',
            text: item.text,
            image_url: item.image_url,
            created_at: item.created_at,
          }
        : {
            role: 'assistant',
            advice: item.advice,
            created_at: item.created_at,
          }
    )
    activeSessionId.value = sessionId
    sessionStorage.setItem(SESSION_KEY, sessionId)
    drawerVisible.value = false
    scrollToBottom()
  } catch (error) {
    sessionStorage.removeItem(SESSION_KEY)
    activeSessionId.value = ''
    messages.value = []
    message.error(error.message)
  } finally {
    messagesLoading.value = false
  }
}

// ---- 会话操作 ----
function createSessionId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID()
  return `s-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function startNewSession() {
  if (loading.value) return
  const oldSession = activeSessionId.value
  if (oldSession) {
    // 只清进程内记忆，不删除数据库历史，旧会话仍可在左侧列表重新打开
    clearAiSession(oldSession).catch(() => {})
  }
  activeSessionId.value = ''
  sessionStorage.removeItem(SESSION_KEY)
  messages.value = []
  draft.value = ''
  attachedImage.value = ''
  drawerVisible.value = false
  message.success('已开启新对话')
}

function selectSession(sessionId) {
  if (sessionId === activeSessionId.value) {
    drawerVisible.value = false
    return
  }
  loadSession(sessionId)
}

// 删除历史会话：连同后台数据库记录与内存记忆一起清除
async function deleteSession(sessionId) {
  try {
    await deleteAiSessionHistory(sessionId)
    sessions.value = sessions.value.filter((item) => item.session_id !== sessionId)
    if (activeSessionId.value === sessionId) {
      // 删的是当前会话：清空聊天区，回到「新对话」状态
      activeSessionId.value = ''
      sessionStorage.removeItem(SESSION_KEY)
      messages.value = []
      draft.value = ''
      attachedImage.value = ''
    }
    message.success('已删除该会话')
  } catch (error) {
    message.error(error.message || '删除会话失败')
  }
}

// ---- 图片上传 ----
function pickImage() {
  if (loading.value || uploading.value) return
  fileInput.value?.click()
}

function validateImage(file) {
  const allowed = ['image/jpeg', 'image/png', 'image/webp']
  if (!allowed.includes(file.type)) {
    message.error('仅支持 jpg/png/webp 图片')
    return false
  }
  if (file.size > 5 * 1024 * 1024) {
    message.error('图片不能超过 5MB')
    return false
  }
  return true
}

async function onFileChange(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || !validateImage(file)) return
  uploading.value = true
  try {
    attachedImage.value = await uploadImage(file)
    message.success('图片已上传，可继续输入问题')
  } catch (error) {
    message.error(error.message)
  } finally {
    uploading.value = false
  }
}

function openImage(url) {
  if (url) window.open(url, '_blank')
}

// ---- 发送与重试 ----
function handleKeydown(event) {
  // 中文输入法组合期间回车只用于选词，不触发发送
  if (event.isComposing) return
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    handleSend()
  }
}

function handleSend() {
  if (loading.value || uploading.value) return
  const text = (draft.value || '').trim()
  const image = attachedImage.value
  if (!text && !image) {
    message.warning('请输入问题或上传植物图片')
    return
  }
  draft.value = ''
  attachedImage.value = ''
  sendMessage(text, image, true)
}

function sendQuick(tip) {
  if (loading.value) return
  draft.value = ''
  sendMessage(tip, '', true)
}

async function sendMessage(text, image, appendUser) {
  const sessionId = activeSessionId.value || createSessionId()
  activeSessionId.value = sessionId
  sessionStorage.setItem(SESSION_KEY, sessionId)
  lastRequest = { text, image }

  if (appendUser) {
    messages.value.push({
      role: 'user',
      text: text || '请根据图片给出养护建议',
      image_url: image || '',
      created_at: new Date().toISOString(),
    })
  }
  const pendingIndex = messages.value.length
  messages.value.push({
    role: 'assistant',
    pending: true,
    stage: '正在理解你的问题...',
    stream_text: '',
    created_at: new Date().toISOString(),
  })
  scrollToBottom()

  loading.value = true
  controller = new AbortController()
  try {
    // 流式：stage 更新进度文案、delta 追加正文，done 后整体替换为建议卡片
    // 不再提交 plant_id / species：品种由问题文本解析或图片识别决定
    const data = await createCareAdviceStream(
      {
        image_url: image || null,
        question: text || null,
        session_id: sessionId,
      },
      {
        signal: controller.signal,
        onStage: (stage) => {
          const current = messages.value[pendingIndex]
          if (!current?.pending) return
          current.stage = stage?.label || current.stage
          scrollToBottomThrottled()
        },
        onDelta: (chunk) => {
          const current = messages.value[pendingIndex]
          if (!current?.pending) return
          current.stream_text = `${current.stream_text || ''}${chunk}`
          scrollToBottomThrottled()
        },
      }
    )
    messages.value[pendingIndex] = { role: 'assistant', advice: data, created_at: new Date().toISOString() }
    await loadSessions()
    scrollToBottom()
  } catch (error) {
    const current = messages.value[pendingIndex]
    // 三种取消形态：axios（ERR_CANCELED/CanceledError）、fetch（AbortError）
    const aborted =
      error.code === 'ERR_CANCELED' || error.name === 'CanceledError' || error.name === 'AbortError'
    messages.value[pendingIndex] = {
      role: 'assistant',
      error: aborted ? '已停止生成' : error.message,
      // 保留已收到的正文：用户已经看到的内容不应因中断/报错凭空消失
      stream_text: current?.stream_text || '',
      created_at: new Date().toISOString(),
    }
  } finally {
    loading.value = false
    controller = null
    scrollToBottom()
  }
}

function handleStop() {
  controller?.abort()
}

function retryLast() {
  if (loading.value || !lastRequest) return
  const last = messages.value[messages.value.length - 1]
  if (!last || last.role !== 'assistant' || !last.error) return
  messages.value.pop()
  sendMessage(lastRequest.text, lastRequest.image, false)
}

async function handleFeedback(advice, value) {
  try {
    await sendAdviceFeedback(advice.id, value)
    advice.feedback = value
    message.success('感谢反馈')
  } catch (error) {
    message.error(error.message)
  }
}

// ---- 展示辅助 ----
function scrollToBottom() {
  nextTick(() => {
    const element = messagesEl.value
    if (element) element.scrollTop = element.scrollHeight
  })
}

// 流式增量可能每秒几十次：滚动做节流，避免每个 token 都触发一次 DOM 布局
let lastScrollAt = 0
function scrollToBottomThrottled() {
  const now = Date.now()
  if (now - lastScrollAt < 80) return
  lastScrollAt = now
  scrollToBottom()
}

// 把流式正文按【标记】切成可直接渲染的分块
// 流未结束时最后一块可能不完整，属于正常现象（下一帧会补全）
const MARKER_RE = /【\s*([^】]{1,16})\s*】/g
function parseStreamBlocks(raw) {
  const text = raw || ''
  const matches = [...text.matchAll(MARKER_RE)]
  if (!matches.length) return text.trim() ? [{ title: '', text: text.trim() }] : []
  return matches
    .map((match, index) => {
      const start = match.index + match[0].length
      const end = index + 1 < matches.length ? matches[index + 1].index : text.length
      return { title: match[1], text: text.slice(start, end).trim() }
    })
    .filter((block) => block.text)
}

function formatTime(value) {
  if (!value) return ''
  return value.replace('T', ' ').slice(11, 16)
}
</script>

<template>
  <div class="ai-page">
    <div class="page-head">
      <h2 class="page-title">AI 养护</h2>
      <p class="page-sub">
        输入植物养护问题，或在提问时附上照片；纯文字提问请说明植物名称或种类，我会检索养护知识并结合你的打卡记录作答。
      </p>
    </div>

    <div class="chat-layout">
      <!-- 桌面端会话侧栏 -->
      <aside class="chat-sidebar">
        <SessionList
          :sessions="sessions"
          :active-id="activeSessionId"
          :loading="sessionsLoading"
          @select="selectSession"
          @new="startNewSession"
          @delete="deleteSession"
        />
      </aside>

      <!-- 移动端会话抽屉 -->
      <n-drawer
        v-model:show="drawerVisible"
        placement="left"
        :width="280"
        :header-style="{ background: '#ffffff', color: '#2d3a2d', borderBottom: '1px solid #e3e8e0' }"
        :body-content-style="{ padding: 0, background: '#f7f9f5' }"
      >
        <template #header>历史对话</template>
        <SessionList
          :sessions="sessions"
          :active-id="activeSessionId"
          :loading="sessionsLoading"
          @select="selectSession"
          @new="startNewSession"
          @delete="deleteSession"
        />
      </n-drawer>

      <section class="chat-panel">
        <header class="chat-header">
          <button type="button" class="mobile-history" @click="drawerVisible = true">历史</button>
          <div class="chat-title">
            <span class="title-text">{{ currentTitle }}</span>
            <span class="title-sub">AI 植物养护助手</span>
          </div>
          <div class="chat-options">
            <n-button size="small" type="primary" secondary @click="startNewSession">新对话</n-button>
          </div>
        </header>

        <div ref="messagesEl" class="messages">
          <div v-if="messagesLoading" class="messages-loading">正在加载历史对话...</div>

          <div v-else-if="!messages.length" class="welcome">
            <div class="welcome-avatar">AI</div>
            <h2>你好，我是植物养护助手</h2>
            <p>
              直接提问时请写明植物名称，如「绿萝叶子发黄怎么办」；也可以上传植物照片，我会先识别品种，再检索知识库并结合你的打卡记录给出建议。
            </p>
            <div class="quick-prompts">
              <button v-for="tip in QUICK_PROMPTS" :key="tip" type="button" @click="sendQuick(tip)">
                {{ tip }}
              </button>
            </div>
          </div>

          <template v-for="(msg, index) in messages" :key="`${msg.role}-${index}`">
            <div v-if="msg.role === 'user'" class="message-row user-row">
              <div class="bubble user-bubble">
                <img
                  v-if="msg.image_url"
                  :src="msg.image_url"
                  class="message-image"
                  alt="植物照片"
                  @click="openImage(msg.image_url)"
                />
                <p class="message-text">{{ msg.text }}</p>
                <span class="message-time">{{ formatTime(msg.created_at) }}</span>
              </div>
              <div class="avatar user-avatar">我</div>
            </div>

            <div v-else class="message-row ai-row">
              <div class="avatar ai-avatar">AI</div>
              <div class="bubble ai-bubble">
                <div v-if="msg.pending" class="stream-block">
                  <div v-if="!msg.stream_text" class="typing">
                    {{ msg.stage || '正在识别植物并检索知识库' }}<span class="typing-dots">...</span>
                  </div>
                  <template v-else>
                    <div v-if="msg.stage" class="stream-stage">{{ msg.stage }}</div>
                    <div
                      v-for="(block, blockIndex) in parseStreamBlocks(msg.stream_text)"
                      :key="`block-${blockIndex}`"
                      class="stream-section"
                    >
                      <div v-if="block.title" class="stream-title">{{ block.title }}</div>
                      <p class="stream-text">{{ block.text }}</p>
                    </div>
                    <span class="stream-cursor"></span>
                  </template>
                </div>
                <div v-else-if="msg.error" class="error-block">
                  <div v-if="msg.stream_text" class="stream-block">
                    <div
                      v-for="(block, blockIndex) in parseStreamBlocks(msg.stream_text)"
                      :key="`partial-${blockIndex}`"
                      class="stream-section"
                    >
                      <div v-if="block.title" class="stream-title">{{ block.title }}</div>
                      <p class="stream-text">{{ block.text }}</p>
                    </div>
                  </div>
                  <p>{{ msg.error }}</p>
                  <n-button size="tiny" @click="retryLast">重新发送</n-button>
                </div>
                <AdviceCard
                  v-else-if="msg.advice"
                  :advice="msg.advice"
                  @feedback="(value) => handleFeedback(msg.advice, value)"
                />
                <span v-if="!msg.pending" class="message-time">{{ formatTime(msg.created_at) }}</span>
              </div>
            </div>
          </template>
        </div>

        <footer class="composer">
          <div v-if="attachedImage" class="attachment">
            <img :src="attachedImage" class="attachment-image" alt="待发送图片" />
            <div class="attachment-info">
              <span>图片已就绪，可继续输入问题</span>
              <button type="button" class="attachment-remove" @click="attachedImage = ''">移除</button>
            </div>
          </div>

          <div class="composer-box">
            <input
              ref="fileInput"
              type="file"
              class="file-input"
              accept="image/png,image/jpeg,image/webp"
              @change="onFileChange"
            />
            <button
              type="button"
              class="image-btn"
              title="上传植物图片"
              :disabled="loading || uploading"
              @click="pickImage"
            >
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8">
                <rect x="3" y="4" width="18" height="16" rx="2" />
                <circle cx="9" cy="10" r="1.6" />
                <path d="M4 17l5-5 4 4 3-3 4 4" stroke-linecap="round" />
              </svg>
            </button>
            <n-input
              v-model:value="draft"
              type="textarea"
              :autosize="{ minRows: 1, maxRows: 4 }"
              placeholder="输入养护问题，纯文字请说明植物名称..."
              class="chat-input"
              @keydown="handleKeydown"
            />
            <n-button v-if="loading" type="error" class="send-btn" @click="handleStop">停止</n-button>
            <n-button v-else type="primary" class="send-btn" :loading="uploading" @click="handleSend">发送</n-button>
          </div>
          <p class="composer-hint">Enter 发送，Shift + Enter 换行；支持 jpg/png/webp，单张 ≤5MB</p>
        </footer>
      </section>
    </div>
  </div>
</template>

<style scoped>
.ai-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-title {
  font-size: 22px;
  color: #2d3a2d;
}

.page-sub {
  margin-top: 4px;
  font-size: 13px;
  color: #7a8a7a;
  line-height: 1.7;
}

.chat-layout {
  display: flex;
  height: calc(100vh - 180px);
  min-height: 520px;
  overflow: hidden;
  border: 1px solid #e3e8e0;
  border-radius: 12px;
  background: #ffffff;
}

.chat-sidebar {
  width: 240px;
  flex: 0 0 240px;
  min-height: 0;
}

.chat-panel {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 20px;
  border-bottom: 1px solid #e3e8e0;
  background: #f7f9f5;
}

.mobile-history {
  display: none;
  padding: 5px 12px;
  border: 1px solid #dfe6db;
  border-radius: 6px;
  background: #ffffff;
  color: #4a5a4a;
  font-size: 12px;
  cursor: pointer;
}

.chat-title {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.title-text {
  overflow: hidden;
  color: #2d3a2d;
  font-size: 15px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.title-sub {
  color: #9aa89a;
  font-size: 11px;
}

.chat-options {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.messages {
  flex: 1;
  min-height: 0;
  padding: 20px clamp(12px, 3vw, 40px);
  overflow-y: auto;
  scroll-behavior: smooth;
  background: #ffffff;
}

.messages::-webkit-scrollbar {
  width: 6px;
}

.messages::-webkit-scrollbar-thumb {
  border-radius: 3px;
  background: #dfe6db;
}

.messages-loading {
  padding: 80px 0;
  color: #9aa89a;
  font-size: 13px;
  text-align: center;
}

.welcome {
  max-width: 620px;
  margin: 6vh auto 0;
  text-align: center;
}

.welcome-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  margin-bottom: 16px;
  border-radius: 50%;
  background: #e4f3e3;
  color: #3f8f47;
  font-weight: 700;
}

.welcome h2 {
  margin-bottom: 10px;
  color: #2d3a2d;
  font-size: 20px;
  font-weight: 600;
}

.welcome p {
  color: #7a8a7a;
  font-size: 13px;
  line-height: 1.8;
}

.quick-prompts {
  display: flex;
  justify-content: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-top: 24px;
}

.quick-prompts button {
  padding: 8px 14px;
  border: 1px solid #dfe6db;
  border-radius: 999px;
  background: #f7f9f5;
  color: #4a5a4a;
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}

.quick-prompts button:hover {
  border-color: #3f8f47;
  background: #ffffff;
  color: #3f8f47;
}

.message-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  max-width: 820px;
  margin: 0 auto 20px;
}

.user-row {
  justify-content: flex-end;
}

.ai-row {
  justify-content: flex-start;
}

.avatar {
  display: flex;
  flex: 0 0 34px;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  font-size: 12px;
  font-weight: 600;
}

.user-avatar {
  background: #3f8f47;
  color: #ffffff;
}

.ai-avatar {
  background: #e4f3e3;
  color: #3f8f47;
}

.bubble {
  position: relative;
  max-width: min(700px, 82%);
  padding: 12px 16px;
  border-radius: 14px;
  font-size: 14px;
}

.user-bubble {
  border-top-right-radius: 4px;
  background: #3f8f47;
  color: #ffffff;
}

.ai-bubble {
  flex: 1;
  min-width: 0;
  border: 1px solid #e3e8e0;
  border-top-left-radius: 4px;
  background: #f7f9f5;
}

.message-text {
  margin: 0;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.message-image {
  display: block;
  max-width: 260px;
  max-height: 200px;
  margin-bottom: 8px;
  border-radius: 8px;
  object-fit: cover;
  cursor: zoom-in;
}

.message-time {
  display: block;
  margin-top: 6px;
  color: #9aa89a;
  font-size: 11px;
  text-align: right;
}

.user-bubble .message-time {
  color: rgba(255, 255, 255, 0.78);
}

.typing {
  color: #7a8a7a;
  font-size: 13px;
}

/* ---- 流式输出：进度文案 + 分块正文 + 光标 ---- */
.stream-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.stream-stage {
  color: #9aa89a;
  font-size: 12px;
}

.stream-section {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stream-title {
  color: #3f8f47;
  font-size: 13px;
  font-weight: 600;
}

.stream-text {
  margin: 0;
  color: #3c4a3c;
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

.stream-cursor {
  display: inline-block;
  width: 6px;
  height: 14px;
  background: #3f8f47;
  animation: blink 1s infinite;
}

.typing-dots {
  display: inline-block;
  animation: blink 1.2s infinite;
}

@keyframes blink {
  0%,
  100% {
    opacity: 0.2;
  }
  50% {
    opacity: 1;
  }
}

.error-block {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  color: #d03050;
  font-size: 13px;
}

.error-block p {
  margin: 0;
}

.composer {
  padding: 12px clamp(12px, 3vw, 40px) 14px;
  border-top: 1px solid #e3e8e0;
  background: #f7f9f5;
}

.attachment {
  display: flex;
  align-items: center;
  gap: 12px;
  max-width: 820px;
  margin: 0 auto 10px;
  padding: 8px 12px;
  border: 1px solid #dfe6db;
  border-radius: 10px;
  background: #ffffff;
}

.attachment-image {
  width: 52px;
  height: 52px;
  border-radius: 6px;
  object-fit: cover;
}

.attachment-info {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: #7a8a7a;
  font-size: 12px;
}

.attachment-remove {
  border: none;
  background: transparent;
  color: #d03050;
  font-size: 12px;
  cursor: pointer;
}

.composer-box {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  max-width: 820px;
  margin: 0 auto;
  padding: 8px;
  border: 1px solid #dfe6db;
  border-radius: 14px;
  background: #ffffff;
}

.composer-box:focus-within {
  border-color: #3f8f47;
}

.file-input {
  display: none;
}

.image-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #7a8a7a;
  cursor: pointer;
}

.image-btn:hover:not(:disabled) {
  background: #eef2ec;
  color: #3f8f47;
}

.image-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.chat-input {
  flex: 1;
}

.send-btn {
  flex: 0 0 auto;
  min-width: 72px;
}

.composer-hint {
  max-width: 820px;
  margin: 8px auto 0;
  color: #9aa89a;
  font-size: 11px;
  text-align: center;
}

@media (max-width: 900px) {
  .chat-sidebar {
    display: none;
  }

  .mobile-history {
    display: inline-flex;
  }

  .chat-layout {
    height: calc(100dvh - 210px);
  }
}

@media (max-width: 640px) {
  .chat-header {
    flex-wrap: wrap;
    gap: 8px;
    padding: 10px 12px;
  }

  .chat-options {
    width: 100%;
    margin-left: 0;
    justify-content: flex-end;
  }

  .messages {
    padding: 16px 12px;
  }

  .composer {
    padding: 10px 12px 12px;
  }

  .bubble {
    max-width: 88%;
  }

  .chat-layout {
    height: calc(100dvh - 230px);
    min-height: 440px;
  }
}
</style>