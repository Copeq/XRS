"""systemd iw core (extracted from hardware_core.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
Command/privilege helpers from hardware_core.py resolve at call time.
"""

def _systemd_enabled_fallback() -> str:
    if not os.path.exists(SYSTEMD_SERVICE_PATH):
        return "not-found"
    wants_root = "/etc/systemd/system"
    try:
        for name in os.listdir(wants_root):
            if not name.endswith(".wants"):
                continue
            link_path = os.path.join(wants_root, name, SYSTEMD_SERVICE_NAME)
            if os.path.exists(link_path):
                return "enabled"
    except Exception:
        pass
    return "disabled"

def _current_process_in_systemd_service() -> bool:
    if not _is_linux_host():
        return False
    try:
        with open("/proc/self/cgroup", "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        return SYSTEMD_SERVICE_NAME in text
    except Exception:
        return False

def _systemd_active_fallback() -> str:
    if _current_process_in_systemd_service():
        return "active"
    return "unknown"

def _iw_manual_install_hint() -> str:
    return "请手动安装: sudo apt-get update && sudo apt-get install -y iw hostapd"

def _iw_missing_message() -> str:
    return "未检测到 iw 命令，无法枚举或切换无线网卡。"

def _set_iw_check_state(**updates) -> dict:
    with iw_check_lock:
        IW_CHECK_STATE.update(updates)
        return dict(IW_CHECK_STATE)

def _refresh_iw_check_state(message: str | None = None) -> dict:
    path = _command_path(IW_PACKAGE_NAME)
    hostapd_path = _command_path("hostapd")
    available = bool(path)
    msg = str(message or "").strip()
    if not msg:
        if available and hostapd_path:
            msg = f"无线工具可用: iw={path} hostapd={hostapd_path}"
        elif not available:
            msg = _iw_missing_message()
        else:
            msg = "未检测到 hostapd，AP 热点无法广播。"
    return _set_iw_check_state(
        checked=True,
        available=available,
        path=path,
        hostapd_available=bool(hostapd_path),
        hostapd_path=hostapd_path,
        message=msg,
        manual_hint=("" if available and hostapd_path else _iw_manual_install_hint()),
    )

def _iw_status_payload(refresh: bool = True) -> dict:
    with iw_check_lock:
        checked = bool(IW_CHECK_STATE.get("checked"))
    if refresh or not checked:
        snap = _refresh_iw_check_state()
    else:
        with iw_check_lock:
            snap = dict(IW_CHECK_STATE)
    snap["sudo_available"] = _sudo_available()
    snap["can_install"] = bool(_is_linux_host() and _can_run_privileged_actions() and _command_path("apt-get"))
    snap["package"] = IW_PACKAGE_NAME
    return snap

def _install_iw_package(sudo_password: str | None = None) -> dict:
    existing = _iw_status_payload(refresh=True)
    if existing.get("available") and existing.get("hostapd_available"):
        return {
            "ok": True,
            "installed": False,
            "message": "无线工具已可用，无需安装。",
            "iw": existing,
        }
    _set_iw_check_state(install_attempted=True, install_ok=False)
    if not _is_linux_host():
        snap = _refresh_iw_check_state("当前主机不是 Linux，无法通过网页自动安装无线工具。")
        return {"ok": False, "installed": False, "error": snap.get("message"), "iw": snap}
    if not _command_path("apt-get"):
        snap = _refresh_iw_check_state("未检测到 apt-get，无法通过网页自动安装无线工具。")
        return {"ok": False, "installed": False, "error": snap.get("message"), "iw": snap}
    if not _can_run_privileged_actions():
        snap = _refresh_iw_check_state("网页安装无线工具需要 root 或 sudo 提权。")
        return {"ok": False, "installed": False, "error": snap.get("message"), "iw": snap}

    env = dict(os.environ)
    env["DEBIAN_FRONTEND"] = "noninteractive"
    ok_update, out_update, rc_update = _run_privileged(["apt-get", "update"], timeout=300, env=env, sudo_password=sudo_password)
    if not ok_update:
        snap = _refresh_iw_check_state("apt-get update 失败，无法通过网页安装无线工具。")
        return {
            "ok": False,
            "installed": False,
            "error": snap.get("message"),
            "returncode": rc_update,
            "output": out_update,
            "iw": snap,
        }
    ok_install, out_install, rc_install = _run_privileged(["apt-get", "install", "-y", IW_PACKAGE_NAME, "hostapd"], timeout=300, env=env, sudo_password=sudo_password)
    snap = _refresh_iw_check_state("无线工具安装完成。" if ok_install else "apt-get install iw hostapd 失败。")
    installed = bool(ok_install and snap.get("available") and snap.get("hostapd_available"))
    _set_iw_check_state(install_ok=installed)
    snap = _iw_status_payload(refresh=False)
    return {
        "ok": installed,
        "installed": installed,
        "error": "" if installed else str(snap.get("message") or "wireless tools install failed"),
        "returncode": rc_install,
        "output": _truncate_text((out_update + "\n" + out_install).strip()),
        "iw": snap,
    }

def _prompt_install_iw_on_startup() -> bool:
    try:
        return bool(sys.stdin and sys.stdin.isatty() and sys.stdout and sys.stdout.isatty())
    except Exception:
        return False

def check_iw_available_on_startup() -> bool:
    snap = _iw_status_payload(refresh=True)
    if snap.get("available"):
        _log(f"[INFO] iw command available: {snap.get('path')}")
        return True

    msg = f"{snap.get('message') or _iw_missing_message()} {snap.get('manual_hint') or _iw_manual_install_hint()}"
    _log(f"[WARN] {msg}")
    _sniff_note_error(msg)
    if not (_is_linux_host() and _is_root_user() and _command_path("apt-get") and _prompt_install_iw_on_startup()):
        _log("[WARN] 启动环境无法交互确认自动安装 iw，请手动安装后重启服务。")
        return False

    try:
        answer = input("未检测到 iw，是否现在自动安装？这将执行 apt-get update && apt-get install -y iw [y/N]: ")
    except Exception:
        answer = ""
    if str(answer or "").strip().lower() not in ("y", "yes"):
        _log(f"[WARN] 已跳过 iw 自动安装。{_iw_manual_install_hint()}")
        return False

    rsp = _install_iw_package()
    if rsp.get("ok"):
        _log("[INFO] iw installed successfully")
        return True
    _log(f"[WARN] iw 自动安装失败: {rsp.get('error') or rsp.get('output') or 'unknown error'}")
    _log(f"[WARN] {_iw_manual_install_hint()}")
    return False

# -----------------------------------------------------------------------------
# Privileged runtime repair / systemd helpers
# -----------------------------------------------------------------------------
def _systemd_supported() -> tuple[bool, str]:
    if not _is_linux_host():
        return False, "当前主机不是 Linux。"
    if not _command_path("systemctl"):
        return False, "未检测到 systemctl。"
    return True, ""

def _systemd_quote_arg(value: str) -> str:
    s = str(value or "")
    if not s:
        return '""'
    if re.search(r"\s|[\"\\]", s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s

def _systemd_service_spec() -> dict:
    # Always point the generated unit at the current script/config pair and
    # force no-TUI mode for unattended service execution.
    script = os.path.abspath(_runtime_entrypoint_path())
    workdir = os.path.abspath(APP_START_CWD or os.path.dirname(script) or ".")
    config_path = os.path.abspath(APP_CONFIG_PATH or os.path.join(workdir, CONFIG_FILE_DEFAULT))
    py = os.path.abspath(sys.executable or "python3")
    if getattr(sys, "frozen", False):
        exec_parts = [_systemd_quote_arg(py)]
    else:
        exec_parts = [_systemd_quote_arg(py), _systemd_quote_arg(script)]
    exec_start = " ".join([
        *exec_parts,
        "--config",
        _systemd_quote_arg(config_path),
        "--no-tui",
    ])
    service_lines = [
        "[Unit]",
        "Description=XRS",
        "Wants=network-online.target",
        "After=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        "Environment=PYTHONUNBUFFERED=1",
        f"WorkingDirectory={_systemd_quote_arg(workdir)}",
        f"ExecStart={exec_start}",
        f"User={RUNTIME_SERVICE_USER}",
    ]
    if _local_group_exists(RUNTIME_SERVICE_USER):
        service_lines.append(f"Group={RUNTIME_SERVICE_USER}")
    if _local_group_exists("netdev"):
        service_lines.append("SupplementaryGroups=netdev")
    caps = " ".join(RUNTIME_SERVICE_CAPABILITIES)
    service_lines.extend([
        f"AmbientCapabilities={caps}",
        f"CapabilityBoundingSet={caps}",
        "Restart=on-failure",
        "RestartSec=3",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ])
    unit = "\n".join(service_lines)
    return {
        "service_name": SYSTEMD_SERVICE_NAME,
        "service_path": SYSTEMD_SERVICE_PATH,
        "python": py,
        "script": script,
        "cwd": workdir,
        "config_path": config_path,
        "exec_start": exec_start,
        "service_user": RUNTIME_SERVICE_USER,
        "service_home": RUNTIME_SERVICE_HOME,
        "service_capabilities": list(RUNTIME_SERVICE_CAPABILITIES),
        "unit_text": unit,
    }

def _read_systemd_unit_text() -> tuple[str, str]:
    try:
        if os.path.exists(SYSTEMD_SERVICE_PATH):
            with open(SYSTEMD_SERVICE_PATH, "r", encoding="utf-8", errors="ignore") as f:
                return f.read(), ""
    except Exception as e:
        return "", str(e)
    return "", ""

def _unit_declared_user(unit_text: str) -> str:
    try:
        for line in str(unit_text or "").splitlines():
            s = line.strip()
            if s.startswith("User="):
                return s.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""

def _runtime_security_payload(unit_text: str | None = None) -> dict:
    uid = _current_uid()
    current_user = _username_for_uid(uid)
    running_as_root = _is_root_user()
    if unit_text is None:
        unit_text, _err = _read_systemd_unit_text()
    actual_service_user = _unit_declared_user(unit_text or "")
    dedicated_exists = _local_user_exists(RUNTIME_SERVICE_USER)
    sudo_available = _sudo_available()
    caps_ok = bool(_process_has_capabilities(list(RUNTIME_SERVICE_CAPABILITIES)))
    risk = "当前程序以 root 权限运行，网页接口和采集进程拥有过高权限。"
    no_caps = f"当前程序以 {current_user or '非 root'} 权限运行，但未检测到采集所需网络能力。"
    ok_msg = f"当前程序以 {current_user or '非 root'} 权限运行。"
    level = "warn" if running_as_root or (not running_as_root and _is_linux_host() and not caps_ok) else "ok"
    return {
        "ok": True,
        "current_uid": uid,
        "current_user": current_user,
        "running_as_root": bool(running_as_root),
        "has_network_capabilities": bool(caps_ok),
        "risk": "root-runtime" if running_as_root else ("" if caps_ok or not _is_linux_host() else "missing-capabilities"),
        "level": level,
        "message": risk if running_as_root else (ok_msg if caps_ok or not _is_linux_host() else no_caps),
        "dedicated_user": RUNTIME_SERVICE_USER,
        "dedicated_user_exists": bool(dedicated_exists),
        "service_user": actual_service_user,
        "service_uses_dedicated_user": actual_service_user == RUNTIME_SERVICE_USER,
        "sudo_available": bool(sudo_available),
        "can_elevate": bool(_is_linux_host() and _can_run_privileged_actions()),
        "password_saved": False,
    }

def _runtime_path_targets() -> tuple[list[str], list[str]]:
    dirs: set[str] = set()
    files: set[str] = set()

    def add_file(path: str | None) -> None:
        p = str(path or "").strip()
        if not p:
            return
        p = os.path.abspath(p)
        files.add(p)
        parent = os.path.dirname(p)
        if parent:
            dirs.add(parent)
            dirs.add(os.path.join(parent, "backups"))

    def add_dir(path: str | None) -> None:
        p = str(path or "").strip()
        if p:
            dirs.add(os.path.abspath(p))

    add_dir(APP_START_CWD)
    add_file(APP_CONFIG_PATH)
    if APP_CONFIG_PATH:
        add_file(str(APP_CONFIG_PATH) + CONFIG_ROLLBACK_SUFFIX)
    add_file(HISTORY_STORE_PATH)
    add_file(_model_map_target_path())
    add_file(_eula_set_path())
    try:
        add_file(str(AP_CFG.get("vendor_db_file") or ""))
    except Exception:
        pass
    add_dir(os.path.dirname(os.path.abspath(HOST_METRICS_PATH)))
    return sorted(dirs), sorted(files)

def _runtime_traverse_dirs(dirs: list[str]) -> list[str]:
    out: set[str] = set()
    for raw in dirs:
        try:
            path = os.path.abspath(str(raw or ""))
        except Exception:
            continue
        parent = os.path.dirname(path)
        while parent and parent != path:
            if parent == os.path.abspath(os.sep):
                break
            out.add(parent)
            path = parent
            parent = os.path.dirname(path)
    return sorted(out, key=lambda p: len(p))

def _run_repair_step(label: str, args: list[str], steps: list[dict], sudo_password: str | None = None, timeout: int = 30, optional: bool = False) -> bool:
    ok, out, rc = _run_privileged(args, timeout=timeout, sudo_password=sudo_password)
    steps.append({"label": label, "ok": bool(ok), "returncode": rc, "output": out})
    return bool(ok or optional)

def _run_as_runtime_user(args: list[str], sudo_password: str | None, timeout: int = 20) -> tuple[bool, str, int]:
    cmd = [str(x) for x in args]
    if not cmd:
        return False, "empty command", -1
    if _command_path("runuser"):
        return _run_privileged(["runuser", "-u", RUNTIME_SERVICE_USER, "--"] + cmd, timeout=timeout, sudo_password=sudo_password)
    sudo = _command_path("sudo")
    if sudo:
        return _run_privileged([sudo, "-u", RUNTIME_SERVICE_USER, "--"] + cmd, timeout=timeout, sudo_password=sudo_password)
    return False, "未检测到 runuser/sudo，无法以 rid 账号验收权限。", -1

def _verify_runtime_path_access(sudo_password: str | None, steps: list[dict]) -> bool:
    dirs, files = _runtime_path_targets()
    for d in dirs:
        if not d:
            continue
        ok, out, rc = _run_as_runtime_user(["test", "-d", d, "-a", "-r", d, "-a", "-w", d, "-a", "-x", d], sudo_password=sudo_password)
        steps.append({"label": f"rid 目录权限验收 {d}", "ok": bool(ok), "returncode": rc, "output": out})
        if not ok:
            return False
    for f in files:
        if not f or not os.path.exists(f):
            continue
        ok, out, rc = _run_as_runtime_user(["test", "-r", f, "-a", "-w", f], sudo_password=sudo_password)
        steps.append({"label": f"rid 文件权限验收 {f}", "ok": bool(ok), "returncode": rc, "output": out})
        if not ok:
            return False
    return True

def _grant_runtime_path_access(sudo_password: str | None, steps: list[dict]) -> bool:
    dirs, files = _runtime_path_targets()
    for d in _runtime_traverse_dirs(dirs):
        if not d or not os.path.isdir(d):
            continue
        acl_cmd = ["setfacl", "-m", f"u:{RUNTIME_SERVICE_USER}:x", d]
        if _command_path("setfacl"):
            if not _run_repair_step(f"上级目录进入权限 {d}", acl_cmd, steps, sudo_password=sudo_password, optional=False):
                return False
        else:
            if not _run_repair_step(f"上级目录进入权限 {d}", ["chmod", "o+x", d], steps, sudo_password=sudo_password, optional=False):
                return False
    for d in dirs:
        if not d:
            continue
        if not _run_repair_step(f"创建目录 {d}", ["mkdir", "-p", d], steps, sudo_password=sudo_password):
            return False
        if not _run_repair_step(f"目录授权 {d}", ["chgrp", RUNTIME_SERVICE_USER, d], steps, sudo_password=sudo_password, optional=False):
            return False
        if not _run_repair_step(f"目录写权限 {d}", ["chmod", "g+rwx,g+s", d], steps, sudo_password=sudo_password):
            return False
    for f in files:
        if not f or not os.path.exists(f):
            continue
        if not _run_repair_step(f"文件授权 {f}", ["chgrp", RUNTIME_SERVICE_USER, f], steps, sudo_password=sudo_password):
            return False
        if not _run_repair_step(f"文件写权限 {f}", ["chmod", "g+rw", f], steps, sudo_password=sudo_password):
            return False
    return True

def _write_systemd_unit_privileged(unit_text: str, sudo_password: str | None, steps: list[dict]) -> tuple[bool, str]:
    backup_path = ""
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, prefix="xrs-service-", suffix=".service") as f:
            tmp_path = f.name
            f.write(unit_text)
    except Exception as e:
        steps.append({"label": "生成临时服务文件", "ok": False, "returncode": -1, "output": str(e)})
        return False, backup_path
    try:
        if os.path.exists(SYSTEMD_SERVICE_PATH):
            backup_path = SYSTEMD_SERVICE_PATH + "." + time.strftime("%Y%m%d_%H%M%S") + ".bak"
            if not _run_repair_step("备份 systemd 服务文件", ["cp", "-a", SYSTEMD_SERVICE_PATH, backup_path], steps, sudo_password=sudo_password):
                return False, backup_path
        if not _run_repair_step("写入 systemd 服务文件", ["install", "-m", "0644", tmp_path, SYSTEMD_SERVICE_PATH], steps, sudo_password=sudo_password):
            return False, backup_path
        return True, backup_path
    finally:
        try:
            if tmp_path:
                os.remove(tmp_path)
        except Exception:
            pass

def _schedule_systemd_restart(sudo_password: str | None, steps: list[dict], delay_sec: int = 3) -> bool:
    delay = max(1, int(delay_sec or 3))
    systemctl = _command_path("systemctl") or "systemctl"
    systemd_run = _command_path("systemd-run")
    if systemd_run:
        unit_name = f"xrs-scanner-restart-{os.getpid()}-{int(time.time())}"
        args = [
            systemd_run,
            f"--unit={unit_name}",
            f"--on-active={delay}s",
            "--collect",
            systemctl,
            "restart",
            SYSTEMD_SERVICE_NAME,
        ]
        ok, out, rc = _run_privileged(args, timeout=20, sudo_password=sudo_password)
        steps.append({"label": f"安排 {delay} 秒后自动重启服务", "ok": bool(ok), "returncode": rc, "output": out})
        return bool(ok)

    shell = f"sleep {delay}; exec {shlex.quote(systemctl)} restart {shlex.quote(SYSTEMD_SERVICE_NAME)}"
    try:
        if _is_root_user():
            subprocess.Popen(
                ["sh", "-c", shell],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        else:
            sudo = _command_path("sudo")
            if not sudo:
                steps.append({"label": "安排自动重启服务", "ok": False, "returncode": -1, "output": "当前进程不是 root，且未检测到 sudo。"})
                return False
            password = "" if sudo_password is None else str(sudo_password)
            if password:
                proc = subprocess.Popen(
                    [sudo, "-S", "-p", "", "--", "sh", "-c", shell],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    start_new_session=True,
                    close_fds=True,
                )
                try:
                    if proc.stdin:
                        proc.stdin.write(password + "\n")
                        proc.stdin.close()
                finally:
                    password = ""
            else:
                subprocess.Popen(
                    [sudo, "-n", "--", "sh", "-c", shell],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
                )
        steps.append({"label": f"安排 {delay} 秒后自动重启服务", "ok": True, "returncode": 0, "output": "已安排后台重启。"})
        return True
    except Exception as e:
        steps.append({"label": "安排自动重启服务", "ok": False, "returncode": -1, "output": str(e)})
        return False

def repair_runtime_security(sudo_password: str | None = None) -> dict:
    supported, reason = _systemd_supported()
    steps: list[dict] = []
    if not supported:
        return {"ok": False, "error": reason, "status": _systemd_service_status_payload(), "steps": steps}
    if not _can_run_privileged_actions():
        return {"ok": False, "error": "创建专用运行账号需要 root 或 sudo 提权。", "status": _systemd_service_status_payload(), "steps": steps}
    if not _local_user_exists(RUNTIME_SERVICE_USER):
        shell_path = "/usr/sbin/nologin" if os.path.exists("/usr/sbin/nologin") else "/bin/false"
        useradd_cmd = [
            _command_path("useradd") or "useradd",
            "--system",
            "--create-home",
            "--home-dir",
            RUNTIME_SERVICE_HOME,
            "--shell",
            shell_path,
            "--user-group",
            RUNTIME_SERVICE_USER,
        ]
        if not _run_repair_step(f"创建 {RUNTIME_SERVICE_USER} 账号", useradd_cmd, steps, sudo_password=sudo_password, timeout=30):
            return {"ok": False, "error": f"创建 {RUNTIME_SERVICE_USER} 账号失败。", "status": _systemd_service_status_payload(), "steps": steps}
    else:
        steps.append({"label": f"{RUNTIME_SERVICE_USER} 账号已存在", "ok": True, "returncode": 0, "output": ""})
    if not _run_repair_step("准备专用运行目录", ["install", "-d", "-o", RUNTIME_SERVICE_USER, "-g", RUNTIME_SERVICE_USER, "-m", "0750", RUNTIME_SERVICE_HOME], steps, sudo_password=sudo_password):
        return {"ok": False, "error": "准备专用运行目录失败。", "status": _systemd_service_status_payload(), "steps": steps}
    if _local_group_exists("netdev"):
        _run_repair_step("加入 netdev 组", ["usermod", "-a", "-G", "netdev", RUNTIME_SERVICE_USER], steps, sudo_password=sudo_password, optional=True)
    if not _grant_runtime_path_access(sudo_password, steps):
        return {"ok": False, "error": "授予运行文件写权限失败。", "status": _systemd_service_status_payload(), "steps": steps}
    if not _verify_runtime_path_access(sudo_password, steps):
        return {"ok": False, "error": "rid 账号权限验收失败。请检查上方失败步骤后重试。", "status": _systemd_service_status_payload(), "steps": steps}
    rsp = register_systemd_service(sudo_password=sudo_password, require_dedicated_user=True, _steps=steps)
    payload = dict(rsp)
    payload["steps"] = steps
    if rsp.get("ok"):
        restart_delay = 3
        restart_scheduled = _schedule_systemd_restart(sudo_password, steps, delay_sec=restart_delay)
        payload["steps"] = steps
        payload["restart_scheduled"] = bool(restart_scheduled)
        payload["restart_delay_sec"] = restart_delay
        if restart_scheduled:
            payload["message"] = "已创建/确认 rid 专用账号，并更新 systemd 服务为 rid 账号运行。服务将在几秒后自动重启，页面可能短暂断开。"
        else:
            payload["message"] = "已创建/确认 rid 专用账号，并更新 systemd 服务为 rid 账号运行；但自动重启安排失败，请手动重启 xrs-scanner.service。"
    return payload

def _systemd_service_status_payload() -> dict:
    supported, reason = _systemd_supported()
    spec = _systemd_service_spec()
    registered = os.path.exists(SYSTEMD_SERVICE_PATH)
    enabled = "unknown"
    active = "unknown"
    unit_matches = False
    last_error = ""
    unit_text = ""
    if registered:
        unit_text, last_error = _read_systemd_unit_text()
        unit_matches = (unit_text.strip() == str(spec.get("unit_text") or "").strip())
    if supported and registered:
        ok_enabled, out_enabled, _rc_enabled = _systemctl(["is-enabled", SYSTEMD_SERVICE_NAME], timeout=8)
        enabled = _systemctl_value_or_fallback(
            out_enabled,
            ok_enabled,
            {"enabled", "disabled", "static", "indirect", "generated", "transient", "masked", "linked", "alias", "not-found"},
            _systemd_enabled_fallback(),
        )
        ok_active, out_active, _rc_active = _systemctl(["is-active", SYSTEMD_SERVICE_NAME], timeout=8)
        active = _systemctl_value_or_fallback(
            out_active,
            ok_active,
            {"active", "inactive", "failed", "activating", "deactivating", "reloading", "maintenance", "unknown"},
            _systemd_active_fallback(),
        )
    security = _runtime_security_payload(unit_text=unit_text)
    return {
        "ok": True,
        "supported": bool(supported),
        "reason": reason,
        "running_as_root": _is_root_user(),
        "current_user": security.get("current_user"),
        "current_uid": security.get("current_uid"),
        "registered": bool(registered),
        "enabled": enabled,
        "active": active,
        "unit_matches": bool(unit_matches),
        "last_error": last_error,
        "dedicated_user": RUNTIME_SERVICE_USER,
        "dedicated_user_exists": bool(security.get("dedicated_user_exists")),
        "actual_service_user": security.get("service_user"),
        "service_uses_dedicated_user": bool(security.get("service_uses_dedicated_user")),
        "sudo_available": bool(security.get("sudo_available")),
        "can_elevate": bool(security.get("can_elevate")),
        "security": security,
        "manual_hint": "需要 root 或临时 sudo 提权写入 /etc/systemd/system 并执行 systemctl daemon-reload、systemctl enable。",
        "iw": _iw_status_payload(refresh=True),
        **spec,
    }

def register_systemd_service(sudo_password: str | None = None, require_dedicated_user: bool = True, _steps: list[dict] | None = None) -> dict:
    supported, reason = _systemd_supported()
    steps = _steps if isinstance(_steps, list) else []
    if not supported:
        return {"ok": False, "error": reason, "status": _systemd_service_status_payload(), "steps": steps}
    if require_dedicated_user and not _local_user_exists(RUNTIME_SERVICE_USER):
        return {
            "ok": False,
            "error": f"专用运行账号 {RUNTIME_SERVICE_USER} 不存在，请先执行一键修复。",
            "status": _systemd_service_status_payload(),
            "steps": steps,
        }
    if not _can_run_privileged_actions():
        return {"ok": False, "error": "注册 systemd 服务需要 root 或临时 sudo 提权。", "status": _systemd_service_status_payload(), "steps": steps}
    spec = _systemd_service_spec()
    unit_text = str(spec.get("unit_text") or "")
    ok_write, backup_path = _write_systemd_unit_privileged(unit_text, sudo_password, steps)
    if not ok_write:
        return {"ok": False, "error": "写入服务文件失败。", "status": _systemd_service_status_payload(), "steps": steps}

    ok_reload, out_reload, rc_reload = _systemctl_privileged(["daemon-reload"], timeout=20, sudo_password=sudo_password)
    steps.append({"label": "systemctl daemon-reload", "ok": bool(ok_reload), "returncode": rc_reload, "output": out_reload})
    if not ok_reload:
        return {
            "ok": False,
            "error": "systemctl daemon-reload 失败",
            "returncode": rc_reload,
            "output": out_reload,
            "backup_path": backup_path,
            "status": _systemd_service_status_payload(),
            "steps": steps,
        }
    ok_enable, out_enable, rc_enable = _systemctl_privileged(["enable", SYSTEMD_SERVICE_NAME], timeout=20, sudo_password=sudo_password)
    steps.append({"label": "systemctl enable", "ok": bool(ok_enable), "returncode": rc_enable, "output": out_enable})
    status = _systemd_service_status_payload()
    if not ok_enable:
        return {
            "ok": False,
            "error": "systemctl enable 失败",
            "returncode": rc_enable,
            "output": out_enable,
            "backup_path": backup_path,
            "status": status,
            "steps": steps,
        }
    return {
        "ok": True,
        "message": f"systemd 服务已注册并设为开机自启；服务文件将以 {RUNTIME_SERVICE_USER} 账号运行，当前进程不会被自动重启。",
        "backup_path": backup_path,
        "output": out_enable,
        "status": status,
        "steps": steps,
    }
