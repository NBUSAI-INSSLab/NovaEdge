<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, fmtTime, relativeTime } from '@/api'
import { useUserStore } from '@/stores/user'
import { useToastStore } from '@/stores/toast'
import DataTable from '@/components/DataTable.vue'
import AppModal from '@/components/AppModal.vue'
import AppIcon from '@/components/AppIcon.vue'

const userStore = useUserStore()
const toast = useToastStore()

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const roles = ref([])
const filters = reactive({ role: '', keyword: '' })

const showForm = ref(false)
const editing = ref(null)
const submitting = ref(false)
const form = reactive({
  username: '', password: '', real_name: '', role: 'viewer',
  email: '', phone: '', department: '', is_active: true
})

const showPassword = ref(false)
const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })
const pwdSubmitting = ref(false)

const columns = [
  { key: 'username', label: '账号' },
  { key: 'real_name', label: '姓名', width: '110px' },
  { key: 'role', label: '角色', width: '120px' },
  { key: 'department', label: '部门', width: '150px' },
  { key: 'contact', label: '联系方式', width: '210px' },
  { key: 'is_active', label: '状态', width: '90px' },
  { key: 'last_login', label: '最近登录', width: '170px' },
  { key: 'actions', label: '操作', width: '150px' }
]

const ROLE_TONE = { admin: 'tag-critical', operator: 'tag-primary', viewer: 'tag-teal' }

async function load() {
  loading.value = true
  try {
    const res = await api.users.list({
      page: page.value,
      page_size: pageSize.value,
      role: filters.role || undefined,
      keyword: filters.keyword || undefined
    })
    if (res.code === 0) {
      rows.value = res.data.items
      total.value = res.data.total
    }
  } finally {
    loading.value = false
  }
}

function openForm(user = null) {
  editing.value = user
  if (user) {
    Object.assign(form, {
      username: user.username, password: '', real_name: user.real_name,
      role: user.role, email: user.email, phone: user.phone,
      department: user.department, is_active: user.is_active
    })
  } else {
    Object.assign(form, {
      username: '', password: '', real_name: '', role: 'viewer',
      email: '', phone: '', department: '', is_active: true
    })
  }
  showForm.value = true
}

async function submit() {
  if (!form.username.trim()) { toast.warning('请填写账号'); return }
  if (!editing.value && form.password.length < 6) { toast.warning('密码至少 6 位'); return }
  submitting.value = true
  const payload = { ...form }
  if (editing.value && !payload.password) delete payload.password
  try {
    const res = editing.value
      ? await api.users.update(editing.value.id, payload)
      : await api.users.create(payload)
    if (res.code === 0) {
      toast.success(res.message)
      showForm.value = false
      load()
    } else toast.error(res.message)
  } finally {
    submitting.value = false
  }
}

async function remove(user) {
  if (!window.confirm(`确认删除用户「${user.real_name || user.username}」？`)) return
  const res = await api.users.remove(user.id)
  if (res.code === 0) { toast.success('用户已删除'); load() } else toast.error(res.message)
}

async function submitPassword() {
  if (pwdForm.new_password.length < 6) { toast.warning('新密码至少 6 位'); return }
  if (pwdForm.new_password !== pwdForm.confirm) { toast.warning('两次输入的新密码不一致'); return }
  pwdSubmitting.value = true
  try {
    const res = await api.auth.changePassword({
      old_password: pwdForm.old_password,
      new_password: pwdForm.new_password
    })
    if (res.code === 0) {
      toast.success('密码修改成功，请牢记新密码')
      showPassword.value = false
      pwdForm.old_password = ''
      pwdForm.new_password = ''
      pwdForm.confirm = ''
    } else toast.error(res.message)
  } finally {
    pwdSubmitting.value = false
  }
}

const roleStats = computed(() => {
  const counters = { admin: 0, operator: 0, viewer: 0 }
  rows.value.forEach((user) => { counters[user.role] = (counters[user.role] || 0) + 1 })
  return counters
})

onMounted(async () => {
  const res = await api.users.roles()
  if (res.code === 0) roles.value = res.data
  load()
})
</script>

<template>
  <div>
    <!-- 概览 -->
    <div class="grid-4 mb-16">
      <div class="stat tone-primary">
        <div class="stat-icon"><AppIcon name="users" :size="19" /></div>
        <div><div class="stat-label">平台用户</div><div class="stat-value">{{ total }}</div></div>
      </div>
      <div class="stat tone-red">
        <div class="stat-icon"><AppIcon name="shield" :size="19" /></div>
        <div><div class="stat-label">系统管理员</div><div class="stat-value">{{ roleStats.admin }}</div></div>
      </div>
      <div class="stat tone-teal">
        <div class="stat-icon"><AppIcon name="sliders" :size="19" /></div>
        <div><div class="stat-label">运维工程师</div><div class="stat-value">{{ roleStats.operator }}</div></div>
      </div>
      <div class="stat tone-amber">
        <div class="stat-icon"><AppIcon name="eye" :size="19" /></div>
        <div><div class="stat-label">只读访客</div><div class="stat-value">{{ roleStats.viewer }}</div></div>
      </div>
    </div>

    <!-- 权限说明 -->
    <div class="card mb-16">
      <div class="card-body tight">
        <div class="perm-row">
          <div class="perm-item">
            <span class="tag tag-critical">系统管理员</span>
            <span class="small muted">全部权限：节点增删、用户管理、系统参数、数据清理</span>
          </div>
          <div class="perm-item">
            <span class="tag tag-primary">运维工程师</span>
            <span class="small muted">节点维护、指令下发、告警处置、媒体删除、物模型维护</span>
          </div>
          <div class="perm-item">
            <span class="tag tag-teal">只读访客</span>
            <span class="small muted">仅可查看节点、数据、媒体、告警与统计，不能修改任何配置</span>
          </div>
          <button class="btn btn-sm" @click="showPassword = true">
            <AppIcon name="lock" :size="14" />修改我的密码
          </button>
        </div>
      </div>
    </div>

    <!-- 用户列表 -->
    <div class="card">
      <div class="card-head">
        <div class="card-title"><i class="bar" />用户与权限</div>
        <div class="row gap-8">
          <select v-model="filters.role" class="select" style="width: 130px" @change="page = 1; load()">
            <option value="">全部角色</option>
            <option v-for="item in roles" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
          <div class="search-box">
            <AppIcon name="search" :size="15" />
            <input v-model="filters.keyword" class="search-input" placeholder="搜索账号或姓名" @keyup.enter="page = 1; load()" />
          </div>
          <button class="btn btn-sm" @click="load"><AppIcon name="refresh" :size="14" />刷新</button>
          <button v-if="userStore.isAdmin" class="btn btn-sm btn-primary" @click="openForm()">
            <AppIcon name="plus" :size="14" />新建用户
          </button>
        </div>
      </div>
      <div class="card-body flush">
        <DataTable
          v-model:page="page"
          :columns="columns"
          :rows="rows"
          :loading="loading"
          :total="total"
          :page-size="pageSize"
          min-width="1080px"
          empty-text="暂无用户"
          @update:page="load"
        >
          <template #cell-username="{ row }">
            <div class="row gap-8">
              <div class="avatar-sm">{{ (row.real_name || row.username).slice(0, 1) }}</div>
              <div>
                <div class="small mono">{{ row.username }}</div>
                <div class="tiny muted-2">ID {{ row.id }}</div>
              </div>
            </div>
          </template>
          <template #cell-role="{ row }">
            <span class="tag" :class="ROLE_TONE[row.role]">{{ row.role_label }}</span>
          </template>
          <template #cell-department="{ row }"><span class="small">{{ row.department || '—' }}</span></template>
          <template #cell-contact="{ row }">
            <div class="tiny muted-2">{{ row.email || '无邮箱' }}</div>
            <div class="tiny muted-2">{{ row.phone || '无手机号' }}</div>
          </template>
          <template #cell-is_active="{ row }">
            <span class="tag" :class="row.is_active ? 'tag-online' : 'tag-offline'">{{ row.is_active ? '正常' : '已禁用' }}</span>
          </template>
          <template #cell-last_login="{ row }">
            <div class="small mono">{{ fmtTime(row.last_login_at) }}</div>
            <div class="tiny muted-2">{{ relativeTime(row.last_login_at) }}</div>
          </template>
          <template #cell-actions="{ row }">
            <div class="actions">
              <button v-if="userStore.isAdmin" class="btn btn-sm" @click="openForm(row)">
                <AppIcon name="edit" :size="13" />编辑
              </button>
              <button
                v-if="userStore.isAdmin && row.id !== userStore.profile?.id"
                class="btn btn-sm btn-danger"
                @click="remove(row)"
              ><AppIcon name="trash" :size="13" /></button>
              <span v-else-if="row.id === userStore.profile?.id" class="tag tag-primary">当前账号</span>
            </div>
          </template>
        </DataTable>
      </div>
    </div>

    <!-- 用户表单 -->
    <AppModal
      v-model="showForm"
      :title="editing ? `编辑用户 · ${editing.username}` : '新建平台用户'"
      size="lg"
      :loading="submitting"
      @confirm="submit"
    >
      <div class="form-grid">
        <div class="field">
          <label class="field-label">登录账号<span class="req">*</span></label>
          <input v-model="form.username" class="input" :disabled="!!editing" placeholder="英文与数字组合" />
        </div>
        <div class="field">
          <label class="field-label">
            登录密码{{ editing ? '（留空则不修改）' : '' }}<span v-if="!editing" class="req">*</span>
          </label>
          <input v-model="form.password" class="input" type="password" placeholder="至少 6 位" />
        </div>
        <div class="field">
          <label class="field-label">姓名</label>
          <input v-model="form.real_name" class="input" placeholder="真实姓名或昵称" />
        </div>
        <div class="field">
          <label class="field-label">角色<span class="req">*</span></label>
          <select v-model="form.role" class="select">
            <option v-for="item in roles" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </div>
        <div class="field">
          <label class="field-label">所属部门</label>
          <input v-model="form.department" class="input" placeholder="如 信息化中心" />
        </div>
        <div class="field">
          <label class="field-label">账号状态</label>
          <select v-model="form.is_active" class="select">
            <option :value="true">正常启用</option>
            <option :value="false">禁用</option>
          </select>
        </div>
        <div class="field">
          <label class="field-label">邮箱</label>
          <input v-model="form.email" class="input" type="email" placeholder="选填" />
        </div>
        <div class="field">
          <label class="field-label">手机号</label>
          <input v-model="form.phone" class="input" placeholder="选填" />
        </div>
      </div>
    </AppModal>

    <!-- 修改密码 -->
    <AppModal v-model="showPassword" title="修改我的登录密码" :loading="pwdSubmitting" @confirm="submitPassword">
      <div class="field mb-10">
        <label class="field-label">原密码</label>
        <input v-model="pwdForm.old_password" class="input" type="password" />
      </div>
      <div class="field mb-10">
        <label class="field-label">新密码</label>
        <input v-model="pwdForm.new_password" class="input" type="password" placeholder="至少 6 位" />
      </div>
      <div class="field">
        <label class="field-label">确认新密码</label>
        <input v-model="pwdForm.confirm" class="input" type="password" />
      </div>
    </AppModal>
  </div>
</template>

<style scoped>
.stat {
  display: flex; align-items: center; gap: 13px;
  padding: 16px 18px; background: var(--c-surface);
  border: 1px solid var(--c-border); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}
.stat-icon {
  width: 40px; height: 40px; border-radius: 11px;
  display: flex; align-items: center; justify-content: center;
  color: var(--tone-color); background: var(--tone-bg);
}
.stat-label { font-size: 12.5px; color: var(--c-text-2); }
.stat-value { font-size: 23px; font-weight: 600; line-height: 1.2; }
.tone-primary { --tone-color: var(--c-primary); --tone-bg: var(--c-primary-100); }
.tone-red { --tone-color: var(--c-red); --tone-bg: var(--c-red-100); }
.tone-teal { --tone-color: var(--c-teal); --tone-bg: var(--c-teal-100); }
.tone-amber { --tone-color: var(--c-amber); --tone-bg: var(--c-amber-100); }

.perm-row { display: flex; align-items: center; gap: 22px; flex-wrap: wrap; }
.perm-item { display: flex; align-items: center; gap: 9px; }
.avatar-sm {
  width: 30px; height: 30px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  background: var(--c-primary-100); color: var(--c-primary-600);
  font-size: 13px; font-weight: 600;
}
.search-box {
  display: flex; align-items: center; gap: 7px;
  height: 30px; padding: 0 10px; min-width: 190px;
  border: 1px solid var(--c-border-strong); border-radius: var(--radius-sm);
  background: var(--c-surface); color: var(--c-text-3);
}
.search-box:focus-within { border-color: var(--c-primary); box-shadow: 0 0 0 3px var(--c-primary-100); }
.search-input { flex: 1; border: none; outline: none; background: transparent; font-family: inherit; font-size: 13px; min-width: 0; }
</style>
