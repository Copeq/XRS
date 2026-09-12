"""BLE Remote ID scanner core.

Passively picks up ASTM F3411 / GB 42590 broadcast Remote ID carried in BLE
advertising (Service Data with 16-bit UUID 0xFFFA) and feeds it into the shared
aircraft state table, complementing the Wi-Fi capture path. Every advertising
device seen is also kept in BLE_DEVICE_TABLE for the UI BLE panel.

Transport notes (why btmon):
- A direct HCI user-channel socket (scapy BluetoothUserSocket) needs a full
  controller init sequence and did not deliver advertising reports on the
  tested Realtek BT5.1 dongle, so we consume BlueZ's own HCI/MGMT text stream
  instead. `btmon` prints LE Advertising Reports and MGMT Device Found events,
  both of which carry the raw AD structures we need.
- BlueZ discovery (bluetoothctl "scan on") keeps scanning active; raw
  `hcitool lescan` is rejected with EIO while bluetoothd owns the controller.

Loaded into the assembled runtime namespace by runtime.py.
"""

BLE_RID_SERVICE_UUID16 = 0xFFFA
BLE_SERVICE_DATA_AD = 0x16
BLE_DEVICE_MAX = 200
BLE_DEVICE_KEEP = 120

BLE_SCAN_STATE: dict = {
    "enabled": False,
    "device": "",
    "state": "off",
    "msg": "",
    "reports": 0,
    "adv_seen": 0,
    "rid_hits": 0,
    "last_hit": "",
}

BLE_DEVICE_TABLE: dict = {}
_ble_device_state: dict = {"seq": 0}
_ble_device_lock = Lock()

_ble_scan_started = False
_ble_thread_lock = Lock()


def _ble_ad_structures(data: bytes) -> list:
    """Split a BLE AD structure blob into (ad_type, payload) pairs."""
    out: list = []
    buf = bytes(data or b"")
    i = 0
    while i < len(buf):
        ln = int(buf[i])
        if ln == 0:
            break
        end = i + 1 + ln
        if end > len(buf):
            break
        out.append((int(buf[i + 1]), bytes(buf[i + 2:end])))
        i = end
    return out


def _ble_rid_payloads_from_ad(data: bytes) -> list:
    """Extract ODID payloads from BLE Service Data entries with UUID 0xFFFA."""
    out: list = []
    for ad_type, payload in _ble_ad_structures(data):
        if ad_type != BLE_SERVICE_DATA_AD or len(payload) < 3:
            continue
        uuid16 = int(payload[0]) | (int(payload[1]) << 8)
        if uuid16 == BLE_RID_SERVICE_UUID16:
            out.append(bytes(payload[2:]))
    return out


def _ble_decoded_has_coord(decoded: dict) -> bool:
    loc = decoded.get("location") if isinstance(decoded.get("location"), dict) else None
    if loc and _coord_pair_valid(loc.get("lat"), loc.get("lon")):
        return True
    sys_loc = decoded.get("system") if isinstance(decoded.get("system"), dict) else None
    if sys_loc and _coord_pair_valid(sys_loc.get("pilot_lat"), sys_loc.get("pilot_lon")):
        return True
    return False


def _ble_process_payload(addr: str, rssi: int | None, payload: bytes) -> int:
    """Decode one BLE RID payload and merge it into the aircraft state table."""
    raw = bytes(payload or b"")
    if not raw:
        return 0
    packets: list = []
    try:
        parsed = parse_rid_payloads(raw, mode="auto")
        if isinstance(parsed, dict) and parsed.get("ok"):
            packets = list(parsed.get("packets") or [])
    except Exception:
        packets = []
    if not packets:
        try:
            decoded_fallback = decode_odid(raw)
            if isinstance(decoded_fallback, dict):
                packets = [{
                    "format": "BLE_ODID",
                    "sn": str(((decoded_fallback.get("basic_id") or {}).get("uas_id")) or ""),
                    "decoded": decoded_fallback,
                    "body_hex": raw.hex(),
                }]
        except Exception:
            packets = []
    handled = 0
    src_mac = "ble:" + (str(addr or "unknown").strip().lower() or "unknown")
    for parsed_packet in packets:
        if not isinstance(parsed_packet, dict):
            continue
        decoded = parsed_packet.get("decoded")
        if not isinstance(decoded, dict):
            decoded = rid_parse_result_to_decoded(parsed_packet)
        if not isinstance(decoded, dict):
            continue
        fmt = str(parsed_packet.get("format") or "")
        sn = str(parsed_packet.get("sn") or ((decoded.get("basic_id") or {}).get("uas_id") or "")).strip()
        if not sn and not _ble_decoded_has_coord(decoded):
            continue
        body_hex = str(parsed_packet.get("body_hex") or "") or raw.hex()
        try:
            sig = zlib.crc32(raw) & 0xFFFFFFFF
        except Exception:
            sig = 0
        try:
            state_update(
                src_mac,
                decoded,
                rssi=rssi,
                ch=0,
                ch_assumed=True,
                pl_sig=sig,
                scan_type="rid",
                ssid=None,
                capture_type="BLE",
                raw_pkt_hex=body_hex[:320],
                firmware_type=("new" if fmt == "GB46750_2025" else "old"),
            )
            handled += 1
        except Exception as ex:
            if DEBUG_MODE:
                _scan(f"[ERR] ble state_update: {ex}")
    return handled


_BLE_RECORD_HEAD_RE = re.compile(
    r"(LE (?:Extended )?Advertising Report|MGMT Event: Device Found)", re.IGNORECASE)
_BLE_ADDR_RE = re.compile(r"^\s*(?:LE )?Address:\s*([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})")
_BLE_RSSI_RE = re.compile(r"^\s*RSSI:\s*(-?\d+)\s*dBm")
_BLE_SVC_RE = re.compile(r"^\s*Service Data:.*?\(0x([0-9a-fA-F]{4})\)\s*$")
_BLE_DATA_RE = re.compile(r"^\s*Data\[(\d+)\]:\s*([0-9a-fA-F]*)\s*$")
_BLE_NAME_RE = re.compile(
    r"^\s*(?:Complete Local Name|Shortened Local Name|Local Name|"
    r"Name(?: \((?:complete|short)\))?):\s*(.+?)\s*$")


def _ble_touch_device(rec: dict) -> None:
    """Record/refresh one advertising device in BLE_DEVICE_TABLE."""
    addr = str(rec.get("addr") or "").strip().upper()
    if not addr:
        return
    now_wall = time.time()
    with _ble_device_lock:
        entry = BLE_DEVICE_TABLE.get(addr)
        if entry is None:
            entry = {
                "addr": addr, "name": "", "rssi": None, "kind": "BLE",
                "hits": 0, "is_rid": False, "ch": 0,
                "first_seen_wall_ts": now_wall, "last_seen_wall_ts": now_wall,
            }
            BLE_DEVICE_TABLE[addr] = entry
        name = str(rec.get("name") or "").strip()
        if name:
            entry["name"] = name
        if rec.get("rssi") is not None:
            entry["rssi"] = rec.get("rssi")
        if rec.get("is_rid"):
            entry["is_rid"] = True
            entry["kind"] = "BLE-RID"
        entry["hits"] = int(entry.get("hits") or 0) + 1
        entry["last_seen_wall_ts"] = now_wall
        if len(BLE_DEVICE_TABLE) > BLE_DEVICE_MAX:
            items = sorted(BLE_DEVICE_TABLE.items(),
                           key=lambda kv: kv[1].get("last_seen_wall_ts", 0.0), reverse=True)
            keep = {k for k, _ in items[:BLE_DEVICE_KEEP]}
            for k in list(BLE_DEVICE_TABLE.keys()):
                if k not in keep:
                    BLE_DEVICE_TABLE.pop(k, None)
        _ble_device_state["seq"] = int(_ble_device_state.get("seq") or 0) + 1


def _ble_device_snapshot() -> tuple[list, int, int]:
    """Return (rows, seq, total) for the UI BLE panel."""
    now_wall = time.time()
    with _ble_device_lock:
        items = [dict(e) for e in BLE_DEVICE_TABLE.values()]
        seq = int(_ble_device_state.get("seq") or 0)
    rows: list = []
    for e in items:
        last_seen_wall = float(e.get("last_seen_wall_ts") or now_wall)
        addr = str(e.get("addr") or "")
        name = str(e.get("name") or "")
        kind = "BLE-RID" if e.get("is_rid") else "BLE"
        rows.append({
            "addr": addr,
            "name": name,
            "kind": kind,
            "rssi": e.get("rssi"),
            "hits": int(e.get("hits") or 0),
            "ch": e.get("ch"),
            "is_rid": bool(e.get("is_rid")),
            "age": max(0, int(now_wall - last_seen_wall)),
            "last_seen": _fmt_wall_ts(last_seen_wall),
            # Compatibility keys so the shared AP-style table can render BLE rows.
            "bssid": addr,
            "ssid": name,
            "vendor": kind,
        })
    rows.sort(key=lambda x: (
        -(float(x["rssi"]) if x["rssi"] is not None else -9999.0),
        x["age"], x["addr"],
    ))
    return rows[:80], seq, len(rows)


def _ble_handle_record(rec: dict) -> None:
    """Emit one completed btmon advertising record (if it carried 0xFFFA data)."""
    data_hex = str(rec.get("data") or "")
    if not data_hex:
        return
    try:
        payload = bytes.fromhex(data_hex)
    except Exception:
        return
    addr = str(rec.get("addr") or "")
    rssi = rec.get("rssi")
    hits = _ble_process_payload(addr, rssi, payload)
    with _ble_thread_lock:
        BLE_SCAN_STATE["reports"] = int(BLE_SCAN_STATE.get("reports") or 0) + 1
        if hits:
            BLE_SCAN_STATE["rid_hits"] = int(BLE_SCAN_STATE.get("rid_hits") or 0) + hits
            BLE_SCAN_STATE["last_hit"] = time.strftime("%H:%M:%S")


def _ble_discovery_keeper(holder: dict) -> None:
    """Keep BLE discovery running through BlueZ (bluetoothctl).

    `hcitool lescan` fails with `Set scan parameters failed: Input/output error`
    while bluetoothd owns the controller, so discovery is driven via BlueZ and
    refreshed periodically instead.
    """
    import subprocess

    while not holder.get("stop"):
        proc = holder.get("proc")
        if proc is None or proc.poll() is not None:
            if proc is not None:
                try:
                    proc.wait(timeout=0)
                except Exception:
                    pass
            try:
                proc = subprocess.Popen(
                    ["bluetoothctl"], stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
                )
                holder["proc"] = proc
            except Exception as ex:
                holder["proc"] = None
                proc = None
                _log(f"[WARN] BLE 扫描进程启动失败: {ex}")
        if proc is not None and proc.poll() is None:
            try:
                proc.stdin.write("scan on\n")
                proc.stdin.flush()
            except Exception:
                pass
        time.sleep(10.0)


def _ble_new_record() -> dict:
    return {"addr": "", "rssi": None, "name": "", "data": "", "uuid": "", "is_rid": False}


def _ble_scan_loop(device: str) -> None:
    import subprocess

    btmon = subprocess.Popen(
        ["btmon"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, errors="replace",
    )
    holder: dict = {"proc": None, "stop": False}
    Thread(target=_ble_discovery_keeper, args=(holder,), daemon=True).start()
    _log("[INFO] BLE RID scanner started (btmon + BlueZ discovery)")
    rec = _ble_new_record()
    try:
        for line in btmon.stdout:  # type: ignore[union-attr]
            line = line.rstrip("\n")
            if _BLE_RECORD_HEAD_RE.search(line):
                with _ble_thread_lock:
                    BLE_SCAN_STATE["adv_seen"] = int(BLE_SCAN_STATE.get("adv_seen") or 0) + 1
                _ble_touch_device(rec)
                rec = _ble_new_record()
                continue
            m = _BLE_ADDR_RE.match(line)
            if m:
                rec["addr"] = m.group(1)
                continue
            m = _BLE_RSSI_RE.match(line)
            if m:
                try:
                    val = int(m.group(1))
                    rec["rssi"] = None if val >= 0 else val
                except Exception:
                    pass
                continue
            m = _BLE_NAME_RE.match(line)
            if m:
                rec["name"] = m.group(1)
                continue
            m = _BLE_SVC_RE.match(line)
            if m:
                rec["uuid"] = m.group(1).lower()
                rec["data"] = ""
                continue
            m = _BLE_DATA_RE.match(line)
            if m and rec.get("uuid") == "fffa":
                rec["data"] = m.group(2)
                rec["is_rid"] = True
                _ble_handle_record(rec)
                rec["data"] = ""
                continue
    except Exception as ex:
        _log(f"[WARN] BLE RID scanner stopped: {ex}")
    finally:
        holder["stop"] = True
        for proc in (holder.get("proc"), btmon):
            try:
                if proc is not None:
                    proc.terminate()
            except Exception:
                pass
        with _ble_thread_lock:
            BLE_SCAN_STATE["state"] = "error"
            BLE_SCAN_STATE["msg"] = "BLE 扫描已停止"


def _ble_pick_device(prefer: str | None = None) -> str:
    want = str(prefer or "").strip()
    if want and os.path.isdir(os.path.join("/sys/class/bluetooth", want)):
        return want
    try:
        names = sorted(os.listdir("/sys/class/bluetooth"))
    except Exception:
        names = []
    return str(names[0]) if names else ""


def init_ble_from_config(cfg: dict | None = None) -> None:
    cfg = cfg if isinstance(cfg, dict) else {}
    basic = cfg.get("basic") if isinstance(cfg.get("basic"), dict) else {}
    with _ble_thread_lock:
        BLE_SCAN_STATE["enabled"] = bool(basic.get("ble_scan", False))
        BLE_SCAN_STATE["device"] = str(basic.get("ble_hci") or "")
        if not BLE_SCAN_STATE["enabled"]:
            BLE_SCAN_STATE["state"] = "off"
            BLE_SCAN_STATE["msg"] = "BLE 扫描未启用"


def start_ble_scanner() -> bool:
    """Start the BLE RID scanner thread when enabled in config."""
    global _ble_scan_started
    if not bool(BLE_SCAN_STATE.get("enabled")):
        return False
    with _ble_thread_lock:
        if _ble_scan_started:
            return True
        _ble_scan_started = True
    dev = _ble_pick_device(BLE_SCAN_STATE.get("device"))
    if not dev:
        with _ble_thread_lock:
            BLE_SCAN_STATE["state"] = "error"
            BLE_SCAN_STATE["msg"] = "未检测到蓝牙适配器"
        _log("[WARN] BLE 扫描启用但未检测到蓝牙适配器")
        return False
    with _ble_thread_lock:
        BLE_SCAN_STATE["device"] = dev
        BLE_SCAN_STATE["state"] = "running"
        BLE_SCAN_STATE["msg"] = ""
    Thread(target=_ble_scan_loop, args=(dev,), daemon=True).start()
    return True


def ble_scan_status() -> dict:
    with _ble_thread_lock:
        return dict(BLE_SCAN_STATE)
