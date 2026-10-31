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
    # 세션 디브리프 요약 전용 모델(비우면 채팅 모델). 답변 코칭·꼬리질문은 채팅 모델을 쓴다
    openai_feedback_model: str = os.getenv("OPENAI_FEEDBACK_MODEL") or openai_chat_model
    # 테스트·e2e에서 가짜 서버를 가리킬 수 있게 API 주소를 바꿀 수 있다
    openai_base_url: str = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    # 음성 전사 제공자: local(faster-whisper, 외부 전송 없음) | openai | off. LLM용 OpenAI 키와 따로 정한다
    stt_provider: str = (os.getenv("STT_PROVIDER") or "local").strip().lower()
    # 로컬 전사: 다국어 Whisper 크기(tiny·base·small·medium·large-v3 등)나 모델 폴더 경로
    local_stt_model: str = os.getenv("LOCAL_STT_MODEL") or "base"
    local_stt_device: str = os.getenv("LOCAL_STT_DEVICE") or "cpu"
    local_stt_compute_type: str = os.getenv("LOCAL_STT_COMPUTE_TYPE") or "int8"
    local_stt_cpu_threads: int = int(os.getenv("LOCAL_STT_CPU_THREADS") or min(4, os.cpu_count() or 1))
    local_stt_beam_size: int = int(os.getenv("LOCAL_STT_BEAM_SIZE") or 5)
    # 모델 캐시 폴더(비우면 Hugging Face 기본 캐시 ~/.cache/huggingface). 한 번 받으면 네트워크 없이 다시 쓴다
    local_stt_model_dir: str = os.getenv("LOCAL_STT_MODEL_DIR", "")
    local_stt_allow_download: bool = os.getenv("LOCAL_STT_ALLOW_DOWNLOAD", "true").lower() == "true"
    # 다른 전사가 도는 동안 기다리는 최대 시간(초)과 자동 전사할 최대 녹음 길이(초)
    local_stt_queue_timeout_sec: float = float(os.getenv("LOCAL_STT_QUEUE_TIMEOUT_SEC") or 60)
    local_stt_max_audio_sec: float = float(os.getenv("LOCAL_STT_MAX_AUDIO_SEC") or 900)
    # 원본 녹음 보관 기간(일)과 만료 녹음 정리 주기(분)
    audio_retention_days: int = int(os.getenv("AUDIO_RETENTION_DAYS") or 30)
    purge_interval_min: int = int(os.getenv("PURGE_INTERVAL_MIN") or 60)
    cors_origins: list[str] = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]


settings = Settings()
