"""설정 생성·검증: 환경변수 매핑에서 만들고, 잘못된 값은 이름을 붙여 알린다."""
from pathlib import Path

import pytest

from app.config import BASE_DIR, ConfigError, Settings


def test_recordings_dir_defaults_to_backend_folder():
    assert Settings({}).local_recordings_dir == BASE_DIR / "recordings"


def test_recordings_dir_can_be_injected(tmp_path):
    """e2e는 실행마다 임시 녹음 폴더를 넘겨, 개발용 backend/recordings/를 건드리지 않는다."""
    assert Settings({"RECORDINGS_DIR": str(tmp_path)}).local_recordings_dir == tmp_path


@pytest.mark.parametrize("name", ["AUDIO_RETENTION_DAYS", "PURGE_INTERVAL_MIN", "LOCAL_STT_CPU_THREADS",
                                  "LOCAL_STT_BEAM_SIZE", "LOCAL_STT_QUEUE_TIMEOUT_SEC", "LOCAL_STT_MAX_AUDIO_SEC"])
def test_bad_number_names_the_variable(name):
    with pytest.raises(ConfigError, match=name):
        Settings({name: "thirty"})


def test_numbers_and_defaults_parse():
    s = Settings({"AUDIO_RETENTION_DAYS": "7", "LOCAL_STT_QUEUE_TIMEOUT_SEC": "2.5"})
    assert s.audio_retention_days == 7
    assert s.local_stt_queue_timeout_sec == 2.5
    assert s.purge_interval_min == 60


def test_auth_enabled_without_secret_is_a_startup_error():
    """인증을 켰는데 JWT 비밀값이 없으면 모든 요청이 401이 된다: 서버를 띄우지 않고 알린다."""
    s = Settings({"AUTH_DISABLED": "false", "SUPABASE_JWT_SECRET": ""})
    with pytest.raises(ConfigError, match="SUPABASE_JWT_SECRET"):
        s.check()


def test_auth_enabled_with_secret_passes():
    Settings({"AUTH_DISABLED": "false", "SUPABASE_JWT_SECRET": "configured", "SUPABASE_URL": "https://configured.supabase.co"}).check()


def test_dev_mode_on_postgres_warns(caplog):
    s = Settings({"AUTH_DISABLED": "true", "DATABASE_URL": "postgresql+psycopg://u@h/db"})
    s.check()
    assert "AUTH_DISABLED" in caplog.text


def test_dev_mode_on_sqlite_is_quiet(caplog):
    Settings({"AUTH_DISABLED": "true"}).check()
    assert "AUTH_DISABLED" not in caplog.text


def test_unknown_auth_flag_keeps_auth_on():
    """true가 아닌 값은 인증을 켠 것으로 본다(잘못 적어도 열리지 않는다)."""
    assert Settings({"AUTH_DISABLED": "yes"}).auth_disabled is False
    assert Settings({}).auth_disabled is False


def test_conftest_isolates_recordings():
    from app.config import settings
    assert Path(settings.local_recordings_dir) != BASE_DIR / "recordings"


def test_production_refuses_auth_bypass():
    with pytest.raises(ConfigError, match="APP_ENV.*AUTH_DISABLED"):
        Settings({"APP_ENV": "production", "AUTH_DISABLED": "true"}).check()


def test_jwks_mode_requires_pinned_supabase_url():
    with pytest.raises(ConfigError, match="SUPABASE_URL"):
        Settings({"SUPABASE_JWT_MODE": "jwks"}).check()
    Settings({"SUPABASE_JWT_MODE": "jwks", "SUPABASE_URL": "https://test.supabase.co"}).check()


@pytest.mark.parametrize("url", ["https://user:pass@host", "https://host?other=x", "https://host/other", "ftp://host", "http://remote.invalid"])
def test_auth_url_must_be_project_origin(url):
    with pytest.raises(ConfigError, match="SUPABASE_URL"):
        Settings({"SUPABASE_JWT_MODE": "jwks", "SUPABASE_URL": url}).check()


def test_unknown_auth_mode_fails_closed():
    with pytest.raises(ConfigError, match="SUPABASE_JWT_MODE"):
        Settings({"SUPABASE_JWT_MODE": "none"}).check()
