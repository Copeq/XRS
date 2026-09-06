<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { VBtn, VBtnGroup, VTable } from "vuetify/components";
import { useLiveSocket, type DroneRow } from "../composables/useLiveSocket";
import { useUiTheme } from "../composables/useUiTheme";
import AppHeader from "../components/AppHeader.vue";
import LiveMap from "../components/LiveMap.vue";
import HardwareAssistant from "../components/HardwareAssistant.vue";
import SettingsView from "../components/SettingsView.vue";
import HistoryView from "./HistoryView.vue";

type PageKey = "live" | "history" | "hardware" | "settings";

function initialPage(): PageKey {
  const p = window.location.pathname.split("?")[0];
  if (p === "/hardware-assistant" || p === "/hardware-assistant.html") return "hardware";
  if (p === "/settings" || p === "/settings.html") return "settings";
  return "live";
}

const state = useLiveSocket();
const page = ref<PageKey>(initialPage());

function setPage(p: PageKey) {
  page.value = p;
}

/* 恢复/应用主页背景与玻璃主题（全 SPA 只需要挂载一次） */
const { apply: applyUiTheme } = useUiTheme();
onMounted(() => {
  applyUiTheme();
});

const liveRows = computed(() =>
  state.drones
    .filter((d) => !d.lost && !d.archived)
    .sort((a, b) => (a.age ?? 0) - (b.age ?? 0)),
);
const sniffMsg = computed(() => String((state.meta as Record<string, unknown>).sniff_msg ?? "") || "-");
const bottomMode = ref<"events" | "ap">("events");

function text(value: unknown, fallback = "-"): string {
  if (value == null || value === "") return fallback;
  return String(value);
}

function rssiCls(d: DroneRow): string {
  const r = Number(d.rssi);
  if (Number.isFinite(r)) {
    if (r >= -60) return "sig good";
    if (r >= -80) return "sig mid";
  }
  return "sig";
}

function logLine(row: unknown): string {
  if (row == null) return "-";
  if (typeof row === "string") return row;
  const o = row as Record<string, unknown>;
  return text(o.text ?? o.msg ?? o.line ?? JSON.stringify(o));
}

function logCls(row: unknown): string {
  if (row == null || typeof row === "string") return "ap";
  const kind = String((row as Record<string, unknown>).kind ?? (row as Record<string, unknown>).cls ?? "ap");
  if (kind.indexOf("rid") >= 0 || kind.indexOf("online") >= 0) return "rid";
  return "ap";
}
</script>

<template>
  <div class="live-home">
    <AppHeader :state="state" :page="page" @set-page="setPage" />

    <template v-if="page === 'live'">
      <div class="main-grid">
        <section class="panel map-panel">
          <h2>地图</h2>
          <LiveMap :state="state" />
        </section>

        <div class="side-col">
          <section class="panel list-panel">
            <h2>实时无人机列表
              <span class="count">{{ liveRows.length }}</span>
            </h2>
            <div class="live-cards">
              <div v-for="d in liveRows" :key="d.sn" class="live-card" :data-sn="d.sn">
                <div class="card-grid">
                  <span class="k">品牌+型号</span>
                  <span class="v brand">{{ text(d.model, "N/A") }}</span>
                  <span class="k">信号强度</span>
                  <span class="v" :class="rssiCls(d)">{{ d.rssi == null ? "-" : `${d.rssi} dBm` }}</span>
                  <span class="k">信号包数</span>
                  <span class="v">{{ text(d.pkts, "0") }}</span>
                  <span class="k">首次发现</span>
                  <span class="v">{{ text(d.first_seen) }}</span>
                  <span class="k">末次发现</span>
                  <span class="v">{{ text(d.last_seen) }}</span>
                  <span class="k">UAS ID</span>
                  <span class="v mono">{{ text(d.uas_id, "-") }}</span>
                  <span class="k">序列号</span>
                  <span class="v mono" :title="text(d.sn)">{{ text(d.sn) }}</span>
                </div>
              </div>
              <div v-if="!liveRows.length" class="empty">暂无在线无人机（可在「更多 → 模拟目标」启动内存仿真验证）。</div>
            </div>
          </section>

          <section class="panel log-panel">
            <div class="panel-hdr">
              <h2>
                <VBtnGroup density="compact">
                  <VBtn
                    size="small"
                    :variant="bottomMode === 'events' ? 'flat' : 'tonal'"
                    :color="bottomMode === 'events' ? 'primary' : undefined"
                    @click="bottomMode = 'events'"
                  >事件</VBtn>
                  <VBtn
                    size="small"
                    :variant="bottomMode === 'ap' ? 'flat' : 'tonal'"
                    :color="bottomMode === 'ap' ? 'primary' : undefined"
                    @click="bottomMode = 'ap'"
                  >AP ({{ state.aps.length }})</VBtn>
                </VBtnGroup>
              </h2>
              <span class="muted-note" v-if="bottomMode === 'events'">sniff: {{ sniffMsg }}</span>
            </div>

            <div v-if="bottomMode === 'events'" class="logbox">
              <div v-for="(row, i) in state.logs" :key="i" :class="logCls(row)">{{ logLine(row) }}</div>
              <div v-if="!state.logs.length" class="ap empty-log">
                暂无事件。WS：{{ state.connected ? "connected" : "connecting…" }}
              </div>
            </div>

            <div v-else class="ap-table">
              <VTable density="compact">
                <thead>
                  <tr>
                    <th>SSID</th>
                    <th>BSSID</th>
                    <th>厂商</th>
                    <th>信道</th>
                    <th>信号</th>
                    <th>末次发现</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(a, i) in state.aps" :key="a.bssid || a.mac || i">
                    <td>{{ text(a.ssid, "(隐藏)") }}</td>
                    <td class="mono">{{ text(a.bssid || a.mac) }}</td>
                    <td>{{ text(a.vendor) }}</td>
                    <td>{{ text(a.ch) }}</td>
                    <td>{{ a.rssi == null ? "-" : `${a.rssi} dBm` }}</td>
                    <td>{{ text(a.last_seen || a.first_seen) }}</td>
                  </tr>
                  <tr v-if="!state.aps.length">
                    <td colspan="6" class="text-center text-medium-emphasis py-4">暂无 AP 数据（无网卡采集时为正常状态）。</td>
                  </tr>
                </tbody>
              </VTable>
            </div>
          </section>
        </div>
      </div>
    </template>

    <HardwareAssistant v-else-if="page === 'hardware'" />
    <SettingsView v-else-if="page === 'settings'" />
    <HistoryView v-else :rows="state.drones" />
  </div>
</template>

<style scoped>
.live-home {
  display: flex;
  flex-direction: column;
  min-height: 100dvh;
}

.main-grid {
  display: grid;
  grid-template-columns: minmax(320px, 1.2fr) minmax(340px, 1fr);
  grid-template-rows: minmax(0, 1fr);
  gap: 12px;
  padding: 12px 14px;
  flex: 1;
  min-height: 0;
  align-items: stretch;
}

/* 右侧纵列：无人机列表在上、事件/AP 在下，宽度与列表一致 */
.side-col {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
  min-height: 0;
}

.side-col .list-panel {
  flex: 1 1 auto;
  min-height: 180px;
}

.side-col .log-panel {
  flex: 0 1 auto;
  min-height: 170px;
}

@media (max-width: 900px) {
  .main-grid {
    grid-template-columns: 1fr;
    grid-template-rows: none;
  }
}

.panel {
  border: 1px solid color-mix(in srgb, var(--border) calc(var(--xrs-line-alpha, 1) * 100%), transparent);
  background: color-mix(in srgb, var(--card) calc(var(--xrs-card-alpha, 1) * 100%), transparent);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  min-height: 280px;
  overflow: hidden;
  -webkit-backdrop-filter: blur(var(--xrs-blur, 0px)) saturate(1.2);
  backdrop-filter: blur(var(--xrs-blur, 0px)) saturate(1.2);
}

.panel h2 {
  margin: 0;
  padding: 8px 12px;
  font-size: 13px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel h2 .count {
  color: var(--blue);
}

.placeholder {
  flex: 1;
  display: grid;
  place-items: center;
  color: var(--muted);
  text-align: center;
  padding: 14px;
}

.placeholder p {
  margin: 4px 0;
}

.live-cards {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.live-card {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  background: color-mix(in srgb, var(--card) 92%, var(--txt) 8%);
}

.card-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
  font-weight: 700;
}

.model {
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  max-width: 45%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-grid {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 4px 12px;
  font-size: 12px;
}

.card-grid .k {
  color: var(--muted);
}

.card-grid .v {
  overflow-wrap: anywhere;
  word-break: break-word;
}

.card-grid .v.brand {
  font-weight: 700;
}

.sig.good {
  color: #2ea043;
}

.sig.mid {
  color: #d29922;
}

.empty {
  color: var(--muted);
  padding: 16px;
  text-align: center;
}

.log-panel {
  margin: 0;
  min-height: 170px;
}

.log-panel .panel-hdr {
  flex-wrap: wrap;
}

.log-panel .muted-note {
  color: var(--muted);
  font-weight: 400;
  font-size: 11px;
  margin-left: auto;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.logbox {
  flex: 1;
  overflow-y: auto;
  padding: 6px 12px;
  font-family: var(--mono);
  font-size: 12px;
  max-height: 220px;
}

/* 底部长文本允许自动换行，避免被右列宽度截断 */
.logbox div {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.logbox .rid {
  color: #2ea043;
  font-weight: 700;
}

.empty-log {
  color: var(--muted);
}

.log-panel .panel-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
}

.log-panel .panel-hdr h2 {
  border-bottom: none;
  gap: 4px;
}

.seg {
  border: 1px solid transparent;
  background: transparent;
  color: var(--muted);
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
}

.seg.on {
  color: var(--blue);
  border-color: var(--blue);
}

.ap-table {
  flex: 1;
  overflow: auto;
  max-height: 240px;
}

.ap-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.ap-table th {
  position: sticky;
  top: 0;
  background: var(--card);
  color: var(--muted);
  text-align: left;
  padding: 5px 10px;
  border-bottom: 1px solid var(--border);
}

.ap-table td {
  padding: 4px 10px;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 50%, transparent);
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.ap-table-empty {
  text-align: center;
  padding: 18px !important;
}
</style>
