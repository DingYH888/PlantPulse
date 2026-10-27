<script setup>
// 记录打卡页面（PRD 5.2 P2 植物记录入口 + 5.5 打卡业务规则）
// 功能点：
//   1. 下拉选择我名下的植物（GET /plants，数据隔离）
//   2. 新增植物档案（POST /plants）：名下无植物时的建档入口，避免卡住打卡
//   3. 新增打卡表单：类型（浇水/施肥/修剪/换盆/病虫害防治/其他）+ 次数 + 日期 + 多图上传
//   4. 提交按钮调用后端打卡接口（POST /checkins）
//   5. 历史打卡卡片列表：植物名称 + 日期 + 类型 + 图片缩略图（GET /checkins?record_date=）
//   6. 图片点击预览（n-image 内置大图预览，n-image-group 多图切换）
//   7. 提交成功后刷新列表
// 业务规则对齐后端：日期默认当天且禁未来（400）、重复打卡（409）、多图存 JSON 数组
import { computed, onMounted, reactive, ref } from 'vue'
import { useMessage } from 'naive-ui'

import { createPlant, getPlants } from '@/api/plants'
import { createCheckin, getCheckins } from '@/api/checkins'
import { uploadImage } from '@/api/upload'

const message = useMessage()

// ---- 常量：打卡类型（PRD care_type 枚举 → 中文展示与标签色）----
const CARE_TYPES = [
  { value: 'watering', label: '浇水', tag: 'success' },
  { value: 'fertilizing', label: '施肥', tag: 'warning' },
  { value: 'pruning', label: '修剪', tag: 'info' },
  { value: 'repotting', label: '换盆', tag: 'default' },
  { value: 'pest_control', label: '病虫害防治', tag: 'error' },
  { value: 'other', label: '其他', tag: 'default' },
]

// ---- 状态：植物下拉 ----
const plants = ref([]) // 我名下的植物
const plantLoading = ref(false)

// ---- 状态：新增植物弹窗 ----
const plantModalVisible = ref(false)
const plantFormRef = ref(null)
const plantSubmitting = ref(false)
const plantForm = reactive({
  name: '',
  species: '',
  location: '',
  plantedAt: null,
  notes: '',
})

// 新增植物校验：必填 + 禁止纯空白名称
const plantRules = {
  name: [
    { required: true, message: '请输入植物名称', trigger: ['input', 'blur'] },
    {
      validator: (_rule, value) => !!(value && value.trim()),
      message: '植物名称不能为空',
      trigger: ['input', 'blur'],
    },
  ],
}

// ---- 状态：打卡表单 ----
// 校验改为手动控制（validation-status + feedback），避免 NaiveUI 异步校验残留
const plantError = ref('')
const careTypeError = ref('')
const uploadRef = ref(null) // 图片上传：重置表单时清空已选文件
const formModel = reactive({
  plantId: null, // 选中的植物 id
  careType: null, // 打卡类型（不预设，避免重登后被误认为残留）
  measureValue: null, // 次数（如浇水次数、施肥次数），可空
  note: '', // 备注
  recordDate: null, // 日期选择器（timestamp），留空时后端默认当天
  images: [], // 上传成功后的图片 URL 数组（多图）
})
const submitting = ref(false)

// ---- 状态：历史打卡列表 ----
const records = ref([])
const recordsLoading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = 10
// 历史筛选日期：默认当天，与「选择植物」完全解耦
const historyDate = ref(Date.now())

// 当前筛选日期是否为今天（用于空状态文案）
const isHistoryToday = computed(() => formatDate(historyDate.value) === formatDate(Date.now()))

// 日期选择器禁止未来日期（PRD BR-04）
function isDateDisabled(ts) {
  return ts > Date.now()
}

// 清除植物选择错误（选择/新建后立即清除，不再依赖 FormItem 的异步校验）
function clearPlantError() {
  plantError.value = ''
}

// 加载植物下拉数据（功能点 1）
// selectPlantId：新建植物后指定选中项；其余场景不自动选中，保持表单空白
async function loadPlants(selectPlantId = null) {
  plantLoading.value = true
  try {
    const data = await getPlants({ page: 1, page_size: 50 })
    plants.value = data.items
    if (selectPlantId) {
      formModel.plantId = selectPlantId
      clearPlantError()
      loadRecords()
    }
  } catch (err) {
    message.error(err.message || '植物列表加载失败')
  } finally {
    plantLoading.value = false
  }
}

// 打开新增植物弹窗：先清空上次填写内容
function openPlantModal() {
  resetPlantForm()
  plantModalVisible.value = true
}

// 重置新增植物表单
function resetPlantForm() {
  plantForm.name = ''
  plantForm.species = ''
  plantForm.location = ''
  plantForm.plantedAt = null
  plantForm.notes = ''
  plantFormRef.value?.restoreValidation()
}

// 提交新增植物（功能点 2）：成功后刷新下拉并选中新植物
async function handleCreatePlant() {
  try {
    await plantFormRef.value?.validate()
  } catch {
    return // 校验失败，提示由表单内部展示
  }

  plantSubmitting.value = true
  try {
    const created = await createPlant({
      name: plantForm.name.trim(),
      species: plantForm.species.trim() || null,
      location: plantForm.location.trim() || null,
      planted_at: plantForm.plantedAt ? formatDate(plantForm.plantedAt) : null,
      notes: plantForm.notes.trim() || null,
    })
    message.success('植物添加成功')
    plantModalVisible.value = false
    await loadPlants(created.id)
  } catch (err) {
    message.error(err.message || '植物添加失败')
  } finally {
    plantSubmitting.value = false
  }
}

// 加载历史打卡（功能点 4）：按当前筛选日期查当前用户的全部植物记录
// 请求序号：快速切换日期时丢弃过期响应，避免旧请求覆盖新数据或卡住加载态
let recordsRequestId = 0

async function loadRecords() {
  const requestId = ++recordsRequestId
  recordsLoading.value = true
  try {
    const data = await getCheckins({
      record_date: formatDate(historyDate.value),
      page: page.value,
      page_size: pageSize,
    })
    if (requestId !== recordsRequestId) return
    records.value = page.value === 1 ? data.items : [...records.value, ...data.items]
    total.value = data.total
  } catch (err) {
    if (requestId !== recordsRequestId) return
    message.error(err.message || '打卡记录加载失败')
  } finally {
    if (requestId === recordsRequestId) recordsLoading.value = false
  }
}

// 切换植物：只清除选择错误，不再影响历史列表（历史展示当前用户当天全部记录）
function onPlantChange() {
  clearPlantError()
}

// 切换历史日期：重置分页并加载该日期的打卡记录
function onHistoryDateChange(value) {
  if (value) historyDate.value = value
  page.value = 1
  records.value = []
  total.value = 0
  loadRecords()
}

// 切换打卡类型：清除类型错误
function onCareTypeChange() {
  careTypeError.value = ''
}

// 加载更多历史记录
function loadMore() {
  page.value += 1
  loadRecords()
}

// 自定义上传：先调后端 /upload/image 拿 URL，再写入文件项供缩略图展示
async function handleCustomUpload({ file, onSuccess, onError }) {
  try {
    const url = await uploadImage(file.file)
    file.url = url // 供 n-upload 列表缩略图直接展示
    formModel.images.push(url) // 收集多图 URL，随打卡请求提交
    onSuccess(url)
  } catch (err) {
    message.error(err.message || '图片上传失败')
    onError(err)
  }
}

// 同步图片数组：删除已上传文件时从 images 中移除（避免提交残留 URL）
function onUploadChange({ fileList }) {
  const finishedUrls = fileList
    .filter((f) => f.status === 'finished' && f.url)
    .map((f) => f.url)
  formModel.images = finishedUrls
}

// 格式化日期：timestamp → YYYY-MM-DD（后端 DATE 字段格式）
function formatDate(ts) {
  const d = new Date(ts)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

// 提交打卡（功能点 3）
async function handleSubmit() {
  // 手动校验：只校验真正必填的两项，错误文案由模板 feedback 展示
  plantError.value = formModel.plantId ? '' : '请选择植物'
  careTypeError.value = formModel.careType ? '' : '请选择打卡类型'
  if (plantError.value || careTypeError.value) return

  submitting.value = true
  try {
    // 次数并入备注内容（PRD 打卡仅有 content 字段承载备注）
    const contentParts = []
    if (formModel.note.trim()) contentParts.push(formModel.note.trim())
    if (formModel.measureValue !== null && formModel.measureValue !== undefined) {
      contentParts.push(`次数：${formModel.measureValue}`)
    }

    await createCheckin({
      plant_id: formModel.plantId,
      care_type: formModel.careType,
      content: contentParts.join('；') || null,
      record_date: formModel.recordDate ? formatDate(formModel.recordDate) : null,
      image_urls: formModel.images.length ? formModel.images : null,
    })

    message.success('打卡成功')
    // 提交成功后定位到该记录所属日期，并刷新当天全部历史
    page.value = 1
    historyDate.value = formModel.recordDate || Date.now()
    records.value = []
    await loadRecords()
    resetForm()
  } catch (err) {
    message.error(err.message || '打卡失败')
  } finally {
    submitting.value = false
  }
}

// 重置表单：类型/次数/备注/图片/日期清空（植物选择保留，便于继续查看该植物历史）
function resetForm() {
  formModel.careType = null
  formModel.measureValue = null
  formModel.note = ''
  formModel.recordDate = null
  formModel.images = []
  plantError.value = ''
  careTypeError.value = ''
  uploadRef.value?.clear()
}

// 页面进入时重置为全新表单：退出登录后重新登录不残留上次填写内容
function initForm() {
  formModel.plantId = null
  resetForm()
}

onMounted(() => {
  initForm()
  loadPlants()
  loadRecords() // 默认展示当前用户今天的全部打卡记录
})
</script>

<template>
  <div class="record-page">
    <h2 class="page-title">记录打卡</h2>
    <p class="page-sub">为它浇一次水、修一片叶，记下这份小小的陪伴；这些点滴也会让 AI 更懂你的植物。</p>

    <!-- 新增打卡表单卡片 -->
    <n-card class="block-card" title="新增打卡">
      <n-form :model="formModel" label-placement="left" label-width="72">
        <n-form-item
          label="植物"
          :validation-status="plantError ? 'error' : undefined"
          :feedback="plantError"
        >
          <div class="plant-field">
            <div class="plant-picker">
              <n-select
                v-model:value="formModel.plantId"
                :options="plants.map((p) => ({ label: p.name, value: p.id }))"
                :loading="plantLoading"
                placeholder="选择我名下的植物"
                clearable
                @change="onPlantChange"
              />
              <n-button size="small" type="primary" secondary @click="openPlantModal">新增植物</n-button>
            </div>
            <!-- 名下无植物：明确引导先建档，否则打卡无法提交 -->
            <span v-if="!plantLoading && plants.length === 0" class="plant-empty-tip">
              你还没有植物档案，先添加一株再开始记录
            </span>
          </div>
        </n-form-item>

        <n-form-item
          label="打卡类型"
          :validation-status="careTypeError ? 'error' : undefined"
          :feedback="careTypeError"
        >
          <n-select
            v-model:value="formModel.careType"
            :options="CARE_TYPES"
            placeholder="选择打卡类型"
            @change="onCareTypeChange"
          />
        </n-form-item>

        <n-form-item label="次数">
          <n-input-number
            v-model:value="formModel.measureValue"
            placeholder="可选，如：2 次"
            :min="1"
            :max="100000"
            :input-props="{ autocomplete: 'off' }"
          />
        </n-form-item>

        <n-form-item label="日期">
          <n-date-picker
            v-model:value="formModel.recordDate"
            type="date"
            placeholder="默认为今天"
            :is-date-disabled="isDateDisabled"
            clearable
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
          <span class="upload-tip">支持 jpg/png/webp，单张 ≤5MB，最多 5 张</span>
        </n-form-item>

        <n-form-item label="备注">
          <n-input
            v-model:value="formModel.note"
            type="textarea"
            placeholder="养护细节，如：浇水 500ml、施肥 10g"
            maxlength="512"
            :input-props="{ autocomplete: 'off' }"
          />
        </n-form-item>

        <n-form-item>
          <n-button type="primary" :loading="submitting" @click="handleSubmit">
            提交打卡
          </n-button>
        </n-form-item>
      </n-form>
    </n-card>

    <!-- 历史打卡列表卡片 -->
    <n-card class="block-card" title="历史打卡">
      <template #header-extra>
        <div class="history-tools">
          <!-- 历史筛选日期：默认当天，可切换查看任意历史日期（禁止未来） -->
          <n-date-picker
            v-model:value="historyDate"
            type="date"
            size="small"
            :clearable="false"
            :is-date-disabled="isDateDisabled"
            style="width: 150px"
            @change="onHistoryDateChange"
          />
          <span class="total-tip">共 {{ total }} 条</span>
        </div>
      </template>

      <!-- NaiveUI Spin 2.x 用 show 控制加载态；loading 不是 prop，会导致永远转圈 -->
      <n-spin :show="recordsLoading">
        <div v-if="records.length === 0" class="empty-block">
          <n-empty :description="isHistoryToday ? '今天还没有打卡记录，快记录第一次养护吧' : '这一天还没有打卡记录'" />
        </div>

        <!-- 记录卡片：植物名称 + 日期 + 类型标签 + 备注 + 图片缩略图（点击预览） -->
        <div v-else class="record-list">
          <n-card v-for="record in records" :key="record.id" class="record-item" size="small">
            <div class="record-head">
              <div class="record-tags">
                <n-tag size="small" type="default" :bordered="false">
                  {{ record.plant_name || `植物#${record.plant_id}` }}
                </n-tag>
                <n-tag :type="CARE_TYPES.find((t) => t.value === record.care_type)?.tag || 'default'" size="small">
                  {{ CARE_TYPES.find((t) => t.value === record.care_type)?.label || record.care_type }}
                </n-tag>
              </div>
              <span class="record-date">{{ record.record_date }}</span>
            </div>
            <p v-if="record.content" class="record-content">{{ record.content }}</p>
            <!-- 多图缩略图：n-image-group 支持点击放大与组内切换预览 -->
            <n-image-group v-if="record.images.length" class="record-images">
              <n-image
                v-for="img in record.images"
                :key="img"
                :src="img"
                width="72"
                height="72"
                object-fit="cover"
                class="record-thumb"
              />
            </n-image-group>
          </n-card>

          <!-- 加载更多 -->
          <div v-if="records.length < total" class="load-more">
            <n-button size="small" quaternary @click="loadMore">加载更多（{{ records.length }}/{{ total }}）</n-button>
          </div>
        </div>
      </n-spin>
    </n-card>

    <!-- 新增植物弹窗：手动建档，AI 识别后续接入预填 -->
    <n-modal
      v-model:show="plantModalVisible"
      preset="card"
      title="添加植物"
      :bordered="false"
      style="width: 480px"
    >
      <n-form ref="plantFormRef" :model="plantForm" :rules="plantRules" label-placement="left" label-width="80">
        <n-form-item label="名称" path="name">
          <n-input v-model:value="plantForm.name" placeholder="如：绿萝、发财树" maxlength="64" show-count />
        </n-form-item>
        <n-form-item label="品种">
          <n-input v-model:value="plantForm.species" placeholder="选填，如：黄金葛" maxlength="64" />
        </n-form-item>
        <n-form-item label="摆放位置">
          <n-input v-model:value="plantForm.location" placeholder="选填，如：阳台 / 客厅" maxlength="64" />
        </n-form-item>
        <n-form-item label="种植日期">
          <n-date-picker
            v-model:value="plantForm.plantedAt"
            type="date"
            :is-date-disabled="isDateDisabled"
            clearable
            style="width: 100%"
          />
        </n-form-item>
        <n-form-item label="备注">
          <n-input
            v-model:value="plantForm.notes"
            type="textarea"
            placeholder="选填，如：喜阴、每周浇水一次"
            maxlength="512"
          />
        </n-form-item>
      </n-form>
      <template #footer>
        <div class="modal-footer">
          <n-button @click="plantModalVisible = false">取消</n-button>
          <n-button type="primary" :loading="plantSubmitting" @click="handleCreatePlant">保存</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.record-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-title {
  font-size: 22px;
  color: #2d3a2d;
}

.page-sub {
  font-size: 13px;
  color: #7a8a7a;
  margin-top: 4px;
}

.block-card {
  border-radius: 12px;
}

.upload-tip {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: #9aa89a;
}

.plant-field {
  width: 100%;
}

.plant-picker {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.plant-picker :deep(.n-select) {
  flex: 1;
}

.plant-empty-tip {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: #b38a3c;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.empty-block {
  padding: 24px 0;
}

.record-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.record-item {
  border-radius: 10px;
}

.record-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.history-tools {
  display: flex;
  align-items: center;
  gap: 10px;
}

.record-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.record-date {
  font-size: 13px;
  color: #7a8a7a;
}

.record-content {
  margin-top: 8px;
  font-size: 14px;
  color: #3c4a3c;
  white-space: pre-wrap;
  word-break: break-all;
}

.record-images {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.record-thumb {
  border-radius: 6px;
  cursor: zoom-in;
}

.load-more {
  text-align: center;
}

.total-tip {
  font-size: 13px;
  color: #7a8a7a;
}
</style>