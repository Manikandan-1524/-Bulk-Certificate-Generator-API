import os
import re
import tempfile
import zipfile

from app.models.certificate import Certificate


def safe_name(name: str | None) -> str:
    result = re.sub(r"[^A-Za-z0-9_-]+", "_", name or "")
    result = result.strip("_")[:50].strip("_")
    if result == "":
        return "recipient"
    return result


def build_job_zip(certificates: list[Certificate]) -> str | None:
    fd, path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        added = 0
        used_names = set()
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for certificate in certificates:
                if certificate.file_path and os.path.isfile(certificate.file_path):
                    arcname = f"{safe_name(certificate.recipient_name)}_{certificate.id[:8]}.pdf"
                    if arcname in used_names:
                        arcname = f"{safe_name(certificate.recipient_name)}_{certificate.id}.pdf"
                    used_names.add(arcname)
                    zf.write(certificate.file_path, arcname)
                    added += 1
        if added == 0:
            os.remove(path)
            return None
        return path
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise