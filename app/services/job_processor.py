import os

from app.core.config import CERTIFICATES_DIR
from app.core.database import SessionLocal
from app.models.certificate import Certificate
from app.models.job import Job
from app.services.certificate_generator import generate_certificate_pdf


def process_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job is None:
            return

        try:
            job.status = "processing"
            db.commit()

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
                        try:
                            os.remove(output_path)
                        except OSError:
                            pass
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
        interrupted_jobs = (
            db.query(Job).filter(Job.status == "processing").all()
        )
        for job in interrupted_jobs:
            db.query(Certificate).filter(
                Certificate.job_id == job.id,
                Certificate.status == "pending",
            ).update(
                {
                    "status": "failed",
                    "error_message": INTERRUPTED_JOB_RECOVERY_REASON,
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
    return len(interrupted_jobs)


# Compatibility aliases for callers that use a different conventional name.
recover_interrupted_job = recover_interrupted_jobs
recover_processing_jobs = recover_interrupted_jobs
job_status_recovery = recover_interrupted_jobs
