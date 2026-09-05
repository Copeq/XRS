"""runtime init core (extracted from common_core.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
Shared globals/constants and sibling chunk functions resolve at call time.
"""

def init_web_from_config(cfg: dict | None) -> None:
    global WEB_CFG
    WEB_CFG = _normalize_web_cfg(cfg)

def _scan_type_key(v: str | None) -> str:
    s = str(v or "").strip()
    low = s.lower()
    if not s:
        return "rid"
    if low in ("rid", "rid_report", "rid_reporting", "rid_reporting_type"):
        return "rid"
    if low in ("phone", "phone_fast", "mobile", "mobile_fast"):
        return "phone"
    if "RID" in s or "rid" in low or "报送" in s:
        return "rid"
    if "手机" in s or "快传" in s:
        return "phone"
    return s

def _scan_type_display(v: str | None) -> str:
    key = _scan_type_key(v)
    if key == "phone":
        return str(WEB_CFG.get("scan_type_phone") or "手机快传")
    if key == "rid":
        return str(WEB_CFG.get("scan_type_rid") or "RID报送")
    return key

def _sn_source_display(id_type: str | None) -> str:
    if str(id_type or "").strip().upper() == "SSID":
        return str(WEB_CFG.get("sn_source_ssid") or "SSID")
    return str(WEB_CFG.get("sn_source_rid") or "RID包")

def _firmware_type_key(v: str | None) -> str:
    s = str(v or "").strip().lower()
    if s in ("new", "new_fw", "new_firmware", "新固件", "新版固件"):
        return "new"
    if s in ("old", "legacy", "old_fw", "old_firmware", "老固件", "旧固件", "旧版固件"):
        return "old"
    return "old"

def _firmware_type_display(v: str | None) -> str:
    return "新版固件" if _firmware_type_key(v) == "new" else "旧版固件"

def _uas_id_clean(v) -> str:
    try:
        s = str(v or "")
    except Exception:
        return ""
    s = "".join(c for c in s.strip() if 32 <= ord(c) <= 126)
    return s[:64]

def init_ap_from_config(cfg: dict | None) -> None:
    global AP_CFG
    AP_CFG = _normalize_ap_cfg(cfg)

def init_model_update_from_config(cfg: dict | None) -> None:
    global MODEL_UPDATE_CFG
    MODEL_UPDATE_CFG = _normalize_model_update_cfg(cfg)

def init_config_update_from_config(cfg: dict | None) -> None:
    global CONFIG_UPDATE_CFG
    CONFIG_UPDATE_CFG = _normalize_config_update_cfg(cfg)

def init_app_update_from_config(cfg: dict | None) -> None:
    global APP_UPDATE_CFG
    APP_UPDATE_CFG = _normalize_app_update_cfg(cfg)

def init_metrics_from_config(cfg: dict | None) -> None:
    global METRICS_CFG
    METRICS_CFG = _normalize_metrics_cfg(cfg)
    if _portable_edition_enabled():
        METRICS_CFG["enabled"] = False

def init_auth_from_config(cfg: dict | None) -> None:
    global AUTH_CFG, AUTH_SESSION_TTL_SEC
    AUTH_CFG = _normalize_auth_cfg(cfg)
    if _portable_edition_enabled():
        AUTH_CFG.update({"enabled": False, "username_hash": "", "password_hash": "", "sso_links": [], "passkeys": []})
        AUTH_CFG["login_methods"] = []
    AUTH_SESSION_TTL_SEC = int(max(60, float(AUTH_CFG.get("session_ttl_min") or 30) * 60.0))
    now_wall = time.time()
    max_exp = now_wall + float(AUTH_SESSION_TTL_SEC)
    with auth_session_lock:
        for tok, exp in list(auth_sessions.items()):
            if float(exp or 0.0) > max_exp:
                auth_sessions[tok] = max_exp

def init_api_from_config(cfg: dict | None) -> None:
    global API_CFG
    API_CFG = _normalize_api_cfg(cfg)
    if _portable_edition_enabled():
        API_CFG.update({"enabled": False, "token": "", "token_hash": "", "tokens": []})

def init_notify_from_config(cfg: dict | None) -> None:
    global NOTIFY_CFG
    NOTIFY_CFG = _normalize_notify_cfg(cfg)
    if _portable_edition_enabled():
        NOTIFY_CFG.update({"enabled": False, "wecom_webhooks": [], "wecom_webhook_key": ""})
    hooks = _notify_wecom_targets(NOTIFY_CFG)
    if NOTIFY_CFG.get("enabled") and hooks:
        _log(f"[INFO] WeCom robot notification enabled ({len(hooks)} channel(s), online-only)")
    else:
        _log("[INFO] notify disabled (missing key or disabled)")

def reload_runtime_config(cfg: dict | None) -> tuple[bool, str]:
    global APP_CONFIG, PRINT_INTERVAL, MIN_GAP, LOST_TIMEOUT, CHANGE_ON_RSSI, CHANGE_ON_PL, RSSI_DELTA, DEBUG_MODE
    if not isinstance(cfg, dict):
        return False, "invalid config root"
    APP_CONFIG = _apply_portable_defaults(_deep_merge_dict(default_app_config(), cfg))
    init_web_from_config(APP_CONFIG)
    init_ap_from_config(APP_CONFIG)
    init_model_update_from_config(APP_CONFIG)
    init_config_update_from_config(APP_CONFIG)
    init_app_update_from_config(APP_CONFIG)
    init_metrics_from_config(APP_CONFIG)
    init_network_bindings_from_config(APP_CONFIG)
    init_auth_from_config(APP_CONFIG)
    init_api_from_config(APP_CONFIG)
    init_notify_from_config(APP_CONFIG)

    basic = APP_CONFIG.get("basic")
    if not isinstance(basic, dict):
        basic = {}
    try:
        PRINT_INTERVAL = max(0.2, float(basic.get("time", PRINT_INTERVAL)))
    except Exception:
        pass
    try:
        MIN_GAP = max(0.0, float(basic.get("min_gap", MIN_GAP)))
    except Exception:
        pass
    try:
        LOST_TIMEOUT = max(3.0, min(3600.0, float(basic.get("lost_timeout", basic.get("offline_timeout", LOST_TIMEOUT)))))
    except Exception:
        pass
    try:
        RSSI_DELTA = max(1, int(basic.get("rssi_delta", RSSI_DELTA)))
    except Exception:
        pass
    CHANGE_ON_RSSI = bool(basic.get("change_on_rssi", CHANGE_ON_RSSI))
    CHANGE_ON_PL = bool(basic.get("change_on_payload", CHANGE_ON_PL))
    DEBUG_MODE = bool(basic.get("debug", DEBUG_MODE))
    try:
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG if DEBUG_MODE else logging.WARNING)
    except Exception:
        pass
    return True, "runtime config reloaded"

def _wecom_webhook_url(key: str) -> str:
    return f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
