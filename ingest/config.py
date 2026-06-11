import os
import pathlib


def read_secret(name: str, default: str = "") -> str:
    """Read a Docker secret from /run/secrets/ or fall back to env var."""
    base = pathlib.Path("/run/secrets")
    secret_path = (base / name).resolve()
    # Prevent path traversal
    if not str(secret_path).startswith(str(base)):
        raise ValueError(f"Invalid secret name: {name}")
    if secret_path.exists():
        return secret_path.read_text().strip()
    return os.getenv(name.upper(), default)


class Settings:
    DB_PASSWORD: str = read_secret("db_password", "postgres")
    DB_USER: str = os.getenv("POSTGRES_USER", "mundial")
    DB_NAME: str = os.getenv("POSTGRES_DB", "mundial")
    DB_HOST: str = os.getenv("POSTGRES_HOST", "postgres")
    DB_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))


settings = Settings()
