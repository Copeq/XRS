"""app update core (extracted from process_core.py during backend module split).

Loaded into the assembled runtime namespace by runtime.py (see DEFAULT_CHUNK_FILES).
References to live state / track / history helpers resolve at call time.
"""

def _app_update_state_dir() -> str:
    if str(platform.system() or "").lower() == "linux":
        return os.path.join(RUNTIME_SERVICE_HOME, "app_update")
    return os.path.join(tempfile.gettempdir(), "xrs_app_update")

def _app_update_lock_path() -> str:
    return os.path.join(_app_update_state_dir(), "lock.json")

def _app_update_notice_path() -> str:
    return os.path.join(_app_update_state_dir(), "notice.json")

def _app_update_current_path() -> str:
    return os.path.join(_app_update_state_dir(), "current.json")

def _app_update_download_state_path() -> str:
    return os.path.join(_app_update_state_dir(), "download.json")

def _app_update_staged_meta_path() -> str:
    return os.path.join(_app_update_state_dir(), "staged.json")

def _app_update_stage_root() -> str:
    return os.path.join(tempfile.gettempdir(), "xrs_app_update_stage")

def _app_update_ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path

def _app_update_read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _app_update_write_json(path: str, payload: dict) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        _app_update_ensure_dir(parent)
    fd, tmp_path = tempfile.mkstemp(prefix="xrs-update-", suffix=".json", dir=parent or None)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload if isinstance(payload, dict) else {}, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

def _app_update_remove_file(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

def _app_update_pop_notice() -> dict:
    path = _app_update_notice_path()
    data = _app_update_read_json(path)
    if data:
        _app_update_remove_file(path)
    return data

def _app_update_persist_download_state(payload: dict) -> dict:
    merged = dict(payload if isinstance(payload, dict) else {})
    merged["updated_at"] = time.time()
    _app_update_write_json(_app_update_download_state_path(), merged)
    return merged

def _app_update_download_state() -> dict:
    return _app_update_read_json(_app_update_download_state_path())

def _app_update_update_runtime_state(payload: dict) -> None:
    if not isinstance(payload, dict):
        return
    with app_update_lock:
        APP_UPDATE_STATE.update(payload)

def _app_update_set_download_state(**payload) -> dict:
    state = _app_update_download_state()
    state.update(payload)
    persisted = _app_update_persist_download_state(state)
    runtime = {
        "download_running": bool(persisted.get("running")),
        "download_status": str(persisted.get("status") or ""),
        "download_message": str(persisted.get("message") or ""),
        "downloaded_bytes": int(persisted.get("downloaded_bytes") or 0),
        "download_total_bytes": int(persisted.get("download_total_bytes") or 0),
        "download_percent": float(persisted.get("download_percent") or 0.0),
        "last_error": str(persisted.get("last_error") or ""),
    }
    _app_update_update_runtime_state(runtime)
    return persisted

def _app_update_stage_meta() -> dict:
    return _app_update_read_json(_app_update_staged_meta_path())

def _app_update_write_stage_meta(payload: dict) -> dict:
    merged = dict(payload if isinstance(payload, dict) else {})
    merged["updated_at"] = time.time()
    _app_update_write_json(_app_update_staged_meta_path(), merged)
    _app_update_update_runtime_state({
        "staged_ready": bool(merged.get("ready")),
        "staged_source": str(merged.get("source") or ""),
        "staged_tag": str(merged.get("latest_tag") or ""),
        "staged_asset_name": str(merged.get("asset_name") or ""),
        "staged_sha256": str(merged.get("sha256") or ""),
        "staged_expected_sha256": str(merged.get("expected_sha256") or ""),
        "staged_verified": bool(merged.get("verified")),
        "staged_size": int(merged.get("size") or 0),
    })
    return merged

def _app_update_clear_stage_meta(remove_file: bool = True) -> None:
    if remove_file:
        _app_update_remove_file(_app_update_staged_meta_path())
    _app_update_update_runtime_state({
        "staged_ready": False,
        "staged_source": "",
        "staged_tag": "",
        "staged_asset_name": "",
        "staged_sha256": "",
        "staged_expected_sha256": "",
        "staged_verified": False,
        "staged_size": 0,
    })

def _app_update_upload_sessions_purge(now_ts: float | None = None) -> None:
    now = float(now_ts or time.time())
    with app_update_upload_lock:
        stale = [
            key
            for key, item in app_update_upload_sessions.items()
            if now >= float((item or {}).get("expires_at") or 0.0)
        ]
        for key in stale:
            app_update_upload_sessions.pop(key, None)

def _app_update_upload_session_create(file_name: str, total_bytes: int) -> dict:
    safe_name = _app_update_safe_filename(file_name)
    size = int(total_bytes or 0)
    if size <= 0:
        raise ValueError("empty upload")
    if size > APP_UPDATE_MAX_BYTES:
        raise ValueError(f"upload too large (>{APP_UPDATE_MAX_BYTES} bytes)")
    release_url = str(APP_UPDATE_CFG.get("release_url") or APP_UPDATE_RELEASE_URL_DEFAULT)
    release = _fetch_latest_release(release_url)
    support = _app_update_runtime_support()
    asset = _pick_release_asset(release.get("assets") or [], str(support.get("target_arch") or ""))
    if not asset:
        raise ValueError("latest release has no matching asset for this architecture")
    digest = _app_update_normalize_digest(asset.get("digest") or "")
    force_update = bool(APP_UPDATE_CFG.get("force_update"))
    if not digest and not force_update:
        raise ValueError("GitHub release asset digest is missing")
    if not safe_name:
        safe_name = _app_update_safe_filename(str(asset.get("name") or "")) or "package.bin"
    token = secrets.token_urlsafe(24)
    payload = {
        "token": token,
        "expires_at": time.time() + float(APP_UPDATE_UPLOAD_SESSION_TTL_SEC),
        "latest_tag": str(release.get("tag_name") or ""),
        "latest_commit": str(release.get("target_commitish") or ""),
        "asset": dict(asset),
        "release": {
            "tag_name": str(release.get("tag_name") or ""),
            "target_commitish": str(release.get("target_commitish") or ""),
            "html_url": str(release.get("html_url") or ""),
            "published_at": str(release.get("published_at") or ""),
        },
    }
    _app_update_upload_sessions_purge()
    with app_update_upload_lock:
        app_update_upload_sessions[token] = payload
    return {
        "token": token,
        "asset_name": str(asset.get("name") or safe_name),
        "expected_sha256": digest,
        "latest_tag": str(release.get("tag_name") or ""),
        "latest_commit": str(release.get("target_commitish") or ""),
        "release_url": str(release.get("html_url") or ""),
        "expires_at": float(payload.get("expires_at") or 0.0),
    }

def _app_update_upload_session_get(token: str) -> dict:
    raw_token = str(token or "").strip()
    if not raw_token:
        return {}
    _app_update_upload_sessions_purge()
    with app_update_upload_lock:
        payload = dict(app_update_upload_sessions.get(raw_token) or {})
    if not payload:
        raise ValueError("upload session expired, please reselect the package")
    return payload

def _app_update_upload_session_remove(token: str) -> None:
    raw_token = str(token or "").strip()
    if not raw_token:
        return
    with app_update_upload_lock:
        app_update_upload_sessions.pop(raw_token, None)

def _discard_upload_stream(body_stream, total_bytes: int) -> None:
    remain = max(0, int(total_bytes or 0))
    while remain > 0:
        chunk = body_stream.read(min(1024 * 512, remain))
        if not chunk:
            break
        remain -= len(chunk)

def _app_update_requires_sudo() -> bool:
    try:
        return hasattr(os, "geteuid") and int(os.geteuid()) != 0
    except Exception:
        return False

def _app_update_sudo_blocked_reason(raw_error: str = "") -> str:
    text = str(raw_error or "").strip()
    if text:
        lower = text.lower()
        if "unable to change to root gid" in lower or "sudoers_audit" in lower:
            return (
                "当前服务进程无法执行 sudo 提权：systemd 权限边界阻止切换到 root。"
                "请通过 SSH/root 执行安装或使用同步部署。原始错误: " + text
            )
        return "sudo 提权不可用: " + text
    return (
        "当前服务进程无法执行 sudo 提权。"
        "如果服务以 rid 用户并带 CapabilityBoundingSet 运行，请通过 SSH/root 执行安装或使用同步部署。"
    )

def _app_update_can_elevate() -> bool:
    if not _app_update_requires_sudo():
        return True
    try:
        return bool(_can_run_privileged_actions())
    except Exception:
        return False

def _app_update_normalize_digest(text: str) -> str:
    raw = str(text or "").strip().lower()
    if raw.startswith("sha256:"):
        raw = raw.split(":", 1)[1].strip()
    return raw if re.fullmatch(r"[0-9a-f]{64}", raw or "") else ""

def _app_update_file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().lower()

def _app_update_safe_filename(name: str) -> str:
    base = os.path.basename(str(name or "").strip())
    safe = re.sub(r"[^0-9A-Za-z._-]+", "_", base)[:160]
    if not safe or safe in (".", ".."):
        raise ValueError("invalid file name")
    return safe

def _app_update_prepare_stage_dir(prefix: str) -> str:
    root = _app_update_ensure_dir(_app_update_stage_root())
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe_prefix = re.sub(r"[^0-9A-Za-z._-]+", "_", str(prefix or "pkg"))[:40] or "pkg"
    return tempfile.mkdtemp(prefix=f"{safe_prefix}_{stamp}_", dir=root)

def _app_update_cleanup_stage_meta(meta: dict | None) -> None:
    if not isinstance(meta, dict):
        return
    try:
        file_path = os.path.abspath(str(meta.get("file_path") or ""))
        stage_dir = os.path.abspath(str(meta.get("stage_dir") or ""))
        if file_path and os.path.isfile(file_path):
            os.remove(file_path)
        if stage_dir and os.path.isdir(stage_dir):
            shutil.rmtree(stage_dir, ignore_errors=True)
    except Exception:
        pass

def _app_update_valid_stage_meta() -> dict:
    meta = _app_update_stage_meta()
    if not meta:
        return {}
    file_path = os.path.abspath(str(meta.get("file_path") or ""))
    if not file_path or not os.path.isfile(file_path):
        _app_update_clear_stage_meta(remove_file=True)
        return {}
    return meta

def _app_update_register_staged_package(
    *,
    source: str,
    file_path: str,
    stage_dir: str,
    release: dict,
    asset: dict,
    sha256_hex: str,
    size: int,
    verified: bool = True,
) -> dict:
    previous = _app_update_valid_stage_meta()
    if previous:
        _app_update_cleanup_stage_meta(previous)
    meta = {
        "ready": True,
        "source": str(source or ""),
        "file_path": os.path.abspath(str(file_path or "")),
        "stage_dir": os.path.abspath(str(stage_dir or "")),
        "latest_tag": str((release or {}).get("tag_name") or ""),
        "latest_commit": str((release or {}).get("target_commitish") or ""),
        "asset_name": str((asset or {}).get("name") or ""),
        "asset_url": str((asset or {}).get("url") or ""),
        "expected_sha256": _app_update_normalize_digest((asset or {}).get("digest") or ""),
        "sha256": _app_update_normalize_digest(sha256_hex or ""),
        "verified": bool(verified),
        "size": int(size or 0),
        "prepared_at": time.time(),
    }
    return _app_update_write_stage_meta(meta)

def _app_update_stage_install_plan(stage_meta: dict, state: dict, manual: bool) -> dict:
    return {
        "version": 1,
        "requested_at": time.time(),
        "requested_by": "manual" if manual else "auto",
        "latest_tag": str(stage_meta.get("latest_tag") or ""),
        "latest_commit": str(stage_meta.get("latest_commit") or ""),
        "current_tag": str((state or {}).get("current_tag") or ""),
        "current_commit": str((state or {}).get("current_commit") or ""),
        "target_arch": str((state or {}).get("target_arch") or ""),
        "target_path": str(_app_update_runtime_support().get("target_path") or ""),
        "asset_name": str(stage_meta.get("asset_name") or ""),
        "asset_url": str(stage_meta.get("asset_url") or ""),
        "download_path": os.path.abspath(str(stage_meta.get("file_path") or "")),
        "stage_dir": os.path.abspath(str(stage_meta.get("stage_dir") or "")),
        "response_grace_sec": 2,
        "package_source": str(stage_meta.get("source") or ""),
        "package_sha256": str(stage_meta.get("sha256") or ""),
        "package_expected_sha256": str(stage_meta.get("expected_sha256") or ""),
    }

def _app_update_download_worker(release_url: str) -> None:
    stage_dir = ""
    download_path = ""
    try:
        release = _fetch_latest_release(release_url)
        support = _app_update_runtime_support()
        asset = _pick_release_asset(release.get("assets") or [], str(support.get("target_arch") or ""))
        if not asset:
            raise RuntimeError("latest release has no matching asset for this architecture")
        digest = _app_update_normalize_digest(asset.get("digest") or "")
        force_update = bool(APP_UPDATE_CFG.get("force_update"))
        if not digest and not force_update:
            raise RuntimeError("GitHub release asset digest is missing")
        stage_dir = _app_update_prepare_stage_dir(str(release.get("tag_name") or "download"))
        download_path = os.path.join(stage_dir, str(asset.get("name") or "package.bin"))
        total_size = int(asset.get("size") or 0)
        _app_update_set_download_state(
            running=True,
            status="downloading",
            message=f"downloading {asset.get('name') or 'package'}",
            downloaded_bytes=0,
            download_total_bytes=total_size,
            download_percent=0.0,
            latest_tag=str(release.get("tag_name") or ""),
            asset_name=str(asset.get("name") or ""),
            last_error="",
        )
        h = hashlib.sha256()
        downloaded = 0
        last_update = 0.0
        with _app_update_http_open(
            str(asset.get("url") or ""),
            headers={"User-Agent": APP_HTTP_USER_AGENT + " (+asset download)"},
            timeout=30,
        ) as resp, open(download_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 512)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                downloaded += len(chunk)
                now = time.time()
                if (now - last_update) >= 0.5:
                    percent = (downloaded * 100.0 / total_size) if total_size > 0 else 0.0
                    _app_update_set_download_state(
                        running=True,
                        status="downloading",
                        message=f"downloading {asset.get('name') or 'package'}",
                        downloaded_bytes=downloaded,
                        download_total_bytes=total_size,
                        download_percent=percent,
                        latest_tag=str(release.get("tag_name") or ""),
                        asset_name=str(asset.get("name") or ""),
                        last_error="",
                    )
                    last_update = now
        actual_digest = h.hexdigest().lower()
        verified = bool(digest and actual_digest == digest)
        if not verified and not force_update:
            raise RuntimeError("downloaded package SHA256 does not match GitHub asset digest")
        meta = _app_update_register_staged_package(
            source="download",
            file_path=download_path,
            stage_dir=stage_dir,
            release=release,
            asset=asset,
            sha256_hex=actual_digest,
            size=os.path.getsize(download_path),
            verified=verified,
        )
        _app_update_set_download_state(
            running=False,
            status="completed" if verified else "completed_unverified",
            message=(f"downloaded and verified {meta.get('asset_name') or 'package'}" if verified else f"downloaded without valid SHA256: {meta.get('asset_name') or 'package'}"),
            downloaded_bytes=int(meta.get("size") or 0),
            download_total_bytes=int(meta.get("size") or 0),
            download_percent=100.0,
            latest_tag=str(meta.get("latest_tag") or ""),
            asset_name=str(meta.get("asset_name") or ""),
            last_error="",
        )
        _app_update_write_notice({
            "kind": "ok",
            "title": "安装包已就绪",
            "text": (f"{meta.get('asset_name') or '安装包'} 已下载并通过 SHA256 校验，可开始更新。" if verified else f"{meta.get('asset_name') or '安装包'} 已下载，但未通过 SHA256 校验；已按强制更新设置允许继续。"),
            "tag": str(meta.get("latest_tag") or ""),
            "asset_name": str(meta.get("asset_name") or ""),
        })
    except Exception as e:
        _app_update_set_download_state(
            running=False,
            status="failed",
            message=str(e),
            last_error=str(e),
        )
        try:
            if download_path and os.path.isfile(download_path):
                os.remove(download_path)
            if stage_dir and os.path.isdir(stage_dir):
                shutil.rmtree(stage_dir, ignore_errors=True)
        except Exception:
            pass

def _start_app_update_download(manual: bool = False) -> dict:
    state = _app_update_status_payload()
    if bool(state.get("download_running")):
        return {"ok": False, "error": "下载任务已经在运行", "state": state}
    if bool(state.get("installing")):
        return {"ok": False, "error": "更新安装流程正在运行", "state": state}
    if not bool(state.get("install_supported")):
        return {"ok": False, "error": str(state.get("support_reason") or "当前运行模式不支持自动更新"), "state": state}
    if not bool(state.get("update_available")):
        check_rsp = _check_app_update_once(manual=manual, auto_apply=False)
        state = dict(check_rsp.get("state") or {})
        if not check_rsp.get("ok"):
            return check_rsp
        if not bool(state.get("update_available")):
            return {"ok": False, "error": "当前没有可下载的新版本", "state": state}
    _app_update_clear_stage_meta(remove_file=True)
    release_url = str(APP_UPDATE_CFG.get("release_url") or APP_UPDATE_RELEASE_URL_DEFAULT)
    _app_update_set_download_state(
        running=True,
        status="queued",
        message="download task queued",
        downloaded_bytes=0,
        download_total_bytes=0,
        download_percent=0.0,
        latest_tag=str(state.get("latest_tag") or ""),
        asset_name=str(state.get("asset_name") or ""),
        last_error="",
    )
    Thread(target=lambda: _app_update_download_worker(release_url), daemon=True).start()
    return {
        "ok": True,
        "message": "下载任务已开始，离开页面后仍会继续。",
        "state": _app_update_status_payload(),
    }

def _prepare_uploaded_app_update_package(file_name: str, total_bytes: int) -> dict:
    info = _app_update_upload_session_create(file_name, total_bytes)
    return {
        "ok": True,
        "prepare": info,
        "message": f"ready to upload {info.get('asset_name') or _app_update_safe_filename(file_name)}",
        "state": _app_update_status_payload(),
    }

def _accept_uploaded_app_update_package(file_name: str, body_stream, total_bytes: int, upload_token: str = "") -> dict:
    safe_name = _app_update_safe_filename(file_name)
    if int(total_bytes or 0) <= 0:
        raise ValueError("empty upload")
    if int(total_bytes) > APP_UPDATE_MAX_BYTES:
        raise ValueError(f"upload too large (>{APP_UPDATE_MAX_BYTES} bytes)")
    session = _app_update_upload_session_get(upload_token) if upload_token else {}
    if session:
        release = dict(session.get("release") or {})
        asset = dict(session.get("asset") or {})
    else:
        release_url = str(APP_UPDATE_CFG.get("release_url") or APP_UPDATE_RELEASE_URL_DEFAULT)
        release = _fetch_latest_release(release_url)
        support = _app_update_runtime_support()
        asset = _pick_release_asset(release.get("assets") or [], str(support.get("target_arch") or ""))
        if not asset:
            raise ValueError("latest release has no matching asset for this architecture")
    digest = _app_update_normalize_digest(asset.get("digest") or "")
    force_update = bool(APP_UPDATE_CFG.get("force_update"))
    if not digest and not force_update:
        raise ValueError("GitHub release asset digest is missing")
    asset_file_name = _app_update_safe_filename(str(asset.get("name") or "")) or safe_name or "package.bin"
    stage_dir = _app_update_prepare_stage_dir(str(release.get("tag_name") or "upload"))
    file_path = os.path.join(stage_dir, asset_file_name)
    h = hashlib.sha256()
    written = 0
    try:
        with open(file_path, "wb") as f:
            remain = int(total_bytes)
            while remain > 0:
                chunk = body_stream.read(min(1024 * 512, remain))
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                written += len(chunk)
                remain -= len(chunk)
        if written != int(total_bytes):
            raise ValueError("upload truncated before all bytes were received")
        actual_digest = h.hexdigest().lower()
        verified = bool(digest and actual_digest == digest)
        if not verified and not force_update:
            raise ValueError("uploaded package SHA256 does not match GitHub asset digest")
        meta = _app_update_register_staged_package(
            source="upload",
            file_path=file_path,
            stage_dir=stage_dir,
            release=release,
            asset=asset,
            sha256_hex=actual_digest,
            size=written,
            verified=verified,
        )
        _app_update_set_download_state(
            running=False,
            status="uploaded" if verified else "uploaded_unverified",
            message=(f"uploaded and verified {meta.get('asset_name') or safe_name}" if verified else f"uploaded without valid SHA256: {meta.get('asset_name') or safe_name}"),
            downloaded_bytes=written,
            download_total_bytes=written,
            download_percent=100.0,
            latest_tag=str(meta.get("latest_tag") or ""),
            asset_name=str(meta.get("asset_name") or ""),
            last_error="",
        )
        _app_update_upload_session_remove(upload_token)
        return meta
    except Exception:
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
            if os.path.isdir(stage_dir):
                shutil.rmtree(stage_dir, ignore_errors=True)
        except Exception:
            pass
        raise

def _local_git_tag() -> str:
    repo = _app_root_dir()
    try:
        proc = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode == 0:
            return str((proc.stdout or "").strip())
    except Exception:
        pass
    return ""

def _local_git_commit() -> str:
    repo = _app_root_dir()
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode == 0:
            commit = (proc.stdout or "").strip()
            if re.fullmatch(r"[0-9a-fA-F]{40}", commit or ""):
                return commit.lower()
    except Exception:
        pass
    return ""

def _local_app_commit() -> str:
    commit = _local_git_commit()
    if commit:
        return commit
    commit = str(_load_build_info().get("commit") or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{7,40}", commit or ""):
        return commit.lower()
    return ""

def _local_app_tag() -> str:
    tag = _local_git_tag()
    if tag:
        return tag
    info = _load_build_info()
    tag = str(info.get("release_tag") or info.get("tag") or "").strip()
    if tag:
        return tag
    tag = str(_app_update_read_json(_app_update_current_path()).get("installed_tag") or "").strip()
    if tag:
        return tag
    return f"v{APP_RELEASE_VERSION}"

def _normalize_commit_ref(text: str) -> str:
    raw = str(text or "").strip().lower()
    return raw if re.fullmatch(r"[0-9a-f]{7,40}", raw or "") else ""

def _app_update_available(current_tag: str, latest_tag: str, current_commit: str, latest_commit: str) -> bool:
    cur_tag = str(current_tag or "").strip()
    new_tag = str(latest_tag or "").strip()
    if cur_tag and new_tag:
        return cur_tag != new_tag
    cur_commit = _normalize_commit_ref(current_commit)
    new_commit = _normalize_commit_ref(latest_commit)
    if cur_commit and new_commit:
        return cur_commit != new_commit
    return False

def _fallback_private_commit() -> str:
    try:
        path = os.path.abspath(_runtime_entrypoint_path())
        st = os.stat(path)
        raw = f"{path}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8", errors="replace")
        return hashlib.sha256(raw).hexdigest()[:7]
    except Exception:
        return "local"

def _app_version_label() -> str:
    info = _load_build_info()
    commit = _local_app_commit()
    tag = _local_app_tag()
    try:
        build = int(info.get("build") or 0)
    except Exception:
        build = 0
    if not commit:
        commit = _fallback_private_commit()
    if build <= 0:
        try:
            build = int(os.stat(os.path.abspath(_runtime_entrypoint_path())).st_mtime)
        except Exception:
            build = int(time.time())
    return f"{tag} commit:{commit}#{build}"

def _short_commit(commit: str) -> str:
    text = str(commit or "").strip()
    return text[:12] if text else ""

def _app_update_target_arch() -> str:
    machine = ""
    try:
        if hasattr(os, "uname"):
            machine = str(os.uname().machine or "")
    except Exception:
        machine = ""
    if not machine:
        machine = str(platform.machine() or "")
    aliases = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "x64": "x86_64",
        "i386": "x32",
        "i686": "x32",
        "x86": "x32",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv7l": "armv7",
        "armv7": "armv7",
        "armhf": "armv7",
        "arm": "armv7",
    }
    return aliases.get(str(machine or "").strip().lower(), "")

def _app_update_runtime_support() -> dict:
    if str(platform.system() or "").lower() != "linux":
        return {"supported": False, "reason": "自动更新仅支持 Linux systemd 部署。", "target_arch": "", "target_path": ""}
    if not _command_path("systemctl"):
        return {"supported": False, "reason": "未检测到 systemctl，无法自动更新 systemd 服务。", "target_arch": "", "target_path": ""}
    target_arch = _app_update_target_arch()
    if not target_arch:
        return {"supported": False, "reason": "未识别当前系统架构，无法匹配 GitHub Release 资产。", "target_arch": "", "target_path": ""}
    if not getattr(sys, "frozen", False):
        return {"supported": False, "reason": "当前为源码/Python 运行模式；自动更新仅支持单文件发布版。", "target_arch": target_arch, "target_path": ""}
    target_path = os.path.abspath(sys.executable or _runtime_entrypoint_path())
    if not os.path.isfile(target_path):
        return {"supported": False, "reason": "当前可执行文件路径无效，无法执行替换。", "target_arch": target_arch, "target_path": target_path}
    return {"supported": True, "reason": "", "target_arch": target_arch, "target_path": target_path}

def _app_update_mirror_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return raw
    mirror = str(APP_UPDATE_CFG.get("mirror") or "github").strip().lower()
    if mirror == "github":
        return raw
    if mirror == "gh-proxy":
        return raw if raw.startswith(GITHUB_PROXY_PREFIX) else (GITHUB_PROXY_PREFIX + raw)
    if mirror == "custom":
        base = str(APP_UPDATE_CFG.get("custom_mirror") or "").strip()
        if not base:
            return raw
        if "{url}" in base:
            return base.replace("{url}", raw)
        if "{encoded_url}" in base:
            return base.replace("{encoded_url}", urllib.parse.quote(raw, safe=""))
        return base.rstrip("/") + "/" + raw
    return raw

def _app_update_http_read(url: str, headers: dict | None = None, timeout: float = 12, max_bytes: int | None = None) -> bytes:
    final_url = _app_update_mirror_url(url)
    req = urllib.request.Request(final_url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if max_bytes is None or max_bytes <= 0:
            return resp.read()
        return resp.read(max_bytes + 1)[:max_bytes]

def _app_update_http_open(url: str, headers: dict | None = None, timeout: float = 30):
    final_url = _app_update_mirror_url(url)
    req = urllib.request.Request(final_url, headers=headers or {})
    return urllib.request.urlopen(req, timeout=timeout)

def _fetch_latest_release(release_url: str) -> dict:
    raw = _app_update_http_read(
        release_url,
        headers={
            "User-Agent": APP_HTTP_USER_AGENT + " (+release update)",
            "Accept": "application/vnd.github+json",
        },
        timeout=12,
        max_bytes=1024 * 1024,
    )
    data = json.loads(raw.decode("utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise RuntimeError("GitHub Release 响应无效")
    assets = data.get("assets")
    return {
        "tag_name": str(data.get("tag_name") or "").strip(),
        "name": str(data.get("name") or "").strip(),
        "target_commitish": str(data.get("target_commitish") or "").strip(),
        "html_url": str(data.get("html_url") or "").strip(),
        "published_at": str(data.get("published_at") or "").strip(),
        "assets": list(assets) if isinstance(assets, list) else [],
    }

def _pick_release_asset(assets: list[dict], target_arch: str) -> dict:
    expected = [
        f"xrs_station-linux-{target_arch}",
        f"xrs_station-{target_arch}",
    ]
    normalized: list[dict] = []
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("browser_download_url") or item.get("url") or "").strip()
        if not name or not url:
            continue
        normalized.append({
            "name": name,
            "url": url,
            "size": int(item.get("size") or 0),
            "content_type": str(item.get("content_type") or "").strip(),
            "digest": _app_update_normalize_digest(item.get("digest") or ""),
        })
    for candidate in expected:
        for item in normalized:
            if item["name"] == candidate:
                return item
    for candidate in expected:
        for item in normalized:
            if item["name"].endswith(candidate):
                return item
    return {}

def _app_update_download_asset(asset: dict, latest_tag: str) -> tuple[str, str]:
    name = str((asset or {}).get("name") or "").strip()
    url = str((asset or {}).get("url") or "").strip()
    if not name or not url:
        raise RuntimeError("未找到可下载的 Release 资产。")
    stage_root = _app_update_ensure_dir(_app_update_stage_root())
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe_tag = re.sub(r"[^0-9A-Za-z._-]+", "_", str(latest_tag or "latest"))[:40] or "latest"
    stage_dir = tempfile.mkdtemp(prefix=f"{safe_tag}_{stamp}_", dir=stage_root)
    download_path = os.path.join(stage_dir, name)
    with _app_update_http_open(
        url,
        headers={"User-Agent": APP_HTTP_USER_AGENT + " (+asset download)"},
        timeout=30,
    ) as resp, open(download_path, "wb") as f:
        shutil.copyfileobj(resp, f, length=1024 * 1024)
    return stage_dir, download_path

def _app_update_helper_command(plan_path: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [os.path.abspath(sys.executable or _runtime_entrypoint_path()), "--update-helper-plan", plan_path]
    return [os.path.abspath(sys.executable or "python3"), os.path.abspath(_runtime_entrypoint_path()), "--update-helper-plan", plan_path]

def _app_update_spawn_helper(plan_path: str, sudo_password: str | None = None) -> tuple[bool, str]:
    helper_cmd = _app_update_helper_command(plan_path)
    unit_name = f"xrs-update-{os.getpid()}-{int(time.time())}"
    systemd_run = _command_path("systemd-run")
    if not systemd_run:
        return False, "未检测到 systemd-run，无法创建独立更新进程。"
    args = [
        systemd_run,
        f"--unit={unit_name}",
        "--collect",
        "--property=Type=simple",
        "--same-dir",
        *helper_cmd,
    ]
    ok, out, _rc = _run_privileged(args, timeout=20, sudo_password=sudo_password)
    if not ok:
        return False, out or "启动更新进程失败"
    return True, unit_name

def _app_update_lock_state(payload: dict) -> dict:
    lock_path = _app_update_lock_path()
    current = _app_update_read_json(lock_path)
    merged = dict(current)
    merged.update(payload if isinstance(payload, dict) else {})
    merged["updated_at"] = time.time()
    _app_update_write_json(lock_path, merged)
    return merged

def _app_update_write_notice(payload: dict) -> None:
    notice = dict(payload if isinstance(payload, dict) else {})
    notice["id"] = str(notice.get("id") or f"update-{int(time.time())}")
    notice["ts"] = float(notice.get("ts") or time.time())
    _app_update_write_json(_app_update_notice_path(), notice)

def _app_update_status_payload(consume_notice: bool = False) -> dict:
    current_commit = _local_app_commit() or _fallback_private_commit()
    current_tag = _local_app_tag()
    with app_update_lock:
        cfg = dict(APP_UPDATE_CFG)
        state = dict(APP_UPDATE_STATE)
    support = _app_update_runtime_support()
    lock_state = _app_update_read_json(_app_update_lock_path())
    download_state = _app_update_download_state()
    stage_meta = _app_update_valid_stage_meta()
    if lock_state:
        status = str(lock_state.get("status") or "")
        state["installing"] = status not in ("", "completed", "failed", "rolled_back")
        state["install_status"] = status
        state["asset_name"] = str(lock_state.get("asset_name") or state.get("asset_name") or "")
        state["asset_url"] = str(lock_state.get("asset_url") or state.get("asset_url") or "")
        state["latest_tag"] = str(lock_state.get("latest_tag") or state.get("latest_tag") or "")
        state["latest_commit"] = str(lock_state.get("latest_commit") or state.get("latest_commit") or "")
        state["last_error"] = str(lock_state.get("last_error") or state.get("last_error") or "")
        state["install_message"] = str(lock_state.get("message") or "")
        state["helper_pid"] = int(lock_state.get("helper_pid") or 0)
        state["backup_path"] = str(lock_state.get("backup_path") or "")
        state["rolled_back"] = bool(lock_state.get("rolled_back"))
    else:
        state["installing"] = False
        state["install_status"] = ""
        state["install_message"] = ""
        state["helper_pid"] = 0
        state["backup_path"] = ""
        state["rolled_back"] = False
    state["download_running"] = bool(download_state.get("running"))
    state["download_status"] = str(download_state.get("status") or state.get("download_status") or "")
    state["download_message"] = str(download_state.get("message") or state.get("download_message") or "")
    state["downloaded_bytes"] = int(download_state.get("downloaded_bytes") or 0)
    state["download_total_bytes"] = int(download_state.get("download_total_bytes") or 0)
    state["download_percent"] = float(download_state.get("download_percent") or 0.0)
    if download_state.get("last_error"):
        state["last_error"] = str(download_state.get("last_error") or state.get("last_error") or "")
    state["staged_ready"] = bool(stage_meta.get("ready"))
    state["staged_source"] = str(stage_meta.get("source") or "")
    state["staged_tag"] = str(stage_meta.get("latest_tag") or "")
    state["staged_asset_name"] = str(stage_meta.get("asset_name") or "")
    state["staged_sha256"] = str(stage_meta.get("sha256") or "")
    state["staged_expected_sha256"] = str(stage_meta.get("expected_sha256") or "")
    state["staged_verified"] = bool(stage_meta.get("verified"))
    state["staged_size"] = int(stage_meta.get("size") or 0)
    requires_sudo = _app_update_requires_sudo()
    can_elevate = _app_update_can_elevate()
    state["requires_sudo"] = bool(requires_sudo)
    state["can_elevate"] = bool(can_elevate)
    state["sudo_blocked_reason"] = _app_update_sudo_blocked_reason() if requires_sudo and not can_elevate else ""
    state["current_commit"] = current_commit
    state["current_tag"] = current_tag
    state["current_short"] = _short_commit(current_commit)
    state["latest_short"] = _short_commit(state.get("latest_commit") or "")
    state["release_url"] = str(cfg.get("release_url") or APP_UPDATE_RELEASE_URL_DEFAULT)
    state["mirror"] = str(cfg.get("mirror") or "github")
    state["custom_mirror"] = str(cfg.get("custom_mirror") or "")
    state["force_update"] = bool(cfg.get("force_update"))
    state["mirror_url"] = _app_update_mirror_url(state["release_url"])
    state["mirror_options"] = list(APP_UPDATE_MIRROR_OPTIONS)
    state["max_upload_bytes"] = int(APP_UPDATE_MAX_BYTES)
    state["install_supported"] = bool(support.get("supported"))
    state["support_reason"] = str(support.get("reason") or "")
    state["target_arch"] = str(support.get("target_arch") or state.get("target_arch") or "")
    state["checked"] = bool(state.get("last_check_ts"))
    notice = _app_update_pop_notice() if consume_notice else {}
    if notice:
        state["completion_notice"] = notice
    return state

def _check_app_update_once(manual: bool = False, auto_apply: bool = False) -> dict:
    _ = auto_apply
    if not manual and not bool(APP_UPDATE_CFG.get("enabled", True)):
        return {"ok": True, "skipped": True, "state": _app_update_status_payload()}
    with app_update_lock:
        if bool(APP_UPDATE_STATE.get("running")):
            busy = True
        else:
            busy = False
            APP_UPDATE_STATE["running"] = True
            APP_UPDATE_STATE["last_error"] = ""
            release_url = str(APP_UPDATE_CFG.get("release_url") or APP_UPDATE_RELEASE_URL_DEFAULT)
    if busy:
        return {"ok": False, "error": "程序更新检查正在运行", "state": _app_update_status_payload()}
    try:
        release = _fetch_latest_release(release_url)
        latest_tag = str(release.get("tag_name") or "")
        latest_commit = str(release.get("target_commitish") or "")
        current_tag = _local_app_tag()
        current_commit = _local_app_commit() or _fallback_private_commit()
        support = _app_update_runtime_support()
        asset = _pick_release_asset(release.get("assets") or [], str(support.get("target_arch") or ""))
        update_available = _app_update_available(current_tag, latest_tag, current_commit, latest_commit)
        with app_update_lock:
            APP_UPDATE_STATE.update({
                "running": False,
                "last_check_ts": time.time(),
                "latest_tag": latest_tag,
                "latest_commit": latest_commit,
                "current_tag": current_tag,
                "current_commit": current_commit,
                "target_arch": str(support.get("target_arch") or ""),
                "asset_name": str(asset.get("name") or ""),
                "asset_url": str(asset.get("url") or ""),
                "install_supported": bool(support.get("supported")),
                "support_reason": str(support.get("reason") or ""),
                "update_available": update_available,
                "last_error": "",
            })
        if update_available:
            _log(
                "[INFO] 检测到程序更新: "
                f"local_tag={current_tag or '-'} latest_tag={latest_tag or '-'} "
                f"local_commit={_short_commit(current_commit)} latest_commit={_short_commit(latest_commit)}"
            )
        elif latest_tag or latest_commit:
            _log(
                "[INFO] 程序更新检查完成: "
                f"current_tag={current_tag or '-'} latest_tag={latest_tag or '-'} "
                f"current_commit={_short_commit(current_commit)} latest_commit={_short_commit(latest_commit)}"
            )
        return {"ok": True, "manual": bool(manual), "state": _app_update_status_payload()}
    except Exception as e:
        with app_update_lock:
            APP_UPDATE_STATE.update({
                "running": False,
                "last_check_ts": time.time(),
                "current_tag": _local_app_tag(),
                "current_commit": _local_app_commit() or _fallback_private_commit(),
                "last_error": str(e),
            })
        _log(f"[WARN] 程序更新检查失败: {e}")
        return {"ok": False, "error": str(e), "state": _app_update_status_payload()}

def _start_app_update_install(*, manual: bool = False, sudo_password: str | None = None) -> dict:
    state = _app_update_status_payload()
    if bool(state.get("installing")):
        return {"ok": False, "error": "更新流程已经在运行", "state": state}
    if not bool(state.get("install_supported")):
        return {"ok": False, "error": str(state.get("support_reason") or "当前运行模式不支持自动更新"), "state": state}
    if bool(state.get("download_running")):
        return {"ok": False, "error": "安装包仍在下载中，请等待校验完成", "state": state}
    stage_meta = _app_update_valid_stage_meta()
    if not stage_meta or not bool(stage_meta.get("ready")):
        return {"ok": False, "error": "请先下载或上传安装包", "state": _app_update_status_payload()}
    if not bool(stage_meta.get("verified")) and not bool(APP_UPDATE_CFG.get("force_update")):
        return {"ok": False, "error": "安装包未通过 SHA256 校验；如确认仍要继续，请在设置中启用强制更新", "state": _app_update_status_payload()}
    requires_sudo = _app_update_requires_sudo()
    if requires_sudo and not _app_update_can_elevate():
        reason = _app_update_sudo_blocked_reason()
        return {"ok": False, "error": reason, "need_sudo": False, "state": _app_update_status_payload()}
    if requires_sudo and not str(sudo_password or "").strip():
        return {"ok": False, "error": "sudo required", "need_sudo": True, "state": _app_update_status_payload()}
    if requires_sudo:
        ok_sudo, out_sudo, _rc_sudo = _run_privileged(["true"], timeout=8, sudo_password=sudo_password)
        if not ok_sudo:
            reason = _app_update_sudo_blocked_reason(out_sudo)
            return {"ok": False, "error": reason, "need_sudo": False, "state": _app_update_status_payload()}
    stage_dir = os.path.abspath(str(stage_meta.get("stage_dir") or ""))
    plan = _app_update_stage_install_plan(stage_meta, state, manual)
    plan_path = os.path.join(stage_dir, "plan.json")
    _app_update_write_json(plan_path, plan)
    _app_update_lock_state({
        "status": "scheduled",
        "requested_at": plan["requested_at"],
        "latest_tag": plan["latest_tag"],
        "latest_commit": plan["latest_commit"],
        "target_arch": plan["target_arch"],
        "target_path": plan["target_path"],
        "asset_name": plan["asset_name"],
        "asset_url": plan["asset_url"],
        "stage_dir": stage_dir,
        "download_path": plan["download_path"],
        "message": "已准备安装已校验的安装包，等待更新进程接管 systemd 服务。",
    })
    ok, helper_ref = _app_update_spawn_helper(plan_path, sudo_password=sudo_password)
    if not ok:
        _app_update_lock_state({"status": "failed", "last_error": helper_ref, "message": helper_ref})
        return {"ok": False, "error": helper_ref, "state": _app_update_status_payload()}
    with app_update_lock:
        APP_UPDATE_STATE["installing"] = True
        APP_UPDATE_STATE["install_status"] = "scheduled"
        APP_UPDATE_STATE["asset_name"] = str(stage_meta.get("asset_name") or "")
        APP_UPDATE_STATE["asset_url"] = str(stage_meta.get("asset_url") or "")
        APP_UPDATE_STATE["latest_tag"] = str(stage_meta.get("latest_tag") or "")
        APP_UPDATE_STATE["latest_commit"] = str(stage_meta.get("latest_commit") or "")
        APP_UPDATE_STATE["last_install_ts"] = time.time()
    _op_log("app-update-start", f"tag={plan['latest_tag']} asset={plan['asset_name']} helper={helper_ref}", ok=True)
    return {
        "ok": True,
        "message": "更新进程已启动，服务将短暂重启。",
        "helper": helper_ref,
        "restart_expected": True,
        "state": _app_update_status_payload(),
    }

def start_app_update_check() -> None:
    Thread(target=lambda: _check_app_update_once(auto_apply=False), daemon=True).start()

def _app_update_mark_startup_ready() -> None:
    lock = _app_update_read_json(_app_update_lock_path())
    if not lock:
        return
    target_path = os.path.abspath(str(lock.get("target_path") or ""))
    current_path = os.path.abspath(sys.executable or _runtime_entrypoint_path())
    status = str(lock.get("status") or "")
    if target_path and current_path != target_path:
        return
    if status not in ("scheduled", "installing", "starting", "waiting_start"):
        return
    _app_update_lock_state({
        "status": "activated",
        "activated_at": time.time(),
        "current_pid": os.getpid(),
        "message": "新版本已启动，等待更新进程收尾。",
    })
    _log("[INFO] 检测到更新锁，已标记新版本启动成功")

def _app_update_health_url() -> str:
    return f"http://127.0.0.1:{int(HTTP_PORT)}/api/update-health"

def _app_update_probe_health(timeout: float = 3.0) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(
            _app_update_health_url(),
            headers={
                "User-Agent": APP_HTTP_USER_AGENT + " (+update health)",
                UPDATE_PROBE_HEADER: UPDATE_PROBE_HEADER_VALUE,
            },
        )
        with urllib.request.urlopen(req, timeout=max(1.0, float(timeout or 0.0))) as resp:
            if int(getattr(resp, "status", 200) or 200) != 200:
                return False, f"http {getattr(resp, 'status', '?')}"
            payload = json.loads(resp.read(256 * 1024).decode("utf-8", errors="replace"))
        if not isinstance(payload, dict):
            return False, "invalid json payload"
        if not bool(payload.get("ok")):
            return False, str(payload.get("error") or "health payload not ok")
        return True, "ok"
    except urllib.error.HTTPError as e:
        return False, f"http {e.code}"
    except urllib.error.URLError as e:
        return False, str(getattr(e, "reason", None) or e)
    except socket.timeout:
        return False, "timeout"
    except Exception as e:
        return False, str(e)

def _app_update_restore_backup(target_path: str, backup_path: str) -> tuple[bool, str]:
    target_path = os.path.abspath(str(target_path or ""))
    backup_path = os.path.abspath(str(backup_path or ""))
    if not target_path or not backup_path:
        return False, "backup path missing"
    if not os.path.isfile(backup_path):
        return False, f"backup not found: {backup_path}"
    rollback_tmp = target_path + ".rollback"
    try:
        shutil.copy2(backup_path, rollback_tmp)
        try:
            os.chmod(rollback_tmp, 0o755)
        except Exception:
            pass
        os.replace(rollback_tmp, target_path)
        try:
            os.chmod(target_path, 0o755)
        except Exception:
            pass
        return True, backup_path
    except Exception as e:
        return False, str(e)
    finally:
        try:
            if os.path.exists(rollback_tmp):
                os.remove(rollback_tmp)
        except Exception:
            pass

def _app_update_wait_health(deadline: float, require_activation: bool = False) -> tuple[bool, str]:
    activated_seen = not require_activation
    last_error = "waiting for service health"
    while time.time() < deadline:
        time.sleep(1.0)
        lock = _app_update_read_json(_app_update_lock_path())
        status = str(lock.get("status") or "")
        if status == "failed":
            return False, str(lock.get("last_error") or "update helper marked failed")
        if status == "activated":
            activated_seen = True
        ok_health, health_msg = _app_update_probe_health(timeout=2.5)
        if activated_seen and ok_health:
            return True, "ok"
        last_error = health_msg if not ok_health else "waiting for startup activation"
    return False, last_error

def _app_update_rollback_after_failure(plan: dict, backup_path: str, failure_text: str) -> tuple[bool, str]:
    target_path = os.path.abspath(str(plan.get("target_path") or ""))
    latest_tag = str(plan.get("latest_tag") or "")
    asset_name = str(plan.get("asset_name") or "")
    _app_update_lock_state({
        "status": "rollback",
        "rolled_back": False,
        "backup_path": backup_path,
        "last_error": failure_text,
        "message": "new version health check failed, restoring backup",
    })
    _systemctl(["stop", SYSTEMD_SERVICE_NAME], timeout=30)
    ok_restore, restore_msg = _app_update_restore_backup(target_path, backup_path)
    if not ok_restore:
        return False, f"rollback restore failed: {restore_msg}"
    _app_update_lock_state({
        "status": "rollback",
        "rolled_back": False,
        "backup_path": backup_path,
        "last_error": failure_text,
        "message": "backup restored, restarting previous service",
    })
    ok_start, out_start, rc_start = _systemctl(["start", SYSTEMD_SERVICE_NAME], timeout=40)
    if not ok_start:
        return False, f"rollback start failed: rc={rc_start} {out_start}"
    ok_health, health_msg = _app_update_wait_health(time.time() + 90.0, require_activation=False)
    if not ok_health:
        return False, f"rollback health check failed: {health_msg}"
    _app_update_lock_state({
        "status": "rolled_back",
        "rolled_back": True,
        "backup_path": backup_path,
        "last_error": failure_text,
        "message": "update failed and the previous version has been restored",
        "rollback_at": time.time(),
    })
    _app_update_write_notice({
        "kind": "warn",
        "title": "更新已回退",
        "text": f"更新到 {latest_tag or asset_name or '新版本'} 失败，已自动恢复旧版本。",
        "tag": latest_tag,
        "asset_name": asset_name,
        "backup_path": backup_path,
        "error": failure_text,
        "rolled_back": True,
    })
    return True, "rolled back"

def _run_app_update_helper_legacy(plan_path: str) -> int:
    plan = _app_update_read_json(str(plan_path or ""))
    if not plan:
        print("update helper plan missing", file=sys.stderr)
        return 2
    lock_path = _app_update_lock_path()
    stage_dir = str(plan.get("stage_dir") or "")
    download_path = os.path.abspath(str(plan.get("download_path") or ""))
    target_path = os.path.abspath(str(plan.get("target_path") or ""))
    asset_name = str(plan.get("asset_name") or "")
    latest_tag = str(plan.get("latest_tag") or "")
    response_grace = max(1, int(plan.get("response_grace_sec") or 2))
    backup_path = ""
    try:
        _app_update_lock_state({
            "status": "installing",
            "helper_pid": os.getpid(),
            "asset_name": asset_name,
            "asset_url": str(plan.get("asset_url") or ""),
            "latest_tag": latest_tag,
            "latest_commit": str(plan.get("latest_commit") or ""),
            "target_arch": str(plan.get("target_arch") or ""),
            "target_path": target_path,
            "message": "更新进程已接管，准备停止服务。",
        })
        time.sleep(response_grace)
        ok_stop, out_stop, rc_stop = _systemctl(["stop", SYSTEMD_SERVICE_NAME], timeout=40)
        if not ok_stop:
            raise RuntimeError(f"停止 systemd 服务失败: rc={rc_stop} {out_stop}")
        _app_update_lock_state({"status": "installing", "message": "服务已停止，正在备份旧文件。"})
        if not os.path.isfile(download_path):
            raise RuntimeError("下载好的更新文件不存在。")
        if not os.path.isfile(target_path):
            raise RuntimeError("当前安装目标不存在，无法备份。")
        backup_dir = os.path.join(os.path.dirname(target_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(
            backup_dir,
            os.path.basename(target_path) + ".bak_" + time.strftime("%Y%m%d_%H%M%S"),
        )
        shutil.copy2(target_path, backup_path)
        staged_target = target_path + ".new"
        shutil.copy2(download_path, staged_target)
        os.chmod(staged_target, 0o755)
        os.replace(staged_target, target_path)
        try:
            os.chmod(target_path, 0o755)
        except Exception:
            pass
        _app_update_lock_state({
            "status": "starting",
            "backup_path": backup_path,
            "message": "新文件已替换，正在启动 systemd 服务。",
        })
        ok_start, out_start, rc_start = _systemctl(["start", SYSTEMD_SERVICE_NAME], timeout=40)
        if not ok_start:
            raise RuntimeError(f"启动 systemd 服务失败: rc={rc_start} {out_start}")
        deadline = time.time() + 120.0
        while time.time() < deadline:
            time.sleep(1.0)
            lock = _app_update_read_json(lock_path)
            status = str(lock.get("status") or "")
            if status == "activated":
                _app_update_write_json(_app_update_current_path(), {
                    "installed_tag": latest_tag,
                    "installed_commit": str(plan.get("latest_commit") or ""),
                    "asset_name": asset_name,
                    "target_arch": str(plan.get("target_arch") or ""),
                    "target_path": target_path,
                    "installed_at": time.time(),
                    "backup_path": backup_path,
                })
                _app_update_write_notice({
                    "kind": "ok",
                    "title": "更新完成",
                    "text": f"已升级到 {latest_tag or asset_name or '新版本'}。",
                    "tag": latest_tag,
                    "asset_name": asset_name,
                    "backup_path": backup_path,
                })
                _app_update_remove_file(lock_path)
                try:
                    if stage_dir and os.path.isdir(stage_dir):
                        shutil.rmtree(stage_dir, ignore_errors=True)
                except Exception:
                    pass
                return 0
            if status == "failed":
                raise RuntimeError(str(lock.get("last_error") or "更新流程失败"))
        raise RuntimeError("新版本启动确认超时，更新进程未收到启动握手。")
    except Exception as e:
        _app_update_lock_state({
            "status": "failed",
            "backup_path": backup_path,
            "last_error": str(e),
            "message": str(e),
        })
        print(str(e), file=sys.stderr)
        return 1

def _run_app_update_helper(plan_path: str) -> int:
    plan = _app_update_read_json(str(plan_path or ""))
    if not plan:
        print("update helper plan missing", file=sys.stderr)
        return 2
    lock_path = _app_update_lock_path()
    stage_dir = str(plan.get("stage_dir") or "")
    download_path = os.path.abspath(str(plan.get("download_path") or ""))
    target_path = os.path.abspath(str(plan.get("target_path") or ""))
    asset_name = str(plan.get("asset_name") or "")
    latest_tag = str(plan.get("latest_tag") or "")
    response_grace = max(1, int(plan.get("response_grace_sec") or 2))
    backup_path = ""
    try:
        _app_update_lock_state({
            "status": "installing",
            "helper_pid": os.getpid(),
            "asset_name": asset_name,
            "asset_url": str(plan.get("asset_url") or ""),
            "latest_tag": latest_tag,
            "latest_commit": str(plan.get("latest_commit") or ""),
            "target_arch": str(plan.get("target_arch") or ""),
            "target_path": target_path,
            "message": "update helper is taking over",
        })
        time.sleep(response_grace)
        ok_stop, out_stop, rc_stop = _systemctl(["stop", SYSTEMD_SERVICE_NAME], timeout=40)
        if not ok_stop:
            raise RuntimeError(f"failed to stop systemd service: rc={rc_stop} {out_stop}")
        _app_update_lock_state({"status": "installing", "message": "service stopped, backing up old binary"})
        if not os.path.isfile(download_path):
            raise RuntimeError("downloaded release asset is missing")
        if not os.path.isfile(target_path):
            raise RuntimeError("installed target is missing, cannot create backup")
        backup_dir = os.path.join(os.path.dirname(target_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(
            backup_dir,
            os.path.basename(target_path) + ".bak_" + time.strftime("%Y%m%d_%H%M%S"),
        )
        shutil.copy2(target_path, backup_path)
        staged_target = target_path + ".new"
        shutil.copy2(download_path, staged_target)
        os.chmod(staged_target, 0o755)
        os.replace(staged_target, target_path)
        try:
            os.chmod(target_path, 0o755)
        except Exception:
            pass
        _app_update_lock_state({
            "status": "starting",
            "backup_path": backup_path,
            "message": "new binary installed, restarting service",
        })
        ok_start, out_start, rc_start = _systemctl(["start", SYSTEMD_SERVICE_NAME], timeout=40)
        if not ok_start:
            raise RuntimeError(f"failed to start systemd service: rc={rc_start} {out_start}")
        ok_health, health_msg = _app_update_wait_health(time.time() + 120.0, require_activation=True)
        if not ok_health:
            raise RuntimeError(f"new version health check failed: {health_msg}")
        _app_update_write_json(_app_update_current_path(), {
            "installed_tag": latest_tag,
            "installed_commit": str(plan.get("latest_commit") or ""),
            "asset_name": asset_name,
            "target_arch": str(plan.get("target_arch") or ""),
            "target_path": target_path,
            "installed_at": time.time(),
            "backup_path": backup_path,
        })
        _app_update_write_notice({
            "kind": "ok",
            "title": "更新完成",
            "text": f"已升级到 {latest_tag or asset_name or '新版本'}。",
            "tag": latest_tag,
            "asset_name": asset_name,
            "backup_path": backup_path,
        })
        _app_update_remove_file(lock_path)
        try:
            if stage_dir and os.path.isdir(stage_dir):
                shutil.rmtree(stage_dir, ignore_errors=True)
        except Exception:
            pass
        return 0
    except Exception as e:
        err_text = str(e)
        rollback_ok = False
        rollback_msg = ""
        if backup_path:
            rollback_ok, rollback_msg = _app_update_rollback_after_failure(plan, backup_path, err_text)
        if rollback_ok:
            print(f"{err_text}; rolled back", file=sys.stderr)
            try:
                if stage_dir and os.path.isdir(stage_dir):
                    shutil.rmtree(stage_dir, ignore_errors=True)
            except Exception:
                pass
            return 0
        final_error = err_text if not rollback_msg else f"{err_text}; rollback failed: {rollback_msg}"
        _app_update_lock_state({
            "status": "failed",
            "rolled_back": False,
            "backup_path": backup_path,
            "last_error": final_error,
            "message": final_error,
        })
        _app_update_write_notice({
            "kind": "warn",
            "title": "更新失败",
            "text": final_error,
            "tag": latest_tag,
            "asset_name": asset_name,
            "backup_path": backup_path,
            "error": final_error,
        })
        print(final_error, file=sys.stderr)
        return 1
