<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useToastStore } from '@/stores/toast'
import AppIcon from '@/components/AppIcon.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const toast = useToastStore()

const form = reactive({ username: 'admin', password: 'admin123' })
const loading = ref(false)
const error = ref('')

const demoAccounts = [
  { username: 'admin', password: 'admin123', label: '系统管理员', desc: '全部权限' },
  { username: 'operator', password: 'operator123', label: '运维工程师', desc: '节点与指令' },
  { username: 'viewer', password: 'viewer123', label: '只读访客', desc: '仅查看数据' }
]

function fill(account) {
  form.username = account.username
  form.password = account.password
}

async function submit() {
  if (!form.username || !form.password) {
    error.value = '请输入用户名与密码'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const user = await userStore.login(form.username.trim(), form.password)
    toast.success(`欢迎回来，${user.real_name || user.username}`)
    router.push(route.query.redirect || { name: 'dashboard' })
  } catch (e) {
    error.value = e.message || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login">
    <!-- 左侧品牌展示 -->
    <section class="brand-side">
      <div class="brand-inner">
        <div class="logo-row">
          <svg viewBox="0 0 48 48" width="46" height="46">
            <circle cx="24" cy="24" r="4.4" style="fill: var(--login-accent)" />
            <circle cx="24" cy="24" r="9.6" fill="none" style="stroke: var(--login-accent)" stroke-opacity="0.6" stroke-width="2.4" />
            <circle cx="24" cy="24" r="15.5" fill="none" stroke="#FFFFFF" stroke-opacity="0.34" stroke-width="2.4" />
            <circle cx="24" cy="8.5" r="2.9" fill="#FFFFFF" />
            <circle cx="24" cy="39.5" r="2.9" fill="#FFFFFF" />
            <circle cx="9" cy="24" r="2.9" fill="#FFFFFF" opacity="0.78" />
            <circle cx="39" cy="24" r="2.9" fill="#FFFFFF" opacity="0.78" />
          </svg>
          <div>
            <h1>NovaEdge</h1>
            <p>边缘智算管理平台</p>
          </div>
        </div>

        <h2 class="headline">
          边缘计算节点的<br />统一接入 · 数据汇聚 · 远程运维
        </h2>
        <p class="sub">
          面向树莓派、香橙派、Jetson 等边缘算力节点，
          提供传感器时序数据接入、图像与视频资产归档、阈值告警与下行指令闭环。
        </p>

        <ul class="feature-list">
          <li>
            <AppIcon name="radio" :size="17" />
            <div>
              <strong>多协议接入</strong>
              <span>MQTT 遥测订阅 + HTTP 分片上传，双通道互备</span>
            </div>
          </li>
          <li>
            <AppIcon name="database" :size="17" />
            <div>
              <strong>三类数据统一建模</strong>
              <span>时序遥测 / 图片 / 视频，元数据与数据分离存储</span>
            </div>
          </li>
          <li>
            <AppIcon name="shield" :size="17" />
            <div>
              <strong>设备级安全凭证</strong>
              <span>节点密钥独立于用户体系，支持一键重置与轮换</span>
            </div>
          </li>
          <li>
            <AppIcon name="zap" :size="17" />
            <div>
              <strong>实时与离线兼顾</strong>
              <span>SSE 实时推送，节点断网自动缓存补传</span>
            </div>
          </li>
        </ul>

        <div class="metrics-row">
          <div><strong>3</strong><span>类数据通道</span></div>
          <div><strong>17</strong><span>张业务数据表</span></div>
          <div><strong>2</strong><span>数据库引擎兼容</span></div>
        </div>
      </div>
    </section>

    <!-- 右侧登录表单 -->
    <section class="form-side">
      <div class="form-card">
        <h3>登录控制台</h3>
        <p class="muted small mt-6">请输入平台账号以访问节点管理功能</p>

        <form class="mt-16" @submit.prevent="submit">
          <div class="field">
            <label class="field-label">用户名</label>
            <input v-model="form.username" class="input" autocomplete="username" placeholder="请输入用户名" />
          </div>
          <div class="field mt-10">
            <label class="field-label">密码</label>
            <input
              v-model="form.password"
              class="input"
              type="password"
              autocomplete="current-password"
              placeholder="请输入密码"
            />
          </div>

          <div v-if="error" class="error-tip">
            <AppIcon name="x-circle" :size="15" />
            {{ error }}
          </div>

          <button class="btn btn-primary btn-block mt-16" type="submit" :disabled="loading">
            <span v-if="loading" class="spin" style="width: 14px; height: 14px; border-width: 2px; border-top-color: #fff; border-color: rgba(255,255,255,.4); border-top-color: #fff" />
            {{ loading ? '正在登录...' : '登 录' }}
          </button>
        </form>

        <div class="demo">
          <div class="demo-title">演示账号（点击快速填充）</div>
          <div class="demo-list">
            <button
              v-for="account in demoAccounts"
              :key="account.username"
              class="demo-item"
              :class="{ active: form.username === account.username }"
              @click="fill(account)"
            >
              <div class="demo-role">{{ account.label }}</div>
              <div class="demo-name mono">{{ account.username }} / {{ account.password }}</div>
              <div class="demo-desc">{{ account.desc }}</div>
            </button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.login { display: flex; min-height: 100vh; }

/* ------------------------------- 左侧 ------------------------------- */
.brand-side {
  flex: 1.15; min-width: 0; position: relative; overflow: hidden;
  background: var(--login-bg);
  color: #EAF3FB;
  display: flex; align-items: center;
}
.brand-side::before {
  content: ''; position: absolute; inset: 0;
  background-image:
    radial-gradient(circle at 82% 18%, var(--login-glow-1), transparent 42%),
    radial-gradient(circle at 12% 82%, var(--login-glow-2), transparent 46%);
}
.brand-side::after {
  content: ''; position: absolute; inset: 0; opacity: 0.16;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.32) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.32) 1px, transparent 1px);
  background-size: 52px 52px;
  mask-image: radial-gradient(circle at 50% 45%, #000 30%, transparent 78%);
}
.brand-inner { position: relative; z-index: 1; padding: 52px 60px; max-width: 620px; }
.logo-row { display: flex; align-items: center; gap: 14px; }
.logo-row h1 { margin: 0; font-size: 25px; letter-spacing: 0.6px; }
.logo-row p { margin: 2px 0 0; font-size: 12.5px; color: rgba(200, 221, 241, 0.85); }

.headline { margin: 40px 0 0; font-size: 29px; line-height: 1.42; font-weight: 600; letter-spacing: 0.4px; }
.sub { margin: 16px 0 0; font-size: 13.5px; line-height: 1.85; color: rgba(200, 221, 241, 0.82); }

.feature-list { list-style: none; margin: 32px 0 0; padding: 0; display: grid; gap: 14px; }
.feature-list li {
  display: flex; gap: 12px; align-items: flex-start;
  padding: 12px 14px; border-radius: 11px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--login-accent);
}
.feature-list strong { display: block; font-size: 13.5px; color: #fff; font-weight: 600; }
.feature-list span { display: block; font-size: 12px; color: rgba(200, 221, 241, 0.78); margin-top: 2px; line-height: 1.55; }

.metrics-row {
  display: flex; gap: 34px; margin-top: 36px;
  padding-top: 24px; border-top: 1px solid rgba(255, 255, 255, 0.12);
}
.metrics-row strong { display: block; font-size: 24px; color: var(--login-accent); font-weight: 600; }
.metrics-row span { font-size: 12px; color: rgba(200, 221, 241, 0.75); }

/* ------------------------------- 右侧 ------------------------------- */
.form-side {
  flex: 1; min-width: 420px;
  display: flex; align-items: center; justify-content: center;
  padding: 40px; background: var(--c-bg);
}
.form-card {
  width: 100%; max-width: 390px;
  padding: 30px 32px 28px;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: 16px;
  box-shadow: var(--shadow-lg);
}
.form-card h3 { margin: 0; font-size: 20px; font-weight: 600; }

.error-tip {
  display: flex; align-items: center; gap: 7px;
  margin-top: 14px; padding: 9px 12px;
  border-radius: 8px; background: var(--c-red-100); color: #B33131; font-size: 12.5px;
}

.demo { margin-top: 24px; padding-top: 18px; border-top: 1px dashed var(--c-border); }
.demo-title { font-size: 12px; color: var(--c-text-3); margin-bottom: 9px; }
.demo-list { display: flex; flex-direction: column; gap: 7px; }
.demo-item {
  text-align: left; padding: 8px 11px;
  border: 1px solid var(--c-border); border-radius: 9px;
  background: var(--c-surface-2); cursor: pointer;
  font-family: inherit; transition: all 0.15s;
}
.demo-item:hover { border-color: var(--c-primary-300); background: var(--c-primary-50); }
.demo-item.active { border-color: var(--c-primary); background: var(--c-primary-50); }
.demo-role { font-size: 12.5px; font-weight: 600; color: var(--c-text); }
.demo-name { font-size: 11.5px; color: var(--c-primary); margin: 1px 0; }
.demo-desc { font-size: 11px; color: var(--c-text-3); }

@media (max-width: 1000px) {
  .brand-side { display: none; }
  .form-side { min-width: 0; }
}
</style>
