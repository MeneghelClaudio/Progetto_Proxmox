import logging
import ssl

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import settings

logger = logging.getLogger(__name__)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "db"}


def _ssl_args() -> dict:
    """
    Return connect_args with SSL when connecting to a remote host (e.g. RDS).
    For local dev (localhost / docker 'db' service) SSL is skipped.
    """
    if settings.DB_HOST in _LOCAL_HOSTS:
        return {}
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return {"ssl": ctx}


def _ensure_database() -> None:
    """
    Create the target database if it does not already exist.
    Connects to the MySQL server without a database name, issues
    CREATE DATABASE IF NOT EXISTS, then disconnects.
    This runs once at startup so the app never fails on a fresh RDS instance.
    """
    db_name = settings.DB_NAME
    root_url = (
        f"mysql+pymysql://{settings.DB_USER}:{settings.DB_PASSWORD}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/?charset=utf8mb4"
    )
    try:
        tmp_engine = create_engine(
            root_url,
            pool_pre_ping=True,
            future=True,
            connect_args=_ssl_args(),
        )
        with tmp_engine.connect() as conn:
            conn.execute(text(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            ))
            conn.commit()
        tmp_engine.dispose()
        logger.info("Database '%s' ready.", db_name)
    except Exception as exc:
        logger.warning("Could not ensure database '%s': %s", db_name, exc)


_ensure_database()

engine = create_engine(
    settings.DB_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    future=True,
    connect_args=_ssl_args(),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a db session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
