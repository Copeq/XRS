from station_edition.xrs.platform_compat import (
    local_group_exists as _platform_local_group_exists,
    local_user_exists as _platform_local_user_exists,
    username_for_uid as _platform_username_for_uid,
)


def _fmt(v, fmt=".6f", unit="", na="N/A") -> str:
    return f"{v:{fmt}}{unit}" if v is not None else na

# -----------------------------------------------------------------------------
# 地理
# -----------------------------------------------------------------------------
def _haversine(lat1, lon1, lat2, lon2) -> float:
    R  = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a  = (math.sin(math.radians(lat2-lat1)/2)**2
          + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lon2-lon1)/2)**2)
    return 2*R*math.asin(min(1.0, math.sqrt(a)))

def _bearing(lat1, lon1, lat2, lon2) -> float | None:
    try:
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dl     = math.radians(lon2-lon1)
        return (math.degrees(math.atan2(
            math.sin(dl)*math.cos(p2),
            math.cos(p1)*math.sin(p2)-math.sin(p1)*math.cos(p2)*math.cos(dl)
        ))+360)%360
    except Exception:
        return None

def _bearing8(deg: float) -> str:
    return ["N","NE","E","SE","S","SW","W","NW"][int((deg+22.5)//45)%8]

# -----------------------------------------------------------------------------
# 系统命令 / 接口
# -----------------------------------------------------------------------------
def run_cmd(cmd: str, timeout: int = 5) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip()
    except Exception:
        return ""

def _is_linux_host() -> bool:
    return platform.system().lower() == "linux"

def _is_root_user() -> bool:
    try:
        return bool(hasattr(os, "geteuid") and os.geteuid() == 0)
    except Exception:
        return False

def _command_path(name: str) -> str:
    try:
        return str(shutil.which(str(name or "").strip()) or "")
    except Exception:
        return ""

def _current_uid() -> int | None:
    try:
        if hasattr(os, "geteuid"):
            return int(os.geteuid())
    except Exception:
        pass
    return None

def _capability_bit(name: str) -> int | None:
    caps = {
        "CAP_NET_ADMIN": 12,
        "CAP_NET_RAW": 13,
        "CAP_NET_BIND_SERVICE": 10,
    }
    return caps.get(str(name or "").strip().upper())

def _process_has_capabilities(names: tuple[str, ...] | list[str]) -> bool:
    if not _is_linux_host():
        return False
    try:
        wanted = [_capability_bit(str(x)) for x in names]
        wanted = [int(x) for x in wanted if x is not None]
        if not wanted:
            return False
        with open("/proc/self/status", "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("CapEff:"):
                    value = int(line.split(":", 1)[1].strip(), 16)
                    return all((value & (1 << bit)) for bit in wanted)
    except Exception:
        pass
    return False

def _username_for_uid(uid: int | None) -> str:
    try:
        if uid is not None and _is_linux_host():
            return _platform_username_for_uid(uid)
    except (OSError, TypeError, ValueError):
        pass
    try:
        return str(os.environ.get("USER") or os.environ.get("USERNAME") or "")
    except Exception:
        return ""

def _local_user_exists(name: str) -> bool:
    user = str(name or "").strip()
    if not user or not _is_linux_host():
        return False
    try:
        exists = _platform_local_user_exists(user)
    except (OSError, TypeError, ValueError):
        exists = None
    if exists is not None:
        return bool(exists)
    ok, _out, _rc = _run_program(["id", "-u", user], timeout=4)
    return bool(ok)

def _local_group_exists(name: str) -> bool:
    group = str(name or "").strip()
    if not group or not _is_linux_host():
        return False
    try:
        exists = _platform_local_group_exists(group)
    except (OSError, TypeError, ValueError):
        exists = None
    if exists is not None:
        return bool(exists)
    ok, _out, _rc = _run_program(["getent", "group", group], timeout=4)
    return bool(ok)

def _sudo_available() -> bool:
    return bool(_is_linux_host() and _command_path("sudo"))

def _current_user_may_sudo() -> bool:
    if not _sudo_available():
        return False
    if _is_root_user():
        return True
    user = _username_for_uid(_current_uid())
    if user == RUNTIME_SERVICE_USER:
        return False
    sudo = _command_path("sudo")
    ok, out, _rc = _run_program([sudo, "-n", "true"], timeout=5)
    if ok:
        return True
    text = str(out or "").lower()
    ok_groups, groups_out, _rc_groups = _run_program(["id", "-nG"], timeout=4)
    groups = set(str(groups_out or "").split()) if ok_groups else set()
    if groups.intersection({"sudo", "wheel", "admin"}) and (
        "password" in text or "a password is required" in text or "a terminal is required" in text
    ):
        return True
    return False

def _can_run_privileged_actions() -> bool:
    return bool(_is_root_user() or _current_user_may_sudo())

def _sudo_password_from_body(body: dict | None) -> str:
    if not isinstance(body, dict):
        return ""
    try:
        return str(body.get("sudo_password") or body.get("password") or "")
    except Exception:
        return ""

def _truncate_text(text: str, limit: int = 3600) -> str:
    raw = str(text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[:limit] + "\n...输出已截断..."

def _run_program(args: list[str], timeout: int = 30, env: dict | None = None, input_text: str | None = None) -> tuple[bool, str, int]:
    try:
        r = subprocess.run(
            [str(x) for x in args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            input=input_text,
        )
        out = ((r.stdout or "") + ("\n" if r.stdout and r.stderr else "") + (r.stderr or "")).strip()
        return r.returncode == 0, _truncate_text(out), int(r.returncode)
    except Exception as e:
        return False, str(e), -1

def _run_privileged(args: list[str], timeout: int = 30, env: dict | None = None, sudo_password: str | None = None) -> tuple[bool, str, int]:
    cmd = [str(x) for x in args]
    if not cmd:
        return False, "empty command", -1
    if _is_root_user():
        return _run_program(cmd, timeout=timeout, env=env)
    sudo = _command_path("sudo")
    if not sudo:
        return False, "当前进程不是 root，且未检测到 sudo。", -1
    password = "" if sudo_password is None else str(sudo_password)
    if password:
        return _run_program([sudo, "-S", "-p", "", "--"] + cmd, timeout=timeout, env=env, input_text=password + "\n")
    return _run_program([sudo, "-n", "--"] + cmd, timeout=timeout, env=env)

def _systemctl(args: list[str], timeout: int = 20, sudo_password: str | None = None, privileged: bool = False) -> tuple[bool, str, int]:
    cmd = [_command_path("systemctl") or "systemctl"] + [str(x) for x in args]
    if privileged:
        return _run_privileged(cmd, timeout=timeout, sudo_password=sudo_password)
    return _run_program(cmd, timeout=timeout)

def _systemctl_privileged(args: list[str], timeout: int = 20, sudo_password: str | None = None) -> tuple[bool, str, int]:
    return _systemctl(args, timeout=timeout, sudo_password=sudo_password, privileged=True)

def _systemctl_value_or_fallback(out: str, ok: bool, known: set[str], fallback: str) -> str:
    line = (str(out or "").splitlines() or [""])[0].strip()
    if line in known:
        return line
    if ok and line:
        return line
    return fallback

