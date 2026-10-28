<script setup>
// 个人中心页（PRD 5.5 P5 个人中心·日历打卡）
// 模块1 个人信息区：
//   1. 头像点击上传（PUT /auth/avatar 原子上传 + 落库 + 清理旧头像）
//   2. 修改昵称（PUT /auth/profile，3-20 位字母数字下划线，唯一性由后端校验）
//   3. 修改密码（PUT /auth/password：原密码 + 新密码 + 确认密码）
//   4. 退出登录
// 模块2 打卡日历区：
//   5. 月历视图（GET /checkins/calendar?month=YYYY-MM），有记录的日期按打卡次数分级上色 + 次数角标
//   6. 点击日期查看当天打卡记录（GET /checkins?record_date=YYYY-MM-DD）
//   7. 当天记录可撤销（DELETE /checkins/{id}，仅当天可撤销，二次确认）
//   8. 日历内直接新增打卡（抽屉表单：植物 + 类型 + 备注 + 多图，未来日期禁止）
//   9. 连续打卡天数 / 本月打卡统计 / 类型偏好（GET /user/stats）
// 布局：PC 双列（左资料统计、右日历记录），移动端单列，日历 7 列网格自适应
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'

import { createCheckin, deleteCheckin, getCheckinCalendar, getCheckins } from '@/api/checkins'
import { getPlants } from '@/api/plants'
import { changePassword, getUserStats, updateProfile } from '@/api/user'
import { uploadAvatar, uploadImage } from '@/api/upload'
import { useAuthStore } from '@/stores/auth'

const message = useMessage()
const router = useRouter()
const auth = useAuthStore()

// ---- 常量：打卡类型（PRD care_type 枚举 → 中文展示与标签色）----
const CARE_TYPES = [
  { value: 'watering', label: '浇水', tag: 'success' },
  { value: 'fertilizing', label: '施肥', tag: 'warning' },
  { value: 'pruning', label: '修剪', tag: 'info' },
  { value: 'repotting', label: '换盆', tag: 'default' },
  { value: 'pest_control', label: '病虫害防治', tag: 'error' },
  { value: 'other', label: '其他', tag: 'default' },
]

// 周起始为周一（与国内日历习惯一致）
const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']
const NICKNAME_PATTERN = /^[a-zA-Z0-9_]{3,20}$/
const PASSWORD_PATTERN = /^(?=.*[A-Za-z])(?=.*\d).{8,64}$/
const MAX_IMAGE_SIZE = 5 * 1024 * 1024
const ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']

// ---- 状态：头像 ----
const avatarInputRef = ref(null)
const avatarUploading = ref(false)
const avatarPreview = ref('')

// 浏览器可能缓存了修复静态挂载前的 404 响应：首次加载失败时加时间戳重试一次
const avatarBust = ref(0)
// 重试仍失败时回退为首字母占位（避免破图）
const avatarFailed = ref(false)
const avatarSrc = computed(() => {
  if (avatarFailed.value) return ''
  const url = avatarPreview.value || auth.user?.avatar_url || ''
  if (!url || !avatarBust.value) return url
  return `${url}${url.includes('?') ? '&' : '?'}t=${avatarBust.value}`
})
const avatarFallback = computed(() => (auth.user?.nickname || '植').slice(0, 1).toUpperCase())

// ---- 状态：昵称（默认只读，点击编辑后进入编辑态）----
const nicknameEditing = ref(false)
const nicknameDraft = ref('')
const nicknameError = ref('')
const nicknameSaving = ref(false)

// ---- 状态：修改密码 ----
const passwordForm = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })
const passwordError = reactive({ old: '', new: '', confirm: '' })
const passwordSaving = ref(false)

// ---- 状态：打卡统计 ----
const stats = ref(null)

// ---- 状态：日历 ----
const now = new Date()
const todayStr = formatDate(now)
const viewYear = ref(now.getFullYear())
const viewMonth = ref(now.getMonth()) // 0-11
const calendarDays = ref([])
const calendarLoading = ref(false)
const calendarSummary = reactive({ checkin_count: 0, active_days: 0 })
const selectedDate = ref(todayStr)

// ---- 状态：当天打卡记录 ----
const dayRecords = ref([])
const recordsLoading = ref(false)

// ---- 状态：新增打卡抽屉 ----
const drawerVisible = ref(false)
const plants = ref([])
const plantLoading = ref(false)
const uploadRef = ref(null)
const checkinForm = reactive({ plantId: null, careType: null, note: '', images: [] })
const checkinError = reactive({ plant: '', careType: '' })
const checkinSubmitting = ref(false)

// ---- 状态：移动端断点（抽屉全屏/日历紧凑）----
const isMobile = ref(window.innerWidth < 640)
function onResize() {
  isMobile.value = window.innerWidth < 640
}

// ---- 日期工具：本地时区格式化，避免 toISOString 的 UTC 偏移导致跨日 ----
function formatDate(value) {
  const date = value instanceof Date ? value : new Date(value)
  const pad = (num) => String(num).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function careMeta(careType) {
  return CARE_TYPES.find((item) => item.value === careType) || { label: careType, tag: 'default' }
}

const isTodaySelected = computed(() => selectedDate.value === todayStr)
const isFutureSelected = computed(() => selectedDate.value > todayStr)
const selectedLabel = computed(() => {
  const [year, month, day] = selectedDate.value.split('-').map(Number)
  const suffix = isTodaySelected.value ? '（今天）' : ''
  return `${year} 年 ${month} 月 ${day} 日${suffix}`
})

// ---- 日历单元格：周一为首列，空白补位保持整齐 ----
const calendarCells = computed(() => {
  const firstDay = new Date(viewYear.value, viewMonth.value, 1)
  const offset = (firstDay.getDay() + 6) % 7 // JS 周日=0，转为周一=0
  const daysInMonth = new Date(viewYear.value, viewMonth.value + 1, 0).getDate()
  const dayMap = new Map(calendarDays.value.map((item) => [item.date, item]))
  const pad = (num) => String(num).padStart(2, '0')

  const cells = []
  for (let i = 0; i < offset; i += 1) {
    cells.push({ key: `blank-${i}`, day: 0 })
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    const dateStr = `${viewYear.value}-${pad(viewMonth.value + 1)}-${pad(day)}`
    const info = dayMap.get(dateStr)
    cells.push({
      key: dateStr,
      day,
      dateStr,
      count: info?.count || 0,
      types: info?.types || [],
      marked: !!info,
      isToday: dateStr === todayStr,
      isFuture: dateStr > todayStr,
    })
  }
  while (cells.length % 7 !== 0) {
    cells.push({ key: `tail-${cells.length}`, day: 0 })
  }
  return cells
})

// 单元格样式：打卡次数 1/2/3+ 三级背景色，选中与今天用描边区分
function cellClass(cell) {
  return {
    'is-empty': !cell.day,
    'is-marked': cell.marked,
    [`is-level-${Math.min(cell.count, 3)}`]: cell.marked,
    'is-today': cell.isToday,
    'is-future': cell.isFuture,
    'is-selected': cell.dateStr === selectedDate.value,
  }
}

// ---- 数据加载：统计 ----
async function loadStats() {
  try {
    stats.value = await getUserStats()
  } catch (err) {
    message.error(err.message || '打卡统计加载失败')
  }
}

// ---- 数据加载：月历 ----
async function loadCalendar() {
  const monthKey = `${viewYear.value}-${String(viewMonth.value + 1).padStart(2, '0')}`
  calendarLoading.value = true
  try {
    const data = await getCheckinCalendar(monthKey)
    calendarDays.value = data.days || []
    calendarSummary.checkin_count = data.checkin_count || 0
    calendarSummary.active_days = data.active_days || 0
  } catch (err) {
    message.error(err.message || '打卡日历加载失败')
  } finally {
    calendarLoading.value = false
  }
}

// ---- 数据加载：选中日期的打卡记录（按日筛选，一次取满 50 条）----
async function loadDayRecords() {
  recordsLoading.value = true
  try {
    const data = await getCheckins({ record_date: selectedDate.value, page: 1, page_size: 50 })
    dayRecords.value = data.items || []
  } catch (err) {
    message.error(err.message || '当天打卡记录加载失败')
  } finally {
    recordsLoading.value = false
  }
}

// ---- 数据加载：植物下拉（抽屉打开时才加载，减少首屏请求）----
async function loadPlants() {
  if (plantLoading.value || plants.value.length) return
  plantLoading.value = true
  try {
    const data = await getPlants({ page: 1, page_size: 50 })
    plants.value = data.items || []
  } catch (err) {
    message.error(err.message || '植物列表加载失败')
  } finally {
    plantLoading.value = false
  }
}

// ---- 日历交互：切月 / 回到今天 / 选日期 ----
function changeMonth(offset) {
  const target = new Date(viewYear.value, viewMonth.value + offset, 1)
  viewYear.value = target.getFullYear()
  viewMonth.value = target.getMonth()
  loadCalendar()
}

function goToday() {
  viewYear.value = now.getFullYear()
  viewMonth.value = now.getMonth()
  selectedDate.value = todayStr
  loadCalendar()
  loadDayRecords()
}

function selectDate(cell) {
  if (!cell.day) return
  selectedDate.value = cell.dateStr
  loadDayRecords()
}

// ---- 头像：点击选择文件 → 上传 → 回写资料 ----
function triggerAvatarPick() {
  if (avatarUploading.value) return
  avatarInputRef.value?.click()
}

// 头像加载失败：先带时间戳重试一次（绕过缓存中的 404），仍失败再回退占位并提示
function handleAvatarError() {
  if (!avatarBust.value) {
    avatarBust.value = Date.now()
    return
  }
  avatarFailed.value = true
  message.warning('头像加载失败，请确认后端服务已启动后重新上传')
}

async function onAvatarChange(event) {
  const file = event.target.files?.[0]
  event.target.value = '' // 清空选择，保证同一文件可再次触发 change
  if (!file) return
  if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
    message.error('仅支持 jpg/png/webp 格式图片')
    return
  }
  if (file.size > MAX_IMAGE_SIZE) {
    message.error('图片大小不能超过 5MB')
    return
  }

  avatarUploading.value = true
  avatarBust.value = 0
  avatarFailed.value = false
  try {
    // 原子上传：服务端一次完成「落盘 → 落库 → 清理旧头像」，失败自动回滚新文件
    const user = await uploadAvatar(file)
    auth.user = user
    // 先落预览地址再提示，确保界面立即刷新（URL 变更会触发 NAvatar 重新加载）
    avatarPreview.value = user.avatar_url
    message.success('头像已更新')
  } catch (err) {
    message.error(err.message || '头像上传失败')
  } finally {
    avatarUploading.value = false
  }
}

// ---- 昵称：默认只读，编辑态下仅保留「取消 / 保存」----
function startEditNickname() {
  nicknameDraft.value = auth.user?.nickname || ''
  nicknameError.value = ''
  nicknameEditing.value = true
}

function cancelEditNickname() {
  nicknameEditing.value = false
  nicknameError.value = ''
  nicknameDraft.value = auth.user?.nickname || ''
}

async function saveNickname() {
  const nickname = nicknameDraft.value.trim()
  if (!nickname) {
    nicknameError.value = '请输入昵称'
    return
  }
  if (!NICKNAME_PATTERN.test(nickname)) {
    nicknameError.value = '昵称需为 3-20 位字母、数字或下划线'
    return
  }
  if (nickname === auth.user?.nickname) {
    message.info('昵称未发生变化')
    return
  }

  nicknameError.value = ''
  nicknameSaving.value = true
  try {
    const user = await updateProfile({ nickname })
    auth.user = user
    nicknameEditing.value = false
    message.success('昵称修改成功')
  } catch (err) {
    nicknameError.value = err.message || '昵称修改失败'
  } finally {
    nicknameSaving.value = false
  }
}

// ---- 修改密码：原密码必填、新密码强度、两次一致、新旧不同 ----
async function savePassword() {
  passwordError.old = passwordForm.oldPassword ? '' : '请输入原密码'
  passwordError.new = PASSWORD_PATTERN.test(passwordForm.newPassword)
    ? ''
    : '新密码需 8-64 位且同时包含字母和数字'
  passwordError.confirm =
    passwordForm.newPassword === passwordForm.confirmPassword ? '' : '两次输入的新密码不一致'
  if (passwordError.old || passwordError.new || passwordError.confirm) return
  if (passwordForm.oldPassword === passwordForm.newPassword) {
    passwordError.new = '新密码不能与原密码相同'
    return
  }

  passwordSaving.value = true
  try {
    await changePassword({
      old_password: passwordForm.oldPassword,
      new_password: passwordForm.newPassword,
    })
    message.success('密码修改成功')
    passwordForm.oldPassword = ''
    passwordForm.newPassword = ''
    passwordForm.confirmPassword = ''
  } catch (err) {
    // 后端「原密码错误」等中文提示直接展示在原密码输入框
    passwordError.old = err.message || '密码修改失败'
  } finally {
    passwordSaving.value = false
  }
}

// ---- 新增打卡抽屉 ----
function openCheckinDrawer() {
  if (isFutureSelected.value) {
    message.warning('不能为未来日期打卡')
    return
  }
  resetCheckinForm()
  drawerVisible.value = true
  loadPlants()
}

function resetCheckinForm() {
  checkinForm.plantId = null
  checkinForm.careType = null
  checkinForm.note = ''
  checkinForm.images = []
  checkinError.plant = ''
  checkinError.careType = ''
  uploadRef.value?.clear()
}

async function handleCustomUpload({ file, onSuccess, onError }) {
  if (checkinForm.images.length >= 5) {
    message.warning('最多上传 5 张图片')
    onError(new Error('超过图片数量上限'))
    return
  }
  try {
    const url = await uploadImage(file.file)
    file.url = url
    checkinForm.images.push(url)
    onSuccess(url)
  } catch (err) {
    message.error(err.message || '图片上传失败')
    onError(err)
  }
}

function onUploadChange({ fileList }) {
  checkinForm.images = fileList
    .filter((file) => file.status === 'finished' && file.url)
    .map((file) => file.url)
}

async function submitCheckin() {
  checkinError.plant = checkinForm.plantId ? '' : '请选择植物'
  checkinError.careType = checkinForm.careType ? '' : '请选择打卡类型'
  if (checkinError.plant || checkinError.careType) return

  checkinSubmitting.value = true
  try {
    await createCheckin({
      plant_id: checkinForm.plantId,
      care_type: checkinForm.careType,
      content: checkinForm.note.trim() || null,
      record_date: selectedDate.value,
      image_urls: checkinForm.images.length ? checkinForm.images : null,
    })
    message.success('打卡成功')
    drawerVisible.value = false
    resetCheckinForm()
    await Promise.all([loadCalendar(), loadDayRecords(), loadStats()])
  } catch (err) {
    message.error(err.message || '打卡失败')
  } finally {
    checkinSubmitting.value = false
  }
}

// ---- 撤销当天打卡：二次确认由 n-popconfirm 承担，仅当天记录可撤销 ----
async function handleDelete(record) {
  try {
    await deleteCheckin(record.id)
    message.success('已撤销打卡')
    await Promise.all([loadCalendar(), loadDayRecords(), loadStats()])
  } catch (err) {
    message.error(err.message || '撤销打卡失败')
  }
}

function handleLogout() {
  auth.logout()
  router.push('/login')
}

onMounted(async () => {
  window.addEventListener('resize', onResize)
  // 始终以服务端资料为准：避免残留的旧 avatar_url 导致头像不显示
  try {
    await auth.fetchProfile()
  } catch (err) {
    // 401 已由请求拦截器统一跳转登录页，其余错误静默避免首屏打扰
  }
  nicknameDraft.value = auth.user?.nickname || ''
  avatarPreview.value = auth.user?.avatar_url || ''
  avatarBust.value = 0
  avatarFailed.value = false
  loadStats()
  loadCalendar()
  loadDayRecords()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <div class="profile-page">
    <header class="page-head">
      <h2 class="page-title">个人中心</h2>
      <p class="page-sub">管理账号资料，回顾每一天与植物的打卡约定。</p>
    </header>

    <div class="profile-layout">
      <!-- ================= 左列：个人信息 + 打卡统计 ================= -->
      <div class="column">
        <n-card class="block-card" title="个人信息">
          <!-- 头像：点击整块区域触发文件选择，移动端同样友好 -->
          <div class="avatar-block">
            <button
              type="button"
              class="avatar-button"
              :disabled="avatarUploading"
              aria-label="点击更换头像"
              @click="triggerAvatarPick"
            >
              <!-- 有图走 :src 分支，无图/加载失败才用默认插槽显示首字母：
                   NAvatar 的默认插槽优先级高于 src，两者同时存在时图片永不渲染 -->
              <n-avatar
                v-if="avatarSrc"
                :key="avatarSrc"
                round
                :size="76"
                :src="avatarSrc"
                :on-error="handleAvatarError"
                class="avatar"
              />
              <n-avatar v-else round :size="76" class="avatar">
                {{ avatarFallback }}
              </n-avatar>
              <span class="avatar-mask">{{ avatarUploading ? '上传中…' : '更换头像' }}</span>
            </button>
            <input
              ref="avatarInputRef"
              class="avatar-input"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              @change="onAvatarChange"
            />
            <div class="avatar-meta">
              <p class="nickname">{{ auth.user?.nickname || '未登录' }}</p>
              <p class="meta-tip">支持 jpg/png/webp，≤5MB</p>
            </div>
          </div>

          <n-form class="profile-form" label-placement="top">
            <n-form-item
              label="昵称"
              :validation-status="nicknameError ? 'error' : undefined"
              :feedback="nicknameError"
            >
              <!-- 只读态：昵称 + 编辑按钮 -->
              <div v-if="!nicknameEditing" class="inline-field">
                <span class="nickname-text">{{ auth.user?.nickname || '-' }}</span>
                <n-button size="small" type="primary" secondary @click="startEditNickname">
                  编辑
                </n-button>
              </div>
              <!-- 编辑态：输入框 + 取消 / 保存（不显示编辑按钮） -->
              <div v-else class="inline-field">
                <n-input
                  v-model:value="nicknameDraft"
                  placeholder="3-20 位字母、数字或下划线"
                  maxlength="20"
                  :input-props="{ autocomplete: 'off' }"
                  @input="nicknameError = ''"
                  @keyup.enter="saveNickname"
                />
                <div class="edit-actions">
                  <n-button :disabled="nicknameSaving" @click="cancelEditNickname">取消</n-button>
                  <n-button type="primary" :loading="nicknameSaving" @click="saveNickname">
                    保存
                  </n-button>
                </div>
              </div>
            </n-form-item>
          </n-form>

          <n-collapse class="password-collapse">
            <n-collapse-item title="修改密码" name="password">
              <n-form label-placement="top">
                <n-form-item
                  label="原密码"
                  :validation-status="passwordError.old ? 'error' : undefined"
                  :feedback="passwordError.old"
                >
                  <n-input
                    v-model:value="passwordForm.oldPassword"
                    type="password"
                    show-password-on="click"
                    placeholder="请输入当前密码"
                    :input-props="{ autocomplete: 'current-password' }"
                    @input="passwordError.old = ''"
                  />
                </n-form-item>
                <n-form-item
                  label="新密码"
                  :validation-status="passwordError.new ? 'error' : undefined"
                  :feedback="passwordError.new"
                >
                  <n-input
                    v-model:value="passwordForm.newPassword"
                    type="password"
                    show-password-on="click"
                    placeholder="8-64 位，需同时包含字母和数字"
                    :input-props="{ autocomplete: 'new-password' }"
                    @input="passwordError.new = ''"
                  />
                </n-form-item>
                <n-form-item
                  label="确认新密码"
                  :validation-status="passwordError.confirm ? 'error' : undefined"
                  :feedback="passwordError.confirm"
                >
                  <n-input
                    v-model:value="passwordForm.confirmPassword"
                    type="password"
                    show-password-on="click"
                    placeholder="请再次输入新密码"
                    :input-props="{ autocomplete: 'new-password' }"
                    @input="passwordError.confirm = ''"
                  />
                </n-form-item>
                <div class="form-actions">
                  <n-button type="primary" :loading="passwordSaving" @click="savePassword">
                    提交修改
                  </n-button>
                </div>
              </n-form>
            </n-collapse-item>
          </n-collapse>

          <div class="logout-row">
            <n-button quaternary type="error" @click="handleLogout">退出登录</n-button>
          </div>
        </n-card>

        <n-card class="block-card" title="打卡统计">
          <div v-if="stats" class="stat-body">
            <div class="streak-badge">
              <n-tag type="success" round size="large">🔥 连续打卡 {{ stats.streak_days }} 天</n-tag>
            </div>
            <div class="stat-grid">
              <div class="stat-item">
                <span class="stat-value">{{ stats.month_checkin_count }}</span>
                <span class="stat-label">本月打卡次数</span>
              </div>
              <div class="stat-item">
                <span class="stat-value">{{ stats.month_active_days }}</span>
                <span class="stat-label">本月打卡天数</span>
              </div>
              <div class="stat-item">
                <span class="stat-value">{{ stats.total_active_days }}</span>
                <span class="stat-label">累计打卡天数</span>
              </div>
              <div class="stat-item">
                <span class="stat-value">{{ stats.plant_count }}</span>
                <span class="stat-label">在养植物</span>
              </div>
            </div>
            <div v-if="stats.type_counts.length" class="type-preference">
              <span class="type-preference-label">养护偏好</span>
              <div class="type-chips">
                <n-tag
                  v-for="item in stats.type_counts.slice(0, 3)"
                  :key="item.type"
                  size="small"
                  :bordered="false"
                >
                  {{ item.label }} {{ item.count }} 次
                </n-tag>
              </div>
            </div>
          </div>
          <n-empty v-else description="还没有打卡数据，去日历里记录第一次养护吧" />
        </n-card>
      </div>

      <!-- ================= 右列：日历 + 当天记录 ================= -->
      <div class="column">
        <n-card class="block-card calendar-card">
          <template #header>
            <div class="calendar-header">
              <span class="calendar-title">打卡日历</span>
              <div class="calendar-nav">
                <n-button size="tiny" quaternary aria-label="上一月" @click="changeMonth(-1)">
                  ‹
                </n-button>
                <span class="calendar-month">{{ viewYear }} 年 {{ viewMonth + 1 }} 月</span>
                <n-button size="tiny" quaternary aria-label="下一月" @click="changeMonth(1)">
                  ›
                </n-button>
                <n-button size="tiny" tertiary @click="goToday">今天</n-button>
              </div>
            </div>
          </template>

          <p class="calendar-summary">
            本月打卡 <strong>{{ calendarSummary.checkin_count }}</strong> 次 · 覆盖
            <strong>{{ calendarSummary.active_days }}</strong> 天
          </p>

          <n-spin :show="calendarLoading">
            <div class="calendar-grid" role="grid" aria-label="打卡日历">
              <div v-for="week in WEEKDAYS" :key="week" class="calendar-weekday">{{ week }}</div>
              <button
                v-for="cell in calendarCells"
                :key="cell.key"
                type="button"
                class="calendar-cell"
                :class="cellClass(cell)"
                :disabled="!cell.day"
                :aria-label="cell.day ? `${cell.dateStr}（打卡 ${cell.count} 次）` : undefined"
                role="gridcell"
                @click="selectDate(cell)"
              >
                <template v-if="cell.day">
                  <span class="calendar-day">{{ cell.day }}</span>
                  <span v-if="cell.count" class="calendar-count">{{ cell.count }}</span>
                </template>
              </button>
            </div>
          </n-spin>

          <div class="calendar-legend">
            <span class="legend-dot level-0" />无打卡
            <span class="legend-dot level-1" />1 次
            <span class="legend-dot level-2" />2 次
            <span class="legend-dot level-3" />3 次及以上
          </div>
        </n-card>

        <n-card class="block-card">
          <template #header>
            <div class="day-header">
              <span class="day-title">{{ selectedLabel }}</span>
              <n-button
                type="primary"
                size="small"
                :disabled="isFutureSelected"
                @click="openCheckinDrawer"
              >
                打卡
              </n-button>
            </div>
          </template>

          <n-spin :show="recordsLoading">
            <n-empty
              v-if="!dayRecords.length"
              :description="isFutureSelected ? '未来日期还没有打卡记录' : '这一天还没有打卡记录'"
            />
            <div v-else class="record-list">
              <div v-for="record in dayRecords" :key="record.id" class="record-item">
                <div class="record-head">
                  <div class="record-tags">
                    <n-tag size="small" :bordered="false">
                      {{ record.plant_name || `植物#${record.plant_id}` }}
                    </n-tag>
                    <n-tag size="small" :type="careMeta(record.care_type).tag">
                      {{ careMeta(record.care_type).label }}
                    </n-tag>
                  </div>
                  <n-popconfirm
                    v-if="isTodaySelected"
                    positive-text="撤销"
                    negative-text="取消"
                    @positive-click="handleDelete(record)"
                  >
                    <template #trigger>
                      <n-button size="tiny" text type="error">撤销</n-button>
                    </template>
                    仅当天打卡可撤销，撤销后不可恢复，确认继续吗？
                  </n-popconfirm>
                </div>
                <p v-if="record.content" class="record-content">{{ record.content }}</p>
                <n-image-group v-if="record.images?.length" class="record-images">
                  <n-image
                    v-for="img in record.images"
                    :key="img"
                    :src="img"
                    width="64"
                    height="64"
                    object-fit="cover"
                    class="record-thumb"
                  />
                </n-image-group>
              </div>
            </div>
          </n-spin>
        </n-card>
      </div>
    </div>

    <!-- 新增打卡抽屉：日期由日历选择决定，未来日期入口已被禁用 -->
    <n-drawer v-model:show="drawerVisible" :width="isMobile ? '100%' : 460" placement="right">
      <n-drawer-content :title="`${selectedLabel} 打卡`" closable>
        <n-form label-placement="top">
          <n-form-item
            label="植物"
            :validation-status="checkinError.plant ? 'error' : undefined"
            :feedback="checkinError.plant"
          >
            <n-select
              v-model:value="checkinForm.plantId"
              :options="plants.map((plant) => ({ label: plant.name, value: plant.id }))"
              :loading="plantLoading"
              placeholder="选择我名下的植物"
              @change="checkinError.plant = ''"
            />
            <span v-if="!plantLoading && plants.length === 0" class="field-tip">
              你还没有植物档案，请先到「植物记录」页添加一株
            </span>
          </n-form-item>

          <n-form-item
            label="打卡类型"
            :validation-status="checkinError.careType ? 'error' : undefined"
            :feedback="checkinError.careType"
          >
            <n-select
              v-model:value="checkinForm.careType"
              :options="CARE_TYPES"
              placeholder="选择打卡类型"
              @change="checkinError.careType = ''"
            />
          </n-form-item>

          <n-form-item label="图片">
            <n-upload
              ref="uploadRef"
              multiple
              :max="5"
              accept="image/jpeg,image/png,image/webp"
              :custom-request="handleCustomUpload"
              @change="onUploadChange"
            >
              <n-button>拍照 / 选择图片</n-button>
            </n-upload>
            <span class="field-tip">可选，支持 jpg/png/webp，单张 ≤5MB，最多 5 张</span>
          </n-form-item>

          <n-form-item label="备注">
            <n-input
              v-model:value="checkinForm.note"
              type="textarea"
              placeholder="养护细节，如：浇水 500ml、施肥 10g"
              maxlength="512"
              :autosize="{ minRows: 3, maxRows: 6 }"
            />
          </n-form-item>
        </n-form>
        <template #footer>
          <div class="drawer-footer">
            <n-button @click="drawerVisible = false">取消</n-button>
            <n-button type="primary" :loading="checkinSubmitting" @click="submitCheckin">
              提交打卡
            </n-button>
          </div>
        </template>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<style scoped>
.profile-page {
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
}

/* PC 双列：左列为资料与统计，右列为日历与当天记录 */
.profile-layout {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) minmax(0, 1.35fr);
  gap: 16px;
  align-items: start;
}

.column {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.block-card {
  border-radius: 12px;
}

/* ---------- 头像 ---------- */
.avatar-block {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 18px;
}

.avatar-button {
  position: relative;
  padding: 0;
  border: none;
  background: none;
  border-radius: 50%;
  cursor: pointer;
  overflow: hidden;
  flex-shrink: 0;
}

.avatar-button:disabled {
  cursor: progress;
}

.avatar-mask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: #fff;
  background: rgba(0, 0, 0, 0.42);
  opacity: 0;
  transition: opacity 0.2s;
}

.avatar-button:hover .avatar-mask,
.avatar-button:focus-visible .avatar-mask {
  opacity: 1;
}

.avatar-input {
  display: none;
}

.avatar-meta {
  min-width: 0;
}

.nickname {
  font-size: 17px;
  font-weight: 600;
  color: #2d3a2d;
  word-break: break-all;
}

.meta-tip {
  margin-top: 4px;
  font-size: 12px;
  color: #9aa89a;
}

/* ---------- 表单 ---------- */
.inline-field {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.inline-field :deep(.n-input) {
  flex: 1;
}

/* 昵称只读态：昵称文本占满剩余空间，编辑按钮固定在右侧 */
.nickname-text {
  flex: 1;
  min-width: 0;
  font-size: 15px;
  color: #2d3a2d;
  word-break: break-all;
}

/* 编辑态：仅「取消 / 保存」两个按钮 */
.edit-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.password-collapse {
  margin-top: 4px;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
}

.logout-row {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #eef2ec;
  display: flex;
  justify-content: flex-end;
}

.field-tip {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: #9aa89a;
}

/* ---------- 统计 ---------- */
.stat-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.streak-badge {
  display: flex;
  justify-content: center;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border-radius: 10px;
  background: #f4f8f2;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: #3f8f47;
}

.stat-label {
  font-size: 12px;
  color: #7a8a7a;
}

.type-preference {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.type-preference-label {
  font-size: 12px;
  color: #7a8a7a;
}

.type-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* ---------- 日历 ---------- */
.calendar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.calendar-title {
  font-size: 16px;
  font-weight: 600;
}

.calendar-nav {
  display: flex;
  align-items: center;
  gap: 4px;
}

.calendar-month {
  min-width: 96px;
  text-align: center;
  font-size: 13px;
  color: #4a5a4a;
}

.calendar-summary {
  margin-bottom: 10px;
  font-size: 12px;
  color: #7a8a7a;
}

.calendar-summary strong {
  color: #3f8f47;
}

.calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 6px;
}

.calendar-weekday {
  text-align: center;
  font-size: 12px;
  color: #9aa89a;
  padding-bottom: 2px;
}

.calendar-cell {
  position: relative;
  min-height: 46px;
  padding: 4px 0;
  border: 1px solid transparent;
  border-radius: 10px;
  background: #f7f9f5;
  color: #4a5a4a;
  font-size: 14px;
  cursor: pointer;
  transition: transform 0.12s, box-shadow 0.12s;
}

.calendar-cell:not(.is-empty):hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(63, 143, 71, 0.12);
}

.calendar-cell.is-empty {
  background: transparent;
  cursor: default;
}

/* 有打卡记录：按次数分级上色（PRD FR-501 日期标记） */
.calendar-cell.is-level-1 {
  background: #e4f3e3;
  color: #2f6b34;
}

.calendar-cell.is-level-2 {
  background: #bfe3bf;
  color: #245826;
}

.calendar-cell.is-level-3 {
  background: #7cc47f;
  color: #173d19;
  font-weight: 600;
}

.calendar-cell.is-today {
  border-color: #8fbf90;
}

.calendar-cell.is-selected {
  border-color: #3f8f47;
  box-shadow: 0 0 0 2px rgba(63, 143, 71, 0.18);
}

.calendar-day {
  display: block;
  line-height: 1.2;
}

.calendar-count {
  position: absolute;
  top: 2px;
  right: 4px;
  font-size: 10px;
  line-height: 1.4;
  color: #3f8f47;
}

.calendar-cell.is-level-3 .calendar-count {
  color: #12451a;
}

.calendar-legend {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin-top: 12px;
  font-size: 11px;
  color: #8a968a;
}

.legend-dot {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 4px;
  margin-right: 4px;
  vertical-align: -2px;
}

.legend-dot.level-0 {
  background: #f7f9f5;
  border: 1px solid #e3e8e0;
}

.legend-dot.level-1 {
  background: #e4f3e3;
}

.legend-dot.level-2 {
  background: #bfe3bf;
}

.legend-dot.level-3 {
  background: #7cc47f;
}

/* ---------- 当天记录 ---------- */
.day-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.day-title {
  font-size: 15px;
  font-weight: 600;
}

.record-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.record-item {
  padding: 10px 12px;
  border-radius: 10px;
  background: #f8faf6;
}

.record-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.record-tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.record-content {
  margin-top: 8px;
  font-size: 13px;
  color: #3c4a3c;
  white-space: pre-wrap;
  word-break: break-all;
}

.record-images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.record-thumb {
  border-radius: 6px;
  cursor: zoom-in;
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

/* ---------- 移动端：单列 + 日历紧凑 + 头像信息纵向排列 ---------- */
@media (max-width: 900px) {
  .profile-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .avatar-block {
    gap: 12px;
  }

  /* 昵称编辑态在小屏下：输入框独占一行，取消/保存右对齐 */
  .inline-field {
    flex-wrap: wrap;
  }

  .inline-field :deep(.n-input) {
    flex-basis: 100%;
  }

  .edit-actions {
    width: 100%;
    justify-content: flex-end;
  }

  .calendar-grid {
    gap: 4px;
  }

  .calendar-cell {
    min-height: 40px;
    font-size: 13px;
  }

  .stat-value {
    font-size: 18px;
  }

  .calendar-nav :deep(.n-button) {
    padding-left: 6px;
    padding-right: 6px;
  }

  .calendar-month {
    min-width: 84px;
    font-size: 12px;
  }
}
</style>