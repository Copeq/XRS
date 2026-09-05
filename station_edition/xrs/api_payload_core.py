"""API token management and page-facing payload builders (settings/logs/diagnostics/OOBE).

Extracted from auth_core.py during backend module split. Loaded into the assembled
runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
"""

def _api_token_enabled() -> bool:
    if _portable_edition_enabled():
        return False
    return bool(API_CFG.get("enabled")) and bool(_auth_enabled()) and _auth_hashes_present(AUTH_CFG) and _api_tokens_have_secret(API_CFG)

def _api_token_check_value(token: str | None) -> dict | None:
    if not _api_token_enabled():
        return None
    raw = str(token or "").strip()
    if not raw:
        return None
    for item in _normalize_api_tokens(API_CFG.get("tokens"), API_CFG.get("token") or "", API_CFG.get("token_hash") or ""):
        token_hash = str(item.get("token_hash") or "").strip()
        if token_hash and _verify_auth_secret(raw, token_hash) and bool(_sso_link_state(item).get("active")):
            return dict(item)
    return None

def _api_token_from_request(headers, query: dict | None = None) -> str:
    authz = str(headers.get("Authorization") or "").strip()
    if authz.lower().startswith("bearer "):
        return authz[7:].strip()
    token = str(headers.get("X-API-Token") or "").strip()
    if token:
        return token
    if isinstance(query, dict):
        try:
            arr = query.get("token") or [""]
            return str(arr[0] or "").strip()
        except Exception:
            return ""
    return ""

def _api_mark_token_used(token_id: str | None) -> bool:
    raw_id = str(token_id or "").strip()
    if not raw_id:
        return False
    changed = False
    now_wall = time.time()
    def _mark(tokens):
        nonlocal changed
        out = []
        for item in tokens:
            row = dict(item or {})
            if str(row.get("id") or "") == raw_id:
                row["used_count"] = int(row.get("used_count") or 0) + 1
                row["used_ts"] = now_wall
                changed = True
            out.append(row)
        return out
    ok, _msg, _tokens = _api_mutate_tokens(_mark, tag="api_token_use")
    return bool(ok and changed)

def _api_mutate_tokens(mutator, *, tag: str = "api_token") -> tuple[bool, str, list[dict]]:
    if not APP_CONFIG_PATH:
        return False, "config path missing", _api_tokens_public()
    try:
        with api_token_lock:
            cfg = load_app_config(APP_CONFIG_PATH)
            api = cfg.setdefault("api", {})
            if not isinstance(api, dict):
                api = {}
                cfg["api"] = api
            tokens = _normalize_api_tokens(api.get("tokens"), api.get("token") or "", api.get("token_hash") or "")
            api["tokens"] = _normalize_api_tokens(mutator(list(tokens)))
            first = api["tokens"][0] if api["tokens"] else {}
            api["token"] = str(first.get("token") or "")
            api["token_hash"] = str(first.get("token_hash") or "")
            cfg, guard_err = _prepare_security_cfg_for_save(cfg)
            if guard_err:
                return False, guard_err, _api_tokens_public()
            b_ok, backup_path = create_config_backup(APP_CONFIG_PATH, tag=tag)
            if not b_ok:
                return False, f"backup failed: {backup_path}", _api_tokens_public()
            ok, msg = save_app_config(APP_CONFIG_PATH, cfg)
            if not ok:
                return False, msg, _api_tokens_public()
            cfg_loaded = load_app_config(APP_CONFIG_PATH)
            r_ok, r_msg = reload_runtime_config(cfg_loaded)
            if not r_ok:
                return False, f"reload failed: {r_msg}", _api_tokens_public()
            api_loaded = cfg_loaded.get("api") if isinstance(cfg_loaded, dict) else None
            return True, "ok", _api_tokens_public(api_loaded if isinstance(api_loaded, dict) else None)
    except Exception as e:
        return False, str(e), _api_tokens_public()

def _build_api_token_create_payload(body: dict | None, *, headers=None, client_ip: str | None = None) -> tuple[dict, int]:
    if not _auth_enabled() or (not _auth_hashes_present(AUTH_CFG)):
        return {"ok": False, "error": "网页登录未启用"}, 400
    src = body if isinstance(body, dict) else {}
    subject = str(src.get("username") or "-")
    reauth_ok = _auth_check_userpass(str(src.get("username") or ""), str(src.get("password") or ""))
    if not reauth_ok and headers is not None and headers.get("Authorization"):
        reauth_ok = _auth_check_basic_header(headers.get("Authorization"))
    if not reauth_ok:
        _op_log("api-token-create", "", actor=subject, ip=str(client_ip or "-"), ok=False)
        return {"ok": False, "error": "用户名或密码错误"}, 401
    now_wall = time.time()
    expires_at, expiry_err = _api_token_expiry_from_row(src, now_wall=now_wall, fallback=0.0)
    if expiry_err:
        return {"ok": False, "error": expiry_err}, 400
    name = str(src.get("name") or "").strip()
    if not name:
        name = "API Token " + time.strftime("%Y-%m-%d %H:%M:%S")
    token_plain = secrets.token_urlsafe(32)
    token_hash = _auth_secret_hash(token_plain)
    token_id = _api_token_id_from_hash(token_hash)
    item = {
        "id": token_id,
        "name": name[:80],
        "token": "",
        "token_hash": token_hash,
        "enabled": True,
        "created_ts": now_wall,
        "expires_at": expires_at,
        "single_use": _to_bool(src.get("single_use"), False),
        "used_ts": 0.0,
        "used_count": 0,
    }
    def _add_token(tokens):
        tokens.append(item)
        return tokens[-64:]
    ok, msg, tokens = _api_mutate_tokens(_add_token, tag="api_token_create")
    if not ok:
        return {"ok": False, "error": msg, "tokens": tokens}, 500
    _op_log("api-token-create", "name=" + name[:40], actor=subject, ip=str(client_ip or "-"), ok=True)
    return {
        "ok": True,
        "id": token_id,
        "name": name,
        "token": token_plain,
        "expires_at": expires_at,
        "expires_in_sec": None if expires_at <= 0 else int(max(0.0, expires_at - now_wall)),
        "single_use": bool(item.get("single_use")),
        "tokens": tokens,
    }, 200

def _api_token_docs_payload() -> dict:
    return {
        "ok": True,
        "api": _api_meta(),
        "auth": {
            "type": "token",
            "usage": [
                "Header: X-API-Token: <token>",
                "or Authorization: Bearer <token>",
                "Query fallback: ?token=<token> (not recommended for browser history/privacy)",
            ],
            "disabled_behavior": "When public API is disabled, /api/docs, /api/health and /api/v1/* only work from the built-in web pages via page session requests.",
            "token_policy": "API tokens support multiple entries, per-token expiry, single-use mode, and retained expired records.",
            "create_sso_link": {
                "method": "POST",
                "path": "/api/v1/auth/sso-links/create",
                "body": {
                    "name": "optional display name",
                    "next": "/",
                    "ttl_sec": 86400,
                    "expires": "never",
                    "single_use": False,
                },
                "expiry_fields": "Use one of ttl_sec, ttl_min, expires_at, or expires=never.",
            },
        },
        "endpoints": _api_endpoint_index(),
    }

def _api_v1_home_payload() -> dict:
    meta = _api_meta()
    return {
        "ok": True,
        "api": meta,
        "auth": {
            "token_api": {
                "enabled": bool(_api_token_enabled()),
                "headers": ["X-API-Token", "Authorization: Bearer <token>"],
                "query_fallback": "token",
                "supports_multiple_tokens": True,
                "supports_single_use": True,
                "supports_never_expires": True,
                "expired_tokens_auto_delete": False,
                "token_count": len(_api_tokens_public(API_CFG)),
                "whitelist_enabled": bool(API_CFG.get("whitelist_enabled")),
                "whitelist_count": len(API_CFG.get("whitelist") or []),
            },
            "web_login": meta.get("web_auth") or {},
            "sso_links": {
                "create_endpoint": "/api/v1/auth/sso-links/create",
                "supports_single_use": True,
                "supports_never_expires": True,
                "expired_links_auto_delete": False,
            },
        },
        "endpoints": _api_endpoint_index(),
    }

def _settings_runtime_payload(limit: int = 180) -> dict:
    try:
        n = max(20, min(1000, int(limit)))
    except Exception:
        n = 180
    aps, aps_seq, aps_total = _ap_snapshot()
    with log_lock:
        event_logs = list(log_buf)[-n:]
        operation_logs = list(op_buf)[-n:]
        scan_logs = list(scan_buf)[-n:]
        scan_diff_logs = list(scan_diff_buf)[-n:]
        ap_logs = list(ap_buf)[-n:]
        system_logs = list(sys_err_buf)[-n:]
    return {
        "ok": True,
        "aps": aps,
        "aps_seq": aps_seq,
        "aps_total": aps_total,
        "workflow": _history_reparse_workflow_snapshot(),
        "metrics": _host_metrics_payload(24 * 3600),
        "event_logs": event_logs,
        "operation_logs": operation_logs,
        "scan_logs": scan_logs,
        "scan_diff_logs": scan_diff_logs,
        "ap_logs": ap_logs,
        "system_logs": system_logs,
    }


def _diagnostics_summary_payload() -> dict:
    host = _host_resource_snapshot()
    parser = _packet_parse_diag_snapshot()
    workflow = _history_reparse_workflow_snapshot()
    cpu_percent = host.get("cpu_percent")
    load1 = host.get("load1")
    cpu_count = max(1, int(host.get("cpu_count") or os.cpu_count() or 1))
    load_percent = None
    try:
        if load1 is not None:
            load_percent = round(max(0.0, min(100.0, (float(load1) / float(cpu_count)) * 100.0)), 1)
    except Exception:
        load_percent = None
    return {
        "ok": True,
        "generated_wall": time.time(),
        "host": {
            "cpu_count": cpu_count,
            "cpu_percent": cpu_percent,
            "load1": host.get("load1"),
            "load5": host.get("load5"),
            "load15": host.get("load15"),
            "load_percent": load_percent,
        },
        "parser": parser,
        "workflow": workflow,
    }

def _logs_snapshot(log_type: str = "runtime", limit: int = 500) -> dict:
    try:
        n = max(1, min(5000, int(limit)))
    except Exception:
        n = 500
    kind = str(log_type or "runtime").strip().lower()
    with log_lock:
        runtime_rows = list(log_buf)[-n:]
        operation_rows = list(op_buf)[-n:]
        scan_rows = list(scan_buf)[-n:]
        scan_diff_rows = list(scan_diff_buf)[-n:]
        ap_rows = list(ap_buf)[-n:]
        system_rows = list(sys_err_buf)[-n:]
    if kind in ("op", "ops", "operation", "audit"):
        kind = "operation"
        rows = operation_rows
    elif kind in ("scan", "scanner"):
        kind = "scan"
        rows = scan_rows
    elif kind in ("ap", "ap_scan"):
        kind = "ap"
        rows = ap_rows
    elif kind in ("system", "system_error", "error", "errors"):
        kind = "system"
        rows = system_rows
    elif kind in ("diff", "scan_diff"):
        kind = "scan_diff"
        rows = scan_diff_rows
    else:
        kind = "runtime"
        rows = runtime_rows
    return {
        "ok": True,
        "type": kind,
        "limit": n,
        "count": len(rows),
        "items": rows,
        "available": ["runtime", "operation", "scan", "scan_diff", "ap", "system"],
    }

def _logs_export_bytes(log_type: str = "all", limit: int = 5000) -> tuple[bytes, str, str]:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    kind = str(log_type or "all").strip().lower()
    if kind == "all":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for name in ("runtime", "operation", "scan", "scan_diff", "ap", "system"):
                snap = _logs_snapshot(name, limit=limit)
                zf.writestr(f"{name}.log", "\n".join(str(x) for x in snap.get("items") or []) + "\n")
        return buf.getvalue(), f"xrs-logs-{stamp}.zip", "application/zip"
    snap = _logs_snapshot(kind, limit=limit)
    body = ("\n".join(str(x) for x in snap.get("items") or []) + "\n").encode("utf-8")
    return body, f"xrs-{snap.get('type')}-{stamp}.log", "text/plain; charset=utf-8"

def _oobe_status_payload() -> dict:
    cfg = load_app_config(APP_CONFIG_PATH) if APP_CONFIG_PATH else default_app_config()
    basic = cfg.get("basic") if isinstance(cfg, dict) else {}
    web = cfg.get("web") if isinstance(cfg, dict) else {}
    auth = cfg.get("auth") if isinstance(cfg, dict) else {}
    if not isinstance(basic, dict): basic = {}
    if not isinstance(web, dict): web = {}
    if not isinstance(auth, dict): auth = {}
    return {
        "ok": True,
        "oobe": _oobe_state(),
        "config_path": APP_CONFIG_PATH or "",
        "interfaces": _iface_options_snapshot(),
        "selected_iface": _cfg_preferred_iface_from_cfg(cfg),
        "network_bindings": _network_bindings_visual_payload(cfg),
        "channel": basic.get("channel"),
        "base_name": str(web.get("base_name") or "基站"),
        "base_lat": web.get("base_lat"),
        "base_lon": web.get("base_lon"),
        "auth_enabled": bool(auth.get("enabled")),
        "auth_configured": _auth_hashes_present(auth),
        "host": _host_resource_snapshot(),
    }

def _oobe_save_config(body: dict | None) -> dict:
    if not APP_CONFIG_PATH:
        return {"ok": False, "error": "config path missing"}
    payload = body if isinstance(body, dict) else {}
    iface = str(payload.get("iface") or "").strip()
    if not iface:
        return {"ok": False, "error": "必须选择默认网卡"}
    safe_iface = _hw_safe_iface(iface)
    if not safe_iface:
        return {"ok": False, "error": f"网卡不可用: {iface}"}
    iface = safe_iface
    try:
        channel = int(payload.get("channel") or 6)
    except Exception:
        channel = 6
    if channel < 1 or channel > 196:
        return {"ok": False, "error": "信道超出范围"}
    cfg = load_app_config(APP_CONFIG_PATH) if APP_CONFIG_PATH else default_app_config()
    basic = cfg.setdefault("basic", {})
    web = cfg.setdefault("web", {})
    auth = cfg.setdefault("auth", {})
    if not isinstance(basic, dict): basic = {}; cfg["basic"] = basic
    if not isinstance(web, dict): web = {}; cfg["web"] = web
    if not isinstance(auth, dict): auth = {}; cfg["auth"] = auth
    basic["iface"] = iface
    basic["channel"] = channel
    basic["no_tui"] = True
    basic["auto_self_heal"] = True
    nb_payload = payload.get("network_bindings") if isinstance(payload.get("network_bindings"), dict) else {}
    if nb_payload:
        cfg, bind_err = _network_bindings_apply_visual(cfg, nb_payload)
        if bind_err:
            return {"ok": False, "error": bind_err}
    else:
        cfg["network_bindings"] = _normalize_network_bindings_cfg({
            "basic": basic,
            "network_bindings": cfg.get("network_bindings") if isinstance(cfg.get("network_bindings"), dict) else {},
        })
    web["base_name"] = str(payload.get("base_name") or web.get("base_name") or "基站").strip() or "基站"
    for k, lo, hi in (("base_lat", -90.0, 90.0), ("base_lon", -180.0, 180.0)):
        raw_v = payload.get(k)
        if raw_v in (None, ""):
            continue
        try:
            val = float(raw_v)
        except Exception:
            return {"ok": False, "error": f"{k} 格式错误"}
        if not (lo <= val <= hi):
            return {"ok": False, "error": f"{k} 超出范围"}
        web[k] = val
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if username or password:
        if not username or not password:
            return {"ok": False, "error": "账号和密码必须同时填写"}
        auth["enabled"] = True
        auth["username_hash"] = _auth_secret_hash(username)
        auth["password_hash"] = _auth_secret_hash(password)
        auth["realm"] = str(auth.get("realm") or "XRS")
    b_ok, backup_path = create_config_backup(APP_CONFIG_PATH, tag="oobe")
    if not b_ok:
        return {"ok": False, "error": f"backup failed: {backup_path}"}
    ok, msg = save_app_config(APP_CONFIG_PATH, cfg)
    if not ok:
        return {"ok": False, "error": f"save failed: {msg}"}
    cfg_loaded = load_app_config(APP_CONFIG_PATH)
    r_ok, r_msg = reload_runtime_config(cfg_loaded)
    if not r_ok:
        restore_config_backup(APP_CONFIG_PATH, backup_path)
        return {"ok": False, "error": f"reload failed: {r_msg}", "backup_path": backup_path}
    _set_oobe_required("", False)
    _op_log("oobe-save", f"iface={iface} channel={channel} backup={backup_path}", ok=True)
    return {
        "ok": True,
        "saved_to": APP_CONFIG_PATH,
        "backup_path": backup_path,
        "iface": iface,
        "channel": channel,
        "reload_msg": r_msg,
        "login_required": bool(_normalize_auth_cfg(cfg_loaded).get("enabled")),
        "next": ("/login" if bool(_normalize_auth_cfg(cfg_loaded).get("enabled")) else "/"),
    }

def _diagnostic_run(cmd: str, timeout: int = 8) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "")
        err = (r.stderr or "")
        text = out
        if err:
            text += ("\n--- STDERR ---\n" + err)
        if not text.strip():
            text = f"(empty, rc={getattr(r, 'returncode', '')})\n"
        return text
    except Exception as e:
        return f"command failed: {e}\n"

def _diagnostic_redact(obj):
    sensitive = ("token", "password", "secret", "webhook", "key", "sha256", "authorization", "cookie")
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            ks = str(k).lower()
            if any(s in ks for s in sensitive):
                out[k] = "***REDACTED***" if v not in (None, "", []) else v
            else:
                out[k] = _diagnostic_redact(v)
        return out
    if isinstance(obj, list):
        return [_diagnostic_redact(x) for x in obj]
    return obj

def _diagnostic_zip_bytes() -> tuple[bytes, str]:
    now_wall = time.time()
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(now_wall))
    buf = io.BytesIO()
    now_mono = time.monotonic()
    meta = {
        "generated_at": _fmt_wall_ts(now_wall),
        "uptime_sec": int(max(0.0, now_wall - APP_START_WALL)),
        "cwd": APP_START_CWD,
        "config_path": APP_CONFIG_PATH or "",
        "history_store": HISTORY_STORE_PATH or "",
        "app_version": _app_version_label(),
        "python": sys.version,
        "platform": platform.platform(),
        "argv": list(sys.argv),
        "current_channel": current_channel,
        "sniff": _sniff_health_meta(now_mono, now_wall),
        "api": _api_meta(),
    }
    with log_lock:
        event_logs = list(log_buf)
        scan_logs = list(scan_buf)
        ap_logs = list(ap_buf)
        operation_logs = list(op_buf)
    with state_lock:
        state_summary = {
            "live_count": len(state_table),
            "history_count": len(history_table),
            "live_keys": sorted([str(k) for k in state_table.keys()])[:500],
            "history_keys": sorted([str(k) for k in history_table.keys()])[:500],
        }
    commands = {
        "system_uname.txt": "uname -a",
        "system_uptime.txt": "uptime",
        "system_free.txt": "free -h",
        "system_df.txt": "df -h",
        "system_ip_addr.txt": "ip addr",
        "system_ip_link.txt": "ip link",
        "wifi_iw_dev.txt": "iw dev",
        "wifi_iw_info.txt": "iw dev 2>/dev/null",
        "wifi_iw_phy.txt": "iw phy",
        "wifi_rfkill.txt": "rfkill list",
        "usb_lsusb.txt": "lsusb",
        "service_status.txt": "systemctl status xrs-scanner.service --no-pager -l",
        "service_journal.txt": "journalctl -u xrs-scanner.service -n 500 --no-pager",
        "process_ps.txt": "ps -eo pid,ppid,stat,pcpu,pmem,comm,args --sort=-pcpu | head -80",
    }
    if sniff_iface_name:
        safe_iface = shlex.quote(str(sniff_iface_name))
        commands[f"wifi_{sniff_iface_name}_info.txt"] = f"iw dev {safe_iface} info"
        commands[f"wifi_{sniff_iface_name}_link.txt"] = f"iw dev {safe_iface} link"
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("README.txt", (
            "XRS quality report\n"
            "Sensitive config values are redacted. Logs may still contain observed SN/MAC/location data.\n"
        ))
        zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        zf.writestr("state_summary.json", json.dumps(state_summary, ensure_ascii=False, indent=2))
        zf.writestr("snapshot.json", json.dumps(_state_snapshot(), ensure_ascii=False, indent=2))
        zf.writestr("config_redacted.json", json.dumps(_diagnostic_redact(APP_CONFIG), ensure_ascii=False, indent=2))
        zf.writestr("logs/event.log", "\n".join(event_logs) + ("\n" if event_logs else ""))
        zf.writestr("logs/scan.log", "\n".join(scan_logs) + ("\n" if scan_logs else ""))
        zf.writestr("logs/ap.log", "\n".join(ap_logs) + ("\n" if ap_logs else ""))
        zf.writestr("logs/operation.log", "\n".join(operation_logs) + ("\n" if operation_logs else ""))
        for name, cmd in commands.items():
            zf.writestr("commands/" + name, "$ " + cmd + "\n\n" + _diagnostic_run(cmd, timeout=10))
    data = buf.getvalue()
    if len(data) < 128:
        fallback = io.BytesIO()
        with zipfile.ZipFile(fallback, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr("README.txt", "XRS quality report fallback\n")
            zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        data = fallback.getvalue()
    filename = f"xrs-quality-{stamp}.zip"
    return data, filename
