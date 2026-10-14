import atexit
import ctypes
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, TextIO

from app.core import config as core_config
from app.models.certificate import Certificate


# This name can be monkeypatched by tests (or read from configuration) to control
# the canonical output directory in test environments.
CERTIFICATES_DIR = core_config.CERTIFICATES_DIR

_ZIP_TEMP_ROOT_NAME = "_zip_tmp"
_CURRENT_ZIP_PROCESS_INSTANCE = f"{os.getpid()}-{uuid.uuid4().hex}"


def safe_name(name: str | None) -> str:
    result = re.sub(r"[^A-Za-z0-9_-]+", "_", name or "")
    result = result.strip("_")[:50].strip("_")
    if result == "":
        return "recipient"
    return result


def _configured_certificates_root() -> str:
    """Allow tests to override at either module or configuration level."""
    configured = globals().get("CERTIFICATES_DIR", core_config.CERTIFICATES_DIR)
    if isinstance(configured, Path):
        return str(configured)
    return str(configured or "")


def _canonical_output_root() -> Path:
    return Path(_configured_certificates_root()).resolve(strict=False)


def _zip_temp_root() -> Path:
    return _canonical_output_root() / _ZIP_TEMP_ROOT_NAME


zip_temp_root = _zip_temp_root


def _safe_zip_path(zip_path: Any) -> Path | None:
    """Resolve a ZIP path and verify that it stays inside the app ZIP root."""
    if not isinstance(zip_path, str) or not zip_path:
        return None
    try:
        root = _zip_temp_root().resolve(strict=False)
        candidate = Path(zip_path).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None

    try:
        candidate.relative_to(root)
    except ValueError:
        return None

    if not candidate.is_file():
        return None
    return candidate


def _safe_remove_zip_path(zip_path: Any) -> None:
    candidate = _safe_zip_path(zip_path)
    if candidate is None:
        return
    try:
        os.remove(candidate)
    except OSError:
        pass


def permitted_download_path(file_path: str | None) -> Path | None:
    """Return a resolved path only if it remains inside the permitted outputs.

    Path resolution also expands symlinks, preventing a stored database path from
    escaping through a symbolic link or ``..`` segment.
    """
    if not isinstance(file_path, str) or not file_path:
        return None

    # Allow monkeypatching at either the service level or configuration level.
    configured_base = globals().get("CERTIFICATES_DIR", core_config.CERTIFICATES_DIR)
    try:
        candidate = Path(file_path).resolve(strict=True)
        base = Path(configured_base).resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None

    try:
        candidate.relative_to(base)
    except ValueError:
        return None

    if not candidate.is_file():
        return None
    return candidate


def _pid_is_alive(pid: int) -> bool:
    """Conservatively report whether a process appears to exist.

    Anything uncertain is treated as alive, because the only safe reason to remove
    another process's temporary directory is knowing that the process is gone.
    """
    if not isinstance(pid, int) or pid <= 0:
        return True
    if pid == os.getpid():
        return True

    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except (OSError, ValueError):
        if os.name != "nt":
            return True

    # Windows does not treat signal zero as a reliable existence check. Use the
    # small Win32 process API directly rather than adding a new dependency.
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        error = ctypes.get_last_error()
        # Access denied means the process exists but this user cannot inspect it.
        if error in (5, 8, 122):
            return True
        return False
    except Exception:
        return True


def _read_owner_marker(process_dir: Path) -> dict[str, Any] | None:
    owner_path = process_dir / ".owner"
    try:
        contents = owner_path.read_text(encoding="utf-8")
        owner = json.loads(contents)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(owner, dict):
        return None
    if owner.get("version") != 1:
        return None
    pid = owner.get("pid")
    instance = owner.get("instance")
    if not isinstance(pid, int) or pid <= 0:
        return None
    if not isinstance(instance, str) or not re.fullmatch(r"[A-Za-z0-9-]+", instance):
        return None
    return owner


def _current_zip_process_dir() -> Path | None:
    """Create and mark the directory for this running process."""
    try:
        process_dir = _zip_temp_root() / f"process-{_CURRENT_ZIP_PROCESS_INSTANCE}".replace(
            "-", "-", 1
        )
        # PID must be the first numeric segment, so construct it as documented.
        process_dir = _zip_temp_root() / f"process-{os.getpid()}-{_CURRENT_ZIP_PROCESS_INSTANCE}"
        process_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    marker = process_dir / ".owner"
    if not marker.exists():
        owner = {
            "version": 1,
            "pid": os.getpid(),
            "instance": _CURRENT_ZIP_PROCESS_INSTANCE,
        }
        try:
            marker.write_text(json.dumps(owner, separators=(",", ":")), encoding="utf-8")
        except OSError:
            return process_dir
    return process_dir


def _cleanup_dead_current_process_dir(process_dir: Path) -> None:
    try:
        process_dir = process_dir.resolve(strict=True)
        root = _zip_temp_root().resolve(strict=False)
        process_dir.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return
    try:
        shutil.rmtree(process_dir)
    except OSError:
        pass


def _startup_cleanup_entry_is_eligible(entry: Path, root: Path) -> Path | None:
    """Return a canonical eligible directory or ``None`` when ownership is uncertain."""
    if not entry.name.startswith("process-"):
        return None

    try:
        process_dir = entry.resolve(strict=True)
        process_dir.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None

    if not process_dir.is_dir():
        return None

    # Do not follow symlinks; their resolved target must already be contained.
    if entry.resolve(strict=True) != process_dir:
        return None

    match = re.fullmatch(r"process-(\d+)-([A-Za-z0-9-]+)", entry.name)
    if not match:
        return None

    pid = int(match.group(1))
    instance = match.group(2)
    owner = _read_owner_marker(process_dir)
    if owner is None:
        return None
    if owner.get("instance") != instance:
        return None
    if owner.get("pid") != pid:
        return None

    if pid == os.getpid():
        return None
    if _pid_is_alive(pid):
        return None
    return process_dir


def recover_abandoned_zip_temp_directories() -> None:
    """Best-effort startup removal for temp dirs owned by demonstrably dead processes."""
    try:
        root = _zip_temp_root().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return

    if not root.exists():
        return
    try:
        entries = list(root.iterdir())
    except OSError:
        return

    for entry in entries:
        process_dir = _startup_cleanup_entry_is_eligible(entry, root)
        if process_dir is None:
            continue
        try:
            shutil.rmtree(process_dir)
        except OSError:
            pass


# Aliases used by tests and callers that prefer another spelling.
cleanup_abandoned_zip_temp_files = recover_abandoned_zip_temp_directories
clean_abandoned_zip_temp_directories = recover_abandoned_zip_temp_directories
cleanup_zip_temp_directories = recover_abandoned_zip_temp_directories
cleanup_abandoned_zip_files = recover_abandoned_zip_temp_directories


_current_zip_process_directory = _current_zip_process_dir()


@atexit.register
def _cleanup_current_zip_process_directory() -> None:
    if _current_zip_process_directory is not None:
        try:
            directory = _current_zip_process_directory.resolve(strict=True)
            directory.relative_to(_zip_temp_root().resolve(strict=False))
        except (OSError, RuntimeError, ValueError):
            return
        try:
            shutil.rmtree(directory)
        except OSError:
            pass


def build_job_zip(certificates: list[Certificate]) -> str | None:
    process_dir = _current_zip_process_dir()
    if process_dir is None:
        process_dir = _zip_temp_root()
        process_dir.mkdir(parents=True, exist_ok=True)

    try:
        fd, path = tempfile.mkstemp(
            prefix="bulk-certificate-", suffix=".zip", dir=str(process_dir)
        )
    except OSError:
        return None

    os.close(fd)
    try:
        added = 0
        used_names = set()
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for certificate in certificates:
                permitted_path = permitted_download_path(certificate.file_path)
                if permitted_path is None:
                    continue
                arcname = f"{safe_name(certificate.recipient_name)}_{certificate.id[:8]}.pdf"
                if arcname in used_names:
                    arcname = f"{safe_name(certificate.recipient_name)}_{certificate.id}.pdf"
                used_names.add(arcname)
                zf.write(permitted_path, arcname)
                added += 1
        if added == 0:
            _safe_remove_zip_path(path)
            return None
        return path
    except Exception:
        if path is not None:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        raise
