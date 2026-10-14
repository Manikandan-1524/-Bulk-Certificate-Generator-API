import io
import os
import zipfile

import pytest
from datetime import date

from app.services.certificate_generator import generate_certificate_pdf

from tests.helpers import ANNA, RAVI, GOOD_RECIPIENTS, submit, get_certificate_list


@pytest.mark.parametrize("name", ["அருண்", "李雷", "Anna 😀", "Łukasz"])
def test_unsupported_recipient_name_is_rejected(tmp_path, name):
    output = tmp_path / "out" / "c.pdf"
    with pytest.raises(ValueError) as info:
        generate_certificate_pdf(name, "Python Basics", date(2026, 10, 13), str(output))
    assert "Recipient name" in str(info.value)
    assert "cannot display" in str(info.value)
    assert not output.exists()
    assert not output.parent.exists()


@pytest.mark.parametrize("course_name", ["பைதான்", "Python 🐍"])
def test_unsupported_course_name_is_rejected(tmp_path, course_name):
    output = tmp_path / "out" / "c.pdf"
    with pytest.raises(ValueError) as info:
        generate_certificate_pdf("Anna", course_name, date(2026, 10, 13), str(output))
    assert "Course name" in str(info.value)
    assert "cannot display" in str(info.value)
    assert not output.exists()
    assert not output.parent.exists()


@pytest.mark.parametrize("name", ["José Ñandú", "Zoë", "Çelik", "Ångström"])
def test_accented_latin_names_still_work(tmp_path, name):
    output = tmp_path / "ok.pdf"
    generate_certificate_pdf(name, "Python Basics", date(2026, 10, 13), str(output))
    assert output.exists()
    assert output.read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize("name", ["Jose\u0301", "Zoe\u0308"])
def test_decomposed_accents_are_accepted(tmp_path, name):
    output = tmp_path / "ok.pdf"
    generate_certificate_pdf(name, "Python Basics", date(2026, 10, 13), str(output))
    assert output.exists()
    assert output.read_bytes().startswith(b"%PDF")


def test_job_fails_only_the_unsupported_certificates(client, certs_dir):
    response = submit(
        client,
        [
            ANNA,
            {"name": "அருண்", "email": "arun@example.com"},
            {"name": "李雷", "email": "li@example.com"},
            RAVI,
        ],
    )
    job_id = response["job_id"]

    status_response = client.get(f"/jobs/{job_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "completed_with_errors"
    assert body["total"] == 4
    assert body["success_count"] == 2
    assert body["failed_count"] == 2
    assert body["pending_count"] == 0

    failed_list = get_certificate_list(client, job_id, "?status=failed")
    assert failed_list["total"] == 2
    for item in failed_list["certificates"]:
        assert item["error_message"] == "Certificate generation failed."
        assert item["download_url"] is None

    success_list = get_certificate_list(client, job_id, "?status=success")
    assert {item["recipient_name"] for item in success_list["certificates"]} == {"Anna", "Ravi"}

    assert len(os.listdir(os.path.join(certs_dir, job_id))) == 2

    zip_response = client.get(f"/jobs/{job_id}/download")
    assert zip_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zip_response.content)) as zf:
        assert len(zf.namelist()) == 2


def test_job_with_only_unsupported_names_fails(client, certs_dir):
    response = submit(
        client,
        [
            {"name": "அருண்", "email": "arun@example.com"},
            {"name": "李雷", "email": "li@example.com"},
        ],
    )
    job_id = response["job_id"]

    status_response = client.get(f"/jobs/{job_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "failed"
    assert body["success_count"] == 0
    assert body["failed_count"] == 2
    assert body["pending_count"] == 0

    assert os.listdir(certs_dir) == []


def test_job_with_unsupported_course_name_fails(client, certs_dir):
    response = submit(client, GOOD_RECIPIENTS, course_name="பைதான்")
    job_id = response["job_id"]

    status_response = client.get(f"/jobs/{job_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "failed"
    assert body["failed_count"] == 2

    for item in get_certificate_list(client, job_id)["certificates"]:
        assert item["error_message"] == "Certificate generation failed."

    assert os.listdir(certs_dir) == []