import json

from station_edition.xrs.analize_core import normalize_parse_mode, parse_raw_packet

def _snap(e: dict) -> dict:
    s = {k: e.get(k) for k in
         ("sn","src_mac","id_type","uas_id","model","lat","lon","alt","speed","vspeed","last_ch","move_dir")}
    if CHANGE_ON_RSSI: s["rssi"]  = e.get("rssi")
    if CHANGE_ON_PL:   s["pl_sig"] = e.get("pl_sig")
    return s

SCAN_DIFF_FIELDS = (
    "sn", "src_mac", "id_type", "uas_id", "model", "scan_type", "firmware_type",
    "capture_type", "ssid", "rid_format", "dji_rid_kind", "sub_format",
    "parse_level", "parse_note", "coordinate_system", "warnings",
    "last_ch", "ch_assumed", "rssi", "pl_sig",
    "lat", "lon", "alt", "speed", "vspeed",
    "pilot_lat", "pilot_lon", "pilot_alt",
    "home_lat", "home_lon", "aux_lat", "aux_lon",
    "pos_a_lat", "pos_a_lon", "pos_b_lat", "pos_b_lon",
    "operator_positions", "raw_coords", "raw_packets_count",
)
SCAN_DIFF_LABELS = {
    "scan_type": "scan",
    "firmware_type": "firmware",
    "capture_type": "capture",
    "rid_format": "format",
    "dji_rid_kind": "dji_kind",
    "sub_format": "sub_format",
    "parse_level": "parse_level",
    "parse_note": "parse_note",
    "coordinate_system": "coord_sys",
    "last_ch": "channel",
    "ch_assumed": "channel_assumed",
    "pilot_lat": "pilot_lat",
    "pilot_lon": "pilot_lon",
    "pilot_alt": "pilot_alt",
    "raw_packets_count": "raw_packets",
    "operator_positions": "operators",
    "raw_coords": "raw_coords",
}
SCAN_DIFF_NOISE_FIELDS = {"rssi", "pl_sig", "raw_packets_count"}
RID_TARGET_SN_RE = re.compile(r"^[A-Za-z0-9]{4,64}$")


def _rid_target_sn_valid(value) -> bool:
    try:
        text = str(value or "").strip()
    except Exception:
        return False
    return bool(text and RID_TARGET_SN_RE.fullmatch(text))


def _decoded_has_valid_coord(loc: dict | None, sys_loc: dict | None, meta: dict | None) -> bool:
    try:
        if isinstance(loc, dict) and _coord_pair_valid(loc.get("lat"), loc.get("lon")):
            return True
    except Exception:
        pass
    try:
        if isinstance(sys_loc, dict) and _coord_pair_valid(sys_loc.get("pilot_lat"), sys_loc.get("pilot_lon")):
            return True
    except Exception:
        pass
    for key in ("operator_positions", "raw_coords"):
        for item in list((meta or {}).get(key) or []):
            if not isinstance(item, dict):
                continue
            try:
                if _coord_pair_valid(item.get("lat"), item.get("lon")):
                    return True
            except Exception:
                continue
    return False


def _rid_realtime_candidate_valid(has_valid_coord: bool) -> bool:
    return bool(has_valid_coord)


def _copy_new_fw_detail(dst: dict, src: dict | None) -> None:
    if not isinstance(src, dict):
        return
    for key in NEW_FW_DETAIL_KEYS:
        if key in src:
            dst[key] = src.get(key)

def _role_coord_valid(item: dict | None) -> bool:
    if not isinstance(item, dict):
        return False
    try:
        return bool(_coord_pair_valid(float(item.get("lat")), float(item.get("lon"))))
    except Exception:
        return False

def _aircraft_position_from_decoded(loc: dict | None, meta: dict | None = None) -> dict | None:
    if isinstance(meta, dict):
        pos = meta.get("aircraft_position")
        if _role_coord_valid(pos):
            return dict(pos)
    if not isinstance(loc, dict) or loc.get("lat") is None or loc.get("lon") is None:
        return None
    try:
        lat = float(loc.get("lat"))
        lon = float(loc.get("lon"))
    except Exception:
        return None
    if not _coord_pair_valid(lat, lon):
        return None
    return {
        "lat": round(lat, 7),
        "lon": round(lon, 7),
        "alt": loc.get("alt_geodetic"),
        "role": "aircraft",
        "source": "ODID_LOCATION",
        "offset": None,
        "coordinate_system": "WGS84",
    }

def _operator_positions_from_decoded(sys_loc: dict | None, meta: dict | None = None) -> list[dict]:
    if isinstance(meta, dict):
        positions = [dict(x) for x in (meta.get("operator_positions") or []) if _role_coord_valid(x)]
        if positions:
            return positions
    if not isinstance(sys_loc, dict) or sys_loc.get("pilot_lat") is None or sys_loc.get("pilot_lon") is None:
        return []
    try:
        lat = float(sys_loc.get("pilot_lat"))
        lon = float(sys_loc.get("pilot_lon"))
    except Exception:
        return []
    if not _coord_pair_valid(lat, lon):
        return []
    return [{
        "lat": round(lat, 7),
        "lon": round(lon, 7),
        "alt": sys_loc.get("pilot_alt"),
        "role": "operator",
        "source": "ODID_SYSTEM",
        "offset": None,
        "coordinate_system": "WGS84",
    }]

def _apply_decoded_role_positions(dst: dict, loc: dict | None, sys_loc: dict | None, meta: dict | None = None) -> None:
    aircraft = _aircraft_position_from_decoded(loc, meta)
    if aircraft:
        dst["aircraft_position"] = aircraft
        dst["pos_a_lat"] = aircraft.get("lat")
        dst["pos_a_lon"] = aircraft.get("lon")
    operators = _operator_positions_from_decoded(sys_loc, meta)
    if operators:
        dst["operator_positions"] = operators
        first = operators[0]
        dst["pos_b_lat"] = first.get("lat")
        dst["pos_b_lon"] = first.get("lon")
    raw_coords = []
    if aircraft:
        raw_coords.append(aircraft)
    raw_coords.extend(operators)
    if raw_coords:
        dst["raw_coords"] = raw_coords


def _track_samples_from_decoded(
    decoded: dict | None,
    receive_time_ms: int | None = None,
    packet_hash: str | None = None,
) -> list[dict]:
    if not isinstance(decoded, dict):
        return []
    meta = decoded.get("metadata") if isinstance(decoded.get("metadata"), dict) else {}
    samples = _sanitize_track_samples(meta.get("track_samples") or [])
    if samples:
        out: list[dict] = []
        for sample in samples:
            item = dict(sample)
            if receive_time_ms is not None:
                item["receive_time_ms"] = int(receive_time_ms)
            if packet_hash:
                item["packet_hash"] = str(packet_hash)
            out.append(item)
        return out
    sn = ""
    basic = decoded.get("basic_id") if isinstance(decoded.get("basic_id"), dict) else {}
    if basic:
        sn = str(basic.get("uas_id") or "").strip()
    uas_id_value = _uas_id_clean(decoded.get("uas_id"))
    out: list[dict] = []
    aircraft = _aircraft_position_from_decoded(decoded.get("location"), meta)
    if aircraft:
        out.extend(_sanitize_track_samples([{
            "sample_type": "aircraft",
            "track_type": "aircraft",
            "sn": sn or None,
            "uas_id": uas_id_value,
            "lat": aircraft.get("lat"),
            "lon": aircraft.get("lon"),
            "alt": aircraft.get("alt"),
            "timestamp_ms": aircraft.get("timestamp_ms"),
            "receive_time_ms": receive_time_ms,
            "packet_hash": packet_hash,
            "source": aircraft.get("source"),
            "coordinate_system": aircraft.get("coordinate_system"),
        }]))
    for operator in _operator_positions_from_decoded(decoded.get("system"), meta):
        out.extend(_sanitize_track_samples([{
            "sample_type": "operator",
            "track_type": "operator",
            "sn": sn or None,
            "uas_id": uas_id_value,
            "lat": operator.get("lat"),
            "lon": operator.get("lon"),
            "alt": operator.get("alt"),
            "timestamp_ms": operator.get("timestamp_ms"),
            "receive_time_ms": receive_time_ms,
            "packet_hash": packet_hash,
            "source": operator.get("source"),
            "coordinate_system": operator.get("coordinate_system"),
        }]))
    return out


def state_update(src_mac: str, decoded: dict, rssi: int | None,
                 ch: int, ch_assumed: bool, pl_sig: int,
                 *, scan_type: str = "rid", ssid: str | None = None,
                 capture_type: str | None = None, raw_pkt_hex: str | None = None,
                 firmware_type: str | None = "old") -> None:
    basic = decoded.get("basic_id")
    loc   = decoded.get("location")
    sys_loc = decoded.get("system")
    meta = decoded.get("metadata") if isinstance(decoded, dict) else None
    firmware_type_key = _firmware_type_key(firmware_type)
    uas_id_value = _uas_id_clean(decoded.get("uas_id"))
    if firmware_type_key == "old":
        uas_id_value = ""

    if firmware_type_key != "old" and basic and basic.get("uas_id"):
        mac_to_basic[src_mac] = {"basic": basic, "ts": time.monotonic()}
        if len(mac_to_basic) > MAC_BASIC_CACHE_MAX:
            old = sorted(mac_to_basic.items(), key=lambda kv: kv[1].get("ts",0))
            for k,_ in old[:max(1,MAC_BASIC_CACHE_MAX//10)]: mac_to_basic.pop(k,None)

    ssid_sn = mac_to_ssid_sn.get(src_mac,{}).get("sn")
    mac_key = f"MAC:{src_mac}"

    if basic and basic.get("uas_id"):
        sn, it = basic["uas_id"].strip(), basic.get("id_type","unknown")
    elif ssid_sn:
        sn, it = ssid_sn, "SSID"
    elif firmware_type_key != "old" and src_mac in mac_to_basic:
        c  = mac_to_basic[src_mac].get("basic",{})
        sn = (c.get("uas_id","") or "").strip() or mac_key
        it = c.get("id_type","unknown")
    else:
        sn, it = mac_key, "unknown"

    scan_type_key = _scan_type_key(scan_type)
    parser_format = str(meta.get("format") or meta.get("rid_format") or "") if isinstance(meta, dict) else ""
    rid_coord_ok = _decoded_has_valid_coord(loc, sys_loc, meta if isinstance(meta, dict) else None)
    model = _resolve_model_name(sn, scan_type_key, None)
    now   = time.monotonic()
    now_wall = time.time()
    scan_diff_entry = ""
    raw_packet_to_store = None

    with state_lock:
        existing_entry = state_table.get(sn) or state_table.get(mac_key)
        if scan_type_key == "rid":
            if not _rid_target_sn_valid(sn):
                return
            if existing_entry is None and not _rid_realtime_candidate_valid(rid_coord_ok):
                return
        # MAC -> SN migration
        if sn != mac_key and mac_key in state_table and sn not in state_table:
            state_table[sn] = state_table.pop(mac_key)
            state_table[sn].update({"sn":sn, "id_type":it, "_first_printed":False})
        if sn != mac_key and mac_key in history_table:
            if sn in history_table:
                _history_merge(history_table[sn], history_table.pop(mac_key))
            else:
                history_table[sn] = history_table.pop(mac_key)
                history_table[sn]["sn"] = sn
            try:
                _history_storage_reassign_sn(mac_key, sn, HISTORY_STORE_PATH)
            except Exception:
                pass
        prev_scan_state = _scan_diff_state_snapshot(state_table.get(sn))

        created = False
        if sn not in state_table:
            created = True
            state_table[sn] = {
                "sn":sn, "src_mac":src_mac, "id_type":it, "model":model,
                "first_seen_ts":now, "last_seen_ts":now,
                "first_seen_wall_ts":now_wall, "last_seen_wall_ts":now_wall,
                "session_start_ts":now, "session_start_wall_ts":now_wall,
                "last_online_duration_sec":None,
                "last_print_ts":0.0,
                "pl_sig":None, "rssi":None, "last_ch":None, "ch_assumed":False,
                "lat":None, "lon":None, "alt":None, "speed":None, "vspeed":None,
                "pilot_lat":None, "pilot_lon":None,
                "pilot_alt":None,
                "pilot_loc_type":None, "pilot_loc_type_text":"",
                "scan_type":scan_type_key,
                "firmware_type":firmware_type_key,
                "uas_id":uas_id_value,
                "ssid":(ssid or ""),
                "capture_type":(capture_type or ""),
                "last_capture_wall_ts":now_wall,
                "raw_packets":[],
                "tracks":_empty_track_store(),
                "track":[],
                "track_updated_wall_ts":None,
                "pkt_count":0, "rx_avg":None, "last_pkt_ts":now,
                "reported_lost":False, "_last_shown":None, "_first_printed":False,
                "_prev_lat":None, "_prev_lon":None, "move_dir":None, "move_dist":None,
                "_dirty":True, "_dirty_keys":set(), "_hl":{},
                "_notify_online_sent": False,
                "_notify_last_wall_ts": 0.0,
            }

        e = state_table[sn]
        was_lost = bool(e.get("reported_lost"))
        e["last_seen_ts"]  = now
        e["last_seen_wall_ts"] = now_wall
        e["reported_lost"] = False
        if created or was_lost:
            e["session_start_ts"] = now
            e["session_start_wall_ts"] = now_wall
            e["last_online_duration_sec"] = None
        e["pkt_count"]    += 1
        if e["pkt_count"] > 1:
            iv = now - e["last_pkt_ts"]
            e["rx_avg"] = 0.3*iv + 0.7*(e["rx_avg"] or iv)
        e["last_pkt_ts"] = now
        e["id_type"] = it or e.get("id_type")
        e["model"]   = _resolve_model_name(sn, scan_type_key, e.get("model"))
        e["scan_type"] = scan_type_key
        if firmware_type_key == "new" or _firmware_type_key(e.get("firmware_type")) != "new":
            e["firmware_type"] = firmware_type_key
        if uas_id_value:
            e["uas_id"] = uas_id_value
        if firmware_type_key == "new":
            _copy_new_fw_detail(e, meta)
        if ssid is not None:
            e["ssid"] = str(ssid)
        e["capture_type"] = str(capture_type or e.get("capture_type") or "")
        e["last_capture_wall_ts"] = now_wall
        if raw_pkt_hex:
            rp = list(e.get("raw_packets") or [])
            raw_packet_to_store = {
                "ts": _fmt_wall_ts(now_wall),
                "capture_type": str(capture_type or ""),
                "firmware_type": firmware_type_key,
                "uas_id": uas_id_value,
                "_wall_ts": now_wall,
                "hex": str(raw_pkt_hex),
                "parsed": _history_packet_parsed_snapshot(decoded, firmware_type_key, "live"),
                "parse_mode": "live",
                "parse_format": parser_format or firmware_type_key,
            }
            rp.append(dict(raw_packet_to_store))
            if len(rp) > HISTORY_RAW_PACKET_SNAPSHOT_LIMIT:
                rp = rp[-HISTORY_RAW_PACKET_SNAPSHOT_LIMIT:]
            e["raw_packets"] = rp

        if CHANGE_ON_PL:   e["pl_sig"] = pl_sig
        if rssi is not None:
            old = e.get("rssi")
            if old is None or not CHANGE_ON_RSSI or abs(rssi-old)>=RSSI_DELTA:
                e["rssi"] = rssi
        if ch:
            e["last_ch"]   = ch
            e["ch_assumed"] = bool(ch_assumed)

        new_fw_base = _web_base_coord_pair() if firmware_type_key == "new" else None
        if loc:
            cands = loc.get("_cands") if isinstance(loc, dict) else None
            if cands and e.get("lat") is not None and e.get("lon") is not None:
                prev_lat = float(e.get("lat"))
                prev_lon = float(e.get("lon"))
                best_c = None
                best_d = None
                cur_d = None
                try:
                    if loc.get("lat") is not None and loc.get("lon") is not None:
                        cur_d = _haversine(prev_lat, prev_lon, float(loc["lat"]), float(loc["lon"]))
                except Exception:
                    cur_d = None
                for c in cands:
                    try:
                        lat_c = float(c.get("lat"))
                        lon_c = float(c.get("lon"))
                    except Exception:
                        continue
                    d_c = _haversine(prev_lat, prev_lon, lat_c, lon_c)
                    if best_d is None or d_c < best_d:
                        best_d = d_c
                        best_c = c
                if best_c is not None and (cur_d is None or (best_d is not None and best_d + 50.0 < cur_d)):
                    loc = best_c
            if firmware_type_key == "new" and parser_format != "GB46750_2025":
                try:
                    cur_lat = None if e.get("lat") is None else float(e.get("lat"))
                    cur_lon = None if e.get("lon") is None else float(e.get("lon"))
                    ref_lat = new_fw_base[0] if new_fw_base else None
                    ref_lon = new_fw_base[1] if new_fw_base else None
                    if loc.get("lat") is not None and loc.get("lon") is not None:
                        if _new_fw_coord_anomalous(float(loc.get("lat")), float(loc.get("lon")),
                                                   prev_lat=cur_lat, prev_lon=cur_lon,
                                                   ref_lat=ref_lat, ref_lon=ref_lon):
                            loc = None
                except Exception:
                    loc = None

            if loc:
                nlat, nlon = loc.get("lat"), loc.get("lon")
                if nlat is not None and nlon is not None and (abs(nlat)>0.001 or abs(nlon)>0.001):
                    if e["lat"] is not None:
                        e["_prev_lat"], e["_prev_lon"] = e["lat"], e["lon"]
                    e["lat"], e["lon"] = nlat, nlon
                    if e.get("_prev_lat") is not None:
                        d = _haversine(e["_prev_lat"],e["_prev_lon"],nlat,nlon)
                        if d >= HEADING_MIN_MOVE_M:
                            b = _bearing(e["_prev_lat"],e["_prev_lon"],nlat,nlon)
                            if b is not None:
                                e["move_dir"]  = _bearing8(b)
                                e["move_dist"] = d
                e["alt"]    = loc.get("alt_geodetic")
                e["speed"]  = loc.get("speed_ms")
                e["vspeed"] = loc.get("vspeed_ms")
                if loc.get("direction_deg") is not None:
                    e["move_dir"] = loc.get("direction_deg")
                if firmware_type_key == "new":
                    for key, src_key in (
                        ("track_deg", "direction_deg"),
                        ("ground_speed", "speed_ms"),
                        ("vertical_speed", "vspeed_ms"),
                        ("alt_relative", "relative_alt"),
                        ("alt_geoid", "alt_geodetic"),
                        ("alt_baro", "alt_baro"),
                        ("horizontal_accuracy", "horizontal_accuracy"),
                        ("vertical_accuracy", "vertical_accuracy"),
                        ("speed_accuracy", "speed_accuracy"),
                        ("horizontal_accuracy_text", "horizontal_accuracy_text"),
                        ("vertical_accuracy_text", "vertical_accuracy_text"),
                        ("speed_accuracy_text", "speed_accuracy_text"),
                        ("timestamp_ms", "timestamp_ms"),
                        ("timestamp_accuracy", "timestamp_accuracy"),
                        ("timestamp_accuracy_text", "timestamp_accuracy_text"),
                    ):
                        if loc.get(src_key) is not None:
                            e[key] = loc.get(src_key)

        if sys_loc and (sys_loc.get("pilot_lat") is not None) and (sys_loc.get("pilot_lon") is not None):
            try:
                plat = float(sys_loc.get("pilot_lat"))
                plon = float(sys_loc.get("pilot_lon"))
                if firmware_type_key == "new":
                    cur_lat = None if e.get("lat") is None else float(e.get("lat"))
                    cur_lon = None if e.get("lon") is None else float(e.get("lon"))
                    ref_lat = new_fw_base[0] if new_fw_base else None
                    ref_lon = new_fw_base[1] if new_fw_base else None
                    if _new_fw_coord_anomalous(plat, plon,
                                               prev_lat=cur_lat, prev_lon=cur_lon,
                                               ref_lat=ref_lat, ref_lon=ref_lon):
                        raise ValueError("pilot coord anomaly")
                if (-90.0 <= plat <= 90.0) and (-180.0 <= plon <= 180.0):
                    e["pilot_lat"] = plat
                    e["pilot_lon"] = plon
                    e["pilot_alt"] = sys_loc.get("pilot_alt")
                    e["pilot_loc_type"] = sys_loc.get("pilot_loc_type")
                    e["pilot_loc_type_text"] = str(sys_loc.get("pilot_loc_type_text") or "")
            except Exception:
                pass

        _apply_decoded_role_positions(e, loc, sys_loc, meta if isinstance(meta, dict) else None)
        track_samples = _track_samples_from_decoded(decoded, int(now_wall * 1000.0), packet_hash=str(pl_sig))
        e["track_samples"] = track_samples
        e["tracks"] = _sanitize_tracks(e.get("tracks") or e.get("track") or [])
        for sample in track_samples:
            _track_store_append_sample(e["tracks"], sample)
        e["track"] = _track_store_primary(e["tracks"], "aircraft")
        last_aircraft = e["tracks"].get("last_aircraft")
        if isinstance(last_aircraft, dict):
            e["track_updated_wall_ts"] = float((last_aircraft.get("receive_time_ms") or last_aircraft.get("timestamp_ms") or 0) / 1000.0)

        alarm_zone_hits = _alarm_zone_names_for_point(e.get("lat"), e.get("lon"))
        prev_alarm_zone_hits = {str(x) for x in (e.get("_alarm_zone_hits_current") or [])}
        new_alarm_zone_hits = [z for z in alarm_zone_hits if str(z) not in prev_alarm_zone_hits]
        e["_alarm_zone_hits_current"] = list(alarm_zone_hits)
        e["alarm_zone_hits"] = list(alarm_zone_hits)

        _history_touch(e, now, now_wall)
        h_notify = history_table.get(sn) or {}

        notify_event_title = None
        sn_now = str(e.get("sn",""))
        skip_mac_only = bool(NOTIFY_CFG.get("skip_mac_only", True))
        if not (skip_mac_only and sn_now.startswith("MAC:")):
            if not bool(h_notify.get("notify_first_online_sent")):
                notify_event_title = "上线"
                h_notify["notify_first_online_sent"] = True
                h_notify["notify_last_wall_ts"] = now_wall
                _history_mark_dirty()
            elif was_lost and bool(NOTIFY_CFG.get("notify_reonline", True)):
                last_nt = float(h_notify.get("notify_last_wall_ts") or 0.0)
                cd_sec = float(NOTIFY_CFG.get("reonline_cooldown_sec") or NOTIFY_REONLINE_COOLDOWN_DEFAULT)
                if (now_wall - last_nt) >= max(0.0, cd_sec):
                    notify_event_title = "重新上线"
                    h_notify["notify_last_wall_ts"] = now_wall
                    _history_mark_dirty()
        notify_payload = dict(e) if notify_event_title else None
        zone_notify_payload = None
        zone_notify_names: list[str] = []
        if new_alarm_zone_hits and not (skip_mac_only and sn_now.startswith("MAC:")):
            zone_notify_payload = dict(e)
            zone_notify_names = list(new_alarm_zone_hits)

        _SNAP_TO_COL = {"lat":"lat_s","lon":"lon_s","alt":"alt_s","speed":"spd_s",
                        "vspeed":"vsp_s","last_ch":"ch_s","move_dir":"dir_s",
                        "rssi":"rssi_s","model":"model","sn":"sn_s","uas_id":"uas_id"}
        cur     = _snap(e)
        changed = {k for k,v in cur.items() if (e.get("_last_shown") or {}).get(k)!=v}
        if changed:
            e["_dirty"] = True
            e["_dirty_keys"].update(changed)
            hl_until = now + 3.0
            if "_hl" not in e: e["_hl"] = {}
            for k in changed:
                e["_hl"][_SNAP_TO_COL.get(k, k)] = hl_until

        elapsed = now - e.get("last_print_ts", 0.0)
        do_print = False
        reason   = ""
        if not e.get("_first_printed"):
            do_print, reason = True, "first"
        elif e.get("_dirty") and elapsed >= MIN_GAP:
            do_print = True
            reason = "changed" if changed else "tick"
        elif e.get("_dirty") and elapsed >= PRINT_INTERVAL:
            do_print, reason = True, "heartbeat"

        if do_print:
            _emit_log(e, set(e.get("_dirty_keys") or set()), reason)
            e["last_print_ts"]  = now
            e["_last_shown"]    = cur
            e["_first_printed"] = True
            e["_dirty"]         = False
            e["_dirty_keys"]    = set()

        next_scan_state = _scan_diff_state_snapshot(e)
        if created or was_lost or prev_scan_state != next_scan_state:
            changed_keys = _scan_diff_changed_keys(prev_scan_state, next_scan_state)
            if created or was_lost or any(key not in SCAN_DIFF_NOISE_FIELDS for key in changed_keys):
                diff_reason = "first" if created else ("reonline" if was_lost else "changed")
                scan_diff_entry = _build_scan_diff_entry(prev_scan_state, next_scan_state, reason=diff_reason)

    if notify_payload is not None and notify_event_title:
        _notification_add(_notify_online_text(notify_payload, notify_event_title, now_wall), "ok", "rid")
        queue_online_notification(notify_payload, notify_event_title, now_wall=now_wall)
    if zone_notify_payload is not None and zone_notify_names:
        _notification_add(_notify_zone_alarm_text(zone_notify_payload, zone_notify_names, now_wall), "warn", "rid")
        queue_zone_alarm_notification(zone_notify_payload, zone_notify_names, now_wall=now_wall)
    if raw_packet_to_store is not None:
        try:
            _history_storage_append_raw_packet(sn, raw_packet_to_store, HISTORY_STORE_PATH)
        except Exception as exc:
            _log(f"[WARN] raw packet database append failed for {sn}: {exc}")
    if scan_diff_entry:
        _scan_diff(scan_diff_entry)

def _emit_log(e: dict, changed_keys: set, reason: str) -> None:
    sn    = str(e.get("sn",""))
    model = str(e.get("model","N/A"))
    it    = str(e.get("id_type",""))
    mac   = str(e.get("src_mac",""))
    uas   = _uas_id_clean(e.get("uas_id"))
    lat   = _fmt(e.get("lat"),".6f")
    lon   = _fmt(e.get("lon"),".6f")
    alt   = _fmt(e.get("alt"),".1f","m")
    spd   = _fmt(e.get("speed"),".2f","m/s")
    vsp   = _fmt(e.get("vspeed"),".1f","m/s")
    rssi  = _fmt(e.get("rssi"),"d","dBm")
    ch    = e.get("last_ch") or 0
    ch_s  = f"{'~' if e.get('ch_assumed') else ''}ch{ch}" if ch else "ch?"
    pkts  = e.get("pkt_count",0)
    avg   = e.get("rx_avg")
    avg_s = f"{avg:.1f}s" if avg else "N/A"
    mv    = e.get("move_dir")
    md    = e.get("move_dist")
    mv_s  = f" dir={mv} d={md:.1f}m" if mv and md else ""
    uas_s = f" uas={uas}" if uas else ""
    pfx   = "★" if reason=="first" else "→"
    _log(f"{pfx} SN={sn}{uas_s} model={model} id={it} MAC={mac} "
         f"loc={lat},{lon} alt={alt} spd={spd} vspd={vsp} rssi={rssi} {ch_s} "
         f"pkts={pkts} avg={avg_s}{mv_s}")

# -----------------------------------------------------------------------------
# Lost checker
# -----------------------------------------------------------------------------
def lost_checker() -> None:
    while True:
        time.sleep(1.0)
        now = time.monotonic()
        with state_lock:
            for sn, e in list(state_table.items()):
                age = now - e["last_seen_ts"]
                if age > LOST_TIMEOUT and not e["reported_lost"]:
                    dur = None
                    try:
                        st = e.get("session_start_ts")
                        ls = e.get("last_seen_ts")
                        if st is not None and ls is not None:
                            dur = max(0.0, float(ls) - float(st))
                    except Exception:
                        dur = None
                    if dur is None:
                        try:
                            stw = e.get("session_start_wall_ts")
                            lsw = e.get("last_seen_wall_ts")
                            if stw is not None and lsw is not None:
                                dur = max(0.0, float(lsw) - float(stw))
                        except Exception:
                            dur = None
                    if dur is not None:
                        e["last_online_duration_sec"] = dur
                        h = history_table.get(sn)
                        if h is not None:
                            h["last_online_duration_sec"] = dur
                            _history_mark_dirty()
                    _log(f"[LOST] SN={sn!r} unseen {age:.0f}s MAC={e.get('src_mac')}")
                    _notification_add(_notify_lost_text(e, age, time.time()), "warn", "rid")
                    e["reported_lost"] = True
                if e["reported_lost"] and age > PURGE_TIMEOUT:
                    del state_table[sn]

# -----------------------------------------------------------------------------
# HTTP + WebSocket service (port 4600)
# -----------------------------------------------------------------------------
HTTP_PORT = 4600

# Connected websocket clients
_ws_clients: list[dict] = []
_ws_lock = Lock()

def _api_iso_now(ts: float | None = None) -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts if ts is not None else time.time()))
    except Exception:
        return ""

def _load_build_info() -> dict:
    paths: list[str] = [_app_file_path(BUILD_INFO_FILE)]
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        paths.append(os.path.join(str(frozen_root), BUILD_INFO_FILE))
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(os.path.abspath(str(path or "")))
        if not key or key in seen:
            continue
        seen.add(key)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            continue
    return {}

def _api_meta() -> dict:
    auth_configured = _auth_hashes_present(AUTH_CFG)
    api_configured = _api_tokens_have_secret(API_CFG)
    public_enabled = bool(API_CFG.get("enabled")) and bool(_auth_enabled()) and auth_configured and api_configured
    login_methods = _auth_login_methods()
    return {
        "name": API_NAME,
        "version": API_VERSION,
        "app_version": _app_version_label(),
        "time": _api_iso_now(),
        "web_auth": {
            "type": "login+session",
            "enabled": bool(_auth_enabled()),
            "configured": bool(auth_configured),
            "realm": str(AUTH_CFG.get("realm") or "XRS"),
            "session_ttl_min": int(AUTH_CFG.get("session_ttl_min") or 30),
            "login_methods": login_methods,
        },
        "public_api": {
            "enabled": bool(public_enabled),
            "configured": bool(api_configured),
            "header": "X-API-Token",
            "authorization": "Bearer <token>",
            "token_count": len(_api_tokens_public(API_CFG)),
            "supports_multiple_tokens": True,
            "supports_single_use": True,
            "supports_never_expires": True,
            "whitelist_enabled": bool(API_CFG.get("whitelist_enabled")),
            "whitelist_count": len(API_CFG.get("whitelist") or []),
            "mode_when_disabled": "page-session-only",
        },
    }

def _api_endpoint_index() -> list[dict]:
    return [
        {"method": "GET", "path": "/api/docs", "desc": "API docs and auth guide"},
        {"method": "GET", "path": "/api/health", "desc": "Service health"},
        {"method": "GET", "path": "/api/v1/", "desc": "API v1 home and auth summary"},
        {"method": "GET", "path": "/api/v1/snapshot", "desc": "Full runtime snapshot"},
        {"method": "GET", "path": "/api/v1/auth/status", "desc": "Auth status"},
        {"method": "POST", "path": "/api/v1/auth/sso-links/create", "desc": "Create SSO login link"},
        {"method": "GET", "path": "/api/v1/drones", "desc": "Drone list"},
        {"method": "GET", "path": "/api/v1/drones/{sn}", "desc": "Drone detail"},
        {"method": "GET", "path": "/api/v1/tracks/{sn}", "desc": "Track by SN"},
        {"method": "GET", "path": "/api/v1/aps", "desc": "Realtime AP list"},
        {"method": "GET", "path": "/api/v1/metrics?window=12h|24h|7d", "desc": "Host metrics for token API clients"},
        {"method": "GET", "path": "/api/v1/logs?type=event|scan|ap&limit=200", "desc": "Logs"},
        {"method": "GET", "path": "/api/simulation/status", "desc": "Ephemeral simulation status (page session)"},
        {"method": "POST", "path": "/api/simulation/start", "desc": "Start ephemeral target simulation (page session)"},
        {"method": "POST", "path": "/api/simulation/stop", "desc": "Stop and clear simulated targets (page session)"},
        {"method": "GET", "path": "/api/settings/export/settings", "desc": "Export settings file"},
        {"method": "GET", "path": "/api/settings/export/scan-data", "desc": "Export scan data"},
        {"method": "POST", "path": "/api/settings/import/settings", "desc": "Import settings file"},
        {"method": "POST", "path": "/api/settings/import/scan-data", "desc": "Import scan data"},
        {"method": "GET", "path": "/api/logs/view?type=runtime|operation|scan|scan_diff|ap|system", "desc": "Built-in page log viewer"},
        {"method": "GET", "path": "/api/logs/export?type=all|runtime|operation|scan|scan_diff|ap|system", "desc": "Built-in page log export"},
        {"method": "POST", "path": "/api/v1/history/clear", "desc": "Clear history cache"},
        {"method": "POST", "path": "/api/v1/history/delete", "desc": "Delete one history item"},
        {"method": "GET", "path": "/api/v1/history/reidentify-status", "desc": "Background history reidentify workflow status"},
        {"method": "POST", "path": "/api/v1/history/reidentify-recent", "desc": "Queue recent history raw packets for background reidentify"},
        {"method": "POST", "path": "/api/v1/tracks/clear", "desc": "Clear tracks"},
        {"method": "POST", "path": "/api/v1/config/reload", "desc": "Reload config file"},
    ]