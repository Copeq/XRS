"""History merge / raw-packet decode / reparse / reidentify workers.

Extracted from process_core.py during backend module split. Loaded into the assembled
runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES) right after process_core.py;
state/history globals and sibling chunk functions resolve at call time.
"""

def _history_packet_parsed_snapshot(
    decoded: dict | None,
    firmware_type: str | None = None,
    used_mode: str | None = None,
) -> dict | None:
    if not isinstance(decoded, dict):
        return None
    snapshot = {
        "basic_id": decoded.get("basic_id"),
        "location": decoded.get("location"),
        "system": decoded.get("system"),
        "metadata": decoded.get("metadata"),
        "uas_id": decoded.get("uas_id"),
        "firmware_type": _firmware_type_key(firmware_type),
    }
    mode_text = str(used_mode or "").strip()
    if mode_text:
        snapshot["mode"] = mode_text
    try:
        return json.loads(json.dumps(snapshot, ensure_ascii=False, default=str))
    except Exception:
        return None

def _history_track_updated_wall_ts(raw_tracks) -> float | None:
    tracks = _sanitize_tracks(raw_tracks)
    last_aircraft = tracks.get("last_aircraft")
    if isinstance(last_aircraft, dict):
        try:
            recv_ms = last_aircraft.get("receive_time_ms")
            if recv_ms:
                return float(recv_ms) / 1000.0
            ts_ms = last_aircraft.get("timestamp_ms")
            if ts_ms:
                return float(ts_ms) / 1000.0
        except Exception:
            return None
    return None

def _history_copy_tracks(dst: dict, src: dict | None) -> None:
    tracks = _sanitize_tracks((src or {}).get("tracks") or (src or {}).get("track") or [])
    dst["tracks"] = tracks
    dst["track"] = _track_store_primary(tracks, "aircraft")
    track_ts = (src or {}).get("track_updated_wall_ts")
    if track_ts is None:
        track_ts = _history_track_updated_wall_ts(tracks)
    dst["track_updated_wall_ts"] = track_ts

def _history_merge_tracks(dst: dict, src: dict | None) -> None:
    merged = _sanitize_tracks(dst)
    incoming = _sanitize_tracks(src)
    for track_type in ("aircraft", "operator"):
        cur_seq = list(merged.get(track_type) or [])
        next_seq = list(incoming.get(track_type) or [])
        use_incoming = len(next_seq) > len(cur_seq)
        if not use_incoming and next_seq and len(next_seq) == len(cur_seq):
            cur_last = merged.get(f"last_{track_type}") or {}
            next_last = incoming.get(f"last_{track_type}") or {}
            cur_ts = max(int(cur_last.get("receive_time_ms") or 0), int(cur_last.get("timestamp_ms") or 0))
            next_ts = max(int(next_last.get("receive_time_ms") or 0), int(next_last.get("timestamp_ms") or 0))
            use_incoming = next_ts > cur_ts
        if use_incoming:
            _track_store_set_sequence(merged, track_type, next_seq)
    dst["tracks"] = merged
    dst["track"] = _track_store_primary(merged, "aircraft")
    dst_ts = dst.get("track_updated_wall_ts")
    src_ts = (src or {}).get("track_updated_wall_ts")
    computed_ts = _history_track_updated_wall_ts(merged)
    candidates = [x for x in (dst_ts, src_ts, computed_ts) if x not in (None, "")]
    dst["track_updated_wall_ts"] = max(candidates) if candidates else None

def _history_merge(dst: dict, src: dict) -> None:
    if not src:
        return
    if src.get("first_seen_ts") is not None:
        if dst.get("first_seen_ts") is None or src["first_seen_ts"] < dst["first_seen_ts"]:
            dst["first_seen_ts"] = src["first_seen_ts"]
    if src.get("first_seen_wall_ts") is not None:
        if dst.get("first_seen_wall_ts") is None or src["first_seen_wall_ts"] < dst["first_seen_wall_ts"]:
            dst["first_seen_wall_ts"] = src["first_seen_wall_ts"]
    if src.get("last_seen_ts") is not None:
        if dst.get("last_seen_ts") is None or src["last_seen_ts"] > dst["last_seen_ts"]:
            dst["last_seen_ts"] = src["last_seen_ts"]
    if src.get("last_seen_wall_ts") is not None:
        if dst.get("last_seen_wall_ts") is None or src["last_seen_wall_ts"] > dst["last_seen_wall_ts"]:
            dst["last_seen_wall_ts"] = src["last_seen_wall_ts"]
    if bool(src.get("notify_first_online_sent")):
        dst["notify_first_online_sent"] = True
    src_nt = src.get("notify_last_wall_ts")
    dst_nt = dst.get("notify_last_wall_ts")
    if src_nt is not None and (dst_nt is None or float(src_nt) > float(dst_nt)):
        dst["notify_last_wall_ts"] = src_nt
    src_lod = src.get("last_online_duration_sec")
    if src_lod is not None:
        src_last_wall = float(src.get("last_seen_wall_ts") or 0.0)
        dst_last_wall = float(dst.get("last_seen_wall_ts") or 0.0)
        if dst.get("last_online_duration_sec") is None or src_last_wall >= dst_last_wall:
            dst["last_online_duration_sec"] = src_lod
    if src.get("ssid"):
        dst["ssid"] = src.get("ssid")
    if src.get("capture_type"):
        dst["capture_type"] = src.get("capture_type")
    src_uas = _uas_id_clean(src.get("uas_id"))
    if src_uas:
        dst["uas_id"] = src_uas
    src_fw = _firmware_type_key(src.get("firmware_type"))
    dst_fw = _firmware_type_key(dst.get("firmware_type"))
    if src_fw == "new" or not dst_fw:
        dst["firmware_type"] = src_fw
    if src.get("pilot_lat") is not None and src.get("pilot_lon") is not None:
        dst["pilot_lat"] = src.get("pilot_lat")
        dst["pilot_lon"] = src.get("pilot_lon")
        dst["pilot_loc_type"] = src.get("pilot_loc_type")
        dst["pilot_loc_type_text"] = src.get("pilot_loc_type_text")
    _copy_new_fw_detail(dst, src)
    src_cap_ts = src.get("last_capture_wall_ts")
    dst_cap_ts = dst.get("last_capture_wall_ts")
    if src_cap_ts is not None and (dst_cap_ts is None or float(src_cap_ts) > float(dst_cap_ts)):
        dst["last_capture_wall_ts"] = src_cap_ts
    src_rp = list(src.get("raw_packets") or [])
    if src_rp:
        dst_rp = list(dst.get("raw_packets") or [])
        merged = (dst_rp + src_rp)[-HISTORY_RAW_PACKET_SNAPSHOT_LIMIT:]
        dst["raw_packets"] = merged
    _history_merge_tracks(dst, src)
    src_st = _scan_type_key(src.get("scan_type"))
    if src_st and (not dst.get("scan_type")):
        dst["scan_type"] = src_st
    dst["pkt_count_total"] = dst.get("pkt_count_total", 0) + src.get("pkt_count_total", 0)

def _history_touch(e: dict, now: float, now_wall: float) -> None:
    sn = str(e.get("sn",""))
    if not sn:
        return
    h = history_table.get(sn)
    if h is None:
        h = {
            "sn": sn,
            "first_seen_ts": e.get("first_seen_ts", now),
            "first_seen_wall_ts": e.get("first_seen_wall_ts", now_wall),
            "last_seen_ts": now,
            "last_seen_wall_ts": now_wall,
            "pkt_count_total": 0,
            "notify_first_online_sent": False,
            "notify_last_wall_ts": 0.0,
            "last_online_duration_sec": e.get("last_online_duration_sec"),
            "ssid": e.get("ssid"),
            "capture_type": e.get("capture_type"),
            "uas_id": _uas_id_clean(e.get("uas_id")),
            "firmware_type": _firmware_type_key(e.get("firmware_type")),
            "pilot_lat": e.get("pilot_lat"),
            "pilot_lon": e.get("pilot_lon"),
            "pilot_loc_type": e.get("pilot_loc_type"),
            "pilot_loc_type_text": e.get("pilot_loc_type_text"),
            "pilot_alt": e.get("pilot_alt"),
            "last_capture_wall_ts": e.get("last_capture_wall_ts"),
            "raw_packets": list(e.get("raw_packets") or [])[-HISTORY_RAW_PACKET_SNAPSHOT_LIMIT:],
            "scan_type": _scan_type_key(e.get("scan_type")),
            "tracks": _sanitize_tracks(e.get("tracks") or e.get("track") or []),
            "track": _track_store_primary(e.get("tracks") or e.get("track") or [], "aircraft"),
            "track_updated_wall_ts": e.get("track_updated_wall_ts"),
        }
        history_table[sn] = h
    h["sn"] = sn
    h["src_mac"] = e.get("src_mac")
    h["id_type"] = e.get("id_type")
    h["model"] = _resolve_model_name(sn, e.get("scan_type"), e.get("model"))
    h["last_ch"] = e.get("last_ch")
    h["ch_assumed"] = e.get("ch_assumed")
    h["lat"] = e.get("lat")
    h["lon"] = e.get("lon")
    h["alt"] = e.get("alt")
    h["speed"] = e.get("speed")
    h["vspeed"] = e.get("vspeed")
    h["pilot_lat"] = e.get("pilot_lat")
    h["pilot_lon"] = e.get("pilot_lon")
    h["pilot_loc_type"] = e.get("pilot_loc_type")
    h["pilot_loc_type_text"] = e.get("pilot_loc_type_text")
    _copy_new_fw_detail(h, e)
    h["rssi"] = e.get("rssi")
    h["move_dir"] = e.get("move_dir")
    h["ssid"] = e.get("ssid")
    h["capture_type"] = e.get("capture_type")
    h["uas_id"] = _uas_id_clean(e.get("uas_id"))
    h["firmware_type"] = _firmware_type_key(e.get("firmware_type"))
    h["last_capture_wall_ts"] = e.get("last_capture_wall_ts")
    h["raw_packets"] = list(e.get("raw_packets") or [])[-HISTORY_RAW_PACKET_SNAPSHOT_LIMIT:]
    h["scan_type"] = _scan_type_key(e.get("scan_type"))
    _history_copy_tracks(h, e)
    h["last_seen_ts"] = now
    h["last_seen_wall_ts"] = now_wall
    h["pkt_count_total"] = h.get("pkt_count_total", 0) + 1
    h.setdefault("notify_first_online_sent", False)
    h.setdefault("notify_last_wall_ts", 0.0)
    h.setdefault("last_online_duration_sec", e.get("last_online_duration_sec"))
    h.setdefault("pilot_lat", e.get("pilot_lat"))
    h.setdefault("pilot_lon", e.get("pilot_lon"))
    h.setdefault("pilot_loc_type", e.get("pilot_loc_type"))
    h.setdefault("pilot_loc_type_text", e.get("pilot_loc_type_text"))
    h.setdefault("pilot_alt", e.get("pilot_alt"))
    h.setdefault("raw_packets", list(e.get("raw_packets") or [])[-HISTORY_RAW_PACKET_SNAPSHOT_LIMIT:])
    h.setdefault("scan_type", _scan_type_key(e.get("scan_type")))
    h.setdefault("uas_id", _uas_id_clean(e.get("uas_id")))
    h.setdefault("firmware_type", _firmware_type_key(e.get("firmware_type")))
    h.setdefault("tracks", _sanitize_tracks(e.get("tracks") or e.get("track") or []))
    h.setdefault("track", _track_store_primary(h.get("tracks"), "aircraft"))
    h.setdefault("track_updated_wall_ts", e.get("track_updated_wall_ts"))
    _history_mark_dirty()

def _history_raw_packet_wall_ts(raw: dict, fallback: float | None = None) -> float:
    if isinstance(raw, dict):
        ts_text = str(raw.get("ts") or "").strip()
        if ts_text and ts_text != "-":
            try:
                return float(time.mktime(time.strptime(ts_text, "%Y-%m-%d %H:%M:%S")))
            except Exception:
                pass
    try:
        return float(fallback or 0.0)
    except Exception:
        return 0.0

def _history_recent_raw_packet_candidates_locked(limit: int | None = None) -> list[dict]:
    try:
        per_aircraft_limit = int(limit)
    except Exception:
        per_aircraft_limit = _track_store_points_limit()
    per_aircraft_limit = max(1, min(per_aircraft_limit, _track_store_points_limit()))
    out: list[dict] = []
    seq = 0
    for sn, hist in history_table.items():
        if not isinstance(hist, dict):
            continue
        fallback_ts = hist.get("last_capture_wall_ts") or hist.get("last_seen_wall_ts") or 0.0
        raw_packets = _history_storage_fetch_raw_packets(sn, per_aircraft_limit, newest_first=True, path=HISTORY_STORE_PATH)
        if not raw_packets:
            raw_packets = list(hist.get("raw_packets") or [])[-per_aircraft_limit:]
            for item in raw_packets:
                if isinstance(item, dict) and "_wall_ts" not in item:
                    item["_wall_ts"] = fallback_ts
        for packet_index, raw in enumerate(raw_packets):
            seq += 1
            if not isinstance(raw, dict):
                continue
            if not str(raw.get("hex") or "").strip():
                continue
            wall_ts = _history_raw_packet_wall_ts(raw, fallback_ts)
            out.append({
                "wall_ts": wall_ts,
                "seq": seq,
                "sn": str(sn or ""),
                "hist": dict(hist),
                "raw": dict(raw),
                "packet_index": packet_index,
                "packet_count": len(raw_packets),
            })
    out.sort(key=lambda x: (str(x.get("sn") or ""), float(x.get("wall_ts") or 0.0), int(x.get("seq") or 0)))
    return out


def _history_storage_fetch_recent_raw_packets_by_sn(sns: list[str], limit: int, path: str | None = None) -> dict[str, list[dict]]:
    clean_sns: list[str] = []
    seen: set[str] = set()
    for sn in sns or []:
        text = str(sn or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        clean_sns.append(text)
    if not clean_sns:
        return {}
    try:
        per_sn_limit = max(1, int(limit or 1))
    except Exception:
        per_sn_limit = 1
    db_path = os.path.abspath(str(path or HISTORY_STORE_PATH or _history_store_default_path()))
    if not os.path.exists(db_path):
        return {}
    placeholders = ",".join("?" for _ in clean_sns)
    sql = (
        "WITH ranked AS ("
        "SELECT id, sn, capture_wall_ts, capture_time_text, capture_type, firmware_type, uas_id, payload, hex_text, decoded_json, parse_mode, parse_format, "
        "ROW_NUMBER() OVER (PARTITION BY sn ORDER BY capture_wall_ts DESC, id DESC) AS rn "
        "FROM raw_packets WHERE sn IN (" + placeholders + ")"
        ") "
        "SELECT id, sn, capture_wall_ts, capture_time_text, capture_type, firmware_type, uas_id, payload, hex_text, decoded_json, parse_mode, parse_format "
        "FROM ranked WHERE rn <= ? ORDER BY sn ASC, capture_wall_ts ASC, id ASC"
    )
    args = list(clean_sns) + [per_sn_limit]
    conn = None
    try:
        _log(f"[INFO] history raw packet bulk fetch open: sns={len(clean_sns)} limit={per_sn_limit}")
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        _log("[INFO] history raw packet bulk fetch query")
        rows = conn.execute(sql, args).fetchall()
        _log(f"[INFO] history raw packet bulk fetch rows={len(rows)}")
    except Exception as exc:
        _log(f"[WARN] history raw packet bulk fetch failed: {exc}")
        return {}
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
    out: dict[str, list[dict]] = {}
    for row in rows:
        item = _history_storage_packet_row_to_dict(row)
        sn = str((row["sn"] if isinstance(row, sqlite3.Row) else row[1]) or "")
        out.setdefault(sn, []).append(item)
    return out


def _history_recent_raw_packet_candidates(limit: int | None = None) -> list[dict]:
    try:
        per_aircraft_limit = int(limit)
    except Exception:
        per_aircraft_limit = _track_store_points_limit()
    per_aircraft_limit = max(1, min(per_aircraft_limit, _track_store_points_limit()))
    started_at = time.perf_counter()
    _log(f"[INFO] history reparse candidate collect start: limit={per_aircraft_limit}")
    with state_lock:
        history_items = [
            (str(sn or ""), dict(hist))
            for sn, hist in history_table.items()
            if isinstance(hist, dict)
            and (_scan_type_key(hist.get("scan_type")) == "phone" or (len(str(sn or "")) == 20 and str(sn or "").isalnum()))
        ]
    _log(f"[INFO] history reparse candidate collect copied: aircraft={len(history_items)} elapsed={time.perf_counter() - started_at:.2f}s")
    raw_by_sn = _history_storage_fetch_recent_raw_packets_by_sn(
        [sn for sn, _hist in history_items],
        per_aircraft_limit,
        path=HISTORY_STORE_PATH,
    )
    _log(f"[INFO] history reparse candidate collect fetched: aircraft={len(raw_by_sn)} elapsed={time.perf_counter() - started_at:.2f}s")
    out: list[dict] = []
    for item_index, (sn, hist) in enumerate(history_items, 1):
        fallback_ts = hist.get("last_capture_wall_ts") or hist.get("last_seen_wall_ts") or 0.0
        raw_packets = list(raw_by_sn.get(sn) or [])
        if not raw_packets:
            raw_packets = list(hist.get("raw_packets") or [])[-per_aircraft_limit:]
            for item in raw_packets:
                if isinstance(item, dict) and "_wall_ts" not in item:
                    item["_wall_ts"] = fallback_ts
        for packet_index, raw in enumerate(raw_packets):
            if not isinstance(raw, dict):
                continue
            if not str(raw.get("hex") or "").strip():
                continue
            out.append({
                "wall_ts": _history_raw_packet_wall_ts(raw, fallback_ts),
                "seq": (item_index * max(1, per_aircraft_limit)) + packet_index,
                "sn": sn,
                "hist": dict(hist),
                "raw": dict(raw),
                "packet_index": packet_index,
                "packet_count": len(raw_packets),
            })
    out.sort(key=lambda x: (str(x.get("sn") or ""), float(x.get("wall_ts") or 0.0), int(x.get("seq") or 0)))
    _log(f"[INFO] history reparse candidate collect done: packets={len(out)} elapsed={time.perf_counter() - started_at:.2f}s")
    return out

def _history_raw_hex_to_bytes(raw_hex: str) -> bytes:
    text = str(raw_hex or "")
    if "..." in text:
        text = text.split("...", 1)[0]
    pairs = re.findall(r"(?i)(?<![0-9a-f])([0-9a-f]{2})(?![0-9a-f])", text)
    if not pairs:
        compact = re.sub(r"(?i)[^0-9a-f]", "", text)
        if len(compact) >= 2:
            if len(compact) % 2:
                compact = compact[:-1]
            pairs = [compact[i:i + 2] for i in range(0, len(compact), 2)]
    if not pairs:
        return b""
    return bytes(int(p, 16) for p in pairs)

def _history_ssid_hint(hist: dict, target_sn: str) -> str:
    ssid = str(hist.get("ssid") or "").strip()
    rid = _ssid_to_sn(ssid) if ssid else None
    if rid:
        return rid
    target = str(target_sn or "").strip()
    if len(target) == RID_NEW_FW_SN_LEN and target.isalnum():
        return target
    return ""

def _history_decode_old_payloads(data: bytes) -> dict:
    merged = {"basic_id": None, "location": None, "system": None}
    payloads = []
    try:
        payloads = list(extract_from_raw(data) or [])
    except Exception:
        payloads = []
    try:
        if not payloads and _valid_payload(data):
            payloads = [data]
    except Exception:
        pass
    for payload in payloads:
        try:
            decoded = decode_odid(payload)
        except Exception:
            continue
        if decoded.get("basic_id") and not merged.get("basic_id"):
            merged["basic_id"] = decoded.get("basic_id")
        if decoded.get("location") and not merged.get("location"):
            merged["location"] = decoded.get("location")
        if decoded.get("system") and not merged.get("system"):
            merged["system"] = decoded.get("system")
    return merged

def _history_parse_mode_key(mode: str | None) -> str:
    return normalize_parse_mode(mode)

def _history_decode_dji_vendor_mode(
    data: bytes,
    hist: dict,
    target_sn: str,
    mode: str,
) -> tuple[dict | None, str, bytes]:
    ssid_hint = _history_ssid_hint(hist, target_sn)
    model_hint = str(hist.get("model") or "")
    result = parse_raw_packet(data, mode, ssid_sn=ssid_hint, model_hint=model_hint)
    body = data
    body_hex = str(result.get("body_hex") or "")
    if body_hex:
        try:
            body = bytes.fromhex(body_hex)
        except Exception:
            body = data
    if result.get("ok") and isinstance(result.get("decoded"), dict):
        return result.get("decoded"), str(result.get("firmware_type") or ""), body
    return None, "", body

def _history_decode_raw_packet(
    data: bytes,
    hist: dict,
    target_sn: str,
    mode: str | None = "auto",
) -> tuple[dict | None, str, bytes, str]:
    mode_key = _history_parse_mode_key(mode)
    ssid_hint = _history_ssid_hint(hist, target_sn)
    model_hint = str(hist.get("model") or "")
    result = parse_raw_packet(data, mode_key, ssid_sn=ssid_hint, model_hint=model_hint)
    body = data
    body_hex = str(result.get("body_hex") or "")
    if body_hex:
        try:
            body = bytes.fromhex(body_hex)
        except Exception:
            body = data
    if result.get("ok") and isinstance(result.get("decoded"), dict):
        return (
            result.get("decoded"),
            str(result.get("firmware_type") or ""),
            body,
            str(result.get("used_mode") or mode_key),
        )
    return None, "", body, str(result.get("used_mode") or mode_key)

def _history_track_replace_latest(record: dict, lat, lon, wall_ts: float) -> None:
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception:
        return
    if not ((-90.0 <= lat_f <= 90.0) and (-180.0 <= lon_f <= 180.0)):
        return
    tracks = _sanitize_tracks(record.get("tracks") or record.get("track") or [])
    sample = {
        "sample_type": "aircraft",
        "track_type": "aircraft",
        "sn": str(record.get("sn") or "") or None,
        "uas_id": _uas_id_clean(record.get("uas_id")),
        "lat": round(lat_f, 7),
        "lon": round(lon_f, 7),
        "alt": record.get("alt"),
        "timestamp_ms": None,
        "receive_time_ms": int(float(wall_ts or time.time()) * 1000.0),
        "source": "history_reparse_aircraft",
        "coordinate_system": "WGS84",
    }
    if _track_store_append_sample(tracks, sample):
        record["tracks"] = tracks
        record["track"] = _track_store_primary(tracks, "aircraft")
        record["track_updated_wall_ts"] = float(wall_ts or time.time())

def _history_track_point_from_decoded(decoded: dict, raw: dict, fallback_ts: float | None = None) -> dict | None:
    loc = decoded.get("location") if isinstance(decoded, dict) else None
    if not isinstance(loc, dict):
        return None
    try:
        lat_f = float(loc.get("lat"))
        lon_f = float(loc.get("lon"))
    except Exception:
        return None
    if not ((-90.0 <= lat_f <= 90.0) and (-180.0 <= lon_f <= 180.0)):
        return None
    if abs(lat_f) < 0.001 and abs(lon_f) < 0.001:
        return None
    return {
        "lat": round(lat_f, 7),
        "lon": round(lon_f, 7),
        "ts": float(_history_raw_packet_wall_ts(raw, fallback_ts or time.time()) or time.time()),
    }

def _history_raw_packet_matches(a: dict, b: dict) -> bool:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    if str(a.get("hex") or "").strip() != str(b.get("hex") or "").strip():
        return False
    b_ts = str(b.get("ts") or "").strip()
    if b_ts:
        return str(a.get("ts") or "").strip() == b_ts
    return True

def _history_update_raw_packet_metadata(record: dict, hist: dict, raw: dict) -> None:
    packets = list(record.get("raw_packets") or hist.get("raw_packets") or [])[-HISTORY_RAW_PACKET_SNAPSHOT_LIMIT:]
    if isinstance(raw, dict) and raw.get("hex"):
        replaced = False
        for idx in range(len(packets) - 1, -1, -1):
            if _history_raw_packet_matches(packets[idx], raw):
                packets[idx] = dict(raw)
                replaced = True
                break
        if not replaced:
            packets.append(dict(raw))
    record["raw_packets"] = packets[-HISTORY_RAW_PACKET_SNAPSHOT_LIMIT:]

def _history_apply_reidentified_locked(
    target_sn: str,
    hist: dict,
    raw: dict,
    decoded: dict,
    firmware_type: str,
    body: bytes,
    *,
    used_mode: str | None = None,
    update_track: bool = True,
    update_raw_packet: bool = True,
    update_memory: bool = True,
) -> dict:
    basic = decoded.get("basic_id") if isinstance(decoded, dict) else None
    loc = decoded.get("location") if isinstance(decoded, dict) else None
    sys_loc = decoded.get("system") if isinstance(decoded, dict) else None
    meta = decoded.get("metadata") if isinstance(decoded, dict) else None
    parsed_sn = ""
    id_type = hist.get("id_type")
    if isinstance(basic, dict):
        parsed_sn = str(basic.get("uas_id") or "").strip()
        id_type = basic.get("id_type") or id_type
    old_sn = str(target_sn or "").strip()
    sn = parsed_sn if parsed_sn and (old_sn.startswith("MAC:") or old_sn != parsed_sn) else old_sn
    if not sn:
        sn = parsed_sn or old_sn
    existing = history_table.get(sn) if (update_memory and sn != old_sn) else None
    record = dict(existing) if isinstance(existing, dict) else dict(hist)
    if update_memory and sn != old_sn and old_sn in history_table:
        old_record = history_table.pop(old_sn)
        if existing:
            _history_merge(record, old_record)
        try:
            _history_storage_reassign_sn(old_sn, sn, HISTORY_STORE_PATH)
        except Exception:
            pass
    record["sn"] = sn
    if id_type:
        record["id_type"] = id_type
    uas_id_value = _uas_id_clean(decoded.get("uas_id"))
    record["uas_id"] = uas_id_value
    record["firmware_type"] = _firmware_type_key(firmware_type)
    record["scan_type"] = _scan_type_key(record.get("scan_type"))
    record["model"] = _resolve_model_name(sn, record.get("scan_type"), record.get("model"))
    cap_wall = _history_raw_packet_wall_ts(raw, record.get("last_capture_wall_ts") or record.get("last_seen_wall_ts"))
    if cap_wall:
        record["last_capture_wall_ts"] = cap_wall
        record["last_seen_wall_ts"] = max(float(record.get("last_seen_wall_ts") or 0.0), float(cap_wall))
    if isinstance(raw, dict):
        raw["firmware_type"] = record["firmware_type"]
        raw["uas_id"] = uas_id_value
        raw["parsed"] = _history_packet_parsed_snapshot(decoded, record["firmware_type"], used_mode)
        raw["parse_mode"] = str(used_mode or raw.get("parse_mode") or "").strip()
        raw["parse_format"] = str(
            (meta.get("rid_format") if isinstance(meta, dict) else None)
            or (meta.get("dji_rid_kind") if isinstance(meta, dict) else None)
            or (meta.get("format") if isinstance(meta, dict) else None)
            or record.get("rid_format")
            or record.get("dji_rid_kind")
            or record.get("kind")
            or record["firmware_type"]
            or ""
        ).strip()
    _history_update_raw_packet_metadata(record, hist, raw)
    if record["firmware_type"] == "new":
        for key in NEW_FW_DETAIL_KEYS:
            record[key] = meta.get(key) if isinstance(meta, dict) else None
        if body:
            record["raw_vendor"] = body.hex()
    elif isinstance(meta, dict):
        _copy_new_fw_detail(record, meta)
    if isinstance(loc, dict):
        for key, src_key in (
            ("lat", "lat"),
            ("lon", "lon"),
            ("alt", "alt_geodetic"),
            ("speed", "speed_ms"),
            ("vspeed", "vspeed_ms"),
            ("move_dir", "direction_deg"),
            ("alt_relative", "relative_alt"),
            ("alt_geoid", "alt_geodetic"),
            ("alt_baro", "alt_baro"),
        ):
            if src_key in loc:
                record[key] = loc.get(src_key)
        if record["firmware_type"] == "new":
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
                    record[key] = loc.get(src_key)
    elif record["firmware_type"] == "new":
        for key in (
            "lat", "lon", "alt", "speed", "vspeed", "move_dir",
            "track_deg", "ground_speed", "vertical_speed",
            "alt_relative", "alt_geoid", "alt_baro",
            "horizontal_accuracy", "vertical_accuracy", "speed_accuracy",
            "horizontal_accuracy_text", "vertical_accuracy_text", "speed_accuracy_text",
            "timestamp_ms", "timestamp_accuracy", "timestamp_accuracy_text",
        ):
            record[key] = None
    if isinstance(sys_loc, dict):
        record["pilot_lat"] = sys_loc.get("pilot_lat")
        record["pilot_lon"] = sys_loc.get("pilot_lon")
        record["pilot_alt"] = sys_loc.get("pilot_alt")
        record["pilot_loc_type"] = sys_loc.get("pilot_loc_type")
        record["pilot_loc_type_text"] = str(sys_loc.get("pilot_loc_type_text") or "")
    elif record["firmware_type"] == "new":
        for key in ("pilot_lat", "pilot_lon", "pilot_alt", "pilot_loc_type", "pilot_loc_type_text"):
            record[key] = None if key != "pilot_loc_type_text" else ""
    _apply_decoded_role_positions(record, loc, sys_loc, meta if isinstance(meta, dict) else None)
    if update_track:
        record["track_samples"] = []
        record["tracks"] = _empty_track_store()
        record["track"] = []
        record["track_updated_wall_ts"] = None
    if update_memory:
        history_table[sn] = record
        if sn != old_sn and old_sn in state_table:
            if sn not in state_table:
                state_table[sn] = state_table.pop(old_sn)
                state_table[sn]["sn"] = sn
            else:
                state_table.pop(old_sn, None)
        state_entry = state_table.get(sn)
        if isinstance(state_entry, dict):
            for key in (
                "id_type", "uas_id", "model", "lat", "lon", "alt", "speed", "vspeed", "move_dir",
                "pilot_lat", "pilot_lon", "pilot_alt", "pilot_loc_type", "pilot_loc_type_text",
                "firmware_type", "last_capture_wall_ts", "raw_packets",
            ) + NEW_FW_DETAIL_KEYS:
                if key in record:
                    state_entry[key] = record.get(key)
    if update_raw_packet and isinstance(raw, dict):
        try:
            _history_storage_update_raw_packet(sn, raw, HISTORY_STORE_PATH)
        except Exception as exc:
            _log(f"[WARN] raw packet database update failed for {sn}: {exc}")
    if update_memory:
        _history_mark_dirty()
    return record


def _history_reidentify_finalize_tracks(
    existing_raw,
    rebuilt_raw,
) -> tuple[dict, dict, dict, bool, list[str]]:
    existing_tracks = _sanitize_tracks(existing_raw)
    rebuilt_tracks = _sanitize_tracks(rebuilt_raw)
    existing_counts = _track_store_counts(existing_tracks)
    rebuilt_counts = _track_store_counts(rebuilt_tracks)
    final_tracks = _sanitize_tracks(existing_tracks)
    preserved_types: list[str] = []
    for track_type in ("aircraft", "operator"):
        existing_len = int(existing_counts.get(track_type) or 0)
        rebuilt_len = int(rebuilt_counts.get(track_type) or 0)
        if rebuilt_len >= existing_len:
            _track_store_set_sequence(final_tracks, track_type, list(rebuilt_tracks.get(track_type) or []))
        elif existing_len > rebuilt_len:
            preserved_types.append(track_type)
            rebuilt_last = rebuilt_tracks.get(f"last_{track_type}")
            if isinstance(rebuilt_last, dict):
                final_tracks[f"last_{track_type}"] = dict(rebuilt_last)
    return (
        final_tracks,
        existing_counts,
        rebuilt_counts,
        bool(preserved_types),
        preserved_types,
    )


HISTORY_REPARSE_PACKET_LIMIT_DEFAULT = 4000


def _history_reparse_effective_limit(limit: int | None = None) -> int:
    try:
        store_limit = _track_store_points_limit()
    except Exception:
        store_limit = HISTORY_REPARSE_PACKET_LIMIT_DEFAULT
    try:
        requested = int(limit) if limit not in (None, "") else HISTORY_REPARSE_PACKET_LIMIT_DEFAULT
    except Exception:
        requested = HISTORY_REPARSE_PACKET_LIMIT_DEFAULT
    return max(1, min(requested, store_limit, HISTORY_REPARSE_PACKET_LIMIT_DEFAULT))


def reidentify_recent_history_packets(limit: int | None = None) -> dict:
    effective_limit = _history_reparse_effective_limit(limit)
    candidates = _history_recent_raw_packet_candidates(effective_limit)
    if not candidates:
        return {"ok": False, "error": "no history raw packet"}
    return _reidentify_recent_history_packets_sync(candidates, effective_limit)

def _reidentify_recent_history_packets_sync(
    candidates: list[dict],
    effective_limit: int,
    *,
    progress_cb=None,
) -> dict:
    decoded_count = 0
    skipped_count = 0
    failed_count = 0
    migrated_count = 0
    updated_sns: set[str] = set()
    formats: dict[str, int] = {}
    errors: list[dict] = []
    aircraft_seen = {str(item.get("sn") or "") for item in candidates if str(item.get("sn") or "")}
    for index, item in enumerate(candidates, 1):
        started_at = time.perf_counter()
        target_sn = str(item.get("sn") or "")
        hist = item.get("hist") if isinstance(item.get("hist"), dict) else {}
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        data = _history_raw_hex_to_bytes(str(raw.get("hex") or ""))
        if not data:
            skipped_count += 1
            if len(errors) < 8:
                errors.append({"sn": target_sn, "error": "raw packet has no usable hex"})
            _packet_parse_diag_note_parse((time.perf_counter() - started_at) * 1000.0, queue_depth=max(0, len(candidates) - index))
            if progress_cb:
                progress_cb(index, decoded_count, skipped_count, failed_count, migrated_count, len(updated_sns), formats, errors)
            continue
        decoded, firmware_type, body, used_mode = _history_decode_raw_packet(data, hist, target_sn, "auto")
        if not decoded:
            failed_count += 1
            if len(errors) < 8:
                errors.append({"sn": target_sn, "error": "raw packet could not be decoded"})
            _packet_parse_diag_note_parse((time.perf_counter() - started_at) * 1000.0, queue_depth=max(0, len(candidates) - index))
            if progress_cb:
                progress_cb(index, decoded_count, skipped_count, failed_count, migrated_count, len(updated_sns), formats, errors)
            continue
        with state_lock:
            record = _history_apply_reidentified_locked(target_sn, hist, raw, decoded, firmware_type, body, used_mode=used_mode)
        _packet_parse_diag_note_parse((time.perf_counter() - started_at) * 1000.0, queue_depth=max(0, len(candidates) - index))
        decoded_count += 1
        sn_now = str(record.get("sn") or target_sn)
        updated_sns.add(sn_now)
        if sn_now and sn_now != target_sn:
            migrated_count += 1
        fmt = str(record.get("rid_format") or record.get("dji_rid_kind") or record.get("kind") or firmware_type or used_mode or "unknown")
        formats[fmt] = int(formats.get(fmt, 0)) + 1
        if progress_cb:
            progress_cb(index, decoded_count, skipped_count, failed_count, migrated_count, len(updated_sns), formats, errors)
    saved = save_history_store(force=True)
    _log(
        "[INFO] history recent packets reidentified: "
        f"aircraft={len(updated_sns)}/{len(aircraft_seen)} packets={decoded_count}/{len(candidates)} "
        f"skipped={skipped_count} failed={failed_count} migrated={migrated_count}"
    )
    return {
        "ok": True,
        "limit": effective_limit,
        "aircraft_count": len(aircraft_seen),
        "updated_aircraft": len(updated_sns),
        "packet_count": len(candidates),
        "decoded": decoded_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "migrated": migrated_count,
        "formats": formats,
        "errors": errors,
        "saved": bool(saved),
    }

def _history_reparse_queue_depth() -> int:
    try:
        return max(0, int(history_reparse_queue.qsize()))
    except Exception:
        return 0


def _history_reparse_clear_pending_queue() -> int:
    drained = 0
    while True:
        try:
            history_reparse_queue.get_nowait()
            drained += 1
        except queue.Empty:
            break
        except Exception:
            break
    return drained


def _history_reparse_dynamic_worker_count(total_aircraft: int, total_packets: int) -> int:
    if max(0, int(total_aircraft or 0), int(total_packets or 0)) <= 0:
        return 1
    return 12


def _history_reparse_group_candidates(candidates: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        sn = str(item.get("sn") or "").strip()
        if not sn:
            continue
        group = groups.setdefault(sn, {
            "sn": sn,
            "hist": dict(item.get("hist") or {}) if isinstance(item.get("hist"), dict) else {},
            "items": [],
        })
        group["items"].append(item)
    out = list(groups.values())
    for group in out:
        group["items"].sort(key=lambda x: (float(x.get("wall_ts") or 0.0), int(x.get("packet_index") or 0), int(x.get("seq") or 0)))
    out.sort(key=lambda x: str(x.get("sn") or ""))
    return out


def _history_reparse_task_active(task_id: str) -> bool:
    with history_reparse_lock:
        return bool(history_reparse_state.get("running")) and str(history_reparse_state.get("task_id") or "") == str(task_id or "")


def _history_reparse_note_result(
    task_id: str,
    *,
    index: int,
    batch_size: int,
    updated_sn: str = "",
    fmt: str = "",
    error: str = "",
    decoded: bool = False,
    skipped: bool = False,
    failed: bool = False,
    migrated: bool = False,
) -> dict:
    now_wall = time.time()
    with history_reparse_runtime_lock:
        if decoded and updated_sn:
            history_reparse_runtime_updated_sns.add(str(updated_sn))
        updated_aircraft = len(history_reparse_runtime_updated_sns)
    with history_reparse_lock:
        if (not bool(history_reparse_state.get("running"))) or str(history_reparse_state.get("task_id") or "") != str(task_id or ""):
            return _history_reparse_workflow_snapshot()
        total = max(0, int(history_reparse_state.get("total") or 0))
        step = max(0, min(total, int(index or 0)))
        completed_now = min(total, int(history_reparse_state.get("completed") or 0) + 1)
        history_reparse_state["completed"] = completed_now
        if decoded:
            history_reparse_state["decoded"] = int(history_reparse_state.get("decoded") or 0) + 1
        if skipped:
            history_reparse_state["skipped"] = int(history_reparse_state.get("skipped") or 0) + 1
        if failed:
            history_reparse_state["failed"] = int(history_reparse_state.get("failed") or 0) + 1
        if migrated:
            history_reparse_state["migrated"] = int(history_reparse_state.get("migrated") or 0) + 1
        history_reparse_state["updated_aircraft"] = updated_aircraft
        if fmt:
            formats = dict(history_reparse_state.get("formats") or {})
            formats[str(fmt)] = int(formats.get(str(fmt)) or 0) + 1
            history_reparse_state["formats"] = formats
        if error:
            errors = list(history_reparse_state.get("errors") or [])
            if len(errors) < 8:
                errors.append({"index": step, "error": str(error), "sn": str(updated_sn or "")})
            history_reparse_state["errors"] = errors
            history_reparse_state["last_error"] = str(error)
        active_batch = int(math.ceil(float(completed_now or 1) / float(max(1, int(batch_size or 1))))) if completed_now > 0 else 0
        history_reparse_state["active_batch"] = active_batch
        history_reparse_state["active_batch_size"] = (
            min(max(1, int(batch_size or 1)), max(0, total - ((active_batch - 1) * max(1, int(batch_size or 1)))))
            if active_batch > 0 else 0
        )
        history_reparse_state["message"] = f"processing {history_reparse_state['completed']}/{total}"
        history_reparse_state["updated_wall"] = now_wall
    return _history_reparse_workflow_snapshot()


def _history_reparse_finish_if_ready(task_id: str) -> bool:
    with history_reparse_lock:
        if (not bool(history_reparse_state.get("running"))) or str(history_reparse_state.get("task_id") or "") != str(task_id or ""):
            return False
        total = max(0, int(history_reparse_state.get("total") or 0))
        completed = max(0, int(history_reparse_state.get("completed") or 0))
        producer_done = bool(history_reparse_state.get("producer_done"))
        batch_size = max(1, int(history_reparse_state.get("batch_size") or HISTORY_REPARSE_BATCH_SIZE))
        decoded = max(0, int(history_reparse_state.get("decoded") or 0))
        skipped = max(0, int(history_reparse_state.get("skipped") or 0))
        failed = max(0, int(history_reparse_state.get("failed") or 0))
        migrated = max(0, int(history_reparse_state.get("migrated") or 0))
    if (not producer_done) or completed < total:
        return False
    with history_reparse_runtime_lock:
        updated_aircraft = len(history_reparse_runtime_updated_sns)
    saved = save_history_store(force=True)
    _log(
        "[INFO] history recent packets reidentified: "
        f"aircraft={updated_aircraft} packets={decoded}/{total} "
        f"skipped={skipped} failed={failed} migrated={migrated}"
    )
    _history_reparse_workflow_finish(
        ok=True,
        message="history reparse completed",
        completed=completed,
        decoded=decoded,
        skipped=skipped,
        failed=failed,
        migrated=migrated,
        updated_aircraft=updated_aircraft,
        saved=bool(saved),
        producer_done=True,
        active_batch=int(math.ceil(float(total) / float(batch_size))) if total > 0 else 0,
    )
    return True


def _history_reparse_process_item(item: dict) -> None:
    task_id = str(item.get("task_id") or "")
    if not task_id or not _history_reparse_task_active(task_id):
        return
    index = max(0, int(item.get("index") or 0))
    batch_size = max(1, int(item.get("batch_size") or HISTORY_REPARSE_BATCH_SIZE))
    target_sn = str(item.get("sn") or "")
    hist = item.get("hist") if isinstance(item.get("hist"), dict) else {}
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    started_at = time.perf_counter()
    updated_sn = target_sn
    fmt = ""
    err = ""
    decoded_ok = False
    skipped = False
    failed = False
    migrated = False
    try:
        data = _history_raw_hex_to_bytes(str(raw.get("hex") or ""))
        if not data:
            skipped = True
            err = "raw packet has no usable hex"
            return
        decoded, firmware_type, body, used_mode = _history_decode_raw_packet(data, hist, target_sn, "auto")
        if not decoded:
            failed = True
            err = "raw packet could not be decoded"
            return
        with state_lock:
            record = _history_apply_reidentified_locked(target_sn, hist, raw, decoded, firmware_type, body, used_mode=used_mode)
        decoded_ok = True
        updated_sn = str(record.get("sn") or target_sn)
        migrated = bool(updated_sn and updated_sn != target_sn)
        fmt = str(record.get("rid_format") or record.get("dji_rid_kind") or record.get("kind") or firmware_type or used_mode or "unknown")
    except Exception as exc:
        failed = True
        err = str(exc)
        _log(f"[WARN] history reparse item failed: {exc}")
    finally:
        _packet_parse_diag_note_parse((time.perf_counter() - started_at) * 1000.0, queue_depth=_history_reparse_queue_depth())
        _history_reparse_note_result(
            task_id,
            index=index,
            batch_size=batch_size,
            updated_sn=updated_sn if decoded_ok else target_sn,
            fmt=fmt,
            error=err,
            decoded=decoded_ok,
            skipped=skipped,
            failed=failed,
            migrated=migrated,
        )
        _history_reparse_finish_if_ready(task_id)


def _history_reparse_process_aircraft_group(group: dict, task_id: str, batch_size: int) -> list[dict]:
    if not task_id or not _history_reparse_task_active(task_id):
        return []
    target_sn = str(group.get("sn") or "")
    items = list(group.get("items") or [])
    hist_seed = dict(group.get("hist") or {}) if isinstance(group.get("hist"), dict) else {}
    with state_lock:
        current_hist = history_table.get(target_sn)
        hist_copy = dict(current_hist) if isinstance(current_hist, dict) else dict(hist_seed)
    before_tracks = _sanitize_tracks(hist_copy)
    rebuilt_tracks = _empty_track_store()
    sn_now = target_sn
    record: dict | None = None
    parse_result_updates: list[dict] = []
    for item in items:
        if not _history_reparse_task_active(task_id):
            return parse_result_updates
        index = max(0, int(item.get("index") or 0))
        raw = dict(item.get("raw") or {}) if isinstance(item.get("raw"), dict) else {}
        started_at = time.perf_counter()
        updated_sn = sn_now
        fmt = ""
        err = ""
        decoded_ok = False
        skipped = False
        failed = False
        migrated = False
        try:
            data = _history_raw_hex_to_bytes(str(raw.get("hex") or ""))
            if not data:
                skipped = True
                err = "raw packet has no usable hex"
                continue
            decoded, firmware_type, body, used_mode = _history_decode_raw_packet(data, hist_copy, sn_now, "auto")
            if not decoded:
                failed = True
                err = "raw packet could not be decoded"
                continue
            receive_time_ms = None
            try:
                fallback_wall = hist_copy.get("last_capture_wall_ts") or hist_copy.get("last_seen_wall_ts") or time.time()
                receive_time_ms = int(float(_history_raw_packet_wall_ts(raw, fallback_wall) or 0.0) * 1000.0)
            except Exception:
                receive_time_ms = None
            packet_hash = str(raw.get("hex") or f"history-{index}")[:128]
            for sample in _track_samples_from_decoded(decoded, receive_time_ms, packet_hash=packet_hash):
                _track_store_append_sample(rebuilt_tracks, sample)
            with state_lock:
                live_hist = history_table.get(sn_now) or history_table.get(target_sn) or hist_copy
                record = _history_apply_reidentified_locked(
                    sn_now,
                    live_hist,
                    raw,
                    decoded,
                    firmware_type,
                    body,
                    used_mode=used_mode,
                    update_track=False,
                    update_raw_packet=False,
                    update_memory=False,
                )
            decoded_ok = True
            updated_sn = str(record.get("sn") or sn_now)
            migrated = bool(updated_sn and updated_sn != sn_now)
            sn_now = updated_sn or sn_now
            hist_copy = dict(record)
            fmt = str(record.get("rid_format") or record.get("dji_rid_kind") or record.get("kind") or firmware_type or used_mode or "unknown")
            parse_result_updates.append({
                "sn": sn_now,
                "raw": dict(raw),
                "parsed": raw.get("parsed") if isinstance(raw, dict) else None,
                "parse_mode": raw.get("parse_mode") if isinstance(raw, dict) else used_mode,
                "parse_format": raw.get("parse_format") if isinstance(raw, dict) else fmt,
            })
        except Exception as exc:
            failed = True
            err = str(exc)
            _log(f"[WARN] history reparse item failed: {exc}")
        finally:
            _packet_parse_diag_note_parse((time.perf_counter() - started_at) * 1000.0, queue_depth=0)
            _history_reparse_note_result(
                task_id,
                index=index,
                batch_size=batch_size,
                updated_sn=updated_sn if decoded_ok else target_sn,
                fmt=fmt,
                error=err,
                decoded=decoded_ok,
                skipped=skipped,
                failed=failed,
                migrated=migrated,
            )
    return parse_result_updates


def _history_reparse_reload_from_db() -> bool:
    try:
        load_history_store(HISTORY_STORE_PATH)
        return bool(save_history_store(force=True))
    except Exception as exc:
        _log(f"[WARN] history reparse db reload failed: {exc}")
        return False


def _history_reparse_worker_loop() -> None:
    while True:
        item = history_reparse_queue.get()
        try:
            if isinstance(item, dict):
                _history_reparse_process_item(item)
        except Exception as exc:
            _log(f"[WARN] history reparse worker error: {exc}")
            task_id = str(item.get("task_id") or "") if isinstance(item, dict) else ""
            if task_id and _history_reparse_task_active(task_id):
                _history_reparse_workflow_finish(
                    ok=False,
                    message="history reparse failed",
                    error=str(exc),
                )


def start_history_reparse_worker() -> None:
    global history_reparse_worker_started
    if history_reparse_worker_started:
        return
    history_reparse_worker_started = True
    Thread(target=_history_reparse_worker_loop, daemon=True).start()


def _recent_history_reidentify_producer(candidates: list[dict], effective_limit: int, task_id: str) -> None:
    total = len(candidates)
    groups = _history_reparse_group_candidates(candidates)
    worker_count = _history_reparse_dynamic_worker_count(len(groups), total)
    batch_size = max(1, int(math.ceil(float(total or 1) / float(worker_count or 1))))
    try:
        _history_reparse_workflow_update(
            total=total,
            aircraft_total=len(groups),
            batches_total=int(math.ceil(float(total or 0) / float(batch_size or 1))) if total else 0,
            message=f"starting parallel reparse: {worker_count} threads",
            active_batch=0,
            active_batch_size=0,
            worker_total=worker_count,
            worker_busy=0,
            worker_idle=worker_count,
            enqueued=total,
            producer_done=True,
            batch_size=batch_size,
        )
        from concurrent.futures import ThreadPoolExecutor, as_completed
        parse_result_updates: list[dict] = []
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="history-reparse") as pool:
            futures = [
                pool.submit(_history_reparse_process_aircraft_group, group, task_id, batch_size)
                for group in groups
            ]
            _history_reparse_workflow_update(
                active_batch_size=min(len(groups), worker_count),
                worker_total=worker_count,
                worker_busy=min(len(groups), worker_count),
                worker_idle=max(0, worker_count - min(len(groups), worker_count)),
                message=f"processing {total} packets across {len(groups)} aircraft with {worker_count} threads",
            )
            for future in as_completed(futures):
                if not _history_reparse_task_active(task_id):
                    return
                try:
                    result = future.result()
                    if isinstance(result, list):
                        parse_result_updates.extend([item for item in result if isinstance(item, dict)])
                except Exception as exc:
                    _log(f"[WARN] history reparse parallel task failed: {exc}")
        if parse_result_updates:
            _history_reparse_workflow_update(message=f"saving {len(parse_result_updates)} parsed packets to database")
            try:
                save_started = time.perf_counter()
                saved_packets = _history_storage_update_raw_packet_parse_results(parse_result_updates, HISTORY_STORE_PATH)
                _log(f"[INFO] history reparse parsed packet db update: rows={saved_packets}/{len(parse_result_updates)} elapsed={time.perf_counter() - save_started:.2f}s")
            except Exception as exc:
                _log(f"[WARN] raw packet parse-result database batch update failed: {exc}")
        saved = _history_reparse_reload_from_db()
        _history_reparse_workflow_update(
            saved=bool(saved),
            worker_busy=0,
            worker_idle=worker_count,
            message="history reparse parsed results saved; refreshing history from database",
        )
        _history_reparse_finish_if_ready(task_id)
    except Exception as exc:
        _log(f"[WARN] history reparse producer failed: {exc}")
        if _history_reparse_task_active(task_id):
            _history_reparse_workflow_finish(
                ok=False,
                message="history reparse failed",
                error=str(exc),
            )


def _recent_history_reidentify_prepare_and_run(effective_limit: int, task_id: str) -> None:
    try:
        _history_reparse_workflow_update(message="collecting history raw packets", producer_done=False)
        candidates = _history_recent_raw_packet_candidates(effective_limit)
        if not candidates:
            if _history_reparse_task_active(task_id):
                _history_reparse_workflow_finish(
                    ok=False,
                    message="history reparse failed",
                    error="no history raw packet",
                    producer_done=True,
                )
            return
        _recent_history_reidentify_producer(candidates, effective_limit, task_id)
    except Exception as exc:
        _log(f"[WARN] history reparse prepare failed: {exc}")
        if _history_reparse_task_active(task_id):
            _history_reparse_workflow_finish(
                ok=False,
                message="history reparse failed",
                error=str(exc),
                producer_done=True,
            )


def start_recent_history_reidentify_workflow(limit: int | None = None) -> dict:
    effective_limit = _history_reparse_effective_limit(limit)
    _history_reparse_clear_pending_queue()
    with history_reparse_runtime_lock:
        history_reparse_runtime_updated_sns.clear()
    with state_lock:
        aircraft_total = len([
            sn for sn, hist in history_table.items()
            if sn and isinstance(hist, dict)
            and (_scan_type_key(hist.get("scan_type")) == "phone" or (len(str(sn or "")) == 20 and str(sn or "").isalnum()))
        ])
    started, workflow = _history_reparse_workflow_start(
        kind="history_recent",
        title="最近历史重解析",
        limit=effective_limit,
        total=0,
        aircraft_total=aircraft_total,
        batch_size=HISTORY_REPARSE_BATCH_SIZE,
    )
    if not started:
        return {
            "ok": True,
            "started": False,
            "busy": True,
            "message": str(workflow.get("message") or "history reparse already running"),
            "workflow": workflow,
        }
    task_id = str(workflow.get("task_id") or "")
    Thread(target=lambda: _recent_history_reidentify_prepare_and_run(effective_limit, task_id), daemon=True).start()
    return {
        "ok": True,
        "started": True,
        "message": "history reparse started; collecting raw packets in background",
        "workflow": _history_reparse_workflow_snapshot(),
    }

def history_reparse_workflow_status() -> dict:
    return {
        "ok": True,
        "workflow": _history_reparse_workflow_snapshot(),
    }

def reidentify_latest_history_packet() -> dict:
    return reidentify_recent_history_packets(limit=_track_store_points_limit())

def reidentify_history_packet_for_sn(sn: str, mode: str | None = "auto") -> dict:
    target_sn = str(sn or "").strip()
    if not target_sn:
        return {"ok": False, "error": "sn required"}
    mode_key = _history_parse_mode_key(mode)
    with state_lock:
        hist = history_table.get(target_sn) or state_table.get(target_sn)
        if not isinstance(hist, dict):
            return {"ok": False, "error": "aircraft not found", "sn": target_sn, "mode": mode_key}
        hist_copy = dict(hist)
    before_tracks = _sanitize_tracks(hist_copy)
    raw_packets = _history_storage_fetch_raw_packets(target_sn, path=HISTORY_STORE_PATH)
    if not raw_packets:
        fallback_wall_ts = hist_copy.get("last_capture_wall_ts") or hist_copy.get("last_seen_wall_ts") or time.time()
        raw_packets = list(hist_copy.get("raw_packets") or [])
        for item in raw_packets:
            if isinstance(item, dict) and "_wall_ts" not in item:
                item["_wall_ts"] = fallback_wall_ts
    if not raw_packets:
        return {"ok": False, "error": "no raw packet for aircraft", "sn": target_sn, "mode": mode_key}

    workflow_task_id = ""
    workflow_started = False
    with history_reparse_runtime_lock:
        history_reparse_runtime_updated_sns.clear()
    workflow_started, workflow = _history_reparse_workflow_start(
        kind="history_single",
        title=f"历史重解析 {target_sn}",
        limit=len(raw_packets),
        total=len(raw_packets),
        aircraft_total=1,
        batch_size=max(1, len(raw_packets)),
    )
    if workflow_started:
        workflow_task_id = str(workflow.get("task_id") or "")
        _history_reparse_workflow_update(
            message=f"processing {target_sn}",
            producer_done=True,
            enqueued=len(raw_packets),
            active_batch=1,
            active_batch_size=len(raw_packets),
        )

    decoded_count = 0
    skipped_count = 0
    failed_count = 0
    errors: list[dict] = []
    formats: dict[str, int] = {}
    used_modes: dict[str, int] = {}
    warnings: list[str] = []
    sn_now = target_sn
    record: dict | None = None
    rebuilt_tracks = _empty_track_store()
    for index, raw in enumerate(raw_packets):
        decoded_ok = False
        skipped_ok = False
        failed_ok = False
        packet_fmt = ""
        packet_err = ""
        data = _history_raw_hex_to_bytes(str(raw.get("hex") or ""))
        if not data:
            skipped_count += 1
            skipped_ok = True
            packet_err = "raw packet has no usable hex"
            if len(errors) < 8:
                errors.append({"packet_index": index, "error": packet_err})
            if workflow_task_id:
                _history_reparse_note_result(
                    workflow_task_id,
                    index=index + 1,
                    batch_size=max(1, len(raw_packets)),
                    updated_sn=sn_now,
                    error=packet_err,
                    skipped=skipped_ok,
                )
            continue
        decoded, firmware_type, body, used_mode = _history_decode_raw_packet(data, hist_copy, sn_now, mode_key)
        if not decoded:
            failed_count += 1
            failed_ok = True
            packet_err = "raw packet could not be decoded with selected mode"
            if len(errors) < 8:
                errors.append({"packet_index": index, "error": packet_err})
            if workflow_task_id:
                _history_reparse_note_result(
                    workflow_task_id,
                    index=index + 1,
                    batch_size=max(1, len(raw_packets)),
                    updated_sn=sn_now,
                    error=packet_err,
                    failed=failed_ok,
                )
            continue
        receive_time_ms = None
        try:
            receive_time_ms = int(float(_history_raw_packet_wall_ts(raw, hist_copy.get("last_capture_wall_ts") or time.time()) or 0.0) * 1000.0)
        except Exception:
            receive_time_ms = None
        packet_hash = str(raw.get("hex") or f"history-{index}")[:128]
        for sample in _track_samples_from_decoded(decoded, receive_time_ms, packet_hash=packet_hash):
            _track_store_append_sample(rebuilt_tracks, sample)
        with state_lock:
            current_hist = history_table.get(sn_now) or history_table.get(target_sn) or hist_copy
            record = _history_apply_reidentified_locked(
                sn_now,
                current_hist,
                raw,
                decoded,
                firmware_type,
                body,
                used_mode=used_mode,
                update_track=False,
            )
        decoded_count += 1
        decoded_ok = True
        sn_now = str(record.get("sn") or sn_now)
        hist_copy = dict(record)
        fmt_item = str(record.get("rid_format") or record.get("dji_rid_kind") or record.get("kind") or firmware_type or used_mode or "unknown")
        packet_fmt = fmt_item
        formats[fmt_item] = int(formats.get(fmt_item, 0)) + 1
        used_key = str(used_mode or mode_key or "auto")
        used_modes[used_key] = int(used_modes.get(used_key, 0)) + 1
        if workflow_task_id:
            _history_reparse_note_result(
                workflow_task_id,
                index=index + 1,
                batch_size=max(1, len(raw_packets)),
                updated_sn=sn_now,
                fmt=packet_fmt,
                decoded=decoded_ok,
            )
    if not record:
        if workflow_task_id:
            _history_reparse_workflow_finish(
                ok=False,
                message="history reparse failed",
                error="no raw packet could be decoded with selected mode",
                completed=len(raw_packets),
                decoded=decoded_count,
                skipped=skipped_count,
                failed=failed_count,
                producer_done=True,
                active_batch=1,
            )
        return {
            "ok": False,
            "error": "no raw packet could be decoded with selected mode",
            "sn": target_sn,
            "mode": mode_key,
            "packet_count": len(raw_packets),
            "decoded": decoded_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "errors": errors,
            "workflow": _history_reparse_workflow_snapshot(),
        }

    final_tracks, before_counts, rebuilt_counts, preserve_existing_longer_tracks, preserved_track_types = _history_reidentify_finalize_tracks(
        before_tracks,
        rebuilt_tracks,
    )
    final_counts = _track_store_counts(final_tracks)
    final_track = _track_store_primary(final_tracks, "aircraft")
    if len(raw_packets) <= 1:
        warnings.append(f"history for {sn_now} only has 1 raw packet; rebuilt track detail is limited")
    with state_lock:
        current = history_table.get(sn_now) or record
        current["tracks"] = final_tracks
        current["track"] = final_track
        last_aircraft = final_tracks.get("last_aircraft")
        current["track_updated_wall_ts"] = None
        if isinstance(last_aircraft, dict):
            try:
                current["track_updated_wall_ts"] = float((last_aircraft.get("receive_time_ms") or last_aircraft.get("timestamp_ms") or 0) / 1000.0)
            except Exception:
                current["track_updated_wall_ts"] = None
        history_table[sn_now] = current
        state_entry = state_table.get(sn_now)
        if isinstance(state_entry, dict):
            state_entry["tracks"] = _sanitize_tracks(final_tracks)
            state_entry["track"] = list(final_track)
            state_entry["track_updated_wall_ts"] = current.get("track_updated_wall_ts")
        record = dict(current)
        _history_mark_dirty()
    saved = save_history_store(force=True)
    fmt = str(record.get("rid_format") or record.get("dji_rid_kind") or record.get("kind") or record.get("firmware_type") or "unknown")
    used_summary = ",".join(f"{k}:{v}" for k, v in sorted(used_modes.items())) or mode_key
    _log(
        f"[INFO] history packets reidentified: sn={target_sn} -> {sn_now} "
        f"mode={mode_key} used={used_summary} decoded={decoded_count}/{len(raw_packets)} "
        f"format={fmt}"
    )
    if workflow_task_id:
        _history_reparse_workflow_finish(
            ok=True,
            message="history reparse completed",
            completed=len(raw_packets),
            decoded=decoded_count,
            skipped=skipped_count,
            failed=failed_count,
            migrated=1 if sn_now != target_sn else 0,
            updated_aircraft=1,
            saved=bool(saved),
            producer_done=True,
            active_batch=1,
        )
    return {
        "ok": True,
        "sn": target_sn,
        "sn_now": sn_now,
        "mode": mode_key,
        "used_mode": used_summary,
        "packet_count": len(raw_packets),
        "decoded": decoded_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "formats": formats,
        "track_count": len(final_track),
        "track": final_track,
        "tracks": final_tracks,
        "before_counts": before_counts,
        "rebuilt_counts": rebuilt_counts,
        "final_counts": final_counts,
        "preserve_existing_longer_tracks": preserve_existing_longer_tracks,
        "preserved_track_types": preserved_track_types,
        "errors": errors,
        "warnings": warnings,
        "firmware_type": record.get("firmware_type"),
        "format": fmt,
        "saved": bool(saved),
        "workflow": _history_reparse_workflow_snapshot(),
        "refresh": True,
        "message": f"reparsed {sn_now} with {mode_key}; metadata and trajectory refreshed",
    }
