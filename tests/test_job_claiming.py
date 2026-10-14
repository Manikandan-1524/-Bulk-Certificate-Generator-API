import os
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from app.models.certificate import Certificate
from app.models.job import Job
from app.services.job_processor import process_job


def _seed_pending_job(session_factory, certificates_dir):
    db = session_factory()
    try:
        job_id = str(uuid4())
        job = Job(
            id=job_id,
            course_name="Python Basics",
            issue_date=date(2026, 10, 13),
            status="pending",
            total=2,
            success_count=0,
            failed_count=0,
        )
        db.add(job)
        db.add_all(
            [
                Certificate(
                    id=str(uuid4()),
                    job_id=job_id,
                    recipient_name="Anna",
                    recipient_email="anna@example.com",
                    status="pending",
                ),
                Certificate(
                    id=str(uuid4()),
                    job_id=job_id,
                    recipient_name="Ravi",
                    recipient_email="ravi@example.com",
                    status="pending",
                ),
            ]
        )
        db.commit()
        return job_id
    finally:
        db.close()


@pytest.fixture(autouse=True)
def job_processor_resources(session_factory, certs_dir, monkeypatch):
    monkeypatch.setattr("app.services.job_processor.SessionLocal", session_factory)
    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", certs_dir)
    monkeypatch.setattr("app.core.config.CERTIFICATES_DIR", certs_dir)


def _counting_generator(state):
    def generate(recipient_name, course_name, issue_date, output_path):
        state["calls"] += 1
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"%PDF")

        # The job must be in processing state before generation begins.
        database = state["session_factory"]()
        try:
            status = (
                database.query(Job)
                .filter(Job.id == state["job_id"])
                .first()
                .status
            )
        finally:
            database.close()
        state["statuses_during_generation"].append(status)

    return generate


def test_pending_job_is_claimed_and_processed(session_factory, tmp_path, monkeypatch):
    certificates_dir = str(tmp_path / "certificates")
    Path(certificates_dir).mkdir(exist_ok=True)

    monkeypatch.setattr("app.services.job_processor.SessionLocal", session_factory)
    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", certificates_dir)
    monkeypatch.setattr("app.core.config.CERTIFICATES_DIR", certificates_dir)

    db = session_factory()
    try:
        db.close()
    except Exception:
        pass

    job_id = _seed_pending_job(session_factory, certificates_dir)
    generator_state = {
        "calls": 0,
        "statuses_during_generation": [],
        "job_id": job_id,
        "session_factory": session_factory,
    }
    monkeypatch.setattr(
        "app.services.job_processor.generate_certificate_pdf",
        _counting_generator(generator_state),
    )

    process_job(job_id)

    db = session_factory()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        certificates = db.query(Certificate).filter(Certificate.job_id == job_id).all()
        assert job.status == "completed"
        assert job.success_count == 2
        assert job.failed_count == 0
        assert all(certificate.status == "success" for certificate in certificates)
        assert generator_state["calls"] == 2
        assert generator_state["statuses_during_generation"] == ["processing", "processing"]
        assert os.path.isdir(os.path.join(certificates_dir, job_id))
    finally:
        db.close()


def test_duplicate_invocation_does_not_process_again(session_factory, tmp_path, monkeypatch):
    certificates_dir = str(tmp_path / "certificates")
    Path(certificates_dir).mkdir(exist_ok=True)

    monkeypatch.setattr("app.services.job_processor.SessionLocal", session_factory)
    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", certificates_dir)
    monkeypatch.setattr("app.core.config.CERTIFICATES_DIR", certificates_dir)

    job_id = _seed_pending_job(session_factory, certificates_dir)
    generator_state = {
        "calls": 0,
        "statuses_during_generation": [],
        "job_id": job_id,
        "session_factory": session_factory,
    }
    monkeypatch.setattr(
        "app.services.job_processor.generate_certificate_pdf",
        _counting_generator(generator_state),
    )

    process_job(job_id)
    first_calls = generator_state["calls"]

    process_job(job_id)

    assert first_calls == 2
    assert generator_state["calls"] == 2

    db = session_factory()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        assert job.status == "completed"
        assert job.success_count == 2
        assert job.failed_count == 0
        certificates = db.query(Certificate).filter(Certificate.job_id == job_id).all()
        assert all(certificate.status == "success" for certificate in certificates)
    finally:
        db.close()


def _seed_terminal_job(session_factory, status):
    db = session_factory()
    try:
        job_id = str(uuid4())
        job = Job(
            id=job_id,
            course_name="Python Basics",
            issue_date=date(2026, 10, 13),
            status=status,
            total=2,
            success_count=2 if status == "completed" else 0,
            failed_count=0 if status == "completed" else 2,
        )
        db.add(job)
        db.add_all(
            [
                Certificate(
                    id=str(uuid4()),
                    job_id=job_id,
                    recipient_name="Anna",
                    recipient_email="anna@example.com",
                    status="success" if status == "completed" else "failed",
                    error_message=None if status == "completed" else "Certificate generation failed",
                ),
                Certificate(
                    id=str(uuid4()),
                    job_id=job_id,
                    recipient_name="Ravi",
                    recipient_email="ravi@example.com",
                    status="success" if status == "completed" else "failed",
                    error_message=None if status == "completed" else "Certificate generation failed",
                ),
            ]
        )
        db.commit()
        return job_id
    finally:
        db.close()


def test_completed_job_is_not_processed(session_factory, tmp_path, monkeypatch):
    certificates_dir = str(tmp_path / "certificates")
    Path(certificates_dir).mkdir(exist_ok=True)
    monkeypatch.setattr("app.services.job_processor.SessionLocal", session_factory)
    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", certificates_dir)
    monkeypatch.setattr("app.core.config.CERTIFICATES_DIR", certificates_dir)

    job_id = _seed_terminal_job(session_factory, "completed")
    calls = {"count": 0}

    def generate(*arguments):
        calls["count"] += 1
        return None

    monkeypatch.setattr("app.services.job_processor.generate_certificate_pdf", generate)
    process_job(job_id)

    assert calls["count"] == 0

    db = session_factory()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        assert job.status == "completed"
        assert job.success_count == 2
        assert job.failed_count == 0
    finally:
        db.close()


def test_failed_job_is_not_processed(session_factory, tmp_path, monkeypatch):
    certificates_dir = str(tmp_path / "certificates")
    Path(certificates_dir).mkdir(exist_ok=True)
    monkeypatch.setattr("app.services.job_processor.SessionLocal", session_factory)
    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", certificates_dir)
    monkeypatch.setattr("app.core.config.CERTIFICATES_DIR", certificates_dir)

    job_id = _seed_terminal_job(session_factory, "failed")
    calls = {"count": 0}

    def generate(*arguments):
        calls["count"] += 1
        return None

    monkeypatch.setattr("app.services.job_processor.generate_certificate_pdf", generate)
    process_job(job_id)

    assert calls["count"] == 0

    db = session_factory()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        assert job.status == "failed"
        assert job.success_count == 0
        assert job.failed_count == 2
    finally:
        db.close()