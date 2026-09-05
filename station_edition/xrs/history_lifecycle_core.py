"""history lifecycle core helpers (extracted from common_core.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
Shared globals/constants and sibling chunk functions resolve at call time in the
shared namespace, so exec order stays after common_core.py.
"""

def _history_reparse_workflow_snapshot() -> dict:
    with history_reparse_lock:
        state = dict(history_reparse_state)
        state["formats"] = dict(history_reparse_state.get("formats") or {})
        state["errors"] = list(history_reparse_state.get("errors") or [])
    queue_depth = 0
    try:
        queue_depth = max(0, int(history_reparse_queue.qsize()))
    except Exception:
        queue_depth = 0
    total = max(0, int(state.get("total") or 0))
    completed = max(0, min(total, int(state.get("completed") or 0)))
    batch_size = max(1, int(state.get("batch_size") or HISTORY_REPARSE_BATCH_SIZE))
    pending = max(0, total - completed)
    batches_total = max(0, int(state.get("batches_total") or 0))
    if not batches_total and total > 0:
        batches_total = int(math.ceil(float(total) / float(batch_size)))
    running = bool(state.get("running"))
    active_batch = max(0, int(state.get("active_batch") or 0))
    progress_pct = 0.0
    if total > 0:
        progress_pct = round(max(0.0, min(100.0, (float(completed) / float(total)) * 100.0)), 1)
    now_wall = time.time()
    started_wall = float(state.get("started_wall") or 0.0)
    finished_wall = float(state.get("finished_wall") or 0.0)
    elapsed_sec = 0.0
    if started_wall > 0.0:
        end_wall = now_wall if running else (finished_wall or now_wall)
        elapsed_sec = max(0.0, end_wall - started_wall)
    rate_per_sec = None
    if elapsed_sec > 0.0 and completed > 0:
        rate_per_sec = round(float(completed) / elapsed_sec, 2)
    decoded_rate_per_sec = None
    decoded = max(0, int(state.get("decoded") or 0))
    if elapsed_sec > 0.0 and decoded > 0:
        decoded_rate_per_sec = round(float(decoded) / elapsed_sec, 2)
    eta_sec = None
    if running and rate_per_sec and rate_per_sec > 0.0 and pending > 0:
        eta_sec = round(float(pending) / float(rate_per_sec), 1)
    state["total"] = total
    state["completed"] = completed
    state["pending"] = pending
    state["batch_size"] = batch_size
    state["batches_total"] = batches_total
    state["batches_pending"] = max(0, int(math.ceil(float(pending) / float(batch_size)))) if pending else 0
    state["active_batch"] = active_batch
    state["queue_depth"] = queue_depth
    state["progress_pct"] = progress_pct
    state["elapsed_sec"] = round(elapsed_sec, 1) if elapsed_sec > 0.0 else 0.0
    state["rate_per_sec"] = rate_per_sec
    state["decoded_rate_per_sec"] = decoded_rate_per_sec
    state["eta_sec"] = eta_sec
    return state

def _history_reparse_workflow_start(
    *,
    kind: str,
    title: str,
    limit: int,
    total: int,
    aircraft_total: int,
    batch_size: int = HISTORY_REPARSE_BATCH_SIZE,
) -> tuple[bool, dict]:
    now_wall = time.time()
    busy = False
    with history_reparse_lock:
        if bool(history_reparse_state.get("running")):
            busy = True
        else:
            history_reparse_state.clear()
            history_reparse_state.update({
                "task_id": f"history-reparse-{int(now_wall * 1000)}",
                "kind": str(kind or "history_recent"),
                "title": str(title or "历史重解析"),
                "status": "running",
                "running": True,
                "limit": max(0, int(limit or 0)),
                "total": max(0, int(total or 0)),
                "completed": 0,
                "decoded": 0,
                "skipped": 0,
                "failed": 0,
                "migrated": 0,
                "saved": False,
                "aircraft_total": max(0, int(aircraft_total or 0)),
                "updated_aircraft": 0,
                "enqueued": 0,
                "producer_done": False,
                "batch_size": max(1, int(batch_size or HISTORY_REPARSE_BATCH_SIZE)),
                "batches_total": int(math.ceil(float(max(0, int(total or 0))) / float(max(1, int(batch_size or HISTORY_REPARSE_BATCH_SIZE))))) if total else 0,
                "active_batch": 0,
                "active_batch_size": 0,
                "message": "queued",
                "last_error": "",
                "started_wall": now_wall,
                "updated_wall": now_wall,
                "finished_wall": 0.0,
                "formats": {},
                "errors": [],
            })
    return (not busy), _history_reparse_workflow_snapshot()

def _history_reparse_workflow_update(**payload) -> dict:
    now_wall = time.time()
    with history_reparse_lock:
        for key, value in (payload or {}).items():
            if key == "formats":
                history_reparse_state["formats"] = dict(value or {})
            elif key == "errors":
                history_reparse_state["errors"] = list(value or [])
            else:
                history_reparse_state[key] = value
        history_reparse_state["updated_wall"] = now_wall
    return _history_reparse_workflow_snapshot()

def _history_reparse_workflow_finish(*, ok: bool, message: str = "", error: str = "", **payload) -> dict:
    final_payload = dict(payload or {})
    final_payload["running"] = False
    final_payload["status"] = "completed" if ok else "failed"
    final_payload["message"] = str(message or ("completed" if ok else error or "failed"))
    final_payload["last_error"] = "" if ok else str(error or message or "failed")
    final_payload["finished_wall"] = time.time()
    final_payload["active_batch_size"] = 0
    return _history_reparse_workflow_update(**final_payload)

def _history_storage_normalize_import_item(raw: dict) -> dict:
    item = dict(raw if isinstance(raw, dict) else {})
    item["tracks"] = _empty_track_store()
    item["track"] = []
    packets = list(item.get("raw_packets") or [])
    if packets:
        item["raw_packets"] = packets[-HISTORY_RAW_PACKET_SNAPSHOT_LIMIT:]
    return item

def _history_storage_migrate_legacy_json(db_path: str) -> tuple[bool, str]:
    conn = _history_db_conn(db_path)
    with history_db_lock:
        row = conn.execute("SELECT value FROM meta WHERE key='legacy_migration_done'").fetchone()
    if row is not None:
        done_value = ""
        try:
            done_value = str(row["value"] or "")
        except Exception:
            done_value = str(row[0] or "")
        if done_value:
            return False, ""
    summary = _history_storage_read_summary(db_path)
    items = summary.get("items") if isinstance(summary, dict) else []
    if isinstance(items, list) and items:
        return False, ""
    source_path = ""
    for candidate in _history_legacy_source_candidates(db_path):
        if os.path.exists(candidate):
            source_path = candidate
            break
    if not source_path:
        return False, ""
    try:
        with open(source_path, "r", encoding="utf-8") as f:
            legacy = json.load(f)
        legacy_items = legacy.get("items") if isinstance(legacy, dict) else legacy
        if not isinstance(legacy_items, list):
            return False, ""
        normalized_items: list[dict] = []
        _history_storage_clear_raw_packets(db_path)
        for raw in legacy_items:
            if not isinstance(raw, dict):
                continue
            item = _history_storage_normalize_import_item(raw)
            sn = str(item.get("sn") or "").strip()
            if not sn:
                continue
            fallback_ts = item.get("last_capture_wall_ts") or item.get("last_seen_wall_ts") or time.time()
            for packet in list(raw.get("raw_packets") or []):
                if not isinstance(packet, dict):
                    continue
                packet_copy = dict(packet)
                packet_copy.setdefault("_wall_ts", fallback_ts)
                _history_storage_append_raw_packet(sn, packet_copy, db_path)
            normalized_items.append(item)
        payload = {
            "version": HISTORY_STORAGE_EXPORT_VERSION,
            "store_version": HISTORY_STORAGE_EXPORT_VERSION,
            "saved_at": time.time(),
            "migrated_from": source_path,
            "items": normalized_items,
        }
        _history_storage_write_summary(payload, db_path)
        with history_db_lock:
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                ("legacy_migration_done", source_path or "done"),
            )
        return True, source_path
    except Exception as exc:
        _log(f"[WARN] history storage migration failed: {exc}")
        return False, source_path

def _history_disk_items_locked(*, include_all_raw_packets: bool = True) -> list[dict]:
    items: list[dict] = []
    for sn, e in history_table.items():
        if not sn:
            continue
        raw_packets = (
            _history_storage_fetch_raw_packets(sn, path=HISTORY_STORE_PATH)
            if include_all_raw_packets and HISTORY_STORE_PATH
            else list(e.get("raw_packets") or [])[-HISTORY_RAW_PACKET_SNAPSHOT_LIMIT:]
        )
        items.append({
            "sn": sn,
            "src_mac": e.get("src_mac"),
            "id_type": e.get("id_type"),
            "uas_id": _uas_id_clean(e.get("uas_id")),
            "kind": e.get("kind"),
            "format": e.get("format"),
            "rid_format": e.get("rid_format"),
            "dji_rid_kind": e.get("dji_rid_kind"),
            "sub_format": e.get("sub_format"),
            "parse_level": e.get("parse_level"),
            "confidence": e.get("confidence"),
            "coordinate_system": e.get("coordinate_system"),
            "warnings": e.get("warnings"),
            "parse_note": e.get("parse_note"),
            "raw_vendor": e.get("raw_vendor"),
            "model": _resolve_model_name(sn, e.get("scan_type"), e.get("model")),
            "last_ch": e.get("last_ch"),
            "ch_assumed": bool(e.get("ch_assumed")),
            "lat": e.get("lat"),
            "lon": e.get("lon"),
            "alt": e.get("alt"),
            "speed": e.get("speed"),
            "vspeed": e.get("vspeed"),
            "pilot_lat": e.get("pilot_lat"),
            "pilot_lon": e.get("pilot_lon"),
            "pilot_loc_type": e.get("pilot_loc_type"),
            "pilot_loc_type_text": e.get("pilot_loc_type_text"),
            "rssi": e.get("rssi"),
            "move_dir": e.get("move_dir"),
            "ssid": e.get("ssid"),
            "gb_data_type": e.get("gb_data_type"),
            "gb_version_raw": e.get("gb_version_raw"),
            "gb_data_len": e.get("gb_data_len"),
            "gb_header": e.get("gb_header"),
            "gb_basic_like": e.get("gb_basic_like"),
            "dji_dynamic": e.get("dji_dynamic"),
            "reg_mark": e.get("reg_mark"),
            "status": e.get("status"),
            "coord_type": e.get("coord_type"),
            "coord_sys": e.get("coord_sys"),
            "coord_sys_text": e.get("coord_sys_text"),
            "home_lat": e.get("home_lat"),
            "home_lon": e.get("home_lon"),
            "aux_lat": e.get("aux_lat"),
            "aux_lon": e.get("aux_lon"),
            "pos_a_lat": e.get("pos_a_lat"),
            "pos_a_lon": e.get("pos_a_lon"),
            "pos_b_lat": e.get("pos_b_lat"),
            "pos_b_lon": e.get("pos_b_lon"),
            "operator_positions": e.get("operator_positions"),
            "raw_coords": e.get("raw_coords"),
            "aircraft_position": e.get("aircraft_position"),
            "tracks": _empty_track_store(),
            "marker_offset": e.get("marker_offset"),
            "capture_type": e.get("capture_type"),
            "firmware_type": _firmware_type_key(e.get("firmware_type")),
            "last_capture_wall_ts": e.get("last_capture_wall_ts"),
            "raw_packets": raw_packets,
            "scan_type": _scan_type_key(e.get("scan_type")),
            "track": [],
            "track_updated_wall_ts": e.get("track_updated_wall_ts"),
            "first_seen_wall_ts": e.get("first_seen_wall_ts"),
            "last_seen_wall_ts": e.get("last_seen_wall_ts"),
            "pkt_count_total": int(e.get("pkt_count_total") or 0),
            "notify_first_online_sent": bool(e.get("notify_first_online_sent")),
            "notify_last_wall_ts": e.get("notify_last_wall_ts"),
            "last_online_duration_sec": e.get("last_online_duration_sec"),
        })
    items.sort(key=lambda x: (-(x.get("last_seen_wall_ts") or 0.0), x.get("sn") or ""))
    return items

def load_history_store(path: str | None) -> None:
    global history_persist_dirty, history_persist_last_save_wall
    if not path:
        return
    try:
        db_path = _history_storage_init(path)
        migrated, migrated_from = _history_storage_migrate_legacy_json(db_path)
        obj = _history_storage_read_summary(db_path)
        items = obj.get("items") if isinstance(obj, dict) else []
        if not isinstance(items, list):
            _log(f"[WARN] history storage summary invalid: {db_path}")
            return
        parsed_packets_by_sn = _history_storage_fetch_parsed_packets_by_sn(db_path)
        loaded = 0
        repaired_model = 0
        compat_dirty = bool(migrated)
        with state_lock:
            history_table.clear()
            for raw in items:
                if not isinstance(raw, dict):
                    continue
                sn = str(raw.get("sn","") or "").strip()
                if not sn:
                    continue
                if "firmware_type" not in raw or "uas_id" not in raw:
                    compat_dirty = True
                h = history_table.get(sn) or {"sn": sn}
                h["sn"] = sn
                for k in HISTORY_DETAIL_KEYS:
                    if k in raw:
                        h[k] = raw.get(k)
                h["scan_type"] = _scan_type_key(h.get("scan_type"))
                h["firmware_type"] = _firmware_type_key(h.get("firmware_type"))
                h["uas_id"] = _uas_id_clean(h.get("uas_id"))
                old_model = str(h.get("model") or "").strip()
                new_model = _resolve_model_name(sn, h.get("scan_type"), h.get("model"))
                if new_model != (old_model if old_model else "N/A"):
                    h["model"] = new_model
                    repaired_model += 1
                raw_packets = list(raw.get("raw_packets") or [])
                if not raw_packets and db_path:
                    raw_packets = _history_storage_fetch_raw_packets(sn, HISTORY_RAW_PACKET_SNAPSHOT_LIMIT, newest_first=True, path=db_path)
                h["raw_packets"] = list(raw_packets or [])[-HISTORY_RAW_PACKET_SNAPSHOT_LIMIT:]
                h["tracks"] = _empty_track_store()
                h["track"] = []
                h["track_updated_wall_ts"] = None
                for packet in list(parsed_packets_by_sn.get(sn) or []):
                    _history_summary_apply_parsed_packet(h, packet)
                h["pkt_count_total"] = max(0, int(raw.get("pkt_count_total") or 0))
                # Monotonic timestamps are process-local; keep them unset until new packets arrive.
                h.setdefault("first_seen_ts", None)
                h.setdefault("last_seen_ts", None)
                history_table[sn] = h
                loaded += 1
            history_persist_dirty = False
            history_persist_last_save_wall = time.time()
        _log(f"[INFO] history storage loaded: {db_path} ({loaded} items)")
        if repaired_model or compat_dirty:
            _history_mark_dirty()
        if compat_dirty:
            if migrated:
                _history_storage_notice(
                    f"检测到旧扫描缓存，已升级到数据库 {os.path.basename(db_path)}。自 {HISTORY_STORAGE_UPGRADE_TARGET} 起仅保留列表最后点位，不再保留历史轨迹，HEX 已迁入数据库。"
                )
                _log(f"[INFO] history storage migrated from legacy json: {migrated_from}")
            else:
                _log("[INFO] history storage summary upgraded for compatibility fields")
        if repaired_model:
            _log(f"[INFO] history model repaired from SN map: {repaired_model}")
    except Exception as e:
        _log(f"[WARN] history storage load failed: {e}")

def save_history_store(force: bool = False) -> bool:
    global history_persist_dirty, history_persist_last_save_wall
    path = HISTORY_STORE_PATH
    if not path:
        return False
    now_wall = time.time()
    if not force and (not history_persist_dirty or (now_wall - history_persist_last_save_wall) < HISTORY_SAVE_INTERVAL):
        return False
    with history_io_lock:
        now_wall = time.time()
        with state_lock:
            if not force and (not history_persist_dirty or (now_wall - history_persist_last_save_wall) < HISTORY_SAVE_INTERVAL):
                return False
            payload = {
                "version": HISTORY_STORAGE_EXPORT_VERSION,
                "store_version": HISTORY_STORAGE_EXPORT_VERSION,
                "saved_at": now_wall,
                "items": _history_disk_items_locked(include_all_raw_packets=False),
            }
            history_persist_dirty = False
        try:
            _history_storage_write_summary(payload, path)
            history_persist_last_save_wall = now_wall
            return True
        except Exception:
            with state_lock:
                history_persist_dirty = True
            if force:
                _log(f"[WARN] history storage save failed: {path}")
            return False

def history_persist_loop() -> None:
    while True:
        time.sleep(HISTORY_SAVE_INTERVAL)
        try:
            save_history_store(force=False)
        except Exception:
            pass

def clear_history_store(delete_file: bool = True) -> tuple[int, bool]:
    global history_persist_dirty, history_persist_last_save_wall
    path = HISTORY_STORE_PATH
    removed_file = False
    with history_io_lock:
        with state_lock:
            cleared = len(history_table)
            history_table.clear()
            history_persist_dirty = False
            history_persist_last_save_wall = time.time()
        if delete_file and path:
            try:
                abs_path = os.path.abspath(path)
                with history_db_lock:
                    if history_db_path and os.path.abspath(str(history_db_path)) == abs_path:
                        _history_db_close_locked()
                if os.path.exists(abs_path):
                    os.remove(abs_path)
                    removed_file = True
            except Exception as e:
                _log(f"[WARN] history storage file delete failed: {e}")
            try:
                for suffix in ("-wal", "-shm"):
                    aux_path = os.path.abspath(path) + suffix
                    if os.path.exists(aux_path):
                        os.remove(aux_path)
            except Exception:
                pass
        else:
            try:
                _history_storage_clear_raw_packets(path)
                _history_storage_write_summary({
                    "version": HISTORY_STORAGE_EXPORT_VERSION,
                    "store_version": HISTORY_STORAGE_EXPORT_VERSION,
                    "saved_at": time.time(),
                    "items": [],
                }, path)
            except Exception as e:
                _log(f"[WARN] history storage clear failed: {e}")
    _log(f"[INFO] history storage cleared: {cleared}" + (f" (deleted file {path})" if removed_file else ""))
    return cleared, removed_file

def delete_history_item(sn: str) -> bool:
    sn = str(sn or "").strip()
    if not sn:
        return False
    removed = False
    with state_lock:
        if sn in history_table:
            history_table.pop(sn, None)
            removed = True
            _history_mark_dirty()
        if sn in state_table:
            state_table.pop(sn, None)
            removed = True
    if removed:
        try:
            _history_storage_delete_sn(sn, HISTORY_STORE_PATH)
        except Exception:
            pass
        try:
            save_history_store(force=True)
        except Exception:
            pass
    return removed

def clear_track_store(sn: str | None = None) -> int:
    """Clear stored trajectory points. Returns affected drone count."""
    affected = 0
    target = str(sn or "").strip()
    with state_lock:
        if target:
            h = history_table.get(target)
            if h is not None and h.get("track"):
                h["track"] = []
                h["track_updated_wall_ts"] = time.time()
                affected += 1
            e = state_table.get(target)
            if e is not None:
                e["track"] = []
                e["track_updated_wall_ts"] = time.time()
            if affected:
                _history_mark_dirty()
            return affected
        for h in history_table.values():
            if h.get("track"):
                h["track"] = []
                h["track_updated_wall_ts"] = time.time()
                affected += 1
        for e in state_table.values():
            e["track"] = []
            e["track_updated_wall_ts"] = time.time()
        if affected:
            _history_mark_dirty()
    return affected

HISTORY_DETAIL_KEYS = (
    "src_mac","id_type","uas_id","model","last_ch","ch_assumed","lat","lon",
    "alt","speed","vspeed","pilot_lat","pilot_lon","pilot_loc_type","pilot_loc_type_text",
    "kind","format","rid_format","dji_rid_kind","sub_format","parse_level","confidence",
    "coordinate_system","warnings","parse_note","raw_vendor",
    "gb_version","gb_identifiers",
    "gb_data_type","gb_version_raw","gb_data_len","gb_header","gb_basic_like","dji_dynamic",
    "reg_mark","status","coord_type",
    "operation_category","operation_category_text",
    "aircraft_category","aircraft_category_text",
    "pilot_alt","track_deg","ground_speed","vertical_speed",
    "alt_relative","alt_geoid","alt_baro",
    "operation_state","operation_state_text",
    "coord_sys","coord_sys_text",
    "horizontal_accuracy","vertical_accuracy","speed_accuracy",
    "timestamp_ms","timestamp_accuracy","timestamp_accuracy_text",
    "home_lat","home_lon","aux_lat","aux_lon",
    "pos_a_lat","pos_a_lon","pos_b_lat","pos_b_lon",
    "operator_positions","raw_coords","aircraft_position","marker_offset",
    "rssi","move_dir","ssid",
    "capture_type","firmware_type","last_capture_wall_ts","raw_packets",
    "scan_type","tracks","track","track_updated_wall_ts",
    "first_seen_wall_ts","last_seen_wall_ts",
    "notify_first_online_sent","notify_last_wall_ts",
    "last_online_duration_sec",
)

def _history_apply_raw_locked(raw: dict) -> tuple[bool, bool]:
    """Apply one imported history/detail record into `history_table`.
    Must be called with `state_lock` held.
    Returns (applied, is_new).
    """
    if not isinstance(raw, dict):
        return False, False
    sn = str(raw.get("sn", "") or "").strip()
    if not sn:
        return False, False
    old = history_table.get(sn)
    is_new = old is None
    h = dict(old) if isinstance(old, dict) else {"sn": sn}
    h["sn"] = sn
    imported_raw_packets = [dict(x) for x in list(raw.get("raw_packets") or []) if isinstance(x, dict)]
    for k in HISTORY_DETAIL_KEYS:
        if k not in raw:
            continue
        if k == "raw_packets":
            h[k] = imported_raw_packets[-HISTORY_RAW_PACKET_SNAPSHOT_LIMIT:]
        elif k in ("tracks", "track"):
            continue
        else:
            h[k] = raw.get(k)
    h["scan_type"] = _scan_type_key(h.get("scan_type"))
    h["firmware_type"] = _firmware_type_key(h.get("firmware_type"))
    h["uas_id"] = _uas_id_clean(h.get("uas_id"))
    h["model"] = _resolve_model_name(sn, h.get("scan_type"), h.get("model"))
    h["tracks"] = _empty_track_store()
    h["track"] = []
    h["track_updated_wall_ts"] = None
    try:
        h["pkt_count_total"] = max(0, int(raw.get("pkt_count_total", h.get("pkt_count_total", 0)) or 0))
    except Exception:
        h["pkt_count_total"] = max(0, int(h.get("pkt_count_total") or 0))
    # Monotonic timestamps are process-local; keep them unset unless produced at runtime.
    h.setdefault("first_seen_ts", None)
    h.setdefault("last_seen_ts", None)
    if imported_raw_packets:
        fallback_ts = h.get("last_capture_wall_ts") or h.get("last_seen_wall_ts") or time.time()
        for packet in imported_raw_packets:
            packet_copy = dict(packet)
            packet_copy.setdefault("_wall_ts", fallback_ts)
            _history_storage_append_raw_packet(sn, packet_copy, HISTORY_STORE_PATH)
    history_table[sn] = h
    return True, is_new
