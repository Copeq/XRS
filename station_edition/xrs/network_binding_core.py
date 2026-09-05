from __future__ import annotations

# This chunk keeps NIC binding, hotspot, and lightweight DHCP support out of
# the larger web/runtime chunks while sharing their assembled namespace.

NETWORK_BINDING_ROLES = ("none", "scan", "web", "ap_web", "disabled", "idle")
NETWORK_BINDING_ROLE_LABELS = {
    "none": "None",
    "scan": "扫描",
    "web": "网页服务",
    "ap_web": "AP热点网页服务",
    "disabled": "禁用",
    "idle": "闲置",
}
AP_WEB_ADDRESS_DEFAULT = "172.16.0.1"
AP_WEB_CIDR_DEFAULT = "172.16.0.1/24"
AP_WEB_DHCP_START_DEFAULT = "172.16.0.20"
AP_WEB_DHCP_END_DEFAULT = "172.16.0.240"
AP_WEB_HTTP_PORT_DEFAULT = 80

NETWORK_BINDINGS_CFG: dict = {
    "items": [],
    "ap": {
        "ssid": "XRS-HotSpot",
        "password": "",
        "channel": 6,
        "address": AP_WEB_ADDRESS_DEFAULT,
        "cidr": AP_WEB_CIDR_DEFAULT,
        "dhcp_start": AP_WEB_DHCP_START_DEFAULT,
        "dhcp_end": AP_WEB_DHCP_END_DEFAULT,
        "http_port": AP_WEB_HTTP_PORT_DEFAULT,
        "internet_enabled": False,
        "uplink_iface": "",
    },
}
network_binding_lock = Lock()
network_binding_runtime: dict = {
    "http_servers": {},
    "dhcp_threads": {},
    "dns_threads": {},
    "hostapd": {},
    "last_apply": {},
}


def _network_role_key(value: str | None) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    alias = {
        "": "none",
        "null": "none",
        "none": "none",
        "scan": "scan",
        "scanner": "scan",
        "capture": "scan",
        "web": "web",
        "http": "web",
        "lan_web": "web",
        "ap": "ap_web",
        "apweb": "ap_web",
        "ap_web": "ap_web",
        "hotspot": "ap_web",
        "hotspot_web": "ap_web",
        "disabled": "disabled",
        "disable": "disabled",
        "down": "disabled",
        "idle": "idle",
        "unused": "idle",
    }
    return alias.get(raw, "none")


def _network_safe_iface_name(iface: str | None) -> str | None:
    name = str(iface or "").strip()
    if not name:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,32}", name):
        return None
    return name


def _network_ap_defaults() -> dict:
    return dict(NETWORK_BINDINGS_CFG.get("ap") or {})


def _normalize_network_bindings_cfg(cfg: dict | None) -> dict:
    raw_root = cfg.get("network_bindings") if isinstance(cfg, dict) else {}
    raw_root = raw_root if isinstance(raw_root, dict) else {}
    raw_items = raw_root.get("items") if isinstance(raw_root.get("items"), list) else []
    preferred = _cfg_preferred_iface_from_cfg(cfg)
    seen: set[str] = set()
    items: list[dict] = []
    scan_seen = False
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        safe_iface = _network_safe_iface_name(str(item.get("iface") or "").strip())
        if not safe_iface or safe_iface in seen:
            continue
        role = _network_role_key(item.get("role"))
        if role == "scan":
            scan_seen = True
        seen.add(safe_iface)
        items.append({"iface": safe_iface, "role": role})
    if preferred and preferred not in seen:
        items.insert(0, {"iface": preferred, "role": "scan"})
        scan_seen = True
    if preferred and not scan_seen:
        for item in items:
            if item.get("iface") == preferred:
                item["role"] = "scan"
                scan_seen = True
                break
    ap = _network_ap_defaults()
    raw_ap = raw_root.get("ap") if isinstance(raw_root.get("ap"), dict) else {}
    for k in ("ssid", "password", "address", "cidr", "dhcp_start", "dhcp_end"):
        if k in raw_ap:
            ap[k] = str(raw_ap.get(k) or "").strip()
    uplink = _network_safe_iface_name(raw_ap.get("uplink_iface")) if "uplink_iface" in raw_ap else None
    ap["uplink_iface"] = uplink or ""
    ap["internet_enabled"] = bool(raw_ap.get("internet_enabled"))
    try:
        ap["channel"] = max(1, min(196, int(raw_ap.get("channel") if "channel" in raw_ap else ap.get("channel", 6))))
    except Exception:
        ap["channel"] = 6
    try:
        ap["http_port"] = max(1, min(65535, int(raw_ap.get("http_port") if "http_port" in raw_ap else ap.get("http_port", AP_WEB_HTTP_PORT_DEFAULT))))
    except Exception:
        ap["http_port"] = AP_WEB_HTTP_PORT_DEFAULT
    if not ap.get("ssid"):
        ap["ssid"] = "XRS-HotSpot"
    if not ap.get("address"):
        ap["address"] = AP_WEB_ADDRESS_DEFAULT
    if not ap.get("cidr"):
        ap["cidr"] = AP_WEB_CIDR_DEFAULT
    if not ap.get("dhcp_start"):
        ap["dhcp_start"] = AP_WEB_DHCP_START_DEFAULT
    if not ap.get("dhcp_end"):
        ap["dhcp_end"] = AP_WEB_DHCP_END_DEFAULT
    if not ap.get("uplink_iface"):
        ap["internet_enabled"] = False
    return {"items": items, "ap": ap}


def init_network_bindings_from_config(cfg: dict | None) -> None:
    global NETWORK_BINDINGS_CFG
    NETWORK_BINDINGS_CFG = _normalize_network_bindings_cfg(cfg)


def _network_binding_scan_iface(cfg: dict | None) -> str | None:
    norm = _normalize_network_bindings_cfg(cfg)
    for item in norm.get("items") or []:
        if item.get("role") == "scan" and item.get("iface"):
            return str(item.get("iface"))
    return _cfg_preferred_iface_from_cfg(cfg)


def _network_bindings_visual_payload(cfg: dict | None = None) -> dict:
    norm = _normalize_network_bindings_cfg(cfg if isinstance(cfg, dict) else APP_CONFIG)
    return {
        "items": list(norm.get("items") or []),
        "ap": dict(norm.get("ap") or {}),
        "roles": [
            {"key": key, "label": NETWORK_BINDING_ROLE_LABELS.get(key, key)}
            for key in NETWORK_BINDING_ROLES
        ],
        "runtime": _network_bindings_runtime_payload(),
    }


def _network_bindings_runtime_payload() -> dict:
    with network_binding_lock:
        http = {
            str(k): {"running": bool(v.get("running")), "error": str(v.get("error") or "")}
            for k, v in (network_binding_runtime.get("http_servers") or {}).items()
            if isinstance(v, dict)
        }
        dhcp = {
            str(k): {"running": bool(v.get("running")), "error": str(v.get("error") or "")}
            for k, v in (network_binding_runtime.get("dhcp_threads") or {}).items()
            if isinstance(v, dict)
        }
        dns = {
            str(k): {"running": bool(v.get("running")), "error": str(v.get("error") or "")}
            for k, v in (network_binding_runtime.get("dns_threads") or {}).items()
            if isinstance(v, dict)
        }
        hostapd = {
            str(k): {"running": bool(v.get("running")), "error": str(v.get("error") or ""), "pid": v.get("pid")}
            for k, v in (network_binding_runtime.get("hostapd") or {}).items()
            if isinstance(v, dict)
        }
        last_apply = dict(network_binding_runtime.get("last_apply") or {})
    return {"http": http, "dhcp": dhcp, "dns": dns, "hostapd": hostapd, "last_apply": last_apply}


def _network_bindings_status_payload() -> dict:
    cfg = load_app_config(APP_CONFIG_PATH) if APP_CONFIG_PATH else APP_CONFIG
    return {
        "ok": True,
        "interfaces": _iface_options_snapshot(),
        "bindings": _network_bindings_visual_payload(cfg),
        "selected_iface": _network_binding_scan_iface(cfg),
    }


def _network_bindings_apply_visual(cfg: dict, payload: dict | None) -> tuple[dict, str | None]:
    p = payload if isinstance(payload, dict) else {}
    norm = _normalize_network_bindings_cfg({"network_bindings": p, "basic": cfg.get("basic") if isinstance(cfg, dict) else {}})
    ifaces_seen: set[str] = set()
    scan_ifaces: list[str] = []
    for item in list(norm.get("items") or []):
        iface = str(item.get("iface") or "").strip()
        role = _network_role_key(item.get("role"))
        if not iface or iface in ifaces_seen:
            continue
        ifaces_seen.add(iface)
        if role == "scan":
            scan_ifaces.append(iface)
    if len(scan_ifaces) > 1:
        return cfg, "只能设置一张网卡为扫描"
    basic = cfg.setdefault("basic", {})
    if not isinstance(basic, dict):
        basic = {}
        cfg["basic"] = basic
    if scan_ifaces:
        basic["iface"] = scan_ifaces[0]
    elif basic.get("iface"):
        norm["items"].insert(0, {"iface": str(basic.get("iface")), "role": "scan"})
    cfg["network_bindings"] = norm
    return cfg, None


def _network_bindings_save_payload(body: dict | None) -> dict:
    if not APP_CONFIG_PATH:
        return {"ok": False, "error": "config path missing"}
    payload = body.get("network_bindings") if isinstance(body, dict) else None
    if not isinstance(payload, dict):
        payload = body if isinstance(body, dict) else {}
    cfg = load_app_config(APP_CONFIG_PATH)
    cfg, err = _network_bindings_apply_visual(cfg, payload)
    if err:
        return {"ok": False, "error": err}
    b_ok, backup_path = create_config_backup(APP_CONFIG_PATH, tag="network-bindings")
    if not b_ok:
        return {"ok": False, "error": f"backup failed: {backup_path}"}
    ok, msg = save_app_config(APP_CONFIG_PATH, cfg)
    if not ok:
        return {"ok": False, "error": f"save failed: {msg}"}
    cfg_loaded = load_app_config(APP_CONFIG_PATH)
    r_ok, r_msg = reload_runtime_config(cfg_loaded)
    if not r_ok:
        return {"ok": False, "error": f"reload failed: {r_msg}", "backup_path": backup_path}
    return {"ok": True, "backup_path": backup_path, "reload_msg": r_msg, "bindings": _network_bindings_visual_payload(cfg_loaded)}


def _apply_network_bindings_os(cfg: dict, sudo_password: str | None = None) -> dict:
    norm = _normalize_network_bindings_cfg(cfg)
    steps: list[dict] = []
    ok_all = True
    ap = dict(norm.get("ap") or {})
    if not _is_linux_host():
        return {"ok": False, "error": "network binding apply is only supported on Linux", "steps": steps}
    if not (_is_root_user() or _sudo_available()):
        return {"ok": False, "error": "applying NIC roles requires root or sudo", "steps": steps}

    def step(label: str, args: list[str], optional: bool = False) -> bool:
        ok, out, rc = _run_privileged(args, timeout=20, sudo_password=sudo_password)
        steps.append({"label": label, "ok": ok, "returncode": rc, "output": out})
        return bool(ok or optional)

    for item in norm.get("items") or []:
        iface = str(item.get("iface") or "")
        role = _network_role_key(item.get("role"))
        if not iface:
            continue
        if role == "disabled":
            ok_all = step(f"disable {iface}", ["ip", "link", "set", iface, "down"]) and ok_all
        elif role == "ap_web":
            if _command_path("nmcli"):
                step(f"release {iface} from NetworkManager", ["nmcli", "device", "set", iface, "managed", "no"], optional=True)
            ok_all = step(f"stop {iface}", ["ip", "link", "set", iface, "down"]) and ok_all
            step(f"set {iface} AP type", ["iw", "dev", iface, "set", "type", "__ap"], optional=True)
            step(f"flush {iface} addresses", ["ip", "addr", "flush", "dev", iface], optional=True)
            ok_all = step(f"assign {iface} {ap.get('cidr')}", ["ip", "addr", "add", str(ap.get("cidr") or AP_WEB_CIDR_DEFAULT), "dev", iface]) and ok_all
            ok_all = step(f"start {iface}", ["ip", "link", "set", iface, "up"]) and ok_all
            hostapd_state = _start_hostapd(iface, ap)
            with network_binding_lock:
                network_binding_runtime.setdefault("hostapd", {})[iface] = hostapd_state
            if not hostapd_state.get("running"):
                ok_all = False
                steps.append({"label": f"start hostapd {iface}", "ok": False, "returncode": -1, "output": hostapd_state.get("error") or ""})
            if hostapd_state.get("running"):
                _start_dhcp_server(iface, ap)
                _start_dns_server(iface, ap)
                share_steps = _apply_ap_internet_sharing_steps(iface, ap, privileged=True, sudo_password=sudo_password)
                steps.extend(share_steps)
                if any(not bool(s.get("ok")) for s in share_steps):
                    ok_all = False
        elif role in ("web", "idle", "none"):
            step(f"ensure {iface} up", ["ip", "link", "set", iface, "up"], optional=True)
    with network_binding_lock:
        network_binding_runtime["last_apply"] = {
            "ok": bool(ok_all),
            "ts": time.time(),
            "steps": steps[-20:],
        }
    return {"ok": bool(ok_all), "steps": steps, "bindings": _network_bindings_visual_payload(cfg)}


def _network_bindings_apply_payload(body: dict | None) -> dict:
    cfg = load_app_config(APP_CONFIG_PATH) if APP_CONFIG_PATH else APP_CONFIG
    rsp = _apply_network_bindings_os(cfg, sudo_password=_sudo_password_from_body(body))
    rsp["runtime"] = _network_bindings_runtime_payload()
    if not rsp.get("ok") and not rsp.get("error"):
        rsp["error"] = "one or more network binding steps failed"
    return rsp


def start_bound_http_servers(server_cls, handler_cls) -> None:
    cfg = _normalize_network_bindings_cfg(APP_CONFIG)
    ap = dict(cfg.get("ap") or {})
    enabled = any(_network_role_key(item.get("role")) == "ap_web" for item in cfg.get("items") or [])
    if not enabled:
        return
    host = str(ap.get("address") or AP_WEB_ADDRESS_DEFAULT)
    port = int(ap.get("http_port") or AP_WEB_HTTP_PORT_DEFAULT)
    key = f"{host}:{port}"
    with network_binding_lock:
        current = (network_binding_runtime.get("http_servers") or {}).get(key)
        if isinstance(current, dict) and current.get("running"):
            return
    state = {"running": False, "error": "", "server": None}
    try:
        srv = server_cls((host, port), handler_cls)
        state.update({"running": True, "server": srv})
        with network_binding_lock:
            network_binding_runtime.setdefault("http_servers", {})[key] = state
        Thread(target=srv.serve_forever, daemon=True).start()
        _log(f"[INFO] AP HTTP service started: http://{host}:{port}/")
    except Exception as e:
        state["error"] = str(e)
        with network_binding_lock:
            network_binding_runtime.setdefault("http_servers", {})[key] = state
        _log(f"[WARN] AP HTTP service failed on {key}: {e}")


def start_network_binding_services() -> None:
    cfg = _normalize_network_bindings_cfg(APP_CONFIG)
    ap = dict(cfg.get("ap") or {})
    for item in cfg.get("items") or []:
        iface = str(item.get("iface") or "")
        if iface and _network_role_key(item.get("role")) == "ap_web":
            can_configure = _is_root_user() or _process_has_capabilities(("CAP_NET_ADMIN", "CAP_NET_RAW"))
            if can_configure:
                if _command_path("nmcli"):
                    _run_program(["nmcli", "device", "set", iface, "managed", "no"], timeout=10)
                for args in (
                    ["ip", "link", "set", iface, "down"],
                    ["iw", "dev", iface, "set", "type", "__ap"],
                    ["ip", "addr", "flush", "dev", iface],
                    ["ip", "addr", "add", str(ap.get("cidr") or AP_WEB_CIDR_DEFAULT), "dev", iface],
                    ["ip", "link", "set", iface, "up"],
                ):
                    _run_program(args, timeout=10)
                hostapd_state = _start_hostapd(iface, ap)
                with network_binding_lock:
                    network_binding_runtime.setdefault("hostapd", {})[iface] = hostapd_state
                if hostapd_state.get("running"):
                    _start_dhcp_server(iface, ap)
                    _start_dns_server(iface, ap)
                    share_steps = _apply_ap_internet_sharing_steps(iface, ap, privileged=False)
                    if share_steps and any(not bool(s.get("ok")) for s in share_steps):
                        bad = "; ".join(str(s.get("label") or "") + ": " + str(s.get("output") or "") for s in share_steps if not bool(s.get("ok")))
                        _log(f"[WARN] AP Internet sharing failed on {iface}: {bad}")
