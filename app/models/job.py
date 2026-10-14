import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy import Date as SQLDate
from sqlalchemy.orm import relationship

from app.core.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    course_name = Column(String, nullable=False)
    issue_date = Column(SQLDate, nullable=False)
    status = Column(String, default="pending", nullable=False)
    total = Column(Integer, default=0, nullable=False)
    success_count = Column(Integer, default=0, nullable=False)
    failed_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    certificates = relationship("Certificate", back_populates="job", cascade="all, delete-orphan")