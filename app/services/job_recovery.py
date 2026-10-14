"""Compatibility module for interrupted-job recovery imports."""

from app.services.job_processor import recover_interrupted_jobs

__all__ = ["recover_interrupted_jobs"]