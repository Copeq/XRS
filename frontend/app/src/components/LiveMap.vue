<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from "vue";
import type { HomeState, DroneRow } from "../composables/useLiveSocket";
import { pageFetch } from "../composables/pageApi";

// 与旧版一致：运行时同源加载站端自带 /assets/leaflet/leaflet.{js,css}
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
let fittedOnce = false;
let selectedSn = "";
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let trackLayer: any = null;
let riskHintEl: HTMLDivElement | null = null;

const META = (): Record<string, unknown> => (props.state.meta ?? {}) as Record<string, unknown>;
const DEFAULT_URL = "https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}";

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

async function fetchDroneTracks(sn: string) {
  const d = (await pageFetch(
    `/api/drones/get?sn=${encodeURIComponent(sn)}&include_tracks=1`,
  )) as Record<string, unknown>;
  const tracks = d.tracks && typeof d.tracks === "object" ? (d.tracks as Record<string, unknown>) : {};
  const pick = (list: unknown) => {
    const out: Array<[number, number]> = [];
    if (!Array.isArray(list)) return out;
    for (const raw of list) {
      const p = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : null;
      if (!p) continue;
      const lat = Number(p.lat ?? p.latitude);
      const lon = Number(p.lon ?? p.lng ?? p.longitude);
      if (Number.isFinite(lat) && Number.isFinite(lon) && lat !== 0 && lon !== 0) out.push([lat, lon]);
    }
    return out;
  };
  return {
    item: d && typeof d.item === "object" ? (d.item as Record<string, unknown>) : {},
    aircraft: pick(Array.isArray(tracks.aircraft) ? tracks.aircraft : Array.isArray(d.track) ? d.track : []),
    operator: pick(Array.isArray(tracks.operator) ? tracks.operator : []),
  };
}

function clearTrackLayer() {
  if (trackLayer) {
    map.removeLayer(trackLayer);
    trackLayer = null;
  }
}

let selectSeq = 0;

function circle(pos: [number, number], color: string, tooltip?: string) {
  const m = L.circleMarker(pos, {
    radius: 6,
    color,
    weight: 2,
    fillColor: color,
    fillOpacity: 0.6,
  });
  if (tooltip) m.bindTooltip(tooltip, { sticky: true });
  m.addTo(trackLayer);
  return m;
}

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

function fitTo(all: Array<[number, number]>) {
  if (map && all.length) map.fitBounds(L.latLngBounds(all), { padding: [32, 32] });
}

// 同步立即绘制：基于实时行先显示无人机/飞手当前点，不等网络
function drawLiveImmediately(sn: string): boolean {
  const live = liveRow(sn);
  const pts = livePoint(live);
  if (!pts) return false;
  ensureTrackLayer();
  const all: Array<[number, number]> = [];
  circle(pts, "#2f81f7", "无人机(实时)");
  all.push(pts);
  const pilot = livePilot(live);
  if (pilot) {
    circle(pilot, "#e67e22", "飞手位置(实时)");
    all.push(pilot);
  }
  fitTo(all);
  return true;
}

function drawDetailed(sn: string, aircraft: Array<[number, number]>, operator: Array<[number, number]>) {
  clearTrackLayer();
  ensureTrackLayer();
  const all: Array<[number, number]> = [];
  const style = (c: string) => ({ color: c, weight: 3, fillOpacity: 0 });
  if (aircraft.length >= 2) {
    L.polyline(aircraft, style("#2f81f7")).addTo(trackLayer);
  } else if (aircraft.length === 1) {
    circle(aircraft[0], "#2f81f7", "无人机");
  }
  if (operator.length) {
    if (operator.length >= 2) L.polyline(operator, style("#e67e22")).addTo(trackLayer);
    circle(operator[operator.length - 1], "#e67e22", "飞手位置");
  }
  all.push(...aircraft);
  all.push(...operator);
  if (all.length) {
    fitTo(all);
  } else {
    drawLiveImmediately(sn);
  }
}

async function selectDrone(sn: string) {
  if (!map) return;
  const seq = ++selectSeq;
  selectedSn = sn;
  // 1) 同步先画实时点，立即有反馈
  if (!drawLiveImmediately(sn)) clearTrackLayer();
  // 2) 异步拉详情后替换为完整轨迹
  try {
    const { aircraft, operator } = await fetchDroneTracks(sn);
    if (!map || seq !== selectSeq || selectedSn !== sn) return;
    drawDetailed(sn, aircraft, operator);
  } catch (_e) {
    // 保留同步已画的实时点即可
    if (!map || seq !== selectSeq || selectedSn !== sn) return;
  }
}

function applyDrones() {
  if (!map) return;
  const rows = props.state.drones ?? [];
  const seen = new Set<string>();
  const hasPos = rows.some((d) => Number.isFinite(Number(d.lat)) && Number.isFinite(Number(d.lon)));
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
      existing.setLatLng([lat, lon]).setIcon(droneArrowIcon(deg, color));
      const tip = existing.getTooltip?.();
      if (tip) tip.setContent(tooltip);
    } else {
      const mk = L.marker([lat, lon], { icon: droneArrowIcon(deg, color) })
        .addTo(map)
        .bindTooltip(tooltip, { sticky: true })
        .on("click", () => {
          void selectDrone(sn);
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
      if (sn === selectedSn) clearTrackLayer();
    }
  }
  if (!fittedOnce) {
    if (hasPos) {
      const pts: Array<[number, number]> = [];
      for (const d of rows) {
        const la = Number(d.lat);
        const lo = Number(d.lon);
        if (Number.isFinite(la) && Number.isFinite(lo)) pts.push([la, lo]);
      }
      if (pts.length) map.fitBounds(L.latLngBounds(pts), { padding: [40, 40] });
      fittedOnce = true;
    }
  }
}

function initMap() {
  if (!mountEl.value || map) return;
  void loadLeaflet().then((lib) => {
    L = lib;
    if (!mountEl.value) return;
    map = L.map(mountEl.value, { zoomControl: true, attributionControl: true, maxZoom: 30 });
    map.on("click", () => {
      selectedSn = "";
      clearTrackLayer();
    });
    applyTileLayer();
    const meta = META();
    const lat = Number(meta.base_lat);
    const lon = Number(meta.base_lon);
    const zoom = Number(meta.base_zoom ?? 13);
    if (Number.isFinite(lat) && Number.isFinite(lon)) {
      map.setView([lat, lon], Number.isFinite(zoom) ? zoom : 13);
    } else {
      map.setView([30, 114], 5);
    }
    applyBaseMarker();
    applyZones();
    syncRiskHint();
    applyDrones();
    window.setTimeout(() => {
      if (map) map.invalidateSize(false);
    }, 60);
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
  droneMarkers.clear();
  prevPos.clear();
  if (trackLayer) trackLayer = null;
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
