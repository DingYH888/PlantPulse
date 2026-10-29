<script setup>
// AI 建议消息卡片：聊天流中的 AI 回复内容
// 职责：只渲染建议数据 + 触发反馈事件；来源角标与降级提示保持与后端字段一致
// 视觉：与其他业务页统一为浅色绿主题（白底 / #3f8f47 主色）
import { computed } from 'vue'

const props = defineProps({
  advice: { type: Object, required: true },
})

const emit = defineEmits(['feedback'])

const confidence = computed(() => {
  const value = Number(props.advice?.confidence)
  return Number.isFinite(value) ? Math.round(value * 100) : null
})

const sections = computed(() => props.advice?.sections || [])
const warnings = computed(() => props.advice?.warnings || [])
const refs = computed(() => props.advice?.doc_refs || [])

function sourceLabel(section) {
  return section.source_type === 'general' ? '通用知识' : '知识库'
}

function feedback(value) {
  if (props.advice?.feedback) return
  emit('feedback', value)
}
</script>

<template>
  <div class="advice-card">
    <div class="advice-head">
      <span class="species">{{ advice.species || '未知品种' }}</span>
      <span v-if="confidence !== null" class="confidence">置信度 {{ confidence }}%</span>
      <span v-if="advice.is_fallback" class="badge">通用知识</span>
    </div>

    <div v-if="advice.is_fallback" class="fallback-tip">
      未匹配到该品种专属知识，以下为通用养护建议，请结合实际情况判断。
    </div>

    <p v-if="advice.summary" class="summary">{{ advice.summary }}</p>

    <div v-for="warning in warnings" :key="warning" class="warning">{{ warning }}</div>

    <div class="sections">
      <div v-for="section in sections" :key="section.key" class="section">
        <div class="section-head">
          <span class="section-title">{{ section.title }}</span>
          <span :class="['source', section.source_type]">{{ sourceLabel(section) }}</span>
        </div>
        <p class="section-content">{{ section.content }}</p>
        <div v-if="section.doc_ids?.length" class="doc-ids">
          <span v-for="docId in section.doc_ids" :key="docId" class="doc-id">{{ docId }}</span>
        </div>
      </div>
    </div>

    <details v-if="refs.length" class="refs">
      <summary>参考来源（{{ refs.length }}）</summary>
      <div v-for="ref in refs" :key="`${ref.doc_id}-${ref.source}`" class="ref-item">
        <span class="ref-title">{{ ref.title }}</span>
        <span class="ref-score">{{ Math.round((ref.score || 0) * 100) }}%</span>
      </div>
    </details>

    <div class="feedback">
      <span class="feedback-label">这条建议有用吗？</span>
      <button
        type="button"
        :class="['feedback-btn', { active: advice.feedback === 1 }]"
        :disabled="!!advice.feedback"
        @click="feedback(1)"
      >
        有用
      </button>
      <button
        type="button"
        :class="['feedback-btn', { active: advice.feedback === -1 }]"
        :disabled="!!advice.feedback"
        @click="feedback(-1)"
      >
        无用
      </button>
      <span v-if="advice.feedback" class="feedback-done">已反馈</span>
    </div>
  </div>
</template>

<style scoped>
.advice-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  color: #3c4a3c;
  font-size: 14px;
  line-height: 1.75;
}

.advice-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.species {
  font-size: 15px;
  font-weight: 600;
  color: #2d3a2d;
}

.confidence {
  color: #9aa89a;
  font-size: 12px;
}

.badge {
  padding: 1px 8px;
  border-radius: 999px;
  background: rgba(179, 138, 60, 0.12);
  color: #b38a3c;
  font-size: 12px;
}

.fallback-tip {
  padding: 8px 12px;
  border: 1px solid rgba(179, 138, 60, 0.35);
  border-radius: 8px;
  background: rgba(179, 138, 60, 0.08);
  color: #8c6a2f;
  font-size: 13px;
}

.summary {
  margin: 0;
  color: #2d3a2d;
  font-weight: 500;
}

.warning {
  padding: 8px 12px;
  border-left: 3px solid #d03050;
  border-radius: 6px;
  background: rgba(208, 48, 80, 0.06);
  color: #a3253e;
  font-size: 13px;
}

.sections {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 2px;
}

.section {
  padding: 10px 14px;
  border: 1px solid #e3e8e0;
  border-radius: 10px;
  background: #ffffff;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 4px;
}

.section-title {
  color: #2d3a2d;
  font-weight: 600;
  font-size: 13px;
}

.source {
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  white-space: nowrap;
}

.source.knowledge {
  background: #e4f3e3;
  color: #3f8f47;
}

.source.general {
  background: rgba(179, 138, 60, 0.12);
  color: #b38a3c;
}

.section-content {
  margin: 0;
  color: #4a5a4a;
  font-size: 13px;
}

.doc-ids {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 6px;
}

.doc-id {
  padding: 0 6px;
  border-radius: 4px;
  background: #f2f6ef;
  color: #8a968a;
  font-size: 11px;
}

.refs {
  margin-top: 2px;
  border-top: 1px solid #eef2ec;
  padding-top: 8px;
  color: #8a968a;
  font-size: 12px;
}

.refs summary {
  cursor: pointer;
  color: #6b7a6b;
}

.ref-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 4px 0;
}

.ref-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ref-score {
  color: #9aa89a;
}

.feedback {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid #eef2ec;
}

.feedback-label {
  color: #8a968a;
  font-size: 12px;
}

.feedback-btn {
  padding: 3px 12px;
  border: 1px solid #dfe6db;
  border-radius: 6px;
  background: #ffffff;
  color: #6b7a6b;
  font-size: 12px;
  cursor: pointer;
}

.feedback-btn:hover:not(:disabled) {
  border-color: #3f8f47;
  color: #3f8f47;
}

.feedback-btn.active {
  border-color: #3f8f47;
  background: #e4f3e3;
  color: #3f8f47;
}

.feedback-btn:disabled {
  cursor: default;
  opacity: 0.55;
}

.feedback-done {
  color: #3f8f47;
  font-size: 12px;
}
</style>