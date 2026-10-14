import os

import pytest

from app.services.job_processor import _safe_remove_generated_pdf, process_job

from tests.helpers import (
    ANNA,
    RAVI,
    ZOE,
    FAIL_ME,
    GOOD_RECIPIENTS,
    MIXED_RECIPIENTS,
    NAME_ERROR,
    install_flaky_generator,
    make_invalid_recipients,
    make_recipients,
    submit,
    get_certificate_list,
)


def test_one_failing_certificate_does_not_stop_others(client, session_factory, monkeypatch, certs_dir):
    install_flaky_generator(monkeypatch, {"Fail Me"})
    data = submit(client, [ANNA, FAIL_ME, RAVI])
    job_id = data["job_id"]

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed_with_errors"
    assert body["success_count"] == 2
    assert body["failed_count"] == 1
    assert body["pending_count"] == 0

    items = get_certificate_list(client, job_id)["certificates"]
    failed_item = next(item for item in items if item["recipient_name"] == "Fail Me")
    assert failed_item["status"] == "failed"
    assert "Certificate generation failed" in failed_item["error_message"]
    assert "forced failure" in failed_item["error_message"]
    assert failed_item["download_url"] is None
    assert sum(1 for item in items if item["status"] == "success") == 2

    assert len(os.listdir(os.path.join(certs_dir, job_id))) == 2

    from app.models.certificate import Certificate

    db = session_factory()
    try:
        failed_row = db.query(Certificate).filter(
            Certificate.job_id == job_id, Certificate.status == "failed"
        ).first()
        assert failed_row is not None
        assert failed_row.file_path is None
    finally:
        db.close()


def test_failure_works_in_any_position(client, monkeypatch):
    for failing_name in ("Anna", "Ravi", "Zoe"):
        install_flaky_generator(monkeypatch, {failing_name})
        data = submit(client, [ANNA, RAVI, ZOE])
        job_id = data["job_id"]

        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["success_count"] == 2
        assert body["failed_count"] == 1
        assert body["status"] == "completed_with_errors"

        items = get_certificate_list(client, job_id)["certificates"]
        failing_item = next(item for item in items if item["recipient_name"] == failing_name)
        assert failing_item["status"] == "failed"
        assert sum(1 for item in items if item["status"] == "success") == 2


def test_all_certificates_failing_marks_job_failed(client, monkeypatch, certs_dir):
    install_flaky_generator(monkeypatch, {"Anna", "Ravi"})
    data = submit(client, GOOD_RECIPIENTS)
    job_id = data["job_id"]

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["success_count"] == 0
    assert body["failed_count"] == 2
    assert body["pending_count"] == 0
    assert body["progress_percent"] == 100.0
    assert os.listdir(certs_dir) == []


def test_failed_certificates_are_counted_together_with_invalid_recipients(client, monkeypatch):
    install_flaky_generator(monkeypatch, {"Anna"})
    data = submit(client, MIXED_RECIPIENTS)
    job_id = data["job_id"]

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed_with_errors"
    assert body["total"] == 5
    assert body["success_count"] == 1
    assert body["failed_count"] == 4


def test_half_written_file_is_removed_when_generation_fails(client, monkeypatch, certs_dir):
    def broken(recipient_name, course_name, issue_date, output_path):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(b"partial")
        raise RuntimeError("forced failure")

    monkeypatch.setattr("app.services.job_processor.generate_certificate_pdf", broken)

    data = submit(client, [ANNA])
    job_id = data["job_id"]

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert os.listdir(os.path.join(certs_dir, job_id)) == []


def test_unexpected_processing_error_does_not_leave_job_stuck(client, monkeypatch, certs_dir):
    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", None)
    data = submit(client, GOOD_RECIPIENTS)
    job_id = data["job_id"]

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["success_count"] == 0
    assert body["failed_count"] == 2
    assert body["pending_count"] == 0

    items = get_certificate_list(client, job_id)["certificates"]
    assert all(item["status"] == "failed" for item in items)
    assert all(item["error_message"] == "Processing stopped unexpectedly" for item in items)


def test_process_job_with_unknown_id_does_nothing(client):
    assert process_job("does-not-exist") is None


def test_safe_remove_generated_pdf_removes_partial_inside_root(tmp_path, monkeypatch):
    root = tmp_path / "certificates"
    root.mkdir()
    certificate_dir = root / "job-id"
    certificate_dir.mkdir()
    partial = certificate_dir / "partial.pdf"
    partial.write_bytes(b"partial")

    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", str(root))
    _safe_remove_generated_pdf(str(partial))

    assert not partial.exists()


def test_safe_remove_generated_pdf_does_not_delete_outside_file(tmp_path, monkeypatch):
    root = tmp_path / "certificates"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("do not delete", encoding="utf-8")

    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", str(root))
    _safe_remove_generated_pdf(str(outside.resolve()))

    assert outside.exists()
    assert outside.read_text(encoding="utf-8") == "do not delete"


def test_safe_remove_generated_pdf_does_not_follow_symlink_escape(tmp_path, monkeypatch):
    root = tmp_path / "certificates"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("do not delete", encoding="utf-8")
    link = root / "link.pdf"

    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not supported on this platform")

    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", str(root))
    _safe_remove_generated_pdf(str(link))

    assert outside.exists()
    assert outside.read_text(encoding="utf-8") == "do not delete"
    assert link.exists()


def test_generation_error_remains_original_when_partial_cleanup_fails(client, monkeypatch, certs_dir):
    def broken(recipient_name, course_name, issue_date, output_path):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(b"partial")
        raise RuntimeError("forced failure")

    monkeypatch.setattr("app.services.job_processor.generate_certificate_pdf", broken)
    monkeypatch.setattr("app.services.job_processor.os.remove", lambda path: (_ for _ in ()).throw(OSError("cleanup failed")))

    data = submit(client, [ANNA])
    job_id = data["job_id"]

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"

    items = get_certificate_list(client, job_id)["certificates"]
    assert all("forced failure" in item["error_message"] for item in items)