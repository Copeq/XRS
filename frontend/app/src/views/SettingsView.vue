<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
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
  /* 机型库更新 */
  const mu = (visual.model_update ?? {}) as Dict;
  form.model_enabled = mu.enabled !== false;
  form.model_url = text(mu.url, "");
  /* 主机指标 */
  const mc = (visual.metrics ?? {}) as Dict;
  form.metrics_enabled = !!mc.enabled;
  form.metrics_retention = num(mc.retention_days ?? 7, 7);
  form.metrics_temp = text(mc.temperature_source, "auto");
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
    await loadRawTree();
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

async function save() {
  saving.value = true;
  try {
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
    const d = (await postJson("/api/settings/visual/save", {
      basic,
      web,
      notify: notifyPayload,
      api: apiPayload,
      auth: authPayload,
      metrics: metricsPayload,
      model_update: modelPayload,
    })) as Dict;
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

/* ------- 维护工具 ------- */
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
              :items="[{ title: '自动', value: 'auto' }, { title: 'CPU', value: 'cpu' }, { title: '主板', value: 'board' }, { title: '关闭', value: 'off' }]"
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
