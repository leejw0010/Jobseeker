import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
# 녹음도 임시 폴더에(개발용 backend/recordings/를 건드리지 않게). .env보다 먼저 정해 둔다
os.environ["RECORDINGS_DIR"] = f"{_tmp}/recordings"
os.environ["AUTH_DISABLED"] = "true"
os.environ["OPENAI_API_KEY"] = ""
os.environ["SUPABASE_URL"] = ""
os.environ["AUDIO_RETENTION_DAYS"] = "30"
os.environ["PURGE_INTERVAL_MIN"] = "60"
# 개발자가 e2e용 가짜 서버로 바꿔 둔 값(.env 포함)이 테스트에 끼어들지 않게 기본값으로 고정한다
os.environ["OPENAI_BASE_URL"] = "https://api.openai.com/v1"
os.environ["OPENAI_FEEDBACK_MODEL"] = ""
# 기존 전사 테스트는 OpenAI 경로(모의 응답)를 검사한다. 로컬 전사는 test_local_stt.py가 제공자를 바꿔 끼워 검사한다
os.environ["STT_PROVIDER"] = "openai"

os.environ["PRACTICE_INSIGHTS_ENABLED"] = "true"
os.environ["PRACTICE_COMPETENCY_EVIDENCE_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def consent(client):
    """녹음 동의(업로드 전에 필요). consent(headers, keep_audio=False)"""
    def _consent(headers: dict, keep_audio: bool = False) -> dict:
        r = client.put("/practice/settings", json={"consent": True, "keep_audio": keep_audio}, headers=headers)
        assert r.status_code == 200, r.text
        return r.json()
    return _consent


@pytest.fixture
def isolated_db(client, tmp_path, monkeypatch):
    """이 테스트만 쓰는 빈 DB와 녹음 폴더(세션 팩토리를 돌려준다).

    다른 테스트는 사용자 id로만 나뉜 공용 DB를 함께 쓴다. 만료 정리처럼 DB·저장소 전체를 훑는 작업은 그 데이터까지
    건드려 결과가 실행 순서에 따라 달라지므로, 그런 테스트는 이 픽스처로 API·백그라운드 작업·정리를 모두 새 DB에 묶는다.
    """
    from sqlalchemy.orm import sessionmaker

    from app import db as app_db
    from app import debrief, retention
    from app.config import settings
    from app.seed import seed_question_bank

    engine = app_db.make_engine(f"sqlite:///{tmp_path / 'isolated.db'}")
    app_db.upgrade_sqlite(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as s:
        seed_question_bank(s)

    def get_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    for module in (app_db, retention, debrief):
        monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(settings, "local_recordings_dir", tmp_path / "recordings")
    app.dependency_overrides[app_db.get_db] = get_db
    try:
        yield factory
    finally:
        app.dependency_overrides.pop(app_db.get_db, None)
        engine.dispose()
