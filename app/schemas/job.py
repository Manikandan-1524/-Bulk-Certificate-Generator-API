from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

CertificateStatus = Literal["pending", "success", "failed"]


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    course_name: str = Field(min_length=1, max_length=200)
    issue_date: date
    recipients: list[dict[str, Any]] = Field(min_length=1)


class JobCreateResponse(BaseModel):
    job_id: str
    status: str
    total: int
    valid_count: int
    invalid_count: int


class JobStatusResponse(BaseModel):
    job_id: str
    course_name: str
    issue_date: date
    status: str
    total: int
    success_count: int
    failed_count: int
    pending_count: int
    progress_percent: float
    created_at: datetime


class CertificateItem(BaseModel):
    certificate_id: str
    recipient_name: str | None
    recipient_email: str | None
    status: str
    error_message: str | None
    download_url: str | None


class CertificateListResponse(BaseModel):
    job_id: str
    total: int
    limit: int
    offset: int
    certificates: list[CertificateItem]