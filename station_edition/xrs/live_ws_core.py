"""live ws core (extracted from process_core.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
References to live state / track / history helpers resolve at call time.
"""

def _ws_settings_runtime_payload() -> dict:
    aps, aps_seq, aps_total = _ap_snapshot()
    return {
        "ok": True,
        "kind": "settings_runtime",
        "aps": aps,
        "aps_seq": aps_seq,
        "aps_total": aps_total,
        "workflow": _history_reparse_workflow_snapshot(),
    }

_HOME_LIST_DRONE_FIELDS = (
    "sn",
    "sn_src",
    "uas_id",
    "scan_type",
    "firmware_type",
    "firmware_type_key",
    "model",
    "lost",
    "archived",
    "mac",
    "id_type",
    "ch",
    "ch_assumed",
    "lat",
    "lon",
    "alt",
    "spd",
    "vspd",
    "pilot_lat",
    "pilot_lon",
    "pilot_alt",
    "pilot_loc_type",
    "pilot_loc_type_text",
    "home_lat",
    "home_lon",
    "aux_lat",
    "aux_lon",
    "pos_a_lat",
    "pos_a_lon",
    "pos_b_lat",
    "pos_b_lon",
    "rssi",
    "pkts",
    "dir",
    "ssid",
    "capture_type",
    "capture_time",
    "last_pkt_time",
    "scan_type_key",
    "age",
    "age_text",
    "online_dur",
    "first_seen",
    "last_seen",
)

def _home_list_drone(row: dict) -> dict:
    if not isinstance(row, dict):
        return {}
    return {key: row.get(key) for key in _HOME_LIST_DRONE_FIELDS if key in row}

def _home_workflow_summary(state: dict | None) -> dict:
    if not isinstance(state, dict):
        return {}
    keys = (
        "task_id",
        "kind",
        "title",
        "status",
        "running",
        "limit",
        "total",
        "completed",
        "decoded",
        "skipped",
        "failed",
        "migrated",
        "saved",
        "aircraft_total",
        "updated_aircraft",
        "enqueued",
        "producer_done",
        "batch_size",
        "batches_total",
        "active_batch",
        "active_batch_size",
        "message",
        "last_error",
        "worker_total",
        "worker_busy",
        "worker_idle",
        "pending",
        "batches_pending",
        "queue_depth",
        "progress_pct",
        "elapsed_sec",
        "rate_per_sec",
        "decoded_rate_per_sec",
        "eta_sec",
    )
    out = {key: state.get(key) for key in keys if key in state}
    errors = state.get("errors")
    if isinstance(errors, list) and errors:
        out["errors_count"] = len(errors)
    return out

def _home_runtime_security_summary(state: dict | None) -> dict:
    if not isinstance(state, dict):
        return {}
    keys = (
        "ok",
        "current_uid",
        "current_user",
        "running_as_root",
        "has_network_capabilities",
        "risk",
        "level",
        "message",
        "dedicated_user",
        "dedicated_user_exists",
        "service_user",
        "service_uses_dedicated_user",
        "sudo_available",
        "can_elevate",
        "password_saved",
    )
    return {key: state.get(key) for key in keys if key in state}

def _home_meta_summary(meta: dict) -> dict:
    if not isinstance(meta, dict):
        return {}
    keys = (
        "dji_lookup_url",
        "allow_restart",
        "restart_args_current",
        "restart_args_saved",
        "base_name",
        "base_lat",
        "base_lon",
        "base_zoom",
        "heading_ref_deg",
        "map_auto_center_idle_sec",
        "map_tile_url",
        "map_tile_subdomains",
        "map_tile_attribution",
        "map_tile_max_native_zoom",
        "map_api_configured",
        "map_default_legal_notice",
        "config_path",
        "iface_selected",
        "scan_wifi_fast",
        "wifi_fast_supported",
        "wifi_fast_msg",
        "sniff_state",
        "sniff_msg",
        "sniff_iface",
        "sniff_idle_sec",
        "sniff_last_pkt",
        "sniff_last_err_at",
        "oobe",
        "alert_zone",
        "alert_zones",
        "settings_path",
    )
    out = {key: meta.get(key) for key in keys if key in meta}
    out["runtime_security"] = _home_runtime_security_summary(meta.get("runtime_security"))
    out["workflow"] = _home_workflow_summary(meta.get("workflow"))
    app_update = meta.get("app_update")
    if isinstance(app_update, dict) and app_update.get("completion_notice"):
        out["app_update"] = {"completion_notice": app_update.get("completion_notice")}
    return out

def _ws_push_loop() -> None:
    """Push latest state JSON to home/settings websocket clients."""
    import json as _json
    last_home_logs_seq = None
    last_home_aps_seq = None
    while True:
        time.sleep(1.0)
        home_frame = None
        settings_frame = None
        now = time.monotonic()
        dead: list[dict] = []
        with _ws_lock:
            clients = list(_ws_clients)
        for client in clients:
            sock = client.get("sock")
            if sock is None:
                dead.append(client)
                continue
            try:
                if str(client.get("mode") or "home") == "settings":
                    if now < float(client.get("next_send_at") or 0.0):
                        continue
                    if settings_frame is None:
                        settings_payload = _json.dumps(_ws_settings_runtime_payload(), ensure_ascii=False)
                        settings_frame = _ws_frame(settings_payload.encode())
                    _ws_send_client(client, settings_frame)
                    client["next_send_at"] = now + 5.0
                else:
                    if home_frame is None:
                        home_snapshot = _state_snapshot(lightweight=True)
                        logs_seq = home_snapshot.get("logs_seq")
                        aps_seq = home_snapshot.get("aps_seq")
                        if last_home_logs_seq == logs_seq:
                            home_snapshot.pop("logs", None)
                        if last_home_aps_seq == aps_seq:
                            home_snapshot.pop("aps", None)
                        home_payload = _json.dumps(home_snapshot, ensure_ascii=False)
                        home_frame = _ws_frame(home_payload.encode())
                        last_home_logs_seq = logs_seq
                        last_home_aps_seq = aps_seq
                    _ws_send_client(client, home_frame)
            except Exception:
                dead.append(client)
        if dead:
            with _ws_lock:
                for client in dead:
                    sock = client.get("sock")
                    try:
                        if sock is not None:
                            sock.close()
                    except Exception: pass
                    if client in _ws_clients:
                        _ws_clients.remove(client)

def _ws_frame(data: bytes) -> bytes:
    """Build a server-side websocket text frame (RFC 6455, no masking)."""
    n = len(data)
    if n <= 125:
        return bytes([0x81, n]) + data
    if n <= 65535:
        return bytes([0x81, 126, (n>>8)&0xFF, n&0xFF]) + data
    return bytes([0x81, 127]) + n.to_bytes(8,"big") + data

def _ws_recv_exact(sock, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("websocket disconnected")
        data.extend(chunk)
    return bytes(data)

def _ws_recv_client_frame(sock) -> tuple[int, bytes]:
    header = _ws_recv_exact(sock, 2)
    opcode = header[0] & 0x0F
    masked = bool(header[1] & 0x80)
    length = header[1] & 0x7F
    if length == 126:
        length = int.from_bytes(_ws_recv_exact(sock, 2), "big")
    elif length == 127:
        length = int.from_bytes(_ws_recv_exact(sock, 8), "big")
    if length > 1_048_576:
        raise ValueError("websocket frame too large")
    mask = _ws_recv_exact(sock, 4) if masked else b""
    payload = bytearray(_ws_recv_exact(sock, length))
    if mask:
        for index in range(len(payload)):
            payload[index] ^= mask[index % 4]
    return opcode, bytes(payload)

def _ws_send_client(client: dict, frame: bytes) -> None:
    sock = client.get("sock")
    if sock is None:
        raise ConnectionError("websocket disconnected")
    send_lock = client.get("send_lock")
    if send_lock is None:
        sock.sendall(frame)
        return
    with send_lock:
        sock.sendall(frame)


def _fmt_wall_ts(ts: float | None) -> str:
    if not ts:
        return "-"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except Exception:
        return "-"

def _state_snapshot(lightweight: bool = False) -> dict:
    """Return a JSON-serializable snapshot of current runtime state."""
    now = time.monotonic()
    now_wall = time.time()
    with state_lock:
        live_by_sn = {str(e.get("sn","")): e for e in state_table.values() if e.get("sn")}
        drones = []
        for sn in (set(history_table.keys()) | set(live_by_sn.keys())):
            sn = str(sn or "")
            cur = live_by_sn.get(sn) or {}
            hist = history_table.get(sn) or cur
            scan_type_key = _scan_type_key(cur.get("scan_type", hist.get("scan_type", "rid")))
            firmware_type_key = _firmware_type_key(cur.get("firmware_type", hist.get("firmware_type", "old")))
            if scan_type_key != "phone" and (len(sn) != 20 or (not sn.isalnum())):
                continue
            model_name = _resolve_model_name(sn, scan_type_key, cur.get("model", hist.get("model")))
            if cur:
                last_seen_ts = cur.get("last_seen_ts")
                if last_seen_ts is None:
                    last_seen_ts = now
                age = max(0.0, now - last_seen_ts)
            else:
                last_seen_wall = hist.get("last_seen_wall_ts")
                if last_seen_wall is None:
                    age = 0.0
                else:
                    try:
                        age = max(0.0, now_wall - float(last_seen_wall))
                    except Exception:
                        age = 0.0
            lost = age > LOST_TIMEOUT
            id_src = str(cur.get("id_type", hist.get("id_type","")) or "")
            sn_src = _sn_source_display(id_src)
            scan_type = _scan_type_display(scan_type_key)
            firmware_type = _firmware_type_display(firmware_type_key)
            online_dur = None
            if cur:
                if lost:
                    online_dur = cur.get("last_online_duration_sec")
                    if online_dur is None:
                        try:
                            st = cur.get("session_start_ts")
                            ls = cur.get("last_seen_ts")
                            if st is not None and ls is not None:
                                online_dur = max(0.0, float(ls) - float(st))
                        except Exception:
                            online_dur = None
                else:
                    try:
                        st = cur.get("session_start_ts", cur.get("first_seen_ts"))
                        if st is not None:
                            online_dur = max(0.0, now - float(st))
                    except Exception:
                        online_dur = None
                if online_dur is None:
                    online_dur = hist.get("last_online_duration_sec")
            else:
                online_dur = hist.get("last_online_duration_sec")
            ch = cur.get("last_ch", hist.get("last_ch")) or 0
            ch_assumed = bool(cur.get("ch_assumed", hist.get("ch_assumed")))
            cap_wall_ts = cur.get("last_capture_wall_ts", hist.get("last_capture_wall_ts"))
            if lightweight:
                drone = {
                    "sn": sn,
                    "sn_src": sn_src,
                    "uas_id": _uas_id_clean(cur.get("uas_id") or hist.get("uas_id","")),
                    "scan_type": scan_type,
                    "firmware_type": firmware_type,
                    "firmware_type_key": firmware_type_key,
                    "model": model_name,
                    "lost": lost,
                    "archived": sn not in live_by_sn,
                    "mac": cur.get("src_mac", hist.get("src_mac","")),
                    "id_type": id_src or "-",
                    "ch": f"{'~' if ch_assumed else ''}{ch}" if ch else "?",
                    "ch_assumed": ch_assumed,
                    "lat": cur.get("lat", hist.get("lat")),
                    "lon": cur.get("lon", hist.get("lon")),
                    "alt": cur.get("alt", hist.get("alt")),
                    "spd": cur.get("speed", hist.get("speed")),
                    "vspd": cur.get("vspeed", hist.get("vspeed")),
                    "pilot_lat": cur.get("pilot_lat", hist.get("pilot_lat")),
                    "pilot_lon": cur.get("pilot_lon", hist.get("pilot_lon")),
                    "pilot_alt": cur.get("pilot_alt", hist.get("pilot_alt")),
                    "pilot_loc_type": cur.get("pilot_loc_type", hist.get("pilot_loc_type")),
                    "pilot_loc_type_text": cur.get("pilot_loc_type_text", hist.get("pilot_loc_type_text","")) or "",
                    "home_lat": cur.get("home_lat", hist.get("home_lat")),
                    "home_lon": cur.get("home_lon", hist.get("home_lon")),
                    "aux_lat": cur.get("aux_lat", hist.get("aux_lat")),
                    "aux_lon": cur.get("aux_lon", hist.get("aux_lon")),
                    "pos_a_lat": cur.get("pos_a_lat", hist.get("pos_a_lat")),
                    "pos_a_lon": cur.get("pos_a_lon", hist.get("pos_a_lon")),
                    "pos_b_lat": cur.get("pos_b_lat", hist.get("pos_b_lat")),
                    "pos_b_lon": cur.get("pos_b_lon", hist.get("pos_b_lon")),
                    "rssi": cur.get("rssi", hist.get("rssi")),
                    "pkts": hist.get("pkt_count_total", cur.get("pkt_count",0)),
                    "dir": cur.get("move_dir", hist.get("move_dir")) or "-",
                    "ssid": cur.get("ssid", hist.get("ssid","")) or "",
                    "capture_type": cur.get("capture_type", hist.get("capture_type","")) or "",
                    "capture_time": _fmt_wall_ts(cap_wall_ts),
                    "last_pkt_time": _fmt_wall_ts(cap_wall_ts),
                    "scan_type_key": scan_type_key,
                    "age": round(age),
                    "age_text": _fmt_age_compact(age),
                    "online_dur": (None if online_dur is None else int(round(float(online_dur)))),
                    "first_seen": _fmt_wall_ts(hist.get("first_seen_wall_ts", cur.get("first_seen_wall_ts"))),
                    "last_seen": _fmt_wall_ts(hist.get("last_seen_wall_ts", cur.get("last_seen_wall_ts"))),
                }
                drones.append(_home_list_drone(drone))
                continue
            track_store = _sanitize_tracks(cur.get("tracks", hist.get("tracks", cur.get("track", hist.get("track", [])))) or [])
            aircraft_track_count = _track_display_count(track_store, "aircraft", firmware_type=firmware_type_key)
            operator_track_count = _track_display_count(track_store, "operator", firmware_type=firmware_type_key)
            drone = {
                "sn": sn,
                "sn_src": sn_src,
                "uas_id": _uas_id_clean(cur.get("uas_id") or hist.get("uas_id","")),
                "scan_type": scan_type,
                "firmware_type": firmware_type,
                "firmware_type_key": firmware_type_key,
                "kind": cur.get("kind", hist.get("kind")),
                "format": cur.get("format", hist.get("format")),
                "rid_format": cur.get("rid_format", hist.get("rid_format")),
                "dji_rid_kind": cur.get("dji_rid_kind", hist.get("dji_rid_kind")),
                "sub_format": cur.get("sub_format", hist.get("sub_format")),
                "parse_level": cur.get("parse_level", hist.get("parse_level")),
                "confidence": cur.get("confidence", hist.get("confidence")),
                "parse_note": cur.get("parse_note", hist.get("parse_note")),
                "raw_vendor": cur.get("raw_vendor", hist.get("raw_vendor")),
                "model": model_name,
                "lost": lost,
                "archived": sn not in live_by_sn,
                "mac": cur.get("src_mac", hist.get("src_mac","")),
                "id_type": id_src or "-",
                "ch": f"{'~' if ch_assumed else ''}{ch}" if ch else "?",
                "ch_assumed": ch_assumed,
                "lat": cur.get("lat", hist.get("lat")),
                "lon": cur.get("lon", hist.get("lon")),
                "alt": cur.get("alt", hist.get("alt")),
                "spd": cur.get("speed", hist.get("speed")),
                "vspd": cur.get("vspeed", hist.get("vspeed")),
                "pilot_lat": cur.get("pilot_lat", hist.get("pilot_lat")),
                "pilot_lon": cur.get("pilot_lon", hist.get("pilot_lon")),
                "pilot_alt": cur.get("pilot_alt", hist.get("pilot_alt")),
                "pilot_loc_type": cur.get("pilot_loc_type", hist.get("pilot_loc_type")),
                "pilot_loc_type_text": cur.get("pilot_loc_type_text", hist.get("pilot_loc_type_text","")) or "",
                "home_lat": cur.get("home_lat", hist.get("home_lat")),
                "home_lon": cur.get("home_lon", hist.get("home_lon")),
                "aux_lat": cur.get("aux_lat", hist.get("aux_lat")),
                "aux_lon": cur.get("aux_lon", hist.get("aux_lon")),
                "pos_a_lat": cur.get("pos_a_lat", hist.get("pos_a_lat")),
                "pos_a_lon": cur.get("pos_a_lon", hist.get("pos_a_lon")),
                "pos_b_lat": cur.get("pos_b_lat", hist.get("pos_b_lat")),
                "pos_b_lon": cur.get("pos_b_lon", hist.get("pos_b_lon")),
                "operator_positions": cur.get("operator_positions", hist.get("operator_positions")),
                "aircraft_position": cur.get("aircraft_position", hist.get("aircraft_position")),
                "marker_offset": cur.get("marker_offset", hist.get("marker_offset")),
                "gb_header": cur.get("gb_header", hist.get("gb_header")),
                "gb_basic_like": cur.get("gb_basic_like", hist.get("gb_basic_like")),
                "gb_version": cur.get("gb_version", hist.get("gb_version")),
                "gb_identifiers": cur.get("gb_identifiers", hist.get("gb_identifiers")),
                "operation_category": cur.get("operation_category", hist.get("operation_category")),
                "operation_category_text": cur.get("operation_category_text", hist.get("operation_category_text")),
                "aircraft_category": cur.get("aircraft_category", hist.get("aircraft_category")),
                "aircraft_category_text": cur.get("aircraft_category_text", hist.get("aircraft_category_text")),
                "track_deg": cur.get("track_deg", hist.get("track_deg")),
                "ground_speed": cur.get("ground_speed", hist.get("ground_speed")),
                "vertical_speed": cur.get("vertical_speed", hist.get("vertical_speed")),
                "alt_relative": cur.get("alt_relative", hist.get("alt_relative")),
                "alt_geoid": cur.get("alt_geoid", hist.get("alt_geoid")),
                "alt_baro": cur.get("alt_baro", hist.get("alt_baro")),
                "operation_state": cur.get("operation_state", hist.get("operation_state")),
                "operation_state_text": cur.get("operation_state_text", hist.get("operation_state_text")),
                "coord_sys": cur.get("coord_sys", hist.get("coord_sys")),
                "coord_sys_text": cur.get("coord_sys_text", hist.get("coord_sys_text")),
                "horizontal_accuracy": cur.get("horizontal_accuracy", hist.get("horizontal_accuracy")),
                "vertical_accuracy": cur.get("vertical_accuracy", hist.get("vertical_accuracy")),
                "speed_accuracy": cur.get("speed_accuracy", hist.get("speed_accuracy")),
                "timestamp_ms": cur.get("timestamp_ms", hist.get("timestamp_ms")),
                "timestamp_accuracy": cur.get("timestamp_accuracy", hist.get("timestamp_accuracy")),
                "timestamp_accuracy_text": cur.get("timestamp_accuracy_text", hist.get("timestamp_accuracy_text")),
                "rssi": cur.get("rssi", hist.get("rssi")),
                "pkts": hist.get("pkt_count_total", cur.get("pkt_count",0)),
                "dir": cur.get("move_dir", hist.get("move_dir")) or "-",
                "ssid": cur.get("ssid", hist.get("ssid","")) or "",
                "capture_type": cur.get("capture_type", hist.get("capture_type","")) or "",
                "capture_time": _fmt_wall_ts(cap_wall_ts),
                "last_pkt_time": _fmt_wall_ts(cap_wall_ts),
                "raw_packets_count": len(list(cur.get("raw_packets", hist.get("raw_packets", [])) or [])),
                "scan_type_key": scan_type_key,
                "age": round(age),
                "age_text": _fmt_age_compact(age),
                "online_dur": (None if online_dur is None else int(round(float(online_dur)))),
                "first_seen": _fmt_wall_ts(hist.get("first_seen_wall_ts", cur.get("first_seen_wall_ts"))),
                "last_seen": _fmt_wall_ts(hist.get("last_seen_wall_ts", cur.get("last_seen_wall_ts"))),
                "track_count": aircraft_track_count,
                "aircraft_track_count": aircraft_track_count,
                "operator_track_count": operator_track_count,
                "track_updated": _fmt_wall_ts(hist.get("track_updated_wall_ts", cur.get("track_updated_wall_ts"))),
            }
            drones.append(drone)
        drones.sort(key=lambda d: (d["lost"], d.get("archived", False), d["age"], d["sn"]))
        map_drones = [d for d in drones if not d.get("archived")]
    sniff_meta = _sniff_health_meta(now, now_wall)
    if simulation_scan_pause_event.is_set():
        sniff_meta = dict(sniff_meta)
        sniff_meta["state"] = "paused"
        sniff_meta["msg"] = "真实模拟发射中，扫描暂时停止；结束模拟后自动恢复"
    basic_cfg = APP_CONFIG.get("basic") if isinstance(APP_CONFIG, dict) else {}
    if not isinstance(basic_cfg, dict):
        basic_cfg = {}
    map_tile_url = str(WEB_CFG.get("map_tile_url") or "").strip()
    payload = {
        "ts": time.strftime("%H:%M:%S"),
        "server_wall_ms": int(now_wall * 1000.0),
        "ch": f"ch{current_channel}" if current_channel else "ch?",
        "drones": drones,
        "map_drones": map_drones,
        "lightweight": bool(lightweight),
        "meta": {
            "dji_lookup_url": str(WEB_CFG.get("dji_lookup_url") or ""),
            "allow_restart": bool(WEB_CFG.get("allow_restart", True)),
            "restart_args_current": " ".join(sys.argv[1:]),
            "restart_args_saved": str(WEB_CFG.get("last_restart_args") or ""),
            "base_name": str(WEB_CFG.get("base_name") or "基站"),
            "base_lat": WEB_CFG.get("base_lat"),
            "base_lon": WEB_CFG.get("base_lon"),
            "base_zoom": WEB_CFG.get("base_zoom"),
            "heading_ref_deg": WEB_CFG.get("heading_ref_deg"),
            "map_auto_center_idle_sec": WEB_CFG.get("map_auto_center_idle_sec"),
            "map_tile_url": map_tile_url,
            "map_tile_subdomains": str(WEB_CFG.get("map_tile_subdomains") or ""),
            "map_tile_attribution": str(WEB_CFG.get("map_tile_attribution") or ""),
            "map_tile_max_native_zoom": WEB_CFG.get("map_tile_max_native_zoom"),
            "map_api_configured": bool(map_tile_url),
            "map_default_legal_notice": not bool(map_tile_url),
            "config_path": APP_CONFIG_PATH or "",
            "iface_selected": (None if basic_cfg.get("iface") in (None, "") else str(basic_cfg.get("iface"))),
            "scan_wifi_fast": bool(basic_cfg.get("scan_wifi_fast")),
            "wifi_fast_supported": WIFI_FAST_SUPPORTED,
            "wifi_fast_msg": str(WIFI_FAST_SUPPORT_MSG or ""),
            "sniff_state": sniff_meta.get("state"),
            "sniff_msg": sniff_meta.get("msg"),
            "sniff_iface": sniff_meta.get("iface"),
            "sniff_idle_sec": sniff_meta.get("idle_sec"),
            "sniff_last_pkt": sniff_meta.get("last_pkt"),
            "sniff_last_err_at": sniff_meta.get("last_err_at"),
            "oobe": _oobe_state(),
            "runtime_security": _runtime_security_payload(unit_text=""),
            "alert_zone": _normalize_web_cfg({"web": {"alarm_zone": WEB_CFG.get("alarm_zone"), "alarm_zones": WEB_CFG.get("alarm_zones")}}).get("alarm_zone"),
            "alert_zones": _normalize_web_cfg({"web": {"alarm_zone": WEB_CFG.get("alarm_zone"), "alarm_zones": WEB_CFG.get("alarm_zones")}}).get("alarm_zones"),
            "app_update": _app_update_status_payload(consume_notice=True),
            "workflow": _history_reparse_workflow_snapshot(),
            "settings_path": "/settings",
        },
    }
    if lightweight:
        payload.pop("map_drones", None)
        payload["meta"] = _home_meta_summary(payload.get("meta") or {})
    if not lightweight:
        with log_lock:
            logs = list(ap_buf)[-80:]
            logs_seq = ap_seq
        aps, aps_seq, aps_total = _ap_snapshot()
        payload.update({
            "logs": logs,
            "logs_seq": logs_seq,
            "aps": aps,
            "aps_seq": aps_seq,
            "aps_total": aps_total,
            "notifications": _notification_payload(200),
        })
    return payload
