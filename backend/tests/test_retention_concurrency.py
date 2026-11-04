"""느린 저장소 삭제가 새로 커밋된 녹음과 그 보관 기한을 덮어쓰지 않는다."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from app import retention, storage
from app.config import settings
from app.models import PracticeAnswer, UserSettings


def _recording(client, consent):
    headers = {"X-User-Id": "user-retention-race"}
    consent(headers, keep_audio=True)
    session = client.post("/practice/sessions", headers=headers, json={"mode": "free", "count": 1}).json()
    aid = session["answers"][0]["id"]
    first = client.post(f"/practice/answers/{aid}/audio", headers=headers,
                        files={"file": ("old.webm", b"original recording", "audio/webm")})
    assert first.status_code == 200, first.text
    return headers, aid, first.json()


@pytest.mark.parametrize("deleted", [True, False], ids=["delete-succeeds", "delete-fails"])
@pytest.mark.parametrize("operation", ["purge", "delete-one", "delete-all"])
def test_old_snapshot_cannot_clear_or_expire_a_new_upload(client, consent, isolated_db, monkeypatch, deleted, operation):
    """새 업로드가 저장소 삭제 도중 커밋되면 옛 경로 삭제 결과만 처리한다."""
    headers, aid, original = _recording(client, consent)
    old_path = original["audio_path"]
    if operation == "purge":
        with isolated_db() as db:
            db.get(PracticeAnswer, aid).audio_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
    real_delete = storage.delete
    replacement = None

    def replace_while_deleting(path):
        nonlocal replacement
        if path == old_path and replacement is None:
            # 실제 API가 별도 DB 세션에서 새 녹음과 시각을 커밋한다. 이전 파일의 삭제는 여기서 계속 막아 둔다.
            replacement = {}
            result = client.post(f"/practice/answers/{aid}/audio", headers=headers,
                                 files={"file": ("new.webm", b"new recording", "audio/webm")})
            assert result.status_code == 200, result.text
            replacement = result.json()
            return real_delete(path) if deleted else False
        return real_delete(path) if deleted else False

    monkeypatch.setattr(storage, "delete", replace_while_deleting)
    with isolated_db() as db:
        if operation == "purge":
            retention.purge_expired_audio(db)
        elif operation == "delete-all":
            result = retention.delete_user_audio(db, headers["X-User-Id"])
            db.commit()
            assert (result.deleted, result.failed) == ((1, 0) if deleted else (0, 1))
        else:
            retention.delete_audio(db.get(PracticeAnswer, aid))
            db.commit()
    assert replacement
    with isolated_db() as db:
        stored = db.get(PracticeAnswer, aid)
        assert stored.audio_path == replacement["audio_path"]
        assert stored.audio_deleted_at is None
        assert stored.audio_expires_at.isoformat() == replacement["audio_expires_at"].removesuffix("Z").removesuffix("+00:00")
        assert stored.recorded_at.isoformat() == replacement["recorded_at"].removesuffix("Z").removesuffix("+00:00")
    assert (settings.local_recordings_dir / replacement["audio_path"]).read_bytes() == b"new recording"
    assert (settings.local_recordings_dir / old_path).exists() is not deleted
    assert client.get(f"/practice/answers/{aid}/audio", headers=headers).content == b"new recording"


@pytest.mark.parametrize("modified", ["fresh", "missing", "stale"])
def test_user_clear_skips_a_recording_committed_after_its_cutoff(client, consent, isolated_db, monkeypatch, modified):
    """전체 삭제 표시 직후 새 녹음을 저장해도, 그 뒤 실행되는 행 조회가 새 녹음을 고르지 않는다."""
    headers, aid, original = _recording(client, consent)
    real_list = storage.list
    orphan_path = f"{original['audio_path'].rsplit('/', 1)[0]}/orphan.webm"
    storage.save(orphan_path, b"unlinked original recording", "audio/webm")
    replacement = None
    engine = isolated_db.kw["bind"]
    replacing = False

    def listed_objects(prefix=""):
        objects = real_list(prefix)
        if modified == "fresh":
            return objects
        timestamp = None if modified == "missing" else datetime.now(timezone.utc) - timedelta(days=1)
        return [storage.StoredObject(obj.path, timestamp) for obj in objects]

    monkeypatch.setattr(storage, "list", listed_objects)

    def upload_before_rows(conn, cursor, statement, parameters, context, executemany):
        nonlocal replacement, replacing
        if replacing or replacement is not None or not statement.lstrip().startswith("SELECT practice_answers."):
            return
        replacing = True
        try:
            result = client.post(f"/practice/answers/{aid}/audio", headers=headers,
                                 files={"file": ("new.webm", b"after clear cutoff", "audio/webm")})
            assert result.status_code == 200, result.text
            replacement = result.json()
        finally:
            replacing = False

    event.listen(engine, "before_cursor_execute", upload_before_rows)
    try:
        with isolated_db() as db:
            cleared = retention.delete_user_audio(db, headers["X-User-Id"])
            db.commit()
    finally:
        event.remove(engine, "before_cursor_execute", upload_before_rows)
    assert replacement
    assert cleared.deleted == 1 and cleared.failed == 0 and not cleared.unchecked
    with isolated_db() as db:
        stored = db.get(PracticeAnswer, aid)
        assert stored.audio_path == replacement["audio_path"]
        assert stored.audio_deleted_at is None
        assert db.get(UserSettings, headers["X-User-Id"]).audio_cleared_at < stored.recorded_at
    assert (settings.local_recordings_dir / replacement["audio_path"]).read_bytes() == b"after clear cutoff"
    assert not (settings.local_recordings_dir / original["audio_path"]).exists()
    assert not (settings.local_recordings_dir / orphan_path).exists()
    assert len(real_list(f"{headers['X-User-Id']}/")) == 1
