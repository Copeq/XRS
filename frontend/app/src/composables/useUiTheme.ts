import { reactive } from "vue";

/**
 * 主页主题（背景 + 玻璃拟态）。
 * 状态为模块级单例：任意页面/组件读取同一份；通过 CSS 变量下发，
 * 避免逐组件传参；只操作 background 与 backdrop-filter 等合成属性，性能友好。
 */

export interface UiThemeState {
  enabled: boolean;
  /** "preset" = 内置渐变， "image" = 自定义图片 URL */
  mode: "preset" | "image";
  preset: string;
  url: string;
  /** 玻璃虚化强度 px */
  blur: number;
  /** 顶部暗色遮罩 0~0.7（保证文字可读） */
  overlay: number;
}

export interface UiThemePreset {
  key: string;
  label: string;
  css: string;
}

const STORAGE_KEY = "xrs_ui_theme_v1";

export const THEME_PRESETS: UiThemePreset[] = [
  { key: "auto", label: "默认", css: "" },
  { key: "aurora", label: "极光", css: "linear-gradient(160deg, #0b1020 0%, #16213e 45%, #0f3460 100%)" },
  {
    key: "nebula",
    label: "星云",
    css: "radial-gradient(circle at 18% 18%, rgba(78,46,168,.95), transparent 52%), radial-gradient(circle at 82% 64%, rgba(208,70,160,.5), transparent 58%), linear-gradient(150deg, #05060f 0%, #101736 100%)",
  },
  {
    key: "light",
    label: "浅色",
    css: "linear-gradient(160deg, #eef2f7 0%, #d9e3ee 55%, #c7d6e6 100%)",
  },
  {
    key: "forest",
    label: "深林",
    css: "linear-gradient(160deg, #0a1510 0%, #12301f 55%, #1b3a26 100%)",
  },
];

function defaults(): UiThemeState {
  return { enabled: false, mode: "preset", preset: "aurora", url: "", blur: 22, overlay: 0.22 };
}

function load(): UiThemeState {
  const base = defaults();
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return base;
    const o = JSON.parse(raw) as Partial<UiThemeState>;
    if (o && typeof o === "object") {
      return {
        enabled: !!o.enabled,
        mode: o.mode === "image" ? "image" : "preset",
        preset: String(o.preset ?? base.preset),
        url: String(o.url ?? ""),
        blur: Math.max(0, Math.min(40, Number(o.blur ?? base.blur))),
        overlay: Math.max(0, Math.min(0.7, Number(o.overlay ?? base.overlay))),
      };
    }
  } catch (_e) {
    /* ignore corrupted storage */
  }
  return base;
}

const state = reactive<UiThemeState>(load());

function presetCss(key: string): string {
  return THEME_PRESETS.find((p) => p.key === key)?.css ?? "";
}

/** 当前应绘制的背景（CSS background 值；enabled=false 返回空字符串） */
export function currentBackgroundCss(): string {
  if (!state.enabled) return "";
  if (state.mode === "image" && state.url) {
    const o = Math.max(0, Math.min(0.7, state.overlay));
    return `linear-gradient(rgba(8,10,18,${o}), rgba(8,10,18,${o})), url("${state.url}") center / cover no-repeat fixed`;
  }
  const css = presetCss(state.preset);
  if (!css) return "";
  return css;
}

function persist() {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch (_e) {
    /* storage full / unavailable */
  }
}

function syncDom() {
  const root = document.documentElement;
  const on = state.enabled;
  const blur = on ? Math.max(0, Math.min(40, state.blur)) : 0;
  root.style.setProperty("--xrs-blur", `${blur}px`);
  root.style.setProperty("--xrs-card-alpha", on ? "0.68" : "1");
  root.style.setProperty("--xrs-line-alpha", on ? "0.6" : "1");
  const bg = currentBackgroundCss();
  const body = document.body;
  if (bg) {
    body.style.backgroundImage = bg;
    body.style.backgroundSize = "cover";
    body.style.backgroundPosition = "center";
    body.style.backgroundAttachment = "fixed";
  } else {
    body.style.backgroundImage = "";
    body.style.backgroundSize = "";
    body.style.backgroundPosition = "";
    body.style.backgroundAttachment = "";
  }
}

export function useUiTheme() {
  return {
    state,
    presets: THEME_PRESETS,
    /** 应用主题到 DOM；页面挂载时调用一次即可 */
    apply() {
      syncDom();
      persist();
    },
    setEnabled(v: boolean) {
      state.enabled = !!v;
      syncDom();
      persist();
    },
    setMode(mode: "preset" | "image") {
      state.mode = mode;
      if (mode === "preset") state.url = "";
      syncDom();
      persist();
    },
    setPreset(key: string) {
      state.preset = key;
      state.mode = "preset";
      syncDom();
      persist();
    },
    setUrl(url: string) {
      state.url = String(url ?? "").trim();
      if (state.url) state.mode = "image";
      syncDom();
      persist();
    },
    setBlur(v: number) {
      state.blur = Math.max(0, Math.min(40, Number(v) || 0));
      syncDom();
      persist();
    },
    setOverlay(v: number) {
      state.overlay = Math.max(0, Math.min(0.7, Number(v) || 0));
      syncDom();
      persist();
    },
    reset() {
      Object.assign(state, defaults());
      syncDom();
      persist();
    },
  };
}
