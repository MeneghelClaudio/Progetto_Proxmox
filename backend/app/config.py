"""
config.py — Application settings with AWS Secrets Manager integration.

Priority order for each secret value:
  1. AWS Secrets Manager (if AWS_REGION + AWS_SECRET_NAME are set)
  2. Environment variables / .env file (fallback for local dev)

Non-sensitive config (AWS coords, CORS) always comes from env vars.
"""

import json
import logging
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── AWS Secrets Manager (non-sensitive, always from env) ──────────────────
    AWS_REGION:            str = ""   # e.g. "eu-west-1"
    AWS_SECRET_NAME:       str = ""   # e.g. "proxmox-manager/config"
    # Explicit credentials for local/Docker use.
    # On ECS/EC2 leave these empty and use the IAM task/instance role instead.
    AWS_ACCESS_KEY_ID:     str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    # ── Database (overridden by Secrets Manager when configured) ──────────────
    DB_HOST:     str = "localhost"
    DB_PORT:     int = 3306
    DB_NAME:     str = "proxmox_manager"
    DB_USER:     str = "pmxuser"
    DB_PASSWORD: str = "pmxpass"

    # ── Auth ──────────────────────────────────────────────────────────────────
    JWT_SECRET:         str = "change-me"
    JWT_ALGORITHM:      str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 8   # 8-hour working session

    # ── Encryption (Fernet) ───────────────────────────────────────────────────
    # When stored in Secrets Manager the key travels encrypted at rest.
    # If blank here AND no Secrets Manager, a key is auto-generated and saved
    # to FERNET_KEY_FILE (only useful for single-node local dev).
    FERNET_KEY:      str = ""
    FERNET_KEY_FILE: str = "/data/fernet.key"

    # ── CORS ──────────────────────────────────────────────────────────────────
    CORS_ORIGINS: str = "*"

    @property
    def DB_URL(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )


# ── Secret Manager loader ─────────────────────────────────────────────────────

def _fetch_aws_secret(secret_name: str, region: str,
                      access_key: str, secret_key: str) -> dict:
    """
    Retrieve a JSON secret from AWS Secrets Manager.

    Uses explicit credentials when provided (local/Docker).
    Falls back to IAM role when keys are empty (ECS/EC2).
    """
    import boto3

    kwargs: dict = {"region_name": region}
    if access_key and secret_key:
        kwargs["aws_access_key_id"]     = access_key
        kwargs["aws_secret_access_key"] = secret_key

    client   = boto3.client("secretsmanager", **kwargs)
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response["SecretString"])


# ── Fields that can be overridden from the secret ────────────────────────────
_SECRET_FIELDS = {
    "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
    "JWT_SECRET", "FERNET_KEY",
}


def _build_settings() -> Settings:
    """
    Build the Settings object, overlaying values from Secrets Manager
    on top of any env-var defaults.
    """
    base = Settings()

    if not base.AWS_REGION or not base.AWS_SECRET_NAME:
        logger.info(
            "AWS_REGION / AWS_SECRET_NAME not set — "
            "running with env-var config (local dev mode)."
        )
        return base

    try:
        raw = _fetch_aws_secret(
            base.AWS_SECRET_NAME,
            base.AWS_REGION,
            base.AWS_ACCESS_KEY_ID,
            base.AWS_SECRET_ACCESS_KEY,
        )
        # Keep only recognised fields; cast DB_PORT to int if present
        overrides = {}
        for k, v in raw.items():
            if k not in _SECRET_FIELDS:
                continue
            overrides[k] = int(v) if k == "DB_PORT" else str(v)

        logger.info(
            "Loaded %d secret field(s) from AWS Secrets Manager (%s).",
            len(overrides), base.AWS_SECRET_NAME,
        )
        return base.model_copy(update=overrides)

    except Exception as exc:
        logger.error(
            "Failed to load secret '%s' from AWS Secrets Manager: %s. "
            "Falling back to env vars — DO NOT use this in production!",
            base.AWS_SECRET_NAME, exc,
        )
        return base


settings = _build_settings()


# ── Fernet key helper ─────────────────────────────────────────────────────────

def ensure_fernet_key() -> bytes:
    """
    Return the Fernet key in priority order:
      1. settings.FERNET_KEY  (comes from Secrets Manager or env var)
      2. FERNET_KEY_FILE on disk  (legacy / single-node dev)
      3. Auto-generate and persist to FERNET_KEY_FILE  (last resort)

    Production deployments should always supply FERNET_KEY via Secrets Manager.
    """
    from cryptography.fernet import Fernet

    if settings.FERNET_KEY:
        return settings.FERNET_KEY.encode()

    path = Path(settings.FERNET_KEY_FILE)
    if path.exists():
        return path.read_bytes().strip()

    logger.warning(
        "No FERNET_KEY found — generating a new key and saving to %s. "
        "Store this key in AWS Secrets Manager for production use.",
        settings.FERNET_KEY_FILE,
    )
    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key)
    path.chmod(0o600)
    return key
