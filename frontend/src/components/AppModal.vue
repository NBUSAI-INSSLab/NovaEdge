<script setup>
import AppIcon from './AppIcon.vue'
import { useToastStore } from '@/stores/toast'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
  size: { type: String, default: '' },       // '' | lg | xl
  width: { type: String, default: '' },      // 自定义宽度，如 '560px'，优先于 size
  confirmText: { type: String, default: '确定' },
  cancelText: { type: String, default: '取消' },
  loading: { type: Boolean, default: false },
  hideFooter: { type: Boolean, default: false },
  hideConfirm: { type: Boolean, default: false },
  wide: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'confirm', 'close'])

function close() {
  emit('update:modelValue', false)
  emit('close')
}
</script>

<template>
  <teleport to="body">
    <div v-if="modelValue" class="overlay" @click.self="close">
      <div class="modal" :class="size" :style="width ? { width, maxWidth: '94vw' } : null">
        <div class="modal-head">
          <div class="modal-title">{{ title }}</div>
          <button class="btn btn-ghost btn-icon btn-sm" @click="close">
            <AppIcon name="close" :size="16" />
          </button>
        </div>
        <div class="modal-body">
          <slot />
        </div>
        <div v-if="!hideFooter" class="modal-foot">
          <slot name="footer-prepend" />
          <slot name="footer">
            <button class="btn" @click="close">{{ cancelText }}</button>
            <button v-if="!hideConfirm" class="btn btn-primary" :disabled="loading" @click="emit('confirm')">
              <span v-if="loading" class="spin" style="width: 14px; height: 14px; border-width: 2px" />
              {{ confirmText }}
            </button>
          </slot>
        </div>
      </div>
    </div>
  </teleport>
</template>
