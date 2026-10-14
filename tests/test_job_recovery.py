import os
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.certificate import Certificate
from app.models.job import Job
from app.services.job_processor import (
    INTERRUPTED_JOB_RECOVERY_REASON,
    recover_interrupted_jobs,
)


def _make_job(session_factory, status, certificate_specs):
    db = session_factory()
    try:
        job = Job(
            id=str(uuid4()),
            course_name="Python Basics",
            issue_date=date(2026, 10, 13),
            status=status,
            total=len(certificate_specs),
            success_count=sum(1 for _, certificate_status in certificate_specs if certificate_status == "success"),
            failed_count=sum(1 for _, certificate_status in certificate_specs if certificate_status == "failed"),
        )
        db.add(job)
        db.flush()

        for recipient_name, certificate_status in certificate_specs:
            db.add(
                Certificate(
                    id=str(uuid4()),
                    job_id=job.id,
                    recipient_name=recipient_name,
                    status=certificate_status,
                    file_path=f"generated_certificates/{job.id}/successful.pdf"
                    if certificate_status == "success"
                    else None,
                    error_message=(
                        "Certificate generation failed: forced failure"
                        if certificate_status == "failed"
                        else None
                    ),
                )
            )

        db.commit()
        return job.id
    finally:
        db.close()


def test_recovery_processing_job_with_success_and_pending(session_factory, monkeypatch, certs_dir):
    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", certs_dir)
    monkeypatch.setattr("app.services.job_processor.SessionLocal", session_factory)
    job_id = _make_job(
        session_factory, "processing", [("Anna", "success"), ("Ravi", "pending")]
    )

    recover_interrupted_jobs()

    db = session_factory()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        certificates = db.query(Certificate).filter(Certificate.job_id == job_id).all()
        success = next(cert for cert in certificates if cert.recipient_name == "Anna")
        pending = next(cert for cert in certificates if cert.recipient_name == "Ravi")

        assert job.status == "completed_with_errors"
        assert job.success_count == 1
        assert job.failed_count == 1
        assert success.status == "success"
        assert success.file_path is not None
        assert pending.status == "failed"
        assert pending.error_message == INTERRUPTED_JOB_RECOVERY_REASON
    finally:
        db.close()


def test_recovery_processing_job_with_no_successful_certificates(session_factory, monkeypatch, certs_dir):
    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", certs_dir)
    monkeypatch.setattr("app.services.job_processor.SessionLocal", session_factory)
    job_id = _make_job(
        session_factory, "processing", [("Anna", "pending"), ("Ravi", "pending")]
    )

    recover_interrupted_jobs()

    db = session_factory()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        certificates = db.query(Certificate).filter(Certificate.job_id == job_id).all()

        assert job.status == "failed"
        assert job.success_count == 0
        assert job.failed_count == 2
        assert all(certificate.status == "failed" for certificate in certificates)
        assert all(
            certificate.error_message == INTERRUPTED_JOB_RECOVERY_REASON
            for certificate in certificates
        )
    finally:
        db.close()


def test_recovery_processing_job_with_success_and_failed_but_no_pending(session_factory, monkeypatch, certs_dir):
    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", certs_dir)
    monkeypatch.setattr("app.services.job_processor.SessionLocal", session_factory)
    job_id = _make_job(
        session_factory,
        "processing",
        [("Anna", "success"), ("Ravi", "failed")],
    )

    recover_interrupted_jobs()

    db = session_factory()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        assert job.status == "completed_with_errors"
        assert job.success_count == 1
        assert job.failed_count == 1
    finally:
        db.close()


def test_recovery_processing_job_all_success_no_pending(session_factory, monkeypatch, certs_dir):
    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", certs_dir)
    monkeypatch.setattr("app.services.job_processor.SessionLocal", session_factory)
    job_id = _make_job(
        session_factory, "processing", [("Anna", "success"), ("Ravi", "success")]
    )

    recover_interrupted_jobs()

    db = session_factory()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        assert job.status == "completed"
        assert job.success_count == 2
        assert job.failed_count == 0
    finally:
        db.close()


def test_recovery_does_not_change_terminal_jobs(session_factory, monkeypatch, certs_dir):
    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", certs_dir)
    monkeypatch.setattr("app.services.job_processor.SessionLocal", session_factory)
    completed_job_id = _make_job(
        session_factory, "completed", [("Anna", "success")]
    )
    failed_job_id = _make_job(
        session_factory, "failed", [("Anna", "failed")]
    )

    recover_interrupted_jobs()

    db = session_factory()
    try:
        completed_job = db.query(Job).filter(Job.id == completed_job_id).first()
        failed_job = db.query(Job).filter(Job.id == failed_job_id).first()
        assert completed_job.status == "completed"
        assert completed_job.success_count == 1
        assert completed_job.failed_count == 0
        assert failed_job.status == "failed"
        assert failed_job.success_count == 0
        assert failed_job.failed_count == 1
    finally:
        db.close()


def test_recovery_with_no_processing_jobs(session_factory, monkeypatch):
    monkeypatch.setattr("app.services.job_processor.SessionLocal", session_factory)
    job_id = _make_job(session_factory, "completed", [("Anna", "success")])

    recover_interrupted_jobs()

    db = session_factory()
    try:
        assert db.query(Job).filter(Job.status == "processing").count() == 0
        job = db.query(Job).filter(Job.id == job_id).first()
        assert job.status == "completed"
    finally:
        db.close()


def test_recovery_is_idempotent(session_factory, monkeypatch, certs_dir):
    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", certs_dir)
    monkeypatch.setattr("app.services.job_processor.SessionLocal", session_factory)
    job_id = _make_job(
        session_factory, "processing", [("Anna", "success"), ("Ravi", "pending")]
    )

    recover_interrupted_jobs()
    first = session_factory()
    try:
        job = first.query(Job).filter(Job.id == job_id).first()
        first_counts = (job.status, job.success_count, job.failed_count)
    finally:
        first.close()

    recover_interrupted_jobs()

    db = session_factory()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        assert (job.status, job.success_count, job.failed_count) == first_counts
    finally:
        db.close()


def test_recovery_can_be_called_with_explicit_session(session_factory, monkeypatch):
    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", "")
    job_id = _make_job(
        session_factory, "processing", [("Anna", "pending")]
    )

    db = session_factory()
    try:
        recover_interrupted_jobs(db)
    finally:
        db.close()

    verification = session_factory()
    try:
        job = verification.query(Job).filter(Job.id == job_id).first()
        assert job.status == "failed"
        assert job.failed_count == 1
    finally:
        verification.close()


def test_startup_invokes_recovery_before_accepting_requests(monkeypatch):
    calls = []

    def fake_recovery():
        calls.append("called")

    monkeypatch.setattr("app.main.recover_interrupted_jobs", fake_recovery)
    with TestClient(app):
        pass

    assert calls == ["called"]