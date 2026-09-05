"""cli parse core (extracted from cli_app.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
Scapy / curses / shared names resolve at call time.
"""

def _rid_parser_sn_valid(value) -> bool:
    try:
        text = str(value or "").strip()
    except Exception:
        return False
    return bool(text and RID_PARSE_SN_RE.fullmatch(text))


def _rid_parser_has_coord(decoded: dict | None) -> bool:
    if not isinstance(decoded, dict):
        return False
    loc = decoded.get("location") if isinstance(decoded.get("location"), dict) else None
    if loc and _coord_pair_valid(loc.get("lat"), loc.get("lon")):
        return True
    sys_loc = decoded.get("system") if isinstance(decoded.get("system"), dict) else None
    if sys_loc and _coord_pair_valid(sys_loc.get("pilot_lat"), sys_loc.get("pilot_lon")):
        return True
    meta = decoded.get("metadata") if isinstance(decoded.get("metadata"), dict) else {}
    for key in ("operator_positions", "raw_coords"):
        for item in list(meta.get(key) or []):
            if not isinstance(item, dict):
                continue
            if _coord_pair_valid(item.get("lat"), item.get("lon")):
                return True
    return False


def _rid_parser_hint(pkt_bytes: bytes, ssid_rid: str | None, payloads: list[bytes], gb_payloads: list) -> bool:
    if ssid_rid:
        return True
    if gb_payloads or payloads:
        return True
    raw = bytes(pkt_bytes or b"")
    return (DJI_RID_VENDOR_PREFIX in raw) or (ODID_OUI in raw)


def _packet_clone_for_parse(pkt):
    try:
        return pkt.copy()
    except Exception:
        return pkt


def _packet_parse_drop_one() -> bool:
    try:
        packet_parse_queue.get_nowait()
        return True
    except queue.Empty:
        return False


def _enqueue_packet_for_parse(pkt) -> None:
    global packet_parse_drop_count
    item = _packet_clone_for_parse(pkt)
    while True:
        try:
            packet_parse_queue.put_nowait(item)
            _packet_parse_diag_note_queue(packet_parse_queue.qsize())
            return
        except queue.Full:
            dropped = _packet_parse_drop_one()
            if not dropped:
                return
            packet_parse_drop_count += 1
            if packet_parse_drop_count == 1 or (packet_parse_drop_count % 50) == 0:
                _log(
                    f"[WARN] packet parse queue full, dropped {packet_parse_drop_count} frame(s); "
                    f"queue={packet_parse_queue.qsize()}/{PACKET_PARSE_QUEUE_MAX}"
                )


def _packet_parse_worker_loop() -> None:
    global packet_parse_active_count
    while True:
        pkt = packet_parse_queue.get()
        started_at = time.perf_counter()
        queue_depth = packet_parse_queue.qsize()
        with packet_parse_active_lock:
            packet_parse_active_count += 1
        try:
            _parse_frame_impl(pkt)
        except Exception as ex:
            if DEBUG_MODE:
                _scan(f"[ERR] parse worker: {ex}")
        finally:
            with packet_parse_active_lock:
                packet_parse_active_count = max(0, packet_parse_active_count - 1)
            _packet_parse_diag_note_parse((time.perf_counter() - started_at) * 1000.0, queue_depth=queue_depth)


def start_packet_parse_worker() -> None:
    global packet_parse_worker_started
    if packet_parse_worker_started:
        return
    packet_parse_worker_started = True
    for _ in range(PACKET_PARSE_WORKERS):
        Thread(target=_packet_parse_worker_loop, daemon=True).start()


def parse_frame(pkt) -> None:
    _enqueue_packet_for_parse(pkt)


def _parse_frame_impl(pkt) -> None:
    global ap_seq
    try:
        if simulation_scan_pause_event.is_set():
            return
        if not pkt.haslayer(Dot11): return
        d11 = pkt[Dot11]
        if d11.type != 0: return
        _sniff_note_packet()
        if d11.subtype not in (8, 5, 13): return
        subtype_name = {8:"Beacon",5:"ProbeResp",13:"Action"}.get(d11.subtype,"Mgmt")

        src_mac = d11.addr2 or "unknown"
        rssi    = None
        if pkt.haslayer(RadioTap):
            try: rssi = pkt[RadioTap].dBm_AntSignal
            except Exception: pass

        rt_ch     = _rt_channel(pkt)
        ch        = rt_ch or current_channel
        ch_assumed = (rt_ch is None)
        now       = time.monotonic()

        # SSID 提取
        ssid = None
        if pkt.haslayer(Dot11Beacon):
            try:
                elt = pkt[Dot11Beacon].payload
                while elt and elt.name != "NoPayload":
                    if hasattr(elt,"ID") and elt.ID==0:
                        ssid = bytes(elt.info).decode("utf-8", errors="replace")
                        sn_s = _ssid_to_sn(ssid)
                        if sn_s: mac_to_ssid_sn[src_mac]={"sn":sn_s,"ts":now}
                        break
                    elt = elt.payload
            except Exception: pass
            # AP scan logs (for HTTP log panel)
            ts    = time.strftime("%H:%M:%S")
            rssi_s = f"{rssi}dBm" if rssi is not None else "N/A"
            ch_s2  = f"ch{ch}" if ch else "ch?"
            ssid_s = ssid or "(hidden)"
            with log_lock:
                ap_buf.append(f"[{ts}] {src_mac}  {rssi_s:>8}  {ch_s2:<5}  {ssid_s}")
                ap_seq += 1
            try:
                _ap_touch(src_mac, ssid, rssi, ch, "Beacon")
            except Exception:
                pass

        # Parse GB46750_2025 vendor bodies before legacy DJI ODID fragments.
        payloads = extract_from_ies(pkt)
        ssid_rid = _ssid_to_sn(ssid or "")
        gb_payloads = extract_gb46750_from_ies(pkt, ssid_rid) if d11.subtype == 8 else []
        gb_frame = bool(gb_payloads)
        if d11.subtype in (13, 5, 8):   # Extra: also scan raw payload for all mgmt subtypes
            raw_p = extract_from_raw(pkt)
            # 去重
            sigs = {zlib.crc32(p)&0xFFFFFFFF for p in payloads}
            for p in raw_p:
                if (zlib.crc32(p)&0xFFFFFFFF) not in sigs:
                    payloads.append(p)
            if d11.subtype == 8:
                gb_raw = extract_gb46750_from_raw(pkt, ssid_rid)
                gb_sigs = {_gb_payload_sig(p[0]) for p in gb_payloads}
                for p in gb_raw:
                    sig = _gb_payload_sig(p[0])
                    if sig not in gb_sigs:
                        gb_sigs.add(sig)
                        gb_payloads.append(p)
                if ssid_rid:
                    try:
                        gb_frame = bool(gb_payloads or (DJI_RID_VENDOR_PREFIX in bytes(pkt)))
                    except Exception:
                        gb_frame = bool(gb_payloads)
        if gb_frame and payloads:
            # GB46750 DJI vendor bodies contain byte sequences that
            # can look like legacy ODID fragments. Keep both parser paths
            # separate so those fragments cannot create fake positions.
            payloads = []

        # Debug scan logs
        if DEBUG_MODE:
            rssi_s  = f"{rssi}dBm" if rssi is not None else "N/A"
            ch_s    = f"{'~' if ch_assumed else ''}ch{ch}" if ch else "ch?"
            ssid_s  = f" SSID={ssid!r}" if ssid else ""
            odid_s  = ""
            if payloads:
                types = [f"{((p[0]>>4)&0xF):X}" for p in payloads if p]
                odid_s = f" ODID={len(payloads)}[{','.join(types)}]"
            if gb_payloads:
                odid_s += f" GB46750={len(gb_payloads)}"
            _scan(f"[FRAME] {subtype_name} src={src_mac} {rssi_s} {ch_s}{ssid_s}{odid_s}")

        is_wifi_fast = bool(SCAN_WIFI_FAST) and _is_wifi_fast_mac(src_mac)
        pkt_bytes = b""
        try:
            pkt_bytes = bytes(pkt)
        except Exception:
            pkt_bytes = b""
        rid_parser_hint = _rid_parser_hint(pkt_bytes, ssid_rid, payloads, gb_payloads)
        if not rid_parser_hint:
            payloads = []
            gb_payloads = []
        frame_hex = ""
        try:
            frame_hex = _hex_preview(pkt_bytes, max_bytes=220)
        except Exception:
            frame_hex = ""
        parsed_packets = []
        if rid_parser_hint:
            try:
                parsed_batch = parse_rid_payloads(
                    pkt_bytes,
                    mode="auto",
                    ssid_sn=(ssid_rid or None),
                    model_hint=None,
                )
                parsed_packets = list(parsed_batch.get("packets") or []) if parsed_batch.get("ok") else []
            except Exception:
                parsed_packets = []

        if parsed_packets:
            _notify_hit(ch if not ch_assumed or ch == current_channel else 0)
            for parsed in parsed_packets:
                if not isinstance(parsed, dict):
                    continue
                decoded = parsed.get("decoded") if isinstance(parsed.get("decoded"), dict) else rid_parse_result_to_decoded(parsed)
                if not isinstance(decoded, dict):
                    continue
                fmt = str(parsed.get("format") or "")
                sn = str(parsed.get("sn") or ((decoded.get("basic_id") or {}).get("uas_id") or "")).strip()
                if fmt not in RID_PARSE_FORMATS or not _rid_parser_sn_valid(sn) or not _rid_parser_has_coord(decoded):
                    continue
                body_hex = str(parsed.get("body_hex") or "")
                try:
                    body_bytes = bytes.fromhex(body_hex) if body_hex else bytes(pkt)
                except Exception:
                    body_bytes = bytes(pkt)
                sig = zlib.crc32(body_bytes) & 0xFFFFFFFF
                state_update(
                    src_mac,
                    decoded,
                    rssi=rssi,
                    ch=ch,
                    ch_assumed=ch_assumed,
                    pl_sig=sig,
                    scan_type=("phone" if is_wifi_fast else "rid"),
                    ssid=ssid,
                    capture_type=subtype_name,
                    raw_pkt_hex=(body_hex or frame_hex),
                    firmware_type=("new" if fmt == "GB46750_2025" else "old"),
                )
                if DEBUG_MODE:
                    b = decoded.get("basic_id")
                    l = decoded.get("location")
                    s = decoded.get("system")
                    if b: _scan(f"  -> Parsed BasicID: {b}")
                    if l and l.get("lat") is not None and l.get("lon") is not None:
                        _scan(f"  -> Parsed Location: lat={l.get('lat'):.5f} lon={l.get('lon'):.5f}")
                    if s and s.get("pilot_lat") is not None and s.get("pilot_lon") is not None:
                        _scan(f"  -> Parsed System: lat={s.get('pilot_lat'):.5f} lon={s.get('pilot_lon'):.5f}")
            return

        if not payloads and not gb_payloads:
            # Even without ODID payload, if SSID contains RID SN, still refresh last_seen_ts.
            if is_wifi_fast:
                state_update(src_mac, {"basic_id": {"uas_id": _wifi_fast_sn(src_mac), "id_type": "SSID"}, "location": None, "system": None},
                             rssi=rssi, ch=ch, ch_assumed=ch_assumed, pl_sig=0,
                             scan_type="phone", ssid=(ssid or ""), capture_type=subtype_name,
                             raw_pkt_hex=frame_hex, firmware_type="old")
            elif ssid and src_mac in mac_to_ssid_sn:
                state_update(src_mac, {"basic_id": None, "location": None, "system": None},
                             rssi=rssi, ch=ch, ch_assumed=ch_assumed, pl_sig=0,
                             scan_type="rid", ssid=ssid, capture_type=subtype_name,
                             raw_pkt_hex=frame_hex, firmware_type="old")
            return

        _notify_hit(ch if not ch_assumed or ch==current_channel else 0)

        def explode(p: bytes) -> list[bytes]:
            if not p: return []
            mt = (p[0]>>4)&0xF
            if mt != MSG_TYPE_PACK:
                return [p[:ODID_MSG_SIZE]] if len(p)>=ODID_MSG_SIZE else [p]
            layout = _decode_odid_pack_layout(p)
            if not layout:
                return [p]
            base, msg_size, qty = layout
            out = []
            for i in range(qty):
                s, e2 = base + i * msg_size, base + (i + 1) * msg_size
                if e2 <= len(p): out.append(p[s:e2])
            return out or [p]

        for payload in payloads:
            if not payload: continue
            for piece in explode(payload):
                sig     = zlib.crc32(piece if len(piece)>=ODID_MSG_SIZE else payload)&0xFFFFFFFF
                decoded = decode_odid(piece)
                if is_wifi_fast and not (decoded.get("basic_id") and decoded.get("basic_id", {}).get("uas_id")):
                    decoded = {
                        "basic_id": {"uas_id": _wifi_fast_sn(src_mac), "id_type": "SSID"},
                        "location": decoded.get("location"),
                        "system": decoded.get("system"),
                    }
                if not is_wifi_fast:
                    decoded["metadata"] = {
                        "format": "DJI_OLD_ODID",
                        "rid_format": "DJI_OLD_ODID",
                        "dji_rid_kind": "DJI_OLD_ODID",
                    }
                    legacy_sn = str(((decoded.get("basic_id") or {}).get("uas_id")) or ssid_rid or mac_to_basic.get(src_mac, {}).get("basic", {}).get("uas_id") or "").strip()
                    if not _rid_parser_sn_valid(legacy_sn) or not _rid_parser_has_coord(decoded):
                        continue
                state_update(src_mac, decoded, rssi=rssi, ch=ch,
                             ch_assumed=ch_assumed, pl_sig=sig,
                             scan_type=("phone" if is_wifi_fast else "rid"),
                             ssid=ssid, capture_type=subtype_name,
                             raw_pkt_hex=_hex_preview(piece if piece else payload, max_bytes=160),
                             firmware_type="old")
                if DEBUG_MODE:
                    b = decoded.get("basic_id")
                    l = decoded.get("location")
                    s = decoded.get("system")
                    if b: _scan(f"  -> BasicID: {b}")
                    if l: _scan(f"  -> Location: lat={l.get('lat'):.5f} lon={l.get('lon'):.5f} "
                                f"alt={l.get('alt_geodetic'):.1f}m spd={l.get('speed_ms')}")
                    if s: _scan(f"  -> System(pilot): lat={s.get('pilot_lat')} lon={s.get('pilot_lon')} type={s.get('pilot_loc_type_text')}")
        for body, decoded in gb_payloads:
            if not body or not decoded:
                continue
            meta = decoded.get("metadata") if isinstance(decoded.get("metadata"), dict) else {}
            gb_sn = str(((decoded.get("basic_id") or {}).get("uas_id")) or ssid_rid or "").strip()
            gb_fmt = str(meta.get("format") or meta.get("rid_format") or "")
            if gb_fmt not in RID_PARSE_FORMATS or not _rid_parser_sn_valid(gb_sn) or not _rid_parser_has_coord(decoded):
                continue
            sig = _gb_payload_sig(body)
            state_update(src_mac, decoded, rssi=rssi, ch=ch,
                         ch_assumed=ch_assumed, pl_sig=sig,
                         scan_type="rid", ssid=ssid, capture_type=subtype_name,
                         raw_pkt_hex=_hex_preview(body, max_bytes=160),
                         firmware_type="new")
            if DEBUG_MODE:
                b = decoded.get("basic_id")
                l = decoded.get("location")
                if b: _scan(f"  -> GB BasicID: {b}")
                if l and l.get("lat") is not None and l.get("lon") is not None:
                    _scan(f"  -> GB Location: lat={l.get('lat'):.5f} lon={l.get('lon'):.5f} "
                          f"alt={l.get('alt_geodetic')}m")
    except Exception as ex:
        if DEBUG_MODE:
            _scan(f"[ERR] parse_frame: {ex}")

# -----------------------------------------------------------------------------
# TUI -curses
# -----------------------------------------------------------------------------

# Column definition: (header text, display width, field key)
COLUMNS = [
    ("●",    2, "dot"),
    ("SN",  22, "sn_s"),
    ("机型", 12, "model"),
    ("ch",   5, "ch_s"),
    ("纬度", 11, "lat_s"),
    ("经度", 11, "lon_s"),
    ("高程",  8, "alt_s"),
    ("速度",  8, "spd_s"),
    ("垂速",  7, "vsp_s"),
    ("信号",  8, "rssi_s"),
    ("包",    6, "pkts"),
    ("方向",  4, "dir_s"),
    ("时效",  7, "age_s"),
]
