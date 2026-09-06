<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  VAlert,
  VBtn,
  VChip,
  VDivider,
  VProgressCircular,
  VSelect,
  VSnackbar,
  VSwitch,
  VTextarea,
  VTextField,
} from "vuetify/components";
import { pageFetch, postJson } from "../composables/pageApi";

type Dict = Record<string, unknown>;

interface ZoneForm {
  enabled: boolean;
  name: string;
  lat1: string;
  lon1: string;
  lat2: string;
  lon2: string;
}

interface HookForm {
  index: number;
  name: string;
  enabled: boolean;
  key: string;
}

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
  map_idle: number;
  dji_lookup_url: string;
  fixed_channel: boolean;
  channel: number;
  lost_timeout: number;
  min_gap: number;
  /* 扫描高级 */
  hop: boolean;
  hop_5g: boolean;
  scan_wifi_fast: boolean;
  auto_self_heal: boolean;
  change_on_rssi: boolean;
  change_on_payload: boolean;
  debug: boolean;
  dwell_2g: number;
  dwell_5g: number;
  settle: number;
  dwell_on_hit: number;
  hit_cap: number;
  rssi_delta: number;
  time: number;
  track_points_limit: number;
  /* Web 访问控制 */
  access_enabled: boolean;
  access_mode: string;
  access_list: string[];
  /* 报警区域 */
  alarm_zones: ZoneForm[];
  /* 通知 */
  notify_enabled: boolean;
  notify_reonline: boolean;
  reonline_cooldown_sec: number;
  send_timeout_sec: number;
  hooks: HookForm[];
  /* Token API */
  api_enabled: boolean;
  api_whitelist_enabled: boolean;
  api_whitelist_mode: string;
  api_whitelist: string[];
  /* 鉴权 */
  auth_enabled: boolean;
  auth_realm: string;
  auth_ttl: number;
  login_password: boolean;
  login_passkey: boolean;
  auth_username: string;
  auth_password: string;
  /* 机型库更新 */
  model_enabled: boolean;
  model_url: string;
  /* 主机指标 */
  metrics_enabled: boolean;
  metrics_retention: number;
  metrics_temp: string;
}

const loading = ref(true);
const loadError = ref("");
const saving = ref(false);
const snack = reactive({ show: false, text: "", error: false });

/* 只读总览 */
const overview = reactive<Dict>({});
const hostIps = ref<string[]>([]);
const hostCpuMem = ref("");
const hostLoad = ref("");
const hostUptime = ref("");
const hostTemp = ref("");
const hostTempSrc = ref("");
const ifaceOptions = ref<Array<{ title: string; value: string }>>([]);
const lastPayloadJson = ref("");
const configDirty = computed(() => JSON.stringify(buildVisualPayload()) !== lastPayloadJson.value);

/* ------- 网卡绑定与 AP 热点 ------- */
const NET_ROLE_FALLBACKS: Array<{ key: string; label: string }> = [
  { key: "none", label: "None" },
  { key: "scan", label: "扫描" },
  { key: "web", label: "网页服务" },
  { key: "ap_web", label: "AP热点网页服务" },
  { key: "disabled", label: "禁用" },
  { key: "idle", label: "闲置" },
];
const netRoles = ref<Array<Dict>>([...NET_ROLE_FALLBACKS]);
const netIfaces = ref<Array<Dict>>([]);
const netItems = ref<Array<Dict>>([]);
const netAp = ref<Dict>({});
const applyNet = ref("");
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
  map_idle: 60,
  fixed_channel: false,
  channel: 6,
  lost_timeout: 15,
  min_gap: 0.5,
  dji_lookup_url: "",
  hop: false,
  hop_5g: false,
  scan_wifi_fast: false,
  auto_self_heal: true,
  change_on_rssi: false,
  change_on_payload: false,
  debug: false,
  dwell_2g: 300,
  dwell_5g: 300,
  settle: 50,
  dwell_on_hit: 2500,
  hit_cap: 6000,
  rssi_delta: 3,
  time: 1,
  track_points_limit: 10000,
  access_enabled: false,
  access_mode: "allow",
  access_list: [] as string[],
  alarm_zones: [] as ZoneForm[],
  notify_enabled: false,
  notify_reonline: true,
  reonline_cooldown_sec: 300,
  send_timeout_sec: 8,
  hooks: [] as HookForm[],
  api_enabled: false,
  api_whitelist_enabled: false,
  api_whitelist_mode: "allow",
  api_whitelist: [] as string[],
  auth_enabled: false,
  auth_realm: "XRS",
  auth_ttl: 30,
  login_password: true,
  login_passkey: true,
  auth_username: "",
  auth_password: "",
  model_enabled: true,
  model_url: "",
  metrics_enabled: false,
  metrics_retention: 7,
  metrics_temp: "auto",
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
  form.map_idle = num(w.map_auto_center_idle_sec ?? 60, 60);
  form.fixed_channel = !(b.channel == null || b.channel === "");
  form.channel = num(b.channel ?? 6, 6);
  form.lost_timeout = num(b.lost_timeout ?? 15, 15);
  form.min_gap = num(b.min_gap ?? 0.5, 0.5);
  form.dji_lookup_url = text(w.dji_lookup_url ?? (visual as Dict).dji_lookup_url, "");
  form.hop = !!b.hop;
  form.hop_5g = !!b.hop_5g;
  form.scan_wifi_fast = !!b.scan_wifi_fast;
  form.auto_self_heal = b.auto_self_heal !== false;
  form.change_on_rssi = !!b.change_on_rssi;
  form.change_on_payload = !!b.change_on_payload;
  form.debug = !!b.debug;
  form.dwell_2g = num(b.dwell_2g ?? 300, 300);
  form.dwell_5g = num(b.dwell_5g ?? 300, 300);
  form.settle = num(b.settle ?? 50, 50);
  form.dwell_on_hit = num(b.dwell_on_hit ?? 2500, 2500);
  form.hit_cap = num(b.hit_cap ?? 6000, 6000);
  form.rssi_delta = num(b.rssi_delta ?? 3, 3);
  form.time = num(b.time ?? 1, 1);
  form.track_points_limit = num(b.track_points_limit ?? 10000, 10000);
  /* Web 访问控制 */
  form.access_enabled = !!w.access_list_enabled;
  form.access_mode = text(w.access_list_mode, "allow");
  form.access_list = Array.isArray(w.access_list) ? (w.access_list as Array<unknown>).map((x) => text(x, "").trim()).filter(Boolean) : [];
  /* 报警区域 */
  const zonesRaw = Array.isArray(w.alarm_zones) ? (w.alarm_zones as Array<Dict>) : [];
  form.alarm_zones = zonesRaw.map((z) => ({
    enabled: !!z.enabled,
    name: text(z.name, ""),
    lat1: z.lat1 == null ? "" : String(z.lat1),
    lon1: z.lon1 == null ? "" : String(z.lon1),
    lat2: z.lat2 == null ? "" : String(z.lat2),
    lon2: z.lon2 == null ? "" : String(z.lon2),
  }));
  /* 通知 */
  const n = (visual.notify ?? {}) as Dict;
  form.notify_enabled = !!n.enabled;
  form.notify_reonline = n.notify_reonline !== false;
  form.reonline_cooldown_sec = num(n.reonline_cooldown_sec ?? 300, 300);
  form.send_timeout_sec = num(n.send_timeout_sec ?? 8, 8);
  const hooksRaw = Array.isArray(n.wecom_webhooks) ? (n.wecom_webhooks as Array<Dict>) : [];
  form.hooks = hooksRaw.map((h, idx) => ({
    index: num(h.index ?? idx, idx),
    name: text(h.name, `通道 ${idx + 1}`),
    enabled: h.enabled !== false,
    key: "",
  }));
  /* Token API */
  const ap = (visual.api ?? {}) as Dict;
  form.api_enabled = !!ap.enabled;
  form.api_whitelist_enabled = !!ap.whitelist_enabled;
  form.api_whitelist_mode = text(ap.whitelist_mode, "allow");
  form.api_whitelist = Array.isArray(ap.whitelist) ? (ap.whitelist as Array<unknown>).map((x) => text(x, "").trim()).filter(Boolean) : [];
  tokens.value = Array.isArray(ap.tokens) ? (ap.tokens as Array<Dict>) : [];
  /* 鉴权 */
  const at = (visual.auth ?? {}) as Dict;
  form.auth_enabled = !!at.enabled;
  form.auth_realm = text(at.realm, "XRS");
  form.auth_ttl = num(at.session_ttl_min ?? 30, 30);
  const methods = Array.isArray(at.login_methods) ? (at.login_methods as Array<unknown>).map((x) => String(x)) : [];
  form.login_password = methods.includes("password");
  form.login_passkey = methods.includes("passkey");
  form.auth_username = "";
  form.auth_password = "";
  authConfigured.value = !!at.configured;
  ssoLinks.value = Array.isArray(at.sso_links) ? (at.sso_links as Array<Dict>) : [];
  passkeys.value = Array.isArray(at.passkeys) ? (at.passkeys as Array<Dict>) : [];
  /* 机型库更新 */
  const mu = (visual.model_update ?? {}) as Dict;
  form.model_enabled = mu.enabled !== false;
  form.model_url = text(mu.url, "");
  /* 主机指标 */
  const mc = (visual.metrics ?? {}) as Dict;
  form.metrics_enabled = !!mc.enabled;
  form.metrics_retention = num(mc.retention_days ?? 7, 7);
  form.metrics_temp = text(mc.temperature_source, "auto");
  /* 程序更新 */
  const au = (visual.app_update ?? {}) as Dict;
  auEnabled.value = (au.enabled as boolean | undefined) !== false;
  auForce.value = !!au.force_update;
  auMirror.value = text(au.mirror, "github") || "github";
  auCustomMirror.value = text(au.custom_mirror, "");
  const auStateRaw = ((au.state as Dict) ?? {}) as Dict;
  auState.value = auStateRaw;
  const opts = Array.isArray((au as Dict).mirror_options)
    ? ((au as Dict).mirror_options as Array<Dict>)
    : Array.isArray(auStateRaw.mirror_options)
      ? (auStateRaw.mirror_options as Array<Dict>)
      : [];
  auMirrorOptions.value = opts;
}

function fmtUptime(sec: unknown): string {
  const s = Math.floor(Number(sec ?? 0));
  if (!Number.isFinite(s) || s < 0) return "";
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  return [d ? `${d}天` : "", h ? `${h}时` : "", `${m}分`].filter(Boolean).join("");
}

function syncHostExtras(view: Dict) {
  const h = (view.host as Dict) ?? {};
  hostIps.value = Array.isArray(h.local_ips) ? (h.local_ips as Array<unknown>).map((x) => String(x)) : [];
  const cpu = Number(h.cpu_percent);
  const mem = Number(h.mem_percent);
  hostCpuMem.value = Number.isFinite(cpu) && Number.isFinite(mem) ? `CPU ${cpu.toFixed(1)}% · 内存 ${mem.toFixed(1)}%` : "";
  const l1 = Number(h.load1);
  const l5 = Number(h.load5);
  const l15 = Number(h.load15);
  hostLoad.value = Number.isFinite(l1) && Number.isFinite(l5) && Number.isFinite(l15) ? `${l1.toFixed(2)} / ${l5.toFixed(2)} / ${l15.toFixed(2)}` : "";
  hostUptime.value = fmtUptime(h.uptime_sec);
  const t = Number(h.temperature_c);
  hostTemp.value = Number.isFinite(t) ? `${t.toFixed(1)}°C` : "";
  hostTempSrc.value = text(h.temperature_source_label, "");
}

async function refreshHost() {
  try {
    const d = (await pageFetch("/api/settings/view")) as Dict;
    const host = (d.host as Dict) ?? {};
    Object.assign(overview, {
      version: text(d.path ? text(host.app_version, "") : "", "-"),
      host_name: text(host.hostname ?? host.name, "-"),
      active_iface: text(host.active_iface, "-"),
      channel: text(host.current_channel, "-"),
      sn_state: text(((host.sniff_state as Dict) ?? {}).state, "-"),
      sn_msg: text(((host.sniff_state as Dict) ?? {}).msg, "-"),
      storage: text(((d.scan_data_file as Dict) ?? {}).path, "-"),
    });
    syncHostExtras(d);
    notify("主机状态已刷新", false);
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  }
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
    syncHostExtras(view as Dict);
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
    initNetworkBindings(((bind as Dict).bindings as Dict) ?? {}, ifaces);
    lastPayloadJson.value = JSON.stringify(buildVisualPayload());
    applyEula(((view as Dict).eula as Dict) ?? {});
    try {
      const ls = localStorage.getItem("rid_new_firmware_parse_enabled");
      newFwParse.value = ls == null ? true : ls !== "0";
    } catch (_e) {
      newFwParse.value = true;
    }
    loadSystemServiceStatus().catch(() => {
      /* ignore */
    });
    await loadRawTree();
    await loadMetrics();
    await loadRuntime();
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

function addApiEntry() {
  form.api_whitelist.push("");
}
function removeApiEntry(i: number) {
  form.api_whitelist.splice(i, 1);
}
function addZone() {
  form.alarm_zones.push({ enabled: false, name: "", lat1: "", lon1: "", lat2: "", lon2: "" });
}
function removeZone(i: number) {
  form.alarm_zones.splice(i, 1);
}
function addAccess() {
  form.access_list.push("");
}
function removeAccess(i: number) {
  form.access_list.splice(i, 1);
}
function addHook() {
  form.hooks.push({ index: -1, name: "", enabled: true, key: "" });
}
function removeHook(i: number) {
  form.hooks.splice(i, 1);
}

function initNetworkBindings(bnd: Dict, ifaces: Array<Dict>) {
  const ap0 = (bnd.ap ?? {}) as Dict;
  netRoles.value = Array.isArray(bnd.roles) ? (bnd.roles as Array<Dict>) : [...NET_ROLE_FALLBACKS];
  netIfaces.value = ifaces.slice();
  const savedItems = Array.isArray(bnd.items) ? (bnd.items as Array<Dict>) : [];
  const preferred = text(bnd.selected_iface ?? bnd.scan_iface ?? "", "");
  netItems.value = netIfaces.value.map((it) => {
    const name = text(it.name, "");
    const saved = savedItems.find((x) => text(x.iface, "") === name);
    const detected = text(it.detected_role, "");
    return { iface: name, role: saved ? text(saved.role, "none") : name === preferred ? "scan" : detected || "none" };
  });
  netAp.value = Object.assign(
    {
      ssid: "XRS-HotSpot",
      password: "",
      address: "172.16.0.1",
      cidr: "172.16.0.1/24",
      dhcp_start: "172.16.0.20",
      dhcp_end: "172.16.0.240",
      http_port: 80,
      channel: 6,
      uplink_iface: "",
      internet_enabled: false,
    },
    ap0
  );
  netAp.value.internet_enabled = !!text(netAp.value.uplink_iface, "");
}

function netRoleOf(iface: string): string {
  const it = netItems.value.find((x) => text(x.iface, "") === iface);
  return it ? text(it.role, "none") || "none" : "none";
}
function netIfaceMeta(it: Dict): string {
  const meta: string[] = [];
  if (text(it.model, "")) meta.push(`型号 ${text(it.model, "")}`);
  if (text(it.driver, "")) meta.push(`驱动 ${text(it.driver, "")}`);
  meta.push(it.is_wireless ? `无线 ${text(it.mode, "")}` : "有线");
  if (it.admin_up === false) meta.push("已禁用");
  if (text(it.state, "")) meta.push(`状态 ${text(it.state, "")}`);
  if (Array.isArray(it.ipv4) && (it.ipv4 as Array<unknown>).length) meta.push((it.ipv4 as Array<unknown>).join(", "));
  if (text(it.mac, "")) meta.push(text(it.mac, ""));
  return meta.join(" · ");
}
function netUplinkTitle(it: Dict): string {
  const name = text(it.name, "");
  const kind = it.is_wireless ? "无线" : "有线";
  const ip = Array.isArray(it.ipv4) && (it.ipv4 as Array<unknown>).length ? ` | ${(it.ipv4 as Array<unknown>).join(",")}` : "";
  return name ? `${name} [${kind}${ip}]` : name;
}
function setNetRole(iface: string, val: unknown) {
  const role = String(val ?? "none") || "none";
  const entry = netItems.value.find((x) => text(x.iface, "") === iface);
  if (role === "scan") {
    netItems.value.forEach((x) => {
      if (text(x.iface, "") !== iface && text(x.role, "") === "scan") x.role = "none";
    });
    if (entry) entry.role = "scan";
    form.iface = iface;
  } else {
    if (entry) entry.role = role;
    if (form.iface === iface) form.iface = "";
  }
}
function collectNetworkBindings(): Dict {
  const selected = text(form.iface, "").trim();
  const items: Array<Dict> = [];
  netItems.value.forEach((item) => {
    const iface = text(item.iface, "");
    const role = iface === selected ? "scan" : text(item.role, "") || "none";
    items.push({ iface, role });
  });
  let scanSeen = false;
  for (const item of items) {
    if (String(item.role) === "scan") {
      if (scanSeen) item.role = "none";
      scanSeen = true;
    }
  }
  const ap: Dict = Object.assign({}, netAp.value);
  if (!text(ap.ssid, "").trim()) ap.ssid = "XRS-HotSpot";
  ap.channel = Math.max(1, Math.min(196, Math.floor(num(ap.channel, 6) || 6)));
  ap.http_port = Math.max(1, Math.min(65535, Math.floor(num(ap.http_port, 80) || 80)));
  ap.uplink_iface = text(ap.uplink_iface, "").trim();
  ap.internet_enabled = !!ap.uplink_iface;
  return { items, ap };
}
function netApHttpSummary(): string {
  return `${text(netAp.value.address, "172.16.0.1")}:${num(netAp.value.http_port, 80)}`;
}

function buildVisualPayload(): Dict {
  const iface = text(form.iface, "").trim();
  const basic: Dict = { iface };
  if (form.fixed_channel) basic.channel = num(form.channel, 6);
  else basic.channel = null;
  basic.lost_timeout = num(form.lost_timeout, 15);
  basic.min_gap = num(form.min_gap, 0.5);
  for (const k of ["hop", "hop_5g", "scan_wifi_fast", "auto_self_heal", "change_on_rssi", "change_on_payload", "debug"]) {
    basic[k] = !!form[k as keyof FormState];
  }
  basic.dwell_2g = num(form.dwell_2g, 300);
  basic.dwell_5g = num(form.dwell_5g, 300);
  basic.settle = num(form.settle, 50);
  basic.dwell_on_hit = num(form.dwell_on_hit, 2500);
  basic.hit_cap = num(form.hit_cap, 6000);
  basic.rssi_delta = num(form.rssi_delta, 3);
  basic.time = num(form.time, 1);
  basic.track_points_limit = num(form.track_points_limit, 10000);
  const web: Dict = {
    base_name: text(form.base_name, "基站"),
    base_zoom: num(form.base_zoom, 13),
    heading_ref_deg: num(form.heading_ref_deg, 0),
    dji_lookup_url: text(form.dji_lookup_url, ""),
    map_tile_url: text(form.map_tile_url, ""),
    map_tile_subdomains: text(form.map_tile_subdomains, ""),
    map_tile_attribution: text(form.map_tile_attribution, ""),
    map_tile_max_native_zoom: num(form.map_tile_max_native_zoom, 18),
  };
  if (form.map_idle >= 5) web.map_auto_center_idle_sec = Math.min(600, Math.floor(form.map_idle));
  const latS = text(form.base_lat, "").trim();
  const lonS = text(form.base_lon, "").trim();
  if (latS || lonS) {
    web.base_lat = Number(latS);
    web.base_lon = Number(lonS);
  }
  web.access_list_enabled = form.access_enabled;
  web.access_list_mode = form.access_mode;
  web.access_list = [...form.access_list].map((x) => x.trim()).filter(Boolean);
  web.alarm_zones = form.alarm_zones.map((z, i) => {
    const raw = [z.lat1, z.lon1, z.lat2, z.lon2].map((v) => {
      const s = String(v ?? "").trim();
      return s === "" ? null : Number(s);
    });
    return {
      enabled: !!z.enabled,
      name: z.name.trim() || `报警区域 ${i + 1}`,
      lat1: raw[0],
      lon1: raw[1],
      lat2: raw[2],
      lon2: raw[3],
    };
  });
  const notifyPayload: Dict = {
    enabled: form.notify_enabled,
    notify_reonline: form.notify_reonline,
    reonline_cooldown_sec: num(form.reonline_cooldown_sec, 300),
    send_timeout_sec: num(form.send_timeout_sec, 8),
    wecom_webhooks: form.hooks.map((h, i) => ({
      index: h.index >= 0 ? h.index : i,
      name: h.name.trim() || `通道 ${i + 1}`,
      enabled: h.enabled,
      key: h.key.trim(),
    })),
  };
  const apiPayload: Dict = {
    enabled: form.api_enabled,
    whitelist_enabled: form.api_whitelist_enabled,
    whitelist_mode: form.api_whitelist_mode,
    whitelist: [...form.api_whitelist].map((x) => x.trim()).filter(Boolean),
  };
  const loginMethods: string[] = [];
  if (form.login_password) loginMethods.push("password");
  if (form.login_passkey) loginMethods.push("passkey");
  const usernameRaw = text(form.auth_username, "").trim();
  const passwordRaw = form.auth_password;
  const authPayload: Dict = {
    enabled: form.auth_enabled,
    realm: text(form.auth_realm, "XRS"),
    session_ttl_min: num(form.auth_ttl, 30),
    login_methods: loginMethods.length ? loginMethods : ["password"],
  };
  if (usernameRaw) authPayload.username = usernameRaw;
  if (passwordRaw) authPayload.password = passwordRaw;
  const metricsPayload: Dict = {
    enabled: form.metrics_enabled,
    retention_days: num(form.metrics_retention, 7),
    temperature_source: text(form.metrics_temp, "auto"),
  };
  const modelPayload: Dict = {
    enabled: form.model_enabled,
    url: text(form.model_url, ""),
  };
  const appUpdatePayload: Dict = {
    enabled: auEnabled.value,
    force_update: auForce.value,
    mirror: text(auMirror.value, "github") || "github",
    custom_mirror: auMirror.value === "custom" ? text(auCustomMirror.value, "") : "",
  };
  return {
    basic,
    web,
    notify: notifyPayload,
    api: apiPayload,
    auth: authPayload,
    metrics: metricsPayload,
    model_update: modelPayload,
    app_update: appUpdatePayload,
    network_bindings: collectNetworkBindings(),
  };
}

async function save() {
  saving.value = true;
  try {
    const payload = buildVisualPayload();
    const d = (await postJson("/api/settings/visual/save", payload)) as Dict;
    if (d.ok === false) {
      notify(text(d.error, "保存失败"), true);
      return;
    }
    lastPayloadJson.value = JSON.stringify(payload);
    notify(d.reload_msg ? `已保存：${text(d.reload_msg)}` : "已保存", false);
    await load();
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  } finally {
    saving.value = false;
  }
}

async function applyNetworkBindings() {
  if (configDirty.value) {
    notify("设置尚未保存。请先点击「保存设置」，再应用网卡绑定。", true);
    return;
  }
  const ok = window.confirm("将按已保存配置调整网卡角色、AP 地址、hostapd 与内置 DHCP。继续？");
  if (!ok) return;
  toolBusy.value = "net-apply";
  applyNet.value = "";
  try {
    const d = (await postJson("/api/network-bindings/apply", { confirm: true })) as Dict;
    const lines: string[] = [];
    (Array.isArray(d.steps) ? (d.steps as Array<Dict>) : []).forEach((s) => {
      lines.push(`${s.ok ? "OK  " : "FAIL "}${text(s.label, "")}${text(s.output, "") ? ` | ${text(s.output, "")}` : ""}`);
    });
    applyNet.value = lines.join("\n") || (d.ok ? "已应用网卡绑定。" : "未返回执行步骤。");
    notify(d.ok === false ? text(d.error, "应用失败") : applyNet.value || "网卡绑定已应用。", d.ok === false);
  } catch (e) {
    applyNet.value = e instanceof Error ? e.message : String(e);
    notify(applyNet.value, true);
  } finally {
    toolBusy.value = "";
  }
}

/* ------- Token 管理 ------- */
const tokens = ref<Array<Dict>>([]);
const tokenName = ref("");
const tokenUser = ref("");
const tokenPass = ref("");
const tokenSecret = ref("");
const toolBusy = ref("");

async function refreshTokensFromView() {
  try {
    const d = (await pageFetch("/api/settings/view")) as Dict;
    const visual = (d.visual as Dict) ?? {};
    const api = (visual.api as Dict) ?? {};
    tokens.value = Array.isArray(api.tokens) ? (api.tokens as Array<Dict>) : [];
  } catch (_e) {
    /* ignore */
  }
}

async function createToken() {
  toolBusy.value = "token";
  tokenSecret.value = "";
  try {
    const r = (await postJson("/api/settings/api-token/create", {
      name: text(tokenName, "").trim(),
      username: text(tokenUser, "").trim(),
      password: tokenPass,
    })) as Dict;
    if (r.ok === false) {
      notify(text(r.error, "创建失败"), true);
      return;
    }
    tokenSecret.value = text(r.token, "");
    tokens.value = Array.isArray(r.tokens) ? (r.tokens as Array<Dict>) : tokens.value;
    tokenName.value = "";
    tokenPass.value = "";
    notify("已创建 Token，请立即复制保存", false);
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  } finally {
    toolBusy.value = "";
  }
}

async function deleteToken(id: string) {
  try {
    const r = (await postJson("/api/settings/api-token/delete", { id })) as Dict;
    if (r.ok === false) {
      notify(text(r.error, "删除失败"), true);
      return;
    }
    tokens.value = Array.isArray(r.tokens) ? (r.tokens as Array<Dict>) : [];
    notify("Token 已删除", false);
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  }
}

async function copyTokenSecret() {
  try {
    await navigator.clipboard.writeText(tokenSecret.value);
    notify("已复制到剪贴板", false);
  } catch (_e) {
    notify("复制失败，请手动选中复制", true);
  }
}

/* ------- SSO 登录链接 / 通行密钥 ------- */
const authConfigured = ref(false);
const ssoLinks = ref<Array<Dict>>([]);
const passkeys = ref<Array<Dict>>([]);
const ssoName = ref("");
const ssoUser = ref("");
const ssoPass = ref("");
const ssoExpireMode = ref("86400");
const ssoSingleUse = ref(false);
const ssoUrl = ref("");
const passkeyName = ref("");
const passkeyUser = ref("");
const passkeyPass = ref("");

function bytesToB64u(data: Uint8Array): string {
  let bin = "";
  data.forEach((b) => {
    bin += String.fromCharCode(b);
  });
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function b64uToBytes(s: string): Uint8Array {
  const clean = String(s || "").replace(/-/g, "+").replace(/_/g, "/");
  const pad = clean.length % 4 === 0 ? "" : "=".repeat(4 - (clean.length % 4));
  const bin = atob(clean + pad);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
function fmtSsoExpiry(item: Dict): string {
  const at = Number(item.expires_at ?? 0);
  if (!Number.isFinite(at) || at <= 0) return "无限时间";
  const left = Math.max(0, at - Date.now() / 1000);
  if (left <= 0) return "已过期";
  if (left < 3600) return `${Math.max(1, Math.round(left / 60))} 分钟`;
  if (left < 86400) return `${Math.round(left / 3600)} 小时`;
  return `${Math.round(left / 86400)} 天`;
}
function fmtTs(v: unknown): string {
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return "";
  try {
    return new Date(n * 1000).toLocaleString();
  } catch {
    return "";
  }
}

async function refreshAuthListsFromView() {
  try {
    const d = (await pageFetch("/api/settings/view")) as Dict;
    const visual = (d.visual as Dict) ?? {};
    const at = (visual.auth as Dict) ?? {};
    authConfigured.value = !!at.configured;
    ssoLinks.value = Array.isArray(at.sso_links) ? (at.sso_links as Array<Dict>) : [];
    passkeys.value = Array.isArray(at.passkeys) ? (at.passkeys as Array<Dict>) : [];
  } catch (_e) {
    /* ignore */
  }
}

function authReadyForExtra(): boolean {
  return !!form.auth_enabled && authConfigured.value;
}

async function createSsoLink() {
  if (!authReadyForExtra()) {
    notify("需先启用网页登录并配置账号密码", true);
    return;
  }
  const user = text(ssoUser, "").trim();
  const pass = ssoPass;
  if (!user || !pass) {
    notify("请输入网页登录账号和密码（用于创建 SSO 校验码）", true);
    return;
  }
  toolBusy.value = "sso-create";
  ssoUrl.value = "";
  try {
    const body: Dict = {
      name: text(ssoName, "").trim(),
      next: "/",
      single_use: ssoSingleUse.value,
      username: user,
      password: pass,
    };
    const mode = ssoExpireMode.value;
    if (mode === "never") body.expires = "never";
    else if (mode === "custom") body.ttl_min = Math.max(1, 1440);
    else body.ttl_sec = Math.max(60, Number(mode || 86400) || 86400);
    const d = (await postJson("/api/settings/login-link/create", body)) as Dict;
    if (d.ok === false) {
      notify(text(d.error, "创建失败"), true);
      return;
    }
    ssoUrl.value = text(d.url ?? d.path, "");
    ssoLinks.value = Array.isArray(d.links) ? (d.links as Array<Dict>) : ssoLinks.value;
    const expireText = d.expires_at ? fmtTs(d.expires_at) : "无限时间";
    notify(`SSO 链接已创建${text(d.check, "") ? `，校验码 ${text(d.check, "").slice(0, 10)}…` : ""}（${expireText}${ssoSingleUse.value ? "，单次登录" : ""}）`, false);
    ssoName.value = "";
    ssoPass.value = "";
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  } finally {
    toolBusy.value = "";
  }
}

async function deleteSsoLink(check: string) {
  if (!window.confirm("删除该 SSO 校验码后，对应链接立即失效。继续？")) return;
  try {
    const d = (await postJson("/api/settings/login-link/delete", { check })) as Dict;
    if (d.ok === false) {
      notify(text(d.error, "删除失败"), true);
      return;
    }
    ssoLinks.value = Array.isArray(d.links) ? (d.links as Array<Dict>) : [];
    notify("SSO 链接已删除", false);
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  }
}

async function copySsoUrl() {
  try {
    await navigator.clipboard.writeText(ssoUrl.value);
    notify("已复制 SSO 链接", false);
  } catch (_e) {
    notify("复制失败，请手动复制", true);
  }
}

async function createPasskey() {
  if (!authReadyForExtra() || !form.login_passkey) {
    notify("需先启用网页登录且允许通行密钥", true);
    return;
  }
  if (!window.PublicKeyCredential || !navigator.credentials || !navigator.credentials.create) {
    notify("当前浏览器不支持通行密钥创建", true);
    return;
  }
  const user = text(passkeyUser, "").trim();
  const pass = passkeyPass;
  if (!user || !pass) {
    notify("请输入网页登录账号和密码（用于通行密钥登记）", true);
    return;
  }
  toolBusy.value = "passkey-create";
  try {
    const name = text(passkeyName, "").trim();
    const start = (await postJson("/api/settings/passkey/start", { username: user, password: pass, name })) as Dict;
    if (start.ok === false) {
      notify(text(start.error, "启动通行密钥登记失败"), true);
      return;
    }
    const pk = (start.publicKey ?? {}) as Dict;
    const challengeRaw = text(pk.challenge ?? start.challenge ?? start.challenge_token, "");
    const createOptions = {
      publicKey: {
        challenge: b64uToBytes(challengeRaw),
        rp: (pk.rp as Dict) ?? { name: text(start.realm, "XRS"), id: start.rp_id || location.hostname },
        user: {
          id: b64uToBytes(text(((pk.user as Dict)?.id as unknown) ?? "", "")),
          name: text(((pk.user as Dict)?.name as unknown) ?? user, user),
          displayName: text(((pk.user as Dict)?.displayName as unknown) ?? (name || user), name || user),
        },
        pubKeyCredParams: (pk.pubKeyCredParams as Array<Dict>) ?? [{ type: "public-key", alg: -7 }],
        timeout: num(pk.timeout ?? start.timeout_ms ?? 300000, 300000),
        attestation: text(pk.attestation, "none") || "none",
        authenticatorSelection: (pk.authenticatorSelection as Dict) ?? { userVerification: "preferred", residentKey: "preferred" },
        excludeCredentials: ((pk.excludeCredentials as Array<Dict>) ?? []).map((item) => ({
          type: "public-key",
          id: b64uToBytes(text(item.id, "")),
        })),
      },
    } as unknown as CredentialCreationOptions;
    const cred = (await navigator.credentials.create(createOptions)) as PublicKeyCredential | null;
    if (!cred) {
      notify("未获取到通行密钥凭据（可能已取消）", true);
      return;
    }
    const resp = cred.response as AuthenticatorAttestationResponse;
    const finish = (await postJson("/api/settings/passkey/finish", {
      challenge: challengeRaw || start.challenge_token || start.challenge || "",
      id: cred.id || "",
      rawId: bytesToB64u(new Uint8Array(cred.rawId)),
      type: cred.type || "public-key",
      response: {
        clientDataJSON: bytesToB64u(new Uint8Array(resp.clientDataJSON)),
        attestationObject: bytesToB64u(new Uint8Array(resp.attestationObject)),
        userHandle: (resp as unknown as Dict).userHandle ? bytesToB64u(new Uint8Array((resp as unknown as Dict).userHandle as ArrayBuffer)) : "",
      },
      name,
      username: user,
      next: "/",
    })) as Dict;
    if (finish.ok === false) {
      notify(text(finish.error, "通行密钥登记失败"), true);
      return;
    }
    passkeys.value = Array.isArray(finish.passkeys) ? (finish.passkeys as Array<Dict>) : passkeys.value;
    passkeyName.value = "";
    passkeyPass.value = "";
    notify("通行密钥已添加，可直接用于网页登录", false);
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  } finally {
    toolBusy.value = "";
  }
}

async function deletePasskey(id: string) {
  if (!window.confirm("删除该通行密钥后不可恢复。继续？")) return;
  try {
    const d = (await postJson("/api/settings/passkey/delete", { id })) as Dict;
    if (d.ok === false) {
      notify(text(d.error, "删除失败"), true);
      return;
    }
    passkeys.value = Array.isArray(d.passkeys) ? (d.passkeys as Array<Dict>) : [];
    notify("通行密钥已删除", false);
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  }
}

/* ------- 导入 / 导出 ------- */
async function exportData(kind: "settings" | "scan") {
  toolBusy.value = `export-${kind}`;
  try {
    const url = kind === "settings" ? "/api/settings/export/settings" : "/api/settings/export/scan-data";
    const d = (await pageFetch(url)) as Dict;
    const fileName = kind === "settings" ? `xrs-settings-${Date.now()}.json` : `xrs-scan-data-${Date.now()}.json`;
    const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    notify(`已导出：${fileName}`, false);
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  } finally {
    toolBusy.value = "";
  }
}

const importSettingsInput = ref<HTMLInputElement | null>(null);
const importScanInput = ref<HTMLInputElement | null>(null);
function pickImport(kind: "settings" | "scan") {
  if (kind === "settings") importSettingsInput.value?.click();
  else importScanInput.value?.click();
}

async function importFile(kind: "settings" | "scan", ev: Event) {
  const input = ev.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  toolBusy.value = `import-${kind}`;
  try {
    const raw = await file.text();
    const payload = JSON.parse(raw);
    const body: Dict = { payload };
    if (kind === "scan") body.mode = "merge";
    const url = kind === "settings" ? "/api/settings/import/settings" : "/api/settings/import/scan-data";
    const r = (await postJson(url, body)) as Dict;
    if (r.ok === false) {
      notify(text(r.error, "导入失败"), true);
      return;
    }
    notify(`导入成功${r.reload_msg ? `：${text(r.reload_msg)}` : ""}`, false);
    await load();
  } catch (e) {
    notify(e instanceof Error ? e.message : `JSON 解析失败：${String(e)}`, true);
  } finally {
    toolBusy.value = "";
  }
}

/* ------- EULA / 系统服务 / 浏览器偏好 ------- */
const eulaAccepted = ref(false);
const eulaSetPath = ref("EULA.set");
const eulaSource = ref("");
const serviceStatus = ref<Dict>({});
const serviceMsg = ref("");
const newFwParse = ref(true);

function applyEula(e: Dict) {
  eulaAccepted.value = !!e.accepted;
  eulaSetPath.value = text(e.set_path, "EULA.set");
  eulaSource.value = text(e.source_url, "");
}

async function revokeEula() {
  if (!window.confirm("撤回后会立刻回到许可协议确认页。确定继续吗？")) return;
  try {
    const d = (await postJson("/api/eula/revoke", {})) as Dict;
    notify("已撤回 EULA 同意状态", false);
    applyEula(d);
    window.setTimeout(() => {
      window.location.href = "/eula?next=/settings";
    }, 700);
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  }
}

async function loadSystemServiceStatus() {
  try {
    const d = (await pageFetch("/api/settings/systemd/status")) as Dict;
    serviceStatus.value = d ?? {};
    const iw = (d.iw ?? {}) as Dict;
    const lines: string[] = [];
    if (d.supported) {
      if (d.registered) {
        lines.push(d.running_as_root ? "systemd 已注册；当前运行权限过高，建议修复。" : d.service_uses_dedicated_user && d.dedicated_user_exists ? "systemd 服务已注册，专用账号运行正常。" : "systemd 已注册，但未使用 rid 专用账号。");
      } else {
        lines.push("systemd 尚未注册服务。");
      }
      if (d.registered && d.unit_matches === false) lines.push("当前服务文件与页面生成参数不一致，可点「注册/更新服务」修正。");
    } else {
      lines.push(`systemd 不可用${text(d.reason, "") ? `，${text(d.reason, "")}` : ""}`);
      if (text(d.manual_hint, "")) lines.push(text(d.manual_hint, ""));
    }
    const wirelessToolsMissing = !(iw.available && iw.hostapd_available);
    if (iw.message && wirelessToolsMissing) lines.push(text(iw.message, ""));
    if (iw.manual_hint && wirelessToolsMissing) lines.push(text(iw.manual_hint, ""));
    if (text(d.last_error, "")) lines.push(`状态读取失败：${text(d.last_error, "")}`);
    serviceMsg.value = lines.join("\n") || "运行状态正常。";
  } catch (e) {
    serviceMsg.value = `服务状态读取失败：${e instanceof Error ? e.message : String(e)}`;
  }
}

async function refreshServiceStatus() {
  toolBusy.value = "svc-refresh";
  try {
    await loadSystemServiceStatus();
  } finally {
    toolBusy.value = "";
  }
}

function viewEula() {
  window.open("/eula?next=/settings", "_blank", "noopener,noreferrer");
}

function saveNewFwParse() {
  try {
    localStorage.setItem("rid_new_firmware_parse_enabled", newFwParse.value ? "1" : "0");
  } catch (_e) {
    /* ignore */
  }
  notify("页面偏好已保存到当前浏览器", false);
}

/* ------- 程序更新 ------- */
const auEnabled = ref(true);
const auForce = ref(false);
const auMirror = ref("github");
const auCustomMirror = ref("");
const auState = ref<Dict>({});
const auMirrorOptions = ref<Array<Dict>>([]);
const auFileInput = ref<HTMLInputElement | null>(null);
const auFile = ref<File | null>(null);
const auPrep = ref<Dict>({});
const auUploading = ref(false);
const auBusy = computed(() => !!(auState.value.running || auState.value.download_running || auState.value.installing));
const auStaged = computed(() => !!auState.value.staged_ready);
const auHasUpdate = computed(() => !!auState.value.update_available);
const auSupported = computed(() => auState.value.install_supported !== false);
const auSudoBlocked = computed(() => !!(auState.value.requires_sudo && auState.value.can_elevate === false));

function formatBytesUi(bytes: unknown): string {
  let n = Number(bytes ?? 0);
  if (!Number.isFinite(n) || n < 0) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let idx = 0;
  while (n >= 1024 && idx < units.length - 1) {
    n /= 1024;
    idx += 1;
  }
  return `${n.toFixed(n >= 100 || idx === 0 ? 0 : 1)} ${units[idx]}`;
}

const AU_DEFAULT_MIRRORS: Array<{ key: string; label: string }> = [
  { key: "github", label: "GitHub 官方" },
  { key: "gh-proxy", label: "gh-proxy.org" },
  { key: "custom", label: "自定义镜像" },
];

function auMirrorItems(): Array<{ title: string; value: string }> {
  const list = auMirrorOptions.value.length ? auMirrorOptions.value : AU_DEFAULT_MIRRORS;
  return (list as Array<Dict>).map((o) => ({ title: text(o.label, text(o.key, "")), value: text(o.key, "") }));
}

async function loadAuState() {
  try {
    const d = (await pageFetch("/api/settings/view")) as Dict;
    const au = (((d.visual as Dict) ?? {}) as Dict).app_update as Dict | undefined;
    if (!au) return;
    auState.value = ((au.state as Dict) ?? {}) as Dict;
    const opts = Array.isArray((au as Dict).mirror_options)
      ? ((au as Dict).mirror_options as Array<Dict>)
      : Array.isArray(auState.value.mirror_options)
        ? (auState.value.mirror_options as Array<Dict>)
        : [];
    auMirrorOptions.value = opts;
  } catch (_e) {
    /* ignore */
  }
}

const auStateText = computed(() => {
  const s = auState.value;
  const currentTag = text(s.current_tag, "");
  const latestTag = text(s.latest_tag, "");
  const staged = text(s.staged_asset_name ?? s.asset_name, "安装包");
  const percent = Number(s.download_percent ?? 0);
  const lines: string[] = [];
  lines.push(`当前版本 ${currentTag || "-"}${latestTag ? ` | 检查到最新 ${latestTag}` : ""}`);
  if (s.running) {
    lines.push("任务进行中…");
  } else if (s.download_running) {
    lines.push(`后台下载中: ${staged}${percent > 0 ? ` ${percent.toFixed(percent >= 10 ? 0 : 1)}%` : ""}`);
    if (Number(s.download_total_bytes ?? 0) > 0) {
      lines.push(`进度: ${formatBytesUi(s.downloaded_bytes)} / ${formatBytesUi(s.download_total_bytes)}`);
    }
  } else if (s.installing) {
    lines.push(`更新状态: ${text(s.install_message ?? s.install_status, "进行中")}`);
  } else if (s.staged_ready) {
    lines.push(`安装包已就绪: ${staged}`);
    if (text(s.staged_source, "")) lines.push(`来源: ${text(s.staged_source, "")}`);
    if (text(s.staged_sha256 ?? s.sha256, "")) lines.push(`SHA256: ${text(s.staged_sha256 ?? s.sha256, "").slice(0, 12)}…`);
  } else if (text(s.last_error, "")) {
    lines.push(`检查/更新失败: ${text(s.last_error, "")}`);
  } else if (s.checked) {
    lines.push(s.update_available ? "发现新版本，下载或上传安装包后即可安装。" : "当前已是检查到的最新版本。");
  } else {
    lines.push("启用后自动检查 GitHub Release；下载、上传和安装都需要手动确认。");
  }
  if (s.install_supported === false && text(s.support_reason, "")) lines.push(`当前环境: ${text(s.support_reason, "")}`);
  if (text(s.mirror, "") && text(s.mirror, "") !== "github") lines.push(`镜像: ${text(s.mirror_url ?? s.mirror, "")}`);
  if (s.force_update) lines.push("强制更新: 已启用，校验失败的安装包也可继续安装。");
  if (s.staged_ready && s.staged_verified === false) lines.push("安装包校验: 未通过或缺少 SHA256，继续安装属于强制更新。");
  if (s.staged_ready && s.requires_sudo) {
    if (s.can_elevate === false) lines.push(String(s.sudo_blocked_reason ?? "当前服务进程无法 sudo 提权，请通过 SSH/root 执行安装。"));
    else lines.push("安装时会按需询问 sudo 密码。");
  }
  return lines.join("\n");
});

async function checkAppUpdateNow() {
  toolBusy.value = "au-check";
  try {
    const d = (await postJson("/api/settings/app-update/check", {})) as Dict;
    if (d.ok === false) {
      notify(text(d.error, "版本检查失败"), true);
      return;
    }
    auState.value = ((d.state as Dict) ?? {}) as Dict;
    notify((auState.value.update_available as boolean) ? "发现新版本，请手动更新" : "版本检查完成", false);
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  } finally {
    toolBusy.value = "";
  }
}

async function downloadAppUpdateNow() {
  toolBusy.value = "au-download";
  try {
    const d = (await postJson("/api/settings/app-update/download", {})) as Dict;
    if (d.ok === false) {
      notify(text(d.error, "启动下载失败"), true);
      return;
    }
    auState.value = ((d.state as Dict) ?? {}) as Dict;
    notify(text(d.message, "安装包后台下载已开始"), false);
    void pollAuState();
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  } finally {
    toolBusy.value = "";
  }
}

async function pollAuState() {
  for (let i = 0; i < 30; i++) {
    await new Promise((resolve) => setTimeout(resolve, 2500));
    await loadAuState().catch(() => {});
    if (!auBusy.value) break;
  }
}

async function startAppUpdateNow() {
  const s = auState.value;
  if (!s.staged_ready) {
    notify("请先下载或上传安装包，并等待 SHA256 校验通过", true);
    return;
  }
  const target = text(s.staged_asset_name ?? s.asset_name, "安装包");
  if (!window.confirm(`将安装已通过 SHA256 校验的安装包：${target}。更新期间服务会短暂重启，是否继续？`)) return;
  toolBusy.value = "au-start";
  try {
    const d = (await postJson("/api/settings/app-update/start", { confirm: true })) as Dict;
    if (d.ok === false) {
      notify(text(d.error, "安装失败"), true);
      return;
    }
    auState.value = Object.assign({}, auState.value, { installing: true, install_status: "preparing" }, (d.state as Dict) ?? {});
    notify(text(d.message, "更新进程已启动，服务将短暂重启"), false);
    void pollAuState();
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  } finally {
    toolBusy.value = "";
  }
}

function triggerAuUpload() {
  if (auFileInput.value) auFileInput.value.click();
}

async function onAuFileChange(ev: Event) {
  const input = ev.target as HTMLInputElement;
  const f = input.files?.[0] ?? null;
  auFile.value = f;
  auPrep.value = {};
  if (!f) return;
  const maxBytes = Number(auState.value.max_upload_bytes ?? 0);
  if (maxBytes > 0 && f.size > maxBytes) {
    notify(`安装包过大，当前上限为 ${formatBytesUi(maxBytes)}`, true);
    if (input) input.value = "";
    auFile.value = null;
    return;
  }
  auUploading.value = true;
  try {
    const d = (await postJson("/api/settings/app-update/upload/prepare", { file_name: String(f.name || "package.bin"), file_size: Number(f.size || 0) })) as Dict;
    if (d.ok === false) {
      notify(text(d.error, "预检查失败"), true);
      return;
    }
    auPrep.value = ((d.prepare as Dict) ?? {}) as Dict;
    if (d.state) auState.value = (d.state as Dict) ?? auState.value;
    notify(`预检查完成：匹配资产 ${text(auPrep.value.asset_name, "-")}`, false);
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  } finally {
    auUploading.value = false;
  }
}

async function confirmAuUpload() {
  const f = auFile.value;
  const token = text(auPrep.value.token, "");
  if (!f || !token) {
    notify("请先选择文件并完成预检查", true);
    return;
  }
  auUploading.value = true;
  try {
    const headers = new Headers();
    headers.set("X-XRS-Page", "1");
    headers.set("Content-Type", "application/octet-stream");
    headers.set("X-XRS-Upload-Name", encodeURIComponent(String(f.name || "package.bin")));
    headers.set("X-XRS-Upload-Token", token);
    const r = await fetch("/api/settings/app-update/upload", { method: "POST", headers, body: f, cache: "no-store" });
    const txt = await r.text();
    let d: Dict = {};
    try {
      d = JSON.parse(txt) as Dict;
    } catch (_e) {
      d = { error: txt || `HTTP ${r.status}` };
    }
    if (!r.ok || d.ok === false) {
      throw new Error(text(d.error, `HTTP ${r.status}`));
    }
    auState.value = ((d.state as Dict) ?? auState.value) as Dict;
    notify(text(d.message, "安装包已上传并通过校验"), false);
    if (auFileInput.value) auFileInput.value.value = "";
    auFile.value = null;
    auPrep.value = {};
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  } finally {
    auUploading.value = false;
  }
}

async function maintenance(op: "reidentify" | "systemd" | "iw" | "security" | "models") {
  if (op === "reidentify") {
    const ok = window.confirm("对最近记录重新执行机型/SN 识别？");
    if (!ok) return;
  } else if (op === "systemd" || op === "iw" || op === "security") {
    const label = op === "systemd" ? "注册为 systemd 服务" : op === "iw" ? "安装无线工具(iw)" : "修复运行权限/安全项";
    const ok = window.confirm(`执行「${label}」？（可能需要 root/管理员权限）`);
    if (!ok) return;
  }
  toolBusy.value = op;
  try {
    let r: Dict;
    if (op === "reidentify") {
      r = (await postJson("/api/settings/history/reidentify-recent", { limit: 100 })) as Dict;
      notify(r.ok === false ? text(r.error, "执行失败") : text(r.summary ?? "re-identify 完成"), r.ok === false);
    } else if (op === "models") {
      r = (await postJson("/api/settings/models/update", { url: text(form.model_url, "") })) as Dict;
      const modelState = r.state && typeof r.state === "object" ? (r.state as Dict) : null;
      const modelMsg = r.ok === false ? text(r.error, "更新失败") : text(modelState?.message ?? "机型库在线更新完成", "更新完成");
      notify(modelMsg, r.ok === false);
    } else {
      const urlMap: Dict = { systemd: "/api/settings/systemd/register", iw: "/api/settings/iw/install", security: "/api/settings/security/repair" };
      r = (await postJson(String(urlMap[op]), { confirm: true })) as Dict;
      const msg = text(r.message ?? (r.ok ? "操作成功" : r.error), "");
      notify(msg, r.ok === false);
    }
    await refreshTokensFromView();
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  } finally {
    toolBusy.value = "";
  }
}

/* ------- Raw 配置文件 ------- */
const rawFiles = ref<Array<{ title: string; path: string }>>([]);
const rawPath = ref("");
const rawText = ref("");
const rawBusy = ref(false);

function flattenRaw(nodes: Array<Dict>, out: Array<{ title: string; path: string }>, base = "") {
  for (const node of nodes) {
    const rel = text(node.rel_path ?? node.name ?? "", "");
    const full = rel ? (base ? `${base}/${rel}` : rel) : rel;
    if (String(node.type) === "dir") {
      flattenRaw(Array.isArray(node.children) ? (node.children as Array<Dict>) : [], out, full || base);
    } else {
      out.push({ title: full || text(node.path, ""), path: text(node.path, full) });
    }
  }
}

async function loadRawTree() {
  try {
    const d = (await pageFetch("/api/config/tree")) as Dict;
    const arr: Array<{ title: string; path: string }> = [];
    flattenRaw(Array.isArray(d.tree) ? (d.tree as Array<Dict>) : [], arr);
    rawFiles.value = arr.sort((a, b) => a.title.localeCompare(b.title));
  } catch (e) {
    notify(`无法读取配置目录：${e instanceof Error ? e.message : String(e)}`, true);
  }
}

async function openRaw(path: string) {
  if (!path) return;
  rawBusy.value = true;
  rawText.value = "";
  try {
    const d = (await pageFetch(`/api/config/file?path=${encodeURIComponent(path)}`)) as Dict;
    if (d.ok === false) {
      notify(text(d.error, "读取失败"), true);
      return;
    }
    rawPath.value = path;
    rawText.value = String(d.text ?? "");
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  } finally {
    rawBusy.value = false;
  }
}

async function saveRaw() {
  if (!rawPath.value) {
    notify("请先选择配置文件", true);
    return;
  }
  rawBusy.value = true;
  try {
    const r = (await postJson("/api/settings/raw/save", { path: rawPath.value, text: rawText.value })) as Dict;
    if (r.ok === false) {
      notify(text(r.error, "保存失败"), true);
      return;
    }
    notify("Raw 配置已保存", false);
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  } finally {
    rawBusy.value = false;
  }
}

async function deleteRaw() {
  if (!rawPath.value) return;
  const ok = window.confirm(`确定删除配置文件 ${rawPath.value}？`);
  if (!ok) return;
  rawBusy.value = true;
  try {
    const r = (await postJson("/api/config/file/delete", { path: rawPath.value })) as Dict;
    if (r.ok === false) {
      notify(text(r.error, "删除失败"), true);
      return;
    }
    notify("文件已删除", false);
    rawPath.value = "";
    rawText.value = "";
    await loadRawTree();
  } catch (e) {
    notify(e instanceof Error ? e.message : String(e), true);
  } finally {
    rawBusy.value = false;
  }
}

/* ------- 主机负载 / 运行时日志 ------- */
const metricWin = ref("12h");
const metricSeries = ref("load");
const metricItems = ref<Array<Dict>>([]);
const metricMeta = reactive<Dict>({});
const logKind = ref("operation_logs");
const logLines = ref<string[]>([]);
const logKinds = [
  { title: "操作日志", value: "operation_logs" },
  { title: "系统日志", value: "system_logs" },
  { title: "扫描日志", value: "scan_logs" },
  { title: "事件日志", value: "event_logs" },
];

async function loadMetrics() {
  try {
    const d = (await pageFetch(`/api/settings/metrics?window=${encodeURIComponent(metricWin.value)}`)) as Dict;
    metricItems.value = Array.isArray(d.items) ? (d.items as Array<Dict>) : [];
    Object.assign(metricMeta, {
      enabled: !!d.enabled,
      window: text(d.window_label, metricWin.value),
      count: num(d.count, metricItems.value.length),
      source: text(d.temperature_source_label, "-"),
      retention: num(d.retention_days, 0),
    });
  } catch (e) {
    notify(`指标读取失败：${e instanceof Error ? e.message : String(e)}`, true);
  }
}

function seriesNums(key: string): Array<{ x: number; y: number }> {
  const pts: Array<{ x: number; y: number }> = [];
  metricItems.value.forEach((it, i) => {
    const y = Number(it[key]);
    if (Number.isFinite(y)) pts.push({ x: i, y });
  });
  return pts;
}

function metricPath(): string {
  const key = metricSeries.value;
  const pts = seriesNums(key);
  if (!pts.length) return "";
  const W = 640;
  const H = 130;
  const pad = 6;
  const ys = pts.map((p) => p.y);
  let minY = Math.min(...ys);
  let maxY = Math.max(...ys);
  if (maxY - minY < 1e-6) {
    minY -= 1;
    maxY += 1;
  }
  const n = pts.length;
  const sx = (i: number) => (n > 1 ? pad + (i * (W - pad * 2)) / (n - 1) : W / 2);
  const sy = (y: number) => H - pad - ((y - minY) * (H - pad * 2)) / (maxY - minY);
  return pts.map((p, i) => `${sx(i).toFixed(1)},${sy(p.y).toFixed(1)}`).join(" ");
}

function seriesMetaText(): string {
  const key = metricSeries.value;
  const pts = seriesNums(key);
  if (!pts.length) return "暂无采样";
  const last = pts[pts.length - 1].y;
  const min = Math.min(...pts.map((p) => p.y));
  const max = Math.max(...pts.map((p) => p.y));
  return `最新 ${last.toFixed(1)} · 最小 ${min.toFixed(1)} · 最大 ${max.toFixed(1)}`;
}

const metricSeriesMeta = computed(() => seriesMetaText());

async function loadRuntime() {
  try {
    const d = (await pageFetch("/api/settings/runtime?limit=100")) as Dict;
    const arr = Array.isArray(d[logKind.value]) ? (d[logKind.value] as Array<unknown>) : [];
    logLines.value = arr.slice(-80).map((x) => String(x));
  } catch (e) {
    logLines.value = [`读取失败：${e instanceof Error ? e.message : String(e)}`];
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
    <input
      ref="importSettingsInput"
      type="file"
      accept=".json,application/json"
      class="hidden-file"
      @change="importFile('settings', $event)"
    />
    <input
      ref="importScanInput"
      type="file"
      accept=".json,application/json"
      class="hidden-file"
      @change="importFile('scan', $event)"
    />
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
            <template v-if="hostCpuMem">
              <dt>CPU / 内存</dt><dd class="mono">{{ hostCpuMem }}</dd>
            </template>
            <template v-if="hostLoad">
              <dt>负载 1/5/15</dt><dd class="mono">{{ hostLoad }}</dd>
            </template>
            <template v-if="hostTemp">
              <dt>温度</dt><dd class="mono">{{ hostTemp }}<template v-if="hostTempSrc">（{{ hostTempSrc }}）</template></dd>
            </template>
            <template v-if="hostUptime">
              <dt>运行时长</dt><dd>{{ hostUptime }}</dd>
            </template>
            <template v-if="hostIps.length">
              <dt>本机 IP</dt><dd class="mono wrap">{{ hostIps.join(", ") }}</dd>
            </template>
          </dl>
          <VBtn size="small" variant="tonal" @click="refreshHost">刷新主机状态</VBtn>
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

        <!-- 网卡绑定与 AP 热点 -->
        <section class="st-card st-wide">
          <h2>网卡绑定与 AP 热点</h2>
          <VChip variant="tonal" label class="mb-2">
            保存设置后，可在下方“应用到系统”真正调整网卡角色与 AP 热点（需 root 权限）。
          </VChip>
          <div v-if="!netIfaces.length" class="muted-note mb-2">未检测到网卡</div>
          <div v-else v-for="row in netIfaces" :key="text(row.name, '')" class="bind-row">
            <div class="bind-iface mono">{{ text(row.name, "") }}</div>
            <div class="bind-meta">{{ netIfaceMeta(row) }}</div>
            <VSelect
              :model-value="netRoleOf(text(row.name, ''))"
              :items="netRoles"
              item-title="label"
              item-value="key"
              density="compact"
              variant="outlined"
              hide-details
              class="bind-role"
              @update:model-value="setNetRole(text(row.name, ''), $event)"
            />
          </div>
          <VDivider class="my-3" />
          <div class="text-caption text-medium-emphasis mb-1">AP 热点参数（随配置保存生效）</div>
          <div class="ap-grid mb-1">
            <VTextField v-model="netAp.ssid" label="SSID" density="compact" variant="outlined" hide-details />
            <VTextField v-model="netAp.password" label="密码（留空为开放热点）" type="password" density="compact" variant="outlined" hide-details />
            <VTextField v-model.number="netAp.channel" label="信道" type="number" min="1" max="196" density="compact" variant="outlined" hide-details />
            <VSelect
              v-model="netAp.uplink_iface"
              label="桥接出口（不共享 Internet）"
              :items="[{ title: '不共享 Internet', value: '' }, ...netIfaces.map((it) => ({ title: netUplinkTitle(it), value: text(it.name, '') }))]"
              item-title="title"
              item-value="value"
              density="compact"
              variant="outlined"
              hide-details
            />
          </div>
          <div class="d-flex flex-wrap ga-2 mb-3">
            <VChip variant="tonal" label class="mono">AP 地址 {{ netAp.address || "172.16.0.1" }}</VChip>
            <VChip variant="tonal" label class="mono">网段 {{ netAp.cidr || "172.16.0.1/24" }}</VChip>
            <VChip variant="tonal" label class="mono">DHCP {{ netAp.dhcp_start || "172.16.0.20" }} - {{ netAp.dhcp_end || "172.16.0.240" }}</VChip>
            <VChip variant="tonal" label class="mono">网页服务 http://{{ netApHttpSummary() }}</VChip>
          </div>
          <div class="d-flex align-center ga-2">
            <div class="flex-spacer" />
            <VBtn
              size="small"
              color="warning"
              variant="tonal"
              :loading="toolBusy === 'net-apply'"
              @click="applyNetworkBindings"
            >
              保存设置后再应用到系统
            </VBtn>
          </div>
          <pre v-if="applyNet" class="log-box mt-2">{{ applyNet }}</pre>
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
            <VTextField v-model.number="form.map_idle" label="自动回中冷却(s)" type="number" min="5" max="600" density="compact" variant="outlined" hide-details />
          </div>
          <div class="mb-3">
            <VTextField v-model="form.map_tile_url" label="地图瓦片模板 URL（需含 {z}/{x}/{y}）" density="compact" variant="outlined" hide-details />
          </div>
          <div class="d-flex ga-2">
            <VTextField v-model="form.map_tile_subdomains" label="子域名(逗号分隔)" density="compact" variant="outlined" hide-details />
            <VTextField v-model="form.map_tile_attribution" label="版权署名" density="compact" variant="outlined" hide-details />
            <VTextField v-model.number="form.map_tile_max_native_zoom" label="原生最大缩放" type="number" min="1" max="30" density="compact" variant="outlined" hide-details />
          </div>
          <div class="mt-3">
            <VTextField v-model="form.dji_lookup_url" label="DJI 查询 URL" density="compact" variant="outlined" hide-details />
          </div>
        </section>

        <!-- 采集高级 -->
        <section class="st-card">
          <h2>采集高级</h2>
          <div class="sw-grid mb-2">
            <VSwitch v-model="form.hop" label="信道跳频" color="primary" hide-details />
            <VSwitch v-model="form.hop_5g" label="跳频含 5G" color="primary" hide-details />
            <VSwitch v-model="form.scan_wifi_fast" label="WiFi 快速扫描" color="primary" hide-details />
            <VSwitch v-model="form.auto_self_heal" label="自动自愈" color="primary" hide-details />
            <VSwitch v-model="form.change_on_rssi" label="RSSI 变化更新" color="primary" hide-details />
            <VSwitch v-model="form.change_on_payload" label="载荷变化更新" color="primary" hide-details />
            <VSwitch v-model="form.debug" label="调试输出" color="primary" hide-details />
          </div>
          <div class="num-grid">
            <VTextField v-model.number="form.dwell_2g" label="2.4G 停留(ms)" type="number" min="1" density="compact" variant="outlined" hide-details />
            <VTextField v-model.number="form.dwell_5g" label="5G 停留(ms)" type="number" min="1" density="compact" variant="outlined" hide-details />
            <VTextField v-model.number="form.settle" label="跳频稳定(ms)" type="number" min="0" density="compact" variant="outlined" hide-details />
            <VTextField v-model.number="form.dwell_on_hit" label="命中停留(ms)" type="number" min="0" density="compact" variant="outlined" hide-details />
            <VTextField v-model.number="form.hit_cap" label="命中上限(ms)" type="number" min="0" density="compact" variant="outlined" hide-details />
            <VTextField v-model.number="form.rssi_delta" label="RSSI 变化阈值" type="number" min="1" density="compact" variant="outlined" hide-details />
            <VTextField v-model.number="form.time" label="输出周期(s)" type="number" min="0" step="0.1" density="compact" variant="outlined" hide-details />
            <VTextField v-model.number="form.track_points_limit" label="轨迹点数上限" type="number" min="10" density="compact" variant="outlined" hide-details />
          </div>
        </section>

        <!-- Token API -->
        <section class="st-card">
          <h2>Token API</h2>
          <VSwitch v-model="form.api_enabled" label="启用 Token API" color="primary" hide-details class="mb-3" />
          <VSwitch v-model="form.api_whitelist_enabled" label="启用访问名单" color="primary" hide-details class="mb-2" />
          <VSelect
            v-model="form.api_whitelist_mode"
            label="名单模式"
            :items="[{ title: '允许名单', value: 'allow' }, { title: '拒绝名单', value: 'deny' }]"
            :disabled="!form.api_whitelist_enabled"
            density="compact"
            variant="outlined"
            hide-details
            class="mb-2"
          />
          <div v-for="(addr, i) in form.api_whitelist" :key="i" class="d-flex ga-2 mb-2">
            <VTextField v-model="form.api_whitelist[i]" label="IP / CIDR" density="compact" variant="outlined" hide-details class="flex-grow-1" />
            <VBtn icon="mdi-delete-outline" size="small" variant="text" @click="removeApiEntry(i)" />
          </div>
          <VBtn size="small" variant="outlined" color="primary" @click="addApiEntry">添加地址</VBtn>

          <VDivider class="my-3" />
          <div class="text-caption text-medium-emphasis mb-1">Token 列表</div>
          <div v-if="!tokens.length" class="muted-note mb-2">暂无 Token</div>
          <div v-for="t in tokens" :key="text(t.id)" class="d-flex align-center ga-2 mb-1">
            <VChip size="x-small" variant="tonal" label :color="t.active ? 'success' : 'default'">
              {{ t.enabled ? "启用" : "停用" }}
            </VChip>
            <span class="mono token-name">{{ text(t.name) }}</span>
            <span class="muted-note token-id mono">{{ text(t.id).slice(0, 10) }}…</span>
            <VBtn icon="mdi-delete-outline" size="x-small" variant="text" @click="deleteToken(String(t.id))" />
          </div>

          <VDivider class="my-3" />
          <div class="text-caption text-medium-emphasis mb-1">创建新 Token（需网页登录已启用并填写账号密码）</div>
          <div class="d-flex ga-2 mb-2">
            <VTextField v-model="tokenName" label="名称(可选)" density="compact" variant="outlined" hide-details />
            <VTextField v-model="tokenUser" label="网页账号" density="compact" variant="outlined" hide-details />
            <VTextField v-model="tokenPass" label="网页密码" type="password" density="compact" variant="outlined" hide-details />
          </div>
          <VBtn size="small" color="primary" :loading="toolBusy === 'token'" @click="createToken">创建 Token</VBtn>
          <VAlert v-if="tokenSecret" type="success" variant="tonal" class="mt-2">
            <div class="d-flex align-center ga-2">
              <code class="mono token-secret">{{ tokenSecret }}</code>
              <VBtn size="x-small" variant="outlined" @click="copyTokenSecret">复制</VBtn>
            </div>
            <div class="muted-note mt-1">Token 只显示这一次，请立即保存。</div>
          </VAlert>
        </section>

        <!-- 鉴权 -->
        <section class="st-card">
          <h2>网页鉴权</h2>
          <VSwitch v-model="form.auth_enabled" label="启用网页登录" color="primary" hide-details class="mb-3" />
          <div class="d-flex ga-2 mb-3">
            <VTextField v-model="form.auth_username" label="用户名（留空保持不变）" density="compact" variant="outlined" hide-details />
            <VTextField v-model="form.auth_password" label="密码（留空保持不变）" type="password" density="compact" variant="outlined" hide-details />
          </div>
          <div class="d-flex ga-2 mb-3">
            <VTextField v-model="form.auth_realm" label="Realm" density="compact" variant="outlined" hide-details />
            <VTextField v-model.number="form.auth_ttl" label="会话时长(分)" type="number" min="1" max="10080" density="compact" variant="outlined" hide-details />
          </div>
          <div class="sw-grid">
            <VSwitch v-model="form.login_password" label="允许密码登录" color="primary" hide-details />
            <VSwitch v-model="form.login_passkey" label="允许通行密钥" color="primary" hide-details />
          </div>
        </section>

        <!-- SSO 登录链接 -->
        <section class="st-card">
          <h2>SSO 登录链接</h2>
          <VChip v-if="!form.auth_enabled || !authConfigured" color="warning" variant="tonal" label class="mb-2">
            需先启用网页登录并配置账号密码
          </VChip>
          <VChip v-else variant="tonal" label class="mb-2">SSO 链接优先于其他登录方式，可一键登录</VChip>
          <div v-if="!ssoLinks.length" class="muted-note mb-2">暂无 SSO 登录链接</div>
          <div v-else v-for="(item, idx) in ssoLinks" :key="text(item.check, String(idx))" class="list-box mb-2">
            <div class="d-flex align-center ga-2">
              <span class="mono flex-grow-1">{{ text(item.name, `SSO 链接 ${idx + 1}`) }}</span>
              <VChip size="x-small" variant="tonal" label :color="String(item.status ?? (item.active === false ? 'expired' : 'active')) === 'active' ? 'success' : 'default'">
                {{ text(item.status_label ?? (String(item.status ?? (item.active === false ? "expired" : "active")) === "active" ? "可用" : "不可用"), "-") }}
              </VChip>
              <VChip size="x-small" variant="tonal" label>{{ fmtSsoExpiry(item) }}</VChip>
              <VChip size="x-small" variant="tonal" label>{{ item.single_use ? "单次" : "多次" }}</VChip>
              <VChip v-if="text(item.check, '')" size="x-small" variant="tonal" label class="mono">{{ text(item.check, "").slice(0, 12) }}…</VChip>
              <VBtn icon="mdi-delete-outline" size="x-small" variant="text" @click="deleteSsoLink(text(item.check, ''))" />
            </div>
          </div>
          <VDivider class="my-3" />
          <div class="d-flex ga-2 mb-2">
            <VTextField v-model="ssoName" label="链接名称(可选)" density="compact" variant="outlined" hide-details class="flex-grow-1" />
            <VSelect
              v-model="ssoExpireMode"
              label="有效期"
              :items="[
                { title: '1 小时', value: '3600' },
                { title: '1 天', value: '86400' },
                { title: '7 天', value: '604800' },
                { title: '无限期', value: 'never' },
              ]"
              density="compact"
              variant="outlined"
              hide-details
            />
            <VSwitch v-model="ssoSingleUse" label="单次登录" color="primary" hide-details class="ms-1" />
          </div>
          <div class="d-flex ga-2 mb-2">
            <VTextField v-model="ssoUser" label="网页账号" density="compact" variant="outlined" hide-details />
            <VTextField v-model="ssoPass" label="网页密码" type="password" density="compact" variant="outlined" hide-details />
            <VBtn size="small" color="primary" :disabled="!form.auth_enabled || !authConfigured" :loading="toolBusy === 'sso-create'" @click="createSsoLink">创建链接</VBtn>
          </div>
          <VAlert v-if="ssoUrl" type="success" variant="tonal" class="mt-1">
            <div class="d-flex align-center ga-2">
              <code class="mono token-secret">{{ ssoUrl }}</code>
              <VBtn size="x-small" variant="outlined" @click="copySsoUrl">复制</VBtn>
            </div>
            <div class="muted-note mt-1">链接仅显示一次，请立即保存。</div>
          </VAlert>
        </section>

        <!-- 通行密钥 -->
        <section class="st-card">
          <h2>通行密钥 (Passkey)</h2>
          <VChip v-if="!form.auth_enabled || !authConfigured" color="warning" variant="tonal" label class="mb-2">需先启用网页登录并配置账号密码</VChip>
          <VChip v-else-if="!form.login_passkey" color="warning" variant="tonal" label class="mb-2">网页鉴权需允许通行密钥</VChip>
          <VChip v-else variant="tonal" label class="mb-2">已登记的通行密钥可以直接登录网页</VChip>
          <div v-if="!passkeys.length" class="muted-note mb-2">暂无通行密钥</div>
          <div v-else v-for="(item, idx) in passkeys" :key="text(item.id, String(idx))" class="list-box mb-2">
            <div class="d-flex align-center ga-2">
              <div class="flex-grow-1">
                <div class="d-flex align-center ga-2">
                  <span class="mono">{{ text(item.name, `通行密钥 ${idx + 1}`) }}</span>
                  <VChip size="x-small" variant="tonal" label :color="item.enabled === false ? 'default' : 'success'">{{ item.enabled === false ? "已停用" : "已启用" }}</VChip>
                  <VChip size="x-small" variant="tonal" label>签名计数 {{ num(item.sign_count, 0) }}</VChip>
                </div>
                <div class="muted-note">
                  {{
                    `创建时间 ${text(item.created_ts ? fmtTs(item.created_ts) : "-", "-")} | 上次使用 ${text(item.last_used_ts ? fmtTs(item.last_used_ts) : "未使用", "未使用")}`
                  }}
                </div>
              </div>
              <VBtn icon="mdi-delete-outline" size="x-small" variant="text" @click="deletePasskey(text(item.id, ''))" />
            </div>
          </div>
          <VDivider class="my-3" />
          <div class="d-flex ga-2 mb-2">
            <VTextField v-model="passkeyName" label="密钥名称(可选)" density="compact" variant="outlined" hide-details class="flex-grow-1" />
            <VTextField v-model="passkeyUser" label="网页账号" density="compact" variant="outlined" hide-details />
            <VTextField v-model="passkeyPass" label="网页密码" type="password" density="compact" variant="outlined" hide-details />
          </div>
          <VBtn
            size="small"
            color="primary"
            :disabled="!form.auth_enabled || !authConfigured || !form.login_passkey"
            :loading="toolBusy === 'passkey-create'"
            @click="createPasskey"
          >
            添加通行密钥
          </VBtn>
          <div class="muted-note mt-1">需要 HTTPS 或 localhost 安全上下文，并配合浏览器/系统认证器弹窗完成登记。</div>
        </section>

        <!-- 许可协议 -->
        <section class="st-card">
          <h2>许可协议</h2>
          <VChip variant="tonal" label :color="eulaAccepted ? 'success' : 'warning'" class="mb-2">
            {{ eulaAccepted ? "已同意许可协议" : "还没有同意许可协议" }}
          </VChip>
          <div class="muted-note mb-3">
            <div>状态文件 {{ eulaSetPath }}</div>
            <div v-if="eulaSource">协议来源 {{ eulaSource }}</div>
          </div>
          <div class="d-flex ga-2">
            <VBtn size="small" variant="outlined" @click="viewEula">查看 EULA</VBtn>
            <VBtn size="small" color="warning" variant="tonal" :disabled="!eulaAccepted" @click="revokeEula">撤回同意</VBtn>
          </div>
        </section>

        <!-- 系统服务 -->
        <section class="st-card">
          <h2>systemd 服务状态</h2>
          <div class="d-flex flex-wrap ga-2 mb-2">
            <VChip variant="tonal" label :color="serviceStatus.supported ? 'success' : 'default'">systemd {{ serviceStatus.supported ? "可用" : "不可用" }}</VChip>
            <VChip variant="tonal" label :color="serviceStatus.registered ? 'success' : 'default'">{{ serviceStatus.registered ? "已注册" : "未注册" }}</VChip>
            <VChip variant="tonal" label :color="!serviceStatus.running_as_root && serviceStatus.service_uses_dedicated_user ? 'success' : 'warning'">
              {{ serviceStatus.running_as_root ? "运行权限过高" : serviceStatus.service_uses_dedicated_user && serviceStatus.dedicated_user_exists ? "专用账号运行" : "未使用专用账号" }}
            </VChip>
          </div>
          <pre v-if="serviceMsg" class="log-box mb-2">{{ serviceMsg }}</pre>
          <div class="d-flex flex-wrap ga-2">
            <VBtn size="small" variant="tonal" :loading="toolBusy === 'svc-refresh'" @click="refreshServiceStatus">刷新服务状态</VBtn>
            <VBtn size="small" variant="outlined" :loading="toolBusy === 'systemd'" @click="maintenance('systemd')">注册/更新服务</VBtn>
            <VBtn size="small" variant="tonal" :loading="toolBusy === 'iw'" @click="maintenance('iw')">安装无线工具</VBtn>
            <VBtn size="small" color="warning" variant="tonal" :loading="toolBusy === 'security'" @click="maintenance('security')">修复运行权限</VBtn>
          </div>
        </section>

        <!-- 浏览器偏好 -->
        <section class="st-card">
          <h2>浏览器偏好</h2>
          <VSwitch v-model="newFwParse" label="显示 RID 包解析结果" color="primary" hide-details class="mb-2" @change="saveNewFwParse" />
          <div class="muted-note">仅影响当前浏览器显示。</div>
        </section>

        <!-- 机型库与主机指标 -->
        <section class="st-card">
          <h2>机型库与主机指标</h2>
          <VSwitch v-model="form.model_enabled" label="启用机型库在线更新" color="primary" hide-details class="mb-2" />
          <VTextField v-model="form.model_url" label="机型库 URL（留空用默认仓库地址）" density="compact" variant="outlined" hide-details class="mb-4" />
          <VSwitch v-model="form.metrics_enabled" label="采集主机负载指标" color="primary" hide-details class="mb-2" />
          <div class="d-flex ga-2">
            <VTextField v-model.number="form.metrics_retention" label="指标保留(天)" type="number" min="1" max="90" density="compact" variant="outlined" hide-details />
            <VSelect
              v-model="form.metrics_temp"
              label="温度来源"
              :items="[
                { title: '自动', value: 'auto' },
                { title: '仅 vcgencmd', value: 'vcgencmd' },
                { title: '仅 vcgencmd PMIC', value: 'vcgencmd_pmic' },
                { title: '仅 /sys/class/thermal', value: 'thermal_zone' },
                { title: '仅 /sys/class/hwmon', value: 'hwmon' },
                { title: '仅 DS18B20 / w1', value: 'w1' },
                { title: '关闭温度采集', value: 'off' },
              ]"
              density="compact"
              variant="outlined"
              hide-details
            />
          </div>
        </section>

        <!-- Web 访问控制 -->
        <section class="st-card">
          <h2>Web 访问控制</h2>
          <VSwitch v-model="form.access_enabled" label="启用访问名单" color="primary" hide-details class="mb-3" />
          <VSelect
            v-model="form.access_mode"
            label="名单模式"
            :items="[{ title: '允许名单', value: 'allow' }, { title: '拒绝名单', value: 'deny' }]"
            :disabled="!form.access_enabled"
            density="compact"
            variant="outlined"
            hide-details
            class="mb-2"
          />
          <div v-for="(addr, i) in form.access_list" :key="i" class="d-flex ga-2 mb-2">
            <VTextField v-model="form.access_list[i]" label="IP / CIDR" density="compact" variant="outlined" hide-details class="flex-grow-1" />
            <VBtn icon="mdi-delete-outline" size="small" variant="text" @click="removeAccess(i)" />
          </div>
          <VBtn size="small" variant="outlined" color="primary" @click="addAccess">添加地址</VBtn>
        </section>

        <!-- 报警区域 -->
        <section class="st-card">
          <h2>报警区域</h2>
          <div v-if="!form.alarm_zones.length" class="muted-note mb-2">尚未配置报警区域</div>
          <div v-for="(zone, i) in form.alarm_zones" :key="i" class="zone-box mb-3">
            <div class="d-flex align-center ga-2 mb-2">
              <VSwitch v-model="zone.enabled" color="primary" hide-details />
              <VTextField v-model="zone.name" label="名称" density="compact" variant="outlined" hide-details class="flex-grow-1" />
              <VBtn icon="mdi-delete-outline" size="small" variant="text" @click="removeZone(i)" />
            </div>
            <div class="zone-grid">
              <VTextField v-model="zone.lat1" label="纬度1" density="compact" variant="outlined" hide-details />
              <VTextField v-model="zone.lon1" label="经度1" density="compact" variant="outlined" hide-details />
              <VTextField v-model="zone.lat2" label="纬度2" density="compact" variant="outlined" hide-details />
              <VTextField v-model="zone.lon2" label="经度2" density="compact" variant="outlined" hide-details />
            </div>
          </div>
          <VBtn size="small" variant="outlined" color="primary" @click="addZone">添加区域</VBtn>
        </section>

        <!-- 通知/企业微信 -->
        <section class="st-card">
          <h2>通知 / 企业微信</h2>
          <VSwitch v-model="form.notify_enabled" label="启用通知" color="primary" hide-details class="mb-3" />
          <VSwitch v-model="form.notify_reonline" label="目标恢复在线时通知" color="primary" hide-details class="mb-3" />
          <div class="d-flex ga-2 mb-3">
            <VTextField v-model.number="form.reonline_cooldown_sec" label="重复在线提醒冷却(s)" type="number" min="0" density="compact" variant="outlined" hide-details />
            <VTextField v-model.number="form.send_timeout_sec" label="发送超时(s)" type="number" min="2" density="compact" variant="outlined" hide-details />
          </div>
          <div v-for="(hook, i) in form.hooks" :key="hook.index" class="hook-box mb-2">
            <div class="d-flex align-center ga-2 mb-1">
              <VSwitch v-model="hook.enabled" color="primary" hide-details />
              <VTextField v-model="hook.name" label="通道名称" density="compact" variant="outlined" hide-details class="flex-grow-1" />
              <VBtn icon="mdi-delete-outline" size="small" variant="text" @click="removeHook(i)" />
            </div>
            <VTextField v-model="hook.key" label="Webhook Key（留空保持现有密钥）" density="compact" variant="outlined" hide-details />
          </div>
          <VBtn size="small" variant="outlined" color="primary" @click="addHook">添加通道</VBtn>
        </section>

        <!-- 程序更新 -->
        <section class="st-card st-wide">
          <h2>程序更新</h2>
          <div class="d-flex flex-wrap ga-2 align-center mb-2">
            <VSwitch v-model="auEnabled" label="自动检查版本" color="primary" hide-details />
            <VSwitch v-model="auForce" label="强制更新" color="primary" hide-details />
            <VSelect
              v-model="auMirror"
              label="下载镜像"
              :items="auMirrorItems()"
              density="compact"
              variant="outlined"
              hide-details
              style="max-width: 220px"
            />
            <VTextField
              v-if="auMirror === 'custom'"
              v-model="auCustomMirror"
              label="自定义镜像源"
              placeholder="例如 https://gh-proxy.example.com/{url}"
              density="compact"
              variant="outlined"
              hide-details
              class="flex-grow-1"
              style="min-width: 260px"
            />
          </div>
          <div class="muted-note mb-2">镜像与开关随“保存设置”生效；默认直接访问 github.com，强制更新允许校验失败的安装包继续安装。</div>
          <pre v-if="auStateText" class="log-box mb-2">{{ auStateText }}</pre>
          <div class="d-flex flex-wrap ga-2 mb-2">
            <VBtn size="small" variant="outlined" :disabled="auBusy" :loading="toolBusy === 'au-check'" @click="checkAppUpdateNow">检查</VBtn>
            <VBtn size="small" variant="outlined" :disabled="auBusy || !auHasUpdate || !auSupported" :loading="toolBusy === 'au-download'" @click="downloadAppUpdateNow">下载</VBtn>
            <VBtn size="small" variant="tonal" :disabled="auBusy" @click="triggerAuUpload">选择安装包上传…</VBtn>
            <VBtn size="small" color="primary" :disabled="auBusy || !auStaged || !auSupported || auSudoBlocked" :loading="toolBusy === 'au-start'" @click="startAppUpdateNow">安装</VBtn>
            <input ref="auFileInput" type="file" accept=".bin,application/octet-stream" style="display: none" @change="onAuFileChange" />
          </div>
          <div v-if="auFile || Object.keys(auPrep).length" class="upload-box">
            <div class="d-flex align-center ga-2 mb-1">
              <VChip v-if="auFile" variant="tonal" label class="mono">{{ auFile.name }} · {{ formatBytesUi(auFile.size) }}</VChip>
              <span v-if="Object.keys(auPrep).length" class="muted-note">
                匹配资产 {{ text(auPrep.asset_name, "-") }}<template v-if="text(auPrep.latest_tag, '')"> | Release {{ text(auPrep.latest_tag, "") }}</template><template v-if="text(auPrep.expected_sha256, '')"> | SHA256 {{ text(auPrep.expected_sha256, "").slice(0, 16) }}…</template>
              </span>
              <div class="flex-spacer" />
              <VBtn size="small" color="primary" variant="tonal" :disabled="!auFile || !text(auPrep.token, '') || auBusy" :loading="auUploading" @click="confirmAuUpload">上传并校验 SHA256</VBtn>
            </div>
            <div class="muted-note">先选择文件自动完成架构匹配与 SHA256 预检，再点击上传；安装前需等待校验通过。</div>
          </div>
        </section>

        <!-- Raw 配置文件 -->
        <section class="st-card st-wide">
          <h2>Raw 配置文件</h2>
          <div class="d-flex ga-2 mb-3">
            <VSelect
              v-model="rawPath"
              label="选择配置文件"
              :items="rawFiles"
              item-title="title"
              item-value="path"
              density="compact"
              variant="outlined"
              hide-details
              class="flex-grow-1"
              @update:model-value="openRaw(String($event || ''))"
            />
            <VBtn size="small" variant="tonal" :loading="rawBusy" @click="loadRawTree">刷新文件</VBtn>
          </div>
          <VTextarea
            v-model="rawText"
            label="文件内容（JSON/配置文本）"
            variant="outlined"
            auto-grow
            rows="12"
            class="raw-editor"
            :disabled="!rawPath"
          />
          <div class="d-flex ga-2 mt-3">
            <VChip variant="tonal" label>修改前建议先“导出设置”备份</VChip>
            <div class="flex-spacer" />
            <VBtn size="small" color="error" variant="tonal" :disabled="!rawPath" :loading="rawBusy" @click="deleteRaw">删除文件</VBtn>
            <VBtn size="small" color="primary" :disabled="!rawPath" :loading="rawBusy" @click="saveRaw">保存</VBtn>
          </div>
        </section>

        <!-- 数据与维护 -->
        <section class="st-card st-wide">
          <h2>数据与维护</h2>
          <div class="text-caption text-medium-emphasis mb-1">备份 / 恢复</div>
          <div class="d-flex flex-wrap ga-2 mb-3">
            <VBtn size="small" variant="outlined" :loading="toolBusy === 'export-settings'" @click="exportData('settings')">导出设置</VBtn>
            <VBtn size="small" variant="outlined" :loading="toolBusy === 'export-scan'" @click="exportData('scan')">导出扫描数据</VBtn>
            <VBtn size="small" variant="tonal" :loading="toolBusy === 'import-settings'" @click="pickImport('settings')">导入设置…</VBtn>
            <VBtn size="small" variant="tonal" :loading="toolBusy === 'import-scan'" @click="pickImport('scan')">导入扫描数据(合并)…</VBtn>
            <VChip variant="outlined" label class="ml-1">设置/扫描数据 导出为 JSON，可在本页或旧版页面导入</VChip>
          </div>

          <div class="text-caption text-medium-emphasis mb-1">维护操作</div>
          <div class="d-flex flex-wrap ga-2 mb-3">
            <VBtn size="small" color="primary" :loading="toolBusy === 'models'" @click="maintenance('models')">机型库在线更新</VBtn>
            <VBtn size="small" variant="outlined" :loading="toolBusy === 'reidentify'" @click="maintenance('reidentify')">最近记录重新识别</VBtn>
            <VBtn size="small" variant="tonal" :loading="toolBusy === 'systemd'" @click="maintenance('systemd')">注册 systemd 服务</VBtn>
            <VBtn size="small" variant="tonal" :loading="toolBusy === 'iw'" @click="maintenance('iw')">安装无线工具(iw)</VBtn>
            <VBtn size="small" color="warning" variant="tonal" :loading="toolBusy === 'security'" @click="maintenance('security')">修复运行权限/安全项</VBtn>
          </div>
          <VChip variant="tonal" label>
            提示：import 只接受本站导出格式；导入设置会先备份当前配置，失败自动回滚。
          </VChip>
        </section>

        <!-- 主机负载与运行时日志 -->
        <section class="st-card st-wide">
          <h2>主机负载与运行时日志</h2>
          <div class="d-flex flex-wrap ga-2 align-center mb-2">
            <VSelect
              v-model="metricWin"
              label="时间窗"
              :items="['1h', '6h', '12h', '24h', '7d']"
              density="compact"
              variant="outlined"
              hide-details
              class="metric-select"
              @update:model-value="loadMetrics"
            />
            <VSelect
              v-model="metricSeries"
              label="指标"
              :items="[
                { title: '负载(load)', value: 'load' },
                { title: '1分钟负载(load1)', value: 'load1' },
                { title: 'CPU%', value: 'cpu' },
                { title: '内存%', value: 'mem' },
                { title: '温度℃', value: 'temp' },
                { title: 'AP 数', value: 'ap' },
              ]"
              density="compact"
              variant="outlined"
              hide-details
              class="metric-select"
            />
            <VBtn size="small" variant="tonal" @click="loadMetrics">刷新图表</VBtn>
            <div class="flex-spacer" />
            <VChip v-if="metricMeta.enabled === false" color="warning" variant="tonal" label>指标采集未启用</VChip>
            <VChip variant="tonal" label>窗口 {{ metricMeta.window }} · 采样 {{ metricMeta.count }}</VChip>
          </div>
          <div v-if="!seriesNums(metricSeries).length" class="muted-note">暂无采样数据</div>
          <svg v-else viewBox="0 0 640 130" preserveAspectRatio="none" class="spark" role="img" :aria-label="`${metricSeries} 趋势`">
            <polyline :points="metricPath()" fill="none" stroke="var(--blue)" stroke-width="2" />
          </svg>
          <div class="d-flex align-center ga-2 mt-1 mb-4">
            <span class="muted-note mono">{{ metricSeriesMeta }}</span>
          </div>
          <div class="text-caption text-medium-emphasis mb-1">运行时日志</div>
          <div class="d-flex ga-2 mb-2">
            <VSelect
              v-model="logKind"
              :items="logKinds"
              item-title="title"
              item-value="value"
              density="compact"
              variant="outlined"
              hide-details
              class="metric-select"
              @update:model-value="loadRuntime"
            />
            <VBtn size="small" variant="tonal" @click="loadRuntime">刷新</VBtn>
          </div>
          <pre class="log-box">{{ logLines.length ? logLines.join("\n") : "暂无日志" }}</pre>
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

.sw-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
  gap: 2px 14px;
}

.num-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 8px;
}

.zone-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
}

.zone-box,
.hook-box {
  border: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
  border-radius: 8px;
  padding: 8px;
  background: color-mix(in srgb, var(--card) 70%, transparent);
}

.muted-note {
  color: var(--muted);
  font-size: 12px;
}

.hidden-file {
  display: none;
}

.st-card.st-wide {
  grid-column: 1 / -1;
}

.token-name {
  font-size: 12px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.token-id {
  margin-left: auto;
}

.token-secret {
  font-size: 11px;
  overflow-wrap: anywhere;
  word-break: break-all;
}

.bind-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 5px 0;
}

.bind-iface {
  width: 150px;
  flex: none;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bind-meta {
  flex: 1 1 auto;
  min-width: 0;
  color: color-mix(in srgb, var(--txt) 72%, transparent);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.bind-role {
  width: 210px;
  flex: none;
}

.ap-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 10px;
}

.metric-select {
  width: 130px;
}

.spark {
  width: 100%;
  height: auto;
  display: block;
  background:
    linear-gradient(color-mix(in srgb, var(--border) 34%, transparent) 1px, transparent 1px) 0 0 / 100% 25%,
    linear-gradient(color-mix(in srgb, var(--border) 18%, transparent) 1px, transparent 1px) 0 0 / 25% 100%;
}

.upload-box {
  margin-top: 6px;
  padding: 10px;
  border: 1px dashed color-mix(in srgb, var(--border) 70%, transparent);
  border-radius: 8px;
}

.log-box {
  margin: 0;
  max-height: 240px;
  overflow: auto;
  padding: 10px;
  border: 1px solid color-mix(in srgb, var(--border) 60%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--bg) 70%, transparent);
  color: var(--txt);
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
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
