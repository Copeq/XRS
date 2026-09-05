"""ap hostapd core (extracted from network_binding_core.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
"""

def _ap_internet_enabled(ap: dict) -> bool:
    return bool(ap.get("internet_enabled") and _network_safe_iface_name(ap.get("uplink_iface")))


def _ap_network_cidr(ap: dict) -> str:
    try:
        return str(ipaddress.ip_network(str(ap.get("cidr") or AP_WEB_CIDR_DEFAULT), strict=False))
    except Exception:
        return "172.16.0.0/24"


def _iptables_ensure_rule(args: list[str], *, privileged: bool = False,
                          sudo_password: str | None = None) -> tuple[bool, str, int]:
    cmd = [_command_path("iptables") or "iptables"] + [str(x) for x in args]
    check_cmd = cmd[:]
    try:
        check_cmd[check_cmd.index("-A")] = "-C"
    except ValueError:
        return False, "iptables rule must use -A", -1
    runner = _run_privileged if privileged else _run_program
    if privileged:
        ok, out, rc = runner(check_cmd, timeout=10, sudo_password=sudo_password)
    else:
        ok, out, rc = runner(check_cmd, timeout=10)
    if ok:
        return True, out, rc
    if privileged:
        return runner(cmd, timeout=10, sudo_password=sudo_password)
    return runner(cmd, timeout=10)


def _apply_ap_internet_sharing_steps(ap_iface: str, ap: dict, *,
                                     privileged: bool = False,
                                     sudo_password: str | None = None) -> list[dict]:
    steps: list[dict] = []
    uplink = _network_safe_iface_name(ap.get("uplink_iface"))
    if not _ap_internet_enabled(ap) or not uplink:
        return steps
    if uplink == ap_iface:
        steps.append({"label": "enable AP Internet sharing", "ok": False, "returncode": -1, "output": "uplink iface must differ from AP iface"})
        return steps
    iptables = _command_path("iptables")
    if not iptables:
        steps.append({"label": "enable AP Internet sharing", "ok": False, "returncode": -1, "output": "iptables not installed"})
        return steps

    def run_step(label: str, args: list[str]) -> bool:
        if privileged:
            ok, out, rc = _run_privileged(args, timeout=10, sudo_password=sudo_password)
        else:
            ok, out, rc = _run_program(args, timeout=10)
        steps.append({"label": label, "ok": ok, "returncode": rc, "output": out})
        return bool(ok)

    def ipt_step(label: str, args: list[str]) -> bool:
        ok, out, rc = _iptables_ensure_rule(args, privileged=privileged, sudo_password=sudo_password)
        steps.append({"label": label, "ok": ok, "returncode": rc, "output": out})
        return bool(ok)

    net = _ap_network_cidr(ap)
    run_step("enable IPv4 forwarding", ["sysctl", "-w", "net.ipv4.ip_forward=1"])
    ipt_step("NAT AP clients to uplink", ["-t", "nat", "-A", "POSTROUTING", "-s", net, "-o", uplink, "-j", "MASQUERADE"])
    ipt_step("allow AP to uplink forwarding", ["-A", "FORWARD", "-i", ap_iface, "-o", uplink, "-j", "ACCEPT"])
    ipt_step("allow uplink replies to AP", ["-A", "FORWARD", "-i", uplink, "-o", ap_iface, "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"])
    return steps


def _stop_hostapd_process(proc) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=2)
        return
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def _kill_hostapd_pid(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 15)
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.05)
            except OSError:
                return True
        os.kill(pid, 9)
        return True
    except Exception:
        return False


def _stop_stale_hostapd(iface: str, cfg_path: str, pid_path: str) -> list[int]:
    stopped: list[int] = []
    try:
        raw = _sysfs_read_text(pid_path).strip() if os.path.exists(pid_path) else ""
        if raw.isdigit() and _kill_hostapd_pid(int(raw)):
            stopped.append(int(raw))
    except Exception:
        pass
    pgrep = _command_path("pgrep")
    if pgrep:
        ok, out, _rc = _run_program([pgrep, "-f", f"hostapd .*{re.escape(cfg_path)}"], timeout=5)
        if ok:
            for line in str(out or "").splitlines():
                raw = line.strip()
                if raw.isdigit():
                    pid = int(raw)
                    if pid not in stopped and _kill_hostapd_pid(pid):
                        stopped.append(pid)
    try:
        if os.path.exists(pid_path):
            os.unlink(pid_path)
    except Exception:
        pass
    return stopped


def _start_hostapd(iface: str, ap: dict) -> dict:
    hostapd = _command_path("hostapd")
    if not hostapd:
        return {"running": False, "error": "hostapd not installed", "pid": None}
    if not (_is_root_user() or _process_has_capabilities(("CAP_NET_ADMIN", "CAP_NET_RAW"))):
        return {"running": False, "error": "hostapd requires root or CAP_NET_ADMIN/CAP_NET_RAW", "pid": None}
    try:
        with network_binding_lock:
            old = (network_binding_runtime.get("hostapd") or {}).get(iface)
        old_proc = old.get("process") if isinstance(old, dict) else None
        _stop_hostapd_process(old_proc)
        cfg_path = os.path.join(tempfile.gettempdir(), f"xrs_hostapd_{iface}.conf")
        log_path = os.path.join(tempfile.gettempdir(), f"xrs_hostapd_{iface}.log")
        pid_path = os.path.join(tempfile.gettempdir(), f"xrs_hostapd_{iface}.pid")
        ctrl_dir = os.path.join(tempfile.gettempdir(), f"xrs_hostapd_ctrl_{iface}")
        stopped = _stop_stale_hostapd(iface, cfg_path, pid_path)
        try:
            os.makedirs(ctrl_dir, mode=0o770, exist_ok=True)
        except Exception:
            pass
        ssid = re.sub(r"[\r\n]+", "", str(ap.get("ssid") or "XRS-HotSpot"))[:32] or "XRS-HotSpot"
        channel = max(1, min(196, int(ap.get("channel") or 6)))
        password = str(ap.get("password") or "")
        lines = [
            f"interface={iface}",
            "driver=nl80211",
            f"ssid={ssid}",
            f"ctrl_interface={ctrl_dir}",
            "ctrl_interface_group=netdev",
            "country_code=CN",
            "ieee80211d=1",
            "wmm_enabled=1",
            "ieee80211n=1",
            "hw_mode=" + ("a" if channel > 14 else "g"),
            f"channel={channel}",
            "auth_algs=1",
            "ignore_broadcast_ssid=0",
        ]
        if password:
            if len(password) < 8:
                return {"running": False, "error": "AP password must be at least 8 characters", "pid": None}
            lines.extend(["wpa=2", f"wpa_passphrase={password}", "wpa_key_mgmt=WPA-PSK", "rsn_pairwise=CCMP"])
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        log_f = open(log_path, "wb")
        proc = subprocess.Popen([hostapd, cfg_path], stdout=log_f, stderr=log_f)
        time.sleep(1.2)
        if proc.poll() is not None:
            try:
                log_f.close()
            except Exception:
                pass
            err = _sysfs_read_text(log_path)[-1200:] if os.path.exists(log_path) else ""
            return {"running": False, "error": err or f"hostapd exited with code {proc.returncode}", "pid": None, "config": cfg_path, "log": log_path}
        err_log = _sysfs_read_text(log_path)[-1200:] if os.path.exists(log_path) else ""
        if "Interface initialization failed" in err_log or "Unable to setup interface" in err_log:
            _stop_hostapd_process(proc)
            return {"running": False, "error": err_log, "pid": None, "config": cfg_path, "log": log_path}
        state = {"running": True, "error": "", "pid": proc.pid, "process": proc, "config": cfg_path, "log": log_path, "ctrl": ctrl_dir}
        if stopped:
            state["stopped_stale_pids"] = stopped
        return state
    except Exception as e:
        return {"running": False, "error": str(e), "pid": None}
