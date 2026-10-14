import io
import os
import tempfile
import zipfile
from types import SimpleNamespace

import pytest

from app.models.certificate import Certificate
from app.models.job import Job
from app.services.download_service import build_job_zip, safe_name

from tests.helpers import (
    ANNA,
    RAVI,
    GOOD_RECIPIENTS,
    MIXED_RECIPIENTS,
    make_invalid_recipients,
    make_recipients,
    submit,
    get_certificate_list,
)


def test_list_certificates_returns_all_items(client):
    data = submit(client, MIXED_RECIPIENTS)
    job_id = data["job_id"]
    body = get_certificate_list(client, job_id)

    assert body["total"] == 5
    assert body["limit"] == 100
    assert body["offset"] == 0
    assert len(body["certificates"]) == 5
    for item in body["certificates"]:
        assert set(item.keys()) == {
            "certificate_id",
            "recipient_name",
            "recipient_email",
            "status",
            "error_message",
            "download_url",
        }

    success_items = [item for item in body["certificates"] if item["status"] == "success"]
    failed_items = [item for item in body["certificates"] if item["status"] == "failed"]
    assert len(success_items) == 2
    assert len(failed_items) == 3
    for item in success_items:
        assert item["download_url"] == f"/jobs/{job_id}/certificates/{item['certificate_id']}/download"
    for item in failed_items:
        assert item["download_url"] is None
        assert item["error_message"]


def test_list_can_be_filtered_by_status(client):
    data = submit(client, MIXED_RECIPIENTS)
    job_id = data["job_id"]
    for status, expected in [("failed", 3), ("success", 2), ("pending", 0)]:
        body = get_certificate_list(client, job_id, query=f"?status={status}")
        assert body["total"] == expected
        assert all(item["status"] == status for item in body["certificates"])


def test_list_pagination(client):
    data = submit(client, make_recipients(5))
    job_id = data["job_id"]

    page1 = get_certificate_list(client, job_id, query="?limit=2&offset=0")
    page2 = get_certificate_list(client, job_id, query="?limit=2&offset=2")
    page3 = get_certificate_list(client, job_id, query="?limit=2&offset=4")

    assert len(page1["certificates"]) == 2
    assert len(page2["certificates"]) == 2
    assert len(page3["certificates"]) == 1
    assert page1["total"] == page2["total"] == page3["total"] == 5

    all_ids = [item["certificate_id"] for item in page1["certificates"] + page2["certificates"] + page3["certificates"]]
    assert len(set(all_ids)) == 5

    empty = get_certificate_list(client, job_id, query="?limit=2&offset=10")
    assert empty["certificates"] == []
    assert empty["total"] == 5


@pytest.mark.parametrize("query", ["?status=abc", "?limit=0", "?limit=1001", "?limit=abc", "?offset=-1"])
def test_list_rejects_invalid_query_values(client, query):
    data = submit(client, GOOD_RECIPIENTS)
    job_id = data["job_id"]
    response = client.get(f"/jobs/{job_id}/certificates{query}")
    assert response.status_code == 422


def test_list_accepts_boundary_values(client):
    data = submit(client, GOOD_RECIPIENTS)
    job_id = data["job_id"]
    assert client.get(f"/jobs/{job_id}/certificates?limit=1").status_code == 200
    assert len(client.get(f"/jobs/{job_id}/certificates?limit=1").json()["certificates"]) == 1
    assert client.get(f"/jobs/{job_id}/certificates?limit=1000").status_code == 200
    assert len(client.get(f"/jobs/{job_id}/certificates?limit=1000").json()["certificates"]) == 2
    assert client.get(f"/jobs/{job_id}/certificates?offset=0").status_code == 200


def test_list_for_unknown_job_returns_404(client):
    response = client.get("/jobs/unknown-id/certificates")
    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


def test_pending_certificates_have_no_download_url(client, no_background_processing):
    data = submit(client, GOOD_RECIPIENTS)
    job_id = data["job_id"]
    body = get_certificate_list(client, job_id, query="?status=pending")
    assert body["total"] == 2
    assert all(item["download_url"] is None for item in body["certificates"])


def test_download_single_certificate(client):
    data = submit(client, MIXED_RECIPIENTS)
    job_id = data["job_id"]
    body = get_certificate_list(client, job_id)
    item = next(item for item in body["certificates"] if item["recipient_name"] == "Anna")
    assert item["status"] == "success"

    response = client.get(item["download_url"])
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content[:4] == b"%PDF"
    assert "Anna_certificate.pdf" in response.headers.get("content-disposition", "")


def test_download_filename_is_safe(client):
    data = submit(client, [{"name": "O'Brien / Test", "email": "ob@example.com"}])
    job_id = data["job_id"]
    body = get_certificate_list(client, job_id)
    item = body["certificates"][0]
    response = client.get(item["download_url"])
    assert response.status_code == 200
    assert "O_Brien_Test_certificate.pdf" in response.headers.get("content-disposition", "")


def test_download_failed_certificate_returns_409(client):
    data = submit(client, MIXED_RECIPIENTS)
    job_id = data["job_id"]
    body = get_certificate_list(client, job_id, query="?status=failed")
    item = body["certificates"][0]
    response = client.get(f"/jobs/{job_id}/certificates/{item['certificate_id']}/download")
    assert response.status_code == 409
    assert response.json()["detail"] == "Certificate is not available (status: failed)"


def test_download_unknown_ids_return_404(client):
    data = submit(client, GOOD_RECIPIENTS)
    job_id = data["job_id"]
    response = client.get(f"/jobs/{job_id}/certificates/does-not-exist/download")
    assert response.status_code == 404
    assert response.json()["detail"] == "Certificate not found"

    response = client.get("/jobs/unknown-id/certificates/123/download")
    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


def test_download_certificate_of_another_job_returns_404(client):
    data_a = submit(client, GOOD_RECIPIENTS)
    data_b = submit(client, GOOD_RECIPIENTS)
    job_a = data_a["job_id"]
    job_b = data_b["job_id"]

    body_a = get_certificate_list(client, job_a)
    cert_id = next(item for item in body_a["certificates"] if item["status"] == "success")["certificate_id"]

    response = client.get(f"/jobs/{job_b}/certificates/{cert_id}/download")
    assert response.status_code == 404


def test_download_returns_404_when_file_is_missing(client, session_factory):
    data = submit(client, GOOD_RECIPIENTS)
    job_id = data["job_id"]

    db = session_factory()
    try:
        cert = db.query(Certificate).filter(Certificate.job_id == job_id, Certificate.status == "success").first()
        cert_id = cert.id
        file_path = cert.file_path
    finally:
        db.close()

    os.remove(file_path)
    response = client.get(f"/jobs/{job_id}/certificates/{cert_id}/download")
    assert response.status_code == 404
    assert response.json()["detail"] == "Certificate file not found"


def test_download_zip_contains_all_successful_certificates(client):
    data = submit(client, MIXED_RECIPIENTS)
    job_id = data["job_id"]
    body = get_certificate_list(client, job_id)
    success_items = [item for item in body["certificates"] if item["status"] == "success"]

    response = client.get(f"/jobs/{job_id}/download")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    assert f"certificates_{job_id}.zip" in response.headers.get("content-disposition", "")

    zf = zipfile.ZipFile(io.BytesIO(response.content))
    names = set(zf.namelist())
    expected = {f"{item['recipient_name']}_{item['certificate_id'][:8]}.pdf" for item in success_items}
    assert names == expected
    for name in names:
        assert zf.read(name)[:4] == b"%PDF"


def test_zip_with_recipients_of_the_same_name(client):
    recipients = [
        {"name": "Anna", "email": "a1@example.com"},
        {"name": "Anna", "email": "a2@example.com"},
        {"name": "Anna", "email": "a3@example.com"},
    ]
    data = submit(client, recipients)
    job_id = data["job_id"]
    response = client.get(f"/jobs/{job_id}/download")
    assert response.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(response.content))
    assert len(zf.namelist()) == 3
    assert len(set(zf.namelist())) == 3


def test_zip_contains_only_successful_certificates(client, monkeypatch):
    from tests.helpers import install_flaky_generator

    install_flaky_generator(monkeypatch, {"Anna"})
    data = submit(client, GOOD_RECIPIENTS)
    job_id = data["job_id"]
    response = client.get(f"/jobs/{job_id}/download")
    assert response.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(response.content))
    names = zf.namelist()
    assert len(names) == 1
    assert names[0].startswith("Ravi_")


def test_zip_temporary_file_is_deleted_after_download(client, tmp_path, monkeypatch):
    import tempfile as _tempfile

    zip_tmp = tmp_path / "ziptmp"
    zip_tmp.mkdir()
    monkeypatch.setattr(_tempfile, "tempdir", str(zip_tmp))

    data = submit(client, GOOD_RECIPIENTS)
    job_id = data["job_id"]
    response = client.get(f"/jobs/{job_id}/download")
    assert response.status_code == 200
    assert os.listdir(zip_tmp) == []


def test_zip_of_job_with_only_invalid_recipients_returns_404(client):
    data = submit(client, make_invalid_recipients(2))
    job_id = data["job_id"]
    response = client.get(f"/jobs/{job_id}/download")
    assert response.status_code == 404
    assert response.json()["detail"] == "No certificates available for download"


def test_zip_of_pending_job_returns_409(client, no_background_processing):
    data = submit(client, GOOD_RECIPIENTS)
    job_id = data["job_id"]
    response = client.get(f"/jobs/{job_id}/download")
    assert response.status_code == 409
    assert response.json()["detail"] == "Job is still being processed"


def test_zip_of_unknown_job_returns_404(client):
    response = client.get("/jobs/unknown-id/download")
    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


SAFE_NAME_CASES = [
    ("O'Brien / Test", "O_Brien_Test"),
    ("அருண்", "recipient"),
    (None, "recipient"),
    ("", "recipient"),
    ("  Anna  ", "Anna"),
    ("W" * 100, "W" * 50),
    ("A" * 49 + " " + "B" * 10, "A" * 49),
]


@pytest.mark.parametrize("value,expected", SAFE_NAME_CASES)
def test_safe_name(value, expected):
    assert safe_name(value) == expected


def test_build_job_zip_handles_name_collisions_and_missing_files(tmp_path, monkeypatch):
    import tempfile as _tempfile

    zip_tmp = tmp_path / "ziptmp"
    zip_tmp.mkdir()
    monkeypatch.setattr(_tempfile, "tempdir", str(zip_tmp))
    monkeypatch.setattr("app.core.config.CERTIFICATES_DIR", str(tmp_path))
    monkeypatch.setattr("app.services.download_service.CERTIFICATES_DIR", str(tmp_path), raising=False)

    file_one = tmp_path / "one.pdf"
    file_one.write_bytes(b"%PDF-1")
    file_two = tmp_path / "two.pdf"
    file_two.write_bytes(b"%PDF-2")

    certificates = [
        SimpleNamespace(id="12345678-aaaa", recipient_name="Anna", file_path=str(file_one)),
        SimpleNamespace(id="12345678-bbbb", recipient_name="Anna", file_path=str(file_two)),
        SimpleNamespace(id="99999999-cccc", recipient_name="Ravi", file_path=str(tmp_path / "missing.pdf")),
        SimpleNamespace(id="88888888-dddd", recipient_name="Zoe", file_path=None),
    ]

    zip_path = build_job_zip(certificates)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = sorted(zf.namelist())
        assert names == ["Anna_12345678-bbbb.pdf", "Anna_12345678.pdf"]
    finally:
        os.remove(zip_path)
    assert os.listdir(zip_tmp) == []


def test_build_job_zip_returns_none_when_no_file_exists(tmp_path, monkeypatch):
    import tempfile as _tempfile

    zip_tmp = tmp_path / "ziptmp"
    zip_tmp.mkdir()
    monkeypatch.setattr(_tempfile, "tempdir", str(zip_tmp))

    certificates = [
        SimpleNamespace(id="11111111-aaaa", recipient_name="Anna", file_path=None),
        SimpleNamespace(id="22222222-bbbb", recipient_name="Ravi", file_path=str(tmp_path / "missing.pdf")),
    ]
    assert build_job_zip(certificates) is None
    assert build_job_zip([]) is None
    assert os.listdir(zip_tmp) == []


def test_download_rejects_path_traversal_outside_certificates_root(client, session_factory, tmp_path):
    data = submit(client, GOOD_RECIPIENTS)
    job_id = data["job_id"]

    db = session_factory()
    try:
        cert = (
            db.query(Certificate)
            .filter(Certificate.job_id == job_id, Certificate.status == "success")
            .first()
        )
        outside_file = tmp_path / "outside.pdf"
        outside_file.write_bytes(b"%PDF-outside")
        cert.file_path = str(tmp_path / ".." / outside_file.name)
        db.commit()
        cert_id = cert.id
    finally:
        db.close()

    response = client.get(f"/jobs/{job_id}/certificates/{cert_id}/download")
    assert response.status_code == 404
    assert response.json()["detail"] == "Certificate file not found"


def test_zip_rejects_certificates_whose_paths_escape_root(client, session_factory, tmp_path):
    data = submit(client, GOOD_RECIPIENTS)
    job_id = data["job_id"]

    db = session_factory()
    try:
        for cert in db.query(Certificate).filter(
            Certificate.job_id == job_id, Certificate.status == "success"
        ).all():
            cert.file_path = str(tmp_path / "../outside.pdf")
        db.commit()
    finally:
        db.close()

    response = client.get(f"/jobs/{job_id}/download")
    assert response.status_code == 404
    assert response.json()["detail"] == "No certificates available for download"


def test_build_job_zip_prunes_paths_outside_permitted_root(tmp_path, monkeypatch):
    import tempfile as _tempfile

    root = tmp_path / "certificates"
    (root / "job").mkdir(parents=True)
    inside = root / "job" / "inside.pdf"
    inside.write_bytes(b"%PDF-inside")

    zip_tmp = tmp_path / "ziptmp"
    zip_tmp.mkdir()
    monkeypatch.setattr(_tempfile, "tempdir", str(zip_tmp))
    monkeypatch.setattr("app.core.config.CERTIFICATES_DIR", str(root))
    monkeypatch.setattr("app.services.download_service.CERTIFICATES_DIR", str(root), raising=False)

    certificates = [
        SimpleNamespace(id="11111111-aaaa", recipient_name="Anna", file_path=str(inside)),
        SimpleNamespace(
            id="22222222-bbbb",
            recipient_name="Ravi",
            file_path=str(tmp_path / "outside.pdf"),
        ),
    ]
    (tmp_path / "outside.pdf").write_bytes(b"%PDF-outside")

    zip_path = build_job_zip(certificates)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            assert zf.namelist() == ["Anna_11111111.pdf"]
            assert zf.read("Anna_11111111.pdf") == b"%PDF-inside"
    finally:
        os.remove(zip_path)
    assert os.listdir(zip_tmp) == []


def test_download_rejects_symlink_escape_when_supported(client, session_factory, tmp_path):
    root = tmp_path / "certs"
    root.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-outside")
    link = root / "job" / "link.pdf"
    link.parent.mkdir(parents=True)

    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not supported on this platform")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.core.config.CERTIFICATES_DIR", str(root))
    monkeypatch.setattr("app.services.download_service.CERTIFICATES_DIR", str(root), raising=False)

    data = submit(client, GOOD_RECIPIENTS)
    job_id = data["job_id"]

    db = session_factory()
    try:
        cert = (
            db.query(Certificate)
            .filter(Certificate.job_id == job_id, Certificate.status == "success")
            .first()
        )
        cert.file_path = str(link)
        db.commit()
        cert_id = cert.id
    finally:
        db.close()

    response = client.get(f"/jobs/{job_id}/certificates/{cert_id}/download")
    monkeypatch.undo()

    assert response.status_code == 404
    assert response.json()["detail"] == "Certificate file not found"


def test_build_job_zip_preserves_original_exception_on_creation_failure(tmp_path, monkeypatch):
    import tempfile as _tempfile
    import zipfile

    zip_tmp = tmp_path / "ziptmp"
    zip_tmp.mkdir()
    monkeypatch.setattr(_tempfile, "tempdir", str(zip_tmp))

    class FailingZipFile:
        def __init__(*args, **kwargs):
            raise RuntimeError("forced zip creation failure")

    monkeypatch.setattr(zipfile, "ZipFile", FailingZipFile)

    certificates = [
        SimpleNamespace(id="11111111-aaaa", recipient_name="Anna", file_path=str(tmp_path / "anna.pdf")),
    ]

    with pytest.raises(RuntimeError, match="forced zip creation failure"):
        build_job_zip(certificates)

    # Successful cleanup should not leave temporary files behind.
    assert os.listdir(zip_tmp) == []


def test_build_job_zip_attempts_cleanup_before_reraising_original_exception(tmp_path, monkeypatch):
    import tempfile as _tempfile
    import zipfile
    import os as real_os

    zip_tmp = tmp_path / "ziptmp"
    zip_tmp.mkdir()
    monkeypatch.setattr(_tempfile, "tempdir", str(zip_tmp))

    class FailingZipFile:
        def __init__(*args, **kwargs):
            raise RuntimeError("forced zip creation failure")

    monkeypatch.setattr(zipfile, "ZipFile", FailingZipFile)

    real_remove = real_os.remove
    cleanup_calls = []

    def counting_remove(path, *args, **kwargs):
        cleanup_calls.append(path)
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(real_os, "remove", counting_remove)

    certificates = [
        SimpleNamespace(id="22222222-bbbb", recipient_name="Ravi", file_path=str(tmp_path / "ravi.pdf")),
    ]

    with pytest.raises(RuntimeError, match="forced zip creation failure"):
        build_job_zip(certificates)

    assert len(cleanup_calls) == 1
    from app.services.download_service import _zip_temp_root
    assert os.path.dirname(cleanup_calls[0]).startswith(str(_zip_temp_root()))
    assert os.listdir(zip_tmp) == []


def test_build_job_zip_preserves_original_exception_when_cleanup_raises(tmp_path, monkeypatch):
    import tempfile as _tempfile
    import zipfile
    import os as real_os

    zip_tmp = tmp_path / "ziptmp"
    zip_tmp.mkdir()
    monkeypatch.setattr(_tempfile, "tempdir", str(zip_tmp))

    class FailingZipFile:
        def __init__(*args, **kwargs):
            raise RuntimeError("forced zip creation failure")

    monkeypatch.setattr(zipfile, "ZipFile", FailingZipFile)

    cleanup_attempts = []
    real_remove = real_os.remove

    def failing_remove(path, *args, **kwargs):
        cleanup_attempts.append(path)
        raise OSError("forced cleanup failure")

    monkeypatch.setattr(real_os, "remove", failing_remove)

    try:
        certificates = [
            SimpleNamespace(id="33333333-cccc", recipient_name="Zoe", file_path=str(tmp_path / "zoe.pdf")),
        ]

        with pytest.raises(RuntimeError, match="forced zip creation failure"):
            build_job_zip(certificates)

        assert len(cleanup_attempts) == 1
        from app.services.download_service import _zip_temp_root
        assert os.path.dirname(cleanup_attempts[0]).startswith(str(_zip_temp_root()))
    finally:
        # The monkeypatch intentionally prevented deletion; clean up manually.
        for path in zip_tmp.iterdir():
            if path.is_file():
                real_remove(path)