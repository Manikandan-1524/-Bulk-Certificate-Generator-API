from app.models.certificate import Certificate
from app.models.job import Job
from app.schemas.job import JobCreateRequest
from app.services.validation import validate_recipient


def create_job(db, data: JobCreateRequest):
    try:
        job = Job(course_name=data.course_name, issue_date=data.issue_date, total=len(data.recipients))
        db.add(job)
        db.flush()

        certificates = []
        invalid_count = 0
        for recipient in data.recipients:
            name, email, error_message = validate_recipient(recipient)
            if error_message is None:
                status = "pending"
            else:
                status = "failed"
                invalid_count += 1
            certificates.append(
                Certificate(
                    job_id=job.id,
                    recipient_name=name,
                    recipient_email=email,
                    status=status,
                    error_message=error_message,
                )
            )

        db.add_all(certificates)
        job.failed_count = invalid_count
        job.success_count = 0
        valid_count = len(data.recipients) - invalid_count
        job.status = "failed" if valid_count == 0 else "pending"

        db.commit()
        return job, valid_count, invalid_count
    except Exception:
        db.rollback()
        raise