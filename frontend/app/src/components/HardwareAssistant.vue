<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { VBtn, VChip, VSelect, VTextField } from "vuetify/components";
import { pageFetch, postJson } from "../composables/pageApi";

interface IfaceItem {
  name?: string;
  mode?: string;
  is_monitor?: boolean;
  supports_monitor?: boolean;
  is_wireless?: boolean;
  is_loopback?: boolean;
  state?: string;
  admin_up?: boolean;
  mac?: string;
  ipv4?: string[];
  ipv6?: string[];
  supports_5g?: boolean;
  model?: string;
  driver?: string;
  bus?: string;
  vendor_id?: string;
  product_id?: string;
  detected_role?: string;
}

type JsonValue = Record<string, unknown> | unknown[] | string | number | boolean | null;

const items = ref<IfaceItem[]>([]);
const activeIface = ref<string>("");
const snf = ref<Record<string, unknown>>({});
const currentChannel = ref<number>(0);
const extra = ref<string>("-");

const ifaceOptions = computed(() => items.value.map((it) => String(it.name ?? "")).filter(Boolean));

const ifaceSel = ref<string>("");
const channelInput = ref<number>(6);

const busy = ref<string>("");
const statusText = ref<string>("-");
const outputText = ref<string>("-");

let pollTimer: number | null = null;

function text(v: unknown, fallback = "-"): string {
  if (v == null || v === "") return fallback;
  return String(v);
}

function bandOf(it: IfaceItem): string {
  return it.supports_5g ? "2.4G / 5G" : "2.4G";
}

function fmtOpResult(d: JsonValue): string {
  if (!d) return "-";
  const o = d as Record<string, unknown>;
  if (Array.isArray(o.steps)) {
    return (o.steps as Array<Record<string, unknown>>)
      .map((x, i) => {
        const cmd = text(x.cmd, "-");
        const code = text(x.code ?? x.returncode, "-");
        const out = text(x.stdout, "");
        const err = text(x.stderr, "");
        return `[${i + 1}] ${cmd}\ncode=${code}\n${out}${err ? `\n${err}` : ""}`;
      })
      .join("\n\n");
  }
  if (typeof o.stdout === "string" || typeof o.stderr === "string") {
    return `cmd: ${text(o.cmd, "-")}\ncode: ${text(o.code, "-")}\n\n${text(o.stdout, "")}${o.stderr ? `\n${text(o.stderr)}` : ""}`;
  }
  try {
    return JSON.stringify(o, null, 2);
  } catch (_e) {
    return String(o);
  }
}

async function refresh() {
  try {
    statusText.value = "刷新中…";
    const d = (await pageFetch("/api/hw/status")) as Record<string, unknown>;
    const arr = Array.isArray(d.items) ? (d.items as IfaceItem[]) : [];
    items.value = arr;
    activeIface.value = text(d.active_iface, "-");
    const s = d.sniff_state && typeof d.sniff_state === "object" ? (d.sniff_state as Record<string, unknown>) : {};
    snf.value = s;
    const ch = Number(d.current_channel ?? 0);
    currentChannel.value = Number.isFinite(ch) ? ch : 0;
    if (!channelInput.value || channelInput.value === 6) channelInput.value = currentChannel.value || 6;
    if (!ifaceSel.value && arr.length) ifaceSel.value = arr[0]?.name ?? "";
    extra.value = `网卡数: ${arr.length}`;
    statusText.value = `采集网卡: ${text(d.active_iface, "-")}\n状态: ${text(s.state, "-")}\n说明: ${text(s.msg, "-")}`;
    outputText.value = JSON.stringify(d, null, 2);
  } catch (e) {
    statusText.value = `刷新失败: ${e instanceof Error ? e.message : String(e)}`;
  }
}

async function runOp(op: string) {
  const body: Record<string, unknown> = { op };
  if (["iw_dev", "iw_info", "iw_link", "set_monitor", "set_managed", "set_channel", "restart_iface"].includes(op)) {
    body.iface = ifaceSel.value;
  }
  if (op === "set_channel") body.channel = Number(channelInput.value || 0);
  busy.value = op;
  try {
    statusText.value = `执行中: ${op}`;
    const d = (await postJson("/api/hw/op", body)) as Record<string, unknown>;
    statusText.value = `完成: ${op}${d.ok ? " (OK)" : " (FAILED)"}`;
    outputText.value = fmtOpResult(d as JsonValue);
    if (op === "restart_program") {
      window.setTimeout(() => void refresh(), 1500);
    } else {
      void refresh();
    }
  } catch (e) {
    statusText.value = `执行失败: ${e instanceof Error ? e.message : String(e)}`;
  } finally {
    busy.value = "";
  }
}

function onRestartProgram() {
  if (window.confirm("确认重启主程序？")) void runOp("restart_program");
}

onMounted(() => {
  void refresh();
  pollTimer = window.setInterval(() => void refresh(), 5000);
});

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer);
  pollTimer = null;
});
</script>

<template>
  <div class="hw-wrap">
    <div class="hw-layout">
      <div class="hw-stack">
        <section class="hw-card">
          <h2>采集状态</h2>
          <div class="hw-status-grid">
            <div class="hw-tile">
              <div class="k">采集状态</div>
              <div class="v" :class="{ err: (snf.state == null ? '' : String(snf.state)) === 'error' }">{{ text(snf.state, "-") }}</div>
              <div class="s">{{ text(snf.msg, "-") }}</div>
            </div>
            <div class="hw-tile">
              <div class="k">当前网卡</div>
              <div class="v">{{ text(activeIface, "-") }}</div>
              <div class="s">选择: {{ text(ifaceSel, "未绑定") }}</div>
            </div>
            <div class="hw-tile">
              <div class="k">当前信道</div>
              <div class="v">{{ text((snf.channel == null ? currentChannel : snf.channel) || "-", "-") }}</div>
              <div class="s">{{ extra }}</div>
            </div>
          </div>
          <pre class="hw-status-line">{{ statusText }}</pre>
        </section>

        <section class="hw-card">
          <h2>网卡控制</h2>
          <div class="hw-grid">
            <VSelect
              v-model="ifaceSel"
              label="目标网卡"
              density="compact"
              variant="outlined"
              hide-details
              :items="ifaceOptions"
              placeholder="请选择固定网卡"
            />
            <VTextField
              v-model.number="channelInput"
              label="目标信道"
              type="number"
              min="1"
              max="196"
              density="compact"
              variant="outlined"
              hide-details
            />
          </div>
          <div class="hw-btns">
            <div class="hw-row">
              <VBtn size="small" variant="outlined" :loading="busy === 'iw_dev'" @click="runOp('iw_dev')">查看 iw dev</VBtn>
              <VBtn size="small" variant="outlined" :disabled="!ifaceSel" :loading="busy === 'iw_info'" @click="runOp('iw_info')">查看 iw info</VBtn>
              <VBtn size="small" variant="outlined" :disabled="!ifaceSel" :loading="busy === 'iw_link'" @click="runOp('iw_link')">查看 iw link</VBtn>
            </div>
            <div class="hw-row">
              <VBtn size="small" color="primary" :disabled="!ifaceSel" :loading="busy === 'set_monitor'" @click="runOp('set_monitor')">切换为监控模式</VBtn>
              <VBtn size="small" variant="outlined" :disabled="!ifaceSel" :loading="busy === 'set_managed'" @click="runOp('set_managed')">切换为托管模式</VBtn>
              <VBtn size="small" color="secondary" :disabled="!ifaceSel" :loading="busy === 'set_channel'" @click="runOp('set_channel')">应用目标信道</VBtn>
            </div>
            <div class="hw-row">
              <VBtn size="small" color="warning" variant="tonal" :disabled="!ifaceSel" :loading="busy === 'restart_iface'" @click="runOp('restart_iface')">重启网卡</VBtn>
              <VBtn size="small" color="error" :loading="busy === 'restart_program'" @click="onRestartProgram">重启主程序</VBtn>
            </div>
          </div>
        </section>

        <section class="hw-card">
          <h2>网卡总览</h2>
          <div v-if="!items.length" class="hw-empty">未发现网卡，请检查 USB 网卡、驱动与权限。</div>
          <div v-else class="hw-iface-grid">
            <div v-for="it in items" :key="it.name" class="hw-iface">
              <div class="iface-name">{{ text(it.name, "-") }}</div>
              <div class="iface-tags">
                <VChip size="x-small" variant="tonal" label :color="it.is_monitor ? 'success' : 'warning'">
                  {{ it.is_monitor ? "监控模式" : "非监控模式" }}
                </VChip>
                <VChip
                  v-if="it.supports_monitor === false && it.is_wireless"
                  size="x-small"
                  color="error"
                  variant="tonal"
                  label
                  title="驱动不支持监听模式"
                >无 monitor</VChip>
              </div>
              <div class="iface-meta">
                型号: {{ text(it.model || it.driver, "未知型号") }}<br />
                驱动: {{ text(it.driver, "-") }}<br />
                状态: {{ it.admin_up === false ? "已禁用" : text(it.state, "-") }}<br />
                模式: {{ text(it.mode, "-") }}<br />
                频段: {{ bandOf(it) }}<br />
                5G: {{ it.supports_5g ? "支持" : "未检测到" }}
              </div>
            </div>
          </div>
        </section>
      </div>

      <div class="hw-stack">
        <section class="hw-card">
          <div class="hw-card-head">
            <h2>命令输出</h2>
            <VBtn size="small" variant="outlined" color="primary" @click="refresh">刷新状态</VBtn>
          </div>
          <pre class="hw-output">{{ outputText }}</pre>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hw-wrap {
  padding: 12px 14px 14px;
}

.hw-layout {
  display: grid;
  grid-template-columns: minmax(320px, 0.92fr) minmax(400px, 1.08fr);
  gap: 12px;
  align-items: start;
}

.hw-stack {
  display: grid;
  gap: 12px;
}

.hw-card {
  border: 1px solid color-mix(in srgb, var(--border) calc(var(--xrs-line-alpha, 1) * 100%), transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--card) calc(var(--xrs-card-alpha, 1) * 100%), transparent);
  -webkit-backdrop-filter: blur(var(--xrs-blur, 0px)) saturate(1.2);
  backdrop-filter: blur(var(--xrs-blur, 0px)) saturate(1.2);
  padding: 12px 14px;
}

.hw-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.hw-card h2 {
  margin: 0 0 10px;
  font-size: 15px;
}

.hw-card-head h2 {
  margin: 0;
}

.hw-status-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.hw-tile {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px;
  background: color-mix(in srgb, var(--card) 88%, var(--txt) 12%);
}

.hw-tile .k {
  font-size: 11px;
  color: var(--muted);
}

.hw-tile .v {
  margin-top: 6px;
  font-size: 18px;
  font-weight: 700;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.hw-tile .v.err {
  color: #d1242f;
}

.hw-tile .s {
  margin-top: 4px;
  color: var(--muted);
  font-size: 12px;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.hw-status-line {
  margin: 12px 0 0;
  white-space: pre-wrap;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
  font-family: var(--mono);
  background: transparent;
  border: none;
  padding: 0;
}

.hw-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.hw-field {
  display: grid;
  gap: 5px;
}

.hw-field span {
  font-size: 12px;
  color: var(--muted);
}

.hw-field select,
.hw-field input {
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--txt);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 13px;
}

.hw-btns {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.hw-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.hw-row button {
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--txt);
  border-radius: 6px;
  padding: 7px 12px;
  font-size: 13px;
  cursor: pointer;
}

.hw-row button:hover:not(:disabled) {
  border-color: var(--blue);
  color: var(--blue);
}

.hw-row button:disabled {
  opacity: 0.5;
  cursor: default;
}

.hw-row button.danger {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 55%, var(--border));
}

.hw-iface-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 10px;
}

.hw-iface {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  background: color-mix(in srgb, var(--card) 88%, var(--txt) 12%);
}

.hw-iface .iface-name {
  font-size: 15px;
  font-weight: 700;
}

.iface-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 12px;
}

.tag.ok {
  color: var(--green);
  border-color: color-mix(in srgb, var(--green) 40%, var(--border));
}

.tag.warn {
  color: #d29922;
  border-color: color-mix(in srgb, #d29922 40%, var(--border));
}

.hw-iface .iface-meta {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.6;
}

.hw-empty {
  color: var(--muted);
  font-size: 13px;
  padding: 8px 0;
}

.hw-output {
  margin: 10px 0 0;
  min-height: 300px;
  max-height: 62vh;
  overflow: auto;
  background: color-mix(in srgb, var(--card) 86%, var(--txt) 14%);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px;
  color: var(--txt);
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

@media (max-width: 1080px) {
  .hw-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .hw-status-grid,
  .hw-grid {
    grid-template-columns: 1fr;
  }
}
</style>
