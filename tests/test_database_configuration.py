from sqlalchemy import text

from app.core.database import engine


def test_sqlite_connections_use_30_second_busy_timeout():
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA busy_timeout")).scalar() == 30000