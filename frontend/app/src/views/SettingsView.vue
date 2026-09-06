<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import {
  VAlert,
  VBtn,
  VChip,
  VProgressCircular,
  VSelect,
  VSnackbar,
  VSwitch,
  VTextField,
} from "vuetify/components";
import { pageFetch, postJson } from "../composables/pageApi";

type Dict = Record<string, unknown>;

interface FormState {
  iface: string;
  base_name: string;
  base_lat: string;
  base_lon: string;
  base_zoom: number;
  map_tile_url: string;
  map_tile_subdomains: string;
  map_tile_attribution: string;
  map_tile_max_native_zoom: number;
  heading_ref_deg: number;
  fixed_channel: boolean;
  channel: number;
  lost_timeout: number;
  min_gap: number;
}

const loading = ref(true);
const loadError = ref("");
const saving = ref(false);
const snack = reactive({ show: false, text: "", error: false });

/* 只读总览 */
const overview = reactive<Dict>({});
const ifaceOptions = ref<Array<{ title: string; value: string }>>([]);
const form = reactive<FormState>({
  iface: "",
  base_name: "",
  base_lat: "",
  base_lon: "",
  base_zoom: 13,
  map_tile_url: "",
  map_tile_subdomains: "",
  map_tile_attribution: "",
  map_tile_max_native_zoom: 18,
  heading_ref_deg: 0,
  fixed_channel: false,
  channel: 6,
  lost_timeout: 15,
  min_gap: 0.5,
});

function text(v: unknown, fallback = ""): string {
  return v == null ? fallback : String(v);
}
function num(v: unknown, fallback = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function notify(textMsg: string, isError = false) {
  snack.text = textMsg;
  snack.error = isError;
  snack.show = true;
}

function applyVisual(visual: Dict) {
  const b = (visual.basic ?? {}) as Dict;
  const w = (visual.web ?? {}) as Dict;
  form.iface = text(b.iface ?? "", "");
  form.base_name = text(w.base_name ?? "", "基站");
  form.base_lat = w.base_lat == null ? "" : String(w.base_lat);
  form.base_lon = w.base_lon == null ? "" : String(w.base_lon);
  form.base_zoom = num(w.base_zoom ?? 13, 13);
  form.map_tile_url = text(w.map_tile_url, "");
  form.map_tile_subdomains = text(w.map_tile_subdomains, "");
  form.map_tile_attribution = text(w.map_tile_attribution, "");
  form.map_tile_max_native_zoom = num(w.map_tile_max_native_zoom ?? 18, 18);
  form.heading_ref_deg = num(w.heading_ref_deg ?? 0, 0);
  form.fixed_channel = !(b.channel == null || b.channel === "");
  form.channel = num(b.channel ?? 6, 6);
  form.lost_timeout = num(b.lost_timeout ?? 15, 15);
  form.min_gap = num(b.min_gap ?? 0.5, 0.5);
}

async function load() {
  loading.value = true;
  loadError.value = "";
  try {
    const [view, bind] = await Promise.all([
      pageFetch("/api/settings/view") as Promise<Dict>,
      pageFetch("/api/network-bindings/status") as Promise<Dict>,
    ]);
    Object.assign(overview, {
      version: text((view as Dict).path ? ((view.host as Dict)?.app_version ?? "") : "", "-"),
      host_name: text((view.host as Dict)?.hostname ?? (view.host as Dict)?.name, "-"),
      active_iface: text((view.host as Dict)?.active_iface ?? "-", "-"),
      channel: text((view.host as Dict)?.current_channel ?? "-", "-"),
      sn_state: text(((view.host as Dict)?.sniff_state as Dict)?.state ?? "-", "-"),
      sn_msg: text(((view.host as Dict)?.sniff_state as Dict)?.msg ?? "-", "-"),
      storage: text(((view as Dict).scan_data_file as Dict)?.path ?? "-", "-"),
    });
    const ifaces = Array.isArray((bind as Dict).interfaces) ? ((bind as Dict).interfaces as Array<Dict>) : [];
    const used = new Set<string>();
    ifaceOptions.value = ifaces
      .filter((it) => !it.is_loopback)
      .map((it) => {
        const name = text(it.name, "");
        const role = text(it.detected_role, "");
        used.add(name);
        return { title: name ? `${name} · ${role || "未绑定"}` : name, value: name };
      })
      .filter((o) => o.value);
    const bnd = ((bind as Dict).bindings as Dict)?.items as Array<Dict> | undefined;
    const scanIfaces = Array.isArray(bnd) ? bnd.filter((x) => String(x.role) === "scan").map((x) => text(x.iface, "")) : [];
    if (!form.iface && scanIfaces.length) form.iface = scanIfaces[0];
    if (!form.iface && ifaceOptions.value.length && !used.has(text((view as Dict).host as never, ""))) {
      // no preferred binding yet: leave empty so the save warns user to bind NIC
    }
    applyVisual((view as Dict).visual as Dict);
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  try {
    const iface = text(form.iface, "").trim();
    const basic: Dict = { iface };
    if (form.fixed_channel) basic.channel = num(form.channel, 6);
    else basic.channel = null;
    basic.lost_timeout = num(form.lost_timeout, 15);
    basic.min_gap = num(form.min_gap, 0.5);
    const web: Dict = {
      base_name: text(form.base_name, "基站"),
      base_zoom: num(form.base_zoom, 13),
      heading_ref_deg: num(form.heading_ref_deg, 0),
      map_tile_url: text(form.map_tile_url, ""),
      map_tile_subdomains: text(form.map_tile_subdomains, ""),
      map_tile_attribution: text(form.map_tile_attribution, ""),
      map_tile_max_native_zoom: num(form.map_tile_max_native_zoom, 18),
    };
    const latS = text(form.base_lat, "").trim();
    const lonS = text(form.base_lon, "").trim();
    if (latS || lonS) {
      web.base_lat = Number(latS);
      web.base_lon = Number(lonS);
    }
    const d = (await postJson("/api/settings/visual/save", { basic, web })) as Dict;
    if (d.ok === false) {
      notify(text(d.error, "保存失败"), true);
      return;
    }
    notify(d.reload_msg ? `已保存：${text(d.reload_msg)}` : "已保存", false);
    await load();
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  } finally {
    saving.value = false;
  }
}

function openAdvanced() {
  window.open("/settings?standalone=1", "_blank", "noopener,noreferrer");
}

onMounted(() => {
  void load();
});
</script>

<template>
  <div class="settings-native">
    <div v-if="loading" class="loading-wrap">
      <VProgressCircular indeterminate color="primary" size="26" />
      <span>读取设置…</span>
    </div>

    <VAlert v-else-if="loadError" type="error" variant="tonal" class="mb-3" :text="loadError" />

    <template v-else>
      <div class="st-grid">
        <!-- 状态总览 -->
        <section class="st-card">
          <h2>运行状态</h2>
          <dl>
            <dt>版本</dt><dd class="mono">{{ overview.version }}</dd>
            <dt>主机</dt><dd>{{ overview.host_name }}</dd>
            <dt>当前网卡</dt><dd>{{ overview.active_iface }}</dd>
            <dt>信道</dt><dd>{{ overview.channel }}</dd>
            <dt>采集状态</dt><dd>{{ overview.sn_state }}</dd>
            <dt>采集说明</dt><dd class="wrap">{{ overview.sn_msg }}</dd>
            <dt>历史库</dt><dd class="mono wrap">{{ overview.storage }}</dd>
          </dl>
        </section>

        <!-- 网卡与扫描 -->
        <section class="st-card">
          <h2>网卡与扫描</h2>
          <VSelect
            v-model="form.iface"
            label="扫描网卡"
            :items="ifaceOptions"
            density="compact"
            variant="outlined"
            hide-details
            class="mb-3"
          />
          <VSwitch v-model="form.fixed_channel" label="使用固定信道" color="primary" hide-details class="mb-3" />
          <VTextField
            v-if="form.fixed_channel"
            v-model.number="form.channel"
            label="信道"
            type="number"
            min="1"
            max="196"
            density="compact"
            variant="outlined"
            hide-details
            class="mb-3"
          />
          <div class="d-flex ga-2">
            <VTextField v-model.number="form.lost_timeout" label="离线判定(s)" type="number" min="1" density="compact" variant="outlined" hide-details />
            <VTextField v-model.number="form.min_gap" label="最小间隔(s)" type="number" min="0" step="0.1" density="compact" variant="outlined" hide-details />
          </div>
        </section>

        <!-- 基站与地图 -->
        <section class="st-card st-wide">
          <h2>基站与地图</h2>
          <div class="d-flex ga-2 mb-3">
            <VTextField v-model="form.base_name" label="基站名称" density="compact" variant="outlined" hide-details class="flex-grow-1" />
          </div>
          <div class="d-flex ga-2 mb-3">
            <VTextField v-model="form.base_lat" label="基站纬度" type="number" step="any" density="compact" variant="outlined" hide-details />
            <VTextField v-model="form.base_lon" label="基站经度" type="number" step="any" density="compact" variant="outlined" hide-details />
            <VTextField v-model.number="form.base_zoom" label="初始缩放" type="number" min="3" max="30" density="compact" variant="outlined" hide-details />
            <VTextField v-model.number="form.heading_ref_deg" label="机头参考°" type="number" step="any" density="compact" variant="outlined" hide-details />
          </div>
          <div class="mb-3">
            <VTextField v-model="form.map_tile_url" label="地图瓦片模板 URL（需含 {z}/{x}/{y}）" density="compact" variant="outlined" hide-details />
          </div>
          <div class="d-flex ga-2">
            <VTextField v-model="form.map_tile_subdomains" label="子域名(逗号分隔)" density="compact" variant="outlined" hide-details />
            <VTextField v-model="form.map_tile_attribution" label="版权署名" density="compact" variant="outlined" hide-details />
            <VTextField v-model.number="form.map_tile_max_native_zoom" label="原生最大缩放" type="number" min="1" max="30" density="compact" variant="outlined" hide-details />
          </div>
        </section>
      </div>

      <div class="st-actions">
        <VChip variant="tonal" label class="me-2">高级/完整设置请打开独立设置页</VChip>
        <VBtn variant="tonal" @click="openAdvanced">完整设置…</VBtn>
        <div class="flex-spacer" />
        <VBtn color="primary" :loading="saving" @click="save">保存</VBtn>
      </div>
    </template>

    <VSnackbar v-model="snack.show" :color="snack.error ? 'error' : 'success'" timeout="3600" location="bottom">
      {{ snack.text }}
    </VSnackbar>
  </div>
</template>

<style scoped>
.settings-native {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 14px 16px;
}

.loading-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--muted);
  padding: 24px;
}

.st-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 12px;
}

.st-card {
  border: 1px solid color-mix(in srgb, var(--border) calc(var(--xrs-line-alpha, 1) * 100%), transparent);
  background: color-mix(in srgb, var(--card) calc(var(--xrs-card-alpha, 1) * 100%), transparent);
  -webkit-backdrop-filter: blur(var(--xrs-blur, 0px)) saturate(1.2);
  backdrop-filter: blur(var(--xrs-blur, 0px)) saturate(1.2);
  border-radius: 10px;
  padding: 14px;
}

.st-card h2 {
  margin: 0 0 12px;
  font-size: 15px;
}

.st-card dl {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 6px 14px;
  font-size: 13px;
  margin: 0;
}

.st-card dl dt {
  color: var(--muted);
}

.st-card dl dd {
  margin: 0;
}

.st-card dl dd.wrap {
  overflow-wrap: anywhere;
  word-break: break-word;
}

.mono {
  font-family: var(--mono);
}

.st-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
}

.st-actions .flex-spacer {
  flex: 1;
}
</style>
