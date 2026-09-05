def _path_uses_api_token(req_path: str | None) -> bool:
    path = str(req_path or "").split("?", 1)[0]
    if path == "/api/docs":
        return True
    if path == "/api/health":
        return True
    if path in ("/api/v1", "/api/v1/"):
        return True
    return path.startswith("/api/v1/")

def _path_is_page_api(req_path: str | None) -> bool:
    path = str(req_path or "").split("?", 1)[0]
    return path.startswith("/api/") and (not _path_uses_api_token(path))

def _path_is_oobe_public(req_path: str | None) -> bool:
    path = str(req_path or "").split("?", 1)[0]
    return path in ("/oobe", "/oobe.html", "/api/oobe/status", "/api/oobe/save", "/api/health")

def _oobe_redirect_required(req_path: str | None) -> bool:
    if not _oobe_state().get("required"):
        return False
    path = str(req_path or "").split("?", 1)[0]
    if _path_is_oobe_public(path):
        return False
    return True

def _oobe_auth_required() -> bool:
    return bool(_oobe_state().get("required")) and _auth_enabled() and _auth_hashes_present(AUTH_CFG)

def _auth_enabled() -> bool:
    if _portable_edition_enabled():
        return False
    return bool(AUTH_CFG.get("enabled"))

def _auth_check_userpass(username: str, password: str) -> bool:
    if not _auth_enabled():
        return True
    u_hash = str(AUTH_CFG.get("username_hash") or "").strip()
    p_hash = str(AUTH_CFG.get("password_hash") or "").strip()
    if not u_hash or not p_hash:
        return False
    u_ok = _verify_auth_secret(username, u_hash)
    p_ok = _verify_auth_secret(password, p_hash)
    return bool(u_ok and p_ok)


def _auth_sso_path(check: str, next_path: str = "/") -> str:
    from urllib.parse import quote
    target = str(next_path or "/").strip() or "/"
    if not target.startswith("/") or target.startswith("//"):
        target = "/"
    return (
        "/login?check=" + quote(str(check or "").strip(), safe="")
        + "&next=" + quote(target, safe="/")
    )

def _auth_sso_public_links(auth_cfg: dict | None = None, *, include_paths: bool = False) -> list[dict]:
    from urllib.parse import quote
    source = auth_cfg if isinstance(auth_cfg, dict) else AUTH_CFG
    out: list[dict] = []
    for item in _prune_expired_sso_links(source.get("sso_links")):
        check = str(item.get("check") or "").strip()
        next_path = str(item.get("next") or "/")
        path = (
            "/login?check=" + quote(check, safe="")
            + "&next=" + quote(next_path, safe="/")
        )
        state = _sso_link_state(item)
        row = {
            "name": str(item.get("name") or ""),
            "check": check,
            "enabled": bool(item.get("enabled", True)),
            "created_ts": float(item.get("created_ts") or 0.0),
            "expires_at": float(item.get("expires_at") or 0.0),
            "expires_in_sec": state.get("expires_in_sec"),
            "single_use": bool(item.get("single_use")),
            "used_ts": float(item.get("used_ts") or 0.0),
            "used_count": int(item.get("used_count") or 0),
            "next": next_path,
            "active": bool(state.get("active")),
            "status": str(state.get("status") or ""),
            "status_label": str(state.get("status_label") or ""),
        }
        if include_paths:
            row["path"] = path
        out.append(row)
    return out

def _auth_check_sso_link(check: str | None) -> dict | None:
    raw_check = str(check or "").strip()
    if not raw_check:
        return None
    for item in _prune_expired_sso_links(AUTH_CFG.get("sso_links")):
        if hmac.compare_digest(str(item.get("check") or ""), raw_check) and bool(_sso_link_state(item).get("active")):
            return dict(item)
    return None

def _auth_mark_sso_used(check: str | None) -> bool:
    raw_check = str(check or "").strip()
    if not raw_check:
        return False
    changed = False
    now_wall = time.time()
    def _mark(links):
        nonlocal changed
        out = []
        for item in links:
            row = dict(item or {})
            if hmac.compare_digest(str(row.get("check") or ""), raw_check):
                row["used_count"] = int(row.get("used_count") or 0) + 1
                row["used_ts"] = now_wall
                changed = True
            out.append(row)
        return out
    ok, _msg, _links = _auth_mutate_sso_links(_mark, tag="sso_use")
    return bool(ok and changed)

def _build_sso_link_payload(body: dict | None, *, require_reauth: bool = True, headers=None, client_ip: str | None = None) -> tuple[dict, int]:
    if not _auth_enabled() or (not _auth_hashes_present(AUTH_CFG)):
        return {"ok": False, "error": "网页登录未启用"}, 400
    src = body if isinstance(body, dict) else {}
    subject = str(src.get("username") or "-")
    if require_reauth:
        reauth_ok = _auth_check_userpass(str(src.get("username") or ""), str(src.get("password") or ""))
        if not reauth_ok and headers is not None and headers.get("Authorization"):
            reauth_ok = _auth_check_basic_header(headers.get("Authorization"))
        if not reauth_ok:
            _op_log("login-link-create", "", actor=subject, ip=str(client_ip or "-"), ok=False)
            return {"ok": False, "error": "用户名或密码错误"}, 401
    next_path = str(src.get("next") or "/").strip() or "/"
    if not next_path.startswith("/") or next_path.startswith("//"):
        next_path = "/"
    name = str(src.get("name") or "").strip()
    if not name:
        name = "SSO " + time.strftime("%Y-%m-%d %H:%M:%S")
    now_wall = time.time()
    expires_at, expiry_err = _sso_expiry_from_payload(src, now_wall=now_wall)
    if expiry_err:
        return {"ok": False, "error": expiry_err}, 400
    single_use = _to_bool(src.get("single_use"), False)
    check = secrets.token_urlsafe(16)
    def _add_link(links):
        links.append({
            "name": name,
            "check": check,
            "enabled": True,
            "created_ts": now_wall,
            "expires_at": expires_at,
            "single_use": single_use,
            "used_ts": 0.0,
            "used_count": 0,
            "next": next_path,
        })
        return links[-64:]
    ok, msg, links = _auth_mutate_sso_links(_add_link, tag="sso_create")
    if not ok:
        return {"ok": False, "error": msg, "links": links}, 500
    path_url = _auth_sso_path(check, next_path=next_path)
    return {
        "ok": True,
        "check": check,
        "name": name,
        "path": path_url,
        "expires_at": expires_at,
        "expires_in_sec": None if expires_at <= 0 else int(max(0.0, expires_at - now_wall)),
        "single_use": single_use,
        "next": next_path,
        "links": links,
    }, 200

def _auth_mutate_sso_links(mutator, *, tag: str = "sso") -> tuple[bool, str, list[dict]]:
    if not APP_CONFIG_PATH:
        return False, "config path missing", _auth_sso_public_links()
    try:
        with auth_sso_lock:
            cfg = load_app_config(APP_CONFIG_PATH)
            auth = cfg.setdefault("auth", {})
            if not isinstance(auth, dict):
                auth = {}
                cfg["auth"] = auth
            links = _prune_expired_sso_links(auth.get("sso_links"))
            auth["sso_links"] = _prune_expired_sso_links(mutator(list(links)))
            cfg, guard_err = _prepare_security_cfg_for_save(cfg)
            if guard_err:
                return False, guard_err, _auth_sso_public_links()
            b_ok, backup_path = create_config_backup(APP_CONFIG_PATH, tag=tag)
            if not b_ok:
                return False, f"backup failed: {backup_path}", _auth_sso_public_links()
            ok, msg = save_app_config(APP_CONFIG_PATH, cfg)
            if not ok:
                return False, msg, _auth_sso_public_links()
            cfg_loaded = load_app_config(APP_CONFIG_PATH)
            r_ok, r_msg = reload_runtime_config(cfg_loaded)
            if not r_ok:
                return False, f"reload failed: {r_msg}", _auth_sso_public_links()
            auth_loaded = cfg_loaded.get("auth") if isinstance(cfg_loaded, dict) else None
            return True, "ok", _auth_sso_public_links(auth_loaded if isinstance(auth_loaded, dict) else None)
    except Exception as e:
        return False, str(e), _auth_sso_public_links()

def _auth_check_basic_header(header_value: str | None) -> bool:
    if not _auth_enabled():
        return True
    raw = str(header_value or "").strip()
    if not raw.startswith("Basic "):
        return False
    token = raw[6:].strip()
    if not token:
        return False
    try:
        text = base64.b64decode(token).decode("utf-8", errors="replace")
    except Exception:
        return False
    if ":" not in text:
        return False
    user, pwd = text.split(":", 1)
    return _auth_check_userpass(user, pwd)

def _rate_key(scope: str, ip: str | None, subject: str | None = "") -> str:
    return f"{str(scope or 'default')}:{str(ip or '-')}:{str(subject or '-')[:96]}"

def _rate_limited(scope: str, ip: str | None, subject: str | None = "", *, limit: int = 8, window_sec: int = 300, block_sec: int = 900) -> tuple[bool, int]:
    now_wall = time.time()
    key = _rate_key(scope, ip, subject)
    with security_rate_lock:
        st = security_rate_state.get(key) or {"fails": [], "blocked_until": 0.0}
        blocked_until = float(st.get("blocked_until") or 0.0)
        if blocked_until > now_wall:
            return True, int(max(1.0, blocked_until - now_wall))
        fails = [float(x) for x in (st.get("fails") or []) if now_wall - float(x) <= float(window_sec)]
        st["fails"] = fails
        security_rate_state[key] = st
        if len(security_rate_state) > 4096:
            stale = [k for k, v in security_rate_state.items()
                     if float((v or {}).get("blocked_until") or 0.0) <= now_wall and not (v or {}).get("fails")]
            for k in stale[:2048]:
                security_rate_state.pop(k, None)
        if len(fails) >= int(limit):
            st["blocked_until"] = now_wall + float(block_sec)
            return True, int(block_sec)
    return False, 0

def _rate_note(scope: str, ip: str | None, subject: str | None = "", *, success: bool, limit: int = 8, window_sec: int = 300, block_sec: int = 900) -> None:
    key = _rate_key(scope, ip, subject)
    now_wall = time.time()
    with security_rate_lock:
        if success:
            security_rate_state.pop(key, None)
            return
        st = security_rate_state.get(key) or {"fails": [], "blocked_until": 0.0}
        fails = [float(x) for x in (st.get("fails") or []) if now_wall - float(x) <= float(window_sec)]
        fails.append(now_wall)
        st["fails"] = fails
        if len(fails) >= int(limit):
            st["blocked_until"] = now_wall + float(block_sec)
            _op_log("rate-limit", f"scope={scope} subject={str(subject or '-')[:96]} blocked={block_sec}s fails={len(fails)}", ip=str(ip or "-"), ok=False)
        security_rate_state[key] = st
        if len(security_rate_state) > 4096:
            ordered = sorted(security_rate_state.items(), key=lambda kv: max([float(x) for x in ((kv[1] or {}).get("fails") or [0.0])] + [float((kv[1] or {}).get("blocked_until") or 0.0)]), reverse=True)
            security_rate_state.clear()
            security_rate_state.update(dict(ordered[:2048]))

def _auth_cookie_parse(cookie_header: str | None, key: str) -> str:
    raw = str(cookie_header or "")
    if not raw:
        return ""
    for part in raw.split(";"):
        p = str(part or "").strip()
        if not p or "=" not in p:
            continue
        k, v = p.split("=", 1)
        if k.strip() == key:
            return v.strip()
    return ""

def _auth_cleanup_sessions(now_wall: float | None = None) -> None:
    now_wall = float(now_wall or time.time())
    with auth_session_lock:
        stale = [tok for tok, exp in auth_sessions.items() if float(exp or 0.0) <= now_wall]
        for tok in stale:
            auth_sessions.pop(tok, None)

def _auth_issue_session() -> str:
    now_wall = time.time()
    tok_src = f"{now_wall}:{random.random()}:{auth_session_secret}:{os.getpid()}"
    token = hashlib.sha256(tok_src.encode("utf-8", errors="ignore")).hexdigest().lower()
    exp = now_wall + float(AUTH_SESSION_TTL_SEC)
    with auth_session_lock:
        auth_sessions[token] = exp
        if len(auth_sessions) > 4096:
            stale = [tok for tok, ts in auth_sessions.items() if float(ts or 0.0) <= now_wall]
            for tok in stale:
                auth_sessions.pop(tok, None)
            if len(auth_sessions) > 4096:
                # keep most recently expiring sessions
                keep = sorted(auth_sessions.items(), key=lambda kv: float(kv[1]), reverse=True)[:2048]
                auth_sessions.clear()
                auth_sessions.update({k: v for k, v in keep})
    return token

def _auth_check_session_cookie(cookie_header: str | None, *, refresh: bool = True) -> bool:
    if not _auth_enabled():
        return True
    token = _auth_cookie_parse(cookie_header, AUTH_SESSION_COOKIE)
    if not token:
        return False
    now_wall = time.time()
    with auth_session_lock:
        exp = auth_sessions.get(token)
        if not exp or float(exp) <= now_wall:
            auth_sessions.pop(token, None)
            return False
        if refresh:
            auth_sessions[token] = now_wall + float(AUTH_SESSION_TTL_SEC)
    return True

def _request_same_origin(headers) -> bool:
    host = str(headers.get("Host") or "").strip().lower()
    if not host:
        return True
    for header_name in ("Origin", "Referer"):
        raw = str(headers.get(header_name) or "").strip()
        if not raw:
            continue
        try:
            from urllib.parse import urlparse as _urlparse
            parsed = _urlparse(raw)
            if parsed.netloc and parsed.netloc.lower() != host:
                return False
        except Exception:
            return False
    return True

def _page_api_header_ok(headers) -> bool:
    value = str(headers.get(PAGE_API_HEADER) or "").strip()
    return value == PAGE_API_HEADER_VALUE

def _update_probe_header_ok(headers) -> bool:
    value = str(headers.get(UPDATE_PROBE_HEADER) or "").strip()
    return value == UPDATE_PROBE_HEADER_VALUE

