from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

options = {}
if settings.session_environment == "production":
    options = dict(
        hide_parameters=True,
        pool_size=3,
        max_overflow=1,
        pool_timeout=3,
        connect_args={
            "connect_timeout": 3,
            "options": (
                "-c statement_timeout=5000 -c lock_timeout=2000 "
                "-c idle_in_transaction_session_timeout=5000"
            ),
        },
    )
engine = create_engine(settings.database_url, pool_pre_ping=True, **options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    with SessionLocal() as session:
        yield session
