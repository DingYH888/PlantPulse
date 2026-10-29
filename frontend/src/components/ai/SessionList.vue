<script setup>
// AI 会话侧边栏：桌面固定在左侧，移动端复用在抽屉中
// 职责：只负责渲染会话列表与触发事件，不直接发请求（数据由 AICare 维护）
// 视觉：浅色绿主题，与植物记录 / 数据统计 / 个人中心保持一致
import { computed } from 'vue'
import { NButton, NPopconfirm, NSpin } from 'naive-ui'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['select', 'new', 'delete'])

const hasSessions = computed(() => props.sessions.length > 0)

// 会话标题时间：只显示月-日 时:分，避免侧栏过长
function formatTime(value) {
  if (!value) return ''
  return value.replace('T', ' ').slice(5, 16)
}
</script>

<template>
  <div class="session-sidebar">
    <NButton class="new-chat" type="primary" block @click="emit('new')">+ 新建对话</NButton>

    <p class="section-title">历史对话</p>
    <NSpin :show="loading" class="session-spin">
      <div class="session-list">
        <!-- 外层用 div：内部还需放删除按钮，button 不能嵌套 button -->
        <div
          v-for="item in sessions"
          :key="item.session_id"
          :class="['session-item', { active: item.session_id === activeId }]"
          role="button"
          tabindex="0"
          @click="emit('select', item.session_id)"
          @keydown.enter.prevent="emit('select', item.session_id)"
        >
          <div class="session-main">
            <span class="session-title">{{ item.title }}</span>
            <span class="session-meta">
              {{ item.total }} 轮
              <template v-if="item.updated_at"> · {{ formatTime(item.updated_at) }}</template>
            </span>
          </div>
          <NPopconfirm
            positive-text="删除"
            negative-text="取消"
            @positive-click="emit('delete', item.session_id)"
          >
            <template #trigger>
              <button type="button" class="session-del" title="删除该会话" @click.stop>×</button>
            </template>
            删除该会话及其历史记录？
          </NPopconfirm>
        </div>
        <p v-if="!hasSessions && !loading" class="empty">暂无历史对话，开始第一次咨询吧</p>
      </div>
    </NSpin>

    <div class="session-footer">
      <span class="dot"></span>
      会话记忆仅保存在本次服务运行期间
    </div>
  </div>
</template>

<style scoped>
.session-sidebar {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 16px 12px;
  border-right: 1px solid #e3e8e0;
  background: #f7f9f5;
}

.new-chat {
  margin-bottom: 18px;
}

.section-title {
  margin: 0 6px 8px;
  color: #9aa89a;
  font-size: 12px;
  letter-spacing: 1px;
}

.session-spin {
  flex: 1;
  min-height: 0;
}

.session-spin :deep(.n-spin-container),
.session-spin :deep(.n-spin-content) {
  height: 100%;
}

.session-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 100%;
  overflow-y: auto;
}

.session-item {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 10px 8px 10px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: #4a5a4a;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.session-item:hover {
  background: #eef2ec;
}

.session-item.active {
  border-color: #8fbf90;
  background: #e4f3e3;
  color: #2f6b34;
}

.session-main {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.session-title {
  font-size: 13px;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-meta {
  color: #9aa89a;
  font-size: 11px;
}

/* 删除按钮：默认隐藏，hover / 键盘聚焦时出现；移动端常驻可点 */
.session-del {
  flex: none;
  width: 22px;
  height: 22px;
  padding: 0;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #9aa89a;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s, color 0.15s, background 0.15s;
}

.session-item:hover .session-del,
.session-del:focus-visible {
  opacity: 1;
}

.session-del:hover {
  color: #c4544a;
  background: #f4e7e5;
}

.empty {
  padding: 24px 8px;
  color: #9aa89a;
  font-size: 12px;
  text-align: center;
  line-height: 1.7;
}

.session-footer {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e3e8e0;
  color: #9aa89a;
  font-size: 11px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #3f8f47;
}

@media (max-width: 768px) {
  .session-del {
    opacity: 1;
  }
}
</style>