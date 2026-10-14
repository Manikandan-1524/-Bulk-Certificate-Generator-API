import uuid

from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class Certificate(Base):
    __tablename__ = "certificates"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    recipient_name = Column(String, nullable=True)
    recipient_email = Column(String, nullable=True)
    status = Column(String, default="pending", nullable=False)
    file_path = Column(String, nullable=True)
    error_message = Column(String, nullable=True)

    job = relationship("Job", back_populates="certificates")