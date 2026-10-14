from app.models.certificate import Certificate
from app.models.job import Job
from app.schemas.job import CertificateItem, JobStatusResponse


def get_job(db, job_id: str) -> Job | None:
    return db.query(Job).filter(Job.id == job_id).first()


def build_job_status(job: Job) -> JobStatusResponse:
    pending_count = max(job.total - job.success_count - job.failed_count, 0)
    if job.total <= 0:
        progress_percent = 0.0
    else:
        progress_percent = min(
            round((job.success_count + job.failed_count) / job.total * 100, 1),
            100.0,
        )
    return JobStatusResponse(
        job_id=job.id,
        course_name=job.course_name,
        issue_date=job.issue_date,
        status=job.status,
        total=job.total,
        success_count=job.success_count,
        failed_count=job.failed_count,
        pending_count=pending_count,
        progress_percent=progress_percent,
        created_at=job.created_at,
    )


def list_certificates(
    db, job_id: str, status: str | None, limit: int, offset: int
) -> tuple[int, list[Certificate]]:
    query = db.query(Certificate).filter(Certificate.job_id == job_id)
    if status is not None:
        query = query.filter(Certificate.status == status)
    total = query.count()
    items = (
        query.order_by(Certificate.recipient_name, Certificate.id)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return total, items


def build_certificate_item(job_id: str, certificate: Certificate) -> CertificateItem:
    download_url = None
    if certificate.status == "success":
        download_url = f"/jobs/{job_id}/certificates/{certificate.id}/download"
    return CertificateItem(
        certificate_id=certificate.id,
        recipient_name=certificate.recipient_name,
        recipient_email=certificate.recipient_email,
        status=certificate.status,
        error_message=certificate.error_message,
        download_url=download_url,
    )