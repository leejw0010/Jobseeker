import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["AUTH_DISABLED"] = "true"
os.environ["OPENAI_API_KEY"] = ""
os.environ["SUPABASE_URL"] = ""
os.environ["AUDIO_RETENTION_DAYS"] = "30"
os.environ["PURGE_INTERVAL_MIN"] = "60"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

settings.local_recordings_dir = __import__("pathlib").Path(_tmp) / "recordings"


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
