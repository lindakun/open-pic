<script setup lang="ts">
/**
 * 根组件：外壳 + 全局轻提示
 */
import AppShell from '@/components/AppShell.vue'
import MLToast from '@/components/MLToast.vue'
import { useToast } from '@/composables/useToast'

const { toasts, dismiss } = useToast()
</script>

<template>
  <AppShell />
  <MLToast :toasts="toasts" @dismiss="dismiss" />
</template>
