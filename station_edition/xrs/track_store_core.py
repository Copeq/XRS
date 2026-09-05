"""Track-store helpers (extracted from common_core.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
Names such as APP_CONFIG / TRACK_* constants / scan_core helpers resolve at call time
inside the shared namespace, so this file must be exec'd after common_core.py.
"""

def _track_store_points_limit() -> int:
    basic = APP_CONFIG.get("basic") if isinstance(APP_CONFIG, dict) else {}
    if not isinstance(basic, dict):
        basic = {}
    try:
        limit = int(float(basic.get("track_points_limit", TRACK_MAX_POINTS)))
    except Exception:
        limit = TRACK_MAX_POINTS
    return max(TRACK_STORE_POINTS_MIN, min(limit, TRACK_STORE_POINTS_MAX))

def _fmt_age_compact(sec: float | int | None) -> str:
    if sec is None:
        return "-"
    try:
        s = int(max(0, float(sec)))
    except Exception:
        return "-"
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s <= 216000:  # 60h
        return f"{s // 3600}h"
    return f"{s // 86400}d"

def _sanitize_track(raw) -> list[dict]:
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for it in raw:
        if not isinstance(it, dict):
            continue
        try:
            lat = float(it.get("lat"))
            lon = float(it.get("lon"))
            ts = float(it.get("ts"))
        except Exception:
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        if ts <= 0:
            continue
        out.append({
            "lat": round(lat, 7),
            "lon": round(lon, 7),
            "ts": ts,
        })
    out.sort(key=lambda x: (x.get("ts") or 0.0))
    limit = _track_store_points_limit()
    if len(out) > limit:
        out = out[-limit:]
    return out


def _sanitize_track_samples(raw) -> list[dict]:
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for it in raw:
        if not isinstance(it, dict):
            continue
        try:
            lat = float(it.get("lat"))
            lon = float(it.get("lon"))
        except Exception:
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        ts_ms = it.get("timestamp_ms")
        recv_ms = it.get("receive_time_ms")
        try:
            ts_ms = int(ts_ms) if ts_ms is not None else None
        except Exception:
            ts_ms = None
        try:
            recv_ms = int(recv_ms) if recv_ms is not None else None
        except Exception:
            recv_ms = None
        out.append({
            "sample_type": str(it.get("sample_type") or it.get("track_type") or "aircraft"),
            "track_type": str(it.get("track_type") or it.get("sample_type") or "aircraft"),
            "sn": str(it.get("sn") or "") or None,
            "uas_id": str(it.get("uas_id") or "") or None,
            "lat": round(lat, 7),
            "lon": round(lon, 7),
            "alt": it.get("alt"),
            "timestamp_ms": ts_ms,
            "receive_time_ms": recv_ms,
            "packet_hash": str(it.get("packet_hash") or "") or None,
            "source": str(it.get("source") or ""),
            "coordinate_system": str(it.get("coordinate_system") or "WGS84"),
        })
    out.sort(key=lambda x: (
        int(x.get("timestamp_ms") or 0),
        int(x.get("receive_time_ms") or 0),
    ))
    limit = _track_store_points_limit()
    if len(out) > limit:
        out = out[-limit:]
    return out


def _empty_track_store() -> dict:
    return {
        "aircraft": [],
        "operator": [],
        "last_aircraft": None,
        "last_operator": None,
    }


def _track_store_counts(raw) -> dict[str, int]:
    store = _sanitize_tracks(raw)
    return {
        "aircraft": len(store.get("aircraft") or []),
        "operator": len(store.get("operator") or []),
    }


def _track_store_set_sequence(store: dict, track_type: str, seq: list[dict]) -> None:
    if not isinstance(store, dict):
        return
    clean = _sanitize_track_samples(seq)
    store[track_type] = clean
    store[f"last_{track_type}"] = dict(clean[-1]) if clean else None


def _track_store_build_sequence(raw, track_type: str, default_source: str) -> list[dict]:
    seq_store = _empty_track_store()
    if not isinstance(raw, list):
        return []
    for point in raw:
        if not isinstance(point, dict):
            continue
        item_track_type = str(point.get("track_type") or point.get("sample_type") or track_type).strip().lower() or track_type
        if item_track_type not in ("aircraft", "operator"):
            item_track_type = track_type
        sample = {
            "sample_type": item_track_type,
            "track_type": item_track_type,
            "sn": point.get("sn"),
            "uas_id": point.get("uas_id"),
            "lat": point.get("lat"),
            "lon": point.get("lon"),
            "alt": point.get("alt"),
            "timestamp_ms": point.get("timestamp_ms"),
            "receive_time_ms": point.get("receive_time_ms"),
            "packet_hash": point.get("packet_hash"),
            "source": point.get("source") or default_source,
            "coordinate_system": point.get("coordinate_system") or "WGS84",
        }
        if sample["timestamp_ms"] is None and sample["receive_time_ms"] is None and point.get("ts") is not None:
            try:
                sample["receive_time_ms"] = int(float(point.get("ts")) * 1000.0)
            except Exception:
                sample["receive_time_ms"] = None
        _track_store_append_sample(seq_store, sample)
    return list(seq_store.get(track_type) or [])


def _sanitize_tracks(raw) -> dict:
    store = _empty_track_store()
    if isinstance(raw, dict):
        nested = raw.get("tracks")
        if isinstance(nested, dict) and nested is not raw:
            nested_store = _sanitize_tracks(nested)
            _track_store_set_sequence(store, "aircraft", list(nested_store.get("aircraft") or []))
            _track_store_set_sequence(store, "operator", list(nested_store.get("operator") or []))

        for key, track_type, source_name in (
            ("aircraft", "aircraft", "legacy_aircraft"),
            ("operator", "operator", "legacy_operator"),
            ("track", "aircraft", "legacy_track"),
            ("history", "aircraft", "legacy_history"),
            ("path", "aircraft", "legacy_path"),
        ):
            seq = _track_store_build_sequence(raw.get(key), track_type, source_name)
            if len(seq) > len(store.get(track_type) or []):
                _track_store_set_sequence(store, track_type, seq)

        if not store["aircraft"] and isinstance(raw.get("last_aircraft"), dict):
            items = _sanitize_track_samples([raw.get("last_aircraft")])
            if items:
                _track_store_set_sequence(store, "aircraft", items)
        if not store["operator"] and isinstance(raw.get("last_operator"), dict):
            items = _sanitize_track_samples([raw.get("last_operator")])
            if items:
                _track_store_set_sequence(store, "operator", items)
    elif isinstance(raw, list):
        _track_store_set_sequence(store, "aircraft", _track_store_build_sequence(raw, "aircraft", "legacy_track"))
    if store["aircraft"] and not store["last_aircraft"]:
        store["last_aircraft"] = dict(store["aircraft"][-1])
    if store["operator"] and not store["last_operator"]:
        store["last_operator"] = dict(store["operator"][-1])
    return store


def _track_store_append_sample(store: dict, sample: dict) -> bool:
    if not isinstance(store, dict) or not isinstance(sample, dict):
        return False
    track_type = str(sample.get("track_type") or sample.get("sample_type") or "aircraft").strip() or "aircraft"
    if track_type not in ("aircraft", "operator"):
        return False
    items = _sanitize_track_samples([sample])
    if not items:
        return False
    item = items[0]
    seq = _sanitize_track_samples(list(store.get(track_type) or []))
    item_key = _track_sample_dedup_key(item)
    if seq:
        last = seq[-1]
        if _track_sample_dedup_key(last) == item_key:
            if (item.get("receive_time_ms") or 0) >= (last.get("receive_time_ms") or 0):
                seq[-1] = item
                store[track_type] = seq
                store[f"last_{track_type}"] = dict(item)
                return True
            return False
        if (
            abs(float(last.get("lat") or 0.0) - float(item["lat"])) < 1e-7
            and abs(float(last.get("lon") or 0.0) - float(item["lon"])) < 1e-7
            and (last.get("timestamp_ms") == item.get("timestamp_ms") or item.get("timestamp_ms") is None)
        ):
            if (item.get("receive_time_ms") or 0) >= (last.get("receive_time_ms") or 0):
                seq[-1] = item
                store[track_type] = seq
                store[f"last_{track_type}"] = dict(item)
                return True
            return False
    seq.append(item)
    limit = _track_store_points_limit()
    if len(seq) > limit:
        seq = seq[-limit:]
    store[track_type] = seq
    store[f"last_{track_type}"] = dict(item)
    return True


def _track_sample_dedup_key(sample: dict | None) -> str:
    if not isinstance(sample, dict):
        return ""
    identity = str(sample.get("sn") or sample.get("uas_id") or "")
    track_type = str(sample.get("track_type") or sample.get("sample_type") or "aircraft")
    lat = sample.get("lat")
    lon = sample.get("lon")
    ts_ms = sample.get("timestamp_ms")
    recv_ms = sample.get("receive_time_ms")
    packet_hash = str(sample.get("packet_hash") or "")
    packet_or_recv = packet_hash
    if not packet_or_recv and recv_ms is not None:
        packet_or_recv = str(int(recv_ms))
    return "|".join([
        identity,
        track_type,
        str(round(float(lat), 7) if lat is not None else ""),
        str(round(float(lon), 7) if lon is not None else ""),
        str(int(ts_ms) if ts_ms is not None else ""),
        packet_or_recv,
    ])


def _track_store_from_import_payload(
    payload: dict | None,
    *,
    sn: str | None = None,
    uas_id: str | None = None,
) -> tuple[dict, list[dict]]:
    store = _empty_track_store()
    payload = payload if isinstance(payload, dict) else {}

    def append_import_list(raw_items, track_type: str) -> None:
        if not isinstance(raw_items, list):
            return
        for point in raw_items:
            if not isinstance(point, dict):
                continue
            sample = {
                "sample_type": track_type,
                "track_type": track_type,
                "sn": sn or point.get("sn"),
                "uas_id": uas_id or point.get("uas_id"),
                "lat": point.get("lat"),
                "lon": point.get("lon"),
                "alt": point.get("alt"),
                "timestamp_ms": point.get("timestamp_ms"),
                "receive_time_ms": point.get("receive_time_ms"),
                "packet_hash": point.get("packet_hash"),
                "source": point.get("source") or f"import_{track_type}",
                "coordinate_system": point.get("coordinate_system") or "WGS84",
            }
            if sample["timestamp_ms"] is None and point.get("ts") is not None:
                try:
                    sample["receive_time_ms"] = int(float(point.get("ts")) * 1000.0)
                except Exception:
                    sample["receive_time_ms"] = sample.get("receive_time_ms")
            _track_store_append_sample(store, sample)

    if isinstance(payload.get("track"), list):
        append_import_list(payload.get("track"), "aircraft")
    append_import_list(payload.get("aircraft"), "aircraft")
    append_import_list(payload.get("operator"), "operator")
    return store, _track_store_primary(store, "aircraft")


def _track_store_primary(store: dict, track_type: str = "aircraft") -> list[dict]:
    clean = _sanitize_tracks(store)
    seq = clean.get(track_type) if isinstance(clean, dict) else []
    out: list[dict] = []
    for item in list(seq or []):
        try:
            ts_ms = item.get("timestamp_ms")
            recv_ms = item.get("receive_time_ms")
            ts = None
            if ts_ms is not None:
                ts = float(ts_ms) / 1000.0
            elif recv_ms is not None:
                ts = float(recv_ms) / 1000.0
            if ts is None or ts <= 0:
                continue
            out.append({
                "lat": round(float(item.get("lat")), 7),
                "lon": round(float(item.get("lon")), 7),
                "ts": ts,
                "alt": item.get("alt"),
                "track_type": str(item.get("track_type") or track_type),
                "sample_type": str(item.get("sample_type") or track_type),
                "source": str(item.get("source") or ""),
                "coordinate_system": str(item.get("coordinate_system") or "WGS84"),
            })
        except Exception:
            continue
    return out

def _track_append_point(entry: dict, lat: float, lon: float, wall_ts: float) -> bool:
    if entry is None:
        return False
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return False
    tr = _sanitize_track(entry.get("track") or [])
    if tr:
        last = tr[-1]
        try:
            dt = float(wall_ts) - float(last.get("ts") or 0.0)
        except Exception:
            dt = TRACK_MIN_INTERVAL_SEC
        if (abs(float(last.get("lat", 0.0)) - lat) < 1e-7 and
            abs(float(last.get("lon", 0.0)) - lon) < 1e-7):
            if wall_ts > float(last.get("ts") or 0.0):
                last["ts"] = float(wall_ts)
                entry["track"] = tr
                entry["track_updated_wall_ts"] = float(wall_ts)
                return True
            return False
        if dt < TRACK_MIN_INTERVAL_SEC:
            return False
    tr.append({
        "lat": round(float(lat), 7),
        "lon": round(float(lon), 7),
        "ts": float(wall_ts),
    })
    limit = _track_store_points_limit()
    if len(tr) > limit:
        tr = tr[-limit:]
    entry["track"] = tr
    entry["track_updated_wall_ts"] = float(wall_ts)
    return True

# -----------------------------------------------------------------------------
# Track query helpers
# -----------------------------------------------------------------------------
# Page endpoints can request shorter windows/limits for rendering without
# mutating the persisted full track kept in memory/history.
def _track_query_value(query: dict | None, key: str) -> str:
    if not isinstance(query, dict):
        return ""
    try:
        v = query.get(key)
        if isinstance(v, list):
            return str(v[0] if v else "")
        return str(v or "")
    except Exception:
        return ""

def _track_for_query(raw, query: dict | None = None, firmware_type: str | None = None) -> list[dict]:
    track_type = _track_query_value(query, "track_type").strip().lower() or "aircraft"
    if isinstance(raw, dict):
        base_track = _track_store_primary(raw, track_type if track_type in ("aircraft", "operator") else "aircraft")
    else:
        base_track = _sanitize_track(raw or [])
    # Always normalize stored points before applying request-level trimming.
    track = _track_points_for_display(base_track, firmware_type=firmware_type)
    if not isinstance(query, dict):
        return track
    try:
        window_sec = float(_track_query_value(query, "window") or 0.0)
    except Exception:
        window_sec = 0.0
    if window_sec > 0:
        window_sec = min(max(window_sec, 1.0), 30.0 * 86400.0)
        cutoff = time.time() - window_sec
        track = [p for p in track if float(p.get("ts") or 0.0) >= cutoff]
    try:
        limit = int(float(_track_query_value(query, "limit") or 0))
    except Exception:
        limit = 0
    if limit > 0:
        limit = max(TRACK_STORE_POINTS_MIN, min(limit, _track_store_points_limit()))
        track = track[-limit:]
    return track


def _track_display_count(raw, track_type: str = "aircraft", firmware_type: str | None = None) -> int:
    track_kind = str(track_type or "aircraft").strip().lower() or "aircraft"
    if isinstance(raw, dict):
        base_track = _track_store_primary(raw, track_kind if track_kind in ("aircraft", "operator") else "aircraft")
    else:
        base_track = _sanitize_track(raw or [])
    if _firmware_type_key(firmware_type) != "new":
        return len(base_track)
    base = _web_base_coord_pair()
    ref_lat = base[0] if base else None
    ref_lon = base[1] if base else None
    count = 0
    prev_lat = None
    prev_lon = None
    for p in base_track:
        try:
            lat = float(p.get("lat"))
            lon = float(p.get("lon"))
        except Exception:
            continue
        if _new_fw_coord_anomalous(
            lat,
            lon,
            prev_lat=prev_lat,
            prev_lon=prev_lon,
            ref_lat=ref_lat,
            ref_lon=ref_lon,
        ):
            continue
        count += 1
        prev_lat = lat
        prev_lon = lon
    return count
