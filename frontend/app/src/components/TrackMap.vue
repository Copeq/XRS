<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

export interface TrackPoint {
  lat: number;
  lon: number;
}

const props = defineProps<{ points: TrackPoint[] }>();

const mountEl = ref<HTMLDivElement | null>(null);
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let L: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let map: any = null;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let layer: any = null;

function loadLeaf(): Promise<unknown> {
  const win = window as unknown as Record<string, unknown>;
  if (win.L) return Promise.resolve(win.L);
  return new Promise((resolve, reject) => {
    if (!document.querySelector('link[href="/assets/leaflet/leaflet.css"]')) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "/assets/leaflet/leaflet.css";
      document.head.appendChild(link);
    }
    const s = document.createElement("script");
    s.src = "/assets/leaflet/leaflet.js";
    s.onload = () => resolve(win.L);
    s.onerror = () => reject(new Error("load leaflet failed"));
    document.head.appendChild(s);
  });
}

function clearLayer() {
  if (!map || !layer) return;
  map.removeLayer(layer);
  layer = null;
}

function draw() {
  if (!map) return;
  clearLayer();
  if (!props.points.length) return;
  const pts = props.points.map((p) => [p.lat, p.lon] as [number, number]);
  layer = L.layerGroup().addTo(map);
  L.polyline(pts, { color: "#2f81f7", weight: 3 }).addTo(layer);
  L.circleMarker(pts[0], { radius: 5, color: "#2ea043", weight: 2, fillColor: "#2ea043", fillOpacity: 0.8 }).addTo(layer);
  L.circleMarker(pts[pts.length - 1], { radius: 5, color: "#d1242f", weight: 2, fillColor: "#d1242f", fillOpacity: 0.8 }).addTo(layer);
  map.fitBounds(L.latLngBounds(pts), { padding: [20, 20] });
}

onMounted(async () => {
  if (!mountEl.value) return;
  try {
    L = await loadLeaf();
  } catch (_e) {
    if (mountEl.value) mountEl.value.textContent = "Leaflet 加载失败";
    return;
  }
  if (!mountEl.value) return;
  map = L.map(mountEl.value, { zoomControl: true, attributionControl: true });
  L.tileLayer("https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}", {
    subdomains: ["1", "2", "3", "4"],
    maxZoom: 20,
    attribution: "&copy; 高德地图",
  }).addTo(map);
  draw();
  window.setTimeout(() => {
    if (map) map.invalidateSize(false);
  }, 60);
});

onBeforeUnmount(() => {
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
  () => props.points,
  () => {
    if (!map) return;
    draw();
  },
  { deep: true },
);
</script>

<template>
  <div class="track-map">
    <div ref="mountEl" class="track-mount"></div>
    <div v-if="!points.length" class="track-empty">该机暂无可用轨迹坐标</div>
  </div>
</template>

<style scoped>
.track-map {
  position: relative;
  min-height: 260px;
  margin-top: 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.track-mount {
  height: 260px;
}

.track-empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: 12px;
}
</style>
