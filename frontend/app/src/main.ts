import { createApp } from "vue";
import { createVuetify } from "vuetify";
import * as components from "vuetify/components";
import * as directives from "vuetify/directives";
import "vuetify/styles";
import "@mdi/font/css/materialdesignicons.css";
import App from "./App.vue";
import "./style.css";

const xrsLight = {
  dark: false,
  colors: {
    background: "#f3f2f1",
    surface: "#ffffff",
    "surface-variant": "#faf9f8",
    "on-surface": "#323130",
    "on-surface-variant": "#605e5c",
    primary: "#0078d4",
    "on-primary": "#ffffff",
    secondary: "#107c10",
    "on-secondary": "#ffffff",
    error: "#d1242f",
    "on-error": "#ffffff",
    warning: "#d29922",
    "on-warning": "#ffffff",
    info: "#2f81f7",
    "on-info": "#ffffff",
    success: "#2ea043",
    "on-success": "#ffffff",
  },
};

const xrsDark = {
  dark: true,
  colors: {
    background: "#201f1e",
    surface: "#2b2a29",
    "surface-variant": "#252423",
    "on-surface": "#f3f2f1",
    "on-surface-variant": "#c8c6c4",
    primary: "#2899f5",
    "on-primary": "#ffffff",
    secondary: "#92c353",
    "on-secondary": "#0a0f08",
    error: "#f14c54",
    "on-error": "#ffffff",
    warning: "#d29922",
    "on-warning": "#201503",
    info: "#2f81f7",
    "on-info": "#ffffff",
    success: "#3fb950",
    "on-success": "#0a1a0d",
  },
};

const vuetify = createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: "xrsDark",
    themes: {
      xrsDark,
      xrsLight,
    },
  },
});

createApp(App).use(vuetify).mount("#app");
