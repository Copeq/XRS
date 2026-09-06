<script setup lang="ts">
// Vue 壳内的「设置」视图：用隔离 iframe 加载原有独立设置页
// （/settings?standalone=1）。旧页功能 100% 保留，导航已统一到新壳。
const standaloneUrl = "/settings?standalone=1";
</script>

<template>
  <div class="settings-view">
    <iframe
      :src="standaloneUrl"
      class="settings-frame"
      title="设置"
      referrerpolicy="same-origin"
    />
  </div>
</template>

<style scoped>
.settings-view {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 12px 14px 14px;
}

.settings-frame {
  flex: 1;
  min-height: 520px;
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--card);
}
</style>
