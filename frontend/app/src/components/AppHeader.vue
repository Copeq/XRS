<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  VBadge,
  VBtn,
  VCard,
  VCardActions,
  VCardText,
  VChip,
  VDialog,
  VIcon,
  VList,
  VListItem,
  VListItemTitle,
  VMenu,
  VSlider,
  VSpacer,
  VSwitch,
  VTab,
  VTabs,
  VTextField,
  VToolbar,
  VToolbarTitle,
} from "vuetify/components";
import { postJson, pageFetch } from "../composables/pageApi";
import { useUiTheme } from "../composables/useUiTheme";
import type { HomeState } from "../composables/useLiveSocket";

type PageKey = "live" | "history" | "hardware" | "settings";
const props = defineProps<{ state: HomeState; page: PageKey }>();
const emit = defineEmits<{ (e: "set-page", p: PageKey): void }>();

const pageModel = computed({
  get: () => props.page,
  set: (v: unknown) => emit("set-page", String(v) as PageKey),
});

type MetaRecord = Record<string, unknown>;

const meta = computed<MetaRecord>(() => (props.state.meta ?? {}) as MetaRecord);

function sniffKind(): "ok" | "paused" | "error" | "warn" {
  const state = String(meta.value.sniff_state ?? "warn");
  if (state === "ok") return "ok";
  if (state === "paused") return "paused";
  if (state === "error") return "error";
  return "warn";
}
const sniffLabel = computed(() => {
  const m: Record<string, string> = { ok: "正常", paused: "暂停", error: "异常", warn: "警告" };
  return m[sniffKind()] ?? "警告";
});
const sniffBannerText = computed(() => {
  const kind = sniffKind();
  if (kind === "ok") return "";
  const msg = String(meta.value.sniff_msg ?? "");
  let tip = (kind === "error" ? "采集异常：" : "采集告警：") + (msg || "未知");
  const iface = String(meta.value.sniff_iface ?? "");
  if (iface) tip += ` [iface: ${iface}]`;
  const idle = Number(meta.value.sniff_idle_sec ?? 0);
  if (idle > 0) tip += ` (${Math.round(idle)}s)`;
  return tip;
});

const liveCount = computed(() => props.state.drones.filter((d) => !d.lost && !d.archived).length);
const lostCount = computed(() => props.state.drones.filter((d) => d.lost && !d.archived).length);
const totalCount = computed(() => props.state.drones.length);

function onOpenSimulation() {
  void openSim();
}

onMounted(() => {
  window.addEventListener("xrs:open-simulation", onOpenSimulation);
});

onBeforeUnmount(() => {
  window.removeEventListener("xrs:open-simulation", onOpenSimulation);
});

function openDji() {
  const url = String(meta.value.dji_lookup_url ?? "");
  if (!url) {
    window.alert("未配置 DJI 查询地址");
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

/* 更多菜单 */
const moreOpen = ref(false);
function navTo(href: string) {
  moreOpen.value = false;
  window.location.href = href;
}

function goHardware() {
  moreOpen.value = false;
  emit("set-page", "hardware");
}

/* 外观/背景主题 */
const themeOpen = ref(false);
const uiTheme = useUiTheme();
const urlDraft = ref<string>(uiTheme.state.url);
function openTheme() {
  urlDraft.value = uiTheme.state.url;
  themeOpen.value = true;
  moreOpen.value = false;
}
const themeEnabledModel = computed({
  get: () => uiTheme.state.enabled,
  set: (v: boolean) => uiTheme.setEnabled(!!v),
});
const themeBlurModel = computed({
  get: () => uiTheme.state.blur,
  set: (v: unknown) => uiTheme.setBlur(Number(v) || 0),
});
const themeOverlayModel = computed({
  get: () => uiTheme.state.overlay,
  set: (v: unknown) => uiTheme.setOverlay(Number(v) || 0),
});

/* 通知中心 */
interface NotifyItem {
  id?: number;
  text?: string;
  kind?: string;
  source?: string;
  ts?: number;
}
const notifyOpen = ref(false);
const notifyItems = ref<NotifyItem[]>([]);
const notifyBusy = ref(false);
const notifyMsg = ref("");

function notifyCount() {
  return notifyItems.value.length;
}
async function loadNotifications() {
  notifyBusy.value = true;
  notifyMsg.value = "";
  try {
    const d = (await pageFetch("/api/notifications?limit=200")) as Record<string, unknown>;
    const items = Array.isArray(d.items) ? (d.items as NotifyItem[]) : [];
    notifyItems.value = items.slice(0, 100);
  } catch (e) {
    notifyMsg.value = e instanceof Error ? e.message : String(e);
  } finally {
    notifyBusy.value = false;
  }
}
function onNotifyMenu(open: boolean) {
  if (open) void loadNotifications();
}
async function deleteNotify(id: unknown) {
  try {
    await postJson("/api/notifications/delete", { id });
    notifyItems.value = notifyItems.value.filter((x) => x.id !== id);
  } catch (e) {
    notifyMsg.value = e instanceof Error ? e.message : String(e);
  }
}
async function clearNotify() {
  try {
    await postJson("/api/notifications/clear", {});
    notifyItems.value = [];
  } catch (e) {
    notifyMsg.value = e instanceof Error ? e.message : String(e);
  }
}
function notifyTime(ts: unknown): string {
  if (typeof ts !== "number") return "-";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "-";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function notifyKind(item: NotifyItem): string {
  return String(item.kind ?? "info");
}

/* 模拟目标弹窗 */
interface SimForm {
  count: number;
  pattern: string;
  radius_m: number;
  speed_mps: number;
  altitude_m: number;
  duration_sec: number;
  center_lat?: number | null;
  center_lon?: number | null;
}
const simOpen = ref(false);
const simBusy = ref(false);
const simMsg = ref("");
const sim = ref<SimForm>({
  count: 3,
  pattern: "circle",
  radius_m: 500,
  speed_mps: 12,
  altitude_m: 120,
  duration_sec: 1800,
});
const simRunning = ref(false);

async function simStatus() {
  try {
    const d = (await pageFetch("/api/simulation/status")) as Record<string, unknown>;
    simRunning.value = Boolean(d.running);
    if (d.running && typeof d.count === "number") sim.value.count = d.count;
  } catch (_e) {
    /* ignore */
  }
}
function ensureBaseLatLon() {
  const m = meta.value;
  if (typeof m.base_lat === "number" && typeof m.base_lon === "number") {
    sim.value.center_lat = m.base_lat;
    sim.value.center_lon = m.base_lon;
  }
}
async function openSim() {
  simOpen.value = true;
  simMsg.value = "";
  ensureBaseLatLon();
  await simStatus();
}
async function simStart() {
  simBusy.value = true;
  simMsg.value = "";
  try {
    const d = (await postJson("/api/simulation/start", {
      transport: "memory",
      count: Number(sim.value.count || 3),
      pattern: sim.value.pattern,
      center_lat: (sim.value as unknown as Record<string, unknown>).center_lat ?? null,
      center_lon: (sim.value as unknown as Record<string, unknown>).center_lon ?? null,
      radius_m: Number(sim.value.radius_m || 500),
      speed_mps: Number(sim.value.speed_mps || 0),
      altitude_m: Number(sim.value.altitude_m || 120),
      duration_sec: Number(sim.value.duration_sec || 0),
    })) as Record<string, unknown>;
    if (d.ok === false) {
      simMsg.value = String(d.error ?? "启动失败");
    } else {
      simRunning.value = true;
      simMsg.value = `已启动 ${String(d.count ?? "")} 个内存目标`;
    }
  } catch (e) {
    simMsg.value = e instanceof Error ? e.message : String(e);
  } finally {
    simBusy.value = false;
  }
}
async function simStop() {
  simBusy.value = true;
  try {
    await postJson("/api/simulation/stop", {});
    simRunning.value = false;
    simMsg.value = "模拟目标已停止并清除";
  } catch (e) {
    simMsg.value = e instanceof Error ? e.message : String(e);
  } finally {
    simBusy.value = false;
  }
}

</script>

<template>
  <header class="app-header">
    <div class="header-main">
      <div class="brand">
        <h1>XRS</h1>
      </div>

      <div class="header-right">
        <button class="chip-btn" type="button" title="打开 DJI 机型查询" @click="openDji">DJI 查询</button>
        <span class="chip sniff" :class="sniffKind()">
          <i class="dot"></i>采集 {{ sniffLabel }}
        </span>
        <span class="chip"><b>实时</b> {{ liveCount }}</span>
        <span class="chip"><b>离线</b> {{ lostCount }}</span>
        <span class="chip"><b>总计</b> {{ totalCount }}</span>
        <span class="chip mono">更新 {{ state.ts || "--:--:--" }}</span>

        <button class="chip-btn" type="button" @click="openTheme">外观</button>

        <VMenu v-model="notifyOpen" location="bottom end" :close-on-content-click="false" :max-width="420" @update:model-value="onNotifyMenu">
          <template #activator="{ props: notifyActivator }">
            <VBtn v-bind="notifyActivator" variant="tonal" size="small" class="chip-gap">
              <VBadge :content="notifyCount()" :model-value="notifyCount() > 0" color="error" inline>
                <VIcon>mdi-bell-outline</VIcon>
              </VBadge>
              <span class="ms-1">通知</span>
            </VBtn>
          </template>
          <VCard max-width="420" max-height="62vh" class="d-flex flex-column">
            <VToolbar density="compact" color="transparent">
              <VToolbarTitle class="text-body-2">通知中心</VToolbarTitle>
              <VBtn variant="text" size="small" :disabled="notifyBusy" @click="loadNotifications">刷新</VBtn>
              <VBtn variant="text" size="small" @click="clearNotify">清空</VBtn>
            </VToolbar>
            <p v-if="notifyMsg" class="px-3 text-caption text-error mb-0">{{ notifyMsg }}</p>
            <VList density="compact" class="overflow-y-auto">
              <VListItem v-if="!notifyItems.length && !notifyBusy">
                <VListItemTitle class="text-caption text-medium-emphasis">暂无通知</VListItemTitle>
              </VListItem>
              <VListItem v-for="item in notifyItems" :key="item.id">
                <template #prepend>
                  <VChip
                    size="x-small"
                    variant="tonal"
                    label
                    :color="notifyKind(item) === 'error' ? 'error' : notifyKind(item) === 'warn' ? 'warning' : 'info'"
                  >{{ notifyKind(item) }}</VChip>
                </template>
                <VListItemTitle class="text-body-2 text-wrap">{{ item.text }}</VListItemTitle>
                <template #append>
                  <div class="d-flex align-center ga-2">
                    <span class="text-caption text-medium-emphasis text-nowrap">{{ notifyTime(item.ts) }}</span>
                    <VBtn icon="mdi-delete-outline" size="x-small" variant="text" @click="deleteNotify(item.id)" />
                  </div>
                </template>
              </VListItem>
            </VList>
          </VCard>
        </VMenu>

        <VMenu v-model="moreOpen" location="bottom end" :close-on-content-click="true">
          <template #activator="{ props: moreActivator }">
            <VBtn v-bind="moreActivator" variant="tonal" size="small" class="chip-gap">更多</VBtn>
          </template>
          <VList density="compact" min-width="190">
            <VListItem prepend-icon="mdi-crosshairs-gps" title="模拟目标" @click="moreOpen = false; openSim()" />
            <VListItem prepend-icon="mdi-text-box-outline" title="日志" @click="navTo('/logs')" />
            <VListItem prepend-icon="mdi-usb-flash-drive-outline" title="硬件助手" @click="goHardware" />
          </VList>
        </VMenu>
      </div>
    </div>

    <div class="banner-stack">
      <div v-if="sniffBannerText" class="banner" :class="sniffKind() === 'error' ? 'err' : 'warn'">
        {{ sniffBannerText }}
      </div>
    </div>

    <VTabs v-model="pageModel" color="primary" density="compact" class="app-tab-nav">
      <VTab value="live"><VIcon size="small" class="me-1">mdi-radar</VIcon>实时</VTab>
      <VTab value="history"><VIcon size="small" class="me-1">mdi-history</VIcon>历史记录</VTab>
      <VTab value="hardware"><VIcon size="small" class="me-1">mdi-router-wireless</VIcon>硬件助手</VTab>
      <VTab value="settings"><VIcon size="small" class="me-1">mdi-cog-outline</VIcon>设置</VTab>
    </VTabs>

    <!-- 模拟目标弹窗 -->
    <Teleport to="body">
      <div v-if="simOpen" class="modal-mask" @click.self="simOpen = false">
        <div class="modal">
          <div class="modal-head">
            <strong>模拟目标</strong>
            <span class="muted">仅驻留内存，不写入历史记录</span>
            <button class="banner-close" type="button" @click="simOpen = false">×</button>
          </div>
          <div class="modal-body">
            <label>数量 <input v-model.number="sim.count" type="number" min="1" max="100" /></label>
            <label>轨迹 <select v-model="sim.pattern">
              <option value="circle">圆形</option>
              <option value="line">直线</option>
              <option value="stationary">悬停</option>
            </select></label>
            <label>半径(m) <input v-model.number="sim.radius_m" type="number" /></label>
            <label>速度(m/s) <input v-model.number="sim.speed_mps" type="number" /></label>
            <label>高度(m) <input v-model.number="sim.altitude_m" type="number" /></label>
            <label>时长(s) <input v-model.number="sim.duration_sec" type="number" /></label>
          </div>
          <p class="sim-status" :class="{ running: simRunning }">
            {{ simMsg || (simRunning ? "运行中" : "空闲") }}
          </p>
          <div class="modal-foot">
            <button type="button" class="btn primary" :disabled="simBusy" @click="simStart">启动</button>
            <button type="button" class="btn" :disabled="simBusy || !simRunning" @click="simStop">停止</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 外观背景设置（Vuetify） -->
    <VDialog v-model="themeOpen" max-width="560">
      <VCard rounded="lg" class="theme-dialog">
        <VToolbar density="compact" color="transparent">
          <VToolbarTitle class="text-subtitle-1 font-weight-bold">外观背景</VToolbarTitle>
          <VSpacer />
          <VBtn icon="mdi-close" variant="text" size="small" @click="themeOpen = false" />
        </VToolbar>
        <VCardText>
          <VSwitch
            v-model="themeEnabledModel"
            color="primary"
            label="启用自定义背景"
            hide-details
            class="mb-3"
          />
          <div class="text-caption text-medium-emphasis mb-1">背景预设</div>
          <div class="d-flex flex-wrap ga-2 mb-3">
            <VBtn
              v-for="p in uiTheme.presets"
              :key="p.key"
              size="small"
              :variant="uiTheme.state.enabled && uiTheme.state.mode === 'preset' && uiTheme.state.preset === p.key ? 'flat' : 'tonal'"
              :color="uiTheme.state.enabled && uiTheme.state.mode === 'preset' && uiTheme.state.preset === p.key ? 'primary' : undefined"
              @click="uiTheme.setPreset(p.key)"
            >{{ p.label }}</VBtn>
          </div>
          <div class="text-caption text-medium-emphasis mb-1">自定义图片 URL</div>
          <div class="d-flex ga-2 mb-3">
            <VTextField
              v-model="urlDraft"
              density="compact"
              variant="outlined"
              placeholder="https://…/background.jpg"
              hide-details
              @keyup.enter="uiTheme.setUrl(urlDraft)"
            />
            <VBtn variant="tonal" color="primary" @click="uiTheme.setUrl(urlDraft)">应用</VBtn>
          </div>
          <VSlider
            v-model="themeBlurModel"
            color="primary"
            label="玻璃虚化"
            min="0"
            max="40"
            step="1"
            thumb-label="always"
            density="comfortable"
            hide-details
            class="mb-2"
          />
          <VSlider
            v-model="themeOverlayModel"
            color="primary"
            :label="`暗色遮罩 ${Math.round(uiTheme.state.overlay * 100)}%`"
            min="0"
            max="0.7"
            step="0.05"
            thumb-label="always"
            density="comfortable"
            hide-details
          />
        </VCardText>
        <VCardActions class="pa-4 pt-0">
          <VSpacer />
          <VBtn variant="tonal" @click="uiTheme.reset(); urlDraft = ''">恢复默认</VBtn>
          <VBtn color="primary" @click="themeOpen = false">完成</VBtn>
        </VCardActions>
      </VCard>
    </VDialog>
  </header>
</template>

<style scoped>
.app-header {
  border-bottom: 1px solid color-mix(in srgb, var(--border) calc(var(--xrs-line-alpha, 1) * 100%), transparent);
  background: color-mix(in srgb, var(--card) calc(var(--xrs-card-alpha, 1) * 96%), transparent);
  -webkit-backdrop-filter: blur(var(--xrs-blur, 0px)) saturate(1.2);
  backdrop-filter: blur(var(--xrs-blur, 0px)) saturate(1.2);
}

.header-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  flex-wrap: wrap;
}

.brand h1 {
  margin: 0;
  font-size: 18px;
}

.sub {
  color: var(--muted);
  font-size: 12px;
  margin-left: 8px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.chip-btn,
.app-tab-btn {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--txt);
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 12px;
  cursor: pointer;
}

.chip-btn:hover,
.app-tab-btn.active {
  border-color: var(--blue);
  color: var(--blue);
}

.chip {
  font-size: 12px;
  color: var(--txt);
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid color-mix(in srgb, var(--border) calc(var(--xrs-line-alpha, 1) * 90%), transparent);
  border-radius: 999px;
  padding: 3px 9px;
  background: color-mix(in srgb, var(--card) calc(var(--xrs-card-alpha, 1) * 88%), transparent);
}

.chip b {
  color: var(--muted);
  font-weight: 600;
}

.chip .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--muted);
}

.chip.sniff.ok .dot { background: #2ea043; }
.chip.sniff.warn .dot { background: #d29922; }
.chip.sniff.error .dot { background: #d1242f; }
.chip.sniff.paused .dot { background: #d29922; }

.chip.mono {
  font-family: var(--mono);
}

.more-wrap {
  position: relative;
}

.more-pop {
  position: absolute;
  right: 0;
  top: calc(100% + 6px);
  min-width: 180px;
  z-index: 60;
  border: 1px solid color-mix(in srgb, var(--border) calc(var(--xrs-line-alpha, 1) * 90%), transparent);
  background: color-mix(in srgb, var(--card) calc(var(--xrs-card-alpha, 1) * 92%), transparent);
  -webkit-backdrop-filter: blur(var(--xrs-blur, 0px)) saturate(1.2);
  backdrop-filter: blur(var(--xrs-blur, 0px)) saturate(1.2);
  border-radius: 10px;
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.14);
  padding: 6px;
  display: grid;
  gap: 2px;
}

.more-pop button {
  border: none;
  background: transparent;
  color: var(--txt);
  text-align: left;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}

.more-pop button:hover {
  background: color-mix(in srgb, var(--blue) 12%, transparent);
}

.notify-wrap {
  position: relative;
}

.notify-pop {
  position: absolute;
  right: 0;
  top: calc(100% + 6px);
  width: min(380px, calc(100vw - 24px));
  z-index: 70;
  border: 1px solid var(--border);
  background: var(--card);
  border-radius: 10px;
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.16);
  padding: 8px;
  display: flex;
  flex-direction: column;
  max-height: min(520px, 70dvh);
}

.notify-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}

.notify-head strong {
  margin-right: auto;
}

.mini {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--txt);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}

.notify-msg {
  color: var(--warn, #d83b01);
  font-size: 11px;
  margin: 6px 0 0;
}

.notify-list {
  overflow-y: auto;
  flex: 1;
  display: grid;
  gap: 6px;
  padding-top: 6px;
}

.notify-empty {
  color: var(--muted);
  text-align: center;
  padding: 14px;
  font-size: 12px;
}

.notify-item {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 8px;
}

.notify-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.ntag {
  border-radius: 999px;
  padding: 0 8px;
  font-size: 10px;
  border: 1px solid var(--border);
  color: var(--muted);
}

.ntag.error {
  color: #d1242f;
  border-color: #d1242f;
}

.ntag.warn {
  color: #b98900;
  border-color: #d29922;
}

.ntag.ok {
  color: #2ea043;
  border-color: #2ea043;
}

.ntime {
  margin-left: auto;
  color: var(--muted);
  font-size: 11px;
}

.ntext {
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}

.banner-stack {
  padding: 0 14px 8px;
  display: grid;
  gap: 6px;
}

.banner {
  display: flex;
  align-items: center;
  gap: 10px;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  color: var(--txt);
}

.banner.warn {
  background: color-mix(in srgb, #d29922 14%, var(--card));
  border: 1px solid color-mix(in srgb, #d29922 45%, var(--border));
}

.banner.err {
  background: color-mix(in srgb, #d1242f 12%, var(--card));
  border: 1px solid color-mix(in srgb, #d1242f 45%, var(--border));
}

.banner-close {
  margin-left: auto;
  border: none;
  background: transparent;
  color: var(--muted);
  font-size: 16px;
  cursor: pointer;
}

.app-tab-nav {
  padding: 0 14px 4px;
}

.app-tab-nav :deep(.v-tabs),
.app-tab-nav :deep(.v-slide-group) {
  background: transparent;
}

.app-tab-nav :deep(.v-tab) {
  color: var(--muted);
  font-weight: 500;
  min-width: 96px;
  border-radius: 8px 8px 0 0;
  letter-spacing: 0.01em;
}

.app-tab-nav :deep(.v-tab:hover) {
  color: var(--txt);
}

.app-tab-nav :deep(.v-tab--selected) {
  color: var(--blue);
  background: color-mix(in srgb, var(--blue) 14%, transparent);
}

.app-tab-nav :deep(.v-tab--selected .v-icon) {
  color: var(--blue);
}

.app-tab-nav :deep(.v-tab .v-icon) {
  font-size: 16px;
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 10000;
  display: grid;
  place-items: center;
}

.modal {
  width: min(420px, calc(100vw - 32px));
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px;
}

.modal-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.modal-head .muted {
  color: var(--muted);
  font-size: 12px;
}

.modal-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.modal-body label {
  display: grid;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
}

.modal-body input,
.modal-body select {
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--txt);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
}

.sim-status {
  font-size: 12px;
  color: var(--muted);
  min-height: 16px;
}

.sim-status.running {
  color: #2ea043;
}

.modal-foot {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.modal-foot .btn {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--txt);
  border-radius: 6px;
  padding: 6px 14px;
  cursor: pointer;
}

.modal-foot .btn.primary {
  border-color: var(--blue);
  background: var(--blue);
  color: #fff;
}

.modal-foot .btn:disabled {
  opacity: 0.5;
  cursor: default;
}

.theme-modal {
  width: min(520px, calc(100vw - 32px));
}

.theme-body {
  display: grid;
  gap: 12px;
  padding: 2px 0 10px;
}

.theme-row {
  display: grid;
  gap: 8px;
  font-size: 13px;
  color: var(--txt);
}

.theme-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
}

.theme-toggle input {
  width: auto;
}

.theme-cap {
  color: var(--muted);
  font-size: 12px;
}

.theme-presets {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.swatch {
  padding: 6px 12px;
  border: 1px solid color-mix(in srgb, var(--border) 80%, transparent);
  border-radius: 999px;
  font-size: 12px;
  color: var(--txt);
  cursor: pointer;
  background: var(--bg);
}

.swatch.on {
  border-color: var(--blue);
  color: var(--blue);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue) 22%, transparent);
}

.theme-url-row {
  display: flex;
  gap: 8px;
}

.theme-url-row input {
  flex: 1;
}

.theme-url-row button {
  border: 1px solid var(--blue);
  background: var(--blue);
  color: #fff;
  border-radius: 6px;
  padding: 7px 14px;
  cursor: pointer;
}

.theme-sliders {
  display: grid;
  gap: 8px;
}

.theme-sliders label {
  display: grid;
  grid-template-columns: 52px 1fr 52px;
  gap: 10px;
  align-items: center;
  font-size: 12px;
  color: var(--muted);
}

.theme-sliders b {
  text-align: right;
  color: var(--txt);
}

.theme-sliders input[type="range"] {
  width: 100%;
  accent-color: var(--blue);
  padding: 0;
}
</style>
