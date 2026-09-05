"""Scan-diff event/change-log helpers (extracted from process_core.py during backend split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
References state_table/log buffers and change flags resolve at call time.
"""

def _scan_diff_round(value):
    try:
        if value is None:
            return None
        return round(float(value), 7)
    except Exception:
        return value

def _scan_diff_position_digest(items) -> tuple[str, ...]:
    out: list[str] = []
    for item in list(items or [])[:4]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or item.get("source") or "?").strip() or "?"
        lat = _fmt(_scan_diff_round(item.get("lat")), ".6f")
        lon = _fmt(_scan_diff_round(item.get("lon")), ".6f")
        alt = _fmt(item.get("alt"), ".1f", "m")
        out.append(f"{role}@{lat},{lon},{alt}")
    return tuple(out)

def _scan_diff_state_snapshot(entry: dict | None) -> dict:
    if not isinstance(entry, dict):
        return {}
    snap = {
        "warnings": tuple(str(x) for x in (entry.get("warnings") or []) if str(x)),
        "operator_positions": _scan_diff_position_digest(entry.get("operator_positions")),
        "raw_coords": _scan_diff_position_digest(entry.get("raw_coords")),
        "raw_packets_count": len(list(entry.get("raw_packets") or [])),
    }
    for key in SCAN_DIFF_FIELDS:
        if key in snap:
            continue
        value = entry.get(key)
        if key in (
            "lat", "lon", "alt", "speed", "vspeed",
            "pilot_lat", "pilot_lon", "pilot_alt",
            "home_lat", "home_lon", "aux_lat", "aux_lon",
            "pos_a_lat", "pos_a_lon", "pos_b_lat", "pos_b_lon",
        ):
            value = _scan_diff_round(value)
        elif key == "parse_note":
            value = str(value or "").strip()[:240]
        elif key in ("scan_type", "firmware_type", "capture_type", "ssid", "rid_format", "dji_rid_kind", "sub_format", "parse_level", "coordinate_system", "sn", "src_mac", "id_type", "uas_id", "model"):
            value = str(value or "").strip()
        snap[key] = value
    return snap

def _scan_diff_format_value(value) -> str:
    if value in (None, "", (), [], {}):
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if isinstance(value, tuple):
        return "; ".join(_scan_diff_format_value(x) for x in value) or "-"
    return str(value)

def _scan_diff_change_lines(before: dict, after: dict, limit: int = 18) -> list[str]:
    keys = [key for key in SCAN_DIFF_FIELDS if before.get(key) != after.get(key)]
    lines: list[str] = []
    for key in keys[:limit]:
        label = SCAN_DIFF_LABELS.get(key, key)
        lines.append(f"  ~ {label}: {_scan_diff_format_value(before.get(key))} -> {_scan_diff_format_value(after.get(key))}")
    extra = len(keys) - limit
    if extra > 0:
        lines.append(f"  ... {extra} more fields changed")
    return lines


def _scan_diff_changed_keys(before: dict, after: dict) -> list[str]:
    return [key for key in SCAN_DIFF_FIELDS if before.get(key) != after.get(key)]

def _scan_diff_header(after: dict) -> str:
    return (
        f"[SCAN_DIFF] sn={after.get('sn') or '-'} uas={after.get('uas_id') or '-'} "
        f"model={after.get('model') or '-'} scan={after.get('scan_type') or '-'} fw={after.get('firmware_type') or '-'}"
    )

def _scan_diff_summary_lines(after: dict) -> list[str]:
    lines = [
        "  parser: "
        f"format={after.get('rid_format') or after.get('dji_rid_kind') or '-'} "
        f"sub={after.get('sub_format') or '-'} "
        f"level={after.get('parse_level') or '-'} "
        f"coord={after.get('coordinate_system') or '-'}",
        "  radio: "
        f"capture={after.get('capture_type') or '-'} "
        f"ch={_scan_diff_format_value(after.get('last_ch'))}{'~' if after.get('ch_assumed') else ''} "
        f"rssi={_scan_diff_format_value(after.get('rssi'))} "
        f"pl={_scan_diff_format_value(after.get('pl_sig'))} "
        f"raw_packets={_scan_diff_format_value(after.get('raw_packets_count'))}",
        "  aircraft: "
        f"lat={_scan_diff_format_value(after.get('lat'))} "
        f"lon={_scan_diff_format_value(after.get('lon'))} "
        f"alt={_scan_diff_format_value(after.get('alt'))} "
        f"spd={_scan_diff_format_value(after.get('speed'))} "
        f"vspd={_scan_diff_format_value(after.get('vspeed'))}",
        "  operator: "
        f"pilot={_scan_diff_format_value(after.get('pilot_lat'))},{_scan_diff_format_value(after.get('pilot_lon'))},{_scan_diff_format_value(after.get('pilot_alt'))} "
        f"roles={_scan_diff_format_value(after.get('operator_positions'))}",
    ]
    note = str(after.get("parse_note") or "").strip()
    if note:
        lines.append(f"  note: {note}")
    warnings = after.get("warnings") or ()
    if warnings:
        lines.append(f"  warnings: {_scan_diff_format_value(warnings)}")
    return lines

def _build_scan_diff_entry(before: dict, after: dict, *, reason: str) -> str:
    title = _scan_diff_header(after)
    lines = [f"{title} reason={reason}"]
    lines.extend(_scan_diff_summary_lines(after))
    change_lines = _scan_diff_change_lines(before, after)
    if change_lines:
        lines.append("  changes:")
        lines.extend(change_lines)
    else:
        lines.append("  changes: (none)")
    return "\n".join(lines)

NEW_FW_DETAIL_KEYS = (
    "kind", "format", "rid_format", "dji_rid_kind", "sub_format",
    "parse_level", "confidence", "coordinate_system", "warnings", "parse_note", "raw_vendor",
    "gb_version", "gb_identifiers",
    "gb_data_type", "gb_version_raw", "gb_data_len", "gb_header", "gb_basic_like", "dji_dynamic",
    "reg_mark", "status", "coord_type",
    "operation_category", "operation_category_text",
    "aircraft_category", "aircraft_category_text",
    "pilot_alt", "track_deg", "ground_speed", "vertical_speed",
    "alt_relative", "alt_geoid", "alt_baro",
    "operation_state", "operation_state_text",
    "coord_sys", "coord_sys_text",
    "horizontal_accuracy", "vertical_accuracy", "speed_accuracy",
    "timestamp_ms", "timestamp_accuracy", "timestamp_accuracy_text",
    "home_lat", "home_lon", "aux_lat", "aux_lon",
    "pos_a_lat", "pos_a_lon", "pos_b_lat", "pos_b_lon",
    "operator_positions", "raw_coords", "aircraft_position", "track_samples", "marker_offset",
)
