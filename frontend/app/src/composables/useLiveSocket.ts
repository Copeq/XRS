import { onUnmounted, reactive } from "vue";

export interface DroneRow {
  sn: string;
  model?: string | null;
  uas_id?: string;
  mac?: string;
  rssi?: number | null;
  pkts?: number;
  dir?: string;
  alt?: number | null;
  spd?: number | null;
  age_text?: string;
  age?: number;
  first_seen?: string;
  last_seen?: string;
  capture_time?: string;
  lost?: boolean;
  archived?: boolean;
  scan_type?: string;
  firmware_type?: string;
  ch?: string;
  lat?: number | null;
  lon?: number | null;
}

export interface ApsRow {
  bssid?: string;
  mac?: string;
  ssid?: string;
  ch?: string | number;
  rssi?: number | null;
  vendor?: string;
  first_seen?: string;
  last_seen?: string;
}

export interface HomeState {
  connected: boolean;
  ts: string;
  ch: string;
  server_wall_ms: number;
  meta: Record<string, unknown>;
  drones: DroneRow[];
  aps: ApsRow[];
  logs: unknown[];
}

export function useLiveSocket() {
  const state = reactive<HomeState>({
    connected: false,
    ts: "",
    ch: "",
    server_wall_ms: 0,
    meta: {},
    drones: [],
    aps: [],
    logs: [],
  });

  let ws: WebSocket | null = null;
  let retry: number | null = null;
  let ping: number | null = null;
  let closed = false;

  function scheduleRetry() {
    if (retry) window.clearTimeout(retry);
    if (closed) return;
    retry = window.setTimeout(() => connect(), 2000);
  }

  function apply(message: unknown) {
    if (!message || typeof message !== "object") return;
    const m = message as Record<string, unknown>;
    if (typeof m.ts === "string") state.ts = m.ts;
    if (typeof m.server_wall_ms === "number") state.server_wall_ms = m.server_wall_ms;
    if (typeof m.ch === "string") state.ch = m.ch;
    if (m.meta && typeof m.meta === "object") {
      Object.assign(state.meta, m.meta);
    }
    if (Array.isArray(m.drones)) state.drones = m.drones as DroneRow[];
    if (Array.isArray(m.aps)) state.aps = m.aps as ApsRow[];
    if (Array.isArray(m.logs) && m.logs.length > 0) {
      state.logs = state.logs.concat(m.logs).slice(-120);
    }
  }

  function connect() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${window.location.host}/ws?page=home`);
    ws.onopen = () => {
      state.connected = true;
    };
    ws.onmessage = (ev) => {
      try {
        apply(JSON.parse(String(ev.data)));
      } catch (_e) {
        /* ignore malformed frame */
      }
    };
    ws.onclose = () => {
      state.connected = false;
      scheduleRetry();
    };
    ws.onerror = () => {
      try {
        ws && ws.close();
      } catch (_e) {
        /* noop */
      }
    };
    if (ping) window.clearInterval(ping);
    ping = window.setInterval(() => {
      try {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ kind: "ping" }));
        }
      } catch (_e) {
        /* noop */
      }
    }, 25000);
  }

  connect();

  onUnmounted(() => {
    closed = true;
    if (retry) window.clearTimeout(retry);
    if (ping) window.clearInterval(ping);
    if (ws) {
      try {
        ws.close();
      } catch (_e) {
        /* noop */
      }
    }
  });

  return state;
}
