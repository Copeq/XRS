<script setup lang="ts">
import { computed, ref } from "vue";
import type { DroneRow } from "../composables/useLiveSocket";
import { pageFetch } from "../composables/pageApi";

const props = defineProps<{ rows: DroneRow[] }>();

interface DetailRow {
  [key: string]: unknown;
}

const selectedSn = ref<string>("");
const detail = ref<DetailRow | null>(null);
const detailBusy = ref(false);
const detailError = ref("");

const historyRows = computed(() =>
  [...props.rows].sort((a, b) => {
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

async function selectRow(sn: string) {
  selectedSn.value = sn;
  detailBusy.value = true;
  detailError.value = "";
  try {
    const d = (await pageFetch(`/api/drones/get?sn=${encodeURIComponent(sn)}`)) as Record<string, unknown>;
    const item = d && typeof d.item === "object" ? (d.item as DetailRow) : {};
    detail.value = item;
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
        <h2>历史记录 · 全部飞机
          <span class="count">{{ historyRows.length }}</span>
        </h2>
        <div class="table-wrap">
          <table>
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
                  <span v-if="r.archived" class="badge arch">历史</span>
                  <span v-else-if="r.lost" class="badge lost">离线</span>
                  <span v-else class="badge live">实时</span>
                </td>
                <td>{{ rssiText(r.rssi) }}</td>
                <td>{{ esc(r.pkts, "0") }}</td>
                <td>{{ esc(r.dir) }}</td>
                <td>{{ esc(r.age_text) }}</td>
                <td>{{ esc(r.last_seen) }}</td>
              </tr>
              <tr v-if="!historyRows.length">
                <td colspan="9" class="empty-cell">暂无历史记录</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel detail-panel">
        <h2>详情
          <span v-if="selectedSn" class="mono detail-sn">{{ selectedSn }}</span>
        </h2>
        <div v-if="detailBusy" class="detail-state">读取中…</div>
        <div v-else-if="detailError" class="detail-state err">{{ detailError }}</div>
        <div v-else-if="detail" class="detail-grid">
          <template v-for="[key, label] in detailFields" :key="key">
            <span class="k">{{ label }}</span>
            <span class="v">{{ esc(detail[key]) }}</span>
          </template>
        </div>
        <div v-else class="detail-state muted">选择左侧飞机查看详情（含轨迹点数）。</div>
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
  grid-template-columns: minmax(0, 1fr) minmax(300px, 380px);
  gap: 12px;
  min-height: 300px;
}

@media (max-width: 900px) {
  .history-grid {
    grid-template-columns: 1fr;
  }
}

.panel {
  border: 1px solid var(--border);
  background: var(--card);
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
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

.detail-sn {
  color: var(--muted);
  font-weight: 400;
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

.detail-panel .detail-grid {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 6px 14px;
  padding: 12px;
  font-size: 12px;
  overflow: auto;
  flex: 1;
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
