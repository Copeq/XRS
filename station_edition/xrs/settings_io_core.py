"""settings io core helpers (extracted from common_core.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
Shared globals/constants and sibling chunk functions resolve at call time in the
shared namespace, so exec order stays after common_core.py.
"""

def import_details_payload(payload) -> tuple[int, int, int]:
    """Import detail records payload. Returns (added, updated, skipped)."""
    items = None
    if isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            items = payload.get("items")
        elif isinstance(payload.get("drones"), list):
            items = payload.get("drones")
    elif isinstance(payload, list):
        items = payload
    if not isinstance(items, list):
        return 0, 0, 0
    added = 0
    updated = 0
    skipped = 0
    with state_lock:
        for raw in items:
            if not isinstance(raw, dict):
                skipped += 1
                continue
            if "src_mac" not in raw and "mac" in raw:
                raw = dict(raw)
                raw["src_mac"] = raw.get("mac")
            if "speed" not in raw and "spd" in raw:
                raw = dict(raw)
                raw["speed"] = raw.get("spd")
            if "vspeed" not in raw and "vspd" in raw:
                raw = dict(raw)
                raw["vspeed"] = raw.get("vspd")
            if "move_dir" not in raw and "dir" in raw:
                raw = dict(raw)
                raw["move_dir"] = raw.get("dir")
            ok, is_new = _history_apply_raw_locked(raw)
            if not ok:
                skipped += 1
            elif is_new:
                added += 1
            else:
                updated += 1
        if added or updated:
            _history_mark_dirty()
    return added, updated, skipped

def _settings_export_payload() -> dict:
    cfg = load_app_config(APP_CONFIG_PATH) if APP_CONFIG_PATH else default_app_config()
    return {
        "ok": True,
        "kind": "settings",
        "version": 1,
        "exported_at": time.time(),
        "config_path": APP_CONFIG_PATH or "",
        "settings": cfg,
    }

def _settings_import_candidate(payload) -> tuple[dict | None, str | None]:
    src = payload
    if isinstance(src, dict):
        if isinstance(src.get("settings"), dict):
            src = src.get("settings")
        elif isinstance(src.get("config"), dict):
            src = src.get("config")
        elif isinstance(src.get("payload"), dict):
            src = src.get("payload")
    if not isinstance(src, dict):
        return None, "payload must be object"
    if not any(k in src for k in ("basic", "notify", "web", "ap", "auth", "api", "model_update", "config_update", "app_update", "metrics")):
        return None, "invalid settings payload"
    candidate = _deep_merge_dict(default_app_config(), src)
    candidate, guard_err = _prepare_security_cfg_for_save(candidate)
    if guard_err:
        return None, guard_err
    return candidate, None

def _import_settings_payload(payload) -> dict:
    if not APP_CONFIG_PATH:
        return {"ok": False, "error": "config path missing"}
    prev_cfg = load_app_config(APP_CONFIG_PATH)
    candidate_cfg, err = _settings_import_candidate(payload)
    if err or not isinstance(candidate_cfg, dict):
        return {"ok": False, "error": str(err or "invalid settings payload")}
    b_ok, backup_path = create_config_backup(APP_CONFIG_PATH, tag="settings_import")
    if not b_ok:
        return {"ok": False, "error": f"backup failed: {backup_path}"}
    ok, msg = save_app_config(APP_CONFIG_PATH, candidate_cfg)
    if not ok:
        try:
            restore_config_backup(APP_CONFIG_PATH, backup_path)
            reload_runtime_config(prev_cfg)
        except Exception:
            pass
        return {"ok": False, "error": f"save failed: {msg}"}
    cfg_loaded = load_app_config(APP_CONFIG_PATH)
    r_ok, r_msg = reload_runtime_config(cfg_loaded)
    if not r_ok:
        restore_ok, restore_msg = restore_config_backup(APP_CONFIG_PATH, backup_path)
        try:
            reload_runtime_config(prev_cfg)
        except Exception:
            pass
        if restore_ok:
            return {"ok": False, "error": f"reload failed: {r_msg}; rolled back from backup", "backup_path": backup_path}
        return {"ok": False, "error": f"reload failed: {r_msg}; restore failed: {restore_msg}", "backup_path": backup_path}
    return {
        "ok": True,
        "saved_to": APP_CONFIG_PATH,
        "backup_path": backup_path,
        "reload_msg": r_msg,
        "settings": _settings_view_payload().get("visual"),
    }

def _scan_data_payload_unwrap(payload):
    src = payload
    if isinstance(src, dict):
        if isinstance(src.get("scan_data"), dict):
            src = src.get("scan_data")
        elif isinstance(src.get("payload"), (dict, list)):
            src = src.get("payload")
    return src

def _scan_data_payload_valid(payload) -> bool:
    src = _scan_data_payload_unwrap(payload)
    if isinstance(src, list):
        return True
    if isinstance(src, dict):
        return isinstance(src.get("items"), list) or isinstance(src.get("drones"), list)
    return False

def _scan_data_file_info(path: str | None = None) -> dict:
    raw_path = str(path or HISTORY_STORE_PATH or "").strip()
    info = {"path": raw_path, "exists": False, "size": 0, "mtime": None}
    if not raw_path:
        return info
    try:
        abs_path = os.path.abspath(raw_path)
        info["path"] = abs_path
        st = os.stat(abs_path)
        info.update({"exists": True, "size": int(st.st_size), "mtime": float(st.st_mtime)})
    except FileNotFoundError:
        info["path"] = os.path.abspath(raw_path)
    except Exception as exc:
        info["error"] = str(exc)
    return info

def _scan_data_export_payload() -> dict:
    with state_lock:
        items = _history_disk_items_locked(include_all_raw_packets=True)
    file_info = _scan_data_file_info()
    return {
        "ok": True,
        "kind": "scan_data",
        "version": 1,
        "store_version": HISTORY_STORAGE_EXPORT_VERSION,
        "exported_at": time.time(),
        "data_file": file_info.get("path") or HISTORY_STORE_PATH or "",
        "data_file_info": file_info,
        "count": len(items),
        "items": items,
    }

def _import_scan_data_payload(payload, *, mode: str = "merge") -> dict:
    src = _scan_data_payload_unwrap(payload)
    if not _scan_data_payload_valid(src):
        return {"ok": False, "error": "invalid payload: expect items[]/drones[] or list"}
    import_mode = "replace" if str(mode or "").strip().lower() in ("replace", "overwrite", "reset") else "merge"
    replaced = 0
    if import_mode == "replace":
        replaced, _removed = clear_history_store(delete_file=False)
    added, updated, skipped = import_details_payload(src)
    save_history_store(force=True)
    with state_lock:
        total_count = len(history_table)
    return {
        "ok": True,
        "mode": import_mode,
        "replaced": int(replaced),
        "added": int(added),
        "updated": int(updated),
        "skipped": int(skipped),
        "count": int(total_count),
        "data_file": HISTORY_STORE_PATH or "",
        "data_file_info": _scan_data_file_info(),
    }
