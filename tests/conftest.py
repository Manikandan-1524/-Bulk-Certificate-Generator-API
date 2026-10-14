import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401  (registers the tables with Base)
from app.core.database import Base, get_db
from app.main import app


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield factory
    engine.dispose()


@pytest.fixture()
def certs_dir(tmp_path):
    path = tmp_path / "certificates"
    path.mkdir()
    return str(path)


@pytest.fixture()
def client(session_factory, certs_dir, monkeypatch):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("app.services.job_processor.SessionLocal", session_factory)
    monkeypatch.setattr("app.services.job_processor.CERTIFICATES_DIR", certs_dir)
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def no_background_processing(monkeypatch):
    # Jobs stay "pending" because process_job does nothing.
    monkeypatch.setattr("app.api.jobs.process_job", lambda job_id: None)