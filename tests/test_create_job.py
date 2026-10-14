import os

from datetime import date

from app.models.certificate import Certificate
from app.models.job import Job

from tests.helpers import (
    ANNA,
    GOOD_RECIPIENTS,
    MIXED_RECIPIENTS,
    make_invalid_recipients,
    make_payload,
    make_recipients,
    submit,
)


def test_create_job_returns_202_with_counts(client):
    data = submit(client, make_recipients(3))
    assert set(data.keys()) == {"job_id", "status", "total", "valid_count", "invalid_count"}
    assert data["total"] == 3
    assert data["valid_count"] == 3
    assert data["invalid_count"] == 0
    assert data["status"] == "pending"
    assert isinstance(data["job_id"], str) and data["job_id"] != ""

    response = client.get(f"/jobs/{data['job_id']}")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_create_job_saves_job_and_certificates_in_database(client, session_factory):
    data = submit(client, make_recipients(3))

    db = session_factory()
    try:
        jobs = db.query(Job).filter(Job.id == data["job_id"]).all()
        assert len(jobs) == 1
        job = jobs[0]
        assert job.course_name == "Python Basics"
        assert job.issue_date == date(2026, 10, 13)
        assert job.total == 3
        assert job.success_count == 3
        assert job.failed_count == 0
        assert job.status == "completed"

        certs = db.query(Certificate).filter(Certificate.job_id == data["job_id"]).all()
        assert len(certs) == 3
        assert all(c.status == "success" for c in certs)
    finally:
        db.close()


def test_create_job_supports_many_recipients_in_one_request(client, certs_dir):
    data = submit(client, make_recipients(50))
    assert data["total"] == 50
    assert data["valid_count"] == 50

    response = client.get(f"/jobs/{data['job_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["success_count"] == 50
    assert body["failed_count"] == 0

    folder = os.path.join(certs_dir, data["job_id"])
    assert len(os.listdir(folder)) == 50


def test_create_job_with_mixed_recipients_reports_counts(client):
    data = submit(client, MIXED_RECIPIENTS)
    assert data["total"] == 5
    assert data["valid_count"] == 2
    assert data["invalid_count"] == 3
    assert data["status"] == "pending"


def test_create_job_with_only_invalid_recipients_is_failed_and_generates_nothing(client, certs_dir):
    data = submit(client, make_invalid_recipients(3))
    assert data["status"] == "failed"
    assert data["valid_count"] == 0
    assert data["invalid_count"] == 3
    assert os.listdir(certs_dir) == []


def test_duplicate_recipients_each_get_a_certificate(client, session_factory):
    data = submit(client, [ANNA, ANNA])
    assert data["total"] == 2
    assert data["valid_count"] == 2

    response = client.get(f"/jobs/{data['job_id']}")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["success_count"] == 2

    db = session_factory()
    try:
        certs = db.query(Certificate).filter(Certificate.job_id == data["job_id"]).all()
        assert len(certs) == 2
        assert len({c.id for c in certs}) == 2
        assert len({c.file_path for c in certs}) == 2
    finally:
        db.close()


def test_two_jobs_are_independent(client, certs_dir):
    data_a = submit(client, GOOD_RECIPIENTS)
    data_b = submit(client, MIXED_RECIPIENTS)

    assert data_a["job_id"] != data_b["job_id"]

    response_a = client.get(f"/jobs/{data_a['job_id']}")
    response_b = client.get(f"/jobs/{data_b['job_id']}")
    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert response_a.json()["status"] == "completed"
    assert response_a.json()["total"] == 2
    assert response_b.json()["status"] == "completed_with_errors"
    assert response_b.json()["total"] == 5

    folder_a = os.path.join(certs_dir, data_a["job_id"])
    folder_b = os.path.join(certs_dir, data_b["job_id"])
    assert len(os.listdir(folder_a)) == 2
    assert len(os.listdir(folder_b)) == 2