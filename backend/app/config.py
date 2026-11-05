import logging
import os
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent.parent
log = logging.getLogger(__name__)


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


class ConfigError(ValueError):
    """환경변수 값이 잘못됐다. 메시지에 변수 이름을 담는다(값이 비밀일 수 있는 변수는 값을 싣지 않는다)."""


def _number(env: Mapping[str, str], name: str, default, kind):
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        return kind(raw)
    except ValueError:
        what = "정수" if kind is int else "숫자"
        raise ConfigError(f"{name}은(는) {what}여야 해요(지금 값: {raw!r})") from None


class Settings:
    """환경변수(기본: os.environ, backend/.env 포함)에서 만든 설정. 테스트는 매핑을 넘겨 따로 만들 수 있다."""

    def __init__(self, env: Mapping[str, str] | None = None):
        env = os.environ if env is None else env
        self.practice_insights_enabled = env.get("PRACTICE_INSIGHTS_ENABLED", "false").lower() == "true"
        self.practice_competency_evidence_enabled = env.get("PRACTICE_COMPETENCY_EVIDENCE_ENABLED", "false").lower() == "true"
        self.database_url: str = env.get("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'jobseeker.db'}"
        # true일 때만 개발 모드(로그인 없이 X-User-Id). 그 밖의 값은 인증을 켠 것으로 본다
        self.auth_disabled: bool = env.get("AUTH_DISABLED", "false").lower() == "true"
        self.app_env: str = env.get("APP_ENV", "development").strip().lower()
        self.jwt_mode: str = env.get("SUPABASE_JWT_MODE", "hs256").strip().lower()
        self.jwt_secret: str = env.get("SUPABASE_JWT_SECRET", "")
        self.supabase_url: str = env.get("SUPABASE_URL", "").rstrip("/")
        self.supabase_service_key: str = env.get("SUPABASE_SERVICE_ROLE_KEY", "")
        self.storage_bucket: str = env.get("STORAGE_BUCKET", "recordings")
        # 로컬 녹음 폴더. e2e·테스트는 실행마다 임시 폴더를 넘겨 개발용 녹음을 건드리지 않는다
        self.local_recordings_dir: Path = Path(env.get("RECORDINGS_DIR") or BASE_DIR / "recordings")
        self.openai_api_key: str = env.get("OPENAI_API_KEY", "")
        self.openai_chat_model: str = env.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
        self.openai_stt_model: str = env.get("OPENAI_STT_MODEL", "whisper-1")
        # 세션 디브리프 요약 전용 모델(비우면 채팅 모델). 답변 코칭·꼬리질문은 채팅 모델을 쓴다
        self.openai_feedback_model: str = env.get("OPENAI_FEEDBACK_MODEL") or self.openai_chat_model
        # 테스트·e2e에서 가짜 서버를 가리킬 수 있게 API 주소를 바꿀 수 있다
        self.openai_base_url: str = (env.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        # 음성 전사 제공자: local(faster-whisper, 외부 전송 없음) | openai | off. LLM용 OpenAI 키와 따로 정한다
        self.stt_provider: str = (env.get("STT_PROVIDER") or "local").strip().lower()
        # 로컬 전사: 다국어 Whisper 크기(tiny·base·small·medium·large-v3 등)나 모델 폴더 경로
        self.local_stt_model: str = env.get("LOCAL_STT_MODEL") or "base"
        self.local_stt_device: str = env.get("LOCAL_STT_DEVICE") or "cpu"
        self.local_stt_compute_type: str = env.get("LOCAL_STT_COMPUTE_TYPE") or "int8"
        self.local_stt_cpu_threads: int = _number(env, "LOCAL_STT_CPU_THREADS", min(4, os.cpu_count() or 1), int)
        self.local_stt_beam_size: int = _number(env, "LOCAL_STT_BEAM_SIZE", 5, int)
        # 모델 캐시 폴더(비우면 Hugging Face 기본 캐시 ~/.cache/huggingface). 한 번 받으면 네트워크 없이 다시 쓴다
        self.local_stt_model_dir: str = env.get("LOCAL_STT_MODEL_DIR", "")
        self.local_stt_allow_download: bool = env.get("LOCAL_STT_ALLOW_DOWNLOAD", "true").lower() == "true"
        # 다른 전사가 도는 동안 기다리는 최대 시간(초)과 자동 전사할 최대 녹음 길이(초)
        self.local_stt_queue_timeout_sec: float = _number(env, "LOCAL_STT_QUEUE_TIMEOUT_SEC", 60.0, float)
        self.local_stt_max_audio_sec: float = _number(env, "LOCAL_STT_MAX_AUDIO_SEC", 900.0, float)
        # 원본 녹음 보관 기간(일)과 만료 녹음 정리 주기(분)
        self.audio_retention_days: int = _number(env, "AUDIO_RETENTION_DAYS", 30, int)
        self.purge_interval_min: int = _number(env, "PURGE_INTERVAL_MIN", 60, int)
        self.cors_origins: list[str] = [o.strip() for o in env.get("CORS_ORIGINS", "http://localhost:5173").split(",")
                                        if o.strip()]

    def check(self) -> None:
        """서버 시작 전에 부른다. 띄워도 동작할 수 없는 조합은 ConfigError, 배포라면 위험한 조합은 경고 로그."""
        if self.app_env == "production" and self.auth_disabled:
            raise ConfigError("APP_ENV=production에서는 AUTH_DISABLED=true를 사용할 수 없어요")
        if self.jwt_mode not in {"hs256", "jwks"}:
            raise ConfigError("SUPABASE_JWT_MODE은 hs256 또는 jwks여야 해요")
        if not self.auth_disabled:
            if self.jwt_mode == "hs256" and not self.jwt_secret:
                raise ConfigError("AUTH_DISABLED=false이면 SUPABASE_JWT_SECRET 또는 SUPABASE_JWT_MODE=jwks 설정이 필요해요")
            url = urlsplit(self.supabase_url)
            local_http = url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
            if (not url.hostname or (url.scheme != "https" and not local_http)
                    or url.username is not None or url.password is not None
                    or url.path or url.query or url.fragment):
                raise ConfigError("SUPABASE_URL에는 프로젝트의 HTTPS 원점 주소가 필요해요(로컬 루프백은 HTTP 허용)")
        if self.auth_disabled and not self.database_url.startswith("sqlite"):
            log.warning("AUTH_DISABLED=true(개발 모드)로 Postgres에 연결합니다: X-User-Id 헤더를 그대로 믿어요. "
                        "배포 환경이라면 AUTH_DISABLED=false로 두세요")


settings = Settings()
