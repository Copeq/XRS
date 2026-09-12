"""Host metrics sampling + hardware command execution (extracted from auth_core.py during
backend module split; these domains were co-located with auth code historically).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
"""

def _hw_safe_iface(iface: str) -> str | None:
    name = str(iface or "").strip()
    if not name:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,32}", name):
        return None
    iftypes = _sniff_iface_candidates()
    if name not in iftypes:
        return None
    return name

def _hw_cmd_result(cmd: str, timeout: int = 8) -> dict:
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        ok = (proc.returncode == 0)
        return {
            "ok": ok,
            "cmd": cmd,
            "code": int(proc.returncode),
            "stdout": out,
            "stderr": err,
        }
    except Exception as e:
        return {
            "ok": False,
            "cmd": cmd,
            "code": -1,
            "stdout": "",
            "stderr": str(e),
        }

_HOST_CPU_LOCK = Lock()
_HOST_CPU_CACHE: tuple[float, float] | None = None


def _read_proc_cpu_totals() -> tuple[float, float] | None:
    try:
        with open("/proc/stat", "r", encoding="utf-8", errors="ignore") as f:
            first = f.readline().strip()
        if not first.startswith("cpu "):
            return None
        parts = [float(x) for x in first.split()[1:] if x.strip()]
        if len(parts) < 4:
            return None
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0.0)
        total = float(sum(parts))
        return idle, total
    except Exception:
        return None


def _host_cpu_percent() -> float | None:
    global _HOST_CPU_CACHE
    snap = _read_proc_cpu_totals()
    if snap:
        idle, total = snap
        with _HOST_CPU_LOCK:
            prev = _HOST_CPU_CACHE
            _HOST_CPU_CACHE = (idle, total)
        if prev:
            idle_prev, total_prev = prev
            total_delta = total - total_prev
            idle_delta = idle - idle_prev
            if total_delta > 0:
                busy = max(0.0, min(1.0, 1.0 - (idle_delta / total_delta)))
                return round(busy * 100.0, 1)
    try:
        load1 = os.getloadavg()[0]
        cpu_count = max(1, int(os.cpu_count() or 1))
        return round(max(0.0, min(100.0, (float(load1) / float(cpu_count)) * 100.0)), 1)
    except Exception:
        return None


def _host_mem_stats() -> dict:
    try:
        data: dict[str, int] = {}
        with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                try:
                    data[k.strip()] = int(v.strip().split()[0])
                except Exception:
                    continue
        total_kb = int(data.get("MemTotal") or 0)
        avail_kb = int(data.get("MemAvailable") or data.get("MemFree") or 0)
        if total_kb <= 0:
            return {"percent": None, "used_mb": None, "total_mb": None}
        used_kb = max(0, total_kb - avail_kb)
        return {
            "percent": round((used_kb / total_kb) * 100.0, 1),
            "used_mb": int(round(used_kb / 1024.0)),
            "total_mb": int(round(total_kb / 1024.0)),
        }
    except Exception:
        return {"percent": None, "used_mb": None, "total_mb": None}


def _host_temperature_parse_text(text: str) -> float | None:
    m = re.search(r"temp\s*=\s*(-?\d+(?:\.\d+)?)\s*'?\s*c", str(text or ""), re.I)
    if not m:
        m = re.search(r"^\s*(-?\d+(?:\.\d+)?)\s*(?:'?\s*c)?\s*$", str(text or ""), re.I)
    if not m:
        return None
    try:
        value = float(m.group(1))
        if -40.0 <= value <= 140.0:
            return round(value, 1)
    except Exception:
        pass
    return None


def _host_temperature_from_vcgencmd(*extra_args: str) -> float | None:
    try:
        out = subprocess.run(["vcgencmd", "measure_temp", *extra_args], capture_output=True, text=True, timeout=3)
        text = out.stdout or (out.stderr if int(getattr(out, "returncode", 1) or 0) == 0 else "")
        return _host_temperature_parse_text(text)
    except Exception:
        return None


def _host_temperature_from_vcgencmd_pmic() -> float | None:
    return _host_temperature_from_vcgencmd("pmic")


def _host_temperature_value_from_file(path: str, *, min_c: float = -40.0, max_c: float = 140.0) -> float | None:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read().strip()
        if not raw:
            return None
        value = float(raw)
        if abs(value) > 250:
            value = value / 1000.0
        if min_c <= value <= max_c:
            return round(value, 1)
    except Exception:
        pass
    return None


def _host_temperature_best_candidate(candidates: list[tuple[int, float, str]]) -> float | None:
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], abs(item[1] - 55.0), item[1]))
    best = candidates[0]
    if best[1] >= 95.0:
        for item in candidates[1:]:
            if item[1] < 95.0 and item[0] <= best[0] + 8:
                best = item
                break
    return round(best[1], 1)


def _host_temperature_candidates_from_thermal(root: str = "/sys/class/thermal") -> list[tuple[int, float, str]]:
    candidates: list[tuple[int, float, str]] = []
    try:
        names = sorted(os.listdir(root))
    except Exception:
        return candidates
    for name in names:
        if not name.startswith("thermal_zone"):
            continue
        dirpath = os.path.join(root, name)
        temp_path = os.path.join(dirpath, "temp")
        if not os.path.exists(temp_path):
            continue
        label = ""
        try:
            with open(os.path.join(dirpath, "type"), "r", encoding="utf-8", errors="ignore") as f:
                label = f.read().strip().lower()
        except Exception:
            label = ""
        value = _host_temperature_value_from_file(temp_path)
        if value is None:
            continue
        score = 12
        if any(k in label for k in ("cpu", "soc", "board", "thermal", "system")):
            score -= 10
        if any(k in label for k in ("max", "crit", "limit", "trip", "hot")):
            score += 12
        if value >= 95.0 and not any(k in label for k in ("cpu", "soc", "board")):
            score += 8
        candidates.append((score, float(value), temp_path))
    return candidates


def _host_temperature_candidates_from_hwmon(root: str = "/sys/class/hwmon") -> list[tuple[int, float, str]]:
    candidates: list[tuple[int, float, str]] = []
    try:
        names = sorted(os.listdir(root))
    except Exception:
        return candidates
    for name in names:
        if not name.startswith("hwmon"):
            continue
        dirpath = os.path.join(root, name)
        device_label = ""
        try:
            with open(os.path.join(dirpath, "name"), "r", encoding="utf-8", errors="ignore") as f:
                device_label = f.read().strip().lower()
        except Exception:
            device_label = ""
        try:
            files = sorted(os.listdir(dirpath))
        except Exception:
            continue
        for fname in files:
            if not re.match(r"^temp\d+_input$", fname):
                continue
            path = os.path.join(dirpath, fname)
            label = device_label
            label_name = fname[:-6] + "_label"
            try:
                with open(os.path.join(dirpath, label_name), "r", encoding="utf-8", errors="ignore") as f:
                    label = (f.read().strip().lower() or device_label)
            except Exception:
                pass
            value = _host_temperature_value_from_file(path)
            if value is None:
                continue
            score = 20
            if any(k in label for k in ("cpu", "package", "soc", "board", "thermal", "system", "tctl", "tdie")):
                score -= 10
            if any(k in label for k in ("max", "crit", "limit", "trip", "hot")):
                score += 12
            if value >= 95.0 and not any(k in label for k in ("cpu", "package", "soc", "board", "tctl", "tdie")):
                score += 8
            candidates.append((score, float(value), path))
    return candidates


def _host_temperature_from_w1(root: str = "/sys/bus/w1/devices") -> float | None:
    candidates: list[tuple[int, float, str]] = []
    try:
        names = sorted(os.listdir(root))
    except Exception:
        return None
    for name in names:
        if not name.startswith("28-"):
            continue
        path = os.path.join(root, name, "temperature")
        value = _host_temperature_value_from_file(path, min_c=-55.0, max_c=125.0)
        if value is None:
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                if f.read().strip() == "85000":
                    continue
        except Exception:
            pass
        candidates.append((30, float(value), path))
    return _host_temperature_best_candidate(candidates)


def _host_temperature_from_sysfs(*roots: str) -> float | None:
    candidates: list[tuple[int, float, str]] = []
    for root in roots:
        root_text = str(root or "")
        base = os.path.basename(os.path.normpath(root_text)).lower()
        if base == "thermal":
            candidates.extend(_host_temperature_candidates_from_thermal(root_text))
        elif base == "hwmon":
            candidates.extend(_host_temperature_candidates_from_hwmon(root_text))
        elif base == "devices" and "w1" in root_text:
            value = _host_temperature_from_w1(root_text)
            if value is not None:
                candidates.append((30, float(value), root_text))
    return _host_temperature_best_candidate(candidates)


def _host_temperature_read() -> tuple[float | None, str]:
    source = str(METRICS_CFG.get("temperature_source") or "auto")
    if source == "off":
        return None, "off"
    probes = []
    if source == "vcgencmd":
        probes = [
            ("vcgencmd", _host_temperature_from_vcgencmd),
            ("vcgencmd_pmic", _host_temperature_from_vcgencmd_pmic),
        ]
    elif source == "vcgencmd_pmic":
        probes = [("vcgencmd_pmic", _host_temperature_from_vcgencmd_pmic)]
    elif source == "thermal_zone":
        probes = [("thermal_zone", lambda: _host_temperature_from_sysfs("/sys/class/thermal"))]
    elif source == "hwmon":
        probes = [("hwmon", lambda: _host_temperature_from_sysfs("/sys/class/hwmon"))]
    elif source == "w1":
        probes = [("w1", _host_temperature_from_w1)]
    else:
        probes = [
            ("vcgencmd", _host_temperature_from_vcgencmd),
            ("vcgencmd_pmic", _host_temperature_from_vcgencmd_pmic),
            ("thermal_zone", lambda: _host_temperature_from_sysfs("/sys/class/thermal")),
            ("hwmon", lambda: _host_temperature_from_sysfs("/sys/class/hwmon")),
            ("w1", _host_temperature_from_w1),
        ]
    for key, probe in probes:
        value = probe()
        if value is not None:
            return value, key
    return None, source


def _host_temperature_c() -> float | None:
    value, _source = _host_temperature_read()
    return value


def _host_temperature_source_label(source: str | None) -> str:
    key = str(source or "").strip().lower().replace("-", "_")
    labels = {
        "auto": "自动",
        "vcgencmd": "vcgencmd",
        "vcgencmd_pmic": "vcgencmd pmic",
        "thermal_zone": "/sys/class/thermal",
        "hwmon": "/sys/class/hwmon",
        "w1": "DS18B20 / w1",
        "off": "关闭",
    }
    return labels.get(key, "自动")


def _host_local_ips() -> list[str]:
    ips: list[str] = []
    try:
        text = subprocess.run("hostname -I", shell=True, capture_output=True, text=True, timeout=3).stdout or ""
        for part in text.split():
            s = part.strip()
            if s and s not in ips:
                ips.append(s)
    except Exception:
        pass
    if not ips:
        try:
            host = socket.gethostname()
            for item in socket.getaddrinfo(host, None):
                addr = str(item[4][0] or "").strip()
                if addr and not addr.startswith("127.") and addr != "::1" and addr not in ips:
                    ips.append(addr)
        except Exception:
            pass
    return ips[:12]


def _host_resource_snapshot() -> dict:
    temperature_c, temperature_source = _host_temperature_read()
    mem = _host_mem_stats()
    uptime_sec = None
    try:
        with open("/proc/uptime", "r", encoding="utf-8", errors="ignore") as f:
            uptime_sec = int(float((f.read().strip().split() or ["0"])[0]))
    except Exception:
        uptime_sec = None
    load1 = load5 = load15 = None
    try:
        load1, load5, load15 = os.getloadavg()
    except Exception:
        pass
    return {
        "hostname": str(platform.node() or os.environ.get("COMPUTERNAME") or "host"),
        "cpu_percent": _host_cpu_percent(),
        "cpu_count": int(os.cpu_count() or 1),
        "mem_percent": mem.get("percent"),
        "mem_used_mb": mem.get("used_mb"),
        "mem_total_mb": mem.get("total_mb"),
        "temperature_c": temperature_c,
        "temperature_source": temperature_source,
        "temperature_source_label": _host_temperature_source_label(temperature_source),
        "local_ips": _host_local_ips(),
        "load1": (None if load1 is None else round(float(load1), 2)),
        "load5": (None if load5 is None else round(float(load5), 2)),
        "load15": (None if load15 is None else round(float(load15), 2)),
        "uptime_sec": uptime_sec,
    }

def _host_metrics_ensure_store() -> None:
    parent = os.path.dirname(HOST_METRICS_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if not os.path.exists(HOST_METRICS_PATH):
        with open(HOST_METRICS_PATH, "a", encoding="utf-8"):
            pass

def _host_metric_point() -> dict:
    host = _host_resource_snapshot()
    aps, _seq, aps_total = _ap_snapshot()
    cpu_count = max(1, int(host.get("cpu_count") or os.cpu_count() or 1))
    load1 = host.get("load1")
    load_percent = None
    try:
        if load1 is not None:
            load_percent = round(max(0.0, min(100.0, (float(load1) / float(cpu_count)) * 100.0)), 1)
    except Exception:
        load_percent = None
    return {
        "ts": time.time(),
        "cpu": host.get("cpu_percent"),
        "mem": host.get("mem_percent"),
        "temp": host.get("temperature_c"),
        "load": load_percent,
        "load1": load1,
        "ap": int(aps_total if aps_total is not None else len(aps)),
    }

def _host_metrics_read_all() -> list[dict]:
    _host_metrics_ensure_store()
    rows: list[dict] = []
    try:
        with open(HOST_METRICS_PATH, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict) and obj.get("ts") is not None:
                    rows.append(obj)
    except Exception:
        return []
    rows.sort(key=lambda x: float(x.get("ts") or 0.0))
    return rows

def _host_metrics_prune_and_write(rows: list[dict]) -> None:
    retention = int(METRICS_CFG.get("retention_days") or HOST_METRICS_RETENTION_DAYS_DEFAULT)
    cutoff = time.time() - max(1, retention) * 86400.0
    kept = [x for x in rows if float(x.get("ts") or 0.0) >= cutoff]
    tmp_path = HOST_METRICS_PATH + ".tmp"
    _host_metrics_ensure_store()
    with open(tmp_path, "w", encoding="utf-8") as f:
        for item in kept:
            f.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp_path, HOST_METRICS_PATH)

def _host_metrics_sample(force: bool = False) -> dict | None:
    global host_metrics_last_sample_wall
    if not bool(METRICS_CFG.get("enabled")):
        return None
    now = time.time()
    with host_metrics_lock:
        if (not force) and host_metrics_last_sample_wall and (now - host_metrics_last_sample_wall) < HOST_METRICS_SAMPLE_SEC:
            return None
        host_metrics_last_sample_wall = now
    point = _host_metric_point()
    with host_metrics_lock:
        rows = _host_metrics_read_all()
        rows.append(point)
        _host_metrics_prune_and_write(rows)
    return point

def _decimate_points(rows: list[dict], max_points: int = 720) -> list[dict]:
    if len(rows) <= max_points:
        return rows
    step = max(1, int(math.ceil(len(rows) / float(max_points))))
    out = rows[::step]
    if rows and out[-1] is not rows[-1]:
        out.append(rows[-1])
    return out

def _host_metrics_payload(window_sec: int = 24 * 3600) -> dict:
    try:
        window_sec = max(3600, min(7 * 86400, int(window_sec)))
    except Exception:
        window_sec = 24 * 3600
    enabled = bool(METRICS_CFG.get("enabled"))
    if enabled:
        try:
            _host_metrics_sample(force=False)
        except Exception:
            pass
    cutoff = time.time() - float(window_sec)
    if enabled:
        with host_metrics_lock:
            rows = [x for x in _host_metrics_read_all() if float(x.get("ts") or 0.0) >= cutoff]
    else:
        rows = []
    return {
        "ok": True,
        "enabled": enabled,
        "window_sec": int(window_sec),
        "retention_days": int(METRICS_CFG.get("retention_days") or HOST_METRICS_RETENTION_DAYS_DEFAULT),
        "temperature_source": str(METRICS_CFG.get("temperature_source") or "auto"),
        "temperature_source_label": _host_temperature_source_label(METRICS_CFG.get("temperature_source")),
        "sample_interval_sec": int(HOST_METRICS_SAMPLE_SEC),
        "store_path": HOST_METRICS_PATH,
        "count": len(rows),
        "items": _decimate_points(rows, max_points=900),
    }

def host_metrics_loop() -> None:
    if bool(METRICS_CFG.get("enabled")):
        try:
            _host_metrics_sample(force=True)
        except Exception as e:
            _log(f"[WARN] host metrics initial sample failed: {e}")
    while True:
        try:
            _host_metrics_sample(force=False)
        except Exception as e:
            _log(f"[WARN] host metrics sample failed: {e}")
        time.sleep(HOST_METRICS_SAMPLE_SEC)


def _hw_status_snapshot() -> dict:
    items = _iface_options_snapshot()
    host = _host_resource_snapshot()
    host["ifaces"] = items
    return {
        "items": items,
        "active_iface": str(sniff_iface_name or ""),
        "sniff_state": _sniff_health_meta(time.monotonic(), time.time()),
        "current_channel": int(current_channel or 0),
        "scan_wifi_fast": bool(SCAN_WIFI_FAST),
        "wifi_fast_supported": WIFI_FAST_SUPPORTED,
        "wifi_fast_msg": str(WIFI_FAST_SUPPORT_MSG or ""),
        "ble_scan": ble_scan_status(),
        "host": host,
    }

def _hw_execute_task(task: dict) -> dict:
    global current_channel
    op = str(task.get("op") or "").strip().lower()
    iface = _hw_safe_iface(task.get("iface"))
    if op == "status":
        return {"ok": True, "data": _hw_status_snapshot()}
    if op == "list_ifaces":
        return {"ok": True, "items": _iface_options_snapshot(), "active_iface": str(sniff_iface_name or "")}
    if op == "iw_dev":
        return _hw_cmd_result("iw dev", timeout=8)
    if op == "iw_info":
        if not iface:
            return {"ok": False, "error": "invalid iface"}
        return _hw_cmd_result(f"iw dev {iface} info", timeout=8)
    if op == "iw_link":
        if not iface:
            return {"ok": False, "error": "invalid iface"}
        return _hw_cmd_result(f"iw dev {iface} link", timeout=8)
    if op == "set_monitor":
        if not iface:
            return {"ok": False, "error": "invalid iface"}
        steps = [
            _hw_cmd_result(f"ip link set {iface} down", timeout=8),
            _hw_cmd_result(f"iw dev {iface} set type monitor", timeout=8),
            _hw_cmd_result(f"ip link set {iface} up", timeout=8),
            _hw_cmd_result(f"iw dev {iface} set power_save off", timeout=8),
        ]
        return {"ok": all(s.get("ok") for s in steps), "steps": steps}
    if op == "set_managed":
        if not iface:
            return {"ok": False, "error": "invalid iface"}
        steps = [
            _hw_cmd_result(f"ip link set {iface} down", timeout=8),
            _hw_cmd_result(f"iw dev {iface} set type managed", timeout=8),
            _hw_cmd_result(f"ip link set {iface} up", timeout=8),
            _hw_cmd_result(f"iw dev {iface} set power_save off", timeout=8),
        ]
        return {"ok": all(s.get("ok") for s in steps), "steps": steps}
    if op == "restart_iface":
        if not iface:
            return {"ok": False, "error": "invalid iface"}
        steps = [
            _hw_cmd_result(f"ip link set {iface} down", timeout=8),
            _hw_cmd_result(f"ip link set {iface} up", timeout=8),
            _hw_cmd_result(f"iw dev {iface} set power_save off", timeout=8),
        ]
        return {"ok": all(s.get("ok") for s in steps), "steps": steps}
    if op == "set_channel":
        if not iface:
            return {"ok": False, "error": "invalid iface"}
        try:
            ch = int(task.get("channel"))
        except Exception:
            return {"ok": False, "error": "invalid channel"}
        if ch < 1 or ch > 196:
            return {"ok": False, "error": "channel out of range"}
        r = _hw_cmd_result(f"iw dev {iface} set channel {ch}", timeout=8)
        if r.get("ok"):
            current_channel = ch
        return r
    if op == "restart_program":
        ok, msg = _schedule_self_restart(list(sys.argv[1:]))
        return {"ok": bool(ok), "msg": msg}
    return {"ok": False, "error": f"unsupported op: {op}"}

def _hw_worker_loop() -> None:
    while True:
        task = hw_task_queue.get()
        if not isinstance(task, dict):
            continue
        rsp_q = task.get("_rsp_q")
        try:
            out = _hw_execute_task(task)
        except Exception as e:
            out = {"ok": False, "error": str(e)}
        if isinstance(rsp_q, queue.Queue):
            try:
                rsp_q.put_nowait(out)
            except Exception:
                pass

def start_hw_worker() -> None:
    global hw_worker_started
    with hw_worker_lock:
        if hw_worker_started:
            return
        hw_worker_started = True
    Thread(target=_hw_worker_loop, daemon=True).start()

def _hw_submit_task(task: dict, timeout_sec: float = 12.0) -> dict:
    start_hw_worker()
    rsp_q: "queue.Queue[dict]" = queue.Queue(maxsize=1)
    item = dict(task or {})
    item["_rsp_q"] = rsp_q
    try:
        hw_task_queue.put_nowait(item)
    except queue.Full:
        return {"ok": False, "error": "hardware helper busy"}
    try:
        out = rsp_q.get(timeout=max(0.5, float(timeout_sec)))
    except Exception:
        return {"ok": False, "error": "hardware helper timeout"}
    return out if isinstance(out, dict) else {"ok": False, "error": "invalid helper response"}
