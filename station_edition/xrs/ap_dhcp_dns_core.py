"""ap dhcp dns core (extracted from network_binding_core.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
"""

def _dhcp_ip_to_int(ip: str) -> int:
    return int(ipaddress.ip_address(str(ip)))


def _dhcp_int_to_ip(value: int) -> str:
    return str(ipaddress.ip_address(int(value)))


def _dhcp_option(code: int, data: bytes) -> bytes:
    raw = bytes(data or b"")
    return bytes([int(code) & 0xFF, len(raw) & 0xFF]) + raw


def _dhcp_parse_options(buf: bytes) -> dict:
    opts: dict[int, bytes] = {}
    i = 240
    data = bytes(buf or b"")
    while i < len(data):
        code = data[i]
        i += 1
        if code == 255:
            break
        if code == 0:
            continue
        if i >= len(data):
            break
        ln = data[i]
        i += 1
        opts[int(code)] = data[i:i + ln]
        i += ln
    return opts


def _dhcp_build_reply(req: bytes, msg_type: int, yiaddr: str, server_ip: str, lease_sec: int = 3600) -> bytes:
    xid = req[4:8]
    flags = req[10:12]
    chaddr = req[28:44]
    siaddr = socket.inet_aton(server_ip)
    pkt = bytearray(240)
    pkt[0] = 2
    pkt[1] = req[1] if len(req) > 1 else 1
    pkt[2] = req[2] if len(req) > 2 else 6
    pkt[3] = 0
    pkt[4:8] = xid
    pkt[10:12] = flags
    pkt[16:20] = socket.inet_aton(yiaddr)
    pkt[20:24] = siaddr
    pkt[28:44] = chaddr
    pkt[236:240] = b"\x63\x82\x53\x63"
    options = b"".join([
        _dhcp_option(53, bytes([msg_type])),
        _dhcp_option(54, siaddr),
        _dhcp_option(1, socket.inet_aton("255.255.255.0")),
        _dhcp_option(3, siaddr),
        _dhcp_option(6, siaddr),
        _dhcp_option(51, int(lease_sec).to_bytes(4, "big")),
        _dhcp_option(58, int(max(60, lease_sec // 2)).to_bytes(4, "big")),
        _dhcp_option(59, int(max(120, lease_sec * 7 // 8)).to_bytes(4, "big")),
        _dhcp_option(114, f"http://{server_ip}/".encode("ascii")),
        b"\xff",
    ])
    return bytes(pkt) + options


def _dhcp_mac_from_request(req: bytes) -> str:
    try:
        hlen = int(req[2])
        raw = bytes(req[28:28 + min(hlen, 6)])
        return ":".join(f"{b:02x}" for b in raw)
    except Exception:
        return ""


def _dhcp_requested_ip(opts: dict, req: bytes) -> str:
    raw = opts.get(50)
    if raw and len(raw) == 4:
        return socket.inet_ntoa(raw)
    if len(req) >= 16 and req[12:16] != b"\x00\x00\x00\x00":
        return socket.inet_ntoa(req[12:16])
    return ""


def _dhcp_server_loop(iface: str, ap: dict, state: dict) -> None:
    leases: dict[str, str] = {}
    start_i = _dhcp_ip_to_int(ap.get("dhcp_start") or AP_WEB_DHCP_START_DEFAULT)
    end_i = _dhcp_ip_to_int(ap.get("dhcp_end") or AP_WEB_DHCP_END_DEFAULT)
    server_ip = str(ap.get("address") or AP_WEB_ADDRESS_DEFAULT)
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, 25, str(iface).encode() + b"\x00")
        except Exception:
            pass
        sock.bind(("", 67))
        state["running"] = True
        state["error"] = ""
        next_i = start_i
        while True:
            req, _addr = sock.recvfrom(2048)
            if len(req) < 240 or req[236:240] != b"\x63\x82\x53\x63":
                continue
            opts = _dhcp_parse_options(req)
            msg = int(opts.get(53, b"\x00")[0])
            if msg not in (1, 3):
                continue
            mac = _dhcp_mac_from_request(req)
            if not mac:
                continue
            requested = _dhcp_requested_ip(opts, req)
            yiaddr = leases.get(mac) or ""
            if requested:
                try:
                    req_i = _dhcp_ip_to_int(requested)
                    if start_i <= req_i <= end_i:
                        yiaddr = requested
                except Exception:
                    pass
            if not yiaddr:
                for _ in range(max(1, end_i - start_i + 1)):
                    candidate = _dhcp_int_to_ip(next_i)
                    next_i = start_i if next_i >= end_i else next_i + 1
                    if candidate not in leases.values():
                        yiaddr = candidate
                        break
            if not yiaddr:
                continue
            leases[mac] = yiaddr
            reply_type = 2 if msg == 1 else 5
            reply = _dhcp_build_reply(req, reply_type, yiaddr, server_ip)
            sock.sendto(reply, ("255.255.255.255", 68))
    except Exception as e:
        state["running"] = False
        state["error"] = str(e)
        _log(f"[WARN] DHCP server failed on {iface}: {e}")
    finally:
        try:
            if sock:
                sock.close()
        except Exception:
            pass


def _start_dhcp_server(iface: str, ap: dict) -> None:
    with network_binding_lock:
        current = (network_binding_runtime.get("dhcp_threads") or {}).get(iface)
        if isinstance(current, dict) and current.get("running"):
            return
        state = {"running": False, "error": "", "thread": None}
        network_binding_runtime.setdefault("dhcp_threads", {})[iface] = state
    th = Thread(target=_dhcp_server_loop, args=(iface, dict(ap), state), daemon=True)
    state["thread"] = th
    th.start()


def _dns_question_end(data: bytes, offset: int = 12) -> int | None:
    i = int(offset)
    jumps = 0
    while i < len(data):
        ln = data[i]
        if ln & 0xC0 == 0xC0:
            if i + 1 >= len(data):
                return None
            i += 2
            break
        i += 1
        if ln == 0:
            break
        if i + ln > len(data):
            return None
        i += ln
        jumps += 1
        if jumps > 64:
            return None
    if i + 4 > len(data):
        return None
    return i + 4


def _dns_build_portal_reply(query: bytes, server_ip: str) -> bytes | None:
    data = bytes(query or b"")
    if len(data) < 12:
        return None
    qdcount = int.from_bytes(data[4:6], "big")
    if qdcount < 1:
        return None
    q_end = _dns_question_end(data, 12)
    if not q_end:
        return None
    qtype = int.from_bytes(data[q_end - 4:q_end - 2], "big")
    question = data[12:q_end]
    answer = b""
    ancount = 0
    if qtype in (1, 255):
        answer = (
            b"\xc0\x0c"
            + (1).to_bytes(2, "big")
            + (1).to_bytes(2, "big")
            + (30).to_bytes(4, "big")
            + (4).to_bytes(2, "big")
            + socket.inet_aton(server_ip)
        )
        ancount = 1
    header = (
        data[0:2]
        + (0x8180).to_bytes(2, "big")
        + (1).to_bytes(2, "big")
        + int(ancount).to_bytes(2, "big")
        + b"\x00\x00"
        + b"\x00\x00"
    )
    return header + question + answer


def _dns_server_loop(iface: str, ap: dict, state: dict) -> None:
    server_ip = str(ap.get("address") or AP_WEB_ADDRESS_DEFAULT)
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, 25, str(iface).encode() + b"\x00")
        except Exception:
            pass
        sock.bind((server_ip, 53))
        state["running"] = True
        state["error"] = ""
        _log(f"[INFO] AP DNS captive portal service started: {iface} -> {server_ip}:53")
        while True:
            req, addr = sock.recvfrom(2048)
            reply = _dns_build_portal_reply(req, server_ip)
            if reply:
                sock.sendto(reply, addr)
    except Exception as e:
        state["running"] = False
        state["error"] = str(e)
        _log(f"[WARN] AP DNS captive portal service failed on {iface}: {e}")
    finally:
        try:
            if sock:
                sock.close()
        except Exception:
            pass


def _start_dns_server(iface: str, ap: dict) -> None:
    with network_binding_lock:
        current = (network_binding_runtime.get("dns_threads") or {}).get(iface)
        if isinstance(current, dict) and current.get("running"):
            return
        state = {"running": False, "error": "", "thread": None}
        network_binding_runtime.setdefault("dns_threads", {})[iface] = state
    th = Thread(target=_dns_server_loop, args=(iface, dict(ap), state), daemon=True)
    state["thread"] = th
    th.start()
