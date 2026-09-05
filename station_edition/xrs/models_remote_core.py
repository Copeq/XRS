"""models remote core (extracted from hardware_core.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
"""

def _model_from_sn(sn: str) -> str:
    if not sn or sn.startswith("MAC:"):
        return "N/A"
    sn_key = re.sub(r"[^0-9A-Za-z]+", "", str(sn or "")).upper()
    if not sn_key:
        return "N/A"
    items = sorted(MODEL_MAP.items(), key=lambda kv: len(str(kv[0] or "")), reverse=True)
    for pref, model in items:
        pref_key = re.sub(r"[^0-9A-Za-z]+", "", str(pref or "")).upper()
        if pref_key and sn_key.startswith(pref_key):
            return model
    return "N/A"

def _resolve_model_name(sn: str, scan_type: str | None = None, current_model: str | None = None) -> str:
    if _scan_type_key(scan_type) == "phone":
        return "WiFi快传"
    mapped = _model_from_sn(sn)
    if mapped != "N/A":
        return mapped
    cur = str(current_model or "").strip()
    return cur if (cur and cur.upper() != "N/A") else "N/A"

def _refresh_models_locked(*, only_na: bool = False) -> tuple[int, int]:
    """Refresh model names from SN mapping for both history/state tables.
    Must be called with `state_lock` held.
    Returns (history_changed, state_changed).
    """
    history_changed = 0
    state_changed = 0
    for sn, h in history_table.items():
        if not isinstance(h, dict):
            continue
        old = str(h.get("model") or "").strip()
        if only_na and old and old.upper() != "N/A":
            continue
        sn_key = str(h.get("sn") or sn or "")
        new = _resolve_model_name(sn_key, h.get("scan_type"), old)
        old_norm = old if old else "N/A"
        if new != old_norm:
            h["model"] = new
            history_changed += 1
    for sn, e in state_table.items():
        if not isinstance(e, dict):
            continue
        old = str(e.get("model") or "").strip()
        if only_na and old and old.upper() != "N/A":
            continue
        sn_key = str(e.get("sn") or sn or "")
        new = _resolve_model_name(sn_key, e.get("scan_type"), old)
        old_norm = old if old else "N/A"
        if new != old_norm:
            e["model"] = new
            state_changed += 1
    return history_changed, state_changed

def load_model_map(path: str) -> None:
    global MODEL_MAP
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, dict):
            MODEL_MAP = {str(k): str(v) for k, v in obj.items()}
            _log(f"[INFO] model map loaded: {path} ({len(MODEL_MAP)} entries)")
            with state_lock:
                h_changed, s_changed = _refresh_models_locked(only_na=False)
                if h_changed:
                    _history_mark_dirty()
            if h_changed or s_changed:
                _log(f"[INFO] model remap applied: history={h_changed}, live={s_changed}")
        else:
            _log(f"[WARN] model map format invalid: {path}")
    except FileNotFoundError:
        _log(f"[WARN] model map not found: {path}")
    except Exception as e:
        _log(f"[WARN] model map load failed: {e}")

def ensure_model_map_file(path: str) -> None:
    if not path or os.path.exists(path):
        return
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    errors: list[str] = []
    try:
        data, _ = _http_read_with_fallback(
            RID_MODELS_UPDATE_URL_DEFAULT,
            headers={"User-Agent": APP_HTTP_USER_AGENT + " (+model-map bootstrap)"},
            timeout=12,
            max_bytes=2 * 1024 * 1024,
        )
        obj = json.loads(data.decode("utf-8", errors="replace"))
        next_map = _validate_model_map_payload(obj)
        _write_json_file(path, next_map)
        _log(f"[INFO] model map downloaded: {path}")
        return
    except Exception as e:
        errors.append("remote=" + str(e))
    try:
        resource_path = _runtime_resource_path(MODEL_MAP_FILE_DEFAULT)
        with open(resource_path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        next_map = _validate_model_map_payload(obj)
        _write_json_file(path, next_map)
        _log(f"[INFO] model map restored from embedded resource: {path}")
        return
    except Exception as e:
        errors.append("embedded=" + str(e))
    _log("[WARN] model map bootstrap failed: " + "; ".join(errors))

def _model_map_target_path() -> str:
    try:
        basic = APP_CONFIG.get("basic") if isinstance(APP_CONFIG, dict) else {}
        if isinstance(basic, dict):
            raw = str(basic.get("model_map") or "").strip()
            if raw:
                return os.path.abspath(raw)
    except Exception:
        pass
    return os.path.abspath(os.path.join(os.getcwd(), MODEL_MAP_FILE_DEFAULT))

def _model_map_items_from_dict(obj: dict | None) -> list[dict]:
    src = obj if isinstance(obj, dict) else {}
    return [
        {"prefix": str(k), "model": str(v)}
        for k, v in sorted(src.items(), key=lambda kv: str(kv[0]).upper())
    ]

def _read_model_map_file(path: str) -> dict[str, str]:
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    return _validate_model_map_payload(obj)

def _model_map_editor_payload(warning: str = "") -> dict:
    target = _model_map_target_path()
    data: dict[str, str] = {}
    warn = warning
    try:
        data = _read_model_map_file(target)
    except FileNotFoundError:
        data = dict(MODEL_MAP)
        warn = warn or "识别库文件不存在，保存后会创建。"
    except Exception as e:
        data = dict(MODEL_MAP)
        warn = warn or f"识别库文件读取失败，当前显示内存中的识别库：{e}"
    return {
        "ok": True,
        "path": target,
        "count": len(data),
        "items": _model_map_items_from_dict(data),
        "state": _model_update_status_payload(),
        "warning": warn,
    }

def _model_update_status_payload() -> dict:
    with model_update_lock:
        state = dict(MODEL_UPDATE_STATE)
    state["enabled"] = bool(MODEL_UPDATE_CFG.get("enabled", True))
    state["url"] = str(MODEL_UPDATE_CFG.get("url") or RID_MODELS_UPDATE_URL_DEFAULT)
    state["target"] = _model_map_target_path()
    state["interval_sec"] = int(MODEL_UPDATE_CHECK_INTERVAL_SEC)
    state["loaded_count"] = int(len(MODEL_MAP))
    return state

def _validate_model_map_payload(obj) -> dict[str, str]:
    if not isinstance(obj, dict):
        raise ValueError("识别库格式错误：根节点必须是对象")
    out: dict[str, str] = {}
    for k, v in obj.items():
        key = re.sub(r"[^0-9A-Za-z]+", "", str(k or "")).upper()
        val = str(v or "").strip()
        if not key or not val:
            continue
        if not re.fullmatch(r"[0-9A-Z]{4,32}", key):
            continue
        out[key] = val
    if not out:
        raise ValueError("识别库为空或没有有效前缀")
    return out

def _model_map_from_editor_items(items) -> dict[str, str]:
    if isinstance(items, dict):
        return _validate_model_map_payload(items)
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    raw: dict[str, str] = {}
    for row in items:
        if not isinstance(row, dict):
            continue
        pref = re.sub(r"[^0-9A-Za-z]+", "", str(row.get("prefix") or "")).upper()
        model = str(row.get("model") or "").strip()
        if not pref and not model:
            continue
        raw[pref] = model
    return _validate_model_map_payload(raw)

def _write_model_map_file(next_map: dict[str, str], tag: str = "models") -> dict:
    target = _model_map_target_path()
    with model_map_file_lock:
        running = False
        with model_update_lock:
            running = bool(MODEL_UPDATE_STATE.get("running"))
        if running:
            return {"ok": False, "error": "识别库在线更新正在运行，请稍后再保存。", "state": _model_update_status_payload()}
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        b_ok, backup_path = create_config_backup(target, tag=tag)
        if not b_ok:
            return {"ok": False, "error": "backup failed: " + backup_path, "state": _model_update_status_payload()}
        tmp_path = target + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(next_map, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, target)
        load_model_map(target)
    try:
        save_history_store(force=True)
    except Exception:
        pass
    msg = f"识别库已保存：{len(next_map)} 条"
    _op_log("model-map-save", f"count={len(next_map)} target={target}", ok=True)
    _notification_add(msg, "ok", "server")
    payload = _model_map_editor_payload()
    payload.update({"ok": True, "message": msg, "backup_path": backup_path})
    return payload

def save_model_map_entries(items) -> dict:
    next_map = _model_map_from_editor_items(items)
    return _write_model_map_file(next_map, tag="models")

def upsert_model_map_entry(prefix: str = "", model: str = "", sn: str = "") -> dict:
    clean_prefix = re.sub(r"[^0-9A-Za-z]+", "", str(prefix or "")).upper()
    clean_sn = re.sub(r"[^0-9A-Za-z]+", "", str(sn or "")).upper()
    if not clean_prefix and clean_sn and not str(sn or "").upper().startswith("MAC:"):
        clean_prefix = clean_sn[:8]
    clean_model = str(model or "").strip()
    single = _validate_model_map_payload({clean_prefix: clean_model})
    target = _model_map_target_path()
    try:
        current = _read_model_map_file(target)
    except FileNotFoundError:
        current = dict(MODEL_MAP)
    current.update(single)
    return _write_model_map_file(_validate_model_map_payload(current), tag="models_upsert")

def update_model_map_from_url(manual: bool = False, url_override: str | None = None) -> dict:
    url = str(url_override or MODEL_UPDATE_CFG.get("url") or RID_MODELS_UPDATE_URL_DEFAULT).strip()
    if not (url.startswith("https://") or url.startswith("http://")):
        return {"ok": False, "error": "识别库更新地址必须以 http:// 或 https:// 开头", "state": _model_update_status_payload()}
    target = _model_map_target_path()
    busy = False
    with model_update_lock:
        if MODEL_UPDATE_STATE.get("running"):
            busy = True
        else:
            MODEL_UPDATE_STATE["running"] = True
            MODEL_UPDATE_STATE["last_check_ts"] = time.time()
            MODEL_UPDATE_STATE["last_error"] = ""
            MODEL_UPDATE_STATE["last_message"] = "正在检查识别库"
    if busy:
        return {"ok": False, "error": "识别库更新正在运行", "state": _model_update_status_payload()}
    try:
        data, _ = _http_read_with_fallback(
            url,
            headers={"User-Agent": APP_HTTP_USER_AGENT + " (+model-map update)"},
            timeout=20,
            max_bytes=2 * 1024 * 1024,
        )
        if not data:
            raise ValueError("远端返回为空")
        obj = json.loads(data.decode("utf-8", errors="replace"))
        next_map = _validate_model_map_payload(obj)
        with model_map_file_lock:
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            if os.path.exists(target):
                try:
                    shutil.copy2(target, target + ".bak")
                except Exception:
                    pass
            tmp_path = target + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(next_map, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp_path, target)
            load_model_map(target)
        try:
            save_history_store(force=True)
        except Exception:
            pass
        msg = f"识别库已更新：{len(next_map)} 条"
        with model_update_lock:
            MODEL_UPDATE_STATE["running"] = False
            MODEL_UPDATE_STATE["last_success_ts"] = time.time()
            MODEL_UPDATE_STATE["last_error"] = ""
            MODEL_UPDATE_STATE["last_message"] = msg
            MODEL_UPDATE_STATE["last_count"] = len(next_map)
        _op_log("model-update", f"manual={manual} count={len(next_map)} target={target}", ok=True)
        _notification_add(msg, "ok", "server")
        return {"ok": True, "message": msg, "count": len(next_map), "target": target, "state": _model_update_status_payload()}
    except Exception as e:
        msg = str(e)
        with model_update_lock:
            MODEL_UPDATE_STATE["running"] = False
            MODEL_UPDATE_STATE["last_error"] = msg
            MODEL_UPDATE_STATE["last_message"] = "识别库更新失败"
        _op_log("model-update", f"manual={manual} error={msg}", ok=False)
        if manual:
            _notification_add("识别库更新失败：" + msg, "warn", "server")
        return {"ok": False, "error": msg, "target": target, "state": _model_update_status_payload()}

def model_update_loop() -> None:
    time.sleep(10.0)
    while True:
        try:
            if bool(MODEL_UPDATE_CFG.get("enabled", True)):
                with model_update_lock:
                    last = float(MODEL_UPDATE_STATE.get("last_check_ts") or 0.0)
                    running = bool(MODEL_UPDATE_STATE.get("running"))
                if (not running) and (time.time() - last >= MODEL_UPDATE_CHECK_INTERVAL_SEC):
                    update_model_map_from_url(manual=False)
        except Exception as e:
            _log(f"[WARN] model update loop failed: {e}")
        time.sleep(300.0)

# -----------------------------------------------------------------------------
# Remote config update
# -----------------------------------------------------------------------------
def _config_update_status_payload() -> dict:
    with config_update_lock:
        state = dict(CONFIG_UPDATE_STATE)
    state["enabled"] = bool(CONFIG_UPDATE_CFG.get("enabled", False))
    state["url"] = str(CONFIG_UPDATE_CFG.get("url") or "")
    state["target"] = APP_CONFIG_PATH or ""
    return state

def update_config_from_url(manual: bool = False, url_override: str | None = None) -> dict:
    url = str(url_override or CONFIG_UPDATE_CFG.get("url") or "").strip()
    if not url:
        return {"ok": False, "error": "config update url missing", "state": _config_update_status_payload()}
    if not (url.startswith("https://") or url.startswith("http://")):
        return {"ok": False, "error": "config update url must start with http:// or https://", "state": _config_update_status_payload()}
    if not APP_CONFIG_PATH:
        return {"ok": False, "error": "config path missing", "state": _config_update_status_payload()}
    busy = False
    with config_update_lock:
        if CONFIG_UPDATE_STATE.get("running"):
            busy = True
        else:
            CONFIG_UPDATE_STATE["running"] = True
            CONFIG_UPDATE_STATE["last_check_ts"] = time.time()
            CONFIG_UPDATE_STATE["last_error"] = ""
            CONFIG_UPDATE_STATE["last_message"] = "downloading config"
    if busy:
        return {"ok": False, "error": "config update already running", "state": _config_update_status_payload()}
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": APP_HTTP_USER_AGENT + " (+config update)"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read(2 * 1024 * 1024)
        if not data:
            raise ValueError("empty response")
        parsed = json.loads(data.decode("utf-8", errors="replace"))
        if not isinstance(parsed, dict):
            raise ValueError("remote config root must be object")
        # Remote config updates follow the same guard rails as manual saves:
        # merge defaults, validate security, backup, save, reload, rollback.
        candidate = _deep_merge_dict(default_app_config(), parsed)
        candidate, guard_err = _prepare_security_cfg_for_save(candidate)
        if guard_err:
            raise ValueError(guard_err)
        b_ok, backup_path = create_config_backup(APP_CONFIG_PATH, tag="config_update")
        if not b_ok:
            raise ValueError("backup failed: " + backup_path)
        ok, msg = save_app_config(APP_CONFIG_PATH, candidate)
        if not ok:
            raise ValueError("save failed: " + msg)
        cfg_loaded = load_app_config(APP_CONFIG_PATH)
        r_ok, r_msg = reload_runtime_config(cfg_loaded)
        if not r_ok:
            restore_config_backup(APP_CONFIG_PATH, backup_path)
            raise ValueError("reload failed: " + r_msg)
        msg = f"config updated from url; keys={len(candidate.keys())}"
        with config_update_lock:
            CONFIG_UPDATE_STATE["running"] = False
            CONFIG_UPDATE_STATE["last_success_ts"] = time.time()
            CONFIG_UPDATE_STATE["last_error"] = ""
            CONFIG_UPDATE_STATE["last_message"] = msg
            CONFIG_UPDATE_STATE["last_count"] = len(candidate.keys())
        _op_log("config-update", f"manual={manual} target={APP_CONFIG_PATH}", ok=True)
        return {"ok": True, "message": msg, "saved_to": APP_CONFIG_PATH, "state": _config_update_status_payload()}
    except Exception as e:
        msg = str(e)
        with config_update_lock:
            CONFIG_UPDATE_STATE["running"] = False
            CONFIG_UPDATE_STATE["last_error"] = msg
            CONFIG_UPDATE_STATE["last_message"] = "config update failed"
        _op_log("config-update", f"manual={manual} error={msg}", ok=False)
        return {"ok": False, "error": msg, "state": _config_update_status_payload()}

def config_update_loop() -> None:
    time.sleep(20.0)
    while True:
        try:
            if bool(CONFIG_UPDATE_CFG.get("enabled", False)):
                with config_update_lock:
                    last = float(CONFIG_UPDATE_STATE.get("last_check_ts") or 0.0)
                    running = bool(CONFIG_UPDATE_STATE.get("running"))
                if (not running) and (time.time() - last >= 24 * 3600):
                    update_config_from_url(manual=False)
        except Exception as e:
            _log(f"[WARN] config update loop failed: {e}")
        time.sleep(300.0)

def start_config_update_worker() -> None:
    global config_update_worker_started
    if config_update_worker_started:
        return
    config_update_worker_started = True
    Thread(target=config_update_loop, daemon=True).start()

def start_model_update_worker() -> None:
    global model_update_worker_started
    if model_update_worker_started:
        return
    model_update_worker_started = True
    Thread(target=model_update_loop, daemon=True).start()

# -----------------------------------------------------------------------------
# Formatting helpers
# -----------------------------------------------------------------------------
