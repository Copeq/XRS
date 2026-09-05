"""sniff iface core (extracted from hardware_core.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
Command/privilege helpers from hardware_core.py resolve at call time.
"""

def _sniff_note_packet() -> None:
    global sniff_last_pkt_mono, sniff_last_pkt_wall, sniff_last_error, sniff_last_error_wall
    now_mono = time.monotonic()
    now_wall = time.time()
    with sniff_health_lock:
        sniff_last_pkt_mono = now_mono
        sniff_last_pkt_wall = now_wall
        sniff_last_error = ""
        sniff_last_error_wall = 0.0

def _sniff_idle_sec(now_mono: float | None = None) -> float | None:
    now_mono = float(now_mono or time.monotonic())
    with sniff_health_lock:
        last = sniff_last_pkt_mono
    if not last:
        return None
    return max(0.0, now_mono - float(last))

def _sniff_note_error(msg: str) -> None:
    global sniff_last_error, sniff_last_error_wall
    text = str(msg or "").strip()
    if len(text) > 220:
        text = text[:220]
    with sniff_health_lock:
        sniff_last_error = text
        sniff_last_error_wall = time.time()

def _sniff_note_resume() -> None:
    """Reset stall tracking after an intentional real-simulation pause."""
    global sniff_last_pkt_mono, sniff_last_pkt_wall, sniff_last_error, sniff_last_error_wall
    with sniff_health_lock:
        sniff_last_pkt_mono = 0.0
        sniff_last_pkt_wall = 0.0
        sniff_last_error = ""
        sniff_last_error_wall = 0.0

def _sniff_health_meta(now_mono: float, now_wall: float) -> dict:
    with sniff_health_lock:
        last_pkt_mono = float(sniff_last_pkt_mono or 0.0)
        last_pkt_wall = float(sniff_last_pkt_wall or 0.0)
        last_err = str(sniff_last_error or "")
        last_err_wall = float(sniff_last_error_wall or 0.0)
        iface = str(sniff_iface_name or "")
    idle_sec = None
    if last_pkt_mono > 0.0:
        idle_sec = max(0.0, now_mono - last_pkt_mono)
    state = "ok"
    msg = ""
    if last_err:
        state = "error"
        msg = last_err
    elif idle_sec is None:
        state = "warn"
        msg = "尚未收到无线管理帧"
    elif idle_sec >= SNIFF_STALL_RECOVER_SEC:
        state = "warn"
        msg = f"{int(idle_sec)}s no wireless management frame"
    return {
        "state": state,
        "msg": msg,
        "iface": iface,
        "idle_sec": (None if idle_sec is None else int(round(idle_sec))),
        "last_pkt": _fmt_wall_ts(last_pkt_wall if last_pkt_wall > 0 else None),
        "last_err_at": _fmt_wall_ts(last_err_wall if last_err_wall > 0 else None),
    }

def _sniff_recover_iface(iface: str, reason: str, force: bool = False) -> bool:
    global sniff_last_recover_wall, sniff_iface_name
    iface = str(iface or "").strip()
    if not iface:
        _sniff_note_error(f"iface empty: {reason}")
        return False
    now_wall = time.time()
    with sniff_health_lock:
        if (not force) and sniff_last_recover_wall and (now_wall - sniff_last_recover_wall) < SNIFF_RECOVER_COOLDOWN_SEC:
            return False
        sniff_last_recover_wall = now_wall
        sniff_iface_name = iface
    _sniff_note_error(reason)
    _log(f"[WARN] sniff recover: {reason}, reset iface {iface}")
    steps = (
        (f"ip link set {iface} down", 0.15),
        (f"iw dev {iface} set type managed", 0.35),
        (f"ip link set {iface} up", 0.25),
        (f"ip link set {iface} down", 0.15),
        (f"iw dev {iface} set type monitor", 0.35),
        (f"ip link set {iface} up", 0.25),
        (f"iw dev {iface} set power_save off", 0.0),
    )
    for c, pause_sec in steps:
        run_cmd(c, timeout=6)
        if pause_sec > 0:
            time.sleep(pause_sec)
    if current_channel:
        run_cmd(f"iw dev {iface} set channel {current_channel}", timeout=6)
    info_raw = run_cmd(f"iw dev {iface} info")
    if not info_raw or ("Interface" not in info_raw):
        _sniff_note_error(f"iface unavailable: {iface}")
        return False
    info_lines = []
    for ln in info_raw.splitlines():
        t = ln.strip()
        if re.search(r"\b(type|channel)\b", t):
            info_lines.append(t)
    if info_lines:
        _log(f"[INFO] sniff recover result: {' | '.join(info_lines)}")
    with sniff_health_lock:
        sniff_iface_name = iface
    return True

def _sniff_close_socket(sock) -> None:
    if not sock:
        return
    try:
        sock.close()
    except Exception:
        pass

def _sniff_open_socket(iface: str):
    try:
        return conf.L2listen(iface=iface, monitor=True)
    except TypeError:
        return conf.L2listen(iface=iface)

def _sniff_run_once(iface: str, timeout_sec: float = SNIFF_POLL_TIMEOUT) -> tuple[str, str]:
    iface = str(iface or "").strip()
    if not iface:
        return "error", "iface empty"
    timeout_sec = max(1.0, float(timeout_sec or SNIFF_POLL_TIMEOUT))
    hard_deadline = time.monotonic() + timeout_sec + SNIFF_WORKER_HARD_GRACE_SEC
    result = {"error": "", "done": False}
    sock_ref = {"sock": None}

    def _worker() -> None:
        sock = None
        try:
            sock = _sniff_open_socket(iface)
            sock_ref["sock"] = sock
            sniff(opened_socket=sock, prn=parse_frame, store=False, timeout=timeout_sec)
        except Exception as ex:
            result["error"] = str(ex or "")
        finally:
            result["done"] = True
            if sock_ref.get("sock") is sock:
                sock_ref["sock"] = None
            _sniff_close_socket(sock)

    th = Thread(target=_worker, daemon=True)
    th.start()
    while th.is_alive():
        if time.monotonic() >= hard_deadline:
            _sniff_close_socket(sock_ref.get("sock"))
            th.join(SNIFF_WORKER_JOIN_GRACE_SEC)
            if th.is_alive():
                return "hung", f"worker exceeded {timeout_sec + SNIFF_WORKER_HARD_GRACE_SEC:.0f}s"
            return "hung", f"worker forced close after {timeout_sec + SNIFF_WORKER_HARD_GRACE_SEC:.0f}s"
        time.sleep(0.25)
    if result["error"]:
        return "error", result["error"]
    return "ok", ""

def _sniff_iface_candidates() -> dict[str, str]:
    iw = run_cmd("iw dev")
    iftypes: dict[str, str] = {}
    cur = None
    for line in (iw or "").splitlines():
        m = re.match(r"\s*Interface\s+(\S+)", line)
        if m:
            cur = m.group(1)
            continue
        m2 = re.match(r"\s*type\s+(\S+)", line)
        if m2 and cur:
            iftypes[cur] = m2.group(1)
    return iftypes

def _ip_json_snapshot(args: list[str]) -> dict:
    try:
        ok, out, _rc = _run_program(["ip", "-j"] + [str(x) for x in args], timeout=4)
        if not ok or not out:
            return {}
        data = json.loads(out)
        if not isinstance(data, list):
            return {}
        return {
            str(item.get("ifname") or ""): item
            for item in data
            if isinstance(item, dict) and str(item.get("ifname") or "")
        }
    except Exception:
        return {}

def _iface_sysfs_flags(name: str) -> int | None:
    try:
        with open(os.path.join("/sys/class/net", name, "flags"), "r", encoding="utf-8", errors="ignore") as f:
            return int(f.read().strip(), 16)
    except Exception:
        return None

def _iface_addr_lists(name: str, addr_item: dict | None = None) -> tuple[list[str], list[str]]:
    ipv4: list[str] = []
    ipv6: list[str] = []
    item = addr_item if isinstance(addr_item, dict) else {}
    for addr in item.get("addr_info") or []:
        if not isinstance(addr, dict):
            continue
        local = str(addr.get("local") or "").strip()
        prefix = addr.get("prefixlen")
        if not local:
            continue
        text = local + (f"/{prefix}" if prefix not in (None, "") else "")
        if str(addr.get("family") or "").lower() == "inet":
            ipv4.append(text)
        elif str(addr.get("family") or "").lower() == "inet6":
            ipv6.append(text)
    return ipv4, ipv6

def _sysfs_read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().strip()
    except Exception:
        return ""

def _iface_device_model(name: str) -> dict:
    out = {"model": "", "driver": "", "bus": "", "vendor_id": "", "product_id": ""}
    try:
        dev_path = os.path.realpath(os.path.join("/sys/class/net", name, "device"))
    except Exception:
        dev_path = ""
    if not dev_path or not os.path.exists(dev_path):
        return out
    try:
        driver_link = os.path.realpath(os.path.join(dev_path, "driver"))
        if driver_link and os.path.exists(driver_link):
            out["driver"] = os.path.basename(driver_link)
    except Exception:
        pass
    cur = dev_path
    for _ in range(8):
        vid = _sysfs_read_text(os.path.join(cur, "idVendor"))
        pid = _sysfs_read_text(os.path.join(cur, "idProduct"))
        if vid or pid:
            manufacturer = _sysfs_read_text(os.path.join(cur, "manufacturer"))
            product = _sysfs_read_text(os.path.join(cur, "product"))
            out.update({
                "bus": "usb",
                "vendor_id": vid.lower(),
                "product_id": pid.lower(),
                "model": " ".join(x for x in (manufacturer, product) if x) or f"USB {vid}:{pid}",
            })
            return out
        parent = os.path.dirname(cur)
        if not parent or parent == cur or parent == "/sys":
            break
        cur = parent
    modalias = _sysfs_read_text(os.path.join(dev_path, "modalias"))
    if modalias.startswith("pci:"):
        slot = os.path.basename(dev_path)
        ok, desc, _rc = _run_program(["lspci", "-D", "-s", slot], timeout=4)
        out["bus"] = "pci"
        if ok and desc:
            out["model"] = re.sub(r"^[0-9a-fA-F:.]+\\s+", "", desc.strip())
        else:
            out["vendor_id"] = _sysfs_read_text(os.path.join(dev_path, "vendor")).replace("0x", "").lower()
            out["product_id"] = _sysfs_read_text(os.path.join(dev_path, "device")).replace("0x", "").lower()
            if out["vendor_id"] or out["product_id"]:
                out["model"] = f"PCI {out['vendor_id']}:{out['product_id']}"
    return out

def _iface_detected_role(item: dict) -> str:
    if bool(item.get("is_loopback")):
        return "none"
    if item.get("admin_up") is False:
        return "disabled"
    mode = str(item.get("mode") or "").strip().lower()
    ipv4 = [str(x) for x in (item.get("ipv4") or [])]
    if mode in ("__ap", "ap"):
        return "ap_web"
    if any(x.startswith("172.16.0.1/") or x == "172.16.0.1" for x in ipv4):
        return "ap_web"
    if mode == "monitor":
        return "scan"
    if ipv4:
        return "web"
    if str(item.get("state") or "").strip().lower() in ("up", "unknown", "dormant"):
        return "idle"
    return "none"

def _iface_options_snapshot() -> list[dict]:
    iftypes = _sniff_iface_candidates()
    names: set[str] = set(iftypes.keys())
    link_json = _ip_json_snapshot(["-details", "link", "show"])
    addr_json = _ip_json_snapshot(["addr", "show"])
    names.update([x for x in link_json.keys() if x])
    names.update([x for x in addr_json.keys() if x])
    try:
        for name in os.listdir("/sys/class/net"):
            if name:
                names.add(str(name))
    except Exception:
        pass
    if not names:
        ip_out = run_cmd("ip -o link show", timeout=4)
        for line in (ip_out or "").splitlines():
            m = re.match(r"\d+:\s+([^:@]+)", line)
            if m:
                names.add(m.group(1))
    out: list[dict] = []
    for name in names:
        link_item = link_json.get(name) or {}
        addr_item = addr_json.get(name) or {}
        mode = iftypes.get(name, "")
        if not mode:
            linkinfo = link_item.get("linkinfo") if isinstance(link_item.get("linkinfo"), dict) else {}
            info_kind = str(linkinfo.get("info_kind") or "").strip()
            if info_kind:
                mode = info_kind
        try:
            supports_5g = bool(detect_5g(name))
        except Exception:
            supports_5g = False
        is_wireless = bool(mode)
        try:
            is_wireless = is_wireless or os.path.isdir(os.path.join("/sys/class/net", name, "wireless"))
        except Exception:
            pass
        mac = ""
        state = ""
        try:
            with open(os.path.join("/sys/class/net", name, "address"), "r", encoding="utf-8", errors="ignore") as f:
                mac = f.read().strip()
        except Exception:
            mac = ""
        try:
            with open(os.path.join("/sys/class/net", name, "operstate"), "r", encoding="utf-8", errors="ignore") as f:
                state = f.read().strip()
        except Exception:
            state = str(link_item.get("operstate") or "")
        flags_raw = _iface_sysfs_flags(name)
        flags = list(link_item.get("flags") or []) if isinstance(link_item.get("flags"), list) else []
        admin_up = None
        if flags_raw is not None:
            admin_up = bool(flags_raw & 0x1)
        elif flags:
            admin_up = "UP" in [str(x).upper() for x in flags]
        ipv4, ipv6 = _iface_addr_lists(name, addr_item)
        device = _iface_device_model(name)
        item = {
            "name": str(name),
            "mode": str(mode or ""),
            "is_monitor": (str(mode or "") == "monitor"),
            "is_wireless": bool(is_wireless),
            "is_loopback": str(name) == "lo",
            "state": state,
            "admin_up": admin_up,
            "flags": flags,
            "mac": mac,
            "ipv4": ipv4,
            "ipv6": ipv6,
            "supports_5g": supports_5g,
            "model": device.get("model") or "",
            "driver": device.get("driver") or "",
            "bus": device.get("bus") or "",
            "vendor_id": device.get("vendor_id") or "",
            "product_id": device.get("product_id") or "",
        }
        item["detected_role"] = _iface_detected_role(item)
        out.append(item)
    out.sort(key=lambda x: (
        1 if x.get("is_loopback") else 0,
        1 if x.get("detected_role") == "disabled" else 0,
        0 if x.get("is_wireless") else 1,
        0 if x.get("is_monitor") else 1,
        x.get("name") or "",
    ))
    return out

def _cfg_preferred_iface() -> str | None:
    return _cfg_preferred_iface_from_cfg(APP_CONFIG)

def _cfg_auto_self_heal() -> bool:
    try:
        basic = APP_CONFIG.get("basic") if isinstance(APP_CONFIG, dict) else {}
        if not isinstance(basic, dict):
            return True
        return bool(basic.get("auto_self_heal", True))
    except Exception:
        return True

def _sniff_pick_iface(prefer: str | None = None) -> str | None:
    iftypes = _sniff_iface_candidates()
    if not iftypes:
        return None
    if prefer and prefer in iftypes:
        return prefer
    if prefer:
        _sniff_note_error(f"配置的默认网卡未检测到: {prefer}")
        return None
    _sniff_note_error("未绑定默认网卡，请打开 OOBE 或设置页选择网卡")
    return None

def _sniff_is_no_device_error(ex: Exception) -> bool:
    s = str(ex or "")
    return (
        ("No such device" in s) or
        ("Errno 19" in s) or
        ("Network is down" in s) or
        ("Errno 100" in s)
    )

def _freq_to_ch(freq) -> int | None:
    try:
        f = int(freq)
    except Exception:
        return None
    if 2412 <= f <= 2484: return 14 if f==2484 else (f-2407)//5
    if 5000 <= f <= 5900: return (f-5000)//5
    return None

def _rt_channel(pkt) -> int | None:
    if not pkt.haslayer(RadioTap): return None
    rt = pkt[RadioTap]
    for attr in ("ChannelFrequency","ChannelFreq","channel_freq","Channel"):
        if hasattr(rt, attr):
            v = getattr(rt, attr)
            if isinstance(v, tuple) and v: v = v[0]
            if isinstance(v, (int,float)):
                ch = _freq_to_ch(int(v))
                if ch: return ch
    return None

def _ssid_to_sn(ssid: str) -> str | None:
    m = SSID_SN_RE.search(ssid) if ssid else None
    return m.group(1) if m else None

def interface_detect(prefer: str | None = None) -> str | None:
    iw      = run_cmd("iw dev")
    if not iw and not _command_path(IW_PACKAGE_NAME):
        snap = _iw_status_payload(refresh=True)
        msg = f"{snap.get('message') or _iw_missing_message()} {snap.get('manual_hint') or _iw_manual_install_hint()}"
        _log(f"[WARN] {msg}")
        _sniff_note_error(msg)
        _set_oobe_required(msg, True)
        return None
    iftypes: dict[str, str] = {}
    cur     = None
    for line in iw.splitlines():
        m = re.match(r"\s*Interface\s+(\S+)", line)
        if m: cur = m.group(1)
        m2 = re.match(r"\s*type\s+(\S+)", line)
        if m2 and cur: iftypes[cur] = m2.group(1)

    if not prefer:
        msg = "未绑定默认网卡，请进入 OOBE 或设置页选择固定网卡"
        _log(f"[WARN] {msg}")
        _sniff_note_error(msg)
        _set_oobe_required(msg, True)
        return None
    if prefer and prefer in iftypes:
        iface = prefer
    else:
        iface = None
    if not iface:
        msg = f"默认网卡未检测到: {prefer}" if iftypes else NO_IFACE_DEGRADE_HINT
        _log(f"[WARN] {msg}")
        _sniff_note_error(msg + "。请打开 OOBE 或设置页检查默认网卡。")
        _set_oobe_required(msg, True)
        return None

    mode = iftypes.get(iface, "unknown")
    _log(f"[INFO] iface={iface} mode={mode}")
    if mode != "monitor":
        _log("[INFO] switching to monitor mode...")
        for c in (f"ip link set {iface} down",
                  f"iw dev {iface} set type monitor",
                  f"ip link set {iface} up"):
            run_cmd(c)
        new = run_cmd(f"iw dev {iface} info | grep type").strip()
        _log(f"[INFO] monitor switch result: {new}")
    run_cmd(f"iw dev {iface} set power_save off")
    ch_info = run_cmd(f"iw dev {iface} info | grep channel").strip()
    _log(f"[INFO] current channel: {ch_info or 'unknown'}")
    return iface

def detect_5g(iface: str) -> bool:
    out = run_cmd(f"iw dev {iface} info")
    m   = re.search(r"\bwiphy\s+(\d+)", out)
    if not m: return False
    phy = run_cmd(f"iw phy{m.group(1)} info")
    if "Band 2:" in phy: return True
    return any(5000<=int(x)<=5999 for x in re.findall(r"\b(5\d{3})\s+MHz\b", phy))

# -----------------------------------------------------------------------------
# Channel hopper
# -----------------------------------------------------------------------------
def channel_hopper(iface, ch2g, ch5g, dw2, dw5, settle_ms, hit_ms, cap_ms):
    global current_channel
    dw2, dw5, settle = dw2/1000, dw5/1000, settle_ms/1000
    hit_until = 0.0
    lk = Lock()

    def note_hit():
        nonlocal hit_until
        now  = time.monotonic()
        ext  = max(0, hit_ms)/1000
        hold = max(0, cap_ms)/1000
        if ext <= 0: return
        with lk:
            cap = now+hold if hold>0 else now+ext
            hit_until = min(max(hit_until, now+ext), cap)

    globals()["_hopper_note_hit"] = note_hit

    def do_hold():
        with lk: u = hit_until
        rem = u - time.monotonic()
        if rem > 0: time.sleep(rem)

    while True:
        for ch in random.sample(ch2g, len(ch2g)):
            run_cmd(f"iw dev {iface} set channel {ch}")
            current_channel = ch
            if settle: time.sleep(settle)
            do_hold(); time.sleep(dw2)
        for ch in (random.sample(ch5g, len(ch5g)) if ch5g else []):
            run_cmd(f"iw dev {iface} set channel {ch}")
            current_channel = ch
            if settle: time.sleep(settle)
            do_hold(); time.sleep(dw5)
