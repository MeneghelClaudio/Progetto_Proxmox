from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    DB_HOST: str = "db"
    DB_PORT: int = 3306
    DB_NAME: str = "proxmox_manager"
    DB_USER: str = "pmxuser"
    DB_PASSWORD: str = "pmxpass"

    # Auth
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 8  # 8h working session

    # Encryption (Fernet)
    FERNET_KEY: str = ""
    FERNET_KEY_FILE: str = "/data/fernet.key"

    # CORS
    CORS_ORIGINS: str = "*"

    @property
    def DB_URL(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )


settings = Settings()


def ensure_fernet_key() -> bytes:
    """Return the Fernet key, generating and persisting one if missing."""
    from cryptography.fernet import Fernet

    if settings.FERNET_KEY:
        return settings.FERNET_KEY.encode()

    path = Path(settings.FERNET_KEY_FILE)
    if path.exists():
        return path.read_bytes().strip()

    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key)
    path.chmod(0o600)
    return key
