"""security core (extracted from common_core.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
Shared globals/constants and sibling chunk functions resolve at call time.
"""

def _sha256_hex(text: str) -> str:
    # Only for non-security identifiers/cache keys. Do not use for passwords or auth secrets.
    return hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest().lower()

def _auth_secret_hash(value: str, salt: str | None = None) -> str:
    if not salt:
        salt_bytes = secrets.token_bytes(16)
        salt = base64.urlsafe_b64encode(salt_bytes).decode("ascii").rstrip("=")
    else:
        salt_bytes = base64.urlsafe_b64decode(salt + "=" * (-len(salt) % 4))
    n, r, p = 2 ** 14, 8, 1
    digest = hashlib.scrypt(
        str(value or "").encode("utf-8", errors="ignore"),
        salt=salt_bytes,
        n=n,
        r=r,
        p=p,
        dklen=32,
    )
    hash_text = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"scrypt${n}${r}${p}${salt}${hash_text}"

def _verify_auth_secret_hash(value: str, stored: str) -> bool:
    try:
        alg, n_text, r_text, p_text, salt, expected = str(stored or "").split("$", 5)
        if alg != "scrypt":
            return False
        n = int(n_text)
        r = int(r_text)
        p = int(p_text)
        if n < 2 ** 14 or r < 8 or p < 1:
            return False
        salt_bytes = base64.urlsafe_b64decode(salt + "=" * (-len(salt) % 4))
        digest = hashlib.scrypt(
            str(value or "").encode("utf-8", errors="ignore"),
            salt=salt_bytes,
            n=n,
            r=r,
            p=p,
            dklen=32,
        )
        actual = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return secrets.compare_digest(actual, expected)
    except Exception:
        return False

def _normalize_auth_secret_hash(stored: str | None) -> str:
    raw = str(stored or "").strip()
    try:
        alg, n_text, r_text, p_text, salt, expected = raw.split("$", 5)
        if alg == "scrypt" and int(n_text) >= 2 ** 14 and int(r_text) >= 8 and int(p_text) >= 1 and salt and expected:
            return raw
    except Exception:
        pass
    return ""

def _verify_auth_secret(value: str, stored: str) -> bool:
    normalized = _normalize_auth_secret_hash(stored)
    if not normalized:
        return False
    return _verify_auth_secret_hash(value, normalized)

def _auth_hashes_present(auth_cfg: dict | None = None) -> bool:
    source = auth_cfg if isinstance(auth_cfg, dict) else AUTH_CFG
    return bool(_normalize_auth_secret_hash(source.get("username_hash"))) and bool(_normalize_auth_secret_hash(source.get("password_hash")))

def _parse_whitelist_entries(values) -> list[str]:
    items: list[str] = []
    if isinstance(values, list):
        src = values
    elif values in (None, ""):
        src = []
    else:
        src = str(values).replace("\r", "\n").split("\n")
    seen: set[str] = set()
    for raw in src:
        text = str(raw or "").strip()
        if not text:
            continue
        if text in seen:
            continue
        try:
            ipaddress.ip_network(text, strict=False)
        except Exception:
            continue
        seen.add(text)
        items.append(text)
    return items

def _api_ip_allowed(ip_text: str | None, entries: list[str] | None = None) -> bool:
    return _ip_in_list(ip_text, entries if entries is not None else (API_CFG.get("whitelist") or []))

def _ip_in_list(ip_text: str | None, entries: list[str] | None = None) -> bool:
    try:
        ip_obj = ipaddress.ip_address(str(ip_text or "").strip())
    except Exception:
        return False
    rules = list(entries or [])
    if not rules:
        return False
    for item in rules:
        try:
            if ip_obj in ipaddress.ip_network(str(item), strict=False):
                return True
        except Exception:
            continue
    return False

def _ip_policy_allowed(ip_text: str | None, *, enabled: bool, mode: str, entries: list[str]) -> bool:
    if not enabled:
        return True
    hit = _ip_in_list(ip_text, entries)
    policy = str(mode or "allow").strip().lower()
    if policy in ("deny", "block", "black", "blacklist"):
        return not hit
    return hit

def _api_access_allowed(ip_text: str | None) -> bool:
    if not _api_tokens_have_secret(API_CFG):
        return True
    return _ip_policy_allowed(
        ip_text,
        enabled=bool(API_CFG.get("whitelist_enabled")),
        mode=str(API_CFG.get("whitelist_mode") or "allow"),
        entries=list(API_CFG.get("whitelist") or []),
    )

def _web_access_allowed(ip_text: str | None) -> bool:
    return _ip_policy_allowed(
        ip_text,
        enabled=bool(WEB_CFG.get("access_list_enabled")),
        mode=str(WEB_CFG.get("access_list_mode") or "allow"),
        entries=list(WEB_CFG.get("access_list") or []),
    )

def _normalize_sso_links(raw) -> list[dict]:
    src = raw if isinstance(raw, list) else []
    out: list[dict] = []
    seen: set[str] = set()
    for idx, item in enumerate(src):
        if not isinstance(item, dict):
            continue
        check = str(item.get("check") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", check or ""):
            continue
        if check in seen:
            continue
        seen.add(check)
        name = str(item.get("name") or f"SSO {idx + 1}").strip() or f"SSO {idx + 1}"
        try:
            created_ts = float(item.get("created_ts") or 0.0)
        except Exception:
            created_ts = 0.0
        try:
            expires_at = float(item.get("expires_at") or 0.0)
        except Exception:
            expires_at = 0.0
        try:
            used_ts = float(item.get("used_ts") or item.get("last_used_ts") or 0.0)
        except Exception:
            used_ts = 0.0
        try:
            used_count = max(0, int(item.get("used_count") or (1 if used_ts > 0 else 0)))
        except Exception:
            used_count = 0
        next_path = str(item.get("next") or "/").strip() or "/"
        if not next_path.startswith("/") or next_path.startswith("//"):
            next_path = "/"
        out.append({
            "name": name[:80],
            "check": check,
            "enabled": bool(item.get("enabled", True)),
            "created_ts": created_ts,
            "expires_at": max(0.0, expires_at),
            "single_use": _to_bool(item.get("single_use"), False),
            "used_ts": max(0.0, used_ts),
            "used_count": used_count,
            "next": next_path,
        })
    return out[:64]

def _prune_expired_sso_links(raw, now_wall: float | None = None, grace_sec: float = 5 * 3600) -> list[dict]:
    now_wall = float(now_wall or time.time())
    keep: list[dict] = []
    for item in _normalize_sso_links(raw):
        expires_at = float(item.get("expires_at") or 0.0)
        if expires_at > 0 and now_wall - expires_at > float(grace_sec):
            continue
        keep.append(item)
    return keep

def _sso_link_state(item: dict | None, now_wall: float | None = None) -> dict:
    now_wall = float(now_wall or time.time())
    raw = item if isinstance(item, dict) else {}
    expires_at = float(raw.get("expires_at") or 0.0)
    used_count = int(raw.get("used_count") or 0)
    single_use = bool(raw.get("single_use"))
    enabled = bool(raw.get("enabled", True))
    expired = bool(expires_at > 0 and expires_at <= now_wall)
    used = bool(single_use and used_count > 0)
    if not enabled:
        status = "disabled"
        label = "已停用"
    elif used:
        status = "used"
        label = "已使用"
    elif expired:
        status = "expired"
        label = "已过期"
    else:
        status = "active"
        label = "可用"
    expires_in = None if expires_at <= 0 else int(max(0.0, expires_at - now_wall))
    return {
        "active": status == "active",
        "status": status,
        "status_label": label,
        "expired": expired,
        "used": used,
        "expires_in_sec": expires_in,
    }

def _sso_expiry_from_payload(body: dict | None, now_wall: float | None = None) -> tuple[float, str | None]:
    now_wall = float(now_wall or time.time())
    src = body if isinstance(body, dict) else {}
    mode = str(src.get("expires") or src.get("expiry") or src.get("ttl_mode") or "").strip().lower()
    if mode in ("never", "forever", "infinite", "unlimited", "none", "0"):
        return 0.0, None
    if src.get("expires_at") not in (None, ""):
        try:
            expires_at = float(src.get("expires_at") or 0.0)
        except Exception:
            return 0.0, "invalid expires_at"
        if expires_at <= now_wall:
            return 0.0, "expires_at must be in the future"
        return expires_at, None
    raw_ttl = src.get("ttl_sec")
    if raw_ttl in (None, ""):
        raw_ttl = src.get("ttl_seconds")
    if raw_ttl in (None, ""):
        raw_ttl = src.get("ttl_min")
        if raw_ttl not in (None, ""):
            try:
                raw_ttl = float(raw_ttl) * 60.0
            except Exception:
                return 0.0, "invalid ttl_min"
    if raw_ttl in (None, ""):
        raw_ttl = 24 * 3600
    try:
        ttl_sec = int(float(raw_ttl))
    except Exception:
        return 0.0, "invalid ttl_sec"
    if ttl_sec <= 0:
        return 0.0, None
    ttl_sec = max(60, min(3650 * 86400, ttl_sec))
    return now_wall + ttl_sec, None

def _api_token_id_from_hash(token_hash: str | None, idx: int = 1) -> str:
    raw = str(token_hash or "").strip()
    if re.fullmatch(r"[0-9a-f]{64}", raw or ""):
        return "tok_" + raw[:12]
    return "tok_" + secrets.token_urlsafe(8).replace("-", "_")[:12]

def _api_token_expiry_from_row(row: dict | None, now_wall: float | None = None, fallback: float = 0.0) -> tuple[float, str | None]:
    src = row if isinstance(row, dict) else {}
    now_wall = float(now_wall or time.time())
    mode = str(src.get("expires") or src.get("expiry") or src.get("ttl_mode") or "").strip().lower()
    if mode in ("never", "forever", "infinite", "unlimited", "none", "0"):
        return 0.0, None
    if mode == "keep":
        return max(0.0, float(fallback or 0.0)), None
    if mode or src.get("ttl_sec") not in (None, "") or src.get("ttl_seconds") not in (None, "") or src.get("ttl_min") not in (None, ""):
        return _sso_expiry_from_payload(src, now_wall=now_wall)
    if src.get("expires_at") not in (None, ""):
        try:
            return max(0.0, float(src.get("expires_at") or 0.0)), None
        except Exception:
            return 0.0, "invalid expires_at"
    return max(0.0, float(fallback or 0.0)), None

def _normalize_api_tokens(raw, legacy_token: str = "", legacy_hash: str = "") -> list[dict]:
    src = raw if isinstance(raw, list) else []
    if not src:
        legacy_plain = str(legacy_token or "").strip()
        legacy_digest = _normalize_auth_secret_hash(legacy_hash)
        if legacy_plain or legacy_digest:
            src = [{
                "id": "legacy",
                "name": "默认 Token",
                "token": legacy_plain,
                "token_hash": legacy_digest,
                "enabled": True,
                "created_ts": 0.0,
                "expires_at": 0.0,
                "single_use": False,
            }]
    out: list[dict] = []
    seen: set[str] = set()
    now_wall = time.time()
    for idx, item in enumerate(src, 1):
        if not isinstance(item, dict):
            continue
        token_plain = str(item.get("token") or item.get("token_plain") or "").strip()
        if token_plain in ("********", "__KEEP__"):
            token_plain = ""
        token_hash = _normalize_auth_secret_hash(item.get("token_hash"))
        if token_plain:
            token_hash = _auth_secret_hash(token_plain)
        if not _normalize_auth_secret_hash(token_hash):
            continue
        raw_id = str(item.get("id") or "").strip()
        token_id = raw_id if re.fullmatch(r"[A-Za-z0-9_-]{3,64}", raw_id or "") else _api_token_id_from_hash(token_hash, idx)
        base_id = token_id
        suffix = 2
        while token_id in seen:
            token_id = f"{base_id}_{suffix}"
            suffix += 1
        seen.add(token_id)
        name = str(item.get("name") or f"API Token {idx}").strip() or f"API Token {idx}"
        try:
            created_ts = float(item.get("created_ts") or 0.0)
        except Exception:
            created_ts = 0.0
        if created_ts <= 0.0:
            created_ts = now_wall
        try:
            expires_at = max(0.0, float(item.get("expires_at") or 0.0))
        except Exception:
            expires_at = 0.0
        try:
            used_ts = max(0.0, float(item.get("used_ts") or item.get("last_used_ts") or 0.0))
        except Exception:
            used_ts = 0.0
        try:
            used_count = max(0, int(item.get("used_count") or (1 if used_ts > 0 else 0)))
        except Exception:
            used_count = 0
        out.append({
            "id": token_id,
            "name": name[:80],
            "token": "",
            "token_hash": token_hash,
            "enabled": _to_bool(item.get("enabled"), True),
            "created_ts": created_ts,
            "expires_at": expires_at,
            "single_use": _to_bool(item.get("single_use"), False),
            "used_ts": used_ts,
            "used_count": used_count,
        })
    return out[:64]

def _api_tokens_have_secret(api_cfg: dict | None = None) -> bool:
    source = api_cfg if isinstance(api_cfg, dict) else API_CFG
    return any(str(item.get("token_hash") or "").strip() for item in _normalize_api_tokens(source.get("tokens"), source.get("token") or "", source.get("token_hash") or ""))

def _api_tokens_public(api_cfg: dict | None = None) -> list[dict]:
    source = api_cfg if isinstance(api_cfg, dict) else API_CFG
    out: list[dict] = []
    for item in _normalize_api_tokens(source.get("tokens"), source.get("token") or "", source.get("token_hash") or ""):
        state = _sso_link_state(item)
        out.append({
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "enabled": bool(item.get("enabled", True)),
            "created_ts": float(item.get("created_ts") or 0.0),
            "expires_at": float(item.get("expires_at") or 0.0),
            "expires_in_sec": state.get("expires_in_sec"),
            "single_use": bool(item.get("single_use")),
            "used_ts": float(item.get("used_ts") or 0.0),
            "used_count": int(item.get("used_count") or 0),
            "active": bool(state.get("active")),
            "status": str(state.get("status") or ""),
            "status_label": str(state.get("status_label") or ""),
        })
    return out

def _normalize_passkeys(raw) -> list[dict]:
    src = raw if isinstance(raw, list) else []
    out: list[dict] = []
    seen: set[str] = set()
    now_wall = time.time()
    for idx, item in enumerate(src, 1):
        if not isinstance(item, dict):
            continue
        pk_id = str(item.get("id") or item.get("credential_id") or "").strip()
        if not pk_id:
            continue
        if pk_id in seen:
            continue
        seen.add(pk_id)
        pk_name = str(item.get("name") or f"通行密钥 {idx}").strip() or f"通行密钥 {idx}"
        public_key = item.get("public_key") if isinstance(item.get("public_key"), dict) else {}
        x = str(public_key.get("x") or item.get("x") or "").strip()
        y = str(public_key.get("y") or item.get("y") or "").strip()
        if not x or not y:
            continue
        try:
            sign_count = max(0, int(item.get("sign_count") or 0))
        except Exception:
            sign_count = 0
        try:
            created_ts = float(item.get("created_ts") or 0.0)
        except Exception:
            created_ts = 0.0
        if created_ts <= 0.0:
            created_ts = now_wall
        try:
            last_used_ts = max(0.0, float(item.get("last_used_ts") or 0.0))
        except Exception:
            last_used_ts = 0.0
        out.append({
            "id": pk_id[:128],
            "name": pk_name[:80],
            "user_handle": str(item.get("user_handle") or ""),
            "public_key": {"kty": "EC", "crv": "P-256", "x": x, "y": y},
            "sign_count": sign_count,
            "created_ts": created_ts,
            "last_used_ts": last_used_ts,
            "enabled": bool(item.get("enabled", True)),
        })
    return out[:32]

def _normalize_auth_login_methods(raw, *, default_missing=None, default_empty=None) -> list[str]:
    alias = {
        "password": "password",
        "userpass": "password",
        "user_pass": "password",
        "username_password": "password",
        "account_password": "password",
        "passkey": "passkey",
        "webauthn": "passkey",
    }
    if raw is None:
        src = []
        fallback = default_missing
    elif isinstance(raw, dict):
        src = [k for k, enabled in raw.items() if enabled]
        fallback = default_empty
    elif isinstance(raw, (list, tuple, set)):
        src = list(raw)
        fallback = default_empty
    else:
        src = re.split(r"[\s,;|]+", str(raw or ""))
        fallback = default_empty
    out: list[str] = []
    seen: set[str] = set()
    for item in src:
        key = alias.get(str(item or "").strip().lower().replace("-", "_"))
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    if out:
        return out
    if fallback is None:
        return []
    return _normalize_auth_login_methods(fallback, default_missing=None, default_empty=None)

def _auth_login_methods(auth_cfg: dict | None = None) -> list[str]:
    source = auth_cfg if isinstance(auth_cfg, dict) else AUTH_CFG
    return _normalize_auth_login_methods(
        source.get("login_methods") if isinstance(source, dict) else None,
        default_missing=("password", "passkey"),
        default_empty=("password", "passkey"),
    )

def _auth_login_method_enabled(method: str, auth_cfg: dict | None = None) -> bool:
    return str(method or "").strip().lower() in _auth_login_methods(auth_cfg)

def _prepare_auth_cfg_for_save(auth_cfg: dict | None) -> dict:
    raw = dict(auth_cfg) if isinstance(auth_cfg, dict) else {}
    out = dict(raw)
    plain_user = str(out.pop("username", "") or "").strip()
    plain_pass = str(out.pop("password", "") or "")
    user_hash = _normalize_auth_secret_hash(out.get("username_hash"))
    pass_hash = _normalize_auth_secret_hash(out.get("password_hash"))
    if plain_user:
        user_hash = _auth_secret_hash(plain_user)
    if plain_pass:
        pass_hash = _auth_secret_hash(plain_pass)
    out["enabled"] = bool(out.get("enabled"))
    out["realm"] = str(out.get("realm") or "XRS").strip() or "XRS"
    try:
        out["session_ttl_min"] = max(1, min(10080, int(out.get("session_ttl_min") or 30)))
    except Exception:
        out["session_ttl_min"] = 30
    out["login_methods"] = _normalize_auth_login_methods(
        out.get("login_methods"),
        default_missing=("password", "passkey"),
        default_empty=[],
    )
    out["username_hash"] = user_hash
    out["password_hash"] = pass_hash
    out["sso_links"] = _normalize_sso_links(out.get("sso_links"))
    out["passkeys"] = _normalize_passkeys(out.get("passkeys"))
    return out

def _prepare_api_cfg_for_save(api_cfg: dict | None) -> dict:
    raw = dict(api_cfg) if isinstance(api_cfg, dict) else {}
    out = dict(raw)
    plain_token = str(out.get("token") or out.get("token_plain") or "").strip()
    token_hash = _normalize_auth_secret_hash(out.get("token_hash"))
    if plain_token:
        token_hash = _auth_secret_hash(plain_token)
    tokens = _normalize_api_tokens(out.get("tokens"), plain_token, token_hash)
    first = tokens[0] if tokens else {}
    out["enabled"] = bool(out.get("enabled"))
    out["tokens"] = tokens
    out["token"] = str(first.get("token") or "")
    out["token_hash"] = str(first.get("token_hash") or "")
    out["whitelist_enabled"] = bool(out.get("whitelist_enabled"))
    mode = str(out.get("whitelist_mode") or "allow").strip().lower()
    out["whitelist_mode"] = "deny" if mode in ("deny", "block", "black", "blacklist") else "allow"
    out["whitelist"] = _parse_whitelist_entries(out.get("whitelist"))
    out.pop("token_plain", None)
    return out

def _access_rule_empty_error(label: str, enabled: bool, mode: str, entries: list[str]) -> str | None:
    if not enabled:
        return None
    policy = str(mode or "allow").strip().lower()
    if policy in ("deny", "block", "black", "blacklist"):
        return None
    if not entries:
        return f"{label}白名单模式已开启，但地址列表为空或格式无效"
    return None

def _validate_security_sections(auth_cfg: dict | None, api_cfg: dict | None, web_cfg: dict | None = None) -> str | None:
    auth = _prepare_auth_cfg_for_save(auth_cfg)
    api = _prepare_api_cfg_for_save(api_cfg)
    web = web_cfg if isinstance(web_cfg, dict) else {}
    if not list(auth.get("login_methods") or []):
        return "至少保留一种网页登录方式"
    if bool(auth.get("enabled")) and ("password" not in list(auth.get("login_methods") or [])):
        passkey_ready = any(bool(item.get("enabled", True)) for item in _normalize_passkeys(auth.get("passkeys")))
        if not passkey_ready:
            return "关闭账号密码登录前，至少先准备一把可用 PassKey"
    if bool(auth.get("enabled")) and (not _auth_hashes_present(auth)):
        return "启用网页登录前，需先设置账号和密码"
    api_rule_err = _access_rule_empty_error(
        "API ",
        bool(api.get("whitelist_enabled")) and _api_tokens_have_secret(api),
        str(api.get("whitelist_mode") or "allow"),
        list(api.get("whitelist") or []),
    )
    if api_rule_err:
        return api_rule_err
    web_rule_err = _access_rule_empty_error(
        "网页访问",
        bool(web.get("access_list_enabled")),
        str(web.get("access_list_mode") or "allow"),
        _parse_whitelist_entries(web.get("access_list")),
    )
    if web_rule_err:
        return web_rule_err
    if bool(api.get("enabled")):
        if not bool(auth.get("enabled")):
            return "启用外部 API 前，需先启用网页登录"
        if not _auth_hashes_present(auth):
            return "启用外部 API 前，需先设置账号和密码"
        if not _api_tokens_have_secret(api):
            return "启用外部 API 前，需先设置 API Token"
    return None

def _prepare_security_cfg_for_save(cfg: dict | None) -> tuple[dict, str | None]:
    out = dict(cfg) if isinstance(cfg, dict) else {}
    auth_raw = out.get("auth") if isinstance(out.get("auth"), dict) else {}
    api_raw = out.get("api") if isinstance(out.get("api"), dict) else {}
    web_raw = out.get("web") if isinstance(out.get("web"), dict) else {}
    auth_next = _prepare_auth_cfg_for_save(auth_raw)
    api_next = _prepare_api_cfg_for_save(api_raw)
    err = _validate_security_sections(auth_next, api_next, web_raw)
    out["auth"] = auth_next
    out["api"] = api_next
    return out, err

def _normalize_auth_cfg(cfg: dict | None) -> dict:
    base = dict(AUTH_CFG)
    plain_user = ""
    plain_pass = ""
    if isinstance(cfg, dict):
        auth = cfg.get("auth")
        if isinstance(auth, dict):
            for k in base.keys():
                if k in auth:
                    base[k] = auth.get(k)
            plain_user = str(auth.get("username") or "").strip()
            plain_pass = str(auth.get("password") or "")
    base["enabled"] = bool(base.get("enabled"))
    base["realm"] = str(base.get("realm") or "XRS").strip() or "XRS"
    try:
        base["session_ttl_min"] = max(1, min(10080, int(base.get("session_ttl_min") or 30)))
    except Exception:
        base["session_ttl_min"] = 30
    base["login_methods"] = _normalize_auth_login_methods(
        base.get("login_methods"),
        default_missing=("password", "passkey"),
        default_empty=("password", "passkey"),
    )
    u = _normalize_auth_secret_hash(base.get("username_hash"))
    p = _normalize_auth_secret_hash(base.get("password_hash"))
    if (not u) and plain_user:
        u = _auth_secret_hash(plain_user)
        _log("[WARN] auth.username detected in plain text; converted to scrypt in memory")
    if (not p) and plain_pass:
        p = _auth_secret_hash(plain_pass)
        _log("[WARN] auth.password detected in plain text; converted to scrypt in memory")
    base["username_hash"] = u
    base["password_hash"] = p
    base["sso_links"] = _normalize_sso_links(base.get("sso_links"))
    base["passkeys"] = _normalize_passkeys(base.get("passkeys"))
    if base["enabled"] and (not u or not p):
        _log("[WARN] auth enabled but username/password hash missing, fallback disabled")
        base["enabled"] = False
    return base

def _mask_secret(value: str | None, keep: int = 4) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    keep = max(1, int(keep or 1))
    if len(raw) <= keep * 2:
        return "*" * len(raw)
    return raw[:keep] + ("*" * max(4, len(raw) - keep * 2)) + raw[-keep:]

def _normalize_wecom_webhooks(raw_list, legacy_key: str = "") -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    src: list = []
    legacy_key = str(legacy_key or "").strip()
    if legacy_key:
        src.append({"name": "默认通道", "key": legacy_key, "enabled": True})
    if isinstance(raw_list, list):
        src.extend(raw_list)
    elif raw_list not in (None, "", []):
        src.append(raw_list)
    for idx, item in enumerate(src, 1):
        if isinstance(item, dict):
            name = str(item.get("name") or f"通道 {idx}").strip() or f"通道 {idx}"
            key = str(item.get("key") or "").strip()
            enabled = bool(item.get("enabled", True))
        else:
            name = f"通道 {idx}"
            key = str(item or "").strip()
            enabled = True
        if not key or key in seen:
            continue
        seen.add(key)
        items.append({
            "name": name,
            "key": key,
            "enabled": enabled,
        })
    return items

def _normalize_alarm_zone_item(zone, idx: int = 1) -> dict:
    base = dict(WEB_CFG.get("alarm_zone") or {})
    zone = zone if isinstance(zone, dict) else {}
    item = {
        "enabled": bool(zone.get("enabled", base.get("enabled", False))),
        "name": str(zone.get("name") or base.get("name") or f"报警区域 {idx}").strip() or f"报警区域 {idx}",
    }
    for k, lo, hi in (
        ("lat1", -90.0, 90.0),
        ("lat2", -90.0, 90.0),
        ("lon1", -180.0, 180.0),
        ("lon2", -180.0, 180.0),
    ):
        try:
            raw_v = zone.get(k)
            val = None if raw_v in (None, "") else float(raw_v)
            if val is not None and not (lo <= val <= hi):
                val = None
        except Exception:
            val = None
        item[k] = val
    if None in (item["lat1"], item["lon1"], item["lat2"], item["lon2"]):
        item["enabled"] = False
    return item

def _normalize_alarm_zones(raw_list, legacy_zone=None) -> list[dict]:
    src: list = []
    if isinstance(raw_list, list):
        src.extend(raw_list)
    elif raw_list not in (None, "", []):
        src.append(raw_list)
    if (not src) and isinstance(legacy_zone, dict):
        src.append(legacy_zone)
    items: list[dict] = []
    for idx, item in enumerate(src, 1):
        norm = _normalize_alarm_zone_item(item, idx=idx)
        has_coords = any(norm.get(k) is not None for k in ("lat1", "lon1", "lat2", "lon2"))
        if not has_coords and not bool(norm.get("enabled")) and str(norm.get("name") or "").strip() in ("", "报警区域", f"报警区域 {idx}"):
            continue
        items.append(norm)
    return items

def _notify_wecom_targets(cfg: dict | None = None) -> list[dict]:
    source = cfg if isinstance(cfg, dict) else NOTIFY_CFG
    hooks = _normalize_wecom_webhooks(source.get("wecom_webhooks"), source.get("wecom_webhook_key") or "")
    return [x for x in hooks if x.get("enabled") and str(x.get("key") or "").strip()]

def _alarm_zone_names_for_point(lat, lon) -> list[str]:
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception:
        return []
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
        return []
    try:
        zones = _normalize_alarm_zones(WEB_CFG.get("alarm_zones"), WEB_CFG.get("alarm_zone"))
    except Exception:
        zones = []
    hits: list[str] = []
    for idx, z in enumerate(zones):
        if not isinstance(z, dict) or not bool(z.get("enabled")):
            continue
        try:
            lat1 = float(z.get("lat1"))
            lat2 = float(z.get("lat2"))
            lon1 = float(z.get("lon1"))
            lon2 = float(z.get("lon2"))
        except Exception:
            continue
        south, north = min(lat1, lat2), max(lat1, lat2)
        west, east = min(lon1, lon2), max(lon1, lon2)
        if south <= lat_f <= north and west <= lon_f <= east:
            name = str(z.get("name") or f"报警区域 {idx + 1}").strip() or f"报警区域 {idx + 1}"
            hits.append(name)
    return hits

def _normalize_api_cfg(cfg: dict | None) -> dict:
    base = dict(API_CFG)
    if isinstance(cfg, dict):
        api = cfg.get("api")
        if isinstance(api, dict):
            for k in base.keys():
                if k in api:
                    base[k] = api.get(k)
    base = _prepare_api_cfg_for_save(base)
    if base.get("token") and not str(base.get("token_hash") or "").strip():
        base["token_hash"] = _auth_secret_hash(str(base.get("token") or "").strip())
        _log("[WARN] api.token detected in plain text; converted to scrypt in memory")
    auth_cfg = _normalize_auth_cfg(cfg)
    if base["enabled"] and not _api_tokens_have_secret(base):
        _log("[WARN] api token enabled but token hash missing, fallback disabled")
        base["enabled"] = False
    if base["enabled"] and not bool(auth_cfg.get("enabled")):
        _log("[WARN] api enabled but auth disabled, fallback disabled")
        base["enabled"] = False
    if base["enabled"] and not _auth_hashes_present(auth_cfg):
        _log("[WARN] api enabled but auth credentials missing, fallback disabled")
        base["enabled"] = False
    api_rule_err = _access_rule_empty_error(
        "API ",
        bool(base.get("whitelist_enabled")) and _api_tokens_have_secret(base),
        str(base.get("whitelist_mode") or "allow"),
        list(base.get("whitelist") or []),
    )
    if api_rule_err:
        _log("[WARN] " + api_rule_err)
        base["enabled"] = False
    return base
