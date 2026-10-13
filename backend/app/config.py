import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env = BASE_DIR / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


class Settings:
    database_url: str = os.getenv("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'jobseeker.db'}"
    auth_disabled: bool = os.getenv("AUTH_DISABLED", "true").lower() == "true"
    jwt_secret: str = os.getenv("SUPABASE_JWT_SECRET", "")
    supabase_url: str = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_service_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    storage_bucket: str = os.getenv("STORAGE_BUCKET", "recordings")
    local_recordings_dir: Path = BASE_DIR / "recordings"
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_chat_model: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    openai_stt_model: str = os.getenv("OPENAI_STT_MODEL", "whisper-1")
    cors_origins: list[str] = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]


settings = Settings()
