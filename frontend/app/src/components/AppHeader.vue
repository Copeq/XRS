<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { postJson, pageFetch } from "../composables/pageApi";
import type { HomeState } from "../composables/useLiveSocket";

const props = defineProps<{ state: HomeState; page: "live" | "history" }>();
const emit = defineEmits<{ (e: "set-page", p: "live" | "history"): void }>();

type MetaRecord = Record<string, unknown>;

const meta = computed<MetaRecord>(() => (props.state.meta ?? {}) as MetaRecord);
const sec = computed<MetaRecord>(() => {
  const s = meta.value.runtime_security;
  return s && typeof s === "object" ? (s as MetaRecord) : {};
});
const runningAsRoot = computed<boolean>(() => Boolean(sec.value.running_as_root));

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

const secBannerVisible = computed(
  () => runningAsRoot.value && !secIgnored.value,
);
const secIgnored = ref(false);
function ignoreSecBanner() {
  secIgnored.value = true;
  try {
    window.localStorage.setItem("lr_sec_banner_ignored", "1");
  } catch (_e) {
    /* noop */
  }
}
onMounted(() => {
  try {
    secIgnored.value = window.localStorage.getItem("lr_sec_banner_ignored") === "1";
  } catch (_e) {
    secIgnored.value = false;
  }
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
function toggleMore() {
  moreOpen.value = !moreOpen.value;
}
function navTo(href: string) {
  moreOpen.value = false;
  window.location.href = href;
}

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
async function toggleNotify() {
  notifyOpen.value = !notifyOpen.value;
  moreOpen.value = false;
  if (notifyOpen.value) await loadNotifications();
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
        <span class="sub">{{ String(meta.base_name ?? "基站") }} · {{ state.ch || "ch?" }}</span>
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

        <div class="notify-wrap">
          <button class="chip-btn" type="button" @click="toggleNotify">
            通知{{ notifyCount() ? ` (${notifyCount()})` : "" }}
          </button>
          <div v-if="notifyOpen" class="notify-pop">
            <div class="notify-head">
              <strong>通知中心</strong>
              <button class="mini" type="button" :disabled="notifyBusy" @click="loadNotifications">刷新</button>
              <button class="mini" type="button" @click="clearNotify">清空</button>
            </div>
            <p v-if="notifyMsg" class="notify-msg">{{ notifyMsg }}</p>
            <div class="notify-list">
              <div v-if="!notifyItems.length && !notifyBusy" class="notify-empty">暂无通知</div>
              <div v-for="item in notifyItems" :key="item.id" class="notify-item">
                <div class="notify-line">
                  <span class="ntag" :class="notifyKind(item)">{{ notifyKind(item) }}</span>
                  <span class="ntime">{{ notifyTime(item.ts) }}</span>
                  <button class="mini" type="button" @click="deleteNotify(item.id)">删</button>
                </div>
                <div class="ntext">{{ item.text }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="more-wrap">
          <button class="chip-btn" type="button" @click="toggleMore">更多</button>
          <div v-if="moreOpen" class="more-pop">
            <button type="button" @click="navTo('/settings')">设置</button>
            <button type="button" @click="openSim">模拟目标</button>
            <button type="button" @click="navTo('/logs')">日志</button>
            <button type="button" @click="navTo('/hardware-assistant')">硬件助手</button>
          </div>
        </div>
      </div>
    </div>

    <div class="banner-stack">
      <div v-if="secBannerVisible" class="banner warn security-banner">
        <span>当前运行权限过高，建议在设置中修复。</span>
        <button type="button" class="banner-btn" @click="navTo('/settings')">去设置修复</button>
        <button type="button" class="banner-close" aria-label="忽略" title="忽略" @click="ignoreSecBanner">×</button>
      </div>
      <div v-if="sniffBannerText" class="banner" :class="sniffKind() === 'error' ? 'err' : 'warn'">
        {{ sniffBannerText }}
      </div>
    </div>

    <nav class="app-tab-nav">
      <button class="app-tab-btn" :class="{ active: page === 'live' }" type="button" @click="emit('set-page', 'live')">实时</button>
      <button class="app-tab-btn" :class="{ active: page === 'history' }" type="button" @click="emit('set-page', 'history')">历史记录</button>
    </nav>

    <!-- 模拟目标弹窗 -->
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
  </header>
</template>

<style scoped>
.app-header {
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--card) 96%, var(--txt) 4%);
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
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 3px 9px;
  background: var(--card);
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
  border: 1px solid var(--border);
  background: var(--card);
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

.banner-btn {
  border: 1px solid var(--blue);
  background: transparent;
  color: var(--blue);
  border-radius: 6px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 12px;
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
  display: flex;
  gap: 4px;
  padding: 0 14px 8px;
}

.app-tab-btn {
  border: none;
  border-bottom: 2px solid transparent;
  border-radius: 0;
}

.app-tab-btn.active {
  border-bottom-color: var(--blue);
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 2000;
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
</style>
