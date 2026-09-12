"""Configuration domain (defaults, load/save/backup, raw config tree, settings view,
visual settings build, CLI arg merge, per-section normalize helpers).

Extracted from common_core.py during backend module split. Exec'd by runtime.py
(see DEFAULT_CHUNK_FILES) after common_core.py; shared globals resolve at call time.
"""

def _deep_merge_dict(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge_dict(out[k], v)
        else:
            out[k] = v
    return out

def default_app_config() -> dict:
    return {
        "version": 1,
        "basic": {
            "iface": None,
            "channel": None,
            "hop": False,
            "hop_5g": False,
            "scan_wifi_fast": False,
            "ble_scan": False,
            "ble_hci": "",
            "auto_self_heal": True,
            "dwell_2g": DWELL_2G_DEFAULT,
            "dwell_5g": DWELL_5G_DEFAULT,
            "settle": SETTLE_DEFAULT,
            "dwell_on_hit": 2500,
            "hit_cap": 6000,
            "time": DEFAULT_PRINT_INTERVAL,
            "min_gap": DEFAULT_MIN_GAP,
            "lost_timeout": DEFAULT_LOST_TIMEOUT,
            "track_points_limit": TRACK_MAX_POINTS,
            "rssi_delta": 3,
            "change_on_rssi": False,
            "change_on_payload": False,
            "model_map": os.path.join(os.getcwd(), MODEL_MAP_FILE_DEFAULT),
            "history_file": _history_store_default_path(),
            "no_tui": True,
            "debug": False,
        },
        "notify": {
            "enabled": True,
            "only_online": True,
            "notify_reonline": True,
            "reonline_cooldown_sec": int(NOTIFY_REONLINE_COOLDOWN_DEFAULT),
            "skip_mac_only": True,
            "send_timeout_sec": 8,
            "wecom_webhooks": [],
            "wecom_webhook_key": "",
        },
        "web": {
            "dji_lookup_url": DJI_LOOKUP_URL_DEFAULT,
            "allow_restart": True,
            "last_restart_args": "",
            "scan_type_rid": "RID报送",
            "scan_type_phone": "手机快传",
            "sn_source_rid": "RID包",
            "sn_source_ssid": "SSID",
            "base_name": "基站",
            "base_lat": None,
            "base_lon": None,
            "base_zoom": 13,
            "heading_ref_deg": 0.0,
            "map_auto_center_idle_sec": 20,
            "map_tile_url": "",
            "map_tile_subdomains": "",
            "map_tile_attribution": "",
            "map_tile_max_native_zoom": 18,
            "alarm_zones": [],
            "access_list_enabled": False,
            "access_list_mode": "allow",
            "access_list": [],
            "alarm_zone": {
                "enabled": False,
                "lat1": None,
                "lon1": None,
                "lat2": None,
                "lon2": None,
                "name": "报警区域",
            },
        },
        "ap": {
            "list_max": AP_LIST_MAX_DEFAULT,
            "vendor_db_file": os.path.join(os.getcwd(), OUI_DB_DEFAULT),
            "vendor_auto_download": True,
        },
        "model_update": {
            "enabled": True,
            "url": RID_MODELS_UPDATE_URL_DEFAULT,
        },
        "config_update": {
            "enabled": False,
            "url": "",
        },
        "app_update": {
            "enabled": True,
            "release_url": APP_UPDATE_RELEASE_URL_DEFAULT,
            "mirror": "github",
            "custom_mirror": "",
            "force_update": False,
        },
        "metrics": {
            "enabled": False,
            "retention_days": HOST_METRICS_RETENTION_DAYS_DEFAULT,
            "temperature_source": "auto",
        },
        "auth": {
            "enabled": False,
            "username_hash": "",
            "password_hash": "",
            "realm": "XRS",
            "session_ttl_min": 30,
            "login_methods": ["password", "passkey"],
            "sso_links": [],
            "passkeys": [],
        },
        "api": {
            "enabled": False,
            "token": "",
            "token_hash": "",
            "tokens": [],
            "whitelist_enabled": False,
            "whitelist_mode": "allow",
            "whitelist": [],
        },
        "network_bindings": {
            "items": [],
            "ap": {
                "ssid": "XRS-HotSpot",
                "password": "",
                "channel": 6,
                "address": "172.16.0.1",
                "cidr": "172.16.0.1/24",
                "dhcp_start": "172.16.0.20",
                "dhcp_end": "172.16.0.240",
                "http_port": 80,
                "internet_enabled": False,
                "uplink_iface": "",
            },
        },
    }

def _portable_edition_enabled() -> bool:
    return APP_EDITION in ("portable", "pe", "mobile")

def _runtime_resource_path(*parts: str) -> str:
    ctx = globals().get("RUNTIME_CONTEXT")
    base = getattr(ctx, "package_dir", None)
    if base:
        return os.path.abspath(os.path.join(str(base), "resources", *parts))
    return os.path.abspath(os.path.join(os.getcwd(), "resources", *parts))

def _write_json_file(path: str, payload: dict) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)

def _ensure_runtime_json_files(config_path: str | None, history_path: str | None, *, config_locked: bool) -> None:
    if config_path and (not os.path.exists(config_path)) and (not config_locked):
        _write_json_file(config_path, {})
        _log(f"[INFO] config file created: {config_path}")
    if history_path:
        created = not os.path.exists(history_path)
        _history_storage_init(history_path)
        if created:
            _log(f"[INFO] history storage created: {history_path}")

def _apply_portable_defaults(cfg: dict) -> dict:
    if not _portable_edition_enabled():
        return cfg
    out = _deep_merge_dict(default_app_config(), cfg if isinstance(cfg, dict) else {})
    notify = out.setdefault("notify", {})
    notify.update({"enabled": False, "wecom_webhooks": [], "wecom_webhook_key": ""})
    auth = out.setdefault("auth", {})
    auth.update({"enabled": False, "username_hash": "", "password_hash": "", "sso_links": [], "passkeys": []})
    auth["login_methods"] = []
    api = out.setdefault("api", {})
    api.update({"enabled": False, "token": "", "token_hash": "", "tokens": []})
    metrics = out.setdefault("metrics", {})
    metrics["enabled"] = False
    return out

def ensure_config_file(path: str) -> None:
    if not path:
        return
    if os.path.exists(path):
        return
    _set_oobe_required(f"配置文件不存在，已创建默认配置: {path}", True)
    if APP_CONFIG_PATH_LOCKED:
        raise FileNotFoundError(path)
    cfg = {}
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    rb_path = path + CONFIG_ROLLBACK_SUFFIX
    try:
        shutil.copy2(path, rb_path)
    except Exception as e:
        _log(f"[WARN] 配置回滚副本创建失败: {e}")
    _log(f"[INFO] config file created: {path}")

def _config_isolate_file(path: str | None, tag: str = "broken") -> str | None:
    if not path or (not os.path.exists(path)):
        return None
    ts = time.strftime("%Y%m%d%H%M%S")
    dst = f"{path}.{tag}.{ts}"
    try:
        os.replace(path, dst)
        return dst
    except Exception:
        return None

def _config_load_raw(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("root must be object")
    return raw

def _cfg_preferred_iface_from_cfg(cfg: dict | None) -> str | None:
    try:
        basic = cfg.get("basic") if isinstance(cfg, dict) else {}
        if not isinstance(basic, dict):
            basic = {}
        v = basic.get("iface")
        if v not in (None, ""):
            s = str(v).strip()
            if s:
                return s
        nb = cfg.get("network_bindings") if isinstance(cfg, dict) else {}
        items = nb.get("items") if isinstance(nb, dict) else []
        if isinstance(items, list):
            for item in items:
                role = str((item or {}).get("role") or "").strip().lower().replace("-", "_") if isinstance(item, dict) else ""
                if role in ("scan", "scanner", "capture"):
                    s = str(item.get("iface") or "").strip()
                    if s:
                        return s
        return None
    except Exception:
        return None

def load_app_config(path: str | None) -> dict:
    if not path:
        _set_oobe_required("配置路径为空，使用默认配置", True)
        return default_app_config()
    rb_path = path + CONFIG_ROLLBACK_SUFFIX
    try:
        ensure_config_file(path)
        raw = _config_load_raw(path)
        cfg = _apply_portable_defaults(_deep_merge_dict(default_app_config(), raw))
        try:
            shutil.copy2(path, rb_path)
        except Exception as e:
            _log(f"[WARN] 配置回滚副本刷新失败: {e}")
        if not _cfg_preferred_iface_from_cfg(cfg):
            _set_oobe_required("尚未绑定默认网卡，请进入 OOBE 或设置页完成配置", True)
        else:
            _set_oobe_required("", False)
        _log(f"[INFO] config loaded: {path}")
        return cfg
    except Exception as e:
        _log(f"[WARN] config load failed: {e}")
        _set_oobe_required(f"配置文件异常: {e}", True)
        # Try rollback snapshot first.
        if os.path.exists(rb_path):
            try:
                rb_raw = _config_load_raw(rb_path)
                cfg = _apply_portable_defaults(_deep_merge_dict(default_app_config(), rb_raw))
                broken = _config_isolate_file(path, "broken")
                if broken:
                    _log(f"[WARN] 主配置文件已隔离为: {broken}")
                ok, msg = save_app_config(path, cfg)
                if ok:
                    _log(f"[INFO] 已从回滚配置恢复: {msg}")
                else:
                    _log(f"[WARN] 回滚恢复写回失败: {msg}")
                return cfg
            except Exception as e_rb:
                _log(f"[WARN] rollback config load failed: {e_rb}")
                rb_broken = _config_isolate_file(rb_path, "broken")
                if rb_broken:
                    _log(f"[WARN] 回滚配置文件已隔离为: {rb_broken}")

        _log("[WARN] 配置回滚不可用，使用默认配置重建")
        if APP_CONFIG_PATH_LOCKED and (not os.path.exists(path)):
            _log(f"[WARN] locked config missing, using in-memory defaults: {path}")
            return _apply_portable_defaults(default_app_config())
        cfg = _apply_portable_defaults(default_app_config())
        try:
            broken = _config_isolate_file(path, "broken")
            if broken:
                _log(f"[WARN] 配置文件已隔离为: {broken}")
            rb_broken = _config_isolate_file(rb_path, "broken")
            if rb_broken:
                _log(f"[WARN] 回滚配置文件已隔离为: {rb_broken}")
            ok, msg = save_app_config(path, cfg)
            if ok:
                _log(f"[INFO] 已写入默认配置: {msg}")
        except Exception as e2:
            _log(f"[WARN] 配置守护写回失败: {e2}")
        return cfg

def save_app_config(path: str | None, cfg: dict) -> tuple[bool, str]:
    if not path:
        return False, "missing config path"
    tmp_path = path + ".tmp"
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
        # Keep a rollback snapshot in sync for self-protection.
        rb_path = path + CONFIG_ROLLBACK_SUFFIX
        rb_tmp = rb_path + ".tmp"
        try:
            with open(rb_tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(rb_tmp, rb_path)
        except Exception as e:
            try:
                if os.path.exists(rb_tmp):
                    os.remove(rb_tmp)
            except Exception:
                pass
            _log(f"[WARN] 配置回滚副本写入失败: {e}")
        return True, path
    except Exception as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False, str(e)

def create_config_backup(path: str | None, tag: str = "save") -> tuple[bool, str]:
    if not path:
        return False, "missing config path"
    if not os.path.exists(path):
        return True, ""
    try:
        parent = os.path.dirname(path) or os.getcwd()
        backup_dir = os.path.join(parent, "backups")
        os.makedirs(backup_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        base = os.path.basename(path)
        dst = os.path.join(backup_dir, f"{base}.{tag}.{ts}.bak")
        shutil.copy2(path, dst)
        try:
            backups = []
            prefix = base + "."
            for name in os.listdir(backup_dir):
                p = os.path.join(backup_dir, name)
                if not (os.path.isfile(p) and name.startswith(prefix) and name.endswith(".bak")):
                    continue
                backups.append((os.path.getmtime(p), p))
            backups.sort(reverse=True)
            for _mtime, old_path in backups[5:]:
                try:
                    os.remove(old_path)
                except Exception:
                    pass
        except Exception:
            pass
        return True, dst
    except Exception as e:
        return False, str(e)

def restore_config_backup(path: str | None, backup_path: str | None) -> tuple[bool, str]:
    if not path or not backup_path:
        return False, "backup path missing"
    if not os.path.exists(backup_path):
        return False, "backup not found"
    try:
        shutil.copy2(backup_path, path)
        return True, path
    except Exception as e:
        return False, str(e)

# -----------------------------------------------------------------------------
# Raw config editor helpers
# -----------------------------------------------------------------------------
def _config_root_dir() -> str:
    path = APP_CONFIG_PATH or os.path.join(os.getcwd(), CONFIG_FILE_DEFAULT)
    try:
        return os.path.abspath(os.path.dirname(path) or os.getcwd())
    except Exception:
        return os.path.abspath(os.getcwd())

def _config_path_within_root(path: str | None, root_dir: str | None = None) -> bool:
    # The raw-config UI is intentionally jailed to the active config root.
    if not path:
        return False
    try:
        root = os.path.abspath(root_dir or _config_root_dir())
        candidate = os.path.abspath(str(path))
        return os.path.commonpath([root, candidate]) == root
    except Exception:
        return False

def _config_rel_path(path: str | None, root_dir: str | None = None) -> str:
    if not path:
        return ""
    try:
        root = os.path.abspath(root_dir or _config_root_dir())
        candidate = os.path.abspath(str(path))
        if not _config_path_within_root(candidate, root):
            return ""
        rel = os.path.relpath(candidate, root)
        return "." if rel == "." else rel.replace("\\", "/")
    except Exception:
        return ""

def _config_resolve_path(path: str | None, root_dir: str | None = None) -> str | None:
    raw = str(path or "").strip()
    if not raw:
        return None
    root = os.path.abspath(root_dir or _config_root_dir())
    candidate = os.path.abspath(raw if os.path.isabs(raw) else os.path.join(root, raw))
    if not _config_path_within_root(candidate, root):
        return None
    return candidate

def _config_file_stat(path: str) -> dict:
    st = os.stat(path)
    return {
        "path": path,
        "name": os.path.basename(path),
        "rel_path": _config_rel_path(path),
        "type": "file",
        "size": int(st.st_size),
        "mtime": float(st.st_mtime),
    }

def _config_tree_entries(root_dir: str | None = None, *, max_depth: int = 3, max_entries: int = 600) -> dict:
    root = os.path.abspath(root_dir or _config_root_dir())
    root_name = os.path.basename(root.rstrip("\\/")) or root
    visited = 0

    def walk(dir_path: str, depth: int) -> list[dict]:
        nonlocal visited
        nodes: list[dict] = []
        if depth < 0 or visited >= max_entries:
            return nodes
        try:
            entries = list(os.scandir(dir_path))
        except Exception:
            return nodes
        dirs: list[os.DirEntry] = []
        files: list[os.DirEntry] = []
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    dirs.append(entry)
                elif entry.is_file(follow_symlinks=False):
                    files.append(entry)
            except Exception:
                continue
        for entry in sorted(dirs, key=lambda e: e.name.lower()):
            visited += 1
            if visited > max_entries:
                break
            child_path = entry.path
            node = {
                "name": entry.name,
                "path": child_path,
                "rel_path": _config_rel_path(child_path, root),
                "type": "dir",
                "children": [],
            }
            if depth > 0:
                node["children"] = walk(child_path, depth - 1)
            nodes.append(node)
        for entry in sorted(files, key=lambda e: e.name.lower()):
            visited += 1
            if visited > max_entries:
                break
            try:
                nodes.append(_config_file_stat(entry.path))
            except Exception:
                continue
        return nodes
    return {
        "root": root,
        "root_name": root_name,
        "tree": walk(root, max(0, int(max_depth or 0))),
    }

# Raw config editing uses a short-lived secondary unlock tied to the current
# page session so the password check does not permanently open write access.
def _raw_config_unlock_key(cookie_header: str | None) -> str:
    return _auth_cookie_parse(cookie_header, AUTH_SESSION_COOKIE)

def _raw_config_unlock_cleanup(now_wall: float | None = None) -> None:
    now_wall = float(now_wall or time.time())
    with raw_config_unlock_lock:
        stale = [k for k, exp in raw_config_unlocks.items() if float(exp or 0.0) <= now_wall]
        for key in stale:
            raw_config_unlocks.pop(key, None)

def _raw_config_unlock_set(cookie_header: str | None, ttl_sec: int = RAW_CONFIG_UNLOCK_TTL_SEC) -> bool:
    key = _raw_config_unlock_key(cookie_header)
    if not key:
        return False
    now_wall = time.time()
    with raw_config_unlock_lock:
        raw_config_unlocks[key] = now_wall + float(max(60, int(ttl_sec or RAW_CONFIG_UNLOCK_TTL_SEC)))
        if len(raw_config_unlocks) > 4096:
            stale = [k for k, exp in raw_config_unlocks.items() if float(exp or 0.0) <= now_wall]
            for item in stale[:2048]:
                raw_config_unlocks.pop(item, None)
    return True

def _raw_config_unlocked(cookie_header: str | None) -> bool:
    key = _raw_config_unlock_key(cookie_header)
    if not key:
        return False
    now_wall = time.time()
    with raw_config_unlock_lock:
        exp = raw_config_unlocks.get(key)
        if not exp or float(exp) <= now_wall:
            raw_config_unlocks.pop(key, None)
            return False
        return True

def _raw_config_access_payload(headers=None) -> dict:
    unlocked = _raw_config_unlocked(headers.get("Cookie") if headers is not None else None)
    return {
        "required": bool(_auth_enabled() and _auth_hashes_present(AUTH_CFG)),
        "unlocked": bool(unlocked),
        "ttl_sec": int(RAW_CONFIG_UNLOCK_TTL_SEC),
        "root": _config_root_dir(),
    }

def _config_file_payload(path: str | None = None, *, root_dir: str | None = None) -> dict:
    root = os.path.abspath(root_dir or _config_root_dir())
    abs_path = _config_resolve_path(path or APP_CONFIG_PATH or os.path.join(root, CONFIG_FILE_DEFAULT), root)
    if not abs_path:
        raise ValueError("invalid config path")
    with open(abs_path, "r", encoding="utf-8") as f:
        text = f.read()
    stat = os.stat(abs_path)
    return {
        "ok": True,
        "path": abs_path,
        "rel_path": _config_rel_path(abs_path, root),
        "root": root,
        "name": os.path.basename(abs_path),
        "text": text,
        "size": int(stat.st_size),
        "mtime": float(stat.st_mtime),
        "tree": _config_tree_entries(root),
        "raw_access": _raw_config_access_payload(),
    }

def _config_file_save_payload(path: str | None, text: str, *, tag: str = "raw") -> dict:
    root = _config_root_dir()
    abs_path = _config_resolve_path(path or APP_CONFIG_PATH or os.path.join(root, CONFIG_FILE_DEFAULT), root)
    if not abs_path:
        raise ValueError("invalid config path")
    raw_text = str(text or "")
    if not raw_text.strip():
        raise ValueError("empty config text")
    try:
        parsed = json.loads(raw_text)
        if not isinstance(parsed, dict):
            raise ValueError("config root must be object")
    except Exception as e:
        raise ValueError(f"invalid json: {e}") from e
    parsed = _deep_merge_dict(default_app_config(), parsed)
    parsed, guard_err = _prepare_security_cfg_for_save(parsed)
    if guard_err:
        raise ValueError(guard_err)
    b_ok, backup_path = create_config_backup(abs_path, tag=tag)
    if not b_ok:
        raise ValueError(f"backup failed: {backup_path}")
    ok, msg = save_app_config(abs_path, parsed)
    if not ok:
        raise ValueError(f"save failed: {msg}")
    reload_msg = "skipped"
    if APP_CONFIG_PATH and os.path.abspath(abs_path) == os.path.abspath(APP_CONFIG_PATH):
        cfg_loaded = load_app_config(abs_path)
        r_ok, r_msg = reload_runtime_config(cfg_loaded)
        if not r_ok:
            restore_config_backup(abs_path, backup_path)
            raise ValueError(f"reload failed: {r_msg}")
        reload_msg = r_msg
    return {
        "ok": True,
        "saved_to": abs_path,
        "backup_path": backup_path,
        "reloaded": bool(APP_CONFIG_PATH and os.path.abspath(abs_path) == os.path.abspath(APP_CONFIG_PATH)),
        "reload_msg": reload_msg,
        "root": root,
        "raw_access": _raw_config_access_payload(),
    }

def _config_file_delete_payload(path: str | None) -> dict:
    root = _config_root_dir()
    abs_path = _config_resolve_path(path or "", root)
    if not abs_path:
        raise ValueError("invalid config path")
    if APP_CONFIG_PATH and os.path.abspath(abs_path) == os.path.abspath(APP_CONFIG_PATH):
        raise ValueError("active config file cannot be deleted")
    if not os.path.exists(abs_path):
        raise ValueError("file not found")
    backup_path = ""
    try:
        b_ok, backup_path = create_config_backup(abs_path, tag="delete")
        if not b_ok:
            raise ValueError(f"backup failed: {backup_path}")
        os.remove(abs_path)
        return {
            "ok": True,
            "deleted": True,
            "deleted_path": abs_path,
            "backup_path": backup_path,
            "root": root,
            "raw_access": _raw_config_access_payload(),
        }
    except Exception:
        raise

def _settings_view_payload() -> dict:
    cfg = load_app_config(APP_CONFIG_PATH) if APP_CONFIG_PATH else default_app_config()
    basic = cfg.get("basic") if isinstance(cfg, dict) else {}
    if not isinstance(basic, dict):
        basic = {}
    notify = cfg.get("notify") if isinstance(cfg, dict) else {}
    if not isinstance(notify, dict):
        notify = {}
    web = cfg.get("web") if isinstance(cfg, dict) else {}
    if not isinstance(web, dict):
        web = {}
    api = cfg.get("api") if isinstance(cfg, dict) else {}
    if not isinstance(api, dict):
        api = {}
    auth = cfg.get("auth") if isinstance(cfg, dict) else {}
    if not isinstance(auth, dict):
        auth = {}
    model_update = _normalize_model_update_cfg(cfg)
    config_update = _normalize_config_update_cfg(cfg)
    app_update = _normalize_app_update_cfg(cfg)
    metrics_cfg = _normalize_metrics_cfg(cfg)
    api_prepared = _prepare_api_cfg_for_save(api)
    auth_prepared = _prepare_auth_cfg_for_save(auth)
    notify_norm = _normalize_notify_cfg({"notify": notify})
    web_norm = _normalize_web_cfg({"web": web})
    zones = list(web_norm.get("alarm_zones") or [])
    hooks = list(notify_norm.get("wecom_webhooks") or [])
    channel_raw = basic.get("channel")
    try:
        channel_effective = int(channel_raw) if channel_raw not in (None, "") else 6
    except Exception:
        channel_effective = 6
    selected_iface = None if basic.get("iface") in (None, "") else str(basic.get("iface"))
    interfaces = []
    seen_ifaces: set[str] = set()
    for iface_name in (selected_iface, str(sniff_iface_name or "").strip()):
        iface_name = str(iface_name or "").strip()
        if not iface_name or iface_name in seen_ifaces:
            continue
        seen_ifaces.add(iface_name)
        interfaces.append({
            "name": iface_name,
            "mode": "",
            "is_monitor": False,
            "is_wireless": True,
            "admin_up": None,
            "supports_5g": False,
            "model": "",
            "ipv4": [],
        })
    host = _host_resource_snapshot()
    host["active_iface"] = str(sniff_iface_name or selected_iface or "")
    host["current_channel"] = int(current_channel or channel_effective or 6)
    host["sniff_state"] = _sniff_health_meta(time.monotonic(), time.time())
    host["ifaces"] = interfaces
    fixed_history_path = HISTORY_STORE_PATH or _history_store_default_path(APP_CONFIG_PATH)
    scan_data_file = _scan_data_file_info(fixed_history_path)
    api_tokens_public = _api_tokens_public(api_prepared)
    return {
        "ok": True,
        "path": APP_CONFIG_PATH or "",
        "visual": {
            "basic": {
                "iface": None if basic.get("iface") in (None, "") else str(basic.get("iface")),
                "channel": channel_raw,
                "channel_effective": channel_effective,
                "channel_custom": channel_raw not in (None, ""),
                "hop": bool(basic.get("hop")),
                "hop_5g": bool(basic.get("hop_5g")),
                "scan_wifi_fast": bool(basic.get("scan_wifi_fast")),
                "auto_self_heal": bool(basic.get("auto_self_heal", True)),
                "dwell_2g": basic.get("dwell_2g", DWELL_2G_DEFAULT),
                "dwell_5g": basic.get("dwell_5g", DWELL_5G_DEFAULT),
                "settle": basic.get("settle", SETTLE_DEFAULT),
                "dwell_on_hit": basic.get("dwell_on_hit", 2500),
                "hit_cap": basic.get("hit_cap", 6000),
                "time": basic.get("time", DEFAULT_PRINT_INTERVAL),
                "min_gap": basic.get("min_gap", DEFAULT_MIN_GAP),
                "lost_timeout": basic.get("lost_timeout", basic.get("offline_timeout", DEFAULT_LOST_TIMEOUT)),
                "track_points_limit": _track_store_points_limit(),
                "rssi_delta": basic.get("rssi_delta", 3),
                "change_on_rssi": bool(basic.get("change_on_rssi")),
                "change_on_payload": bool(basic.get("change_on_payload")),
                "debug": bool(basic.get("debug")),
                "model_map": str(basic.get("model_map") or os.path.join(os.getcwd(), MODEL_MAP_FILE_DEFAULT)),
                "history_file": fixed_history_path,
            },
            "notify": {
                "enabled": bool(notify_norm.get("enabled")),
                "notify_reonline": bool(notify_norm.get("notify_reonline", True)),
                "reonline_cooldown_sec": int(notify_norm.get("reonline_cooldown_sec") or NOTIFY_REONLINE_COOLDOWN_DEFAULT),
                "send_timeout_sec": int(notify_norm.get("send_timeout_sec") or 8),
                "wecom_webhook_key_masked": (_mask_secret(str(hooks[0].get("key") or "")) if hooks else ""),
                "wecom_webhooks": [
                    {
                        "index": idx,
                        "name": str(item.get("name") or f"通道 {idx + 1}"),
                        "enabled": bool(item.get("enabled", True)),
                        "key_masked": _mask_secret(str(item.get("key") or "")),
                    }
                    for idx, item in enumerate(hooks)
                ],
            },
            "web": {
                "dji_lookup_url": str(web_norm.get("dji_lookup_url") or DJI_LOOKUP_URL_DEFAULT),
                "base_name": str(web_norm.get("base_name") or "基站"),
                "base_lat": web_norm.get("base_lat"),
                "base_lon": web_norm.get("base_lon"),
                "base_zoom": web_norm.get("base_zoom", 13),
                "heading_ref_deg": web_norm.get("heading_ref_deg", 0.0),
                "map_auto_center_idle_sec": web_norm.get("map_auto_center_idle_sec", 20),
                "map_tile_url": str(web_norm.get("map_tile_url") or ""),
                "map_tile_subdomains": str(web_norm.get("map_tile_subdomains") or ""),
                "map_tile_attribution": str(web_norm.get("map_tile_attribution") or ""),
                "map_tile_max_native_zoom": web_norm.get("map_tile_max_native_zoom", 18),
                "access_list_enabled": bool(web_norm.get("access_list_enabled")),
                "access_list_mode": str(web_norm.get("access_list_mode") or "allow"),
                "access_list": list(web_norm.get("access_list") or []),
                "alarm_zones": zones,
            },
            "api": {
                "enabled": bool(api_prepared.get("enabled")),
                "configured": _api_tokens_have_secret(api_prepared),
                "tokens": api_tokens_public,
                "whitelist_effective": _api_tokens_have_secret(api_prepared),
                "whitelist_enabled": bool(api_prepared.get("whitelist_enabled")),
                "whitelist_mode": str(api_prepared.get("whitelist_mode") or "allow"),
                "whitelist": list(api_prepared.get("whitelist") or []),
            },
            "auth": {
                "enabled": bool(auth_prepared.get("enabled")),
                "configured": _auth_hashes_present(auth_prepared),
                "username_masked": ("已设置" if str(auth_prepared.get("username_hash") or "").strip() else ""),
                "password_masked": ("********" if str(auth_prepared.get("password_hash") or "").strip() else ""),
                "realm": str(auth_prepared.get("realm") or "XRS"),
                "session_ttl_min": int(auth_prepared.get("session_ttl_min") or 30),
                "login_methods": list(auth_prepared.get("login_methods") or []),
                "sso_links": _auth_sso_public_links(auth_prepared),
                "passkeys": _auth_passkeys_public(auth_prepared),
            },
            "model_update": {
                "enabled": bool(model_update.get("enabled")),
                "url": "" if str(model_update.get("url") or "").strip() in ("", RID_MODELS_UPDATE_URL_DEFAULT) else str(model_update.get("url") or ""),
                "state": _model_update_status_payload(),
            },
            "config_update": {
                "enabled": bool(config_update.get("enabled")),
                "url": str(config_update.get("url") or ""),
                "state": _config_update_status_payload(),
            },
            "app_update": {
                "enabled": bool(app_update.get("enabled", True)),
                "release_url": str(app_update.get("release_url") or APP_UPDATE_RELEASE_URL_DEFAULT),
                "mirror": str(app_update.get("mirror") or "github"),
                "custom_mirror": str(app_update.get("custom_mirror") or ""),
                "force_update": bool(app_update.get("force_update")),
                "mirror_options": list(APP_UPDATE_MIRROR_OPTIONS),
                "state": _app_update_status_payload(consume_notice=True),
            },
            "metrics": {
                "enabled": bool(metrics_cfg.get("enabled")),
                "retention_days": int(metrics_cfg.get("retention_days") or HOST_METRICS_RETENTION_DAYS_DEFAULT),
                "temperature_source": str(metrics_cfg.get("temperature_source") or "auto"),
                "store_path": HOST_METRICS_PATH,
                "sample_interval_sec": int(HOST_METRICS_SAMPLE_SEC),
            },
            "network_bindings": _network_bindings_visual_payload(cfg),
        },
        "host": host,
        "interfaces": interfaces,
        "oobe": _oobe_state(),
        "eula": _eula_status_payload(),
        "raw_access": _raw_config_access_payload(),
        "scan_data_file": scan_data_file,
        "history_storage_notice": _history_storage_notice_payload(consume=True),
        "hardware_link": "/hardware-assistant",
    }

def _build_visual_settings_candidate(body: dict | None) -> tuple[dict | None, str | None]:
    if not APP_CONFIG_PATH:
        return None, "config path missing"
    payload = body if isinstance(body, dict) else {}
    cfg = load_app_config(APP_CONFIG_PATH)
    basic = cfg.setdefault("basic", {})
    notify = cfg.setdefault("notify", {})
    web = cfg.setdefault("web", {})
    api = cfg.setdefault("api", {})
    auth = cfg.setdefault("auth", {})
    model_update = cfg.setdefault("model_update", {})
    app_update = cfg.setdefault("app_update", {})
    metrics = cfg.setdefault("metrics", {})
    if not isinstance(basic, dict): basic = {}; cfg["basic"] = basic
    if not isinstance(notify, dict): notify = {}; cfg["notify"] = notify
    if not isinstance(web, dict): web = {}; cfg["web"] = web
    if not isinstance(api, dict): api = {}; cfg["api"] = api
    if not isinstance(auth, dict): auth = {}; cfg["auth"] = auth
    if not isinstance(model_update, dict): model_update = {}; cfg["model_update"] = model_update
    if not isinstance(app_update, dict): app_update = {}; cfg["app_update"] = app_update
    if not isinstance(metrics, dict): metrics = {}; cfg["metrics"] = metrics

    p_basic = payload.get("basic") if isinstance(payload.get("basic"), dict) else {}
    p_notify = payload.get("notify") if isinstance(payload.get("notify"), dict) else {}
    p_web = payload.get("web") if isinstance(payload.get("web"), dict) else {}
    p_api = payload.get("api") if isinstance(payload.get("api"), dict) else {}
    p_auth = payload.get("auth") if isinstance(payload.get("auth"), dict) else {}
    p_model_update = payload.get("model_update") if isinstance(payload.get("model_update"), dict) else {}
    p_app_update = payload.get("app_update") if isinstance(payload.get("app_update"), dict) else {}
    p_metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    p_network_bindings = payload.get("network_bindings") if isinstance(payload.get("network_bindings"), dict) else {}

    iface_raw = p_basic.get("iface")
    iface = None if iface_raw in (None, "") else str(iface_raw).strip()
    if not iface:
        return None, "必须选择并绑定默认网卡"
    safe_iface = _hw_safe_iface(iface)
    if not safe_iface:
        return None, "invalid iface"
    iface = safe_iface
    basic["iface"] = iface
    if bool(p_basic.get("channel_use_default")):
        basic["channel"] = None
    else:
        try:
            basic["channel"] = None if p_basic.get("channel") in (None, "") else int(p_basic.get("channel"))
        except Exception:
            return {"ok": False, "error": "invalid channel"}
    for k in ("hop", "hop_5g", "scan_wifi_fast", "ble_scan", "auto_self_heal", "change_on_rssi", "change_on_payload", "debug", "no_tui"):
        if k in p_basic:
            basic[k] = bool(p_basic.get(k))
    if "ble_hci" in p_basic:
        basic["ble_hci"] = str(p_basic.get("ble_hci") or "").strip()
    for k, default_v in (
        ("time", DEFAULT_PRINT_INTERVAL),
        ("min_gap", DEFAULT_MIN_GAP),
        ("lost_timeout", DEFAULT_LOST_TIMEOUT),
        ("track_points_limit", TRACK_MAX_POINTS),
        ("dwell_2g", DWELL_2G_DEFAULT),
        ("dwell_5g", DWELL_5G_DEFAULT),
        ("settle", SETTLE_DEFAULT),
        ("dwell_on_hit", 2500),
        ("hit_cap", 6000),
    ):
        if k in p_basic:
            try:
                basic[k] = max(0.0, float(p_basic.get(k)))
            except Exception:
                return {"ok": False, "error": f"invalid {k}"}
            if k == "track_points_limit":
                basic[k] = max(TRACK_STORE_POINTS_MIN, min(int(round(float(basic[k]))), TRACK_STORE_POINTS_MAX))
            elif k not in ("time", "min_gap"):
                basic[k] = int(round(float(basic[k])))
    if "rssi_delta" in p_basic:
        try:
            basic["rssi_delta"] = max(1, int(p_basic.get("rssi_delta")))
        except Exception:
            return {"ok": False, "error": "invalid rssi_delta"}
    if "model_map" in p_basic:
        basic["model_map"] = str(p_basic.get("model_map") or "").strip()
    basic["history_file"] = HISTORY_STORE_PATH or _history_store_default_path(APP_CONFIG_PATH)

    for k in ("enabled", "notify_reonline"):
        if k in p_notify:
            notify[k] = bool(p_notify.get(k))
    for k, min_v in (("reonline_cooldown_sec", 0), ("send_timeout_sec", 2)):
        if k in p_notify:
            try:
                notify[k] = max(min_v, int(p_notify.get(k)))
            except Exception:
                return {"ok": False, "error": f"invalid {k}"}
    hooks_payload = p_notify.get("wecom_webhooks")
    if isinstance(hooks_payload, list):
        existing_hooks = _normalize_notify_cfg({"notify": notify}).get("wecom_webhooks") or []
        hooks_next: list[dict] = []
        for idx, item in enumerate(hooks_payload):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or f"通道 {idx + 1}").strip() or f"通道 {idx + 1}"
            enabled = bool(item.get("enabled", True))
            cur_key = ""
            try:
                src_idx = int(item.get("index"))
                if 0 <= src_idx < len(existing_hooks):
                    cur_key = str(existing_hooks[src_idx].get("key") or "").strip()
            except Exception:
                cur_key = ""
            raw = str(item.get("key") or "").strip()
            if raw in ("", "********", "__KEEP__"):
                raw = cur_key
            if not raw:
                continue
            hooks_next.append({"name": name, "enabled": enabled, "key": raw})
        notify["wecom_webhooks"] = _normalize_wecom_webhooks(hooks_next, "")
        notify["wecom_webhook_key"] = str((notify["wecom_webhooks"][0]["key"] if notify["wecom_webhooks"] else "") or "")
    else:
        new_wecom = p_notify.get("wecom_webhook_key")
        if new_wecom is not None:
            raw = str(new_wecom or "").strip()
            if raw not in ("", "********", "__KEEP__"):
                notify["wecom_webhook_key"] = raw
        notify["wecom_webhooks"] = _normalize_wecom_webhooks(notify.get("wecom_webhooks"), notify.get("wecom_webhook_key") or "")
        notify["wecom_webhook_key"] = str((notify["wecom_webhooks"][0]["key"] if notify["wecom_webhooks"] else notify.get("wecom_webhook_key") or "") or "")

    for k in ("dji_lookup_url", "base_name", "map_tile_attribution"):
        if k in p_web:
            web[k] = str(p_web.get(k) or "").strip()
    if "map_tile_url" in p_web:
        tile_url = str(p_web.get("map_tile_url") or "").strip()
        if tile_url:
            has_tokens = all(token in tile_url for token in ("{x}", "{y}", "{z}"))
            parsed = urllib.parse.urlparse(tile_url)
            local_path = tile_url.startswith("/")
            remote_url = parsed.scheme in ("http", "https") and bool(parsed.netloc)
            if not has_tokens or not (local_path or remote_url):
                return {"ok": False, "error": "map_tile_url must be an http(s) or local tile template containing {z}, {x}, and {y}"}
        web["map_tile_url"] = tile_url
    if "map_tile_subdomains" in p_web:
        raw_subdomains = p_web.get("map_tile_subdomains")
        if isinstance(raw_subdomains, list):
            parts = [str(x or "").strip() for x in raw_subdomains]
        else:
            parts = re.split(r"[\s,]+", str(raw_subdomains or "").strip())
        parts = [x for x in parts if x]
        if any(len(x) > 32 for x in parts) or len(parts) > 16:
            return {"ok": False, "error": "invalid map_tile_subdomains"}
        web["map_tile_subdomains"] = ",".join(parts)
    for k, lo, hi in (("base_lat", -90.0, 90.0), ("base_lon", -180.0, 180.0)):
        if k in p_web:
            try:
                raw_v = p_web.get(k)
                web[k] = None if raw_v in (None, "") else float(raw_v)
            except Exception:
                return {"ok": False, "error": f"invalid {k}"}
            if web[k] is not None and not (lo <= float(web[k]) <= hi):
                return {"ok": False, "error": f"{k} out of range"}
    for k, mn, mx in (("base_zoom", 3, 30), ("map_auto_center_idle_sec", 5, 600), ("map_tile_max_native_zoom", 1, 30)):
        if k in p_web:
            try:
                web[k] = max(mn, min(mx, int(p_web.get(k))))
            except Exception:
                return {"ok": False, "error": f"invalid {k}"}
    if "heading_ref_deg" in p_web:
        try:
            hd = float(p_web.get("heading_ref_deg") if p_web.get("heading_ref_deg") not in (None, "") else 0.0)
            hd = hd % 360.0
            if hd < 0:
                hd += 360.0
            web["heading_ref_deg"] = round(hd, 2)
        except Exception:
            return {"ok": False, "error": "invalid heading_ref_deg"}
    zones_payload = p_web.get("alarm_zones")
    if isinstance(zones_payload, list):
        zones_next: list[dict] = []
        for idx, zone in enumerate(zones_payload):
            if not isinstance(zone, dict):
                continue
            zone_cfg = {
                "enabled": bool(zone.get("enabled", False)),
                "name": str(zone.get("name") or f"报警区域 {idx + 1}").strip() or f"报警区域 {idx + 1}",
            }
            provided = 0
            for k, lo, hi in (("lat1", -90.0, 90.0), ("lat2", -90.0, 90.0), ("lon1", -180.0, 180.0), ("lon2", -180.0, 180.0)):
                try:
                    raw_v = zone.get(k)
                    zone_cfg[k] = None if raw_v in (None, "") else float(raw_v)
                except Exception:
                    return {"ok": False, "error": f"invalid alarm_zones[{idx}].{k}"}
                if zone_cfg[k] is not None:
                    provided += 1
                    if not (lo <= float(zone_cfg[k]) <= hi):
                        return {"ok": False, "error": f"alarm_zones[{idx}].{k} out of range"}
            if provided == 0:
                zone_cfg["enabled"] = False
            elif provided != 4:
                return {"ok": False, "error": f"alarm_zones[{idx}] incomplete"}
            zones_next.append(zone_cfg)
        web["alarm_zones"] = zones_next
        web["alarm_zone"] = zones_next[0] if zones_next else _normalize_alarm_zone_item({}, idx=1)
    else:
        zone = p_web.get("alarm_zone") if isinstance(p_web.get("alarm_zone"), dict) else {}
        zone_cfg = dict(web.get("alarm_zone") or {})
        zone_cfg["enabled"] = bool(zone.get("enabled", zone_cfg.get("enabled", False)))
        zone_cfg["name"] = str(zone.get("name") or zone_cfg.get("name") or "报警区域").strip() or "报警区域"
        for k, lo, hi in (("lat1", -90.0, 90.0), ("lat2", -90.0, 90.0), ("lon1", -180.0, 180.0), ("lon2", -180.0, 180.0)):
            if k in zone:
                try:
                    raw_v = zone.get(k)
                    zone_cfg[k] = None if raw_v in (None, "") else float(raw_v)
                except Exception:
                    return {"ok": False, "error": f"invalid alarm_zone.{k}"}
                if zone_cfg[k] is not None and not (lo <= float(zone_cfg[k]) <= hi):
                    return {"ok": False, "error": f"alarm_zone.{k} out of range"}
        web["alarm_zone"] = zone_cfg
        web["alarm_zones"] = _normalize_alarm_zones([], zone_cfg)

    if "enabled" in p_api:
        api["enabled"] = bool(p_api.get("enabled"))
    if "whitelist_enabled" in p_api:
        api["whitelist_enabled"] = bool(p_api.get("whitelist_enabled"))
    if "whitelist_mode" in p_api:
        mode = str(p_api.get("whitelist_mode") or "allow").strip().lower()
        api["whitelist_mode"] = "deny" if mode in ("deny", "block", "black", "blacklist") else "allow"
    if "whitelist" in p_api:
        api["whitelist"] = _parse_whitelist_entries(p_api.get("whitelist"))

    if "enabled" in p_auth:
        auth["enabled"] = bool(p_auth.get("enabled"))
    if "realm" in p_auth:
        auth["realm"] = str(p_auth.get("realm") or "XRS").strip() or "XRS"
    if "session_ttl_min" in p_auth:
        try:
            auth["session_ttl_min"] = max(1, min(10080, int(p_auth.get("session_ttl_min") or 30)))
        except Exception:
            return None, "invalid session_ttl_min"
    if "login_methods" in p_auth:
        auth["login_methods"] = _normalize_auth_login_methods(
            p_auth.get("login_methods"),
            default_missing=[],
            default_empty=[],
        )
    if "username" in p_auth:
        raw_user = str(p_auth.get("username") or "").strip()
        if raw_user not in ("", "__KEEP__", "已设置"):
            auth["username_hash"] = _auth_secret_hash(raw_user)
        elif raw_user.lower() == "__clear__":
            auth["username_hash"] = ""
    if "password" in p_auth:
        raw_pass = str(p_auth.get("password") or "")
        raw_pass_trim = raw_pass.strip()
        if raw_pass_trim not in ("", "__KEEP__", "********"):
            auth["password_hash"] = _auth_secret_hash(raw_pass)
        elif raw_pass_trim.lower() == "__clear__":
            auth["password_hash"] = ""

    if "access_list_enabled" in p_web:
        web["access_list_enabled"] = bool(p_web.get("access_list_enabled"))
    if "access_list_mode" in p_web:
        mode = str(p_web.get("access_list_mode") or "allow").strip().lower()
        web["access_list_mode"] = "deny" if mode in ("deny", "block", "black", "blacklist") else "allow"
    if "access_list" in p_web:
        web["access_list"] = _parse_whitelist_entries(p_web.get("access_list"))

    if p_model_update:
        if "enabled" in p_model_update:
            model_update["enabled"] = bool(p_model_update.get("enabled"))
        if "url" in p_model_update:
            url = str(p_model_update.get("url") or "").strip()
            if url and not (url.startswith("https://") or url.startswith("http://")):
                return None, "invalid model_update.url"
            model_update["url"] = url
        cfg["model_update"] = _normalize_model_update_cfg({"model_update": model_update})
    if p_app_update:
        if "enabled" in p_app_update:
            app_update["enabled"] = bool(p_app_update.get("enabled"))
        if "mirror" in p_app_update:
            app_update["mirror"] = str(p_app_update.get("mirror") or "github").strip()
        if "custom_mirror" in p_app_update:
            custom_mirror = str(p_app_update.get("custom_mirror") or "").strip()
            if custom_mirror and not (custom_mirror.startswith("https://") or custom_mirror.startswith("http://")):
                return None, "invalid app_update.custom_mirror"
            app_update["custom_mirror"] = custom_mirror
        if "force_update" in p_app_update:
            app_update["force_update"] = bool(p_app_update.get("force_update"))
        if "release_url" in p_app_update or "commit_url" in p_app_update:
            url = str(p_app_update.get("release_url") or p_app_update.get("commit_url") or "").strip()
            if url and not (url.startswith("https://") or url.startswith("http://")):
                return None, "invalid app_update.release_url"
            app_update["release_url"] = url or APP_UPDATE_RELEASE_URL_DEFAULT
        cfg["app_update"] = _normalize_app_update_cfg({"app_update": app_update})

    if p_metrics:
        if "enabled" in p_metrics:
            metrics["enabled"] = bool(p_metrics.get("enabled"))
        if "retention_days" in p_metrics:
            try:
                metrics["retention_days"] = max(1, min(90, int(p_metrics.get("retention_days") or HOST_METRICS_RETENTION_DAYS_DEFAULT)))
            except Exception:
                return None, "invalid metrics.retention_days"
        if "temperature_source" in p_metrics:
            metrics["temperature_source"] = str(p_metrics.get("temperature_source") or "auto")
        cfg["metrics"] = _normalize_metrics_cfg({"metrics": metrics})

    if p_network_bindings:
        cfg, bind_err = _network_bindings_apply_visual(cfg, p_network_bindings)
        if bind_err:
            return None, bind_err

    cfg, guard_err = _prepare_security_cfg_for_save(cfg)
    if guard_err:
        return None, guard_err

    return cfg, None

def _run_visual_settings_test(candidate_cfg: dict, previous_cfg: dict | None = None, notify_test: bool = False, keep_runtime: bool = False) -> tuple[bool, str, str]:
    prev_cfg = _deep_merge_dict(default_app_config(), previous_cfg if isinstance(previous_cfg, dict) else APP_CONFIG)
    notify_msg = ""
    r_ok, r_msg = reload_runtime_config(candidate_cfg)
    if not r_ok:
        try:
            reload_runtime_config(prev_cfg)
        except Exception:
            pass
        return False, str(r_msg or "runtime config reload failed"), notify_msg
    try:
        if notify_test:
            notify_norm = _normalize_notify_cfg(candidate_cfg)
            if bool(notify_norm.get("enabled")) and _notify_wecom_targets(notify_norm):
                n_ok, notify_msg = send_test_notification_from_config(candidate_cfg)
                if not n_ok:
                    raise RuntimeError(str(notify_msg or "notify test failed"))
            else:
                notify_msg = "skip"
        if not keep_runtime:
            rb_ok, rb_msg = reload_runtime_config(prev_cfg)
            if not rb_ok:
                return False, f"测试结束但运行时回滚失败: {rb_msg}", notify_msg
        return True, "test ok", notify_msg
    except Exception as e:
        try:
            reload_runtime_config(prev_cfg)
        except Exception as rb_e:
            return False, f"{e}; rollback failed: {rb_e}", notify_msg
        return False, str(e), notify_msg

def _save_visual_settings(body: dict | None, test_only: bool = False) -> dict:
    if not APP_CONFIG_PATH:
        return {"ok": False, "error": "config path missing"}
    prev_cfg = load_app_config(APP_CONFIG_PATH)
    candidate_cfg, build_err = _build_visual_settings_candidate(body)
    if build_err or not isinstance(candidate_cfg, dict):
        return {"ok": False, "error": str(build_err or "invalid candidate config")}

    if test_only:
        test_ok, test_msg, notify_msg = _run_visual_settings_test(
            candidate_cfg,
            previous_cfg=prev_cfg,
            notify_test=False,
            keep_runtime=False,
        )
        if not test_ok:
            return {"ok": False, "error": test_msg, "notify_test": notify_msg}
        return {
            "ok": True,
            "tested": True,
            "saved": False,
            "reload_msg": "draft tested and rolled back",
            "notify_test": notify_msg,
            "settings": _settings_view_payload().get("visual"),
        }
    notify_msg = "skip"

    ok, msg = save_app_config(APP_CONFIG_PATH, candidate_cfg)
    if not ok:
        try:
            reload_runtime_config(prev_cfg)
        except Exception:
            pass
        return {"ok": False, "error": f"save failed: {msg}"}

    cfg_loaded = load_app_config(APP_CONFIG_PATH)
    r_ok, r_msg = reload_runtime_config(cfg_loaded)
    if not r_ok:
        restore_ok, restore_msg = save_app_config(APP_CONFIG_PATH, prev_cfg)
        try:
            reload_runtime_config(prev_cfg)
        except Exception:
            pass
        if restore_ok:
            return {"ok": False, "error": f"reload failed: {r_msg}; rolled back to previous config"}
        return {"ok": False, "error": f"reload failed: {r_msg}; restore failed: {restore_msg}"}

    return {
        "ok": True,
        "saved_to": APP_CONFIG_PATH,
        "tested": False,
        "saved": True,
        "reloaded": bool(r_ok),
        "reload_msg": r_msg,
        "notify_test": notify_msg,
        "settings": _settings_view_payload().get("visual"),
    }

def _parser_explicit_dests(parser: argparse.ArgumentParser, argv: list[str]) -> set[str]:
    explicit: set[str] = set()
    opt_to_dest: dict[str, str] = {}
    for act in parser._actions:
        if not getattr(act, "option_strings", None):
            continue
        for opt in act.option_strings:
            opt_to_dest[opt] = act.dest
    for tok in argv:
        if not tok.startswith("-"):
            continue
        key = tok.split("=", 1)[0]
        dest = opt_to_dest.get(key)
        if dest and dest != "help":
            explicit.add(dest)
    return explicit

def _to_bool(v, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on", "t"):
        return True
    if s in ("0", "false", "no", "n", "off", "f", ""):
        return False
    return default

def apply_config_to_args(parser: argparse.ArgumentParser, args, cfg: dict) -> None:
    basic = cfg.get("basic") if isinstance(cfg, dict) else {}
    if not isinstance(basic, dict):
        return
    explicit = _parser_explicit_dests(parser, sys.argv[1:])
    for dest in (
        "iface", "channel", "hop", "hop_5g", "scan_wifi_fast",
        "dwell_2g", "dwell_5g", "settle", "dwell_on_hit", "hit_cap",
        "time", "min_gap", "rssi_delta",
        "lost_timeout",
        "change_on_rssi", "change_on_payload",
        "model_map", "history_file",
        "no_tui", "debug",
    ):
        if dest in explicit:
            continue
        if dest in basic:
            raw_v = basic.get(dest)
            cur_v = getattr(args, dest, None)
            try:
                if isinstance(cur_v, bool):
                    v = _to_bool(raw_v, cur_v)
                elif isinstance(cur_v, int) and not isinstance(cur_v, bool):
                    v = int(raw_v)
                elif isinstance(cur_v, float):
                    v = float(raw_v)
                elif raw_v is None:
                    v = None
                else:
                    v = str(raw_v)
                setattr(args, dest, v)
            except Exception:
                # Guard mode: ignore invalid config value and keep parser default.
                continue

def _normalize_notify_cfg(cfg: dict | None) -> dict:
    base = dict(NOTIFY_CFG)
    if isinstance(cfg, dict):
        notify = cfg.get("notify")
        if isinstance(notify, dict):
            for k in base.keys():
                if k in notify:
                    base[k] = notify.get(k)
    try:
        base["send_timeout_sec"] = max(2, int(base.get("send_timeout_sec") or 8))
    except Exception:
        base["send_timeout_sec"] = 8
    try:
        base["reonline_cooldown_sec"] = max(0, int(base.get("reonline_cooldown_sec") or NOTIFY_REONLINE_COOLDOWN_DEFAULT))
    except Exception:
        base["reonline_cooldown_sec"] = int(NOTIFY_REONLINE_COOLDOWN_DEFAULT)
    base["enabled"] = bool(base.get("enabled"))
    base["only_online"] = bool(base.get("only_online", True))
    base["notify_reonline"] = bool(base.get("notify_reonline", True))
    base["skip_mac_only"] = bool(base.get("skip_mac_only", True))
    legacy_key = str(base.get("wecom_webhook_key") or "").strip()
    hooks = _normalize_wecom_webhooks(base.get("wecom_webhooks"), legacy_key)
    base["wecom_webhooks"] = hooks
    base["wecom_webhook_key"] = str((hooks[0]["key"] if hooks else legacy_key) or "").strip()
    return base

def _normalize_web_cfg(cfg: dict | None) -> dict:
    base = dict(WEB_CFG)
    if isinstance(cfg, dict):
        web = cfg.get("web")
        if isinstance(web, dict):
            for k in base.keys():
                if k in web:
                    base[k] = web.get(k)
    base["dji_lookup_url"] = str(base.get("dji_lookup_url") or DJI_LOOKUP_URL_DEFAULT).strip()
    base["allow_restart"] = bool(base.get("allow_restart", True))
    base["last_restart_args"] = str(base.get("last_restart_args") or "")
    base["scan_type_rid"] = str(base.get("scan_type_rid") or "RID报送").strip() or "RID报送"
    base["scan_type_phone"] = str(base.get("scan_type_phone") or "手机快传").strip() or "手机快传"
    base["sn_source_rid"] = str(base.get("sn_source_rid") or "RID包").strip() or "RID包"
    base["sn_source_ssid"] = str(base.get("sn_source_ssid") or "SSID").strip() or "SSID"
    base["base_name"] = str(base.get("base_name") or "基站").strip() or "基站"
    tile_url = str(base.get("map_tile_url") or "").strip()
    if tile_url:
        parsed = urllib.parse.urlparse(tile_url)
        has_tokens = all(token in tile_url for token in ("{x}", "{y}", "{z}"))
        local_path = tile_url.startswith("/")
        remote_url = parsed.scheme in ("http", "https") and bool(parsed.netloc)
        if not has_tokens or not (local_path or remote_url):
            tile_url = ""
    base["map_tile_url"] = tile_url
    raw_subdomains = base.get("map_tile_subdomains")
    if isinstance(raw_subdomains, list):
        subdomain_parts = [str(x or "").strip() for x in raw_subdomains]
    else:
        subdomain_parts = re.split(r"[\s,]+", str(raw_subdomains or "").strip())
    subdomain_parts = [x for x in subdomain_parts if x and len(x) <= 32][:16]
    base["map_tile_subdomains"] = ",".join(subdomain_parts)
    base["map_tile_attribution"] = str(base.get("map_tile_attribution") or "").strip()[:240]
    try:
        lat_raw = base.get("base_lat")
        base["base_lat"] = None if lat_raw in (None, "") else float(lat_raw)
        if base["base_lat"] is not None and not (-90.0 <= base["base_lat"] <= 90.0):
            base["base_lat"] = None
    except Exception:
        base["base_lat"] = None
    try:
        lon_raw = base.get("base_lon")
        base["base_lon"] = None if lon_raw in (None, "") else float(lon_raw)
        if base["base_lon"] is not None and not (-180.0 <= base["base_lon"] <= 180.0):
            base["base_lon"] = None
    except Exception:
        base["base_lon"] = None
    try:
        base_zoom = int(base.get("base_zoom") if base.get("base_zoom") is not None else 13)
    except Exception:
        base_zoom = 13
    base["base_zoom"] = max(3, min(30, base_zoom))
    try:
        heading_ref = float(base.get("heading_ref_deg") if base.get("heading_ref_deg") is not None else 0.0)
    except Exception:
        heading_ref = 0.0
    heading_ref = heading_ref % 360.0
    if heading_ref < 0:
        heading_ref += 360.0
    base["heading_ref_deg"] = round(heading_ref, 2)
    try:
        idle_sec = int(base.get("map_auto_center_idle_sec") if base.get("map_auto_center_idle_sec") is not None else 20)
    except Exception:
        idle_sec = 20
    base["map_auto_center_idle_sec"] = max(5, min(600, idle_sec))
    try:
        tile_native_zoom = int(base.get("map_tile_max_native_zoom") if base.get("map_tile_max_native_zoom") is not None else 18)
    except Exception:
        tile_native_zoom = 18
    base["map_tile_max_native_zoom"] = max(1, min(30, tile_native_zoom))
    base["access_list_enabled"] = bool(base.get("access_list_enabled"))
    mode = str(base.get("access_list_mode") or "allow").strip().lower()
    base["access_list_mode"] = "deny" if mode in ("deny", "block", "black", "blacklist") else "allow"
    base["access_list"] = _parse_whitelist_entries(base.get("access_list"))
    zones = _normalize_alarm_zones(base.get("alarm_zones"), base.get("alarm_zone"))
    base["alarm_zones"] = zones
    base["alarm_zone"] = zones[0] if zones else _normalize_alarm_zone_item({}, idx=1)
    return base

def _normalize_ap_cfg(cfg: dict | None) -> dict:
    base = dict(AP_CFG)
    if isinstance(cfg, dict):
        ap = cfg.get("ap")
        if isinstance(ap, dict):
            for k in base.keys():
                if k in ap:
                    base[k] = ap.get(k)
    try:
        base["list_max"] = max(10, min(500, int(base.get("list_max") or AP_LIST_MAX_DEFAULT)))
    except Exception:
        base["list_max"] = AP_LIST_MAX_DEFAULT
    base["vendor_auto_download"] = bool(base.get("vendor_auto_download", True))
    db_path = str(base.get("vendor_db_file") or os.path.join(os.getcwd(), OUI_DB_DEFAULT)).strip()
    base["vendor_db_file"] = os.path.abspath(db_path) if db_path else None
    return base

def _normalize_model_update_cfg(cfg: dict | None) -> dict:
    base = dict(MODEL_UPDATE_CFG)
    if isinstance(cfg, dict):
        raw = cfg.get("model_update")
        if isinstance(raw, dict):
            for k in base.keys():
                if k in raw:
                    base[k] = raw.get(k)
    base["enabled"] = bool(base.get("enabled", True))
    url = str(base.get("url") or "").strip()
    if not url:
        url = RID_MODELS_UPDATE_URL_DEFAULT
    elif not (url.startswith("https://") or url.startswith("http://")):
        url = RID_MODELS_UPDATE_URL_DEFAULT
    base["url"] = url
    return base

def _normalize_config_update_cfg(cfg: dict | None) -> dict:
    base = dict(CONFIG_UPDATE_CFG)
    if isinstance(cfg, dict):
        raw = cfg.get("config_update")
        if isinstance(raw, dict):
            for k in base.keys():
                if k in raw:
                    base[k] = raw.get(k)
    base["enabled"] = bool(base.get("enabled", False))
    url = str(base.get("url") or "").strip()
    if url and not (url.startswith("https://") or url.startswith("http://")):
        url = ""
    base["url"] = url
    return base

def _normalize_app_update_cfg(cfg: dict | None) -> dict:
    base = dict(APP_UPDATE_CFG)
    if isinstance(cfg, dict):
        raw = cfg.get("app_update")
        if isinstance(raw, dict):
            for k in base.keys():
                if k in raw:
                    base[k] = raw.get(k)
    base["enabled"] = bool(base.get("enabled", True))
    url = str(base.get("release_url") or "").strip()
    if (not url) and isinstance(cfg, dict):
        raw = cfg.get("app_update")
        if isinstance(raw, dict):
            url = str(raw.get("commit_url") or "").strip()
    if not url:
        url = APP_UPDATE_RELEASE_URL_DEFAULT
    if not (url.startswith("https://") or url.startswith("http://")):
        url = APP_UPDATE_RELEASE_URL_DEFAULT
    base["release_url"] = url
    mirror = str(base.get("mirror") or "github").strip().lower()
    valid_mirrors = {str(item.get("key") or "") for item in APP_UPDATE_MIRROR_OPTIONS}
    if mirror not in valid_mirrors:
        mirror = "github"
    base["mirror"] = mirror
    custom = str(base.get("custom_mirror") or "").strip()
    if custom and not (custom.startswith("https://") or custom.startswith("http://")):
        custom = ""
    base["custom_mirror"] = custom
    base["force_update"] = bool(base.get("force_update"))
    return base

def _normalize_metrics_cfg(cfg: dict | None) -> dict:
    base = dict(METRICS_CFG)
    if isinstance(cfg, dict):
        raw = cfg.get("metrics")
        if isinstance(raw, dict):
            for k in base.keys():
                if k in raw:
                    base[k] = raw.get(k)
    base["enabled"] = bool(base.get("enabled", False))
    try:
        base["retention_days"] = max(1, min(90, int(base.get("retention_days") or HOST_METRICS_RETENTION_DAYS_DEFAULT)))
    except Exception:
        base["retention_days"] = HOST_METRICS_RETENTION_DAYS_DEFAULT
    raw_temp_source = str(base.get("temperature_source") or "auto").strip().lower().replace("-", "_")
    temp_alias = {
        "": "auto",
        "auto": "auto",
        "vcgencmd": "vcgencmd",
        "vcgen": "vcgencmd",
        "vcgencmd_pmic": "vcgencmd_pmic",
        "pmic": "vcgencmd_pmic",
        "thermal": "thermal_zone",
        "thermal_zone": "thermal_zone",
        "thermalzone": "thermal_zone",
        "sysfs": "thermal_zone",
        "hwmon": "hwmon",
        "w1": "w1",
        "ds18b20": "w1",
        "onewire": "w1",
        "one_wire": "w1",
        "off": "off",
        "none": "off",
        "disabled": "off",
    }
    base["temperature_source"] = temp_alias.get(raw_temp_source, "auto")
    return base
