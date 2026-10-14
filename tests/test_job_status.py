from app.models.job import Job

from tests.helpers import make_invalid_recipients, make_recipients, submit


def test_status_of_completed_job(client):
    data = submit(client, make_recipients(3))
    response = client.get(f"/jobs/{data['job_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["total"] == 3
    assert body["success_count"] == 3
    assert body["failed_count"] == 0
    assert body["pending_count"] == 0
    assert body["progress_percent"] == 100.0


def test_status_of_job_with_errors(client):
    from tests.helpers import MIXED_RECIPIENTS

    data = submit(client, MIXED_RECIPIENTS)
    response = client.get(f"/jobs/{data['job_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed_with_errors"
    assert body["total"] == 5
    assert body["success_count"] == 2
    assert body["failed_count"] == 3
    assert body["pending_count"] == 0
    assert body["progress_percent"] == 100.0
    assert body["job_id"] == data["job_id"]
    assert body["course_name"] == "Python Basics"
    assert body["issue_date"] == "2026-10-13"
    assert body["created_at"] != ""


def test_status_of_job_with_only_invalid_recipients(client):
    data = submit(client, make_invalid_recipients(3))
    response = client.get(f"/jobs/{data['job_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["total"] == 3
    assert body["success_count"] == 0
    assert body["failed_count"] == 3
    assert body["pending_count"] == 0
    assert body["progress_percent"] == 100.0


def test_status_of_pending_job(client, no_background_processing):
    from tests.helpers import ANNA, RAVI

    data = submit(client, [ANNA, RAVI, {"name": "", "email": "abc"}])
    response = client.get(f"/jobs/{data['job_id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["total"] == 3
    assert body["success_count"] == 0
    assert body["failed_count"] == 1
    assert body["pending_count"] == 2
    assert body["progress_percent"] == 33.3


def test_progress_while_processing(client, session_factory, no_background_processing):
    data = submit(client, make_recipients(4))
    job_id = data["job_id"]

    db = session_factory()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        job.status = "processing"
        job.success_count = 2
        db.commit()
    finally:
        db.close()

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["success_count"] == 2
    assert body["failed_count"] == 0
    assert body["pending_count"] == 2
    assert body["progress_percent"] == 50.0


def test_progress_never_goes_above_100(client, session_factory, no_background_processing):
    data = submit(client, make_recipients(3))
    job_id = data["job_id"]

    db = session_factory()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        job.success_count = 10
        db.commit()
    finally:
        db.close()

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["progress_percent"] == 100.0
    assert body["pending_count"] == 0


def test_unknown_job_returns_404(client):
    response = client.get("/jobs/unknown-id")
    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"