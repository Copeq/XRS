<script setup lang="ts">
import { computed, ref } from "vue";
import {
  VAlert,
  VBtn,
  VBtnGroup,
  VChip,
  VProgressCircular,
  VTable,
  VTextField,
} from "vuetify/components";
import type { DroneRow } from "../composables/useLiveSocket";
import { pageFetch } from "../composables/pageApi";
import TrackMap, { type TrackPoint } from "../components/TrackMap.vue";

const props = defineProps<{ rows: DroneRow[] }>();

interface DetailRow {
  [key: string]: unknown;
}

const selectedSn = ref<string>("");
const detail = ref<DetailRow | null>(null);
const detailBusy = ref(false);
const detailError = ref("");
const detailPoints = ref<TrackPoint[]>([]);

const filterText = ref("");
const scope = ref<"all" | "live" | "hist">("all");

function matchesFilter(r: DroneRow): boolean {
  const q = filterText.value.trim().toLowerCase();
  if (!q) return true;
  return [r.sn, r.model, r.uas_id, r.mac].some((v) => String(v ?? "").toLowerCase().includes(q));
}

const historyRows = computed(() =>
  [...props.rows]
    .filter((r) => {
      if (scope.value === "live") return !r.archived;
      if (scope.value === "hist") return !!r.archived;
      return true;
    })
    .filter(matchesFilter)
    .sort((a, b) => {
      const al = Number(a.archived ?? 0) - Number(b.archived ?? 0);
      if (al !== 0) return al;
      return (a.age ?? 0) - (b.age ?? 0);
    }),
);

function esc(v: unknown, fallback = "-"): string {
  if (v == null || v === "") return fallback;
  return String(v);
}

function rssiText(r: unknown): string {
  if (r == null) return "-";
  return `${r} dBm`;
}

const detailFields: Array<[string, string]> = [
  ["sn", "SN"],
  ["model", "机型"],
  ["scan_type", "扫描类型"],
  ["firmware_type", "固件类型"],
  ["uas_id", "UAS ID"],
  ["sn_src", "SN 来源"],
  ["mac", "MAC"],
  ["ch", "信道"],
  ["alt", "高度(m)"],
  ["spd", "地速(m/s)"],
  ["vspd", "垂速(m/s)"],
  ["rssi", "信号"],
  ["pkts", "包数"],
  ["dir", "方向"],
  ["capture_time", "采集时间"],
  ["last_pkt_time", "末帧时间"],
  ["age_text", "数据更新"],
  ["first_seen", "首次发现"],
  ["last_seen", "末次发现"],
  ["track_count", "轨迹点数"],
  ["operator_track_count", "飞手轨迹点数"],
];

function parsePoints(list: unknown): TrackPoint[] {
  const out: TrackPoint[] = [];
  if (!Array.isArray(list)) return out;
  for (const raw of list) {
    const p = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : null;
    if (!p) continue;
    const lat = Number(p.lat ?? p.latitude);
    const lon = Number(p.lon ?? p.lng ?? p.longitude);
    if (Number.isFinite(lat) && Number.isFinite(lon) && lat !== 0 && lon !== 0) {
      out.push({ lat, lon });
    }
  }
  return out;
}

async function selectRow(sn: string) {
  selectedSn.value = sn;
  detailBusy.value = true;
  detailError.value = "";
  detailPoints.value = [];
  try {
    const d = (await pageFetch(
      `/api/drones/get?sn=${encodeURIComponent(sn)}&include_tracks=1`,
    )) as Record<string, unknown>;
    const item = d && typeof d.item === "object" ? (d.item as DetailRow) : {};
    detail.value = item;
    const tracks = d.tracks && typeof d.tracks === "object"
      ? ((d.tracks as Record<string, unknown>).aircraft ?? (d.tracks as Record<string, unknown>).operator)
      : d.track;
    detailPoints.value = parsePoints(Array.isArray(tracks) ? tracks : []);
  } catch (e) {
    detailError.value = e instanceof Error ? e.message : String(e);
    detail.value = null;
  } finally {
    detailBusy.value = false;
  }
}
</script>

<template>
  <div class="history-view">
    <div class="history-grid">
      <section class="panel table-panel">
        <div class="panel-hdr">
          <h2>历史记录
            <span class="count">{{ historyRows.length }}</span>
          </h2>
          <div class="toolbar">
            <VBtnGroup density="compact">
              <VBtn
                size="small"
                :variant="scope === 'all' ? 'flat' : 'tonal'"
                :color="scope === 'all' ? 'primary' : undefined"
                @click="scope = 'all'"
              >全部</VBtn>
              <VBtn
                size="small"
                :variant="scope === 'live' ? 'flat' : 'tonal'"
                :color="scope === 'live' ? 'primary' : undefined"
                @click="scope = 'live'"
              >实时</VBtn>
              <VBtn
                size="small"
                :variant="scope === 'hist' ? 'flat' : 'tonal'"
                :color="scope === 'hist' ? 'primary' : undefined"
                @click="scope = 'hist'"
              >历史</VBtn>
            </VBtnGroup>
            <VTextField
              v-model="filterText"
              density="compact"
              variant="outlined"
              hide-details
              prepend-inner-icon="mdi-magnify"
              placeholder="搜索 SN / 机型 / UAS ID"
              class="filter-field"
            />
          </div>
        </div>
        <div class="table-wrap">
          <VTable density="compact" hover>
            <thead>
              <tr>
                <th>#</th>
                <th>SN</th>
                <th>机型</th>
                <th>状态</th>
                <th>信号</th>
                <th>包</th>
                <th>方向</th>
                <th>数据更新</th>
                <th>末次发现</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(r, i) in historyRows"
                :key="r.sn"
                :class="{ selected: r.sn === selectedSn }"
                @click="selectRow(r.sn)"
              >
                <td>{{ i + 1 }}</td>
                <td class="mono sn">{{ r.sn }}</td>
                <td>{{ esc(r.model) }}</td>
                <td>
                  <VChip v-if="r.archived" size="x-small" variant="tonal" label>历史</VChip>
                  <VChip v-else-if="r.lost" size="x-small" color="warning" variant="tonal" label>离线</VChip>
                  <VChip v-else size="x-small" color="success" variant="tonal" label>实时</VChip>
                </td>
                <td>{{ rssiText(r.rssi) }}</td>
                <td>{{ esc(r.pkts, "0") }}</td>
                <td>{{ esc(r.dir) }}</td>
                <td>{{ esc(r.age_text) }}</td>
                <td>{{ esc(r.last_seen) }}</td>
              </tr>
              <tr v-if="!historyRows.length">
                <td colspan="9" class="text-center text-medium-emphasis py-6">无匹配记录</td>
              </tr>
            </tbody>
          </VTable>
        </div>
      </section>

      <section class="panel detail-panel">
        <h2>详情
          <span v-if="selectedSn" class="mono detail-sn">{{ selectedSn }}</span>
        </h2>
        <div v-if="detailBusy" class="detail-state center">
          <VProgressCircular indeterminate color="primary" size="22" />
          <span>读取中…</span>
        </div>
        <VAlert
          v-else-if="detailError"
          type="error"
          variant="tonal"
          density="compact"
          class="mx-3 my-3"
          :text="detailError"
        />
        <div v-else-if="detail" class="detail-body">
          <div class="detail-grid">
            <template v-for="[key, label] in detailFields" :key="key">
              <span class="k">{{ label }}</span>
              <span class="v">{{ esc(detail[key]) }}</span>
            </template>
          </div>
          <TrackMap :points="detailPoints" />
        </div>
        <div v-else class="detail-state muted">选择左侧飞机查看详情与轨迹。</div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.history-view {
  flex: 1;
  padding: 12px 14px;
}

.history-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(300px, 400px);
  gap: 12px;
  min-height: 300px;
}

@media (max-width: 900px) {
  .history-grid {
    grid-template-columns: 1fr;
  }
}

.panel {
  border: 1px solid color-mix(in srgb, var(--border) calc(var(--xrs-line-alpha, 1) * 100%), transparent);
  background: color-mix(in srgb, var(--card) calc(var(--xrs-card-alpha, 1) * 100%), transparent);
  -webkit-backdrop-filter: blur(var(--xrs-blur, 0px)) saturate(1.2);
  backdrop-filter: blur(var(--xrs-blur, 0px)) saturate(1.2);
  border-radius: 10px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.filter-field {
  max-width: 230px;
}

.detail-state.center {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel .panel-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}

.panel-hdr h2 {
  margin: 0;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel h2 .count {
  color: var(--blue);
}

.detail-sn {
  color: var(--muted);
  font-weight: 400;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.scope {
  display: flex;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}

.scope button {
  border: none;
  background: transparent;
  color: var(--muted);
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
}

.scope button.on {
  background: var(--blue);
  color: #fff;
}

.filter {
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--txt);
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 12px;
  min-width: 170px;
}

.table-wrap {
  overflow: auto;
  flex: 1;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

th {
  position: sticky;
  top: 0;
  background: var(--card);
  color: var(--muted);
  text-align: left;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

td {
  padding: 5px 10px;
  border-bottom: 1px solid color-mix(in srgb, var(--border) 55%, transparent);
  white-space: nowrap;
  cursor: pointer;
}

tbody tr:hover {
  background: color-mix(in srgb, var(--blue) 8%, transparent);
}

tbody tr.selected {
  background: color-mix(in srgb, var(--blue) 14%, transparent);
}

.sn {
  font-family: var(--mono);
}

.badge {
  border-radius: 999px;
  padding: 1px 8px;
  font-size: 11px;
}

.badge.live {
  background: color-mix(in srgb, #2ea043 18%, transparent);
  color: #2ea043;
}

.badge.lost {
  background: color-mix(in srgb, #d29922 18%, transparent);
  color: #b98900;
}

.badge.arch {
  background: color-mix(in srgb, var(--muted) 20%, transparent);
  color: var(--muted);
}

.empty-cell {
  text-align: center;
  color: var(--muted);
  padding: 20px !important;
}

.detail-panel {
  max-height: min(70vh, 680px);
}

.detail-body {
  overflow-y: auto;
  flex: 1;
  padding: 10px;
}

.detail-grid {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 6px 14px;
  font-size: 12px;
}

.detail-grid .k {
  color: var(--muted);
}

.detail-state {
  padding: 14px;
  color: var(--muted);
  font-size: 13px;
}

.detail-state.err {
  color: var(--warn, #d83b01);
}
</style>
