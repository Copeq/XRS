<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { HomeState, DroneRow } from "../composables/useLiveSocket";
import { pageFetch } from "../composables/pageApi";

// 运行时同源加载站端自带 /assets/leaflet/leaflet.{js,css}
const LEAF_CSS = "/assets/leaflet/leaflet.css";
const LEAF_JS = "/assets/leaflet/leaflet.js";

const props = defineProps<{ state: HomeState }>();
const mountEl = ref<HTMLDivElement | null>(null);

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let L: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let map: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let tileLayer: any = null;
let tileSig = "";
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let baseMarker: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let zoneLayer: any = null;
let zoneSig = "";
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const droneMarkers = new Map<string, any>();
const prevPos = new Map<string, { lat: number; lon: number }>();
// 平滑动画：WS 约 1Hz，标记以指数趋近方式追向最新坐标，避免跳变
const moveTargets = new Map<string, [number, number]>();
let smoothRaf = 0;
let lastSmoothAt = 0;
let fittedOnce = false;

let selectedSn = "";
let userHiddenSn = "";
// 该机已加载过的历史轨迹缓存（再次点击可立即绘制，不等网络）
const trackCache = new Map<string, Array<{ lat: number; lng: number }>>();
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let trackLayer: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let selAircraftLine: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let selPilotMark: any = null;
let selLastPt: [number, number] | null = null;

let riskHintEl: HTMLDivElement | null = null;
let selectSeq = 0;
let sizeObserver: ResizeObserver | null = null;
let autoFitTimer: number | null = null;
let fallbackBaseView = false;

const META = (): Record<string, unknown> => (props.state.meta ?? {}) as Record<string, unknown>;
const DEFAULT_URL = "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}";

function hasLiveTargets(): boolean {
  return (props.state.drones ?? []).some(
    (d) => !d.lost && Number.isFinite(Number(d.lat)) && Number.isFinite(Number(d.lon)),
  );
}

function openSimulationModal() {
  window.dispatchEvent(new Event("xrs:open-simulation"));
}

function loadLeaflet(): Promise<unknown> {
  const win = window as unknown as Record<string, unknown>;
  if (win.L) return Promise.resolve(win.L);
  return new Promise((resolve, reject) => {
    if (!document.querySelector(`link[href="${LEAF_CSS}"]`)) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = LEAF_CSS;
      document.head.appendChild(link);
    }
    if (document.querySelector(`script[src="${LEAF_JS}"]`)) {
      const timer = window.setInterval(() => {
        if (win.L) {
          window.clearInterval(timer);
          resolve(win.L);
        }
      }, 80);
      window.setTimeout(() => window.clearInterval(timer), 8000);
      return;
    }
    const s = document.createElement("script");
    s.src = LEAF_JS;
    s.onload = () => resolve(win.L);
    s.onerror = () => reject(new Error("load leaflet failed"));
    document.head.appendChild(s);
  });
}

function tileConfig() {
  const meta = META();
  const customUrl = String(meta.map_tile_url ?? "").trim();
  const url = customUrl || DEFAULT_URL;
  let subdomains: string[];
  if (customUrl) {
    subdomains = String(meta.map_tile_subdomains ?? "")
      .split(/[\s,]+/)
      .map((x: string) => x.trim())
      .filter(Boolean);
    if (!subdomains.length) subdomains = [""];
  } else {
    subdomains = ["1", "2", "3", "4"];
  }
  let attribution = customUrl
    ? String(meta.map_tile_attribution ?? "Custom map").slice(0, 240)
    : "&copy; 高德地图";
  let maxNative = Number(meta.map_tile_max_native_zoom ?? 18);
  if (!Number.isFinite(maxNative)) maxNative = 18;
  maxNative = Math.max(1, Math.min(30, maxNative));
  return { url, subdomains, attribution, maxNative };
}

function applyTileLayer() {
  if (!map) return;
  const cfg = tileConfig();
  const sig = JSON.stringify([cfg.url, cfg.subdomains, cfg.maxNative, cfg.attribution]);
  if (tileLayer && tileSig === sig) return;
  if (tileLayer) {
    try {
      map.removeLayer(tileLayer);
    } catch (_e) {
      /* noop */
    }
  }
  tileSig = sig;
  tileLayer = L.tileLayer(cfg.url, {
    subdomains: cfg.subdomains,
    maxZoom: 30,
    maxNativeZoom: cfg.maxNative,
    attribution: cfg.attribution,
  });
  tileLayer.addTo(map);
}

function baseIcon() {
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24">' +
    '<circle cx="12" cy="12" r="10.6" fill="#2f81f7" fill-opacity="0.92" stroke="#fff" stroke-width="1.1"/>' +
    '<path d="M12 6.3v10.2M9.4 17.1h5.2M10.2 10.8L12 9l1.8 1.8M9.8 8.5c.9-.92 2.05-1.38 3.2-1.38 1.15 0 2.3.46 3.2 1.38M8.3 7c1.32-1.34 3.03-2.01 4.74-2.01 1.71 0 3.42.67 4.74 2.01" stroke="#fff" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.35" fill="none"/>' +
    '<path d="M10.8 16.6l-1.15 2.3M13.2 16.6l1.15 2.3" stroke="#fff" stroke-linecap="round" stroke-width="1.2"/>' +
    "</svg>";
  return L.divIcon({ html: svg, className: "", iconSize: [48, 48], iconAnchor: [24, 24], popupAnchor: [0, -22] });
}

function droneArrowIcon(deg: number, color: string) {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 26 26">` +
    `<g transform="rotate(${deg} 13 13)">` +
    `<path d="M13 1.5 L21 23 L13 17.5 L5 23 Z" fill="${color}" stroke="#fff" stroke-width="1" opacity="0.95"/>` +
    `</g></svg>`;
  return L.divIcon({ html: svg, className: "", iconSize: [30, 30], iconAnchor: [15, 15], popupAnchor: [0, -12] });
}

function applyBaseMarker() {
  if (!map) return;
  const meta = META();
  const lat = Number(meta.base_lat);
  const lon = Number(meta.base_lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    if (baseMarker) {
      map.removeLayer(baseMarker);
      baseMarker = null;
    }
    return;
  }
  const name = String(meta.base_name ?? "基站");
  const popup = `<b>${name}</b><br/>${lat.toFixed(6)}, ${lon.toFixed(6)}`;
  if (baseMarker) {
    baseMarker.setLatLng([lat, lon]).setPopupContent(popup);
  } else {
    baseMarker = L.marker([lat, lon], { icon: baseIcon() }).addTo(map).bindPopup(popup);
  }
}

function applyZones() {
  if (!map) return;
  const meta = META();
  const zones = Array.isArray(meta.alert_zones) ? (meta.alert_zones as Array<Record<string, unknown>>) : [];
  const sig = JSON.stringify(zones.map((z) => [z.name, z.enabled, z.lat1, z.lon1, z.lat2, z.lon2]));
  if (zoneLayer && zoneSig === sig) return;
  zoneSig = sig;
  if (zoneLayer) {
    map.removeLayer(zoneLayer);
    zoneLayer = null;
  }
  if (!zones.length) return;
  zoneLayer = L.layerGroup().addTo(map);
  for (const z of zones) {
    if (z.enabled === false) continue;
    const n = Number(z.lat1);
    const e = Number(z.lon1);
    const s = Number(z.lat2);
    const w = Number(z.lon2);
    if (![n, e, s, w].every(Number.isFinite)) continue;
    L.rectangle(
      [
        [n, e],
        [s, w],
      ],
      { color: "#d1242f", weight: 1.5, fillOpacity: 0.06 },
    )
      .bindTooltip(String(z.name ?? "报警区域"))
      .addTo(zoneLayer);
  }
}

function syncRiskHint() {
  if (!mountEl.value) return;
  const show = META().map_default_legal_notice === true;
  if (!show) {
    if (riskHintEl) {
      riskHintEl.remove();
      riskHintEl = null;
    }
    return;
  }
  if (!riskHintEl) {
    riskHintEl = document.createElement("div");
    riskHintEl.className = "map-api-risk";
    mountEl.value.parentElement?.insertBefore(riskHintEl, mountEl.value);
  }
  riskHintEl.textContent = "未配置地图 API，当前使用默认在线底图，可能存在法律风险；请勿暴露公网或商业使用。";
}

function bearingDeg(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const rad = Math.PI / 180;
  const phi1 = aLat * rad;
  const phi2 = bLat * rad;
  const dLon = (bLon - aLon) * rad;
  const y = Math.sin(dLon) * Math.cos(phi2);
  const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLon);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

function droneHeading(d: DroneRow, lat: number, lon: number): number {
  const tracked = Number((d as unknown as Record<string, unknown>).track_deg);
  if (Number.isFinite(tracked)) return ((tracked % 360) + 360) % 360;
  const prev = prevPos.get(String(d.sn ?? ""));
  if (prev) {
    const dist = Math.abs(prev.lat - lat) + Math.abs(prev.lon - lon);
    if (dist > 1e-7) return bearingDeg(prev.lat, prev.lon, lat, lon);
  }
  return 0;
}

/* ---------- 选中轨迹（实时续画） ---------- */

function liveRow(sn: string) {
  return (props.state.drones ?? []).find((d) => String(d.sn ?? "") === sn);
}

function livePoint(live: DroneRow | undefined): [number, number] | null {
  if (!live) return null;
  const lat = Number(live.lat);
  const lon = Number(live.lon);
  return Number.isFinite(lat) && Number.isFinite(lon) ? [lat, lon] : null;
}

function livePilot(live: DroneRow | undefined): [number, number] | null {
  if (!live) return null;
  const pl = Number((live as unknown as Record<string, unknown>).pilot_lat);
  const po = Number((live as unknown as Record<string, unknown>).pilot_lon);
  return Number.isFinite(pl) && Number.isFinite(po) ? [pl, po] : null;
}

function ensureTrackLayer() {
  if (!trackLayer) trackLayer = L.layerGroup().addTo(map);
  return trackLayer;
}

function samePt(a: [number, number] | null, b: [number, number] | null): boolean {
  return !!a && !!b && a[0] === b[0] && a[1] === b[1];
}

function clearTrackLayer() {
  if (trackLayer) {
    map.removeLayer(trackLayer);
    trackLayer = null;
  }
  selAircraftLine = null;
  selPilotMark = null;
  selLastPt = null;
}

// 记录当前已画出的轨迹到缓存，供下次点击立即显示
function captureTrackCache(sn: string) {
  try {
    const line = selAircraftLine as { getLatLngs?: () => unknown } | null;
    const ls = line?.getLatLngs?.() as Array<{ lat: number; lng: number }> | null;
    if (Array.isArray(ls) && ls.length) {
      trackCache.set(
        sn,
        ls.map((p) => ({ lat: Number(p.lat), lng: Number(p.lng) })),
      );
      return;
    }
  } catch (_e) {
    /* ignore */
  }
  trackCache.delete(sn);
}

// 立即用缓存绘制该机轨迹（无缓存则不处理）
function drawCachedTrack(sn: string): boolean {
  const cached = trackCache.get(sn);
  if (!cached || !cached.length) return false;
  const pts = cached.map((p) => [Number(p.lat), Number(p.lng)] as [number, number]);
  ensureAircraftLine().setLatLngs(pts);
  selLastPt = pts[pts.length - 1];
  return true;
}

function ensureAircraftLine() {
  if (!selAircraftLine) {
    selAircraftLine = L.polyline([], { color: "#2f81f7", weight: 3, opacity: 0.95 }).addTo(ensureTrackLayer());
  }
  return selAircraftLine;
}

function ensurePilotMark() {
  if (!selPilotMark) {
    selPilotMark = L.circleMarker([0, 0], {
      radius: 7,
      color: "#e67e22",
      weight: 2,
      fillColor: "#e67e22",
      fillOpacity: 0.7,
    })
      .addTo(ensureTrackLayer())
      .bindTooltip("飞手位置", { sticky: true });
  }
  return selPilotMark;
}

// 实时续画：每帧把新位置追加到已画轨迹，并移动飞手点
function updateSelectedLive() {
  if (!map || !selectedSn || userHiddenSn === selectedSn) return;
  const live = liveRow(selectedSn);
  const pt = livePoint(live);
  if (!pt) return;
  ensureTrackLayer();
  const line = ensureAircraftLine();
  if (!samePt(selLastPt, pt)) {
    if (selLastPt) {
      line.addLatLng(pt);
    } else {
      line.setLatLngs([pt]);
    }
    selLastPt = pt;
  }
  const pilot = livePilot(live);
  if (pilot) {
    ensurePilotMark().setLatLng(pilot);
  }
}

// 点击时同步立即显示当前点，再回填历史，之后由 updateSelectedLive 持续续画
function selectDrone(sn: string) {
  if (!map) return;
  const seq = ++selectSeq;
  selectedSn = sn;
  clearTrackLayer();
  ensureTrackLayer();
  const live = liveRow(sn);
  const pt = livePoint(live);
  if (pt) {
    ensureAircraftLine().setLatLngs([pt]);
    selLastPt = pt;
  }
  const pilot = livePilot(live);
  if (pilot) {
    ensurePilotMark().setLatLng(pilot);
  }
  // 有缓存则立即绘制，减少等待
  drawCachedTrack(sn);
  void (async () => {
    try {
      const d = (await pageFetch(
        `/api/drones/get?sn=${encodeURIComponent(sn)}&include_tracks=1&limit=4000`,
      )) as Record<string, unknown>;
      if (!map || seq !== selectSeq || selectedSn !== sn) return;
      const tracks = d.tracks && typeof d.tracks === "object" ? (d.tracks as Record<string, unknown>) : {};
      const pick = (list: unknown) => {
        const out: Array<[number, number]> = [];
        if (!Array.isArray(list)) return out;
        for (const raw of list) {
          const p = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : null;
          if (!p) continue;
          const la = Number(p.lat ?? p.latitude);
          const lo = Number(p.lon ?? p.lng ?? p.longitude);
          if (Number.isFinite(la) && Number.isFinite(lo) && la !== 0 && lo !== 0) out.push([la, lo]);
        }
        return out;
      };
      const aircraft = pick(Array.isArray(tracks.aircraft) ? tracks.aircraft : Array.isArray(d.track) ? d.track : []);
      const operator = pick(Array.isArray(tracks.operator) ? tracks.operator : []);
      // 回填历史轨迹（已加载则此调用只覆盖轨迹线）
      if (aircraft.length) {
        ensureAircraftLine().setLatLngs(aircraft);
        selLastPt = aircraft[aircraft.length - 1];
        trackCache.set(
          sn,
          aircraft.map((p) => ({ lat: p[0], lng: p[1] })),
        );
      }
      if (operator.length >= 2) {
        L.polyline(operator, { color: "#e67e22", weight: 2, opacity: 0.8 }).addTo(trackLayer);
      }
      if (operator.length) {
        ensurePilotMark().setLatLng(operator[operator.length - 1]);
      } else {
        const lp = liveRow(sn);
        const pil = livePilot(lp);
        if (pil) ensurePilotMark().setLatLng(pil);
      }
    } catch (_e) {
      /* 保留实时绘制即可 */
    }
  })();
}

/* ---------- 无人机标记 ---------- */

function applyDrones() {
  if (!map) return;
  const rows = props.state.drones ?? [];
  const seen = new Set<string>();
  for (const d of rows) {
    const sn = String(d.sn ?? "");
    const lat = Number(d.lat);
    const lon = Number(d.lon);
    if (!sn || !Number.isFinite(lat) || !Number.isFinite(lon)) continue;
    seen.add(sn);
    const color = d.lost ? "#9aa0a6" : "#2ea043";
    const deg = droneHeading(d, lat, lon);
    const tooltip = `${sn}${d.model ? " · " + d.model : ""}`;
    const existing = droneMarkers.get(sn);
    if (existing) {
      // 平滑模式：只更新朝向与目标位置，实际移动由 rAF 动画逐帧逼近
      existing.setIcon(droneArrowIcon(deg, color));
      moveTargets.set(sn, [lat, lon]);
      const tip = existing.getTooltip?.();
      if (tip) tip.setContent(tooltip);
    } else {
      const mk = L.marker([lat, lon], { icon: droneArrowIcon(deg, color) })
        .addTo(map)
        .bindTooltip(tooltip, { sticky: true })
        .on("click", () => {
          if (selectedSn === sn) {
            // 再次点击同一图标：隐藏轨迹（先记录当前轨迹供下次立即显示）
            captureTrackCache(sn);
            selectedSn = "";
            userHiddenSn = sn;
            selectSeq++; // 使历史回填请求的 seq 校验失败，避免延迟到达后重画
            clearTrackLayer();
          } else {
            userHiddenSn = "";
            selectDrone(sn);
          }
        });
      droneMarkers.set(sn, mk);
    }
    prevPos.set(sn, { lat, lon });
  }
  for (const [sn, mk] of Array.from(droneMarkers.entries())) {
    if (!seen.has(sn)) {
      map.removeLayer(mk);
      droneMarkers.delete(sn);
      prevPos.delete(sn);
      moveTargets.delete(sn);
      if (sn === selectedSn) {
        selectedSn = "";
        clearTrackLayer();
      }
      if (sn === userHiddenSn) userHiddenSn = "";
    }
  }
  // 被选中的目标持续续画轨迹
  updateSelectedLive();
  // 首次打开自动缩放（容器就绪且确有实时目标时才真正 fit）
  if (!fittedOnce) attemptAutoFit();
}

function containerReady(): boolean {
  const el = mountEl.value;
  return !!el && el.clientWidth > 0 && el.clientHeight > 0;
}

// 首次打开自动缩放到当前实时目标（要求容器已就绪；成功一次后置位避免后续跳动）
function attemptAutoFit(): boolean {
  if (!map || fittedOnce || !containerReady()) return false;
  const pts: Array<[number, number]> = [];
  for (const d of props.state.drones ?? []) {
    const la = Number(d.lat);
    const lo = Number(d.lon);
    if (Number.isFinite(la) && Number.isFinite(lo) && la !== 0 && lo !== 0) pts.push([la, lo]);
  }
  if (!pts.length) return false;
  map.invalidateSize(false);
  map.fitBounds(L.latLngBounds(pts), { padding: [44, 44] });
  fittedOnce = true;
  return true;
}

// meta 晚于地图创建到达时的补偿：从兜底视图回正到配置的基站位置
function ensureBaseViewOnce(): void {
  if (!map || fittedOnce || !fallbackBaseView) return;
  const m = META();
  const lat = Number(m.base_lat);
  const lon = Number(m.base_lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
  fallbackBaseView = false;
  const zoom = Number(m.base_zoom ?? 13);
  map.invalidateSize(false);
  map.setView([lat, lon], Number.isFinite(zoom) ? zoom : 13);
}

function startSizeWatcher(): void {
  if (sizeObserver || !mountEl.value || typeof ResizeObserver === "undefined") return;
  sizeObserver = new ResizeObserver(() => {
    if (!map) return;
    map.invalidateSize(false);
    if (!fittedOnce) {
      ensureBaseViewOnce();
      attemptAutoFit();
    }
  });
  sizeObserver.observe(mountEl.value);
}

function startAutoFitPolls(): void {
  if (autoFitTimer) return;
  let tries = 0;
  autoFitTimer = window.setInterval(() => {
    tries += 1;
    if (map && containerReady()) map.invalidateSize(false);
    if (!fittedOnce) {
      ensureBaseViewOnce();
      if (attemptAutoFit()) tries = 999;
    }
    if (!map || tries >= 10 || fittedOnce) {
      if (autoFitTimer) window.clearInterval(autoFitTimer);
      autoFitTimer = null;
    }
  }, 120);
}

// 标记平滑移动动画（约 60fps 指数追近目标，消除 1Hz 推送的跳变）
function startSmoothMotion(): void {
  if (smoothRaf || !window.requestAnimationFrame) return;
  lastSmoothAt = 0;
  const tick = (t: number) => {
    smoothRaf = window.requestAnimationFrame(tick);
    if (!map) return;
    const dt = lastSmoothAt ? Math.min(0.15, (t - lastSmoothAt) / 1000) : 0.05;
    lastSmoothAt = t;
    if (!moveTargets.size) return;
    const k = 1 - Math.exp(-dt / 0.38);
    for (const [sn, mk] of Array.from(droneMarkers.entries())) {
      const tgt = moveTargets.get(sn);
      if (!tgt) continue;
      const cur = mk.getLatLng();
      const lat = cur.lat + (tgt[0] - cur.lat) * k;
      const lon = cur.lng + (tgt[1] - cur.lng) * k;
      const arrived = Math.abs(lat - tgt[0]) < 1e-9 && Math.abs(lon - tgt[1]) < 1e-9;
      mk.setLatLng(arrived ? tgt : [lat, lon]);
      if (arrived) moveTargets.delete(sn);
    }
  };
  smoothRaf = window.requestAnimationFrame(tick);
}

function initMap() {
  if (!mountEl.value || map) return;
  void loadLeaflet().then((lib) => {
    L = lib;
    if (!mountEl.value) return;
    map = L.map(mountEl.value, { zoomControl: true, attributionControl: true, maxZoom: 30 });
    applyTileLayer();
    const meta = META();
    const lat = Number(meta.base_lat);
    const lon = Number(meta.base_lon);
    const zoom = Number(meta.base_zoom ?? 13);
    if (Number.isFinite(lat) && Number.isFinite(lon)) {
      fallbackBaseView = false;
      map.setView([lat, lon], Number.isFinite(zoom) ? zoom : 13);
    } else {
      fallbackBaseView = true;
      map.setView([30, 114], 5);
    }
    applyBaseMarker();
    applyZones();
    syncRiskHint();
    applyDrones();
    startSizeWatcher();
    startAutoFitPolls();
    startSmoothMotion();
  });
}

function resize() {
  if (map) map.invalidateSize(false);
}

onMounted(() => {
  initMap();
  window.addEventListener("resize", resize);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", resize);
  if (sizeObserver) {
    sizeObserver.disconnect();
    sizeObserver = null;
  }
  if (autoFitTimer) {
    window.clearInterval(autoFitTimer);
    autoFitTimer = null;
  }
  if (smoothRaf) {
    window.cancelAnimationFrame(smoothRaf);
    smoothRaf = 0;
  }
  moveTargets.clear();
  lastSmoothAt = 0;
  droneMarkers.clear();
  prevPos.clear();
  trackLayer = null;
  selAircraftLine = null;
  selPilotMark = null;
  if (map) {
    try {
      map.remove();
    } catch (_e) {
      /* noop */
    }
    map = null;
  }
});

watch(
  () => props.state.meta,
  () => {
    if (!map) return;
    ensureBaseViewOnce();
    applyTileLayer();
    applyBaseMarker();
    applyZones();
    syncRiskHint();
  },
  { deep: true },
);

watch(
  () => props.state.drones,
  () => applyDrones(),
  { deep: true },
);
</script>

<template>
  <div class="live-map">
    <div ref="mountEl" class="map-mount"></div>
    <div v-if="!hasLiveTargets()" class="map-empty-hint">
      <p>暂无在线无人机</p>
      <button type="button" @click="openSimulationModal">模拟无人机</button>
    </div>
  </div>
</template>

<style scoped>
.live-map {
  flex: 1;
  position: relative;
  min-height: 320px;
  z-index: 0;
  isolation: isolate;
}

.map-mount {
  position: absolute;
  inset: 0;
}

.map-empty-hint {
  position: absolute;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 600;
  background: color-mix(in srgb, var(--card) 94%, var(--txt) 6%);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 6px 12px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.12);
}

.map-empty-hint p {
  margin: 0;
}

.map-empty-hint button {
  border: 1px solid var(--blue);
  background: var(--blue);
  color: #fff;
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 12px;
  cursor: pointer;
}

.live-map :deep(.map-api-risk) {
  position: absolute;
  top: 40px;
  left: 8px;
  z-index: 500;
  max-width: min(360px, calc(100% - 16px));
  background: color-mix(in srgb, #d29922 14%, #fff);
  color: #6b5200;
  border: 1px solid color-mix(in srgb, #d29922 45%, transparent);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 11px;
  line-height: 1.4;
}
</style>
