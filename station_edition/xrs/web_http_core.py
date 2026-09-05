"""HTTP+WebSocket request handling (do_GET/do_POST route dispatch) extracted from
web_server.py during backend module split. Page HTML building stays in web_server.py
(to be extracted to a dedicated frontend later).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
"""

def _web_frontend_mode() -> str:
    """返回前端 UI 产物策略：vue（Vite 壳）/ legacy（web_server.py 模板）。

    由 config.json 的 web.frontend 控制，缺省为 vue（新项目默认走新前端）。
    """
    cfg = WEB_CFG if isinstance(WEB_CFG, dict) else {}
    mode = str((cfg or {}).get("frontend") or "").strip().lower()
    return mode if mode in ("vue", "legacy") else "vue"


def _vue_frontend_enabled() -> bool:
    return _web_frontend_mode() == "vue"


def _frontend_index_path() -> str | None:
    """返回 Vite 产物入口 index.html 的绝对路径；产物缺失时返回 None。"""
    p = _station_asset_path("assets", "frontend", "index.html")
    return None if p is None else str(p)


def http_server_thread() -> None:
    import socket as _socket
    import threading as _threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn

    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    class Handler(BaseHTTPRequestHandler):
        server_version = APP_SERVER_HEADER
        sys_version = ""

        def end_headers(self):
            set_tok = getattr(self, "_auth_set_cookie_token", "")
            if set_tok:
                self.send_header(
                    "Set-Cookie",
                    sanitize_http_header_value(
                        f"{AUTH_SESSION_COOKIE}={set_tok}; Max-Age={int(AUTH_SESSION_TTL_SEC)}; Path=/; HttpOnly; SameSite=Lax"
                    ),
                )
                self._auth_set_cookie_token = ""
            if getattr(self, "_auth_clear_cookie", False):
                self.send_header(
                    "Set-Cookie",
                    sanitize_http_header_value(
                        f"{AUTH_SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"
                    ),
                )
                self._auth_clear_cookie = False
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            self.send_header("Permissions-Policy", "geolocation=(self), microphone=(), camera=()")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; "
                "base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; "
                "script-src 'self' 'unsafe-inline' https://unpkg.com; "
                "style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com data:; "
                "img-src 'self' data: blob: http: https:; "
                "connect-src 'self' ws: wss: https://unpkg.com; "
                "media-src 'none'"
            )
            super().end_headers()

        def handle(self):
            try:
                return super().handle()
            except OSError as e:
                # Browser/WebSocket clients may disconnect abruptly; avoid noisy traceback.
                if getattr(e, "errno", None) in (32, 54, 104, 10053, 10054):
                    return
                raise

        def _send_json(self, obj: dict, code: int = 200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError as e:
                if getattr(e, "errno", None) not in (32, 54, 104, 10053, 10054):
                    raise

        def _send_bytes(self, body: bytes, content_type: str, filename: str | None = None, code: int = 200):
            body = bytes(body or b"")
            self.send_response(code)
            self.send_header(
                "Content-Type",
                sanitize_http_header_value(content_type, "application/octet-stream"),
            )
            self.send_header("Cache-Control", "no-store")
            if filename:
                safe = (
                    re.sub(r'[^A-Za-z0-9._-]+', '_', str(filename or "download.bin")).strip("._")
                    or "download.bin"
                )
                self.send_header(
                    "Content-Disposition",
                    sanitize_http_header_value(f'attachment; filename="{safe}"'),
                )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError as e:
                if getattr(e, "errno", None) not in (32, 54, 104, 10053, 10054):
                    raise

        def _redirect(self, location: str, code: int = 302):
            self.send_response(code)
            self.send_header("Location", sanitize_http_header_value(location, "/"))
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _read_json_body(self) -> dict:
            try:
                n = int(self.headers.get("Content-Length", "0") or "0")
            except Exception:
                n = 0
            if n > HTTP_JSON_MAX_BYTES:
                try:
                    self.rfile.read(min(n, 4096))
                except Exception:
                    pass
                return {}
            raw = b""
            if n > 0:
                try:
                    raw = self.rfile.read(n)
                except Exception:
                    raw = b""
            if not raw:
                return {}
            try:
                obj = json.loads(raw.decode("utf-8", errors="replace"))
            except Exception:
                return {}
            return obj if isinstance(obj, dict) else {}

        def _read_binary_upload_info(self) -> tuple[str, int]:
            raw_name = str(self.headers.get(APP_UPDATE_UPLOAD_NAME_HEADER) or "").strip()
            try:
                file_name = unquote(raw_name) if raw_name else ""
            except Exception:
                file_name = raw_name
            try:
                n = int(self.headers.get("Content-Length", "0") or "0")
            except Exception:
                n = 0
            return file_name, max(0, n)

        def _auth_fail(self):
            self.send_response(401)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = json.dumps({
                "ok": False,
                "error": "auth required",
                "auth_expired": True,
                "login_url": "/login?next=/",
            }, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def _api_token_fail(self):
            self.send_response(401)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = json.dumps({
                "ok": False,
                "error": "api token required",
                "hint": "use X-API-Token or Authorization: Bearer <token>",
            }, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def _rate_limit_fail(self, retry_after: int = 60):
            body = json.dumps({
                "ok": False,
                "error": "too many attempts",
                "retry_after_sec": int(max(1, retry_after)),
            }, ensure_ascii=False).encode("utf-8")
            self.send_response(429)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Retry-After", str(int(max(1, retry_after))))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def _page_api_fail(self, code: int = 403, message: str = "page session required"):
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            payload = {
                "ok": False,
                "error": message,
                "hint": "call this endpoint from the built-in web pages",
            }
            if int(code) == 401:
                payload["auth_expired"] = True
                payload["login_url"] = "/login?next=/"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def _api_whitelist_fail(self):
            self.send_response(403)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = json.dumps({
                "ok": False,
                "error": "当前无权访问该界面",
            }, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def _access_denied_page(self):
            body = '<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>403</title><style>body{margin:0;min-height:100dvh;display:grid;place-items:center;background:#201f1e;color:#f3f2f1;font-family:"Segoe UI","Microsoft YaHei",sans-serif}.box{border:1px solid #3b3a39;background:#2b2a29;padding:24px;border-radius:4px}h1{margin:0;font-size:26px}</style></head><body><div class="box"><h1>当前无权访问该界面</h1></div></body></html>'.encode("utf-8")
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def _require_auth(self) -> bool:
            if not _web_access_allowed(_client_ip_from_handler(self)):
                _op_log("web-access-deny", str(self.path or ""), ip=_client_ip_from_handler(self), ok=False)
                self._access_denied_page()
                return False
            if not _auth_enabled():
                return True
            if _auth_check_session_cookie(self.headers.get("Cookie"), refresh=True):
                return True
            req_path = str(self.path or "").split("?", 1)[0]
            if req_path == "/ws":
                # Avoid Safari repeatedly showing Basic-Auth dialog on websocket reconnect.
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return False
            if req_path.startswith("/api/"):
                self._auth_fail()
                return False
            try:
                from urllib.parse import quote, urlparse, parse_qs
                target = str(self.path or "/")
                if not target.startswith("/") or target.startswith("//"):
                    target = "/"
                parsed_target = urlparse(target)
                target_query = parse_qs(parsed_target.query or "")
                if parsed_target.path in ("/", "/index.html") and _request_prefers_mobile_home(self.headers, target_query):
                    target = "/m/" + (("?" + parsed_target.query) if parsed_target.query else "")
                self._redirect("/login?next=" + quote(target, safe="/?=&%"))
            except Exception:
                self._redirect("/login")
            return False

        def _require_page_api(self) -> bool:
            if not _web_access_allowed(_client_ip_from_handler(self)):
                _op_log("web-api-deny", str(self.path or ""), ip=_client_ip_from_handler(self), ok=False)
                self._page_api_fail(403, "当前无权访问该界面")
                return False
            if not _request_same_origin(self.headers):
                self._page_api_fail(403, "cross-origin page api denied")
                return False
            if not _page_api_header_ok(self.headers):
                self._page_api_fail(403, "page api header required")
                return False
            if _auth_enabled() and not _auth_check_session_cookie(self.headers.get("Cookie"), refresh=True):
                self._page_api_fail(401, "login required")
                return False
            return True

        def _require_raw_config_access(self) -> bool:
            if not self._require_page_api():
                return False
            if not (_auth_enabled() and _auth_hashes_present(AUTH_CFG)):
                return True
            if _raw_config_unlocked(self.headers.get("Cookie")):
                return True
            self._page_api_fail(403, "raw config unlock required")
            return False

        def _require_api_token(self, query: dict | None = None) -> bool:
            if not _api_token_enabled():
                return False
            ip = self.client_address[0] if self.client_address else ""
            if bool(API_CFG.get("whitelist_enabled")) and (not _api_access_allowed(ip)):
                _op_log("api-whitelist-deny", str(self.path or ""), ip=str(ip or "-"), ok=False)
                self._api_whitelist_fail()
                return False
            limited, retry_after = _rate_limited("api-token", ip, str(self.path or ""), limit=24, window_sec=120, block_sec=600)
            if limited:
                self._rate_limit_fail(retry_after)
                return False
            token = _api_token_from_request(self.headers, query)
            matched_token = _api_token_check_value(token)
            if matched_token:
                if bool(matched_token.get("single_use")):
                    _api_mark_token_used(str(matched_token.get("id") or ""))
                _rate_note("api-token", ip, str(self.path or ""), success=True, limit=24, window_sec=120, block_sec=600)
                return True
            _rate_note("api-token", ip, str(self.path or ""), success=False, limit=24, window_sec=120, block_sec=600)
            _op_log("api-token-deny", str(self.path or ""), ip=str(ip or "-"), ok=False)
            self._api_token_fail()
            return False

        def _require_public_api(self, query: dict | None = None) -> bool:
            if _api_token_enabled():
                return self._require_api_token(query)
            return self._require_page_api()

        def _send_captive_portal_page(self) -> None:
            host = str(globals().get("AP_WEB_ADDRESS_DEFAULT", "172.16.0.1") or "172.16.0.1")
            target = f"http://{host}/"
            body = (
                "<!doctype html><html><head><meta charset=\"utf-8\">"
                f"<meta http-equiv=\"refresh\" content=\"0;url={target}\">"
                "<title>XRS</title></head>"
                f"<body><p>正在打开 XRS 页面。<a href=\"{target}\">立即打开</a></p></body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_asset_file(self, path: str) -> bool:
            from urllib.parse import unquote
            rel = unquote(str(path or "")[len("/assets/"):]).replace("\\", "/")
            parts = [p for p in rel.split("/") if p and p not in (".", "..")]
            if not parts or "/".join(parts) != rel:
                self._send_json({"ok": False, "error": "invalid asset path"}, 400)
                return True
            try:
                package_dir = getattr(globals().get("RUNTIME_CONTEXT"), "package_dir", None)
                base_dir = os.path.join(str(package_dir or os.path.dirname(__file__)), "assets")
                full = os.path.abspath(os.path.join(base_dir, *parts))
                base_abs = os.path.abspath(base_dir)
                if not (full == base_abs or full.startswith(base_abs + os.sep)) or not os.path.isfile(full):
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return True
                ext = os.path.splitext(full)[1].lower()
                ctype = {
                    ".css": "text/css; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8",
                    ".png": "image/png",
                    ".svg": "image/svg+xml; charset=utf-8",
                    ".map": "application/json; charset=utf-8",
                }.get(ext, "application/octet-stream")
                with open(full, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                if path.startswith("/assets/vue/") and ext in {".js", ".map"}:
                    self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                else:
                    self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return True
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
                return True

        def _serve_static_asset_or_portal(self, path: str) -> bool:
            """链 1：静态资源 / 门户探测托管 —— 公共、无守卫、纯静态输出。

            原 do_GET 顶部三组（/assets/*、Captive-Portal 探测路径、/favicon.ico）
            收拢为独立托管链。命中即已应答并返回 True。
            """
            if path.startswith("/assets/"):
                self._send_asset_file(path)
                return True
            if path in (
                "/generate_204",
                "/gen_204",
                "/hotspot-detect.html",
                "/library/test/success.html",
                "/connecttest.txt",
                "/ncsi.txt",
                "/canonical.html",
                "/success.txt",
            ):
                self._send_captive_portal_page()
                return True
            if path == "/favicon.ico":
                self.send_response(204)
                self.send_header("Cache-Control", "max-age=86400")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return True
            return False

        def _serve_dashboard_pages(self, path: str, query: dict) -> bool:
            """链 2：dashboard 页面托管（须已通过 EULA/OOBE/鉴权 gate）。

            只负责 /、/m 及各子页 HTML 的路径匹配与响应发送；页面构建函数
            （web_server.py 的 _build_*_html / _HW_PAGE_HTML 常量）保持不动。
            命中返回 True，否则返回 False 交由链 3 继续。
            """
            if path in ("/m", "/m/", "/m/index.html"):
                body = _build_mobile_html().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return True
            if path in ("/", "/index.html"):
                if _request_prefers_mobile_home(self.headers, query):
                    self._redirect("/m/")
                    return True
                # 前端产物开关：config.web.frontend = vue → 首页切到 Vite 产物
                if _vue_frontend_enabled():
                    frontend_index = _frontend_index_path()
                    if frontend_index is not None:
                        self._send_html_file(frontend_index)
                        return True
                body = _build_html().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return True
            if path in ("/settings", "/settings.html"):
                body = _build_settings_html().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return True
            if path in ("/logs", "/logs.html"):
                body = _build_logs_html().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return True
            if path in ("/diagnostics", "/diagnostics.html"):
                body = _build_diagnostics_html().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return True
            if path in ("/hardware-assistant", "/hardware-assistant.html"):
                body = _HW_PAGE_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return True
            return False

        def _send_html_bytes(self, body: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html_file(self, file_path: str) -> None:
            try:
                with open(file_path, "rb") as f:
                    body = f.read()
            except OSError:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._send_html_bytes(body)

        def _send_frontend_static(self, full: str) -> None:
            ext = os.path.splitext(full)[1].lower()
            ctype = {
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".svg": "image/svg+xml; charset=utf-8",
                ".png": "image/png",
                ".ico": "image/x-icon",
                ".woff": "font/woff",
                ".woff2": "font/woff2",
                ".map": "application/json; charset=utf-8",
            }.get(ext, "application/octet-stream")
            try:
                with open(full, "rb") as f:
                    body = f.read()
            except OSError:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            if ext in (".js", ".css"):
                self.send_header("Cache-Control", "no-cache")
            else:
                self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_ui_shell_or_asset(self, path: str) -> bool:
            """链 2：Vite 前端产物托管（/ui[/...]）。

            - 入口 /ui、/ui/、/ui/index.html → index.html
            - /ui/assets/* 等真实文件 → 静态内容
            - 其余 /ui/* 子路径未命中文件 → SPA fallback 回 index.html
            依赖 _frontend_index_path()；产物缺失（尚未 build）时直接返回 False。
            """
            if not (path == "/ui" or path.startswith("/ui/")):
                return False
            frontend_index = _frontend_index_path()
            if not frontend_index:
                return False
            base_dir = os.path.dirname(frontend_index)
            rel = path[len("/ui/"):] if path.startswith("/ui/") else ""
            if not rel or rel in ("index.html", "index.htm"):
                self._send_html_file(frontend_index)
                return True
            safe_rel = str(rel).replace("\\", "/")
            parts = [p for p in safe_rel.split("/") if p and p not in (".", "..")]
            if not parts or "/".join(parts) != safe_rel:
                self._send_html_file(frontend_index)
                return True
            full = os.path.abspath(os.path.join(base_dir, *parts))
            base_abs = os.path.abspath(base_dir)
            if (full == base_abs or full.startswith(base_abs + os.sep)) and os.path.isfile(full):
                self._send_frontend_static(full)
                return True
            self._send_html_file(frontend_index)
            return True

        def _dispatch_data_head_get(self, path: str, query: dict) -> bool:
            """数据 GET 头部分派（auth gate 之后）：/api、/api/docs、/api/health 与 /api/v1*。

            保持原有独立 if 语义；命中任一分支即已应答并返回 True，否则返回 False
            交由后续 dashboard/数据链继续处理。
            """
            from urllib.parse import unquote
            if path in ("/api", "/api/"):
                if not self._require_page_api():
                    return True
                self._send_json(_api_token_docs_payload(), 200)
                return True
            if path == "/api/docs":
                self._send_json(_api_token_docs_payload(), 200)
                return True
            if path == "/api/health":
                now_mono = time.monotonic()
                now_wall = time.time()
                sniff = _sniff_health_meta(now_mono, now_wall)
                self._send_json({
                    "ok": True,
                    "api": _api_meta(),
                    "service": {
                        "uptime_sec": int(max(0.0, now_wall - APP_START_WALL)),
                        "sniff_state": sniff.get("state"),
                        "sniff_msg": sniff.get("msg"),
                        "sniff_iface": sniff.get("iface"),
                        "current_channel": int(current_channel or 0),
                    },
                }, 200)
                return True
            if path in ("/api/v1", "/api/v1/"):
                self._send_json(_api_v1_home_payload(), 200)
                return True
            if path == "/api/v1/snapshot":
                self._send_json({
                    "ok": True,
                    "api": _api_meta(),
                    "data": _state_snapshot(),
                }, 200)
                return True
            if path == "/api/v1/auth/status":
                self._send_json({
                    "ok": True,
                    "api": _api_meta(),
                    "auth": (_api_v1_home_payload().get("auth") or {}),
                }, 200)
                return True
            if path == "/api/v1/drones":
                online_only = _to_bool((query.get("online_only") or ["0"])[0], False)
                include_archived = _to_bool((query.get("include_archived") or ["1"])[0], True)
                snap = _state_snapshot()
                items = list(snap.get("drones") or [])
                if online_only:
                    items = [x for x in items if not bool(x.get("lost")) and not bool(x.get("archived"))]
                elif not include_archived:
                    items = [x for x in items if not bool(x.get("archived"))]
                self._send_json({
                    "ok": True,
                    "api": _api_meta(),
                    "count": len(items),
                    "items": items,
                }, 200)
                return True
            if path == "/api/v1/metrics":
                raw_window = str((query.get("window") or ["24h"])[0] or "24h").strip().lower()
                if raw_window in ("12h", "12"):
                    window_sec = 12 * 3600
                elif raw_window in ("7d", "7"):
                    window_sec = 7 * 86400
                else:
                    window_sec = 24 * 3600
                payload = _host_metrics_payload(window_sec=window_sec)
                payload["api"] = _api_meta()
                self._send_json(payload, 200)
                return True
            if path.startswith("/api/v1/drones/"):
                sn = unquote(path[len("/api/v1/drones/"):]).strip()
                if not sn:
                    self._send_json({"ok": False, "error": "sn required"}, 400)
                    return True
                snap = _state_snapshot()
                item = None
                for x in (snap.get("drones") or []):
                    if str(x.get("sn") or "") == sn:
                        item = x
                        break
                if not item:
                    self._send_json({"ok": False, "error": "sn not found"}, 404)
                    return True
                with state_lock:
                    src = state_table.get(sn) or history_table.get(sn) or {}
                    tracks = _sanitize_tracks(src)
                    track = _track_for_query(tracks, query, firmware_type=src.get("firmware_type"))
                self._send_json({
                    "ok": True,
                    "api": _api_meta(),
                    "item": item,
                    "track_count": len(track),
                    "track": track,
                    "tracks": {
                        "aircraft": _track_for_query(tracks, {"track_type": ["aircraft"]}, firmware_type=src.get("firmware_type")),
                        "operator": _track_for_query(tracks, {"track_type": ["operator"]}, firmware_type=src.get("firmware_type")),
                    },
                }, 200)
                return True
            if path == "/api/v1/aps":
                aps, aps_seq, aps_total = _ap_snapshot()
                self._send_json({
                    "ok": True,
                    "api": _api_meta(),
                    "seq": aps_seq,
                    "total": aps_total,
                    "count": len(aps),
                    "items": aps,
                }, 200)
                return True
            if path == "/api/v1/logs":
                log_type = str((query.get("type") or ["event"])[0] or "event").strip().lower()
                try:
                    limit = int((query.get("limit") or ["200"])[0] or "200")
                except Exception:
                    limit = 200
                limit = max(1, min(2000, limit))
                with log_lock:
                    if log_type == "scan":
                        rows = list(scan_buf)[-limit:]
                    elif log_type == "ap":
                        rows = list(ap_buf)[-limit:]
                    else:
                        log_type = "event"
                        rows = list(log_buf)[-limit:]
                self._send_json({
                    "ok": True,
                    "api": _api_meta(),
                    "type": log_type,
                    "count": len(rows),
                    "items": rows,
                }, 200)
                return True
            if path.startswith("/api/v1/tracks/"):
                sn = unquote(path[len("/api/v1/tracks/"):]).strip()
                if not sn:
                    self._send_json({"ok": False, "error": "sn required"}, 400)
                    return True
                with state_lock:
                    src = state_table.get(sn) or history_table.get(sn) or {}
                    tracks = _sanitize_tracks(src)
                    track = _track_for_query(tracks, query, firmware_type=src.get("firmware_type"))
                self._send_json({
                    "ok": True,
                    "api": _api_meta(),
                    "sn": sn,
                    "count": len(track),
                    "track": track,
                    "tracks": {
                        "aircraft": _track_for_query(tracks, {"track_type": ["aircraft"]}, firmware_type=src.get("firmware_type")),
                        "operator": _track_for_query(tracks, {"track_type": ["operator"]}, firmware_type=src.get("firmware_type")),
                    },
                }, 200)
                return True
            return False

        def do_GET(self):
            from urllib.parse import urlparse, parse_qs, quote, unquote
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query or "")

            # ===== 链 1：静态资源 / 门户探测托管（公共、无守卫）=====
            if self._serve_static_asset_or_portal(path):
                return

            if path == "/api/eula/status":
                self._send_json(_eula_status_payload(), 200)
                return
            if path == "/api/config/tree":
                if not self._require_raw_config_access():
                    return
                try:
                    root = _config_root_dir()
                    self._send_json({
                        "ok": True,
                        "root": root,
                        "root_name": os.path.basename(root.rstrip("\\/")) or root,
                        "tree": _config_tree_entries(root).get("tree") or [],
                        "raw_access": _raw_config_access_payload(self.headers),
                    }, 200)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
                return
            if path == "/api/config/file":
                if not self._require_raw_config_access():
                    return
                try:
                    file_path = _config_resolve_path((query.get("path") or [""])[0] if isinstance(query, dict) else None)
                    if not file_path:
                        self._send_json({"ok": False, "error": "invalid path"}, 400)
                        return
                    root = _config_root_dir()
                    with open(file_path, "r", encoding="utf-8") as f:
                        text = f.read()
                    st = os.stat(file_path)
                    self._send_json({
                        "ok": True,
                        "path": file_path,
                        "rel_path": _config_rel_path(file_path, root),
                        "root": root,
                        "name": os.path.basename(file_path),
                        "text": text,
                        "size": int(st.st_size),
                        "mtime": float(st.st_mtime),
                        "raw_access": _raw_config_access_payload(self.headers),
                    }, 200)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
                return
            if path in ("/eula", "/eula.html"):
                next_path = str((query.get("next") or ["/"])[0] or "/")
                if not next_path.startswith("/") or next_path.startswith("//"):
                    next_path = "/"
                body = _build_eula_html(next_path).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if _eula_redirect_required(path):
                if path.startswith("/api/"):
                    self._send_json({
                        "ok": False,
                        "error": "eula required",
                        "eula_url": EULA_URL,
                    }, 428)
                else:
                    target = str(self.path or "/")
                    if not target.startswith("/") or target.startswith("//"):
                        target = "/"
                    self._redirect("/eula?next=" + quote(target, safe="/?=&%"))
                return
            if (not path.startswith("/api/")) and path != "/ws" and (not _web_access_allowed(_client_ip_from_handler(self))):
                _op_log("web-access-deny", str(self.path or ""), ip=_client_ip_from_handler(self), ok=False)
                self._access_denied_page()
                return
            if path == "/api/oobe/status":
                if not self._require_page_api():
                    return
                self._send_json(_oobe_status_payload(), 200)
                return
            if path in ("/oobe", "/oobe.html"):
                manual_oobe = _to_bool((query.get("manual") or ["0"])[0], False)
                if not _oobe_state().get("required") and not manual_oobe:
                    self._redirect("/")
                    return
                if (_auth_enabled() and _auth_hashes_present(AUTH_CFG)) and not _auth_check_session_cookie(self.headers.get("Cookie"), refresh=True):
                    self._redirect("/login?next=/oobe")
                    return
                body = _build_oobe_html().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if _oobe_redirect_required(path) and not (path in ("/login", "/login.html") and _oobe_auth_required()):
                if path == "/ws":
                    self.send_response(503)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif path.startswith("/api/"):
                    self._send_json({
                        "ok": False,
                        "error": "oobe required",
                        "oobe": _oobe_state(),
                    }, 409)
                else:
                    self._redirect("/oobe")
                return
            if path in ("/login", "/login.html"):
                next_path = str((query.get("next") or ["/"])[0] or "/")
                if not next_path.startswith("/") or next_path.startswith("//"):
                    next_path = "/"
                if not _auth_enabled():
                    self._redirect(next_path)
                    return
                user_value = str((query.get("user") or [""])[0] or "")
                pass_value = str((query.get("password") or [""])[0] or "")
                check_code = str((query.get("check") or [""])[0] or "")
                if user_value and not pass_value and ",password=" in user_value:
                    _ignored_user, pass_value = user_value.split(",password=", 1)
                if user_value and not pass_value and "?password=" in user_value:
                    _ignored_user, pass_value = user_value.split("?password=", 1)
                if pass_value and not check_code and "?check=" in pass_value:
                    _ignored_pass, check_code = pass_value.split("?check=", 1)
                if check_code:
                    ip = _client_ip_from_handler(self)
                    subject = check_code[:12]
                    limited, retry_after = _rate_limited("login-sso", ip, subject, limit=8, window_sec=300, block_sec=900)
                    if limited:
                        self._rate_limit_fail(retry_after)
                        return
                    sso_item = _auth_check_sso_link(check_code)
                    ok_login = bool(sso_item)
                    _rate_note("login-sso", ip, subject, success=ok_login, limit=8, window_sec=300, block_sec=900)
                    _op_log("login-sso", "next=" + next_path, actor=subject, ip=ip, ok=ok_login)
                    if ok_login:
                        if bool((sso_item or {}).get("single_use")):
                            _auth_mark_sso_used(check_code)
                        self._auth_set_cookie_token = _auth_issue_session()
                        sso_next = str((sso_item or {}).get("next") or next_path or "/")
                        if not sso_next.startswith("/") or sso_next.startswith("//"):
                            sso_next = "/"
                        self._redirect(sso_next)
                    else:
                        body = _build_login_html(next_path, "SSO 登录失败或链接已失效", True).encode("utf-8")
                        self.send_response(401)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    return
                if _auth_check_session_cookie(self.headers.get("Cookie"), refresh=True):
                    self._redirect(next_path)
                    return
                body = _build_login_html(next_path).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/logout":
                _op_log("logout", "", ip=_client_ip_from_handler(self), ok=True)
                self._auth_clear_cookie = True
                self._redirect("/login")
                return
            if path == "/api/update-health":
                if not _update_probe_header_ok(self.headers):
                    self._send_json({"ok": False, "error": "probe header required"}, 403)
                    return
                now_wall = time.time()
                self._send_json({
                    "ok": True,
                    "time": _api_iso_now(now_wall),
                    "service": {
                        "uptime_sec": int(max(0.0, now_wall - APP_START_WALL)),
                    },
                }, 200)
                return
            if _path_uses_api_token(path):
                if not self._require_public_api(query):
                    return
            elif _path_is_page_api(path):
                if not self._require_page_api():
                    return
            elif not self._require_auth():
                return
            # ===== 链 2x：数据 GET 头部（/api、/api/docs、/api/health、/api/v1*）=====
            if self._dispatch_data_head_get(path, query):
                return
            # ===== 链 2：前端产物托管（Vite 壳 /ui，位于鉴权 gate 之后）=====
            if self._serve_ui_shell_or_asset(path):
                return
            # ===== 链 2b：dashboard 页面托管（legacy 模板，鉴权 gate 已通过）=====
            if self._serve_dashboard_pages(path, query):
                return
            # ===== 链 3：数据 API + WS（未命中由链尾 else 兜底 404）=====
            if path == "/api/config":
                if not self._require_raw_config_access():
                    return
                try:
                    self._send_json(_config_file_payload(APP_CONFIG_PATH), 200)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
            elif path == "/api/settings/view":
                try:
                    self._send_json(_settings_view_payload(), 200)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
            elif path == "/api/notifications":
                try:
                    limit = int((query.get("limit") or [str(NOTIFICATION_CENTER_MAX)])[0] or NOTIFICATION_CENTER_MAX)
                except Exception:
                    limit = NOTIFICATION_CENTER_MAX
                self._send_json(_notification_payload(limit), 200)
            elif path == "/api/settings/runtime":
                try:
                    limit = int((query.get("limit") or ["180"])[0] or "180")
                except Exception:
                    limit = 180
                self._send_json(_settings_runtime_payload(limit=limit), 200)
            elif path in ("/api/history/reidentify-status", "/api/settings/history/reidentify-status", "/api/v1/history/reidentify-status"):
                payload = history_reparse_workflow_status()
                if path.startswith("/api/v1/"):
                    payload["api"] = _api_meta()
                self._send_json(payload, 200)
            elif path == "/api/diagnostics/summary":
                self._send_json(_diagnostics_summary_payload(), 200)
            elif path == "/api/settings/metrics":
                raw_window = str((query.get("window") or ["24h"])[0] or "24h").strip().lower()
                if raw_window in ("12h", "12"):
                    window_sec = 12 * 3600
                elif raw_window in ("7d", "7"):
                    window_sec = 7 * 86400
                else:
                    window_sec = 24 * 3600
                self._send_json(_host_metrics_payload(window_sec=window_sec), 200)
            elif path == "/api/settings/systemd/status":
                self._send_json(_systemd_service_status_payload(), 200)
            elif path == "/api/simulation/status":
                self._send_json(simulation_status(), 200)
            elif path == "/api/drones/get":
                sn = ""
                try:
                    sn = str((query.get("sn") or [""])[0] or "").strip()
                except Exception:
                    sn = ""
                if not sn:
                    self._send_json({"ok": False, "error": "sn required"}, 400)
                    return
                include_tracks = _to_bool((query.get("include_tracks") or ["0"])[0], False)
                now_mono = time.monotonic()
                now_wall = time.time()
                with state_lock:
                    cur = state_table.get(sn) or {}
                    hist = history_table.get(sn) or {}
                    src = cur or hist
                    if not src:
                        self._send_json({"ok": False, "error": "sn not found"}, 404)
                        return
                    item = {key: src.get(key) for key in HISTORY_DETAIL_KEYS if key in src}
                    scan_type_key = _scan_type_key(cur.get("scan_type", hist.get("scan_type", "rid")))
                    firmware_type_key = _firmware_type_key(cur.get("firmware_type", hist.get("firmware_type", "old")))
                    model_name = _resolve_model_name(sn, scan_type_key, cur.get("model", hist.get("model")))
                    if cur:
                        last_seen_ts = cur.get("last_seen_ts")
                        if last_seen_ts is None:
                            last_seen_ts = now_mono
                        age = max(0.0, now_mono - last_seen_ts)
                    else:
                        try:
                            age = max(0.0, now_wall - float(hist.get("last_seen_wall_ts") or now_wall))
                        except Exception:
                            age = 0.0
                    lost = age > LOST_TIMEOUT
                    id_src = str(cur.get("id_type", hist.get("id_type","")) or "")
                    ch = cur.get("last_ch", hist.get("last_ch")) or 0
                    ch_assumed = bool(cur.get("ch_assumed", hist.get("ch_assumed")))
                    cap_wall_ts = cur.get("last_capture_wall_ts", hist.get("last_capture_wall_ts"))
                    tracks = _sanitize_tracks(src)
                    track = _track_for_query(tracks, query, firmware_type=src.get("firmware_type")) if include_tracks else []
                    raw_packets = list(src.get("raw_packets", []) or [])
                    item.update({
                        "sn": sn,
                        "sn_src": _sn_source_display(id_src),
                        "uas_id": _uas_id_clean(cur.get("uas_id") or hist.get("uas_id","")),
                        "scan_type": _scan_type_display(scan_type_key),
                        "firmware_type": _firmware_type_display(firmware_type_key),
                        "firmware_type_key": firmware_type_key,
                        "model": model_name,
                        "lost": lost,
                        "archived": sn not in state_table,
                        "mac": cur.get("src_mac", hist.get("src_mac","")),
                        "id_type": id_src or "-",
                        "ch": f"{'~' if ch_assumed else ''}{ch}" if ch else "?",
                        "ch_assumed": ch_assumed,
                        "alt": cur.get("alt", hist.get("alt")),
                        "spd": cur.get("speed", hist.get("speed")),
                        "vspd": cur.get("vspeed", hist.get("vspeed")),
                        "rssi": cur.get("rssi", hist.get("rssi")),
                        "pkts": hist.get("pkt_count_total", cur.get("pkt_count",0)),
                        "dir": cur.get("move_dir", hist.get("move_dir")) or "-",
                        "ssid": cur.get("ssid", hist.get("ssid","")) or "",
                        "capture_type": cur.get("capture_type", hist.get("capture_type","")) or "",
                        "capture_time": _fmt_wall_ts(cap_wall_ts),
                        "last_pkt_time": _fmt_wall_ts(cap_wall_ts),
                        "raw_packets": raw_packets[-HISTORY_RAW_PACKET_SNAPSHOT_LIMIT:],
                        "raw_packets_count": len(raw_packets),
                        "scan_type_key": scan_type_key,
                        "age": round(age),
                        "age_text": _fmt_age_compact(age),
                        "first_seen": _fmt_wall_ts(hist.get("first_seen_wall_ts", cur.get("first_seen_wall_ts"))),
                        "last_seen": _fmt_wall_ts(hist.get("last_seen_wall_ts", cur.get("last_seen_wall_ts"))),
                        "track_count": len(_track_store_primary(tracks, "aircraft")),
                        "operator_track_count": len(_track_store_primary(tracks, "operator")),
                    })
                    item.pop("tracks", None)
                    item.pop("track", None)
                    aircraft_query = {**query, "track_type": ["aircraft"]}
                    operator_query = {**query, "track_type": ["operator"]}
                    aircraft_track = _track_for_query(tracks, aircraft_query, firmware_type=src.get("firmware_type")) if include_tracks else []
                    operator_track = _track_for_query(tracks, operator_query, firmware_type=src.get("firmware_type")) if include_tracks else []
                payload = {
                    "ok": True,
                    "item": item,
                    "track_count": len(track),
                }
                if include_tracks:
                    payload["track"] = track
                    payload["tracks"] = {
                        "aircraft": aircraft_track,
                        "operator": operator_track,
                    }
                self._send_json(payload, 200)
            elif path == "/api/settings/models/list":
                self._send_json(_model_map_editor_payload(), 200)
            elif path == "/api/logs/view":
                try:
                    limit = int((query.get("limit") or ["500"])[0] or "500")
                except Exception:
                    limit = 500
                log_type = str((query.get("type") or ["runtime"])[0] or "runtime")
                self._send_json(_logs_snapshot(log_type, limit=limit), 200)
            elif path == "/api/logs/export":
                try:
                    limit = int((query.get("limit") or ["5000"])[0] or "5000")
                except Exception:
                    limit = 5000
                log_type = str((query.get("type") or ["all"])[0] or "all")
                try:
                    body, filename, ctype = _logs_export_bytes(log_type, limit=limit)
                    _op_log("logs-export", f"type={log_type} limit={limit}", ip=_client_ip_from_handler(self), ok=True)
                    self._send_bytes(body, ctype, filename=filename, code=200)
                except Exception as e:
                    _op_log("logs-export", f"type={log_type} error={e}", ip=_client_ip_from_handler(self), ok=False)
                    self._send_json({"ok": False, "error": str(e)}, 500)
            elif path == "/api/interfaces":
                try:
                    basic = APP_CONFIG.get("basic") if isinstance(APP_CONFIG, dict) else {}
                    if not isinstance(basic, dict):
                        basic = {}
                    self._send_json({
                        "ok": True,
                        "items": _iface_options_snapshot(),
                        "active_iface": str(sniff_iface_name or ""),
                        "selected_iface": (None if basic.get("iface") in (None, "") else str(basic.get("iface"))),
                        "scan_wifi_fast": bool(basic.get("scan_wifi_fast")),
                    }, 200)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
            elif path == "/api/network-bindings/status":
                try:
                    self._send_json(_network_bindings_status_payload(), 200)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
            elif path == "/api/hw/status":
                try:
                    snap = _hw_submit_task({"op": "status"}, timeout_sec=10)
                    if snap.get("ok") and isinstance(snap.get("data"), dict):
                        data = snap.get("data")
                        data["ok"] = True
                        self._send_json(data, 200)
                    else:
                        self._send_json({"ok": False, "error": str(snap.get("error") or "status failed")}, 500)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
            elif path == "/api/tracks/get":
                sn = ""
                try:
                    sn = str((query.get("sn") or [""])[0] or "").strip()
                except Exception:
                    sn = ""
                if not sn:
                    self._send_json({"ok": False, "error": "sn required"}, 400)
                    return
                with state_lock:
                    src = state_table.get(sn) or history_table.get(sn) or {}
                    firmware_type = src.get("firmware_type")
                    tracks = _sanitize_tracks(src)
                    full_count = _track_display_count(tracks, "aircraft", firmware_type=firmware_type)
                    track = _track_for_query(tracks, query, firmware_type=firmware_type)
                    aircraft_query = dict(query)
                    aircraft_query["track_type"] = ["aircraft"]
                    operator_query = dict(query)
                    operator_query["track_type"] = ["operator"]
                self._send_json({
                    "ok": True,
                    "sn": sn,
                    "count": len(track),
                    "count_total": full_count,
                    "track": track,
                    "tracks": {
                        "aircraft": _track_for_query(tracks, aircraft_query, firmware_type=firmware_type),
                        "operator": _track_for_query(tracks, operator_query, firmware_type=firmware_type),
                    },
                }, 200)
            elif path == "/api/tools/export/all":
                with state_lock:
                    items = _history_disk_items_locked()
                _op_log("tools-export-all", f"count={len(items)}", ip=_client_ip_from_handler(self), ok=True)
                self._send_json({
                    "ok": True,
                    "version": 1,
                    "exported_at": time.time(),
                    "count": len(items),
                    "items": items,
                }, 200)
            elif path == "/api/tools/export/track":
                sn = ""
                try:
                    sn = str((query.get("sn") or [""])[0] or "").strip()
                except Exception:
                    sn = ""
                if not sn:
                    self._send_json({"ok": False, "error": "sn required"}, 400)
                    return
                with state_lock:
                    src = state_table.get(sn) or history_table.get(sn) or {}
                    tracks = _sanitize_tracks(src)
                    track = _track_for_query(tracks, {"track_type": ["aircraft"]}, firmware_type=src.get("firmware_type"))
                _op_log("tools-export-track", f"sn={sn} count={len(track)}", ip=_client_ip_from_handler(self), ok=True)
                self._send_json({
                    "ok": True,
                    "version": 1,
                    "exported_at": time.time(),
                    "sn": sn,
                    "count": len(track),
                    "track": track,
                    "tracks": {
                        "aircraft": _track_for_query(tracks, {"track_type": ["aircraft"]}, firmware_type=src.get("firmware_type")),
                        "operator": _track_for_query(tracks, {"track_type": ["operator"]}, firmware_type=src.get("firmware_type")),
                    },
                }, 200)
            elif path == "/api/settings/export/settings":
                payload = _settings_export_payload()
                _op_log("settings-export", f"path={payload.get('config_path') or '-'}", ip=_client_ip_from_handler(self), ok=True)
                self._send_json(payload, 200)
            elif path == "/api/settings/export/scan-data":
                payload = _scan_data_export_payload()
                _op_log("scan-data-export", f"count={payload.get('count') or 0}", ip=_client_ip_from_handler(self), ok=True)
                self._send_json(payload, 200)
            elif path == "/api/tools/diagnostic.zip":
                try:
                    body, filename = _diagnostic_zip_bytes()
                    _op_log("diagnostic-export", f"filename={filename} bytes={len(body)}", ip=_client_ip_from_handler(self), ok=True)
                    self._send_bytes(body, "application/zip", filename=filename, code=200)
                except Exception as e:
                    _op_log("diagnostic-export", f"error={e}", ip=_client_ip_from_handler(self), ok=False)
                    self._send_json({"ok": False, "error": str(e)}, 500)
            elif path == "/ws":
                # Headers are already parsed by BaseHTTPRequestHandler; read key directly.
                origin = str(self.headers.get("Origin") or "").strip()
                host = str(self.headers.get("Host") or "").strip()
                if origin and host:
                    try:
                        from urllib.parse import urlparse as _urlparse
                        o = _urlparse(origin)
                        if o.netloc and o.netloc.lower() != host.lower():
                            self.send_response(403)
                            self.end_headers()
                            return
                    except Exception:
                        pass
                key = self.headers.get("Sec-WebSocket-Key","").strip()
                if not key:
                    self.send_response(400); self.end_headers(); return
                import base64 as _b64, hashlib as _hl
                accept = _b64.b64encode(
                    _hl.sha1((key+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
                ).decode()
                resp = ("HTTP/1.1 101 Switching Protocols\r\n"
                        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Accept: {accept}\r\n\r\n")
                self.connection.sendall(resp.encode())
                sock = self.connection
                ws_mode = str((query.get("page") or ["home"])[0] or "home").strip().lower()
                if ws_mode != "settings":
                    ws_mode = "home"
                client_entry = {
                    "sock": sock,
                    "mode": ws_mode,
                    "send_lock": Lock(),
                    "next_send_at": (time.monotonic() + 5.0) if ws_mode == "settings" else 0.0,
                }
                with _ws_lock:
                    _ws_clients.append(client_entry)
                import json as _json
                try:
                    initial_payload = _ws_settings_runtime_payload() if ws_mode == "settings" else _state_snapshot(lightweight=True)
                    _ws_send_client(client_entry, _ws_frame(
                        _json.dumps(initial_payload, ensure_ascii=False).encode()))
                except Exception:
                    pass
                # Keep connection open and drain incoming frames until disconnect.
                try:
                    sock.settimeout(120)
                    while True:
                        opcode, payload = _ws_recv_client_frame(sock)
                        if opcode == 8: break
                        if opcode == 9:
                            _ws_send_client(client_entry, bytes([0x8A, len(payload)]) + payload)
                            continue
                        if opcode != 1:
                            continue
                        try:
                            message = _json.loads(payload.decode("utf-8"))
                        except Exception:
                            continue
                        if isinstance(message, dict) and message.get("kind") == "ping":
                            pong = {"kind": "pong", "id": str(message.get("id") or "")[:80]}
                            _ws_send_client(client_entry, _ws_frame(_json.dumps(pong).encode("utf-8")))
                except Exception:
                    pass
                with _ws_lock:
                    if client_entry in _ws_clients: _ws_clients.remove(client_entry)
                try: sock.close()
                except Exception: pass
            else:
                self.send_response(404); self.end_headers()

        def _dispatch_post_page_actions(self, path: str) -> bool:
            """链 A：页面动作 / 会话流程 POST。

            登录、EULA/OOBE 流程、passkey 登录与 raw 配置解锁等前置端点不需要既有
            会话，统一收拢在本方法；命中即已应答并返回 True，否则返回 False 交给链 B。
            """
            if path == "/api/eula/accept":
                if not _request_same_origin(self.headers) or not _page_api_header_ok(self.headers):
                    self._page_api_fail(403, "page api header required")
                    return True
                body = self._read_json_body()
                if not _to_bool(body.get("accepted"), False):
                    self._send_json({"ok": False, "error": "必须同意许可协议后才能继续"}, 400)
                    return True
                ok, msg = _write_eula_acceptance()
                if not ok:
                    self._send_json({"ok": False, "error": msg}, 500)
                    return True
                next_path = str(body.get("next") or "/")
                if not next_path.startswith("/") or next_path.startswith("//"):
                    next_path = "/"
                self._send_json({"ok": True, "accepted": True, "next": next_path, "set_path": msg}, 200)
                return True
            if _eula_redirect_required(path):
                self._send_json({
                    "ok": False,
                    "error": "eula required",
                    "eula_url": EULA_URL,
                }, 428)
                return True
            if path == "/api/oobe/save":
                if not self._require_page_api():
                    return True
                body = self._read_json_body()
                rsp = _oobe_save_config(body)
                self._send_json(rsp, 200 if rsp.get("ok") else 400)
                return True
            if path == "/api/settings/raw/unlock":
                if not self._require_page_api():
                    return True
                body = self._read_json_body()
                user = str(body.get("username") or "").strip()
                pwd = str(body.get("password") or "")
                if not user or not pwd:
                    self._send_json({"ok": False, "error": "账号和密码必须同时填写", "raw_access": _raw_config_access_payload(self.headers)}, 400)
                    return True
                if not _auth_check_userpass(user, pwd):
                    self._send_json({"ok": False, "error": "账号或密码错误", "raw_access": _raw_config_access_payload(self.headers)}, 401)
                    return True
                _raw_config_unlock_set(self.headers.get("Cookie"))
                self._send_json({
                    "ok": True,
                    "unlocked": True,
                    "raw_access": _raw_config_access_payload(self.headers),
                }, 200)
                return True
            if path == "/api/passkey/login/start":
                if not _request_same_origin(self.headers) or not _page_api_header_ok(self.headers):
                    self._page_api_fail(403, "page api header required")
                    return True
                self._read_json_body()
                rsp = _passkey_login_begin(self.headers)
                self._send_json(rsp, 200 if rsp.get("ok") else 400)
                return True
            if path == "/api/passkey/login/finish":
                if not _request_same_origin(self.headers) or not _page_api_header_ok(self.headers):
                    self._page_api_fail(403, "page api header required")
                    return True
                body = self._read_json_body()
                rsp, code = _passkey_finish_login(body, self.headers, client_ip=_client_ip_from_handler(self))
                if rsp.get("ok"):
                    self._auth_set_cookie_token = str(rsp.pop("session") or "")
                self._send_json(rsp, code)
                return True
            if _oobe_redirect_required(path) and not (path in ("/login", "/login.html") and _oobe_auth_required()):
                self._send_json({
                    "ok": False,
                    "error": "oobe required",
                    "oobe": _oobe_state(),
                }, 409)
                return True
            if path in ("/login", "/login.html"):
                body = self._read_json_body()
                user = str(body.get("username") or "")
                pwd = str(body.get("password") or "")
                if not _auth_login_method_enabled("password"):
                    self._send_json({"ok": False, "error": "账号密码登录已关闭"}, 403)
                    return True
                ip = _client_ip_from_handler(self)
                limited, retry_after = _rate_limited("login", ip, user, limit=8, window_sec=300, block_sec=900)
                if limited:
                    self._rate_limit_fail(retry_after)
                    return True
                ok_login = _auth_check_userpass(user, pwd)
                _rate_note("login", ip, user, success=ok_login, limit=8, window_sec=300, block_sec=900)
                _op_log("login", "", actor=user or "-", ip=ip, ok=ok_login)
                if ok_login:
                    self._auth_set_cookie_token = _auth_issue_session()
                    self._send_json({"ok": True, "next": "/"}, 200)
                else:
                    self._send_json({"ok": False, "error": "账号或密码错误"}, 401)
                return True
            return False

        def do_POST(self):
            from urllib.parse import urlparse
            path = urlparse(self.path).path

            # ===== 链 A：页面动作 / 会话流程 POST（无需既有会话）=====
            if self._dispatch_post_page_actions(path):
                return
            # ===== 链 B：数据 API POST（经下方鉴权 gate 与体积 gate）=====
            if _path_uses_api_token(path):
                if not self._require_public_api(None):
                    return
            elif _path_is_page_api(path):
                if not self._require_page_api():
                    return
            elif not self._require_auth():
                return
            try:
                body_len = int(self.headers.get("Content-Length", "0") or "0")
            except Exception:
                body_len = 0
            if path == "/api/settings/app-update/upload":
                if body_len > APP_UPDATE_MAX_BYTES:
                    self._send_json({"ok": False, "error": f"upload too large (>{APP_UPDATE_MAX_BYTES} bytes)"}, 413)
                    return
            elif body_len > HTTP_JSON_MAX_BYTES:
                self._send_json({"ok": False, "error": f"request too large (>{HTTP_JSON_MAX_BYTES} bytes)"}, 413)
                return
            if path == "/api/notifications":
                body = self._read_json_body()
                item = _notification_add(
                    str(body.get("text") or ""),
                    str(body.get("kind") or "info"),
                    "page",
                )
                if not item:
                    self._send_json({"ok": False, "error": "text required"}, 400)
                    return
                payload = _notification_payload()
                payload["item"] = item
                self._send_json(payload, 200)
                return
            if path == "/api/simulation/start":
                body = self._read_json_body()
                try:
                    rsp = simulation_start(body)
                except Exception as exc:
                    _log(f"[WARN] simulation start failed: {exc}")
                    rsp = {"ok": False, "error": f"simulation start failed: {exc}"}
                _op_log(
                    "simulation-start",
                    f"count={rsp.get('count', 0)} pattern={(rsp.get('options') or {}).get('pattern', '')}",
                    ip=_client_ip_from_handler(self),
                    ok=bool(rsp.get("ok")),
                )
                self._send_json(rsp, 200 if rsp.get("ok") else 400)
                return
            if path == "/api/simulation/stop":
                self._read_json_body()
                rsp = simulation_stop()
                _op_log(
                    "simulation-stop",
                    f"removed={rsp.get('removed', 0)}",
                    ip=_client_ip_from_handler(self),
                    ok=True,
                )
                self._send_json(rsp, 200)
                return
            if path == "/api/notifications/delete":
                body = self._read_json_body()
                removed = _notification_delete(body.get("id"))
                payload = _notification_payload()
                payload["removed"] = bool(removed)
                self._send_json(payload, 200)
                return
            if path == "/api/notifications/clear":
                self._read_json_body()
                cleared = _notification_clear()
                self._send_json({"ok": True, "cleared": cleared, "seq": int(notification_seq), "count": 0, "items": []}, 200)
                return
            if path == "/api/eula/revoke":
                self._read_json_body()
                ok, msg = _revoke_eula_acceptance()
                if not ok:
                    self._send_json({"ok": False, "error": msg}, 500)
                    return
                self._send_json({"ok": True, "accepted": False, "set_path": msg, "next": "/eula?next=/settings"}, 200)
                return
            if path == "/api/v1/auth/logout":
                self._send_json({"ok": True, "api": _api_meta(), "logout": False, "token_api": True}, 200)
                return
            if path == "/api/v1/history/clear":
                try:
                    cleared, removed = clear_history_store(delete_file=True)
                    _op_log("api-v1-history-clear", f"cleared={cleared} file_removed={removed}", ip=_client_ip_from_handler(self), ok=True)
                    self._send_json({
                        "ok": True,
                        "api": _api_meta(),
                        "cleared": cleared,
                        "file_removed": removed,
                        "history_file": HISTORY_STORE_PATH,
                    }, 200)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
                return
            if path == "/api/v1/history/delete":
                body = self._read_json_body()
                sn = str(body.get("sn") or "").strip()
                if not sn:
                    self._send_json({"ok": False, "error": "sn required"}, 400)
                    return
                removed = delete_history_item(sn)
                _op_log("api-v1-history-delete", f"sn={sn} removed={removed}", ip=_client_ip_from_handler(self), ok=True)
                self._send_json({
                    "ok": True,
                    "api": _api_meta(),
                    "sn": sn,
                    "removed": bool(removed),
                }, 200)
                return
            if path == "/api/v1/tracks/clear":
                body = self._read_json_body()
                sn = str(body.get("sn") or "").strip()
                affected = clear_track_store(sn if sn else None)
                _op_log("api-v1-track-clear", f"sn={sn or '*'} affected={affected}", ip=_client_ip_from_handler(self), ok=True)
                self._send_json({
                    "ok": True,
                    "api": _api_meta(),
                    "sn": (sn or None),
                    "affected": int(affected),
                }, 200)
                return
            if path == "/api/v1/config/reload":
                if not APP_CONFIG_PATH:
                    self._send_json({"ok": False, "error": "config path missing"}, 500)
                    return
                try:
                    cfg_loaded = load_app_config(APP_CONFIG_PATH)
                    r_ok, r_msg = reload_runtime_config(cfg_loaded)
                    _op_log("api-v1-config-reload", f"ok={r_ok} msg={r_msg}", ip=_client_ip_from_handler(self), ok=bool(r_ok))
                    self._send_json({
                        "ok": True,
                        "api": _api_meta(),
                        "reloaded": bool(r_ok),
                        "reload_msg": str(r_msg or ""),
                        "config_path": APP_CONFIG_PATH,
                    }, 200)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
                return
            if path == "/api/v1/history/reparse":
                body = self._read_json_body()
                sn = str(body.get("sn") or "").strip() if isinstance(body, dict) else ""
                mode = str(body.get("mode") or "auto") if isinstance(body, dict) else "auto"
                try:
                    rsp = reidentify_history_packet_for_sn(sn, mode=mode)
                    rsp["api"] = _api_meta()
                    _op_log("api-v1-history-reparse", f"sn={sn} mode={mode} ok={bool(rsp.get('ok'))}", ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                    self._send_json(rsp, 200 if rsp.get("ok") else 400)
                except Exception as e:
                    _op_log("api-v1-history-reparse", f"sn={sn} mode={mode} error={e}", ip=_client_ip_from_handler(self), ok=False)
                    self._send_json({"ok": False, "error": str(e), "api": _api_meta()}, 500)
                return
            if path == "/api/v1/history/reidentify-recent":
                body = self._read_json_body()
                try:
                    limit = int(body.get("limit") or _track_store_points_limit()) if isinstance(body, dict) else _track_store_points_limit()
                except Exception:
                    limit = _track_store_points_limit()
                try:
                    rsp = start_recent_history_reidentify_workflow(limit=limit)
                    rsp["api"] = _api_meta()
                    workflow = rsp.get("workflow") if isinstance(rsp.get("workflow"), dict) else {}
                    summary = (
                        f"started={bool(rsp.get('started'))} total={workflow.get('total')} "
                        f"pending={workflow.get('pending')} batch={workflow.get('batch_size')}"
                    )
                    _op_log("api-v1-history-reidentify-recent", str(rsp.get("error") or summary), ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                    self._send_json(rsp, 200 if rsp.get("ok") else 400)
                except Exception as e:
                    _op_log("api-v1-history-reidentify-recent", f"error={e}", ip=_client_ip_from_handler(self), ok=False)
                    self._send_json({"ok": False, "error": str(e), "api": _api_meta()}, 500)
                return
            if path == "/api/history/clear":
                self._read_json_body()
                try:
                    cleared, removed = clear_history_store(delete_file=True)
                    _op_log("history-clear", f"cleared={cleared} file_removed={removed}", ip=_client_ip_from_handler(self), ok=True)
                    self._send_json({
                        "ok": True,
                        "cleared": cleared,
                        "file_removed": removed,
                        "history_file": HISTORY_STORE_PATH,
                    }, 200)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
            elif path == "/api/history/delete":
                body = self._read_json_body()
                sn = str(body.get("sn") or "").strip()
                if not sn:
                    self._send_json({"ok": False, "error": "sn required"}, 400)
                    return
                removed = delete_history_item(sn)
                _op_log("history-delete", f"sn={sn} removed={removed}", ip=_client_ip_from_handler(self), ok=True)
                self._send_json({"ok": True, "sn": sn, "removed": bool(removed)}, 200)
            elif path == "/api/history/reparse":
                body = self._read_json_body()
                sn = str(body.get("sn") or "").strip() if isinstance(body, dict) else ""
                mode = str(body.get("mode") or "auto") if isinstance(body, dict) else "auto"
                try:
                    rsp = reidentify_history_packet_for_sn(sn, mode=mode)
                    _op_log("history-reparse", f"sn={sn} mode={mode} ok={bool(rsp.get('ok'))}", ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                    self._send_json(rsp, 200 if rsp.get("ok") else 400)
                except Exception as e:
                    _op_log("history-reparse", f"sn={sn} mode={mode} error={e}", ip=_client_ip_from_handler(self), ok=False)
                    self._send_json({"ok": False, "error": str(e)}, 500)
            elif path in ("/api/settings/history/reidentify-recent", "/api/settings/history/reidentify-latest"):
                body = self._read_json_body()
                try:
                    limit = int(body.get("limit") or _track_store_points_limit()) if isinstance(body, dict) else _track_store_points_limit()
                except Exception:
                    limit = _track_store_points_limit()
                try:
                    rsp = start_recent_history_reidentify_workflow(limit=limit)
                    workflow = rsp.get("workflow") if isinstance(rsp.get("workflow"), dict) else {}
                    summary = (
                        f"started={bool(rsp.get('started'))} total={workflow.get('total')} "
                        f"pending={workflow.get('pending')} batch={workflow.get('batch_size')}"
                    )
                    _op_log("history-reidentify-recent", str(rsp.get("error") or summary), ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                    self._send_json(rsp, 200 if rsp.get("ok") else 400)
                except Exception as e:
                    _op_log("history-reidentify-recent", f"error={e}", ip=_client_ip_from_handler(self), ok=False)
                    self._send_json({"ok": False, "error": str(e)}, 500)
            elif path == "/api/settings/import/settings":
                body = self._read_json_body()
                payload = body.get("payload", body) if isinstance(body, dict) else body
                rsp = _import_settings_payload(payload)
                _op_log("settings-import", f"ok={bool(rsp.get('ok'))}", ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                self._send_json(rsp, 200 if rsp.get("ok") else 400)
            elif path == "/api/settings/import/scan-data":
                body = self._read_json_body()
                payload = body.get("payload", body) if isinstance(body, dict) else body
                mode = str(body.get("mode") or "merge") if isinstance(body, dict) else "merge"
                rsp = _import_scan_data_payload(payload, mode=mode)
                _op_log("scan-data-import", f"mode={rsp.get('mode') or mode} ok={bool(rsp.get('ok'))}", ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                self._send_json(rsp, 200 if rsp.get("ok") else 400)
            elif path == "/api/tracks/clear":
                body = self._read_json_body()
                sn = str(body.get("sn") or "").strip()
                affected = clear_track_store(sn if sn else None)
                _op_log("track-clear", f"sn={sn or '*'} affected={affected}", ip=_client_ip_from_handler(self), ok=True)
                self._send_json({
                    "ok": True,
                    "sn": (sn or None),
                    "affected": int(affected),
                }, 200)
            elif path == "/api/tools/import/all":
                body = self._read_json_body()
                payload = body.get("payload", body) if isinstance(body, dict) else body
                valid_payload = False
                if isinstance(payload, list):
                    valid_payload = True
                elif isinstance(payload, dict):
                    valid_payload = isinstance(payload.get("items"), list) or isinstance(payload.get("drones"), list)
                if not valid_payload:
                    self._send_json({"ok": False, "error": "invalid payload: expect items[]/drones[] or list"}, 400)
                    return
                added, updated, skipped = import_details_payload(payload)
                _op_log("tools-import-all", f"added={added} updated={updated} skipped={skipped}", ip=_client_ip_from_handler(self), ok=True)
                self._send_json({
                    "ok": True,
                    "added": int(added),
                    "updated": int(updated),
                    "skipped": int(skipped),
                }, 200)
            elif path == "/api/tools/import/track":
                body = self._read_json_body()
                payload = body.get("payload", body) if isinstance(body, dict) else body
                if not isinstance(payload, dict):
                    self._send_json({"ok": False, "error": "payload must be object"}, 400)
                    return
                sn = str(payload.get("sn") or body.get("sn") or "").strip()
                if not sn:
                    self._send_json({"ok": False, "error": "sn required"}, 400)
                    return
                has_legacy_track = isinstance(payload.get("track"), list)
                has_dual_track = isinstance(payload.get("aircraft"), list) or isinstance(payload.get("operator"), list)
                if not has_legacy_track and not has_dual_track:
                    self._send_json({"ok": False, "error": "track or aircraft/operator array required"}, 400)
                    return
                tracks, track = _track_store_from_import_payload(
                    payload,
                    sn=sn,
                    uas_id=_uas_id_clean(payload.get("uas_id")),
                )
                count_aircraft = len(tracks.get("aircraft") or [])
                count_operator = len(tracks.get("operator") or [])
                count_total = count_aircraft + count_operator
                track_updated_wall_ts = None
                for track_type in ("aircraft", "operator"):
                    last = tracks.get(f"last_{track_type}")
                    if not isinstance(last, dict):
                        continue
                    last_ms = last.get("receive_time_ms") or last.get("timestamp_ms")
                    try:
                        wall_ts = float(last_ms) / 1000.0
                        if track_updated_wall_ts is None or wall_ts > track_updated_wall_ts:
                            track_updated_wall_ts = wall_ts
                    except Exception:
                        pass
                if track_updated_wall_ts is None:
                    track_updated_wall_ts = time.time()
                with state_lock:
                    h = history_table.get(sn) or {"sn": sn, "pkt_count_total": 0}
                    h["sn"] = sn
                    h["tracks"] = tracks
                    h["track"] = track
                    h["track_updated_wall_ts"] = track_updated_wall_ts
                    history_table[sn] = h
                    e = state_table.get(sn)
                    if isinstance(e, dict):
                        e["tracks"] = _sanitize_tracks(tracks)
                        e["track"] = list(track)
                        e["track_updated_wall_ts"] = h["track_updated_wall_ts"]
                    _history_mark_dirty()
                _op_log("tools-import-track", f"sn={sn} aircraft={count_aircraft} operator={count_operator}", ip=_client_ip_from_handler(self), ok=True)
                self._send_json({
                    "ok": True,
                    "sn": sn,
                    "count": len(track),
                    "count_aircraft": count_aircraft,
                    "count_operator": count_operator,
                    "count_total": count_total,
                    "tracks": tracks,
                }, 200)
            elif path == "/api/hw/op":
                body = self._read_json_body()
                op = str(body.get("op") or "").strip().lower()
                if not op:
                    self._send_json({"ok": False, "error": "op required"}, 400)
                    return
                try:
                    rsp = _hw_submit_task(body, timeout_sec=15)
                    code = 200 if rsp.get("ok") else 500
                    _op_log("hw-op", f"op={op} ok={rsp.get('ok')} iface={body.get('iface') or ''}", ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                    self._send_json(rsp, code)
                except Exception as e:
                    _op_log("hw-op", f"op={op} error={e}", ip=_client_ip_from_handler(self), ok=False)
                    self._send_json({"ok": False, "error": str(e)}, 500)
            elif path == "/api/admin/restart":
                body = self._read_json_body()
                if not bool(WEB_CFG.get("allow_restart", True)):
                    self._send_json({"ok": False, "error": "restart disabled"}, 403)
                    return
                args_text = str(body.get("args") or "")
                save_cfg = bool(body.get("save"))
                iface_override_raw = body.get("iface")
                iface_override = None if iface_override_raw in (None, "") else str(iface_override_raw).strip()
                scan_wifi_fast_override = body.get("scan_wifi_fast")
                try:
                    tokens, raw = _parse_restart_args_text(args_text)
                    if iface_override_raw is not None:
                        tokens = _merge_token_option(tokens, "--iface", iface_override)
                    if scan_wifi_fast_override is not None:
                        tokens = _merge_token_flag(tokens, "--scan-wifi-fast", _to_bool(scan_wifi_fast_override, False))
                    if save_cfg:
                        overrides: dict = {}
                        if iface_override_raw is not None:
                            overrides["iface"] = iface_override
                        if scan_wifi_fast_override is not None:
                            overrides["scan_wifi_fast"] = _to_bool(scan_wifi_fast_override, False)
                        ok, msg = _save_basic_config_from_tokens(
                            tokens,
                            raw_text=raw or args_text,
                            overrides=overrides,
                        )
                        if not ok:
                            self._send_json({"ok": False, "error": f"save config failed: {msg}"}, 400)
                            return
                    ok, msg = _schedule_self_restart(tokens)
                    if not ok:
                        _op_log("admin-restart", f"schedule_failed={msg}", ip=_client_ip_from_handler(self), ok=False)
                        self._send_json({"ok": False, "error": msg}, 409)
                        return
                    _op_log("admin-restart", f"save={save_cfg} args={tokens}", ip=_client_ip_from_handler(self), ok=True)
                    self._send_json({
                        "ok": True,
                        "restarting": True,
                        "save": save_cfg,
                        "args": tokens,
                    }, 200)
                except ValueError as e:
                    self._send_json({"ok": False, "error": str(e)}, 400)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
            elif path == "/api/config/save":
                if not self._require_raw_config_access():
                    return
                body = self._read_json_body()
                try:
                    rsp = _config_file_save_payload(str(body.get("path") or APP_CONFIG_PATH or ""), str(body.get("text") or ""), tag="config")
                    self._send_json(rsp, 200)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 400)
            elif path == "/api/settings/visual/test":
                body = self._read_json_body()
                rsp = _save_visual_settings(body, test_only=True)
                _op_log("settings-test", str(rsp.get("error") or rsp.get("reload_msg") or ""), ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                self._send_json(rsp, 200 if rsp.get("ok") else 400)
            elif path == "/api/settings/visual/save":
                body = self._read_json_body()
                rsp = _save_visual_settings(body, test_only=False)
                _op_log("settings-save", str(rsp.get("error") or rsp.get("backup_path") or ""), ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                self._send_json(rsp, 200 if rsp.get("ok") else 400)
            elif path == "/api/settings/raw/save":
                if not self._require_raw_config_access():
                    return
                body = self._read_json_body()
                try:
                    rsp = _config_file_save_payload(str(body.get("path") or APP_CONFIG_PATH or ""), str(body.get("text") or ""), tag="raw")
                    self._send_json(rsp, 200)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 400)
            elif path == "/api/config/file/delete":
                if not self._require_raw_config_access():
                    return
                body = self._read_json_body()
                try:
                    rsp = _config_file_delete_payload(str(body.get("path") or ""))
                    self._send_json(rsp, 200)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 400)
            elif path == "/api/settings/passkey/start":
                if not self._require_page_api():
                    return
                body = self._read_json_body()
                rsp = _passkey_register_begin(body, self.headers, client_ip=_client_ip_from_handler(self))
                code = 200
                if isinstance(rsp, tuple):
                    payload, code = rsp
                    self._send_json(payload, code)
                else:
                    code = 200 if rsp.get("ok") else 400
                    self._send_json(rsp, code)
            elif path == "/api/settings/passkey/finish":
                if not self._require_page_api():
                    return
                body = self._read_json_body()
                rsp, code = _passkey_finish_register(body, self.headers, client_ip=_client_ip_from_handler(self))
                self._send_json(rsp, code)
            elif path == "/api/settings/passkey/delete":
                if not self._require_page_api():
                    return
                body = self._read_json_body()
                passkey_id = str(body.get("id") or "").strip()
                if not passkey_id:
                    self._send_json({"ok": False, "error": "id required"}, 400)
                    return
                def _remove_passkey(items):
                    return [x for x in items if str((x or {}).get("id") or "") != passkey_id]
                ok, msg, passkeys = _auth_mutate_passkeys(_remove_passkey, tag="passkey_delete")
                if not ok:
                    self._send_json({"ok": False, "error": msg, "passkeys": passkeys}, 500)
                    return
                _op_log("passkey-delete", "id=" + passkey_id[:16], actor="-", ip=_client_ip_from_handler(self), ok=True)
                self._send_json({"ok": True, "passkeys": passkeys, "id": passkey_id}, 200)
                return
            elif path == "/api/settings/notify/test":
                body = self._read_json_body()
                ok, resp = send_test_notification_from_visual_payload(body)
                _op_log("notify-test", str(resp or ""), ip=_client_ip_from_handler(self), ok=bool(ok))
                self._send_json({
                    "ok": bool(ok),
                    "tested": True,
                    "saved": False,
                    "resp": resp,
                    "error": ("" if ok else str(resp or "notify test failed")),
                }, 200 if ok else 500)
            elif path == "/api/settings/models/update":
                body = self._read_json_body()
                rsp = update_model_map_from_url(manual=True, url_override=str(body.get("url") or "").strip() or None)
                self._send_json(rsp, 200 if rsp.get("ok") else 500)
            elif path == "/api/settings/app-update/check":
                self._read_json_body()
                rsp = _check_app_update_once(manual=True)
                self._send_json(rsp, 200 if rsp.get("ok") else 500)
            elif path == "/api/settings/app-update/download":
                self._read_json_body()
                rsp = _start_app_update_download(manual=True)
                _op_log("app-update-download", str(rsp.get("error") or rsp.get("message") or ""), ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                self._send_json(rsp, 200 if rsp.get("ok") else 500)
            elif path == "/api/settings/app-update/upload/prepare":
                body = self._read_json_body()
                file_name = str(body.get("file_name") or "").strip()
                try:
                    total_bytes = int(body.get("file_size") or 0)
                except Exception:
                    total_bytes = 0
                try:
                    _log(f"[INFO] app update upload prepare: name={file_name or '-'} bytes={total_bytes}")
                    rsp = _prepare_uploaded_app_update_package(file_name, total_bytes)
                    _op_log("app-update-upload-prepare", str((rsp.get("prepare") or {}).get("asset_name") or file_name), ip=_client_ip_from_handler(self), ok=True)
                    self._send_json(rsp, 200)
                except Exception as e:
                    _log(f"[WARN] app update upload prepare failed: name={file_name or '-'} bytes={total_bytes} error={e}")
                    _op_log("app-update-upload-prepare", f"error={e}", ip=_client_ip_from_handler(self), ok=False)
                    self._send_json({"ok": False, "error": str(e), "state": _app_update_status_payload()}, 400)
            elif path == "/api/settings/app-update/upload":
                file_name, body_len = self._read_binary_upload_info()
                upload_token = str(self.headers.get(APP_UPDATE_UPLOAD_TOKEN_HEADER) or "").strip()
                if not file_name:
                    self._send_json({"ok": False, "error": "upload file name missing"}, 400)
                    return
                try:
                    _log(f"[INFO] app update upload started: name={file_name} bytes={body_len}")
                    meta = _accept_uploaded_app_update_package(file_name, self.rfile, body_len, upload_token=upload_token)
                    rsp = {
                        "ok": True,
                        "message": f"{meta.get('asset_name') or file_name} 已上传并通过 SHA256 校验。",
                        "state": _app_update_status_payload(),
                    }
                    _log(f"[INFO] app update upload completed: name={meta.get('asset_name') or file_name} bytes={body_len} sha256={str(meta.get('sha256') or '')[:16]}")
                    _op_log("app-update-upload", str(meta.get("asset_name") or file_name), ip=_client_ip_from_handler(self), ok=True)
                    self._send_json(rsp, 200)
                except Exception as e:
                    _log(f"[WARN] app update upload failed: name={file_name} bytes={body_len} error={e}")
                    _op_log("app-update-upload", f"error={e}", ip=_client_ip_from_handler(self), ok=False)
                    self._send_json({"ok": False, "error": str(e), "state": _app_update_status_payload()}, 400)
            elif path == "/api/settings/app-update/start":
                body = self._read_json_body()
                if not bool(body.get("confirm")):
                    self._send_json({"ok": False, "error": "confirm required", "state": _app_update_status_payload()}, 400)
                    return
                rsp = _start_app_update_install(manual=True, sudo_password=_sudo_password_from_body(body))
                _op_log("app-update-start", str(rsp.get("error") or rsp.get("message") or ""), ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                code = 200 if rsp.get("ok") else 500
                if (not rsp.get("ok")) and (bool(rsp.get("need_sudo")) or "root" in str(rsp.get("error") or "") or "sudo" in str(rsp.get("error") or "") or "权限" in str(rsp.get("error") or "")):
                    code = 403
                self._send_json(rsp, code)
            elif path == "/api/network-bindings/save":
                body = self._read_json_body()
                rsp = _network_bindings_save_payload(body)
                _op_log("network-bindings-save", str(rsp.get("error") or rsp.get("reload_msg") or ""), ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                self._send_json(rsp, 200 if rsp.get("ok") else 400)
            elif path == "/api/network-bindings/apply":
                body = self._read_json_body()
                rsp = _network_bindings_apply_payload(body)
                _op_log("network-bindings-apply", str(rsp.get("error") or ""), ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                self._send_json(rsp, 200 if rsp.get("ok") else 500)
            elif path == "/api/settings/systemd/register":
                body = self._read_json_body()
                if not bool(body.get("confirm")):
                    self._send_json({"ok": False, "error": "confirm required", "status": _systemd_service_status_payload()}, 400)
                    return
                rsp = register_systemd_service(sudo_password=_sudo_password_from_body(body))
                _op_log("systemd-register", str(rsp.get("error") or rsp.get("message") or ""), ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                if rsp.get("ok"):
                    self._send_json(rsp, 200)
                else:
                    err = str(rsp.get("error") or "")
                    code = 403 if ("root" in err or "权限" in err) else 500
                    self._send_json(rsp, code)
            elif path == "/api/settings/iw/install":
                body = self._read_json_body()
                if not bool(body.get("confirm")):
                    self._send_json({"ok": False, "error": "confirm required", "status": _systemd_service_status_payload()}, 400)
                    return
                rsp = _install_iw_package(sudo_password=_sudo_password_from_body(body))
                status = _systemd_service_status_payload()
                payload = dict(rsp)
                payload["status"] = status
                payload["message"] = "无线工具已安装并可用。" if rsp.get("ok") else str(rsp.get("error") or "无线工具安装失败")
                _op_log("iw-install", payload.get("message") or "", ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                if rsp.get("ok"):
                    self._send_json(payload, 200)
                else:
                    err = str(rsp.get("error") or "")
                    code = 403 if ("root" in err or "权限" in err) else 500
                    self._send_json(payload, code)
            elif path == "/api/settings/security/repair":
                body = self._read_json_body()
                if not bool(body.get("confirm")):
                    self._send_json({"ok": False, "error": "confirm required", "status": _systemd_service_status_payload()}, 400)
                    return
                rsp = repair_runtime_security(sudo_password=_sudo_password_from_body(body))
                _op_log("security-repair", str(rsp.get("error") or rsp.get("message") or ""), ip=_client_ip_from_handler(self), ok=bool(rsp.get("ok")))
                if rsp.get("ok"):
                    self._send_json(rsp, 200)
                else:
                    err = str(rsp.get("error") or "")
                    code = 403 if ("root" in err or "权限" in err or "sudo" in err) else 500
                    self._send_json(rsp, code)
            elif path == "/api/settings/models/save":
                body = self._read_json_body()
                try:
                    rsp = save_model_map_entries(body.get("items") if isinstance(body, dict) else None)
                    self._send_json(rsp, 200 if rsp.get("ok") else 400)
                except Exception as e:
                    _op_log("model-map-save", f"error={e}", ip=_client_ip_from_handler(self), ok=False)
                    self._send_json({"ok": False, "error": str(e), "state": _model_update_status_payload()}, 400)
            elif path == "/api/settings/models/upsert":
                body = self._read_json_body()
                try:
                    rsp = upsert_model_map_entry(
                        prefix=str(body.get("prefix") or ""),
                        model=str(body.get("model") or ""),
                        sn=str(body.get("sn") or ""),
                    )
                    self._send_json(rsp, 200 if rsp.get("ok") else 400)
                except Exception as e:
                    _op_log("model-map-upsert", f"error={e}", ip=_client_ip_from_handler(self), ok=False)
                    self._send_json({"ok": False, "error": str(e), "state": _model_update_status_payload()}, 400)
            elif path == "/api/settings/api-token/create":
                body = self._read_json_body()
                ip = _client_ip_from_handler(self)
                subject = str(body.get("username") or "-") if body else "-"
                limited, retry_after = _rate_limited("api-token-create", ip, subject, limit=5, window_sec=300, block_sec=900)
                if limited:
                    self._rate_limit_fail(retry_after)
                    return
                payload, code = _build_api_token_create_payload(body, headers=self.headers, client_ip=ip)
                _rate_note("api-token-create", ip, subject, success=bool(payload.get("ok")), limit=5, window_sec=300, block_sec=900)
                self._send_json(payload, code)
            elif path == "/api/settings/api-token/delete":
                body = self._read_json_body()
                token_id = str(body.get("id") or "").strip()
                if not token_id:
                    self._send_json({"ok": False, "error": "id required"}, 400)
                    return
                def _remove_token(tokens):
                    return [x for x in tokens if str((x or {}).get("id") or "") != token_id]
                ok, msg, tokens = _api_mutate_tokens(_remove_token, tag="api_token_delete")
                if not ok:
                    self._send_json({"ok": False, "error": msg, "tokens": tokens}, 500)
                    return
                _op_log("api-token-delete", "id=" + token_id[:16], actor="-", ip=_client_ip_from_handler(self), ok=True)
                self._send_json({"ok": True, "deleted": True, "tokens": tokens}, 200)
            elif path == "/api/v1/auth/sso-links/create":
                body = self._read_json_body()
                ip = _client_ip_from_handler(self)
                payload, code = _build_sso_link_payload(body, require_reauth=False, headers=self.headers, client_ip=ip)
                if payload.get("ok"):
                    host = str(self.headers.get("Host") or "").strip()
                    scheme = "https" if str(self.headers.get("X-Forwarded-Proto") or "").lower() == "https" else "http"
                    path_url = str(payload.get("path") or "")
                    payload["url"] = (f"{scheme}://{host}{path_url}" if host and path_url else path_url)
                    _op_log("api-sso-create", "next=" + str(payload.get("next") or "/"), ip=ip, ok=True)
                self._send_json(payload, code)
            elif path == "/api/settings/login-link/create":
                body = self._read_json_body()
                ip = _client_ip_from_handler(self)
                subject = str(body.get("username") or "-") if body else "-"
                limited, retry_after = _rate_limited("login-link-create", ip, subject, limit=5, window_sec=300, block_sec=900)
                if limited:
                    self._rate_limit_fail(retry_after)
                    return
                payload, code = _build_sso_link_payload(body, require_reauth=True, headers=self.headers, client_ip=ip)
                if payload.get("ok"):
                    _rate_note("login-link-create", ip, subject, success=True, limit=5, window_sec=300, block_sec=900)
                    host = str(self.headers.get("Host") or "").strip()
                    scheme = "https" if str(self.headers.get("X-Forwarded-Proto") or "").lower() == "https" else "http"
                    path_url = str(payload.get("path") or "")
                    payload["url"] = (f"{scheme}://{host}{path_url}" if host and path_url else path_url)
                    _op_log("login-link-create", "sso next=" + str(payload.get("next") or "/"), actor=subject, ip=ip, ok=True)
                elif code == 401:
                    _rate_note("login-link-create", ip, subject, success=False, limit=5, window_sec=300, block_sec=900)
                self._send_json(payload, code)
            elif path == "/api/settings/login-link/delete":
                body = self._read_json_body()
                check = str(body.get("check") or "").strip()
                if not check:
                    self._send_json({"ok": False, "error": "check required"}, 400)
                    return
                def _remove_link(links):
                    return [x for x in links if str((x or {}).get("check") or "") != check]
                ok, msg, links = _auth_mutate_sso_links(_remove_link, tag="sso_delete")
                if not ok:
                    self._send_json({"ok": False, "error": msg, "links": links}, 500)
                    return
                _op_log("login-link-delete", "check=" + check[:12], actor="-", ip=_client_ip_from_handler(self), ok=True)
                self._send_json({"ok": True, "deleted": True, "links": links}, 200)
            elif path == "/api/web/base/save":
                body = self._read_json_body()
                if not APP_CONFIG_PATH:
                    self._send_json({"ok": False, "error": "config path missing"}, 500)
                    return
                base_name = str(body.get("base_name") or "基站").strip() or "基站"
                lat_raw = body.get("base_lat")
                lon_raw = body.get("base_lon")
                zoom_raw = body.get("base_zoom")
                heading_ref_raw = body.get("heading_ref_deg")
                map_idle_raw = body.get("map_auto_center_idle_sec")
                try:
                    base_lat = None if lat_raw in (None, "") else float(lat_raw)
                except Exception:
                    self._send_json({"ok": False, "error": "invalid base_lat"}, 400)
                    return
                try:
                    base_lon = None if lon_raw in (None, "") else float(lon_raw)
                except Exception:
                    self._send_json({"ok": False, "error": "invalid base_lon"}, 400)
                    return
                if (base_lat is None) != (base_lon is None):
                    self._send_json({"ok": False, "error": "base_lat/base_lon must be both set or both empty"}, 400)
                    return
                if base_lat is not None and not (-90.0 <= base_lat <= 90.0):
                    self._send_json({"ok": False, "error": "base_lat out of range [-90,90]"}, 400)
                    return
                if base_lon is not None and not (-180.0 <= base_lon <= 180.0):
                    self._send_json({"ok": False, "error": "base_lon out of range [-180,180]"}, 400)
                    return
                try:
                    base_zoom = int(zoom_raw if zoom_raw not in (None, "") else 13)
                except Exception:
                    base_zoom = 13
                base_zoom = max(3, min(30, base_zoom))
                try:
                    heading_ref_deg = float(heading_ref_raw if heading_ref_raw not in (None, "") else 0.0)
                except Exception:
                    self._send_json({"ok": False, "error": "invalid heading_ref_deg"}, 400)
                    return
                heading_ref_deg = heading_ref_deg % 360.0
                if heading_ref_deg < 0:
                    heading_ref_deg += 360.0
                try:
                    map_auto_center_idle_sec = int(map_idle_raw if map_idle_raw not in (None, "") else 20)
                except Exception:
                    self._send_json({"ok": False, "error": "invalid map_auto_center_idle_sec"}, 400)
                    return
                map_auto_center_idle_sec = max(5, min(600, map_auto_center_idle_sec))
                try:
                    cfg = load_app_config(APP_CONFIG_PATH)
                    web_cfg = cfg.get("web")
                    if not isinstance(web_cfg, dict):
                        web_cfg = {}
                    web_cfg["base_name"] = base_name
                    web_cfg["base_lat"] = base_lat
                    web_cfg["base_lon"] = base_lon
                    web_cfg["base_zoom"] = base_zoom
                    web_cfg["heading_ref_deg"] = round(float(heading_ref_deg), 2)
                    web_cfg["map_auto_center_idle_sec"] = int(map_auto_center_idle_sec)
                    cfg["web"] = web_cfg
                    b_ok, backup_path = create_config_backup(APP_CONFIG_PATH, tag="web-base")
                    if not b_ok:
                        self._send_json({"ok": False, "error": f"backup failed: {backup_path}"}, 500)
                        return
                    ok, msg = save_app_config(APP_CONFIG_PATH, cfg)
                    if not ok:
                        self._send_json({"ok": False, "error": f"save failed: {msg}"}, 500)
                        return
                    cfg_loaded = load_app_config(APP_CONFIG_PATH)
                    r_ok, r_msg = reload_runtime_config(cfg_loaded)
                    if not r_ok:
                        restore_config_backup(APP_CONFIG_PATH, backup_path)
                        self._send_json({"ok": False, "error": f"reload failed: {r_msg}", "backup_path": backup_path}, 500)
                        return
                    self._send_json({
                        "ok": True,
                        "saved_to": APP_CONFIG_PATH,
                        "backup_path": backup_path,
                        "reloaded": bool(r_ok),
                        "reload_msg": r_msg,
                        "base_name": str(WEB_CFG.get("base_name") or base_name),
                        "base_lat": WEB_CFG.get("base_lat"),
                        "base_lon": WEB_CFG.get("base_lon"),
                        "base_zoom": WEB_CFG.get("base_zoom"),
                        "heading_ref_deg": WEB_CFG.get("heading_ref_deg"),
                        "map_auto_center_idle_sec": WEB_CFG.get("map_auto_center_idle_sec"),
                    }, 200)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
            elif path == "/api/web/basic/save":
                body = self._read_json_body()
                if not APP_CONFIG_PATH:
                    self._send_json({"ok": False, "error": "config path missing"}, 500)
                    return
                iface_raw = body.get("iface")
                iface = None if iface_raw in (None, "") else str(iface_raw).strip()
                if not iface:
                    self._send_json({"ok": False, "error": "必须选择默认网卡"}, 400)
                    return
                safe_iface = _hw_safe_iface(iface)
                if not safe_iface:
                    self._send_json({"ok": False, "error": "invalid iface"}, 400)
                    return
                iface = safe_iface
                scan_wifi_fast = _to_bool(body.get("scan_wifi_fast"), False)
                try:
                    cfg = load_app_config(APP_CONFIG_PATH)
                    basic_cfg = cfg.get("basic")
                    if not isinstance(basic_cfg, dict):
                        basic_cfg = {}
                    basic_cfg["iface"] = iface
                    basic_cfg["scan_wifi_fast"] = bool(scan_wifi_fast)
                    cfg["basic"] = basic_cfg
                    b_ok, backup_path = create_config_backup(APP_CONFIG_PATH, tag="web-basic")
                    if not b_ok:
                        self._send_json({"ok": False, "error": f"backup failed: {backup_path}"}, 500)
                        return
                    ok, msg = save_app_config(APP_CONFIG_PATH, cfg)
                    if not ok:
                        self._send_json({"ok": False, "error": f"save failed: {msg}"}, 500)
                        return
                    cfg_loaded = load_app_config(APP_CONFIG_PATH)
                    r_ok, r_msg = reload_runtime_config(cfg_loaded)
                    if not r_ok:
                        restore_config_backup(APP_CONFIG_PATH, backup_path)
                        self._send_json({"ok": False, "error": f"reload failed: {r_msg}", "backup_path": backup_path}, 500)
                        return
                    basic_now = APP_CONFIG.get("basic") if isinstance(APP_CONFIG, dict) else {}
                    if not isinstance(basic_now, dict):
                        basic_now = {}
                    self._send_json({
                        "ok": True,
                        "saved_to": APP_CONFIG_PATH,
                        "backup_path": backup_path,
                        "reloaded": bool(r_ok),
                        "reload_msg": r_msg,
                        "iface_selected": (None if basic_now.get("iface") in (None, "") else str(basic_now.get("iface"))),
                        "scan_wifi_fast": bool(basic_now.get("scan_wifi_fast")),
                    }, 200)
                except Exception as e:
                    self._send_json({"ok": False, "error": str(e)}, 500)
            else:
                self._send_json({"ok": False, "error": "not found"}, 404)

        def log_message(self, *_): pass

    try:
        srv = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    except OSError as e:
        _log(f"[WARN] HTTP+WS start failed (port {HTTP_PORT} in use): {e}; continue sniff only")
        return

    _threading.Thread(target=_ws_push_loop, daemon=True).start()
    start_bound_http_servers(ThreadingHTTPServer, Handler)
    start_network_binding_services()
    _log(f"[INFO] HTTP+WS service started: http://0.0.0.0:{HTTP_PORT}/")
    if not _auth_enabled():
        _log("[WARN] Web auth disabled: Web UI is exposed to LAN; enable auth in config for safety")
    if not _api_token_enabled():
        _log("[INFO] API public mode disabled: /api/docs, /api/health and /api/v1/* stay page-session-only")
    try:
        srv.serve_forever()
    except Exception as e:
        _log(f"[WARN] HTTP+WS service exception: {e}")

# -----------------------------------------------------------------------------
# parse_frame
# -----------------------------------------------------------------------------
