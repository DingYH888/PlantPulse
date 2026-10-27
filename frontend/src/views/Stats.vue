<script setup>
// 数据统计页（PRD 5.3 P3 数据图表 + 用户确认的统计口径）
// 功能点：
//   1. 下拉选择植物 + 维度切换（长势/浇水统计/施肥统计/光照统计）
//   2. 时间筛选：近 7 / 30 / 90 天
//   3. 切换维度/植物/时间即请求 GET /plants/{id}/stats
//   4. 自动判断图表类型：长势折线图，其余柱状图
//   5. ECharts 响应式 + 触摸 tooltip；空数据显示占位
//   6. 指标录入弹窗，让长势/光照维度能产生真实数据
//
// 长势口径（用户确认）：按 PRD 5.3.3 阈值将每日指标折算为 0~100 健康分；
// 正常 100 / 待关注 60 / 异常 20，取当日各项指标平均，tooltip 展示原始指标与异常项。
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'

import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { AxisPointerComponent, GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import { getPlants } from '@/api/plants'
import { getPlantStats } from '@/api/stats'
import { createMetric, getMetrics } from '@/api/metrics'

// 按需注册 ECharts 组件，避免整包引入（折线/柱状 + 提示框 + 坐标轴）
echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, AxisPointerComponent, CanvasRenderer])

const message = useMessage()
const router = useRouter()

// ---- 常量 ----
const DIMENSIONS = [
  { value: 'growth', label: '长势' },
  { value: 'watering', label: '浇水统计' },
  { value: 'fertilizing', label: '施肥统计' },
  { value: 'light', label: '光照统计' },
]

const RANGES = [
  { value: 7, label: '近7天' },
  { value: 30, label: '近30天' },
  { value: 90, label: '近90天' },
]

// 指标元数据：用于弹窗字段、tooltip 展示
const METRIC_FIELDS = [
  { key: 'temperature', label: '温度', unit: '℃', min: -20, max: 60, precision: 1, placeholder: '如 25' },
  { key: 'humidity', label: '空气湿度', unit: '%', min: 0, max: 100, precision: 1, placeholder: '如 50' },
  { key: 'light', label: '光照', unit: 'lux', min: 0, max: 200000, precision: 0, placeholder: '如 20000' },
  { key: 'soil_moisture', label: '土壤湿度', unit: '%', min: 0, max: 100, precision: 1, placeholder: '如 45' },
  { key: 'ph', label: 'pH', unit: '', min: 0, max: 14, precision: 2, placeholder: '如 6.2' },
]

const METRIC_META = {
  temperature: { label: '温度', unit: '℃', digits: 1 },
  humidity: { label: '空气湿度', unit: '%', digits: 1 },
  soil_moisture: { label: '土壤湿度', unit: '%', digits: 1 },
  ph: { label: 'pH', unit: '', digits: 2 },
  light: { label: '光照', unit: 'lux', digits: 0 },
}

const METRIC_ORDER = ['temperature', 'humidity', 'soil_moisture', 'ph', 'light']

// 汇总卡片配置：[标题, summary 字段, 单位]
const SUMMARY_CONFIG = {
  growth: [
    ['有效天数', 'total', '天'],
    ['平均健康分', 'average', '分'],
    ['最高健康分', 'max', '分'],
    ['最低健康分', 'min', '分'],
  ],
  watering: [
    ['累计浇水', 'total', '次'],
    ['日均浇水', 'average', '次'],
    ['单日最多', 'max', '次'],
    ['最近一次', 'latest', '次'],
  ],
  fertilizing: [
    ['累计施肥', 'total', '次'],
    ['日均施肥', 'average', '次'],
    ['单日最多', 'max', '次'],
    ['最近一次', 'latest', '次'],
  ],
  light: [
    ['记录天数', 'total', '天'],
    ['平均光照', 'average', 'lux'],
    ['最高光照', 'max', 'lux'],
    ['最近光照', 'latest', 'lux'],
  ],
}

// ---- 状态：筛选条件 ----
const plants = ref([])
const plantsLoading = ref(false)
const plantId = ref(null)
const dimension = ref('growth')
const days = ref(30)

// ---- 状态：统计结果与图表 ----
const stats = ref(null)
const loading = ref(false)
const chartEl = ref(null)
const isMobile = ref(typeof window !== 'undefined' ? window.innerWidth < 768 : false)
let chart = null
let resizeObserver = null
let statsRequestId = 0

// ---- 状态：指标录入弹窗 ----
const metricModalVisible = ref(false)
const metricSubmitting = ref(false)
const metricForm = reactive({
  recordDate: Date.now(),
  temperature: null,
  humidity: null,
  light: null,
  soil_moisture: null,
  ph: null,
})
let prefillRequestId = 0

// ---- 计算属性 ----
const plantOptions = computed(() => plants.value.map((plant) => ({ label: plant.name, value: plant.id })))
const hasPlants = computed(() => plants.value.length > 0)
const hasData = computed(() => !!stats.value?.has_data)
const chartHeight = computed(() => (isMobile.value ? '320px' : '380px'))

// 自动判断图表类型：优先后端返回的 chart_type；兜底长势折线、其余柱状
const chartType = computed(() => {
  if (stats.value?.chart_type) return stats.value.chart_type
  return dimension.value === 'growth' ? 'line' : 'bar'
})

const chartTitle = computed(() => {
  if (!stats.value) return '统计图表'
  return `${stats.value.plant.name} · ${stats.value.dimension_label}（近${stats.value.days}天）`
})

const emptyDescription = computed(() => {
  if (dimension.value === 'watering') return `近${days.value}天还没有浇水打卡记录`
  if (dimension.value === 'fertilizing') return `近${days.value}天还没有施肥打卡记录`
  if (dimension.value === 'light') return '暂无数据，请先录入光照指标'
  return '暂无数据，请先录入指标'
})

const summaryCards = computed(() => {
  if (!stats.value) return []
  const config = SUMMARY_CONFIG[stats.value.dimension] || []
  return config.map(([label, key, unit]) => ({
    label,
    unit,
    value: formatSummaryValue(stats.value.summary[key], unit),
  }))
})

// ---- 数据加载 ----
// 加载用户植物下拉，默认选中第一株，随后 watch 自动加载统计
async function loadPlants() {
  plantsLoading.value = true
  try {
    const data = await getPlants({ page: 1, page_size: 50 })
    plants.value = data.items || []
    if (!plantId.value && plants.value.length) {
      plantId.value = plants.value[0].id
    }
  } catch (err) {
    message.error(err.message || '植物列表加载失败')
  } finally {
    plantsLoading.value = false
  }
}

// 加载统计：切换植物/维度/时间都会触发；请求序号防止旧响应覆盖新数据
async function loadStats() {
  if (!plantId.value) {
    stats.value = null
    return
  }

  const requestId = ++statsRequestId
  loading.value = true
  stats.value = null
  try {
    const data = await getPlantStats(plantId.value, {
      dimension: dimension.value,
      days: days.value,
    })
    if (requestId !== statsRequestId) return
    stats.value = data
    await renderChart()
  } catch (err) {
    if (requestId !== statsRequestId) return
    message.error(err.message || '统计数据加载失败')
  } finally {
    if (requestId === statsRequestId) loading.value = false
  }
}

// ---- 图表渲染 ----
function ensureChart() {
  if (!chartEl.value) return null
  // 容器在空数据/加载态下可能隐藏（宽度为 0），此时初始化会得到错误尺寸
  if (!chart && chartEl.value.clientWidth > 0) {
    chart = echarts.init(chartEl.value)
    resizeObserver = new ResizeObserver(() => chart?.resize())
    resizeObserver.observe(chartEl.value)
  }
  return chart
}

async function renderChart() {
  await nextTick()
  if (!stats.value?.has_data) {
    chart?.clear()
    return
  }

  const instance = ensureChart()
  if (!instance) return
  instance.setOption(buildOption(stats.value), true)
  instance.resize()
}

function buildOption(data) {
  const isLine = chartType.value === 'line'
  const unit = data.unit
  const labels = data.points.map((point) => point.date.slice(5))
  const barValues = data.points.map((point) => point.value)

  // 长势折线：异常点红色、待关注点橙色，正常点沿用主题绿
  const lineValues = data.points.map((point) => {
    if (point.value === null || point.value === undefined) return null
    if (point.status === 'abnormal') {
      return { value: point.value, itemStyle: { color: '#d03050' } }
    }
    if (point.status === 'attention') {
      return { value: point.value, itemStyle: { color: '#f0a020' } }
    }
    return point.value
  })

  // X 轴标签密度：7 天全展示；30/90 天按屏幕宽度抽稀，避免移动端重叠
  const labelInterval =
    data.days <= 7 ? 0 : data.days <= 30 ? (isMobile.value ? 4 : 2) : isMobile.value ? 14 : 8

  return {
    animationDuration: 320,
    grid: {
      top: 44,
      right: isMobile.value ? 10 : 24,
      bottom: 8,
      left: 8,
      containLabel: true,
    },
    tooltip: {
      trigger: 'axis',
      // 触摸设备点击/滑动均可查看详情
      triggerOn: 'mousemove|click',
      confine: true,
      backgroundColor: 'rgba(45,58,45,0.94)',
      borderWidth: 0,
      padding: [10, 12],
      // 备注可能较长，限制宽度并允许换行，避免移动端 tooltip 超出屏幕
      extraCssText: 'max-width: 280px; white-space: normal; word-break: break-all;',
      textStyle: { color: '#ffffff', fontSize: isMobile.value ? 12 : 13 },
      axisPointer: { type: isLine ? 'line' : 'shadow' },
      formatter: (params) => buildTooltip(params?.[0]?.dataIndex),
    },
    xAxis: {
      type: 'category',
      data: labels,
      boundaryGap: !isLine,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#dfe6db' } },
      axisLabel: {
        color: '#7a8a7a',
        fontSize: isMobile.value ? 10 : 12,
        interval: labelInterval,
        rotate: data.days > 30 && isMobile.value ? 45 : 0,
      },
    },
    yAxis: {
      type: 'value',
      name: unit,
      nameTextStyle: { color: '#9aa89a', fontSize: isMobile.value ? 10 : 12, padding: [0, 0, 0, -6] },
      min: 0,
      max: isLine ? 100 : (value) => Math.max(1, Math.ceil(value.max)),
      minInterval: isLine ? undefined : 1,
      splitLine: { lineStyle: { color: '#eef2ec' } },
      axisLabel: {
        color: '#7a8a7a',
        fontSize: isMobile.value ? 10 : 12,
        formatter: (value) => formatAxisValue(value, unit),
      },
    },
    series: [
      {
        name: data.dimension_label,
        type: isLine ? 'line' : 'bar',
        data: isLine ? lineValues : barValues,
        smooth: isLine ? 0.25 : false,
        symbol: isLine ? 'circle' : 'none',
        symbolSize: isMobile.value ? 5 : 7,
        connectNulls: false,
        lineStyle: isLine ? { width: 2, color: '#3f8f47' } : undefined,
        itemStyle: isLine
          ? { color: '#3f8f47', borderColor: '#ffffff', borderWidth: 1 }
          : { color: '#7bbf82', borderRadius: [4, 4, 0, 0] },
        areaStyle: isLine ? { color: 'rgba(63,143,71,0.10)' } : undefined,
        barMaxWidth: isMobile.value ? 18 : 28,
        emphasis: { focus: 'series' },
      },
    ],
  }
}

// 备注为用户输入，注入 tooltip HTML 前必须转义，避免 XSS
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[char])
}

// 自定义 tooltip：长势展示健康分 + 原始指标 + 异常项；打卡/光照展示对应数值
function buildTooltip(dataIndex) {
  const data = stats.value
  if (!data) return ''
  const point = data.points?.[dataIndex]
  if (!point) return ''

  const lines = [`<div style="font-weight:600;margin-bottom:4px">${point.date}</div>`]

  if (data.dimension === 'growth') {
    if (point.value === null || point.value === undefined) {
      lines.push('<div style="opacity:.85">未录入指标</div>')
    } else {
      lines.push(`<div>长势健康分：<b>${formatNumber(point.value, 1)}</b> 分</div>`)
      if (point.metrics) {
        for (const key of METRIC_ORDER) {
          const value = point.metrics[key]
          if (value === null || value === undefined) continue
          const meta = METRIC_META[key]
          lines.push(
            `<div style="opacity:.85">${meta.label}：${formatMetricValue(key, value)}${meta.unit}</div>`
          )
        }
      }
      if (point.alerts?.length) {
        lines.push(
          `<div style="margin-top:6px;color:#ffd591">${point.alerts.join('；')}</div>`
        )
      }
    }
  } else if (data.dimension === 'light') {
    lines.push(`<div>平均光照：<b>${formatLux(point.value)}</b> lux</div>`)
  } else {
    lines.push(`<div>${data.dimension_label}：<b>${point.count ?? 0}</b> 次</div>`)
    // 备注为空时整行不展示；换行保留，内容做 HTML 转义
    const note = (point.content || '').trim()
    if (note) {
      lines.push(
        `<div style="margin-top:4px;opacity:.9">备注：${escapeHtml(note).replace(/\n/g, '<br>')}</div>`
      )
    }
  }

  return `<div style="line-height:1.65">${lines.join('')}</div>`
}

function handleResize() {
  const nextMobile = window.innerWidth < 768
  if (nextMobile !== isMobile.value) {
    isMobile.value = nextMobile
    if (hasData.value) nextTick(renderChart)
    return
  }
  chart?.resize()
}

// ---- 指标录入 ----
function isDateDisabled(timestamp) {
  return timestamp > Date.now()
}

function formatDate(timestamp) {
  const d = new Date(timestamp)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function resetMetricForm() {
  metricForm.recordDate = Date.now()
  for (const field of METRIC_FIELDS) {
    metricForm[field.key] = null
  }
}

function openMetricModal() {
  if (!plantId.value) {
    message.warning('请先选择植物')
    return
  }
  resetMetricForm()
  metricModalVisible.value = true
  prefillMetricForm(metricForm.recordDate)
}

// 回填所选日期已有指标：避免"按天覆盖"时把未改动的指标清空
async function prefillMetricForm(timestamp) {
  if (!plantId.value || !timestamp) return
  const requestId = ++prefillRequestId
  try {
    const data = await getMetrics(plantId.value, { days: 90 })
    if (requestId !== prefillRequestId) return
    const targetDate = formatDate(timestamp)
    const point = (data.points || []).find((item) => item.date === targetDate)
    for (const field of METRIC_FIELDS) {
      metricForm[field.key] = point?.[field.key] ?? null
    }
  } catch {
    // 回填失败不阻塞录入，保持空表单由用户填写
  }
}

watch(
  () => metricForm.recordDate,
  (value) => {
    if (metricModalVisible.value) prefillMetricForm(value)
  }
)

async function submitMetric() {
  const hasValue = METRIC_FIELDS.some((field) => metricForm[field.key] !== null)
  if (!hasValue) {
    message.warning('请至少填写一项养护指标')
    return
  }

  const payload = { record_date: formatDate(metricForm.recordDate) }
  for (const field of METRIC_FIELDS) {
    if (metricForm[field.key] !== null) payload[field.key] = metricForm[field.key]
  }

  metricSubmitting.value = true
  try {
    await createMetric(plantId.value, payload)
    message.success('指标录入成功')
    metricModalVisible.value = false
    await loadStats()
  } catch (err) {
    message.error(err.message || '指标录入失败')
  } finally {
    metricSubmitting.value = false
  }
}

// ---- 展示格式化 ----
function formatNumber(value, digits = 1) {
  const text = Number(value).toFixed(digits)
  return text.includes('.') ? text.replace(/0+$/, '').replace(/\.$/, '') : text
}

function formatMetricValue(key, value) {
  const meta = METRIC_META[key]
  if (key === 'light') return Math.round(value).toLocaleString('zh-CN')
  return formatNumber(value, meta.digits)
}

function formatLux(value) {
  if (value === null || value === undefined) return '--'
  return Math.round(value).toLocaleString('zh-CN')
}

function formatSummaryValue(value, unit) {
  if (value === null || value === undefined) return '--'
  if (unit === 'lux') return formatLux(value)
  if (unit === '次') return formatNumber(value, 2)
  return formatNumber(value, 1)
}

function formatAxisValue(value, unit) {
  if (unit === 'lux' && value >= 10000) return `${Math.round(value / 1000)}k`
  return value
}

function goToPlants() {
  router.push('/')
}

// ---- 生命周期 ----
watch([plantId, dimension, days], () => {
  loadStats()
})

onMounted(async () => {
  window.addEventListener('resize', handleResize)
  await loadPlants()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  resizeObserver?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="stats-page">
    <h2 class="page-title">数据统计</h2>
    <p class="page-sub">用图表看一株植物的成长节奏：长势、浇水、施肥与光照，触摸图表可查看每日详情。</p>

    <!-- 筛选区：植物 / 维度 / 时间 / 录入指标 -->
    <n-card class="filter-card" :bordered="false">
      <div class="filter-bar">
        <div class="filter-item">
          <span class="filter-label">植物</span>
          <n-select
            v-model:value="plantId"
            :options="plantOptions"
            :loading="plantsLoading"
            :clearable="false"
            filterable
            placeholder="选择植物"
            class="plant-select"
          />
        </div>

        <div class="filter-item">
          <span class="filter-label">维度</span>
          <n-radio-group v-model:value="dimension" size="small">
            <n-radio-button v-for="item in DIMENSIONS" :key="item.value" :value="item.value">
              {{ item.label }}
            </n-radio-button>
          </n-radio-group>
        </div>

        <div class="filter-item">
          <span class="filter-label">时间</span>
          <n-radio-group v-model:value="days" size="small">
            <n-radio-button v-for="item in RANGES" :key="item.value" :value="item.value">
              {{ item.label }}
            </n-radio-button>
          </n-radio-group>
        </div>

        <div class="filter-actions">
          <n-button type="primary" size="small" :disabled="!plantId" @click="openMetricModal">
            录入指标
          </n-button>
        </div>
      </div>
    </n-card>

    <!-- 图表区 -->
    <n-card class="chart-card" :bordered="false">
      <template #header>
        <div class="chart-header">
          <span class="chart-title">{{ chartTitle }}</span>
          <n-tag v-if="stats" size="small" :bordered="false" type="success">
            {{ chartType === 'line' ? '折线图' : '柱状图' }}
          </n-tag>
        </div>
      </template>

      <n-spin :show="loading || plantsLoading">
        <!-- 无植物档案：先引导去添加，避免统计页空白 -->
        <div v-if="!plantsLoading && !hasPlants" class="empty-block">
          <n-empty description="你还没有植物档案，先添加一株植物再来查看统计">
            <template #extra>
              <n-button size="small" type="primary" @click="goToPlants">去添加植物</n-button>
            </template>
          </n-empty>
        </div>

        <template v-else>
          <div v-if="!hasData && !loading" class="empty-block">
            <n-empty :description="emptyDescription" />
          </div>

          <!-- 图表容器始终保留（v-show），确保 ECharts 数据切换时尺寸计算正确 -->
          <div v-show="hasData" ref="chartEl" class="chart" :style="{ height: chartHeight }" />

          <!-- 汇总卡片 -->
          <div v-if="hasData" class="summary-grid">
            <div v-for="card in summaryCards" :key="card.label" class="summary-card">
              <span class="summary-label">{{ card.label }}</span>
              <span class="summary-value">
                {{ card.value }}<span v-if="card.value !== '--'" class="summary-unit">{{ card.unit }}</span>
              </span>
            </div>
          </div>

          <p v-if="hasData && dimension === 'growth'" class="chart-note">
            长势评分依据介绍：综合当日已录入的温度、空气湿度、土壤湿度、pH 与光照五项指标，按 PRD 5.3.3 阈值逐项判定为正常（100 分）、待关注（60 分）或异常（20 分），再取各项平均得到 0~100 分的健康分。分数越高长势越好；折线断点表示当天未录入指标。
          </p>
        </template>
      </n-spin>
    </n-card>

    <!-- 指标录入弹窗：复用 PRD 5.3.3 合法区间，同一天再次录入覆盖当日记录 -->
    <n-modal
      v-model:show="metricModalVisible"
      preset="card"
      title="录入养护指标"
      :bordered="false"
      style="width: 560px; max-width: 94vw"
    >
      <n-form label-placement="top">
        <div class="metric-grid">
          <n-form-item v-for="field in METRIC_FIELDS" :key="field.key">
            <template #label>
              {{ field.label }}<span v-if="field.unit">（{{ field.unit }}）</span>
            </template>
            <n-input-number
              v-model:value="metricForm[field.key]"
              :min="field.min"
              :max="field.max"
              :precision="field.precision"
              :placeholder="field.placeholder"
              clearable
              style="width: 100%"
            />
          </n-form-item>
        </div>

        <n-form-item label="指标日期">
          <n-date-picker
            v-model:value="metricForm.recordDate"
            type="date"
            :clearable="false"
            :is-date-disabled="isDateDisabled"
            style="width: 100%"
          />
        </n-form-item>

        <p class="metric-tip">
          同一天重复录入会覆盖当日指标；长势与光照统计基于这里的指标数据。
        </p>
      </n-form>

      <template #footer>
        <div class="modal-footer">
          <n-button @click="metricModalVisible = false">取消</n-button>
          <n-button type="primary" :loading="metricSubmitting" @click="submitMetric">保存</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.stats-page {
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

.filter-card,
.chart-card {
  border-radius: 12px;
}

.filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px 20px;
}

.filter-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.filter-label {
  flex: none;
  font-size: 13px;
  color: #6b7a6b;
}

.plant-select {
  width: 180px;
}

.filter-actions {
  margin-left: auto;
}

.chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.chart-title {
  font-size: 16px;
  font-weight: 600;
  color: #2d3a2d;
}

.chart {
  width: 100%;
}

.empty-block {
  padding: 48px 0;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.summary-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  border-radius: 10px;
  background: #f5f8f3;
}

.summary-label {
  font-size: 12px;
  color: #7a8a7a;
}

.summary-value {
  font-size: 20px;
  font-weight: 600;
  color: #3f8f47;
  word-break: break-all;
}

.summary-unit {
  margin-left: 2px;
  font-size: 12px;
  font-weight: 400;
  color: #7a8a7a;
}

.chart-note {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.6;
  color: #9aa89a;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
}

.metric-tip {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: #9aa89a;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

@media (max-width: 768px) {
  .filter-bar {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }

  .filter-item {
    justify-content: space-between;
  }

  .plant-select {
    flex: 1;
    width: auto;
  }

  .filter-actions {
    margin-left: 0;
  }

  .filter-actions :deep(.n-button) {
    width: 100%;
  }

  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .metric-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>