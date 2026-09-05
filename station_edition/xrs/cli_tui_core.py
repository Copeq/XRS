"""cli tui core (extracted from cli_app.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
Scapy / curses / shared names resolve at call time.
"""

def _entry_row(e: dict, now: float) -> dict:
    age  = now - e.get("last_seen_ts", now)
    lost = age > LOST_TIMEOUT
    ch   = e.get("last_ch") or 0
    sn   = str(e.get("sn",""))
    return {
        "dot":     "○" if lost else "●",
        "lost":    lost,
        "mac_only": sn.startswith("MAC:"),
        "sn_s":    (sn[:20]+"...") if len(sn)>21 else sn,
        "model":   str(e.get("model","N/A")),
        "ch_s":    f"{'~' if e.get('ch_assumed') else ''}{ch}" if ch else "?",
        "lat_s":   _fmt(e.get("lat"),".5f"),
        "lon_s":   _fmt(e.get("lon"),".5f"),
        "alt_s":   _fmt(e.get("alt"),".1f","m"),
        "spd_s":   _fmt(e.get("speed"),".1f","m/s"),
        "vsp_s":   _fmt(e.get("vspeed"),".1f"),
        "rssi_s":  _fmt(e.get("rssi"),"d","dBm"),
        "pkts":    str(e.get("pkt_count",0)),
        "dir_s":   e.get("move_dir") or "-",
        "age_s":   f"{age:.0f}s",
    }

def tui_main(stdscr, args) -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)
    curses.start_color()
    curses.use_default_colors()

    curses.init_pair(1, curses.COLOR_GREEN,  -1)   # 在线 SN
    curses.init_pair(2, curses.COLOR_YELLOW, -1)   # MAC-only
    curses.init_pair(3, curses.COLOR_WHITE,  -1)   # 离线
    curses.init_pair(4, curses.COLOR_CYAN,   -1)   # 表头
    curses.init_pair(5, curses.COLOR_BLACK,  curses.COLOR_CYAN)  # title bar
    curses.init_pair(6, curses.COLOR_YELLOW, -1)                 # 变化高亮

    C_ONLINE  = curses.color_pair(1) | curses.A_BOLD
    C_MACONLY = curses.color_pair(2)
    C_LOST    = curses.color_pair(3) | curses.A_DIM
    C_HEADER  = curses.color_pair(4) | curses.A_BOLD
    C_TITLE   = curses.color_pair(5) | curses.A_BOLD
    C_HL      = curses.color_pair(6) | curses.A_BOLD

    # mode: "table" | "log"（事件日志） | "scan"（完整扫描日志）
    mode       = "table"
    log_offset = 0
    last_draw  = 0.0

    while True:
        now = time.monotonic()
        h, w = stdscr.getmaxyx()

        try:
            key = stdscr.getch()
        except curses.error:
            key = -1

        if key in (ord('q'), ord('Q')):
            break
        elif key in (ord('d'), ord('D')):
            if mode == "table":
                mode = "scan"       # First press `d`: scan log
            elif mode == "scan":
                mode = "log"        # Second press `d`: event log
            else:
                mode = "table"      # Third press `d`: back to table
            log_offset = 0
        elif key == curses.KEY_UP:
            if mode != "table": log_offset = min(log_offset+3, LOG_BUF_SIZE-1)
        elif key == curses.KEY_DOWN:
            if mode != "table": log_offset = max(log_offset-3, 0)
        elif key in (ord('g'), curses.KEY_HOME, ord('G'), curses.KEY_END):
            log_offset = 0

        if (now - last_draw) < TUI_REFRESH and key == -1:
            time.sleep(0.03)
            continue
        last_draw = now

        stdscr.erase()

        # -- title bar ------------------------------------------------------
        with state_lock:
            n_total = len(state_table)
            n_live  = sum(1 for e in state_table.values()
                         if (now-e["last_seen_ts"]) <= LOST_TIMEOUT)
        ch_s    = f"ch{current_channel}" if current_channel else "ch?"
        dbg_s   = " [DEBUG]" if DEBUG_MODE else ""
        mode_lbl = {"table":"table","scan":"scan-log","log":"events"}.get(mode,"?")
        left  = f"  RID Monitor  LIVE={n_live}  LOST={n_total-n_live}  {ch_s}{dbg_s} "
        right = f" [d]{mode_lbl}  [↑↓]scroll  [q]quit "
        bar   = left.ljust(w - _sw(right)) + right
        try: stdscr.addstr(0, 0, _pad(bar, w), C_TITLE)
        except curses.error: pass

        if mode == "table":
            _draw_table(stdscr, h, w, now, C_HEADER, C_ONLINE, C_MACONLY, C_LOST, C_HL)
        elif mode == "scan":
            _draw_buf(stdscr, h, w, scan_buf, log_offset, "scan log (all frames)", "d->events d->table")
        else:
            _draw_buf(stdscr, h, w, log_buf,  log_offset, "事件日志", "d->表格")

        try: stdscr.refresh()
        except curses.error: pass

def _draw_table(stdscr, h, w, now, C_HEADER, C_ONLINE, C_MACONLY, C_LOST, C_HL):
    # 表头
    hdr = ""
    for label, width, _ in COLUMNS:
        hdr += _pad(label, width) + " "
    sep = "-" * min(w, _sw(hdr))
    try:
        stdscr.addstr(1, 0, hdr[:w], C_HEADER)
        stdscr.addstr(2, 0, sep[:w], C_HEADER)
    except curses.error: pass

    with state_lock:
        entries = sorted(
            state_table.values(),
            key=lambda e: (
                (now-e["last_seen_ts"]) > LOST_TIMEOUT,
                -(e.get("rssi") or -999),
            )
        )

    row_y = 3
    for e in entries:
        if row_y >= h-1: break
        r  = _entry_row(e, now)
        hl = e.get("_hl", {})   # {col_key: expire_monotonic}
        if r["lost"]:       base_attr = C_LOST
        elif r["mac_only"]: base_attr = C_MACONLY
        else:               base_attr = C_ONLINE

        col_x = 0
        for _, width, key in COLUMNS:
            cell  = _pad(str(r.get(key,"")), width) + " "
            # Highlight this column if it has unexpired change mark.
            attr  = C_HL if (not r["lost"] and hl.get(key, 0) > now) else base_attr
            try: stdscr.addstr(row_y, col_x, cell, attr)
            except curses.error: pass
            col_x += width + 1
            if col_x >= w: break

        row_y += 1

    hint = f" total={len(entries)} refresh~{TUI_REFRESH:.1f}s "
    try: stdscr.addstr(h-1, 0, hint[:w].ljust(w), curses.A_DIM)
    except curses.error: pass

def _draw_buf(stdscr, h, w, buf: deque, offset: int, title: str, hint_extra: str):
    with log_lock:
        lines = list(buf)
    vis     = h - 2
    total   = len(lines)
    end_i   = max(0, total - offset)
    start_i = max(0, end_i - vis)
    for i, line in enumerate(lines[start_i:end_i]):
        if 1+i >= h-1: break
        try: stdscr.addstr(1+i, 0, line[:w].ljust(min(w, len(line)+4)))
        except curses.error: pass
    hint = f" {title} [{start_i+1}-{end_i}/{total}]  scroll ↑↓  {hint_extra} "
    try: stdscr.addstr(h-1, 0, hint[:w].ljust(w), curses.A_DIM)
    except curses.error: pass

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
