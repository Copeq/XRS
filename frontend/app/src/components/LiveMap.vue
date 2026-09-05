<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from "vue";
import type { HomeState } from "../composables/useLiveSocket";

// 与旧版一致：运行时同源加载站端自带的 /assets/leaflet/leaflet.{js,css}，
// 不参与前端 bundle，避免重复打包与图标资源处理。
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
  return L.divIcon({
    html: svg,
    className: "",
    iconSize: [48, 48],
    iconAnchor: [24, 24],
    popupAnchor: [0, -22],
  });
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
    const color = d.lost ? "#9aa0a6" : "#2f81f7";
    const radius = d.lost ? 5 : 6;
    const tooltip = `${sn}${d.model ? " · " + d.model : ""}`;
    const existing = droneMarkers.get(sn);
    if (existing) {
      existing.setLatLng([lat, lon]).setStyle({ color, radius });
      const tip = existing.getTooltip?.();
      if (tip) tip.setContent(tooltip);
    } else {
      const mk = L.circleMarker([lat, lon], {
        radius,
        color,
        weight: 2,
        fillColor: color,
        fillOpacity: 0.45,
      })
        .addTo(map)
        .bindTooltip(tooltip, { sticky: true });
      droneMarkers.set(sn, mk);
    }
  }
  for (const [sn, mk] of Array.from(droneMarkers.entries())) {
    if (!seen.has(sn)) {
      map.removeLayer(mk);
      droneMarkers.delete(sn);
    }
  }
}

async function initMap() {
  if (!mountEl.value || map) return;
  try {
    const lib = await loadLeaflet();
    L = lib;
  } catch (_e) {
    if (mountEl.value) mountEl.value.textContent = "Leaflet 加载失败";
    return;
  }
  if (!mountEl.value) return;
  map = L.map(mountEl.value, { zoomControl: true, attributionControl: true, maxZoom: 30 });
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
  window.setTimeout(() => {
    if (map) map.invalidateSize(false);
  }, 60);
}

function resize() {
  if (map) map.invalidateSize(false);
}

onMounted(() => {
  void initMap();
  window.addEventListener("resize", resize);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", resize);
  droneMarkers.clear();
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
