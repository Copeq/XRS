from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys
from types import MappingProxyType
from typing import Any


DEFAULT_CHUNK_FILES: tuple[str, ...] = (
    "common_core.py",
    "track_store_core.py",
    "history_storage_core.py",
    "history_lifecycle_core.py",
    "settings_io_core.py",
    "config_core.py",
    "security_core.py",
    "runtime_init_core.py",
    "hardware_core.py",
    "systemd_iw_core.py",
    "sniff_iface_core.py",
    "notify_core.py",
    "oui_ap_core.py",
    "models_remote_core.py",
    "scan_core.py",
    "process_core.py",
    "live_ws_core.py",
    "app_update_core.py",
    "history_process_core.py",
    "process_scan_diff_core.py",
    "simulation_core.py",
    "auth_core.py",
    "api_payload_core.py",
    "webauthn_core.py",
    "host_hw_core.py",
    "network_binding_core.py",
    "ap_dhcp_dns_core.py",
    "ap_hostapd_core.py",
    "web_server.py",
    "web_http_core.py",
    "cli_app.py",
    "cli_parse_core.py",
    "cli_tui_core.py",
)


@dataclass
class RuntimeContext:
    """Configuration for loading ordered legacy runtime chunks."""

    package_dir: Path
    entrypoint: Path
    chunk_files: tuple[str, ...] = DEFAULT_CHUNK_FILES
    module_name: str = "station_edition.xrs._assembled"
    package_name: str = "station_edition.xrs"
    namespace: dict[str, Any] = field(default_factory=dict)
    loaded: bool = False

    def __post_init__(self) -> None:
        self.package_dir = Path(self.package_dir).resolve()
        self.entrypoint = Path(self.entrypoint).resolve()
        self.chunk_files = tuple(str(name) for name in self.chunk_files)
        self.namespace.update(
            {
                "__name__": self.module_name,
                "__package__": self.package_name,
                "__file__": str(self.entrypoint),
                "RUNTIME_CONTEXT": self,
            }
        )

    @property
    def chunks(self) -> tuple[str, ...]:
        """Return chunk filenames in execution order."""
        return self.chunk_files

    @property
    def public_config(self) -> MappingProxyType:
        """Return a read-only snapshot suitable for diagnostics."""
        return MappingProxyType(
            {
                "package_dir": str(self.package_dir),
                "entrypoint": str(self.entrypoint),
                "chunk_files": self.chunk_files,
                "module_name": self.module_name,
                "package_name": self.package_name,
                "loaded": self.loaded,
            }
        )

    def chunk_path(self, name: str) -> Path:
        """Resolve a chunk path and ensure it stays inside the package."""
        path = (self.package_dir / name).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"runtime chunk not found: {path}")
        if self.package_dir not in path.parents:
            raise ValueError(f"runtime chunk outside package: {path}")
        return path


def default_package_dir() -> Path:
    """Return the package directory containing runtime chunks."""
    return Path(__file__).resolve().parent


def default_entrypoint() -> Path:
    """Return the process entrypoint used for runtime metadata."""
    return Path(sys.argv[0] or "run.py").resolve()


def create_runtime_context(
    *,
    package_dir: Path | None = None,
    entrypoint: Path | None = None,
    chunk_files: tuple[str, ...] | None = None,
    module_name: str = "station_edition.xrs._assembled",
    package_name: str = "station_edition.xrs",
) -> RuntimeContext:
    """Create a runtime context with project defaults."""
    return RuntimeContext(
        package_dir=package_dir or default_package_dir(),
        entrypoint=entrypoint or default_entrypoint(),
        chunk_files=chunk_files or DEFAULT_CHUNK_FILES,
        module_name=module_name,
        package_name=package_name,
    )


def load_namespace(ctx: RuntimeContext) -> dict[str, Any]:
    """Execute ordered chunk files into the shared runtime namespace."""
    if ctx.loaded:
        return ctx.namespace
    for name in ctx.chunks:
        path = ctx.chunk_path(name)
        source = path.read_text(encoding="utf-8")
        exec(compile(source, str(path), "exec"), ctx.namespace)
    ctx.loaded = True
    return ctx.namespace
