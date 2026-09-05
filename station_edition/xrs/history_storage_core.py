"""SQLite-backed RID history storage (extracted from common_core.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
Shared globals (db connection cache / locks / constants from common_core.py) resolve at
call time inside the shared namespace, so exec order stays after common_core.py.
"""

def _history_store_default_path(config_path: str | None = None) -> str:
    base_dir = os.getcwd()
    raw_cfg = str(config_path or APP_CONFIG_PATH or "").strip()
    if raw_cfg:
        try:
            base_dir = os.path.dirname(os.path.abspath(raw_cfg)) or base_dir
        except Exception:
            base_dir = os.getcwd()
    return os.path.abspath(os.path.join(base_dir, HISTORY_STORE_DEFAULT))

def _history_set_legacy_source_paths(paths) -> None:
    global HISTORY_LEGACY_SOURCE_PATHS
    next_paths: list[str] = []
    seen: set[str] = set()
    for raw in list(paths or []):
        try:
            path = os.path.abspath(str(raw or "").strip())
        except Exception:
            continue
        if not path:
            continue
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        next_paths.append(path)
    HISTORY_LEGACY_SOURCE_PATHS = next_paths

def _history_legacy_source_candidates(path: str | None = None) -> list[str]:
    db_path = os.path.abspath(str(path or HISTORY_STORE_PATH or _history_store_default_path()))
    base_dir = os.path.dirname(db_path) or os.getcwd()
    out: list[str] = []
    seen: set[str] = {os.path.normcase(db_path)}
    for raw in list(HISTORY_LEGACY_SOURCE_PATHS or []) + [
        os.path.join(base_dir, HISTORY_STORE_LEGACY_DEFAULT),
        os.path.join(base_dir, HISTORY_STORE_LEGACY_ALT_DEFAULT),
    ]:
        try:
            candidate = os.path.abspath(str(raw or "").strip())
        except Exception:
            continue
        if not candidate:
            continue
        key = os.path.normcase(candidate)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out

def _history_parse_wall_ts_text(ts_text: str, fallback: float | None = None) -> float:
    text = str(ts_text or "").strip()
    if text and text != "-":
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                return float(time.mktime(time.strptime(text, fmt)))
            except Exception:
                pass
        try:
            return float(text)
        except Exception:
            pass
    try:
        return float(fallback or 0.0)
    except Exception:
        return 0.0

def _history_hex_text_to_bytes(raw_hex: str) -> bytes:
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

def _history_db_close_locked() -> None:
    global history_db_conn, history_db_path
    if history_db_conn is not None:
        try:
            history_db_conn.close()
        except Exception:
            pass
    history_db_conn = None
    history_db_path = None

def _history_db_conn(path: str | None = None):
    global history_db_conn, history_db_path
    db_path = os.path.abspath(str(path or HISTORY_STORE_PATH or _history_store_default_path()))
    with history_db_lock:
        current = os.path.abspath(str(history_db_path or "")) if history_db_path else ""
        if history_db_conn is not None and current == db_path:
            return history_db_conn
        _history_db_close_locked()
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        history_db_conn = conn
        history_db_path = db_path
        return conn

def _history_storage_init(path: str | None = None) -> str:
    db_path = os.path.abspath(str(path or HISTORY_STORE_PATH or _history_store_default_path()))
    conn = _history_db_conn(db_path)
    with history_db_lock:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_packets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sn TEXT NOT NULL,
                capture_wall_ts REAL NOT NULL DEFAULT 0,
                capture_time_text TEXT,
                capture_type TEXT,
                firmware_type TEXT,
                uas_id TEXT,
                payload BLOB,
                hex_text TEXT,
                decoded_json TEXT,
                parse_mode TEXT,
                parse_format TEXT
            )
            """
        )
        cols = {
            str(row["name"] if isinstance(row, sqlite3.Row) else row[1] or "")
            for row in conn.execute("PRAGMA table_info(raw_packets)").fetchall()
        }
        if "decoded_json" not in cols:
            conn.execute("ALTER TABLE raw_packets ADD COLUMN decoded_json TEXT")
        if "parse_mode" not in cols:
            conn.execute("ALTER TABLE raw_packets ADD COLUMN parse_mode TEXT")
        if "parse_format" not in cols:
            conn.execute("ALTER TABLE raw_packets ADD COLUMN parse_format TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_packets_sn_ts ON raw_packets(sn, capture_wall_ts, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_packets_ts ON raw_packets(capture_wall_ts, id)")
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("schema_version", str(HISTORY_STORAGE_SCHEMA_VERSION)),
        )
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)",
            ("summary_json", json.dumps({"version": HISTORY_STORAGE_EXPORT_VERSION, "items": []}, ensure_ascii=False, separators=(",", ":"))),
        )
    return db_path

def _history_storage_read_summary(path: str | None = None) -> dict:
    _history_storage_init(path)
    conn = _history_db_conn(path)
    with history_db_lock:
        row = conn.execute("SELECT value FROM meta WHERE key='summary_json'").fetchone()
    raw = ""
    if row is not None:
        try:
            raw = str(row["value"] or "")
        except Exception:
            raw = str(row[0] or "")
    if not raw:
        return {"version": HISTORY_STORAGE_EXPORT_VERSION, "items": []}
    try:
        payload = json.loads(raw)
    except Exception:
        return {"version": HISTORY_STORAGE_EXPORT_VERSION, "items": []}
    if not isinstance(payload, dict):
        return {"version": HISTORY_STORAGE_EXPORT_VERSION, "items": []}
    items = payload.get("items")
    if not isinstance(items, list):
        payload["items"] = []
    return payload

def _history_storage_write_summary(payload: dict, path: str | None = None) -> bool:
    db_path = _history_storage_init(path)
    conn = _history_db_conn(db_path)
    try:
        raw = json.dumps(payload if isinstance(payload, dict) else {"version": HISTORY_STORAGE_EXPORT_VERSION, "items": []}, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        raw = json.dumps({"version": HISTORY_STORAGE_EXPORT_VERSION, "items": []}, ensure_ascii=False, separators=(",", ":"))
    with history_db_lock:
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("summary_json", raw),
        )
    return True

def _history_storage_json_dumps(value) -> str:
    if value in (None, "", [], {}, ()):
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        return ""

def _history_storage_json_loads(raw) -> object | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None

def _history_storage_packet_row_to_dict(row) -> dict:
    if row is None:
        return {}
    payload = row["payload"] if isinstance(row, sqlite3.Row) else row[7]
    hex_text = row["hex_text"] if isinstance(row, sqlite3.Row) else row[8]
    raw_hex = ""
    if isinstance(payload, (bytes, bytearray)) and payload:
        raw_hex = bytes(payload).hex()
    elif hex_text not in (None, ""):
        raw_hex = str(hex_text)
    ts_text = row["capture_time_text"] if isinstance(row, sqlite3.Row) else row[3]
    capture_wall_ts = row["capture_wall_ts"] if isinstance(row, sqlite3.Row) else row[2]
    item = {
        "_db_id": int((row["id"] if isinstance(row, sqlite3.Row) else row[0]) or 0),
        "_wall_ts": float(capture_wall_ts or 0.0),
        "ts": str(ts_text or _fmt_wall_ts(float(capture_wall_ts or 0.0))),
        "capture_type": str((row["capture_type"] if isinstance(row, sqlite3.Row) else row[4]) or ""),
        "firmware_type": str((row["firmware_type"] if isinstance(row, sqlite3.Row) else row[5]) or ""),
        "uas_id": str((row["uas_id"] if isinstance(row, sqlite3.Row) else row[6]) or ""),
        "hex": raw_hex,
    }
    parsed = _history_storage_json_loads(row["decoded_json"] if isinstance(row, sqlite3.Row) else row[9])
    if parsed is not None:
        item["parsed"] = parsed
    parse_mode = str((row["parse_mode"] if isinstance(row, sqlite3.Row) else row[10]) or "").strip()
    if parse_mode:
        item["parse_mode"] = parse_mode
    parse_format = str((row["parse_format"] if isinstance(row, sqlite3.Row) else row[11]) or "").strip()
    if parse_format:
        item["parse_format"] = parse_format
    return item

def _history_storage_fetch_raw_packets(sn: str | None = None, limit: int | None = None, *, newest_first: bool = False, path: str | None = None) -> list[dict]:
    db_path = _history_storage_init(path)
    conn = _history_db_conn(db_path)
    clauses = []
    args: list = []
    target_sn = str(sn or "").strip()
    if target_sn:
        clauses.append("sn = ?")
        args.append(target_sn)
    order = "ORDER BY capture_wall_ts DESC, id DESC" if newest_first else "ORDER BY capture_wall_ts ASC, id ASC"
    sql = (
        "SELECT id, sn, capture_wall_ts, capture_time_text, capture_type, firmware_type, uas_id, payload, hex_text, decoded_json, parse_mode, parse_format "
        "FROM raw_packets "
        + (("WHERE " + " AND ".join(clauses) + " ") if clauses else "")
        + order
    )
    if limit is not None and int(limit) > 0:
        sql += " LIMIT ?"
        args.append(int(limit))
    with history_db_lock:
        rows = conn.execute(sql, args).fetchall()
    out = [_history_storage_packet_row_to_dict(row) for row in rows]
    if newest_first:
        out.reverse()
    return out

def _history_storage_fetch_latest_parsed_packets(path: str | None = None) -> dict[str, dict]:
    db_path = _history_storage_init(path)
    conn = _history_db_conn(db_path)
    sql = (
        "SELECT id, sn, capture_wall_ts, capture_time_text, capture_type, firmware_type, uas_id, payload, hex_text, decoded_json, parse_mode, parse_format "
        "FROM raw_packets "
        "WHERE decoded_json IS NOT NULL AND decoded_json <> '' "
        "ORDER BY sn ASC, capture_wall_ts ASC, id ASC"
    )
    with history_db_lock:
        rows = conn.execute(sql).fetchall()
    out: dict[str, dict] = {}
    for row in rows:
        sn = str((row["sn"] if isinstance(row, sqlite3.Row) else row[1]) or "").strip()
        item = _history_storage_packet_row_to_dict(row)
        parsed = item.get("parsed")
        if not sn or not isinstance(parsed, dict):
            continue
        out[sn] = {"sn": sn, "raw": item, "parsed": parsed}
    return out

def _history_storage_fetch_parsed_packets_by_sn(path: str | None = None, per_sn_limit: int | None = HISTORY_RAW_PACKET_SNAPSHOT_LIMIT) -> dict[str, list[dict]]:
    db_path = _history_storage_init(path)
    conn = _history_db_conn(db_path)
    cols = "id, sn, capture_wall_ts, capture_time_text, capture_type, firmware_type, uas_id, payload, hex_text, decoded_json, parse_mode, parse_format"
    try:
        limit = int(per_sn_limit or 0)
    except Exception:
        limit = 0
    with history_db_lock:
        if limit > 0:
            sql = (
                f"SELECT {cols} FROM ("
                f"SELECT {cols}, ROW_NUMBER() OVER (PARTITION BY sn ORDER BY capture_wall_ts DESC, id DESC) AS rn "
                "FROM raw_packets "
                "WHERE decoded_json IS NOT NULL AND decoded_json <> ''"
                ") WHERE rn <= ? "
                "ORDER BY sn ASC, capture_wall_ts ASC, id ASC"
            )
            try:
                rows = conn.execute(sql, (max(1, limit),)).fetchall()
            except sqlite3.Error:
                rows = conn.execute(
                    f"SELECT {cols} FROM raw_packets "
                    "WHERE decoded_json IS NOT NULL AND decoded_json <> '' "
                    "ORDER BY sn ASC, capture_wall_ts ASC, id ASC"
                ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {cols} FROM raw_packets "
                "WHERE decoded_json IS NOT NULL AND decoded_json <> '' "
                "ORDER BY sn ASC, capture_wall_ts ASC, id ASC"
            ).fetchall()
    out: dict[str, list[dict]] = {}
    for row in rows:
        sn = str((row["sn"] if isinstance(row, sqlite3.Row) else row[1]) or "").strip()
        item = _history_storage_packet_row_to_dict(row)
        if not sn or not isinstance(item.get("parsed"), dict):
            continue
        out.setdefault(sn, []).append(item)
    return out

def _history_storage_append_raw_packet(sn: str, raw: dict, path: str | None = None) -> bool:
    target_sn = str(sn or "").strip()
    if not target_sn or not isinstance(raw, dict):
        return False
    raw_hex = str(raw.get("hex") or "").strip()
    if not raw_hex:
        return False
    db_path = _history_storage_init(path)
    conn = _history_db_conn(db_path)
    payload = _history_hex_text_to_bytes(raw_hex)
    capture_wall_ts = _history_parse_wall_ts_text(str(raw.get("ts") or ""), raw.get("_wall_ts"))
    decoded_json = _history_storage_json_dumps(raw.get("parsed"))
    with history_db_lock:
        conn.execute(
            """
            INSERT INTO raw_packets(sn, capture_wall_ts, capture_time_text, capture_type, firmware_type, uas_id, payload, hex_text, decoded_json, parse_mode, parse_format)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_sn,
                float(capture_wall_ts or 0.0),
                str(raw.get("ts") or _fmt_wall_ts(float(capture_wall_ts or 0.0))),
                str(raw.get("capture_type") or ""),
                str(raw.get("firmware_type") or ""),
                str(raw.get("uas_id") or ""),
                sqlite3.Binary(payload) if payload else None,
                raw_hex,
                decoded_json or None,
                str(raw.get("parse_mode") or ""),
                str(raw.get("parse_format") or ""),
            ),
        )
    return True

def _history_storage_update_raw_packet(sn: str, raw: dict, path: str | None = None) -> bool:
    target_sn = str(sn or raw.get("sn") or "").strip()
    if not target_sn or not isinstance(raw, dict):
        return False
    raw_hex = str(raw.get("hex") or "").strip()
    if not raw_hex:
        return False
    db_path = _history_storage_init(path)
    conn = _history_db_conn(db_path)
    payload = _history_hex_text_to_bytes(raw_hex)
    capture_wall_ts = _history_parse_wall_ts_text(str(raw.get("ts") or ""), raw.get("_wall_ts"))
    decoded_json = _history_storage_json_dumps(raw.get("parsed"))
    db_id = raw.get("_db_id")
    updated = False
    with history_db_lock:
        if db_id not in (None, "", 0):
            cur = conn.execute(
                """
                UPDATE raw_packets
                SET sn = ?, capture_wall_ts = ?, capture_time_text = ?, capture_type = ?, firmware_type = ?, uas_id = ?,
                    payload = ?, hex_text = ?, decoded_json = ?, parse_mode = ?, parse_format = ?
                WHERE id = ?
                """,
                (
                    target_sn,
                    float(capture_wall_ts or 0.0),
                    str(raw.get("ts") or _fmt_wall_ts(float(capture_wall_ts or 0.0))),
                    str(raw.get("capture_type") or ""),
                    str(raw.get("firmware_type") or ""),
                    str(raw.get("uas_id") or ""),
                    sqlite3.Binary(payload) if payload else None,
                    raw_hex,
                    decoded_json or None,
                    str(raw.get("parse_mode") or ""),
                    str(raw.get("parse_format") or ""),
                    int(db_id),
                ),
            )
            updated = bool(cur.rowcount)
    if updated:
        return True
    return _history_storage_append_raw_packet(target_sn, raw, db_path)

def _history_storage_update_raw_packet_parse_result(sn: str, raw: dict, parsed: dict | None, parse_mode: str | None = None, parse_format: str | None = None, path: str | None = None) -> bool:
    target_sn = str(sn or (raw or {}).get("sn") or "").strip()
    if not target_sn or not isinstance(raw, dict):
        return False
    raw_hex = str(raw.get("hex") or "").strip()
    if not raw_hex:
        return False
    db_path = _history_storage_init(path)
    conn = _history_db_conn(db_path)
    decoded_json = _history_storage_json_dumps(parsed)
    db_id = raw.get("_db_id")
    updated = False
    with history_db_lock:
        if db_id not in (None, "", 0):
            cur = conn.execute(
                """
                UPDATE raw_packets
                SET sn = ?, decoded_json = ?, parse_mode = ?, parse_format = ?
                WHERE id = ?
                """,
                (
                    target_sn,
                    decoded_json or None,
                    str(parse_mode or raw.get("parse_mode") or ""),
                    str(parse_format or raw.get("parse_format") or ""),
                    int(db_id),
                ),
            )
            updated = bool(cur.rowcount)
        if not updated:
            capture_wall_ts = _history_parse_wall_ts_text(str(raw.get("ts") or ""), raw.get("_wall_ts"))
            cur = conn.execute(
                """
                UPDATE raw_packets
                SET sn = ?, decoded_json = ?, parse_mode = ?, parse_format = ?
                WHERE sn = ? AND hex_text = ? AND ABS(capture_wall_ts - ?) < 0.001
                """,
                (
                    target_sn,
                    decoded_json or None,
                    str(parse_mode or raw.get("parse_mode") or ""),
                    str(parse_format or raw.get("parse_format") or ""),
                    target_sn,
                    raw_hex,
                    float(capture_wall_ts or 0.0),
                ),
            )
            updated = bool(cur.rowcount)
    if updated:
        return True
    raw_copy = dict(raw)
    raw_copy["parsed"] = parsed
    raw_copy["parse_mode"] = str(parse_mode or raw_copy.get("parse_mode") or "")
    raw_copy["parse_format"] = str(parse_format or raw_copy.get("parse_format") or "")
    return _history_storage_append_raw_packet(target_sn, raw_copy, db_path)

def _history_storage_update_raw_packet_parse_results(items: list[dict], path: str | None = None) -> int:
    if not isinstance(items, list) or not items:
        return 0
    db_path = _history_storage_init(path)
    updates: list[tuple] = []
    fallback_appends: list[tuple[str, dict]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        target_sn = str(item.get("sn") or "").strip()
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        if not target_sn or not raw:
            continue
        decoded_json = _history_storage_json_dumps(item.get("parsed"))
        parse_mode = str(item.get("parse_mode") or raw.get("parse_mode") or "")
        parse_format = str(item.get("parse_format") or raw.get("parse_format") or "")
        db_id = raw.get("_db_id")
        if db_id not in (None, "", 0):
            updates.append((target_sn, decoded_json or None, parse_mode, parse_format, int(db_id)))
        else:
            raw_copy = dict(raw)
            raw_copy["parsed"] = item.get("parsed")
            raw_copy["parse_mode"] = parse_mode
            raw_copy["parse_format"] = parse_format
            fallback_appends.append((target_sn, raw_copy))
    updated = 0
    if updates:
        conn = sqlite3.connect(db_path, timeout=5.0)
        try:
            cur = conn.executemany(
                """
                UPDATE raw_packets
                SET sn = ?, decoded_json = ?, parse_mode = ?, parse_format = ?
                WHERE id = ?
                """,
                updates,
            )
            conn.commit()
            updated += int(cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else len(updates))
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass
    for target_sn, raw_copy in fallback_appends:
        if _history_storage_append_raw_packet(target_sn, raw_copy, db_path):
            updated += 1
    return updated

def _history_summary_apply_parsed_packet(record: dict, packet: dict) -> None:
    parsed = packet.get("parsed") if isinstance(packet, dict) else None
    if not isinstance(record, dict) or not isinstance(parsed, dict):
        return
    basic = parsed.get("basic_id") if isinstance(parsed.get("basic_id"), dict) else {}
    loc = parsed.get("location") if isinstance(parsed.get("location"), dict) else {}
    sys_loc = parsed.get("system") if isinstance(parsed.get("system"), dict) else {}
    meta = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
    uas_id = _uas_id_clean(parsed.get("uas_id") or basic.get("uas_id") or record.get("uas_id"))
    if uas_id:
        record["uas_id"] = uas_id
    if basic.get("id_type"):
        record["id_type"] = basic.get("id_type")
    firmware_type = _firmware_type_key(parsed.get("firmware_type") or packet.get("firmware_type") or record.get("firmware_type"))
    if firmware_type:
        record["firmware_type"] = firmware_type
    record["scan_type"] = _scan_type_key(record.get("scan_type"))
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
        if src_key in loc and loc.get(src_key) is not None:
            record[key] = loc.get(src_key)
    for key, src_key in (
        ("pilot_lat", "pilot_lat"),
        ("pilot_lon", "pilot_lon"),
        ("pilot_alt", "pilot_alt"),
        ("pilot_loc_type", "pilot_loc_type"),
        ("pilot_loc_type_text", "pilot_loc_type_text"),
    ):
        if src_key in sys_loc and sys_loc.get(src_key) is not None:
            record[key] = sys_loc.get(src_key)
    for key in NEW_FW_DETAIL_KEYS:
        if key in meta:
            record[key] = meta.get(key)
    for key in ("rid_format", "dji_rid_kind", "kind", "parse_note", "enterprise_model", "operator_positions", "raw_coords"):
        if key in meta:
            record[key] = meta.get(key)
    try:
        wall_ts = float(packet.get("_wall_ts") or 0.0)
    except Exception:
        wall_ts = 0.0
    if wall_ts > 0:
        record["last_capture_wall_ts"] = max(float(record.get("last_capture_wall_ts") or 0.0), wall_ts)
        record["last_seen_wall_ts"] = max(float(record.get("last_seen_wall_ts") or 0.0), wall_ts)
    track_store = record.get("tracks")
    if not isinstance(track_store, dict):
        track_store = _sanitize_tracks(record.get("track") or [])
    try:
        lat_f = float(loc.get("lat"))
        lon_f = float(loc.get("lon"))
    except Exception:
        lat_f = None
        lon_f = None
    if lat_f is not None and lon_f is not None and (-90.0 <= lat_f <= 90.0) and (-180.0 <= lon_f <= 180.0) and not (abs(lat_f) < 0.001 and abs(lon_f) < 0.001):
        sample = {
            "sample_type": "aircraft",
            "track_type": "aircraft",
            "sn": str(record.get("sn") or "") or None,
            "uas_id": record.get("uas_id"),
            "lat": round(lat_f, 7),
            "lon": round(lon_f, 7),
            "alt": record.get("alt"),
            "speed": record.get("speed"),
            "direction": record.get("move_dir"),
            "timestamp_ms": loc.get("timestamp_ms"),
            "receive_time_ms": int(float(wall_ts or time.time()) * 1000.0),
            "packet_hash": str(packet.get("hex") or "")[:128],
            "source": "history_db_parsed",
            "coordinate_system": "WGS84",
        }
        if _track_store_append_sample(track_store, sample):
            record["tracks"] = track_store
            record["track"] = _track_store_primary(track_store, "aircraft")
            last_aircraft = track_store.get("last_aircraft")
            if isinstance(last_aircraft, dict):
                try:
                    record["track_updated_wall_ts"] = float((last_aircraft.get("receive_time_ms") or last_aircraft.get("timestamp_ms") or 0) / 1000.0)
                except Exception:
                    record["track_updated_wall_ts"] = wall_ts or None

def _history_storage_delete_sn(sn: str, path: str | None = None) -> None:
    target_sn = str(sn or "").strip()
    if not target_sn:
        return
    db_path = _history_storage_init(path)
    conn = _history_db_conn(db_path)
    with history_db_lock:
        conn.execute("DELETE FROM raw_packets WHERE sn = ?", (target_sn,))

def _history_storage_reassign_sn(old_sn: str, new_sn: str, path: str | None = None) -> None:
    old_key = str(old_sn or "").strip()
    new_key = str(new_sn or "").strip()
    if not old_key or not new_key or old_key == new_key:
        return
    db_path = _history_storage_init(path)
    conn = _history_db_conn(db_path)
    with history_db_lock:
        conn.execute("UPDATE raw_packets SET sn = ? WHERE sn = ?", (new_key, old_key))

def _history_storage_clear_raw_packets(path: str | None = None) -> None:
    db_path = _history_storage_init(path)
    conn = _history_db_conn(db_path)
    with history_db_lock:
        conn.execute("DELETE FROM raw_packets")

def _history_storage_notice(message: str, kind: str = "warn") -> None:
    text = str(message or "").strip()
    if not text:
        return
    notice = {
        "text": text,
        "kind": "warn" if str(kind or "").strip().lower() == "warn" else "ok",
    }
    global history_storage_pending_notice
    with history_storage_notice_lock:
        history_storage_pending_notice = dict(notice)
    try:
        _notification_add(text, notice["kind"], "server")
    except Exception:
        pass

def _history_storage_notice_payload(consume: bool = False) -> dict:
    global history_storage_pending_notice
    with history_storage_notice_lock:
        notice = dict(history_storage_pending_notice or {})
        if consume:
            history_storage_pending_notice = None
    return notice
