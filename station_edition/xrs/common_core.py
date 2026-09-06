from __future__ import annotations
# pylint: disable=unused-import
# This file is the first legacy runtime chunk. Several imports below seed the
# shared exec() namespace for later chunks until they become normal modules.
import argparse
import base64
import difflib
import hashlib
import hmac
import io
import ipaddress
import json
import logging
import math
import os
import platform
import queue
import random
import re
import secrets
import shlex
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from collections import deque
from threading import Lock, Thread

try:
    import curses
except ImportError:
    curses = None

try:
    from scapy.config import conf
    from scapy.layers.dot11 import Dot11, Dot11Beacon, Dot11Elt, RadioTap
    from scapy.sendrecv import sniff
    conf.verb = 0
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False
    sys.exit("[FATAL] scapy not installed. Run: pip3 install scapy")

# -----------------------------------------------------------------------------
# 常量
# -----------------------------------------------------------------------------
ODID_OUI             = bytes([0xFA, 0x0B, 0xBC])
MSG_TYPE_BASIC_ID    = 0x0
MSG_TYPE_LOCATION    = 0x1
MSG_TYPE_SYSTEM      = 0x4
MSG_TYPE_PACK        = 0xF
ODID_MSG_SIZE        = 25
ODID_PROTOCOL_MAX    = 2
DJI_RID_VENDOR_TYPE  = 0x0D
DJI_RID_VENDOR_PREFIX = ODID_OUI + bytes([DJI_RID_VENDOR_TYPE])
RID_NEW_FW_BODY_MIN  = 83
RID_DJI_VENDOR_MIN   = 10
RID_DJI_GB46750_MIN  = 68
RID_NEW_FW_SN_LEN    = 20
RID_NEW_FW_UAS_LEN   = 8
RID_NEW_FW_GB_OFF    = 5
RID_NEW_FW_GB_MIN    = 78
RID_NEW_FW_ALL_IDENTIFIERS = b"\xff\xff\xfe"
RID_NEW_FW_EXT_MARKER = b"\xff\x20\x48\xff\xff\xfe"
RID_GB_FF2048_MARKER = RID_NEW_FW_EXT_MARKER
RID_DJI_GB46750_HEADER = b"\xf1\x19\x03"
RID_NEW_FW_SN_OFF    = 11
RID_NEW_FW_UAS_OFF   = 31
RID_NEW_FW_PILOT_LON_OFF = 42
RID_NEW_FW_PILOT_LAT_OFF = 46
RID_NEW_FW_PILOT_ALT_OFF = 50
RID_NEW_FW_DRONE_LON_OFF = 52
RID_NEW_FW_DRONE_LAT_OFF = 56
RID_NEW_FW_TRACK_OFF = 60
RID_NEW_FW_GROUND_SPEED_OFF = 62
RID_NEW_FW_REL_ALT_OFF = 64
RID_NEW_FW_VSPEED_OFF = 66
RID_NEW_FW_GEOID_ALT_OFF = 67
RID_NEW_FW_BARO_ALT_OFF = 69
RID_NEW_FW_COORD_SEARCH_MAX = 80
RID_NEW_FW_SIG_BYTES = 160

UA_ID_TYPE = {0:"None", 1:"Serial", 2:"CAA", 3:"UTM", 4:"Session"}

LOC_LAT_LON_MULT = 1e-7
LOC_ALT_OFFSET   = -1000.0
LOC_ALT_MULT     = 0.5
# OpenDroneID WiFi payload follows ODID_*_encoded packed layout (little-endian).
LOC_ENDIAN       = "<"

DEFAULT_PRINT_INTERVAL = 2.0
DEFAULT_MIN_GAP        = 1.0
DEFAULT_LOST_TIMEOUT   = 15.0
LOST_TIMEOUT           = DEFAULT_LOST_TIMEOUT
PURGE_TIMEOUT          = 300.0

CHANNELS_2G         = [1, 6, 11]
CHANNELS_5G         = [36, 40, 44, 48, 149, 153, 157, 161]
# Common 5GHz channels for WiFi fast-transfer scan.
CHANNELS_5G_COMMON  = [36, 40, 44, 48, 52, 56, 60, 64,
                       100, 104, 108, 112, 116, 120, 124, 128,
                       132, 136, 140, 149, 153, 157, 161, 165]
DWELL_2G_DEFAULT    = 250
DWELL_5G_DEFAULT    = 800
SETTLE_DEFAULT      = 30
MAC_BASIC_CACHE_MAX = 1000
ODID_MSG_TYPES_OK   = {0x0, 0x1, 0x2, 0x3, 0x4, 0x5, 0xF}
HEADING_MIN_MOVE_M  = 2.0
SSID_SN_RE          = re.compile(r"\bRID-([A-Za-z0-9]{4,64})\b")

LOG_BUF_SIZE = 4000   # Log ring buffer size
TUI_REFRESH  = 0.5    # Forced TUI refresh interval (seconds)
CONFIG_FILE_DEFAULT = "config.json"
HISTORY_STORE_DEFAULT = "rid_storage.db"
HISTORY_STORE_LEGACY_DEFAULT = "history-cache.json"
HISTORY_STORE_LEGACY_ALT_DEFAULT = "rid_history_cache.json"
HISTORY_RAW_PACKET_SNAPSHOT_LIMIT = 3
MODEL_MAP_FILE_DEFAULT = "rid_model.json"
SYSTEMD_SERVICE_NAME = "xrs-scanner.service"
SYSTEMD_SERVICE_PATH = "/etc/systemd/system/" + SYSTEMD_SERVICE_NAME
IW_PACKAGE_NAME = "iw"
RUNTIME_SERVICE_USER = "rid"
RUNTIME_SERVICE_HOME = "/var/lib/xrs"
RUNTIME_SERVICE_CAPABILITIES = ("CAP_NET_ADMIN", "CAP_NET_RAW", "CAP_NET_BIND_SERVICE")
HISTORY_SAVE_INTERVAL = 5.0
HTTP_JSON_MAX_BYTES = 1024 * 1024
API_NAME = "XRS API"
API_VERSION = "v1"
APP_RELEASE_VERSION = "1.0.0"
APP_HTTP_USER_AGENT = f"XRS/{APP_RELEASE_VERSION}"
APP_SERVER_HEADER = f"XRS/{APP_RELEASE_VERSION}"
BUILD_INFO_FILE = "rid_build_info.json"
HISTORY_STORAGE_SCHEMA_VERSION = 2
HISTORY_STORAGE_EXPORT_VERSION = 4
HISTORY_STORAGE_UPGRADE_TARGET = "v1.0.0"
EULA_SET_FILE = "EULA.set"
EULA_MARKDOWN_FILE = "EULA.md"
EULA_URL = "https://raw.githubusercontent.com/Copeq/XRS/refs/heads/main/EULA.md"
OUI_DB_DEFAULT = "oui.txt"
OUI_DB_URL = "https://standards-oui.ieee.org/oui/oui.txt"
GITHUB_PROXY_PREFIX = "https://gh-proxy.org/"
RID_MODELS_UPDATE_URL_DEFAULT = "https://raw.githubusercontent.com/Copeq/XRS/refs/heads/main/rid_model.json"
APP_UPDATE_COMMIT_URL_DEFAULT = "https://api.github.com/repos/Copeq/XRS/commits/main"
APP_UPDATE_RELEASE_URL_DEFAULT = "https://api.github.com/repos/Copeq/XRS/releases/latest"
APP_UPDATE_MIRROR_OPTIONS = [
    {"key": "github", "label": "GitHub 官方", "base": ""},
    {"key": "gh-proxy", "label": "gh-proxy.org", "base": GITHUB_PROXY_PREFIX},
    {"key": "custom", "label": "自定义镜像", "base": ""},
]
MODEL_UPDATE_CHECK_INTERVAL_SEC = 24 * 3600
HOST_METRICS_DIR_DEFAULT = os.path.join(tempfile.gettempdir(), "xrs_scanner")
HOST_METRICS_FILE_DEFAULT = "host_metrics.jsonl"
HOST_METRICS_SAMPLE_SEC = 60.0
HOST_METRICS_RETENTION_DAYS_DEFAULT = 7
AP_LIST_MAX_DEFAULT = 80
AP_STALE_TIMEOUT = 900.0
NOTIFY_REONLINE_COOLDOWN_DEFAULT = 300.0
NOTIFICATION_CENTER_MAX = 200
DJI_LOOKUP_URL_DEFAULT = "https://repair.dji.com/device/search?re=cn&lang=zh-CN"
SNIFF_POLL_TIMEOUT = 20.0
SNIFF_STALL_RECOVER_SEC = 60.0
SNIFF_RECOVER_COOLDOWN_SEC = 20.0
SNIFF_WORKER_HARD_GRACE_SEC = 8.0
SNIFF_WORKER_JOIN_GRACE_SEC = 2.0
SNIFF_RESTART_AFTER_FAILS = 5
WIFI_FAST_OUI_PREFIX = "0c:9a:e6"
TRACK_MAX_POINTS = 10000
TRACK_STORE_POINTS_MIN = 10
TRACK_STORE_POINTS_MAX = 200000
TRACK_MIN_INTERVAL_SEC = 0.8
TRACK_ANOMALY_MAX_METERS = 50_000.0
NO_IFACE_DEGRADE_HINT = "未检测到已绑定的无线网卡，已进入降级运行。请打开设置或 OOBE 完成网卡配置。"
CONFIG_ROLLBACK_SUFFIX = ".rollback"


def _github_proxy_candidate_urls(url: str) -> list[str]:
    raw = str(url or "").strip()
    if not raw:
        return []
    urls = [raw]
    if raw.startswith(GITHUB_PROXY_PREFIX):
        return urls
    try:
        parsed = urllib.parse.urlsplit(raw)
        host = str(parsed.netloc or "").strip().lower()
    except Exception:
        host = ""
    if host in ("github.com", "raw.githubusercontent.com", "api.github.com"):
        urls.append(GITHUB_PROXY_PREFIX + raw)
    return urls


def _http_open_with_fallback(
    url: str,
    *,
    headers: dict | None = None,
    timeout: float = 15.0,
    method: str = "GET",
    data=None,
):
    candidates = _github_proxy_candidate_urls(url)
    if not candidates:
        raise ValueError("url required")
    last_error = None
    for idx, candidate in enumerate(candidates):
        req = urllib.request.Request(candidate, data=data, headers=headers or {}, method=method)
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except Exception as e:
            last_error = e
            if idx + 1 < len(candidates):
                try:
                    _log(f"[WARN] request failed, retrying via mirror: {candidate} -> {e}")
                except Exception:
                    pass
    if last_error is not None:
        raise last_error
    raise RuntimeError("request failed")


def _http_read_with_fallback(
    url: str,
    *,
    headers: dict | None = None,
    timeout: float = 15.0,
    method: str = "GET",
    data=None,
    max_bytes: int | None = None,
) -> tuple[bytes, str]:
    with _http_open_with_fallback(url, headers=headers, timeout=timeout, method=method, data=data) as resp:
        if max_bytes is None:
            payload = resp.read()
        else:
            payload = resp.read(max(0, int(max_bytes)))
        final_url = ""
        try:
            final_url = str(resp.geturl() or "")
        except Exception:
            final_url = ""
    return payload, final_url or str(url or "")

# -----------------------------------------------------------------------------
# Global runtime state (initialized in `main()`)
# -----------------------------------------------------------------------------
state_table: dict[str, dict] = {}
# Web side history cache: keep all seen drones after live-state purge.
history_table: dict[str, dict] = {}
state_lock = Lock()
# A real radio simulation owns the configured scan interface while it transmits.
# Keep packet capture alive, but pause parsing until the simulation stops.
simulation_scan_pause_event = threading.Event()

log_buf:  deque[str] = deque(maxlen=LOG_BUF_SIZE)   # Normal logs (LOST/INFO/etc.)
scan_buf: deque[str] = deque(maxlen=LOG_BUF_SIZE)   # Full scan logs (with debug frame info)
ap_buf:   deque[str] = deque(maxlen=500)            # AP scan logs (for HTTP page)
op_buf:   deque[str] = deque(maxlen=LOG_BUF_SIZE)   # Web/admin/security operation audit log
scan_diff_buf: deque[str] = deque(maxlen=LOG_BUF_SIZE)  # Structured scan state diff log
sys_err_buf: deque[str] = deque(maxlen=LOG_BUF_SIZE)    # System/runtime error log
ap_seq:   int = 0
ap_table: dict[str, dict] = {}
ap_list_seq: int = 0
ap_lock = Lock()
log_lock = Lock()
security_rate_lock = Lock()
security_rate_state: dict[str, dict] = {}

HISTORY_STORE_PATH: str | None = None
HISTORY_LEGACY_SOURCE_PATHS: list[str] = []
history_persist_dirty: bool = False
history_persist_last_save_wall: float = 0.0
history_io_lock = Lock()
history_db_lock = Lock()
history_db_conn = None
history_db_path: str | None = None
history_storage_notice_lock = Lock()
history_storage_pending_notice: dict | None = None

APP_CONFIG: dict = {}
APP_CONFIG_PATH: str | None = None
APP_CONFIG_PATH_IS_DEFAULT: bool = True
APP_CONFIG_PATH_LOCKED: bool = False
APP_EDITION: str = os.environ.get("XRS_EDITION", "station").strip().lower() or "station"
OOBE_REQUIRED: bool = False
OOBE_REASON: str = ""
OOBE_LOCK = Lock()
APP_START_CWD: str = os.getcwd()
APP_START_WALL: float = time.time()
RAW_CONFIG_UNLOCK_TTL_SEC = 15 * 60
raw_config_unlock_lock = Lock()
raw_config_unlocks: dict[str, float] = {}
WEB_CFG: dict = {
    "dji_lookup_url": DJI_LOOKUP_URL_DEFAULT,
    "allow_restart": True,
    "last_restart_args": "",
    "scan_type_rid": "RID报送",
    "scan_type_phone": "手机快传",
    "sn_source_rid": "RID包",
    "sn_source_ssid": "SSID",
    "base_name": "基站",
    "base_lat": None,
    "base_lon": None,
    "base_zoom": 13,
    "heading_ref_deg": 0.0,
    "map_auto_center_idle_sec": 20,
    "map_tile_url": "",
    "map_tile_subdomains": "",
    "map_tile_attribution": "",
    "map_tile_max_native_zoom": 18,
    "alarm_zones": [],
    "access_list_enabled": False,
    "access_list_mode": "allow",
    "access_list": [],
    "alarm_zone": {
        "enabled": False,
        "lat1": None,
        "lon1": None,
        "lat2": None,
        "lon2": None,
        "name": "报警区域",
    },
}
AP_CFG: dict = {
    "list_max": AP_LIST_MAX_DEFAULT,
    "vendor_db_file": os.path.join(os.getcwd(), OUI_DB_DEFAULT),
    "vendor_auto_download": True,
}
AUTH_CFG: dict = {
    "enabled": False,
    "username_hash": "",
    "password_hash": "",
    "realm": "XRS",
    "session_ttl_min": 30,
    "login_methods": ["password", "passkey"],
    "sso_links": [],
    "passkeys": [],
}
AUTH_SESSION_COOKIE = "rid_auth"
AUTH_SESSION_TTL_SEC = 30 * 60
auth_session_lock = Lock()
auth_sso_lock = Lock()
auth_passkey_lock = Lock()
api_token_lock = Lock()
auth_sessions: dict[str, float] = {}
auth_session_secret = secrets.token_hex(16)
PASSKEY_CHALLENGE_TTL_SEC = 5 * 60
passkey_challenge_lock = Lock()
passkey_challenges: dict[str, dict] = {}
API_CFG: dict = {
    "enabled": False,
    "token": "",
    "token_hash": "",
    "tokens": [],
    "whitelist_enabled": False,
    "whitelist_mode": "allow",
    "whitelist": [],
}
PAGE_API_HEADER = "X-XRS-Page"
PAGE_API_HEADER_VALUE = "1"
UPDATE_PROBE_HEADER = "X-XRS-Update-Probe"
UPDATE_PROBE_HEADER_VALUE = "1"
APP_UPDATE_UPLOAD_NAME_HEADER = "X-XRS-Upload-Name"
APP_UPDATE_UPLOAD_TOKEN_HEADER = "X-XRS-Upload-Token"
APP_UPDATE_MAX_BYTES = 512 * 1024 * 1024
APP_UPDATE_UPLOAD_SESSION_TTL_SEC = 15 * 60
NOTIFY_CFG: dict = {
    "enabled": False,
    "only_online": True,
    "notify_reonline": True,
    "reonline_cooldown_sec": NOTIFY_REONLINE_COOLDOWN_DEFAULT,
    "skip_mac_only": True,
    "wecom_webhooks": [],
    "wecom_webhook_key": "",
    "send_timeout_sec": 8,
}
MODEL_UPDATE_CFG: dict = {
    "enabled": True,
    "url": RID_MODELS_UPDATE_URL_DEFAULT,
}
CONFIG_UPDATE_CFG: dict = {
    "enabled": False,
    "url": "",
}
APP_UPDATE_CFG: dict = {
    "enabled": True,
    "release_url": APP_UPDATE_RELEASE_URL_DEFAULT,
    "mirror": "github",
    "custom_mirror": "",
    "force_update": False,
}
APP_UPDATE_STATE: dict = {
    "running": False,
    "last_check_ts": 0.0,
    "last_install_ts": 0.0,
    "latest_tag": "",
    "latest_commit": "",
    "current_tag": "",
    "current_commit": "",
    "target_arch": "",
    "asset_name": "",
    "asset_url": "",
    "installing": False,
    "install_status": "",
    "install_supported": False,
    "support_reason": "",
    "update_available": False,
    "last_error": "",
    "download_running": False,
    "download_status": "",
    "download_message": "",
    "downloaded_bytes": 0,
    "download_total_bytes": 0,
    "download_percent": 0.0,
    "staged_ready": False,
    "staged_source": "",
    "staged_tag": "",
    "staged_asset_name": "",
    "staged_sha256": "",
    "staged_expected_sha256": "",
    "staged_verified": False,
    "staged_size": 0,
    "requires_sudo": False,
}
MODEL_UPDATE_STATE: dict = {
    "running": False,
    "last_check_ts": 0.0,
    "last_success_ts": 0.0,
    "last_error": "",
    "last_message": "",
    "last_count": 0,
}
model_update_lock = Lock()
model_map_file_lock = Lock()
model_update_worker_started = False
CONFIG_UPDATE_STATE: dict = {
    "running": False,
    "last_check_ts": 0.0,
    "last_success_ts": 0.0,
    "last_error": "",
    "last_message": "",
    "last_count": 0,
}
config_update_lock = Lock()
config_update_worker_started = False
app_update_lock = Lock()
app_update_upload_lock = Lock()
app_update_upload_sessions: dict[str, dict] = {}

METRICS_CFG: dict = {
    "enabled": False,
    "retention_days": HOST_METRICS_RETENTION_DAYS_DEFAULT,
    "temperature_source": "auto",
}
HOST_METRICS_PATH = os.path.join(HOST_METRICS_DIR_DEFAULT, HOST_METRICS_FILE_DEFAULT)
host_metrics_lock = Lock()
host_metrics_last_sample_wall: float = 0.0
iw_check_lock = Lock()
IW_CHECK_STATE: dict = {
    "checked": False,
    "available": False,
    "path": "",
    "install_attempted": False,
    "install_ok": False,
    "message": "",
    "manual_hint": "",
}

notify_queue: "queue.Queue[dict]" = queue.Queue(maxsize=256)
notify_worker_started = False
notify_worker_lock = Lock()
notification_lock = Lock()
notification_items: deque[dict] = deque(maxlen=NOTIFICATION_CENTER_MAX)
notification_seq: int = 0

current_channel: int = 0

_oui_line_re = re.compile(
    r"^\s*([0-9A-Fa-f]{2})-([0-9A-Fa-f]{2})-([0-9A-Fa-f]{2})\s+\(hex\)\s+(.+?)\s*$"
)
oui_db_lock = Lock()
oui_map: dict[str, str] = {}
oui_vendor_cache: dict[str, str] = {}
oui_loaded = False
oui_loading_started = False
oui_last_attempt_wall = 0.0

restart_lock = Lock()
restart_pending = False

hw_worker_lock = Lock()
hw_worker_started = False
hw_task_queue: "queue.Queue[dict]" = queue.Queue(maxsize=128)
HISTORY_REPARSE_QUEUE_MAX = 65536
history_reparse_queue: "queue.Queue[dict]" = queue.Queue(maxsize=HISTORY_REPARSE_QUEUE_MAX)
history_reparse_runtime_lock = Lock()
history_reparse_runtime_updated_sns: set[str] = set()
history_reparse_worker_started = False

sniff_health_lock = Lock()
sniff_last_pkt_mono: float = 0.0
sniff_last_pkt_wall: float = 0.0
sniff_last_recover_wall: float = 0.0
sniff_last_error: str = ""
sniff_last_error_wall: float = 0.0
sniff_iface_name: str = ""
packet_parse_diag_lock = Lock()
packet_parse_diag_state: dict[str, float | int] = {
    "samples": 0,
    "last_ms": 0.0,
    "avg_ms": 0.0,
    "max_ms": 0.0,
    "high_water": 0,
    "last_done_wall": 0.0,
}
HISTORY_REPARSE_BATCH_SIZE = 128
history_reparse_lock = Lock()
history_reparse_state: dict[str, object] = {
    "task_id": "",
    "kind": "",
    "title": "",
    "status": "idle",
    "running": False,
    "limit": 0,
    "total": 0,
    "completed": 0,
    "decoded": 0,
    "skipped": 0,
    "failed": 0,
    "migrated": 0,
    "saved": False,
    "aircraft_total": 0,
    "updated_aircraft": 0,
    "enqueued": 0,
    "producer_done": False,
    "batch_size": HISTORY_REPARSE_BATCH_SIZE,
    "batches_total": 0,
    "active_batch": 0,
    "active_batch_size": 0,
    "message": "",
    "last_error": "",
    "started_wall": 0.0,
    "updated_wall": 0.0,
    "finished_wall": 0.0,
    "formats": {},
    "errors": [],
}

# Runtime parameters (set in `main()`)
PRINT_INTERVAL: float = DEFAULT_PRINT_INTERVAL
MIN_GAP:        float = DEFAULT_MIN_GAP
CHANGE_ON_RSSI: bool  = False
CHANGE_ON_PL:   bool  = False
RSSI_DELTA:     int   = 3
MODEL_MAP:      dict[str, str] = {}
NO_TUI:         bool  = False
DEBUG_MODE:     bool  = False
SCAN_WIFI_FAST: bool  = False
WIFI_FAST_SUPPORTED: bool | None = None
WIFI_FAST_SUPPORT_MSG: str = ""

# -----------------------------------------------------------------------------
# CJK width helpers (without wcwidth dependency)
# -----------------------------------------------------------------------------
def _cw(c: str) -> int:
    """Return display width for one char (CJK=2, others=1)."""
    cp = ord(c)
    if ((0x1100 <= cp <= 0x115F) or (0x2E80 <= cp <= 0x303E) or
        (0x3040 <= cp <= 0x33FF) or (0x3400 <= cp <= 0x4DBF) or
        (0x4E00 <= cp <= 0xA4CF) or (0xAC00 <= cp <= 0xD7FF) or
        (0xF900 <= cp <= 0xFAFF) or (0xFE10 <= cp <= 0xFE1F) or
        (0xFE30 <= cp <= 0xFE6F) or (0xFF01 <= cp <= 0xFF60) or
        (0xFFE0 <= cp <= 0xFFE6)):
        return 2
    return 1

def _sw(s: str) -> int:
    """Return display width for a string."""
    return sum(_cw(c) for c in s)

def _pad(s: str, w: int) -> str:
    """Pad/truncate a string to display width `w` with CJK-safe behavior."""
    out, cur = "", 0
    for c in s:
        cw = _cw(c)
        if cur + cw > w:
            break
        out += c
        cur += cw
    return out + " " * (w - cur)

# -----------------------------------------------------------------------------
# 日志
# -----------------------------------------------------------------------------
def _system_error_append(scope: str, text: str) -> None:
    safe_scope = re.sub(r"[\r\n\t]+", " ", str(scope or "system")).strip()[:96] or "system"
    safe_text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not safe_text:
        return
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{safe_scope}] {safe_text}"
    with log_lock:
        sys_err_buf.append(line)

def _system_error_log(scope: str, detail: str, *, exc=None, include_trace: bool = False) -> None:
    parts = [str(detail or "").strip() or "system error"]
    exc_info = exc if exc is not None else sys.exc_info()
    if include_trace and exc_info and exc_info[0]:
        try:
            trace_text = "".join(traceback.format_exception(exc_info[0], exc_info[1], exc_info[2])).strip()
        except Exception:
            trace_text = ""
        if trace_text:
            parts.append(trace_text)
    _system_error_append(scope, "\n".join(x for x in parts if x))

class _SystemErrorLogHandler(logging.Handler):
    def emit(self, record) -> None:
        try:
            msg = self.format(record) or record.getMessage()
            _system_error_log(
                f"logging:{record.name}",
                f"{record.levelname}: {msg}",
                exc=record.exc_info if record.exc_info else None,
                include_trace=bool(record.exc_info),
            )
        except Exception:
            pass

def _install_system_error_hooks() -> None:
    if globals().get("_SYSTEM_ERROR_HOOKS_READY"):
        return
    globals()["_SYSTEM_ERROR_HOOKS_READY"] = True

    prev_excepthook = getattr(sys, "excepthook", None)
    def _codex_excepthook(exc_type, exc_value, exc_tb):
        _system_error_log(
            "uncaught",
            f"{getattr(exc_type, '__name__', 'Exception')}: {exc_value}",
            exc=(exc_type, exc_value, exc_tb),
            include_trace=True,
        )
        if callable(prev_excepthook):
            try:
                prev_excepthook(exc_type, exc_value, exc_tb)
            except Exception:
                pass
    sys.excepthook = _codex_excepthook

    if hasattr(threading, "excepthook"):
        prev_thread_hook = getattr(threading, "excepthook", None)
        def _codex_thread_excepthook(args):
            _system_error_log(
                f"thread:{getattr(getattr(args, 'thread', None), 'name', '-')}",
                f"{getattr(getattr(args, 'exc_type', None), '__name__', 'Exception')}: {getattr(args, 'exc_value', '')}",
                exc=(getattr(args, "exc_type", None), getattr(args, "exc_value", None), getattr(args, "exc_traceback", None)),
                include_trace=True,
            )
            if callable(prev_thread_hook):
                try:
                    prev_thread_hook(args)
                except Exception:
                    pass
        threading.excepthook = _codex_thread_excepthook

    root = logging.getLogger()
    for existing in list(root.handlers):
        if isinstance(existing, _SystemErrorLogHandler):
            return
    root.addHandler(_SystemErrorLogHandler(level=logging.ERROR))

def _log(msg: str) -> None:
    ts   = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    with log_lock:
        log_buf.append(line)
        scan_buf.append(line)   # Mirror normal logs into scan stream
    if any(tag in str(msg or "") for tag in ("[WARN]", "[ERROR]", "[FATAL]")):
        _system_error_append("runtime", str(msg or ""))
    if NO_TUI:
        print(line, flush=True)

def _scan(msg: str) -> None:
    """Write only to scan log buffer (without normal log/print)."""
    ts   = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    with log_lock:
        scan_buf.append(line)

def _scan_diff(msg: str) -> None:
    text = str(msg or "").strip()
    if not text:
        return
    with log_lock:
        scan_diff_buf.append(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}")

def _op_log(action: str, detail: str = "", *, actor: str = "-", ip: str = "-", ok: bool = True) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    status = "OK" if ok else "FAIL"
    safe_action = re.sub(r"[\r\n\t]+", " ", str(action or "-")).strip()[:80]
    safe_actor = re.sub(r"[\r\n\t]+", " ", str(actor or "-")).strip()[:80]
    safe_ip = re.sub(r"[\r\n\t]+", " ", str(ip or "-")).strip()[:80]
    safe_detail = re.sub(r"[\r\n]+", " ", str(detail or "")).strip()
    safe_detail = re.sub(r"(?i)(token|password|webhook|key|secret)=([^,\s\]}]+)", r"\1=***", safe_detail)
    safe_detail = safe_detail[:1200]
    line = f"[{ts}] [{status}] action={safe_action} actor={safe_actor} ip={safe_ip} {safe_detail}".rstrip()
    with log_lock:
        op_buf.append(line)
    if not ok:
        _system_error_append(f"operation:{safe_action}", f"actor={safe_actor} ip={safe_ip} {safe_detail or '(empty detail)'}")

_install_system_error_hooks()

def _client_ip_from_handler(handler) -> str:
    try:
        return str((handler.client_address or ("",))[0] or "")
    except Exception:
        return ""

def _set_oobe_required(reason: str, required: bool = True) -> None:
    global OOBE_REQUIRED, OOBE_REASON
    text = str(reason or "").strip()
    with OOBE_LOCK:
        OOBE_REQUIRED = bool(required)
        OOBE_REASON = text if required else ""
    if required and text:
        _op_log("oobe-required", text, ok=False)

def _oobe_state() -> dict:
    with OOBE_LOCK:
        return {"required": bool(OOBE_REQUIRED), "reason": str(OOBE_REASON or "")}

def _runtime_entrypoint_path() -> str:
    ctx = globals().get("RUNTIME_CONTEXT")
    entrypoint = getattr(ctx, "entrypoint", None)
    if entrypoint:
        return str(entrypoint)
    return str(__file__)

def _app_root_dir() -> str:
    cfg_path = globals().get("APP_CONFIG_PATH")
    if cfg_path:
        try:
            return os.path.abspath(os.path.dirname(str(cfg_path)) or os.getcwd())
        except Exception:
            pass
    return os.path.dirname(os.path.abspath(_runtime_entrypoint_path()))

def _app_file_path(name: str) -> str:
    return os.path.join(_app_root_dir(), str(name or ""))

def _eula_set_path() -> str:
    return _app_file_path(EULA_SET_FILE)

def _eula_accepted() -> bool:
    try:
        with open(_eula_set_path(), "r", encoding="utf-8") as f:
            return f.read().strip() == "1"
    except Exception:
        return False

def _write_eula_acceptance() -> tuple[bool, str]:
    try:
        path = _eula_set_path()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("1\n")
        _op_log("eula-accept", f"path={path}", ok=True)
        return True, path
    except Exception as e:
        _op_log("eula-accept", str(e), ok=False)
        return False, str(e)

def _revoke_eula_acceptance() -> tuple[bool, str]:
    try:
        path = _eula_set_path()
        if os.path.exists(path):
            os.remove(path)
        _op_log("eula-revoke", f"path={path}", ok=True)
        return True, path
    except Exception as e:
        _op_log("eula-revoke", str(e), ok=False)
        return False, str(e)

def _eula_status_payload() -> dict:
    return {
        "ok": True,
        "accepted": _eula_accepted(),
        "set_path": _eula_set_path(),
        "source_url": EULA_URL,
    }

def _eula_redirect_required(req_path: str | None) -> bool:
    path = str(req_path or "/")
    if _eula_accepted():
        return False
    allowed = {
        "/eula",
        "/eula.html",
        "/api/eula/status",
        "/api/eula/accept",
        "/api/eula/revoke",
        "/favicon.ico",
    }
    return path not in allowed

def _html_escape(text: str, *, quote: bool = True) -> str:
    out = str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if quote:
        out = out.replace('"', "&quot;").replace("'", "&#39;")
    return out

def _markdown_inline_html(text: str) -> str:
    escaped = _html_escape(text)

    def _link_repl(match) -> str:
        label = _html_escape(match.group(1))
        url = str(match.group(2) or "").strip()
        if not (url.startswith("https://") or url.startswith("http://")):
            return label
        return '<a href="' + _html_escape(url) + '" target="_blank" rel="noopener noreferrer">' + label + "</a>"

    escaped = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", _link_repl, escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped

def _markdown_to_html(md: str) -> str:
    lines = str(md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    paragraph: list[str] = []
    in_list = False
    in_code = False
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append("<p>" + _markdown_inline_html(" ".join(paragraph).strip()) + "</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for line in lines:
        raw = line.rstrip("\n")
        stripped = raw.strip()
        if stripped.startswith("```"):
            if in_code:
                out.append('<pre class="eula-code"><code>' + _html_escape("\n".join(code_lines), quote=False) + "</code></pre>")
                code_lines = []
                in_code = False
            else:
                flush_paragraph()
                close_list()
                in_code = True
            continue
        if in_code:
            code_lines.append(raw)
            continue
        if not stripped:
            flush_paragraph()
            close_list()
            continue
        m = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if m:
            flush_paragraph()
            close_list()
            level = min(4, len(m.group(1)))
            out.append(f"<h{level}>{_markdown_inline_html(m.group(2))}</h{level}>")
            continue
        m = re.match(r"^[-*]\s+(.+)$", stripped)
        if m:
            flush_paragraph()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + _markdown_inline_html(m.group(1)) + "</li>")
            continue
        paragraph.append(stripped)
    if in_code:
        out.append('<pre class="eula-code"><code>' + _html_escape("\n".join(code_lines), quote=False) + "</code></pre>")
    flush_paragraph()
    close_list()
    return "\n".join(out)

def _load_eula_markdown() -> str:
    md_path = _app_file_path(EULA_MARKDOWN_FILE)
    if os.path.exists(md_path):
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                text = f.read().strip()
            if text:
                return text
        except Exception as e:
            return f"# 最终用户许可协议\n\n本地 EULA.md 读取失败：{e}\n\n请查看：[EULA.md]({EULA_URL})。"
    return "# 最终用户许可协议\n\n当前未能读取许可协议正文，请稍后刷新或查看：[EULA.md](" + EULA_URL + ")。"

def _history_mark_dirty() -> None:
    global history_persist_dirty
    history_persist_dirty = True

# Track-store helpers moved to track_store_core.py (exec'd by runtime.py in the same namespace).


def _packet_parse_diag_note_queue(depth: int | None = None) -> None:
    if depth is None:
        return
    try:
        depth_i = max(0, int(depth))
    except Exception:
        return
    with packet_parse_diag_lock:
        packet_parse_diag_state["high_water"] = max(int(packet_parse_diag_state.get("high_water") or 0), depth_i)


def _packet_parse_diag_note_parse(duration_ms: float | None, queue_depth: int | None = None) -> None:
    if queue_depth is not None:
        _packet_parse_diag_note_queue(queue_depth)
    if duration_ms is None:
        return
    try:
        dur = max(0.0, float(duration_ms))
    except Exception:
        return
    now_wall = time.time()
    with packet_parse_diag_lock:
        samples = int(packet_parse_diag_state.get("samples") or 0) + 1
        prev_avg = float(packet_parse_diag_state.get("avg_ms") or 0.0)
        packet_parse_diag_state["samples"] = samples
        packet_parse_diag_state["last_ms"] = dur
        packet_parse_diag_state["avg_ms"] = dur if samples <= 1 else (((prev_avg * (samples - 1)) + dur) / samples)
        packet_parse_diag_state["max_ms"] = max(float(packet_parse_diag_state.get("max_ms") or 0.0), dur)
        packet_parse_diag_state["last_done_wall"] = now_wall


def _packet_parse_diag_snapshot() -> dict:
    q = globals().get("packet_parse_queue")
    rq = globals().get("history_reparse_queue")
    qsize = 0
    qmax = int(globals().get("PACKET_PARSE_QUEUE_MAX") or 0)
    reparse_qsize = 0
    reparse_qmax = int(globals().get("HISTORY_REPARSE_QUEUE_MAX") or 0)
    if q is not None:
        try:
            qsize = max(0, int(q.qsize()))
        except Exception:
            qsize = 0
        if not qmax:
            try:
                qmax = max(0, int(q.maxsize))
            except Exception:
                qmax = 0
    if rq is not None:
        try:
            reparse_qsize = max(0, int(rq.qsize()))
        except Exception:
            reparse_qsize = 0
        if not reparse_qmax:
            try:
                reparse_qmax = max(0, int(rq.maxsize))
            except Exception:
                reparse_qmax = 0
    workers = max(0, int(globals().get("PACKET_PARSE_WORKERS") or 0))
    drops = max(0, int(globals().get("packet_parse_drop_count") or 0))
    active_workers = 0
    active_lock = globals().get("packet_parse_active_lock")
    if active_lock is not None:
        try:
            with active_lock:
                active_workers = max(0, int(globals().get("packet_parse_active_count") or 0))
        except Exception:
            active_workers = max(0, int(globals().get("packet_parse_active_count") or 0))
    else:
        active_workers = max(0, int(globals().get("packet_parse_active_count") or 0))
    active_workers = min(workers, active_workers) if workers else active_workers
    idle_workers = max(0, workers - active_workers)
    with packet_parse_diag_lock:
        state = dict(packet_parse_diag_state)
        high_water = max(int(state.get("high_water") or 0), qsize)
        packet_parse_diag_state["high_water"] = high_water
    usage_pct = None
    if qmax > 0:
        try:
            usage_pct = round(max(0.0, min(100.0, (float(qsize) / float(qmax)) * 100.0)), 1)
        except Exception:
            usage_pct = None
    return {
        "queue_size": qsize,
        "queue_max": qmax,
        "queue_usage_pct": usage_pct,
        "queue_high_water": high_water,
        "live_queue_size": qsize,
        "live_queue_max": qmax,
        "reparse_queue_size": reparse_qsize,
        "reparse_queue_max": reparse_qmax,
        "combined_queue_size": qsize + reparse_qsize,
        "workers": workers,
        "worker_total": workers,
        "worker_busy": active_workers,
        "worker_idle": idle_workers,
        "dropped": drops,
        "samples": int(state.get("samples") or 0),
        "last_parse_ms": round(float(state.get("last_ms") or 0.0), 3) if state.get("samples") else None,
        "avg_parse_ms": round(float(state.get("avg_ms") or 0.0), 3) if state.get("samples") else None,
        "max_parse_ms": round(float(state.get("max_ms") or 0.0), 3) if state.get("samples") else None,
        "last_done_wall": float(state.get("last_done_wall") or 0.0),
    }

