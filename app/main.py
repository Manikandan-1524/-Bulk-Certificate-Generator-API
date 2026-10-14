from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.ui import router as ui_router
from app.core.database import Base, engine
from app.models import Certificate, Job  # noqa: F401
from app.services.job_processor import recover_interrupted_jobs
from app.services.download_service import recover_abandoned_zip_temp_directories


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    recover_interrupted_jobs()
    recover_abandoned_zip_temp_directories()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(health_router)
app.include_router(jobs_router)
app.include_router(ui_router)