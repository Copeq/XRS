PACKET_PARSE_QUEUE_MAX = 4096
PACKET_PARSE_WORKERS = 12
packet_parse_queue = queue.Queue(maxsize=PACKET_PARSE_QUEUE_MAX)
packet_parse_drop_count = 0
packet_parse_worker_started = False
packet_parse_active_lock = Lock()
packet_parse_active_count = 0
RID_PARSE_FORMATS = {"GB46750_2025", "DJI_OLD_ODID"}
RID_PARSE_SN_RE = re.compile(r"^[A-Za-z0-9]{4,64}$")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenDroneID RID WLAN listener")
    parser.add_argument("--config", default=os.path.join(os.getcwd(), CONFIG_FILE_DEFAULT),
                        help="config file path (default: config.json)")
    parser.add_argument("--iface",        default=None)
    parser.add_argument("--channel",      default=None, type=int)
    parser.add_argument("--hop",          action="store_true")
    parser.add_argument("--hop-5g",       action="store_true")
    parser.add_argument("--scan-wifi-fast", action="store_true")
    parser.add_argument("--dwell-2g",     default=DWELL_2G_DEFAULT, type=int)
    parser.add_argument("--dwell-5g",     default=DWELL_5G_DEFAULT, type=int)
    parser.add_argument("--settle",       default=SETTLE_DEFAULT,   type=int)
    parser.add_argument("--dwell-on-hit", default=2500, type=int)
    parser.add_argument("--hit-cap",      default=6000, type=int)
    parser.add_argument("--time",         default=DEFAULT_PRINT_INTERVAL, type=float,
                        help="heartbeat interval seconds (default 2.0)")
    parser.add_argument("--min-gap",      default=DEFAULT_MIN_GAP, type=float,
                        help="minimum output gap for same SN (default 1.0)")
    parser.add_argument("--lost-timeout", default=DEFAULT_LOST_TIMEOUT, type=float,
                        help="aircraft offline threshold seconds (default 15)")
    parser.add_argument("--rssi-delta",   default=3, type=int)
    parser.add_argument("--change-on-rssi",    action="store_true")
    parser.add_argument("--change-on-payload", action="store_true")
    parser.add_argument("--model-map", default=os.path.join(os.getcwd(), MODEL_MAP_FILE_DEFAULT))
    parser.add_argument("--history-file", default=os.path.join(os.getcwd(), HISTORY_STORE_LEGACY_DEFAULT),
                        help="legacy history json path used only for migration into rid_storage.db")
    parser.add_argument("--no-tui",   action="store_true", default=True, help="禁用 TUI，纯文本输出")
    parser.add_argument("--tui",      action="store_false", dest="no_tui", help="启用 TUI")
    parser.add_argument("--debug",    action="store_true", help="write all raw frames into scan log")
    parser.add_argument("--notify-test", action="store_true", help="send one WeCom test notification then exit")
    parser.add_argument("--update-helper-plan", default="", help=argparse.SUPPRESS)
    return parser

_BASIC_CFG_ARG_DESTS = {
    "iface", "channel", "hop", "hop_5g", "scan_wifi_fast",
    "dwell_2g", "dwell_5g", "settle", "dwell_on_hit", "hit_cap",
    "time", "min_gap", "rssi_delta",
    "lost_timeout",
    "change_on_rssi", "change_on_payload",
    "model_map", "history_file",
    "no_tui", "debug",
}

def _parse_restart_args_text(args_text: str | None) -> tuple[list[str], str]:
    raw = str(args_text or "").strip()
    if not raw:
        return list(sys.argv[1:]), ""
    try:
        tokens = shlex.split(raw, posix=True)
    except ValueError as e:
        raise ValueError(f"参数解析失败: {e}")
    for t in tokens:
        opt = t.split("=", 1)[0]
        if opt in ("--notify-test", "--config"):
            raise ValueError(f"not allowed from web page: {opt}")
    return tokens, raw

def _merge_token_option(tokens: list[str], opt: str, value: str | None) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(tokens):
        t = str(tokens[i])
        if t == opt:
            i += 1
            if i < len(tokens):
                i += 1
            continue
        if t.startswith(opt + "="):
            i += 1
            continue
        out.append(t)
        i += 1
    if value is not None and str(value).strip():
        out.extend([opt, str(value).strip()])
    return out

def _merge_token_flag(tokens: list[str], flag: str, enabled: bool) -> list[str]:
    out = [str(t) for t in tokens if str(t) != flag]
    if enabled:
        out.append(flag)
    return out

def _save_basic_config_from_tokens(tokens: list[str], raw_text: str = "", overrides: dict | None = None) -> tuple[bool, str]:
    global APP_CONFIG
    if not APP_CONFIG_PATH:
        return False, "config file path is empty"
    parser = build_arg_parser()
    try:
        ns = parser.parse_args(tokens)
    except SystemExit:
        return False, "invalid args"
    explicit = _parser_explicit_dests(parser, tokens)
    cfg = load_app_config(APP_CONFIG_PATH)
    basic = cfg.setdefault("basic", {})
    if not isinstance(basic, dict):
        basic = {}
        cfg["basic"] = basic
    for dest in _BASIC_CFG_ARG_DESTS:
        if dest in explicit:
            basic[dest] = getattr(ns, dest)
    if isinstance(overrides, dict):
        if "iface" in overrides:
            ov_iface = overrides.get("iface")
            basic["iface"] = (None if ov_iface in (None, "") else str(ov_iface).strip())
        if "scan_wifi_fast" in overrides:
            basic["scan_wifi_fast"] = _to_bool(overrides.get("scan_wifi_fast"), False)
    web = cfg.setdefault("web", {})
    if not isinstance(web, dict):
        web = {}
        cfg["web"] = web
    web["last_restart_args"] = raw_text if raw_text else " ".join(tokens)
    b_ok, backup_path = create_config_backup(APP_CONFIG_PATH, tag="restart")
    if not b_ok:
        return False, f"backup failed: {backup_path}"
    ok, msg = save_app_config(APP_CONFIG_PATH, cfg)
    if ok:
        APP_CONFIG = cfg
        init_web_from_config(APP_CONFIG)
        init_ap_from_config(APP_CONFIG)
        init_notify_from_config(APP_CONFIG)
        return True, msg
    return False, msg

def _schedule_self_restart(tokens: list[str]) -> tuple[bool, str]:
    global restart_pending
    if not bool(WEB_CFG.get("allow_restart", True)):
        return False, "restart disabled"
    py = sys.executable or "python3"
    script = os.path.abspath(_runtime_entrypoint_path())
    if not os.path.exists(script):
        return False, f"script not found: {script}"
    exec_target = py
    exec_argv = [py] if getattr(sys, "frozen", False) else [py, script]
    with restart_lock:
        if restart_pending:
            return False, "已有重启任务"
        restart_pending = True

    def _do_restart(argv_tokens: list[str]) -> None:
        global restart_pending
        try:
            time.sleep(0.4)
            try:
                save_history_store(force=True)
            except Exception:
                pass
            try:
                os.chdir(APP_START_CWD)
            except Exception:
                pass
            argv_tokens = list(argv_tokens)
            has_cfg_arg = any(str(t).split("=", 1)[0] == "--config" for t in argv_tokens)
            if APP_CONFIG_PATH and (not APP_CONFIG_PATH_IS_DEFAULT) and not has_cfg_arg:
                argv_tokens.extend(["--config", APP_CONFIG_PATH])
            argv = exec_argv + argv_tokens
            _log("[INFO] 正在重启程序...")
            os.execv(exec_target, argv)
        except Exception as e:
            _log(f"[WARN] 程序重启失败: {e}")
            with restart_lock:
                restart_pending = False

    Thread(target=_do_restart, args=(list(tokens),), daemon=True).start()
    return True, "restarting"

def main() -> None:
    global PRINT_INTERVAL, MIN_GAP, LOST_TIMEOUT, CHANGE_ON_RSSI, CHANGE_ON_PL
    global RSSI_DELTA, NO_TUI, DEBUG_MODE, current_channel, HISTORY_STORE_PATH, APP_CONFIG
    global APP_CONFIG_PATH, APP_CONFIG_PATH_IS_DEFAULT, APP_CONFIG_PATH_LOCKED, APP_START_CWD
    global sniff_iface_name
    global SCAN_WIFI_FAST, WIFI_FAST_SUPPORTED, WIFI_FAST_SUPPORT_MSG

    try:
        if hasattr(sys.stdout,"reconfigure"):
            sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="OpenDroneID RID WLAN listener")
    parser.add_argument("--config", default=os.path.join(os.getcwd(), CONFIG_FILE_DEFAULT),
                        help="config file path (default: config.json)")
    parser.add_argument("--iface",        default=None)
    parser.add_argument("--channel",      default=None, type=int)
    parser.add_argument("--hop",          action="store_true")
    parser.add_argument("--hop-5g",       action="store_true")
    parser.add_argument("--scan-wifi-fast", action="store_true")
    parser.add_argument("--dwell-2g",     default=DWELL_2G_DEFAULT, type=int)
    parser.add_argument("--dwell-5g",     default=DWELL_5G_DEFAULT, type=int)
    parser.add_argument("--settle",       default=SETTLE_DEFAULT,   type=int)
    parser.add_argument("--dwell-on-hit", default=2500, type=int)
    parser.add_argument("--hit-cap",      default=6000, type=int)
    parser.add_argument("--time",         default=DEFAULT_PRINT_INTERVAL, type=float,
                        help="heartbeat interval seconds (default 2.0)")
    parser.add_argument("--min-gap",      default=DEFAULT_MIN_GAP, type=float,
                        help="minimum output gap for same SN (default 1.0)")
    parser.add_argument("--lost-timeout", default=DEFAULT_LOST_TIMEOUT, type=float,
                        help="aircraft offline threshold seconds (default 15)")
    parser.add_argument("--rssi-delta",   default=3, type=int)
    parser.add_argument("--change-on-rssi",    action="store_true")
    parser.add_argument("--change-on-payload", action="store_true")
    parser.add_argument("--model-map", default=os.path.join(os.getcwd(), MODEL_MAP_FILE_DEFAULT))
    parser.add_argument("--history-file", default=os.path.join(os.getcwd(), HISTORY_STORE_LEGACY_DEFAULT),
                        help="legacy history json path used only for migration into rid_storage.db")
    parser.add_argument("--no-tui",   action="store_true", default=True, help="禁用 TUI，纯文本输出")
    parser.add_argument("--tui",      action="store_false", dest="no_tui", help="启用 TUI")
    parser.add_argument("--debug",    action="store_true", help="write all raw frames into scan log")
    parser.add_argument("--notify-test", action="store_true", help="send one WeCom test notification then exit")
    parser.add_argument("--update-helper-plan", default="", help=argparse.SUPPRESS)
    APP_START_CWD = os.getcwd()
    args = parser.parse_args()

    if str(getattr(args, "update_helper_plan", "") or "").strip():
        raise SystemExit(_run_app_update_helper(str(args.update_helper_plan)))

    cfg_path = os.path.abspath(str(args.config)) if args.config else None
    APP_CONFIG_PATH = cfg_path
    APP_CONFIG_PATH_IS_DEFAULT = (cfg_path == os.path.abspath(os.path.join(os.getcwd(), CONFIG_FILE_DEFAULT))) if cfg_path else True
    APP_CONFIG_PATH_LOCKED = any(str(t).split("=", 1)[0] == "--config" for t in sys.argv[1:])
    legacy_hist_path = os.path.abspath(str(args.history_file)) if args.history_file else None
    model_path = os.path.abspath(str(args.model_map)) if args.model_map else None
    hist_path = _history_store_default_path(cfg_path)
    _ensure_runtime_json_files(cfg_path, hist_path, config_locked=APP_CONFIG_PATH_LOCKED)
    APP_CONFIG = load_app_config(cfg_path)
    if not _eula_accepted():
        _log(f"[INFO] EULA pending: open /eula to accept ({_eula_set_path()})")
    apply_config_to_args(parser, args, APP_CONFIG)
    legacy_hist_path = os.path.abspath(str(args.history_file)) if args.history_file else legacy_hist_path
    model_path = os.path.abspath(str(args.model_map)) if args.model_map else None
    _ensure_runtime_json_files(None, hist_path, config_locked=True)
    _history_set_legacy_source_paths([legacy_hist_path])

    PRINT_INTERVAL  = max(0.2, float(args.time))
    MIN_GAP         = max(0.0, float(args.min_gap))
    LOST_TIMEOUT    = max(3.0, min(3600.0, float(args.lost_timeout)))
    CHANGE_ON_RSSI  = bool(args.change_on_rssi)
    CHANGE_ON_PL    = bool(args.change_on_payload)
    RSSI_DELTA      = max(1, int(args.rssi_delta))
    NO_TUI          = bool(args.no_tui)
    DEBUG_MODE      = bool(args.debug)
    SCAN_WIFI_FAST  = bool(args.scan_wifi_fast)
    HISTORY_STORE_PATH = hist_path

    # Redirect Python logging to `scan_buf` instead of `stderr` (avoids TUI swallow).
    class BufHandler(logging.Handler):
        def emit(self, record):
            _scan(f"[{record.levelname}] {self.format(record)}")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if DEBUG_MODE else logging.WARNING)
    root_logger.handlers.clear()
    root_logger.addHandler(BufHandler())

    init_web_from_config(APP_CONFIG)
    init_ap_from_config(APP_CONFIG)
    init_model_update_from_config(APP_CONFIG)
    init_config_update_from_config(APP_CONFIG)
    init_app_update_from_config(APP_CONFIG)
    init_metrics_from_config(APP_CONFIG)
    init_network_bindings_from_config(APP_CONFIG)
    init_auth_from_config(APP_CONFIG)
    init_api_from_config(APP_CONFIG)
    init_notify_from_config(APP_CONFIG)
    start_oui_loader()
    ensure_model_map_file(model_path or args.model_map)
    load_model_map(args.model_map)
    load_history_store(HISTORY_STORE_PATH)

    if args.notify_test:
        ok, resp = send_test_notification_from_config()
        if ok:
            _log("[INFO] WeCom notify test sent")
            if resp:
                _log(f"[INFO] WeCom response: {resp}")
        else:
            _log(f"[WARN] WeCom test notification failed: {resp}")
        return

    if hasattr(os, "geteuid") and os.geteuid() != 0:
        if _process_has_capabilities(list(RUNTIME_SERVICE_CAPABILITIES)):
            _log("[INFO] running without root; required network capabilities are present")
        else:
            _log("[WARN] 权限不足，请在设置页修复。")

    check_iw_available_on_startup()

    if SCAN_WIFI_FAST and (not args.hop) and (not args.channel):
        args.hop = True
        args.hop_5g = True
        _log("[INFO] WiFi fast-transfer scan enabled: auto use 2.4G+5G hopping")
    elif SCAN_WIFI_FAST and args.hop and (not args.hop_5g):
        args.hop_5g = True
        _log("[INFO] WiFi fast-transfer scan enabled: append 5G hopping")

    iface = interface_detect(prefer=args.iface)
    with sniff_health_lock:
        sniff_iface_name = str(iface or "")
    WIFI_FAST_SUPPORTED = False
    WIFI_FAST_SUPPORT_MSG = ""
    if iface:
        try:
            WIFI_FAST_SUPPORTED = bool(detect_5g(iface))
        except Exception:
            WIFI_FAST_SUPPORTED = False
        if SCAN_WIFI_FAST and WIFI_FAST_SUPPORTED:
            WIFI_FAST_SUPPORT_MSG = f"iface {iface} supports 5GHz; WiFi fast-transfer scan enabled"
        if SCAN_WIFI_FAST and not WIFI_FAST_SUPPORTED:
            WIFI_FAST_SUPPORT_MSG = f"iface {iface} does not support 5GHz; WiFi fast-transfer scan unavailable"
            _log(f"[WARN] {WIFI_FAST_SUPPORT_MSG}")
    else:
        WIFI_FAST_SUPPORT_MSG = NO_IFACE_DEGRADE_HINT
        _log(f"[WARN] {NO_IFACE_DEGRADE_HINT}")

    if args.hop and args.channel:
        _log("[WARN] --hop and --channel both set; using hopping mode")

    hop_cfg: tuple[list[int], list[int], int, int] | None = None
    if args.hop:
        dw2 = max(100, args.dwell_2g)
        dw5 = max(200, args.dwell_5g)
        hop_2g = CHANNELS_2G[:]
        hop_5g: list[int] = []
        if args.hop_5g:
            if WIFI_FAST_SUPPORTED:
                if SCAN_WIFI_FAST:
                    hop_5g = sorted(set(CHANNELS_5G + CHANNELS_5G_COMMON))
                else:
                    hop_5g = CHANNELS_5G[:]
                _log(f"[INFO] 5G channels={hop_5g}")
            else:
                _log("[INFO] 5G unsupported, using 2.4G only")
        hop_cfg = (hop_2g, hop_5g, dw2, dw5)
        _log(f"[INFO] hopping 2.4G={hop_2g}@{dw2}ms" + (f" 5G={hop_5g}@{dw5}ms" if hop_5g else ""))
        if iface:
            Thread(target=channel_hopper,
                   args=(iface, hop_2g, hop_5g, dw2, dw5,
                         max(0, args.settle), args.dwell_on_hit, args.hit_cap),
                   daemon=True).start()
        else:
            _log("[WARN] 无可用网卡，等待恢复…")
    elif args.channel:
        _log(f"[INFO] lock channel {args.channel}")
        if iface:
            run_cmd(f"iw dev {iface} set channel {args.channel}")
        else:
            _log("[WARN] 当前无网卡，先记录信道配置，网卡恢复后自动应用")
        current_channel = args.channel
    else:
        # Default lock to ch6 (DJI RID commonly used channel).
        _log("[INFO] default lock channel 6 (DJI RID common). Use --hop or --channel N to change")
        if iface:
            run_cmd(f"iw dev {iface} set channel 6")
        else:
            _log("[WARN] 当前无网卡，先使用默认信道配置，网卡恢复后自动应用")
        current_channel = 6

    _log(f"[INFO] output: first/changed(min-gap={MIN_GAP:.1f}s)/heartbeat(time={PRINT_INTERVAL:.1f}s)")
    _log(f"[INFO] LOST timeout={LOST_TIMEOUT:.0f}s  PURGE={PURGE_TIMEOUT:.0f}s")
    if DEBUG_MODE:
        _log("[INFO] DEBUG mode: all raw frames are written into scan log (press d)")

    Thread(target=lost_checker, daemon=True).start()
    Thread(target=http_server_thread, daemon=True).start()
    Thread(target=history_persist_loop, daemon=True).start()
    Thread(target=host_metrics_loop, daemon=True).start()
    start_packet_parse_worker()
    start_history_reparse_worker()
    start_hw_worker()
    start_notify_worker()
    start_model_update_worker()
    start_config_update_worker()
    start_app_update_check()
    _app_update_mark_startup_ready()

    def sniff_thread():
        global sniff_iface_name
        retry_delay = 2.0
        fail_count = 0
        recover_fail_count = 0
        iface_cur = str(iface or "")
        iface_watch_since = time.monotonic() if iface_cur else 0.0
        hop_started = bool(args.hop and bool(iface))
        simulation_was_paused = False

        def note_recover_failure(reason: str, allow_restart: bool = True) -> None:
            nonlocal recover_fail_count
            if (not allow_restart) or (not _cfg_auto_self_heal()):
                recover_fail_count = 0
                return
            recover_fail_count += 1
            _log(f"[WARN] sniff recover failed {recover_fail_count}/{SNIFF_RESTART_AFTER_FAILS}: {reason}")
            if recover_fail_count >= SNIFF_RESTART_AFTER_FAILS:
                _log("[WARN] sniff recover failed too many times, schedule self-restart")
                ok, msg = _schedule_self_restart(list(sys.argv[1:]))
                if not ok:
                    _log(f"[WARN] self-restart scheduling failed: {msg}")
                recover_fail_count = 0

        def note_recover_success() -> None:
            nonlocal recover_fail_count
            recover_fail_count = 0

        def set_iface_watch(iface_name: str) -> None:
            nonlocal iface_watch_since
            iface_watch_since = time.monotonic() if iface_name else 0.0

        while True:
            prefer_iface = _cfg_preferred_iface()
            if not iface_cur:
                iface_cur = _sniff_pick_iface(prefer=prefer_iface)
                if iface_cur:
                    set_iface_watch(iface_cur)
                    with sniff_health_lock:
                        sniff_iface_name = iface_cur
                    _log(f"[INFO] sniff iface recovered: {iface_cur}")
                    ok = _sniff_recover_iface(iface_cur, "iface connected", force=True)
                    if not ok:
                        _log(f"[WARN] sniff iface init failed: {iface_cur}, waiting retry")
                        iface_cur = ""
                        time.sleep(retry_delay)
                        continue
                    if args.hop and (not hop_started) and hop_cfg:
                        hop_2g, hop_5g, dw2, dw5 = hop_cfg
                        Thread(target=channel_hopper,
                               args=(iface_cur, hop_2g, hop_5g, dw2, dw5,
                                     max(0, args.settle), args.dwell_on_hit, args.hit_cap),
                               daemon=True).start()
                        hop_started = True
                    elif (not args.hop):
                        if current_channel:
                            run_cmd(f"iw dev {iface_cur} set channel {current_channel}")
                else:
                    _sniff_note_error(NO_IFACE_DEGRADE_HINT)
                    # Missing/unconfigured NIC should surface as a stable degraded state,
                    # not a self-restart loop.
                    note_recover_failure("no iface available", allow_restart=False)
                    _log(f"[WARN] sniff no available iface, retry in {retry_delay:.0f}s")
                    time.sleep(retry_delay)
                    continue

            try:
                with sniff_health_lock:
                    sniff_iface_name = iface_cur
                state, detail = _sniff_run_once(iface_cur, timeout_sec=SNIFF_POLL_TIMEOUT)
                if state == "hung":
                    _sniff_note_error(f"sniff worker hung: {detail}")
                    _log(f"[WARN] sniff worker hung on {iface_cur}: {detail}")
                    recovered = _sniff_recover_iface(iface_cur, f"worker hung: {detail}", force=True)
                    if not recovered:
                        new_iface = _sniff_pick_iface(prefer=(prefer_iface or iface_cur))
                        if new_iface and new_iface != iface_cur:
                            _log(f"[WARN] sniff iface switch after hang: {iface_cur} -> {new_iface}")
                            iface_cur = new_iface
                            set_iface_watch(iface_cur)
                            with sniff_health_lock:
                                sniff_iface_name = iface_cur
                            recovered = _sniff_recover_iface(iface_cur, "switch iface after hang", force=True)
                    if recovered:
                        set_iface_watch(iface_cur)
                        note_recover_success()
                    else:
                        note_recover_failure(f"worker hung on {iface_cur}", allow_restart=True)
                    time.sleep(retry_delay)
                    continue
                if state != "ok":
                    raise RuntimeError(detail or "sniff worker failed")
                fail_count = 0
                if simulation_scan_pause_event.is_set():
                    simulation_was_paused = True
                    set_iface_watch(iface_cur)
                    note_recover_success()
                    time.sleep(0.05)
                    continue
                if simulation_was_paused:
                    _sniff_note_resume()
                    set_iface_watch(iface_cur)
                    simulation_was_paused = False
                now_mono = time.monotonic()
                idle = _sniff_idle_sec(now_mono)
                no_pkt_elapsed = None
                if idle is None and iface_watch_since > 0.0:
                    no_pkt_elapsed = max(0.0, now_mono - iface_watch_since)
                stall_reason = None
                if idle is not None and idle >= SNIFF_STALL_RECOVER_SEC:
                    stall_reason = f"idle {idle:.0f}s without management frame"
                elif no_pkt_elapsed is not None and no_pkt_elapsed >= SNIFF_STALL_RECOVER_SEC:
                    stall_reason = f"no management frame for {no_pkt_elapsed:.0f}s after sniff start"
                if stall_reason:
                    recovered = _sniff_recover_iface(iface_cur, stall_reason, force=True)
                    if not recovered:
                        new_iface = _sniff_pick_iface(prefer=(prefer_iface or iface_cur))
                        if new_iface and new_iface != iface_cur:
                            _log(f"[WARN] sniff iface switch: {iface_cur} -> {new_iface}")
                            iface_cur = new_iface
                            set_iface_watch(iface_cur)
                            with sniff_health_lock:
                                sniff_iface_name = iface_cur
                            recovered = _sniff_recover_iface(iface_cur, "switch iface recovery", force=True)
                    if recovered:
                        set_iface_watch(iface_cur)
                        note_recover_success()
                    else:
                        note_recover_failure(stall_reason, allow_restart=True)
                else:
                    note_recover_success()
                time.sleep(0.05)
            except Exception as ex:
                fail_count += 1
                ex_msg = str(ex or "")
                _sniff_note_error(f"sniff exception#{fail_count}: {ex_msg}")
                no_dev_err = _sniff_is_no_device_error(ex)
                note_recover_failure(ex_msg, allow_restart=True)
                if _cfg_auto_self_heal() and (not no_dev_err) and fail_count >= SNIFF_RESTART_AFTER_FAILS:
                    _log(f"[WARN] sniff exception count reached {SNIFF_RESTART_AFTER_FAILS}, scheduling self-restart")
                    ok, msg = _schedule_self_restart(list(sys.argv[1:]))
                    if not ok:
                        _log(f"[WARN] self-restart scheduling failed: {msg}")
                    fail_count = 0

                if no_dev_err:
                    fail_count = 0
                    new_iface = _sniff_pick_iface(prefer=(prefer_iface or iface_cur))
                    if new_iface and new_iface != iface_cur:
                        _log(f"[WARN] sniff iface unavailable, switch {iface_cur} -> {new_iface}")
                        iface_cur = new_iface
                        set_iface_watch(iface_cur)
                        with sniff_health_lock:
                            sniff_iface_name = iface_cur
                        _sniff_recover_iface(iface_cur, f"after iface switch: {ex_msg}", force=True)
                    elif new_iface:
                        _log(f"[WARN] sniff iface exception#{fail_count}: {ex_msg}, try reset {iface_cur}")
                        if _sniff_recover_iface(iface_cur, f"exception#{fail_count}: {ex_msg}", force=True):
                            set_iface_watch(iface_cur)
                    else:
                        _log(f"[WARN] sniff iface lost: {ex_msg}, waiting for NIC recovery")
                        iface_cur = ""
                else:
                    _log(f"[WARN] sniff exception#{fail_count}: {ex_msg}, retry in {retry_delay:.0f}s")
                    _sniff_recover_iface(iface_cur, f"exception#{fail_count}: {ex_msg}", force=(fail_count >= 3))

                time.sleep(retry_delay)

    Thread(target=sniff_thread, daemon=True).start()

    if NO_TUI:
        _log("[INFO] --no-tui mode (Ctrl+C to exit)")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            _log("[INFO] stopped")
        finally:
            save_history_store(force=True)
    else:
        if curses is None:
            raise SystemExit("curses is not available; install windows-curses on Windows or run with --no-tui")
        try:
            curses.wrapper(tui_main, args)
        except KeyboardInterrupt:
            pass
        finally:
            save_history_store(force=True)
            print("\n[INFO] TUI exited, last 30 event logs:")
            with log_lock:
                for line in list(log_buf)[-30:]:
                    print(line)
            if DEBUG_MODE:
                print("\n[INFO] Last 30 scan logs:")
                with log_lock:
                    for line in list(scan_buf)[-30:]:
                        print(line)

if __name__ == "__main__":
    main()
