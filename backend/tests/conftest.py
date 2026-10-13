import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["AUTH_DISABLED"] = "true"
os.environ["OPENAI_API_KEY"] = ""
os.environ["SUPABASE_URL"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

settings.local_recordings_dir = __import__("pathlib").Path(_tmp) / "recordings"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
