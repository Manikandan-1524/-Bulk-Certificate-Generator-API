import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.core.database import get_db
from app.models import Certificate
from app.schemas.job import (
    CertificateListResponse,
    CertificateStatus,
    JobCreateRequest,
    JobCreateResponse,
    JobStatusResponse,
)
from app.services.download_service import build_job_zip, permitted_download_path, safe_name
from app.services.job_processor import process_job
from app.services.job_query import (
    build_certificate_item,
    build_job_status,
    get_job,
    list_certificates,
)
from app.services.job_service import create_job


router = APIRouter(prefix="/jobs")


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=JobCreateResponse)
def create_job_endpoint(data: JobCreateRequest, background_tasks: BackgroundTasks, db=Depends(get_db)):
    job, valid_count, invalid_count = create_job(db, data)
    if valid_count > 0:
        background_tasks.add_task(process_job, job.id)
    return JobCreateResponse(
        job_id=job.id,
        status=job.status,
        total=job.total,
        valid_count=valid_count,
        invalid_count=invalid_count,
    )


def _get_job_or_404(db, job_id):
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, db=Depends(get_db)):
    job = _get_job_or_404(db, job_id)
    return build_job_status(job)


@router.get("/{job_id}/certificates", response_model=CertificateListResponse)
def get_certificates(
    job_id: str,
    status_filter: CertificateStatus | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
):
    _get_job_or_404(db, job_id)
    total, items = list_certificates(db, job_id, status_filter, limit, offset)
    return CertificateListResponse(
        job_id=job_id,
        total=total,
        limit=limit,
        offset=offset,
        certificates=[build_certificate_item(job_id, c) for c in items],
    )


@router.get("/{job_id}/certificates/{certificate_id}/download")
def download_certificate(job_id: str, certificate_id: str, db=Depends(get_db)):
    _get_job_or_404(db, job_id)
    certificate = (
        db.query(Certificate)
        .filter(Certificate.id == certificate_id, Certificate.job_id == job_id)
        .first()
    )
    if certificate is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if certificate.status != "success":
        raise HTTPException(
            status_code=409, detail=f"Certificate is not available (status: {certificate.status})"
        )
    allowed_path = permitted_download_path(certificate.file_path)
    if allowed_path is None:
        raise HTTPException(status_code=404, detail="Certificate file not found")
    return FileResponse(
        str(allowed_path),
        media_type="application/pdf",
        filename=f"{safe_name(certificate.recipient_name)}_certificate.pdf",
    )


@router.get("/{job_id}/download")
def download_job_zip(job_id: str, db=Depends(get_db)):
    job = _get_job_or_404(db, job_id)
    if job.status in ("pending", "processing"):
        raise HTTPException(status_code=409, detail="Job is still being processed")
    certificates = (
        db.query(Certificate)
        .filter(Certificate.job_id == job.id, Certificate.status == "success")
        .all()
    )
    zip_path = build_job_zip(certificates)
    if zip_path is None:
        raise HTTPException(status_code=404, detail="No certificates available for download")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"certificates_{job_id}.zip",
        background=BackgroundTask(os.remove, zip_path),
    )