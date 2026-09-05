"""WebAuthn / passkey domain: CBOR, P-256 & ECDSA primitives, attestation parsing,
passkey CRUD and register/login flows (extracted from auth_core.py during backend split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
"""

def _webauthn_b64u_encode(data: bytes | None) -> str:
    raw = bytes(data or b"")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

def _webauthn_b64u_decode(text: str | None) -> bytes:
    raw = str(text or "").strip()
    if not raw:
        return b""
    raw += "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw.encode("ascii"))

def _webauthn_host_from_header(host_header: str | None) -> str:
    host = str(host_header or "").strip().lower()
    if not host:
        return "localhost"
    if host.startswith("[") and "]" in host:
        host = host[1:host.index("]")]
    elif ":" in host:
        host = host.rsplit(":", 1)[0]
    return host or "localhost"

def _webauthn_origin_from_headers(headers) -> str:
    host = _webauthn_host_from_header(headers.get("Host") if headers is not None else None)
    if headers is not None:
        proto = str(headers.get("X-Forwarded-Proto") or "").strip().lower()
        if proto not in ("http", "https"):
            origin = str(headers.get("Origin") or "").strip()
            m = re.match(r"^(https?)://([^/]+)", origin)
            if m:
                proto = m.group(1).lower()
        if proto not in ("http", "https"):
            proto = "https" if str(headers.get("Upgrade-Insecure-Requests") or "") == "1" else "http"
    else:
        proto = "http"
    return f"{proto}://{host}"

def _webauthn_rp_id_from_headers(headers) -> str:
    return _webauthn_host_from_header(headers.get("Host") if headers is not None else None)

def _webauthn_user_handle() -> bytes:
    seed = str(AUTH_CFG.get("username_hash") or AUTH_CFG.get("realm") or "XRS").strip()
    if not seed:
        seed = "XRS"
    return hashlib.sha256((seed + "|passkey").encode("utf-8", errors="ignore")).digest()

_CBOR_BREAK = object()

def _cbor_read_length(data: bytes, offset: int, ai: int) -> tuple[int | None, int]:
    if ai < 24:
        return ai, offset
    if ai == 24:
        return data[offset], offset + 1
    if ai == 25:
        return int.from_bytes(data[offset:offset + 2], "big"), offset + 2
    if ai == 26:
        return int.from_bytes(data[offset:offset + 4], "big"), offset + 4
    if ai == 27:
        return int.from_bytes(data[offset:offset + 8], "big"), offset + 8
    if ai == 31:
        return None, offset
    raise ValueError("unsupported cbor length")

def _cbor_decode_one(data: bytes, offset: int = 0):
    if offset >= len(data):
        raise ValueError("cbor truncated")
    initial = data[offset]
    offset += 1
    major = initial >> 5
    ai = initial & 31
    if major in (0, 1):
        n, offset = _cbor_read_length(data, offset, ai)
        if n is None:
            raise ValueError("indefinite integer")
        return (n if major == 0 else -1 - n), offset
    if major in (2, 3):
        length, offset = _cbor_read_length(data, offset, ai)
        if length is None:
            chunks: list[bytes] = []
            while True:
                if offset >= len(data):
                    raise ValueError("cbor truncated")
                if data[offset] == 0xFF:
                    offset += 1
                    break
                part, offset = _cbor_decode_one(data, offset)
                if major == 2:
                    if not isinstance(part, (bytes, bytearray)):
                        raise ValueError("invalid cbor chunk")
                    chunks.append(bytes(part))
                else:
                    if not isinstance(part, str):
                        raise ValueError("invalid cbor chunk")
                    chunks.append(part.encode("utf-8"))
            raw = b"".join(chunks)
            return (raw if major == 2 else raw.decode("utf-8", errors="replace")), offset
        raw = data[offset:offset + length]
        offset += length
        return (bytes(raw) if major == 2 else raw.decode("utf-8", errors="replace")), offset
    if major == 4:
        length, offset = _cbor_read_length(data, offset, ai)
        items = []
        if length is None:
            while True:
                if offset >= len(data):
                    raise ValueError("cbor truncated")
                if data[offset] == 0xFF:
                    offset += 1
                    break
                item, offset = _cbor_decode_one(data, offset)
                items.append(item)
        else:
            for _ in range(length):
                item, offset = _cbor_decode_one(data, offset)
                items.append(item)
        return items, offset
    if major == 5:
        length, offset = _cbor_read_length(data, offset, ai)
        items = {}
        if length is None:
            while True:
                if offset >= len(data):
                    raise ValueError("cbor truncated")
                if data[offset] == 0xFF:
                    offset += 1
                    break
                key, offset = _cbor_decode_one(data, offset)
                val, offset = _cbor_decode_one(data, offset)
                items[key] = val
        else:
            for _ in range(length):
                key, offset = _cbor_decode_one(data, offset)
                val, offset = _cbor_decode_one(data, offset)
                items[key] = val
        return items, offset
    if major == 6:
        _tag, offset = _cbor_read_length(data, offset, ai)
        return _cbor_decode_one(data, offset)
    if major == 7:
        if ai == 20:
            return False, offset
        if ai == 21:
            return True, offset
        if ai in (22, 23):
            return None, offset
        if ai == 24:
            return data[offset], offset + 1
        if ai == 25:
            raw = int.from_bytes(data[offset:offset + 2], "big")
            offset += 2
            sign = (raw >> 15) & 1
            exp = (raw >> 10) & 0x1F
            frac = raw & 0x3FF
            val = (1 if sign == 0 else -1) * (2 ** (exp - 15)) * (1 + frac / 1024.0)
            return val, offset
        if ai == 26:
            return struct.unpack(">f", data[offset:offset + 4])[0], offset + 4
        if ai == 27:
            return struct.unpack(">d", data[offset:offset + 8])[0], offset + 8
        if ai == 31:
            return _CBOR_BREAK, offset
    raise ValueError("unsupported cbor type")

def _cbor_loads(data: bytes):
    value, offset = _cbor_decode_one(bytes(data or b""))
    if offset != len(data):
        raise ValueError("cbor trailing data")
    return value

def _webauthn_decode_json(data: bytes | str | None) -> dict:
    raw = data.decode("utf-8", errors="replace") if isinstance(data, (bytes, bytearray)) else str(data or "")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("client data must be object")
    return parsed

def _webauthn_public_key_coords(public_key) -> tuple[int, int]:
    if not isinstance(public_key, dict):
        raise ValueError("public key missing")
    x_raw = public_key.get("x")
    y_raw = public_key.get("y")
    if not x_raw or not y_raw:
        raise ValueError("public key missing coordinates")
    def _decode_coord(raw):
        text = str(raw or "").strip()
        if not text:
            raise ValueError("empty coordinate")
        if re.fullmatch(r"[0-9a-fA-F]{64}", text):
            return int.from_bytes(bytes.fromhex(text), "big")
        buf = _webauthn_b64u_decode(text)
        if len(buf) != 32:
            raise ValueError("invalid coordinate length")
        return int.from_bytes(buf, "big")
    return _decode_coord(x_raw), _decode_coord(y_raw)

_P256_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_P256_A = (_P256_P - 3) % _P256_P
_P256_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_P256_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_P256_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
_P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_P256_G = (_P256_GX, _P256_GY)

def _p256_on_curve(point: tuple[int, int] | None) -> bool:
    if point is None:
        return True
    x, y = point
    if not (0 <= x < _P256_P and 0 <= y < _P256_P):
        return False
    return (y * y - (x * x * x + _P256_A * x + _P256_B)) % _P256_P == 0

def _p256_point_add(p: tuple[int, int] | None, q: tuple[int, int] | None) -> tuple[int, int] | None:
    if p is None:
        return q
    if q is None:
        return p
    x1, y1 = p
    x2, y2 = q
    if x1 == x2:
        if (y1 + y2) % _P256_P == 0:
            return None
        slope = ((3 * x1 * x1 + _P256_A) * pow(2 * y1, -1, _P256_P)) % _P256_P
    else:
        slope = ((y2 - y1) * pow((x2 - x1) % _P256_P, -1, _P256_P)) % _P256_P
    x3 = (slope * slope - x1 - x2) % _P256_P
    y3 = (slope * (x1 - x3) - y1) % _P256_P
    return x3, y3

def _p256_point_mul(k: int, point: tuple[int, int] | None) -> tuple[int, int] | None:
    if point is None:
        return None
    if k % _P256_N == 0:
        return None
    result = None
    addend = point
    n = k % _P256_N
    while n:
        if n & 1:
            result = _p256_point_add(result, addend)
        addend = _p256_point_add(addend, addend)
        n >>= 1
    return result

def _ecdsa_parse_der_signature(sig: bytes) -> tuple[int, int]:
    raw = bytes(sig or b"")
    if len(raw) < 8 or raw[0] != 0x30:
        raise ValueError("invalid signature")
    total_len = raw[1]
    idx = 2
    if total_len & 0x80:
        n_len = total_len & 0x7F
        total_len = int.from_bytes(raw[idx:idx + n_len], "big")
        idx += n_len
    if idx + total_len > len(raw):
        raise ValueError("invalid signature length")
    def read_int() -> int:
        nonlocal idx
        if idx >= len(raw) or raw[idx] != 0x02:
            raise ValueError("invalid signature integer")
        idx += 1
        if idx >= len(raw):
            raise ValueError("invalid signature integer length")
        ln = raw[idx]
        idx += 1
        if ln & 0x80:
            n_len = ln & 0x7F
            ln = int.from_bytes(raw[idx:idx + n_len], "big")
            idx += n_len
        val = int.from_bytes(raw[idx:idx + ln], "big")
        idx += ln
        return val
    r = read_int()
    s = read_int()
    return r, s

def _ecdsa_verify_p256(public_key: dict, message_hash: bytes, signature: bytes) -> bool:
    try:
        x, y = _webauthn_public_key_coords(public_key)
    except Exception:
        return False
    if not _p256_on_curve((x, y)):
        return False
    try:
        r, s = _ecdsa_parse_der_signature(signature)
    except Exception:
        return False
    if not (1 <= r < _P256_N and 1 <= s < _P256_N):
        return False
    e = int.from_bytes(bytes(message_hash or b""), "big")
    w = pow(s, -1, _P256_N)
    u1 = (e * w) % _P256_N
    u2 = (r * w) % _P256_N
    p = _p256_point_add(_p256_point_mul(u1, _P256_G), _p256_point_mul(u2, (x, y)))
    if p is None:
        return False
    return (p[0] % _P256_N) == r

def _webauthn_parse_attestation_object(raw: bytes) -> dict:
    obj = _cbor_loads(bytes(raw or b""))
    if not isinstance(obj, dict):
        raise ValueError("attestation object must be map")
    fmt = str(obj.get("fmt") or "").strip().lower()
    auth_data = obj.get("authData")
    if fmt != "none":
        raise ValueError("only none attestation is supported")
    if not isinstance(auth_data, (bytes, bytearray)) or len(auth_data) < 37:
        raise ValueError("authData missing")
    auth = bytes(auth_data)
    rp_id_hash = auth[:32]
    flags = auth[32]
    sign_count = int.from_bytes(auth[33:37], "big")
    offset = 37
    if not (flags & 0x40):
        raise ValueError("credential data missing")
    if offset + 16 + 2 > len(auth):
        raise ValueError("credential data truncated")
    aaguid = auth[offset:offset + 16]
    offset += 16
    cred_len = int.from_bytes(auth[offset:offset + 2], "big")
    offset += 2
    if offset + cred_len > len(auth):
        raise ValueError("credential id truncated")
    cred_id = auth[offset:offset + cred_len]
    offset += cred_len
    public_key, offset = _cbor_decode_one(auth, offset)
    if offset > len(auth):
        raise ValueError("public key truncated")
    if not isinstance(public_key, dict):
        raise ValueError("public key missing")
    cose_kty = public_key.get(1)
    cose_alg = public_key.get(3)
    cose_crv = public_key.get(-1)
    x = public_key.get(-2)
    y = public_key.get(-3)
    if cose_kty != 2 or cose_alg != -7 or cose_crv != 1 or not x or not y:
        raise ValueError("unsupported credential public key")
    return {
        "auth_data": auth,
        "rp_id_hash": rp_id_hash,
        "flags": flags,
        "credential_id": bytes(cred_id),
        "sign_count": sign_count,
        "public_key": {
            "kty": "EC",
            "crv": "P-256",
            "x": _webauthn_b64u_encode(bytes(x) if isinstance(x, (bytes, bytearray)) else b""),
            "y": _webauthn_b64u_encode(bytes(y) if isinstance(y, (bytes, bytearray)) else b""),
        },
        "aaguid": _webauthn_b64u_encode(aaguid),
    }

# -----------------------------------------------------------------------------
# WebAuthn / passkey helpers
# -----------------------------------------------------------------------------
def _auth_passkeys_public(auth_cfg: dict | None = None) -> list[dict]:
    source = auth_cfg if isinstance(auth_cfg, dict) else AUTH_CFG
    out: list[dict] = []
    for item in _normalize_passkeys(source.get("passkeys")):
        out.append({
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "enabled": bool(item.get("enabled", True)),
            "created_ts": float(item.get("created_ts") or 0.0),
            "last_used_ts": float(item.get("last_used_ts") or 0.0),
            "sign_count": int(item.get("sign_count") or 0),
        })
    return out

def _passkey_timeout_ms() -> int:
    return int(PASSKEY_CHALLENGE_TTL_SEC * 1000)

def _auth_mutate_passkeys(mutator, *, tag: str = "passkey") -> tuple[bool, str, list[dict]]:
    if not APP_CONFIG_PATH:
        return False, "config path missing", _auth_passkeys_public()
    try:
        with auth_passkey_lock:
            cfg = load_app_config(APP_CONFIG_PATH)
            auth = cfg.setdefault("auth", {})
            if not isinstance(auth, dict):
                auth = {}
                cfg["auth"] = auth
            items = _normalize_passkeys(auth.get("passkeys"))
            auth["passkeys"] = _normalize_passkeys(mutator(list(items)))
            # Passkey changes must stay aligned with the saved config and the
            # in-memory auth runtime, so save + reload are handled as one flow.
            cfg, guard_err = _prepare_security_cfg_for_save(cfg)
            if guard_err:
                return False, guard_err, _auth_passkeys_public()
            b_ok, backup_path = create_config_backup(APP_CONFIG_PATH, tag=tag)
            if not b_ok:
                return False, f"backup failed: {backup_path}", _auth_passkeys_public()
            ok, msg = save_app_config(APP_CONFIG_PATH, cfg)
            if not ok:
                return False, msg, _auth_passkeys_public()
            cfg_loaded = load_app_config(APP_CONFIG_PATH)
            r_ok, r_msg = reload_runtime_config(cfg_loaded)
            if not r_ok:
                return False, f"reload failed: {r_msg}", _auth_passkeys_public()
            auth_loaded = cfg_loaded.get("auth") if isinstance(cfg_loaded, dict) else None
            return True, "ok", _auth_passkeys_public(auth_loaded if isinstance(auth_loaded, dict) else None)
    except Exception as e:
        return False, str(e), _auth_passkeys_public()

def _passkey_cleanup(now_wall: float | None = None) -> None:
    now_wall = float(now_wall or time.time())
    with passkey_challenge_lock:
        stale = [k for k, v in passkey_challenges.items() if float((v or {}).get("expires_at") or 0.0) <= now_wall]
        for key in stale:
            passkey_challenges.pop(key, None)

def _passkey_challenge_new(kind: str, data: dict | None = None, *, ttl_sec: int = PASSKEY_CHALLENGE_TTL_SEC) -> dict:
    now_wall = time.time()
    token = secrets.token_urlsafe(24)
    row = dict(data or {})
    row.update({
        "kind": kind,
        "challenge": token,
        "created_ts": now_wall,
        "expires_at": now_wall + max(60, int(ttl_sec or PASSKEY_CHALLENGE_TTL_SEC)),
    })
    with passkey_challenge_lock:
        passkey_challenges[token] = row
        if len(passkey_challenges) > 1024:
            _passkey_cleanup(now_wall=now_wall)
    return row

def _passkey_challenge_take(token: str | None, kind: str | None = None) -> dict | None:
    raw = str(token or "").strip()
    if not raw:
        return None
    now_wall = time.time()
    with passkey_challenge_lock:
        row = passkey_challenges.pop(raw, None)
    if not isinstance(row, dict):
        return None
    if float(row.get("expires_at") or 0.0) <= now_wall:
        return None
    if kind and str(row.get("kind") or "") != kind:
        return None
    return row

def _passkey_options_public(passkeys: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in passkeys:
        cred_id = str(item.get("id") or "").strip()
        if not cred_id or not bool(item.get("enabled", True)):
            continue
        out.append({
            "type": "public-key",
            "id": cred_id,
            "transports": ["internal", "hybrid", "usb", "nfc", "ble"],
        })
    return out

def _passkey_record_payload(passkey_name: str | None = None) -> str:
    name = str(passkey_name or "").strip()
    if name:
        return name[:80]
    return "PassKey " + time.strftime("%Y-%m-%d %H:%M:%S")

def _passkey_login_begin(headers) -> dict:
    if not _auth_enabled() or not _auth_hashes_present(AUTH_CFG):
        return {"ok": False, "error": "未配置登录账号"}
    if not _auth_login_method_enabled("passkey"):
        return {"ok": False, "error": "PassKey 登录已关闭"}
    items = [item for item in _normalize_passkeys(AUTH_CFG.get("passkeys")) if bool(item.get("enabled", True))]
    if not items:
        return {"ok": False, "error": "暂无可用的通行密钥"}
    rp_id = _webauthn_rp_id_from_headers(headers)
    origin = _webauthn_origin_from_headers(headers)
    row = _passkey_challenge_new("login", {
        "rp_id": rp_id,
        "origin": origin,
        "allow_credentials": [str(item.get("id") or "") for item in items],
    })
    return {
        "ok": True,
        "challenge": row["challenge"],
        "challenge_token": row["challenge"],
        "rp_id": rp_id,
        "origin": origin,
        "timeout_ms": _passkey_timeout_ms(),
        "allow_credentials": _passkey_options_public(items),
        "passkeys": _auth_passkeys_public(),
        "realm": str(AUTH_CFG.get("realm") or "XRS"),
    }

def _passkey_register_begin(body: dict | None, headers, *, client_ip: str | None = None) -> dict:
    if not _auth_enabled() or not _auth_hashes_present(AUTH_CFG):
        return {"ok": False, "error": "未配置登录账号"}, 400
    if not _auth_login_method_enabled("passkey"):
        return {"ok": False, "error": "PassKey 登录已关闭"}, 403
    src = body if isinstance(body, dict) else {}
    user = str(src.get("username") or "").strip()
    pwd = str(src.get("password") or "")
    if not user or not pwd:
        return {"ok": False, "error": "请同时提供账号和密码"}, 400
    if not _auth_check_userpass(user, pwd):
        _op_log("passkey-register", "start auth failed", actor=user or "-", ip=str(client_ip or "-"), ok=False)
        return {"ok": False, "error": "用户名或密码错误"}, 401
    rp_id = _webauthn_rp_id_from_headers(headers)
    origin = _webauthn_origin_from_headers(headers)
    realm = str(AUTH_CFG.get("realm") or "XRS")
    passkey_name = _passkey_record_payload(src.get("name") or src.get("label"))
    row = _passkey_challenge_new("register", {
        "rp_id": rp_id,
        "origin": origin,
        "passkey_name": passkey_name,
        "user_handle": _webauthn_b64u_encode(_webauthn_user_handle()),
    })
    return {
        "ok": True,
        "challenge": row["challenge"],
        "challenge_token": row["challenge"],
        "rp_id": rp_id,
        "origin": origin,
        "timeout_ms": _passkey_timeout_ms(),
        "publicKey": {
            "challenge": row["challenge"],
            "rp": {"name": realm, "id": rp_id},
            "user": {
                "id": _webauthn_b64u_encode(_webauthn_user_handle()),
                "name": user,
                "displayName": passkey_name,
            },
            "pubKeyCredParams": [{"type": "public-key", "alg": -7}],
            "timeout": _passkey_timeout_ms(),
            "attestation": "none",
            "authenticatorSelection": {
                "userVerification": "preferred",
                "residentKey": "preferred",
            },
            "excludeCredentials": _passkey_options_public(_normalize_passkeys(AUTH_CFG.get("passkeys"))),
        },
        "passkey_name": passkey_name,
        "realm": realm,
    }

def _passkey_finish_register(body: dict | None, headers, *, client_ip: str | None = None) -> dict:
    if not _auth_login_method_enabled("passkey"):
        return {"ok": False, "error": "PassKey 登录已关闭"}, 403
    src = body if isinstance(body, dict) else {}
    token = str(src.get("challenge") or src.get("challenge_token") or "").strip()
    row = _passkey_challenge_take(token, "register")
    if not row:
        return {"ok": False, "error": "challenge expired"}, 400
    expected_origin = str(row.get("origin") or "")
    expected_rp_id = str(row.get("rp_id") or "")
    response = src.get("response") if isinstance(src.get("response"), dict) else {}
    try:
        # Registration accepts a new credential only after challenge, origin,
        # and rpId validation succeed against the stored single-use challenge.
        client_data_raw = _webauthn_b64u_decode(str(response.get("clientDataJSON") or ""))
        client_data = _webauthn_decode_json(client_data_raw)
        if str(client_data.get("type") or "") != "webauthn.create":
            raise ValueError("invalid client data type")
        if str(client_data.get("challenge") or "") != token:
            raise ValueError("challenge mismatch")
        if str(client_data.get("origin") or "") != expected_origin:
            raise ValueError("origin mismatch")
        att_obj = _webauthn_parse_attestation_object(_webauthn_b64u_decode(str(response.get("attestationObject") or "")))
        cred_id = bytes(att_obj.get("credential_id") or b"")
        if not cred_id:
            raise ValueError("credential id missing")
        if str(expected_rp_id) and hashlib.sha256(expected_rp_id.encode("utf-8", errors="ignore")).digest() != bytes(att_obj.get("rp_id_hash") or b""):
            raise ValueError("rpId mismatch")
        passkey_name = str(src.get("name") or row.get("passkey_name") or "通行密钥").strip() or "通行密钥"
        cred_id_text = _webauthn_b64u_encode(cred_id)
        public_key = att_obj.get("public_key") if isinstance(att_obj.get("public_key"), dict) else {}
        sign_count = int(att_obj.get("sign_count") or 0)
    except Exception as e:
        _op_log("passkey-register", f"finish error={e}", actor=str(src.get("username") or "-"), ip=str(client_ip or "-"), ok=False)
        return {"ok": False, "error": str(e)}, 400
    def _add_passkey(items):
        items = [dict(item or {}) for item in items]
        items = [item for item in items if str(item.get("id") or "") != cred_id_text]
        items.append({
            "id": cred_id_text,
            "name": passkey_name,
            "user_handle": str(row.get("user_handle") or ""),
            "public_key": public_key,
            "sign_count": sign_count,
            "created_ts": time.time(),
            "last_used_ts": 0.0,
            "enabled": True,
        })
        return items[-32:]
    ok, msg, passkeys = _auth_mutate_passkeys(_add_passkey, tag="passkey_create")
    if not ok:
        return {"ok": False, "error": msg, "passkeys": passkeys}, 500
    _op_log("passkey-register", f"ok name={passkey_name}", actor=str(src.get("username") or "-"), ip=str(client_ip or "-"), ok=True)
    return {"ok": True, "passkeys": passkeys, "passkey_name": passkey_name}, 200

def _passkey_finish_login(body: dict | None, headers, *, client_ip: str | None = None) -> dict:
    if not _auth_enabled() or not _auth_hashes_present(AUTH_CFG):
        return {"ok": False, "error": "未配置登录账号"}, 400
    if not _auth_login_method_enabled("passkey"):
        return {"ok": False, "error": "PassKey 登录已关闭"}, 403
    src = body if isinstance(body, dict) else {}
    token = str(src.get("challenge") or src.get("challenge_token") or "").strip()
    row = _passkey_challenge_take(token, "login")
    if not row:
        return {"ok": False, "error": "challenge expired"}, 400
    expected_origin = str(row.get("origin") or "")
    expected_rp_id = str(row.get("rp_id") or "")
    response = src.get("response") if isinstance(src.get("response"), dict) else {}
    cred_id = str(src.get("id") or src.get("rawId") or "").strip()
    if not cred_id:
        return {"ok": False, "error": "credential id required"}, 400
    passkey_row = None
    for item in _normalize_passkeys(AUTH_CFG.get("passkeys")):
        if str(item.get("id") or "") == cred_id and bool(item.get("enabled", True)):
            passkey_row = dict(item)
            break
    if not passkey_row:
        return {"ok": False, "error": "unknown passkey"}, 401
    try:
        # Login verification stays fully local: validate challenge/origin/rpId,
        # then verify the signature against the stored credential public key.
        client_data_raw = _webauthn_b64u_decode(str(response.get("clientDataJSON") or ""))
        client_data = _webauthn_decode_json(client_data_raw)
        if str(client_data.get("type") or "") != "webauthn.get":
            raise ValueError("invalid client data type")
        if str(client_data.get("challenge") or "") != token:
            raise ValueError("challenge mismatch")
        if str(client_data.get("origin") or "") != expected_origin:
            raise ValueError("origin mismatch")
        auth_data = _webauthn_b64u_decode(str(response.get("authenticatorData") or ""))
        signature = _webauthn_b64u_decode(str(response.get("signature") or ""))
        if len(auth_data) < 37 or not signature:
            raise ValueError("invalid assertion response")
        if expected_rp_id and hashlib.sha256(expected_rp_id.encode("utf-8", errors="ignore")).digest() != auth_data[:32]:
            raise ValueError("rpId mismatch")
        flags = auth_data[32]
        if not (flags & 0x01):
            raise ValueError("user presence required")
        message_hash = hashlib.sha256(auth_data + hashlib.sha256(client_data_raw).digest()).digest()
        if not _ecdsa_verify_p256(passkey_row.get("public_key") or {}, message_hash, signature):
            raise ValueError("signature mismatch")
        sign_count = int.from_bytes(auth_data[33:37], "big")
    except Exception as e:
        _op_log("passkey-login", f"finish error={e}", actor=str(passkey_row.get("name") or "-"), ip=str(client_ip or "-"), ok=False)
        return {"ok": False, "error": str(e)}, 401
    def _touch_passkey(items):
        now_wall = time.time()
        out = []
        for item in items:
            row_item = dict(item or {})
            if str(row_item.get("id") or "") == cred_id:
                row_item["last_used_ts"] = now_wall
                if sign_count > int(row_item.get("sign_count") or 0):
                    row_item["sign_count"] = sign_count
            out.append(row_item)
        return out
    ok, _msg, _ = _auth_mutate_passkeys(_touch_passkey, tag="passkey_use")
    if not ok:
        _log("[WARN] passkey usage update failed: " + str(_msg))
    self_tok = _auth_issue_session()
    _op_log("passkey-login", "login ok", actor=str(passkey_row.get("name") or "-"), ip=str(client_ip or "-"), ok=True)
    return {"ok": True, "next": str(src.get("next") or "/") or "/", "session": self_tok}, 200
