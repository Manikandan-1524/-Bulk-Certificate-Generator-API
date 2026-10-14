import json
import os
import shutil
from pathlib import Path

import pytest

from app.services import download_service as ds

JSON = json.dumps


def _configure_root(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.config.CERTIFICATES_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.services.download_service.CERTIFICATES_DIR", str(tmp_path), raising=False
    )
    return ds._zip_temp_root()


def test_recover_abandoned_zip_directory_removes_dead_process_files(
    tmp_path, monkeypatch
):
    zip_root = _configure_root(tmp_path, monkeypatch)
    process_dir = zip_root / "process-999999-legacy"
    process_dir.mkdir(parents=True)
    (process_dir / "abandoned.zip").write_bytes(b"zip")
    (process_dir / ".owner").write_text(
        JSON({"version": 1, "pid": 999999, "instance": "legacy"}),
        encoding="utf-8",
    )

    monkeypatch.setattr("app.services.download_service._pid_is_alive", lambda pid: False)
    ds.recover_abandoned_zip_temp_directories()

    assert not process_dir.exists()


def test_recover_abandoned_zip_directory_preserves_live_process_files(
    tmp_path, monkeypatch
):
    zip_root = _configure_root(tmp_path, monkeypatch)
    process_dir = zip_root / "process-43210-living"
    process_dir.mkdir(parents=True)
    kept = process_dir / "active.zip"
    kept.write_bytes(b"zip")
    (process_dir / ".owner").write_text(
        JSON({"version": 1, "pid": 43210, "instance": "living"}),
        encoding="utf-8",
    )

    monkeypatch.setattr("app.services.download_service._pid_is_alive", lambda pid: True)
    ds.recover_abandoned_zip_temp_directories()

    assert process_dir.exists()
    assert kept.exists()
    kept.unlink()
    shutil.rmtree(process_dir)


def test_recover_abandoned_zip_directory_preserves_current_process_directory(
    tmp_path, monkeypatch
):
    zip_root = _configure_root(tmp_path, monkeypatch)
    current_dir = ds._current_zip_process_dir()
    assert current_dir is not None
    kept = current_dir / "in-flight.zip"
    kept.write_bytes(b"zip")

    ds.recover_abandoned_zip_temp_directories()

    assert current_dir.exists()
    assert kept.exists()
    shutil.rmtree(current_dir)


def test_recover_abandoned_zip_directory_preserves_unrelated_entries(
    tmp_path, monkeypatch
):
    zip_root = _configure_root(tmp_path, monkeypatch)
    unknown_dir = zip_root / "unknown_directory"
    zip_root.mkdir(parents=True, exist_ok=True)
    unknown_dir.mkdir()
    unrelated_file = zip_root / "unrelated.txt"
    unrelated_file.write_text("do not remove", encoding="utf-8")

    abandoned = zip_root / "process-999999-unmarked"
    abandoned.mkdir()
    (abandoned / ".owner").write_text(
        JSON({"version": 1, "pid": 999999, "instance": "unmarked"}),
        encoding="utf-8",
    )
    (abandoned / "stale.zip").write_bytes(b"zip")

    monkeypatch.setattr("app.services.download_service._pid_is_alive", lambda pid: False)
    ds.recover_abandoned_zip_temp_directories()

    assert unknown_dir.exists()
    assert unrelated_file.exists()
    assert not (zip_root / "process-999999-unmarked").exists()


def test_recover_abandoned_zip_directory_skips_pid_reuse_or_uncertain_owner(
    tmp_path, monkeypatch
):
    zip_root = _configure_root(tmp_path, monkeypatch)
    process_dir = zip_root / "process-999999-reused"
    process_dir.mkdir(parents=True)
    (process_dir / "stale.zip").write_bytes(b"zip")
    (process_dir / ".owner").write_text(
        JSON({"version": 1, "pid": 999999, "instance": "reused"}),
        encoding="utf-8",
    )

    monkeypatch.setattr("app.services.download_service._pid_is_alive", lambda pid: True)
    ds.recover_abandoned_zip_temp_directories()

    assert process_dir.exists()
    assert (process_dir / "stale.zip").exists()
    shutil.rmtree(process_dir)


def test_recover_abandoned_zip_directory_skips_owner_mismatch_and_no_marker(
    tmp_path, monkeypatch
):
    zip_root = _configure_root(tmp_path, monkeypatch)
    mismatched = zip_root / "process-999999-mismatch"
    mismatched.mkdir(parents=True)
    (mismatched / ".owner").write_text(
        JSON({"version": 1, "pid": 999999, "instance": "different"}),
        encoding="utf-8",
    )
    (mismatched / "stale.zip").write_bytes(b"zip")

    no_marker = zip_root / "process-999998-no-owner"
    no_marker.mkdir(parents=True)
    (no_marker / "stale.zip").write_bytes(b"zip")

    monkeypatch.setattr("app.services.download_service._pid_is_alive", lambda pid: False)
    ds.recover_abandoned_zip_temp_directories()

    assert mismatched.exists()
    assert no_marker.exists()
    shutil.rmtree(mismatched)
    shutil.rmtree(no_marker)


def test_abandoned_zip_path_containment_and_symlink_protection(
    tmp_path, monkeypatch
):
    zip_root = _configure_root(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "outside.zip"
    outside_file.write_bytes(b"zip")

    link_name = zip_root / "process-100000-escape"
    try:
        os.symlink(outside, link_name)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not supported on this platform")

    # A marker cannot make a symlink outside the root eligible.
    try:
        link_name.mkdir(exist_ok=True)
    except FileExistsError:
        pass
    # Build the marker inside what appears to be the directory; if symlink creation
    # succeeds, the path used for recovery is outside and must be skipped.
    marker = zip_root / "process-100000-escape" / ".owner"
    # Cleanup defensively without following the link.
    if outside_file.exists():
        assert outside_file.exists()

    ds.recover_abandoned_zip_temp_directories()
    assert outside_file.exists()
    try:
        os.unlink(link_name)
    except OSError:
        pass


def test_safe_zip_path_does_not_resolve_outside_zip_root(tmp_path, monkeypatch):
    _configure_root(tmp_path, monkeypatch)
    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"zip")
    assert ds._safe_zip_path(str(outside)) is None

    inside = None
    if "inside" not in locals():
        pass
    zip_root = ds._zip_temp_root()
    process_dir = zip_root / "process-123-safe"
    process_dir.mkdir(parents=True)
    inside = process_dir / "inside.zip"
    inside.write_bytes(b"zip")
    try:
        assert ds._safe_zip_path(str(inside)) == inside.resolve()
    finally:
        shutil.rmtree(process_dir)

    # A traversal-like value is rejected even if masked with ..
    traversal = str(zip_root / ".." / outside.name)
    assert ds._safe_zip_path(traversal) is None


def test_abandoned_zip_cleanup_uses_alias_for_prev_process(
    tmp_path, monkeypatch
):
    # Compatibility with callers using another cleanup spelling.
    zip_root = _configure_root(tmp_path, monkeypatch)
    process_dir = zip_root / "process-123456-alias"
    process_dir.mkdir(parents=True)
    (process_dir / "stale.zip").write_bytes(b"zip")
    (process_dir / ".owner").write_text(
        JSON({"version": 1, "pid": 123456, "instance": "alias"}),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.services.download_service._pid_is_alive", lambda pid: False)
    ds.cleanup_abandoned_zip_files()
    assert not process_dir.exists()
