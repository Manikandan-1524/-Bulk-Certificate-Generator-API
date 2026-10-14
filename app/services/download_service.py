import os
import re
import tempfile
import zipfile
from pathlib import Path

from app.core import config as core_config
from app.models.certificate import Certificate


# This name can be monkeypatched by tests (or read from configuration) to control
# the canonical output directory in test environments.
CERTIFICATES_DIR = core_config.CERTIFICATES_DIR


def safe_name(name: str | None) -> str:
    result = re.sub(r"[^A-Za-z0-9_-]+", "_", name or "")
    result = result.strip("_")[:50].strip("_")
    if result == "":
        return "recipient"
    return result


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


def build_job_zip(certificates: list[Certificate]) -> str | None:
    fd, path = tempfile.mkstemp(suffix=".zip")
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
            os.remove(path)
            return None
        return path
    except Exception:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
        raise