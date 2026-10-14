import os
from pathlib import Path

from app.core.config import CERTIFICATES_DIR
from app.core.database import SessionLocal
from app.models.certificate import Certificate
from app.models.job import Job
from app.services.certificate_generator import generate_certificate_pdf


def _safe_remove_generated_pdf(output_path) -> None:
    """Delete a generated partial only if it stays inside CERTIFICATES_DIR."""
    if not isinstance(output_path, str):
        return

    configured_base = globals().get("CERTIFICATES_DIR", CERTIFICATES_DIR)
    try:
        base = Path(configured_base).resolve(strict=False)
        candidate = Path(output_path).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return

    try:
        candidate.relative_to(base)
    except ValueError:
        return

    if not candidate.is_file():
        return

    try:
        os.remove(candidate)
    except OSError:
        pass


# Backwards-compatible names for direct tests and future callers.
safe_remove_generated_pdf = _safe_remove_generated_pdf
safe_remove_certificate_file = _safe_remove_generated_pdf
cleanup_partial_certificate_file = _safe_remove_generated_pdf


def process_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            return

        # Atomically claim a pending job so duplicate background tasks or repeated
        # processing calls cannot generate certificates or advance the same job twice.
        claimed = (
            db.query(Job)
            .filter(Job.id == job_id, Job.status == "pending")
            .update({"status": "processing"}, synchronize_session=False)
        )
        db.commit()

        if claimed != 1:
            return

        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            return

        try:
            pending = (
                db.query(Certificate)
                .filter(Certificate.job_id == job_id, Certificate.status == "pending")
                .all()
            )

            for certificate in pending:
                output_path = os.path.join(CERTIFICATES_DIR, job_id, f"{certificate.id}.pdf")
                try:
                    generate_certificate_pdf(
                        certificate.recipient_name, job.course_name, job.issue_date, output_path
                    )
                except Exception as error:
                    if os.path.exists(output_path):
                        _safe_remove_generated_pdf(output_path)
                    certificate.status = "failed"
                    certificate.error_message = f"Certificate generation failed: {error}"
                    job.failed_count += 1
                else:
                    certificate.status = "success"
                    certificate.file_path = output_path
                    job.success_count += 1
                db.commit()

        except Exception:
            db.rollback()
            db.query(Certificate).filter(
                Certificate.job_id == job_id, Certificate.status == "pending"
            ).update(
                {"status": "failed", "error_message": "Processing stopped unexpectedly"},
                synchronize_session=False,
            )
            db.commit()

        success = (
            db.query(Certificate)
            .filter(Certificate.job_id == job_id, Certificate.status == "success")
            .count()
        )
        failed = (
            db.query(Certificate)
            .filter(Certificate.job_id == job_id, Certificate.status == "failed")
            .count()
        )
        job = db.query(Job).filter(Job.id == job_id).first()
        job.success_count = success
        job.failed_count = failed
        if success == 0:
            job.status = "failed"
        elif failed == 0:
            job.status = "completed"
        else:
            job.status = "completed_with_errors"
        db.commit()
    finally:
        db.close()


INTERRUPTED_JOB_RECOVERY_REASON = (
    "Processing stopped unexpectedly during application restart"
)

STALE_PENDING_JOB_RECOVERY_REASON = (
    "Processing did not start before application shutdown"
)


def recover_interrupted_jobs(db=None):
    """Finalize jobs abandoned in ``processing`` by a previous shutdown.

    The function only touches certificate rows that are still ``pending`` and
    never resumes generation, which keeps it idempotent and avoids duplicate PDF
    generation.
    """

    owns_session = db is None
    if owns_session:
        db = SessionLocal()

    try:
        # Startup is the only point where a persisted pending job cannot have
        # an actively queued background task. Treat both statuses as stale before
        # the application accepts requests, without resubmitting anything.
        recoverable_jobs = (
            db.query(Job)
            .filter(Job.status.in_(("processing", "pending")))
            .all()
        )
        for job in recoverable_jobs:
            reason = (
                INTERRUPTED_JOB_RECOVERY_REASON
                if job.status == "processing"
                else STALE_PENDING_JOB_RECOVERY_REASON
            )
            db.query(Certificate).filter(
                Certificate.job_id == job.id,
                Certificate.status == "pending",
            ).update(
                {
                    "status": "failed",
                    "error_message": reason,
                },
                synchronize_session=False,
            )

            success = (
                db.query(Certificate)
                .filter(
                    Certificate.job_id == job.id,
                    Certificate.status == "success",
                )
                .count()
            )
            failed = (
                db.query(Certificate)
                .filter(
                    Certificate.job_id == job.id,
                    Certificate.status == "failed",
                )
                .count()
            )

            job.success_count = success
            job.failed_count = failed
            if success == 0:
                job.status = "failed"
            elif failed == 0:
                job.status = "completed"
            else:
                job.status = "completed_with_errors"

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        if owns_session:
            db.close()
    return len(recoverable_jobs)


# Compatibility aliases for callers that use a different conventional name.
recover_interrupted_job = recover_interrupted_jobs
recover_processing_jobs = recover_interrupted_jobs
job_status_recovery = recover_interrupted_jobs
