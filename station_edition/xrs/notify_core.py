"""notify core (extracted from hardware_core.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
"""

def _wecom_send_text(key: str, content: str, timeout_sec: int = 8) -> tuple[bool, str]:
    body = json.dumps({
        "msgtype": "text",
        "text": {"content": content},
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        _wecom_webhook_url(key),
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = (resp.read() or b"").decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        return False, f"network error: {e}"
    except Exception as e:
        return False, f"send error: {e}"
    try:
        obj = json.loads(raw) if raw else {}
    except Exception:
        obj = {}
    if isinstance(obj, dict) and int(obj.get("errcode", -1)) == 0:
        return True, raw or "ok"
    return False, raw or "unknown response"

def _notify_queue_put(item: dict) -> None:
    try:
        notify_queue.put_nowait(item)
    except queue.Full:
        _log("[WARN] notification queue full, dropping one message")

def _notify_online_text(e: dict, event_title: str, now_wall: float) -> str:
    def _f(v, fmt_str: str, unit: str = "N/A") -> str:
        if v is None:
            return "N/A"
        try:
            return f"{v:{fmt_str}}{unit if unit != 'N/A' else ''}"
        except Exception:
            return str(v)
    sn = str(e.get("sn",""))
    model = str(e.get("model","N/A"))
    it = str(e.get("id_type",""))
    mac = str(e.get("src_mac",""))
    ch = e.get("last_ch") or 0
    ch_s = f"{'~' if e.get('ch_assumed') else ''}ch{ch}" if ch else "ch?"
    rssi = _f(e.get("rssi"), "d", "dBm")
    lat = e.get("lat")
    lon = e.get("lon")
    loc_s = f"{lat:.6f}, {lon:.6f}" if lat is not None and lon is not None else "N/A"
    alt_s = _f(e.get("alt"), ".1f", "m")
    spd_s = _f(e.get("speed"), ".1f", "m/s")
    vsp_s = _f(e.get("vspeed"), ".1f", "m/s")
    pkts = int(e.get("pkt_count") or 0)
    ts_s = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_wall))
    alarm_hits = e.get("alarm_zone_hits")
    if not isinstance(alarm_hits, list):
        alarm_hits = _alarm_zone_names_for_point(lat, lon)
    alarm_s = ""
    if alarm_hits:
        alarm_s = "\n报警区域: " + "、".join(str(x) for x in alarm_hits if str(x).strip())
    return (
        f"[RID{event_title}] {ts_s}\n"
        f"SN: {sn}\n"
        f"机型/ID: {model} / {it}\n"
        f"MAC/信道/信号: {mac} / {ch_s} / {rssi}\n"
        f"位置: {loc_s}  高程: {alt_s}\n"
        f"速度: {spd_s}  垂速: {vsp_s}  包数: {pkts}"
        f"{alarm_s}"
    )

def _notify_zone_alarm_text(e: dict, zone_names: list[str], now_wall: float) -> str:
    sn = str(e.get("sn", ""))
    model = str(e.get("model", "N/A"))
    lat = e.get("lat")
    lon = e.get("lon")
    try:
        loc_s = f"{float(lat):.6f}, {float(lon):.6f}" if lat is not None and lon is not None else "N/A"
    except Exception:
        loc_s = "N/A"
    alt = e.get("alt")
    spd = e.get("speed")
    try:
        alt_s = f"{float(alt):.1f}m" if alt is not None else "N/A"
    except Exception:
        alt_s = "N/A"
    try:
        spd_s = f"{float(spd):.1f}m/s" if spd is not None else "N/A"
    except Exception:
        spd_s = "N/A"
    ts_s = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_wall))
    zones = "、".join(str(x) for x in (zone_names or []) if str(x).strip()) or "报警区域"
    return (
        f"[RID区域告警] {ts_s}\n"
        f"SN: {sn}\n"
        f"机型: {model}\n"
        f"进入区域: {zones}\n"
        f"位置: {loc_s}  高程: {alt_s}\n"
        f"速度: {spd_s}"
    )

def _notify_lost_text(e: dict, age_sec: float, now_wall: float) -> str:
    sn = str(e.get("sn", ""))
    model = str(e.get("model", "N/A"))
    mac = str(e.get("src_mac") or "-")
    ts_s = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_wall))
    try:
        age_s = f"{float(age_sec):.0f}s"
    except Exception:
        age_s = "N/A"
    return (
        f"[RID离线] {ts_s}\n"
        f"SN: {sn}\n"
        f"机型: {model}\n"
        f"MAC: {mac}\n"
        f"未收到数据: {age_s}"
    )

def _notification_kind(kind: str | None) -> str:
    k = str(kind or "info").strip().lower()
    return k if k in ("info", "ok", "warn") else "info"

def _notification_add(text: str, kind: str = "info", source: str = "server") -> dict | None:
    global notification_seq
    msg = str(text or "").strip()
    if not msg:
        return None
    if len(msg) > 2000:
        msg = msg[:1997] + "..."
    with notification_lock:
        notification_seq += 1
        item = {
            "id": notification_seq,
            "text": msg,
            "kind": _notification_kind(kind),
            "source": str(source or "server")[:40],
            "ts": int(time.time() * 1000),
        }
        notification_items.appendleft(item)
        return dict(item)

def _notification_payload(limit: int = NOTIFICATION_CENTER_MAX) -> dict:
    try:
        limit = int(limit)
    except Exception:
        limit = NOTIFICATION_CENTER_MAX
    limit = max(1, min(NOTIFICATION_CENTER_MAX, limit))
    with notification_lock:
        items = [dict(x) for x in list(notification_items)[:limit]]
        seq = int(notification_seq)
    return {"ok": True, "seq": seq, "count": len(items), "items": items}

def _notification_delete(item_id) -> bool:
    target = str(item_id or "").strip()
    if not target:
        return False
    with notification_lock:
        before = len(notification_items)
        kept = [x for x in notification_items if str((x or {}).get("id") or "") != target]
        notification_items.clear()
        notification_items.extend(kept[:NOTIFICATION_CENTER_MAX])
        return len(notification_items) != before

def _notification_clear() -> int:
    with notification_lock:
        n = len(notification_items)
        notification_items.clear()
        return n

def _notify_worker_loop() -> None:
    while True:
        item = notify_queue.get()
        try:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "wecom_text":
                continue
            key = str(item.get("key") or "")
            content = str(item.get("content") or "")
            if not key or not content:
                continue
            ok, resp = _wecom_send_text(key, content, timeout_sec=int(item.get("timeout_sec") or 8))
            if not ok:
                _log(f"[WARN] WeCom notification send failed: {resp}")
        except Exception as e:
            _log(f"[WARN] 通知线程异常: {e}")
        finally:
            try:
                notify_queue.task_done()
            except Exception:
                pass

def start_notify_worker() -> None:
    global notify_worker_started
    with notify_worker_lock:
        if notify_worker_started:
            return
        Thread(target=_notify_worker_loop, daemon=True).start()
        notify_worker_started = True

def queue_online_notification(e: dict, event_title: str, now_wall: float | None = None) -> bool:
    if not NOTIFY_CFG.get("enabled"):
        return False
    targets = _notify_wecom_targets(NOTIFY_CFG)
    if not targets:
        return False
    now_wall = float(now_wall or time.time())
    content = _notify_online_text(e, event_title, now_wall)
    for item in targets:
        _notify_queue_put({
            "type": "wecom_text",
            "key": str(item.get("key") or "").strip(),
            "content": content,
            "timeout_sec": int(NOTIFY_CFG.get("send_timeout_sec") or 8),
        })
    return True

def queue_zone_alarm_notification(e: dict, zone_names: list[str], now_wall: float | None = None) -> bool:
    if not NOTIFY_CFG.get("enabled"):
        return False
    targets = _notify_wecom_targets(NOTIFY_CFG)
    if not targets:
        return False
    now_wall = float(now_wall or time.time())
    content = _notify_zone_alarm_text(e, zone_names, now_wall)
    for item in targets:
        _notify_queue_put({
            "type": "wecom_text",
            "key": str(item.get("key") or "").strip(),
            "content": content,
            "timeout_sec": int(NOTIFY_CFG.get("send_timeout_sec") or 8),
        })
    return True

def send_test_notification_from_config(cfg: dict | None = None) -> tuple[bool, str]:
    notify_cfg = _normalize_notify_cfg(cfg) if isinstance(cfg, dict) else dict(NOTIFY_CFG)
    if not notify_cfg.get("enabled"):
        return False, "notify disabled"
    targets = _notify_wecom_targets(notify_cfg)
    if not targets:
        return False, "missing wecom webhook"
    now_wall = time.time()
    test_e = {
        "sn": "TEST-RID-ONLINE",
        "model": "Config/Test",
        "id_type": "Test",
        "src_mac": "00:11:22:33:44:55",
        "last_ch": current_channel or 6,
        "ch_assumed": True,
        "rssi": -45,
        "lat": None,
        "lon": None,
        "alt": None,
        "speed": None,
        "vspeed": None,
        "pkt_count": 1,
    }
    content = _notify_online_text(test_e, "上线(测试)", now_wall)
    timeout_sec = int(notify_cfg.get("send_timeout_sec") or 8)
    results: list[str] = []
    ok_count = 0
    for item in targets:
        ok, resp = _wecom_send_text(str(item.get("key") or "").strip(), content, timeout_sec=timeout_sec)
        if ok:
            ok_count += 1
        results.append(f"{item.get('name') or '通道'}: {'OK' if ok else 'FAIL'} {resp}")
    return (ok_count > 0), " | ".join(results)


def send_test_notification_from_visual_payload(body: dict | None = None) -> tuple[bool, str]:
    """Send a WeCom test using the unsaved visual-settings draft."""
    if not isinstance(body, dict) or not body:
        return send_test_notification_from_config()
    notify_cfg = dict(_normalize_notify_cfg(APP_CONFIG))
    draft = body.get("notify") if isinstance(body.get("notify"), dict) else {}
    if "send_timeout_sec" in draft:
        try:
            notify_cfg["send_timeout_sec"] = max(2, int(draft.get("send_timeout_sec")))
        except Exception:
            return False, "invalid send_timeout_sec"
    hooks_payload = draft.get("wecom_webhooks")
    if isinstance(hooks_payload, list):
        existing_hooks = notify_cfg.get("wecom_webhooks") or []
        hooks_next: list[dict] = []
        for idx, item in enumerate(hooks_payload):
            if not isinstance(item, dict):
                continue
            cur_key = ""
            try:
                src_idx = int(item.get("index"))
                if 0 <= src_idx < len(existing_hooks):
                    cur_key = str(existing_hooks[src_idx].get("key") or "").strip()
            except Exception:
                cur_key = ""
            key = str(item.get("key") or "").strip()
            if key in ("", "********", "__KEEP__"):
                key = cur_key
            if not key:
                continue
            hooks_next.append({
                "name": str(item.get("name") or f"通道 {idx + 1}").strip() or f"通道 {idx + 1}",
                "enabled": bool(item.get("enabled", True)),
                "key": key,
            })
        notify_cfg["wecom_webhooks"] = _normalize_wecom_webhooks(hooks_next, "")
        notify_cfg["wecom_webhook_key"] = str(
            (notify_cfg["wecom_webhooks"][0]["key"] if notify_cfg["wecom_webhooks"] else "") or ""
        )
    # A test should be available before the global notification switch is saved.
    # Individual channel enable flags are still respected.
    notify_cfg["enabled"] = True
    return send_test_notification_from_config({"notify": notify_cfg})
