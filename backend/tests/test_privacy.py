"""P0-1: 녹음 동의, 원본 녹음 기본 삭제·보관 기한, 만료 정리."""
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from app import llm, retention, storage
from app.config import settings
from app.db import SessionLocal
from app.models import PracticeAnswer, PracticeSession, Question
from app.retention import purge_expired_audio, run_purge

AUDIO = {"file": ("a.webm", b"\x1aE\xdf\xa3fakewebm", "audio/webm")}


def _session(client, h, n=1):
    bank = client.get("/practice/questions", params={"source": "bank"}, headers=h).json()
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"] for q in bank[:n]]}, headers=h)
    assert s.status_code == 201, s.text
    return s.json()


def _upload(client, h, aid):
    return client.post(f"/practice/answers/{aid}/audio", files=AUDIO, data={"duration_sec": "30"}, headers=h)


def _ts(v: str) -> datetime:
    return datetime.fromisoformat(v)


def _file(answer: dict):
    return settings.local_recordings_dir / answer["audio_path"]


def test_consent_required_then_upload_keeps_audio_when_stt_unavailable(client):
    h = {"X-User-Id": "user-consent"}
    st = client.get("/practice/settings", headers=h).json()
    assert st == {"consented_at": None, "keep_audio": False, "retention_days": 30}
    s = _session(client, h)
    aid = s["answers"][0]["id"]
    r = _upload(client, h, aid)
    assert r.status_code == 403 and r.json()["detail"] == "녹음 전에 동의가 필요합니다"

    st = client.put("/practice/settings", json={"consent": True}, headers=h).json()
    assert st["consented_at"] and st["keep_audio"] is False
    first = st["consented_at"]
    # 다시 동의해도 처음 동의 시각은 그대로
    assert client.put("/practice/settings", json={"consent": True}, headers=h).json()["consented_at"] == first

    a = _upload(client, h, aid).json()
    assert a["stt_status"] == "unavailable" and a["audio_available"] and a["recorded_at"]
    expected = datetime.now(timezone.utc) + timedelta(days=30)
    assert abs((_ts(a["audio_expires_at"]) - expected).total_seconds()) < 60
    assert client.get(f"/practice/answers/{aid}/audio", headers=h).status_code == 200


def test_text_answer_needs_no_consent_but_audio_does(client):
    """글 답변·코칭·종료에는 녹음 동의가 필요 없다. 녹음 업로드와 전사 다시 시도만 동의를 확인한다."""
    h = {"X-User-Id": "user-text-only"}
    s = _session(client, h)
    aid = s["answers"][0]["id"]
    a = client.patch(f"/practice/answers/{aid}", json={"transcript": "제가 직접 정리한 글 답변입니다."}, headers=h)
    assert a.status_code == 200 and a.json()["recorded_at"] is None and a.json()["audio_available"] is False
    assert client.post(f"/practice/answers/{aid}/coach", headers=h).json()["coaching_report"]["method"] == "basic"
    assert client.post(f"/practice/sessions/{s['id']}/finish", headers=h).status_code == 200
    r = _upload(client, h, aid)
    assert r.status_code == 403 and r.json()["detail"] == "녹음 전에 동의가 필요합니다"
    assert client.post(f"/practice/answers/{aid}/transcribe", headers=h).status_code == 403
    assert client.get("/practice/settings", headers=h).json()["consented_at"] is None
    me = next(x for x in client.get("/practice/sessions", headers=h).json() if x["id"] == s["id"])
    assert me["recorded_count"] == 0  # 글 답변은 녹음으로 세지 않는다


def test_successful_transcription_deletes_raw_audio(client, monkeypatch, consent):
    h = {"X-User-Id": "user-stt-done"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(llm, "transcribe", lambda audio, filename, ctype: "프로젝트에서 API를 개선했습니다")
    consent(h)
    s = _session(client, h, 2)
    aid = s["answers"][0]["id"]
    a = _upload(client, h, aid).json()
    assert a["stt_status"] == "done" and a["transcript"] == "프로젝트에서 API를 개선했습니다"
    assert a["audio_available"] is False and a["audio_path"] is None
    assert a["audio_deleted_at"] and a["recorded_at"] and a["duration_sec"] == 30
    assert not list(settings.local_recordings_dir.glob(f"{h['X-User-Id']}/**/*.webm"))
    r = client.get(f"/practice/answers/{aid}/audio", headers=h)
    assert r.status_code == 404 and r.json()["detail"] == "원본 녹음은 삭제됐어요"

    client.post(f"/practice/sessions/{s['id']}/finish", headers=h)
    me = next(x for x in client.get("/practice/sessions", headers=h).json() if x["id"] == s["id"])
    assert me["recorded_count"] == 1  # 원본이 지워져도 녹음한 답변으로 센다


def test_keep_audio_true_keeps_audio(client, monkeypatch, consent):
    h = {"X-User-Id": "user-keep"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(llm, "transcribe", lambda audio, filename, ctype: "보관할 답변")
    assert consent(h, keep_audio=True)["keep_audio"] is True
    aid = _session(client, h)["answers"][0]["id"]
    a = _upload(client, h, aid).json()
    assert a["stt_status"] == "done" and a["audio_available"] and a["audio_deleted_at"] is None
    expected = datetime.now(timezone.utc) + timedelta(days=30)
    assert abs((_ts(a["audio_expires_at"]) - expected).total_seconds()) < 60
    assert client.get(f"/practice/answers/{aid}/audio", headers=h).status_code == 200


def test_failed_transcription_keeps_audio_then_retry_deletes(client, monkeypatch, consent):
    h = {"X-User-Id": "user-retry"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")

    def broken(audio, filename, ctype):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(llm, "transcribe", broken)
    consent(h)
    aid = _session(client, h)["answers"][0]["id"]
    a = _upload(client, h, aid).json()
    assert a["stt_status"] == "failed" and a["audio_available"] and a["audio_expires_at"]

    monkeypatch.setattr(llm, "transcribe", lambda audio, filename, ctype: "다시 전사한 답변")
    a = client.post(f"/practice/answers/{aid}/transcribe", headers=h).json()
    assert a["stt_status"] == "done" and a["transcript"] == "다시 전사한 답변"
    assert a["audio_available"] is False and a["audio_deleted_at"]
    r = client.post(f"/practice/answers/{aid}/transcribe", headers=h)
    assert r.status_code == 404 and r.json()["detail"] == "원본 녹음은 삭제됐어요"


def test_purge_with_future_now_deletes_expired_audio_and_file(client, consent):
    h = {"X-User-Id": "user-purge"}
    consent(h, keep_audio=True)
    s = _session(client, h)
    aid = s["answers"][0]["id"]
    a = _upload(client, h, aid).json()
    f = _file(a)
    assert f.exists()

    with SessionLocal() as db:
        purge_expired_audio(db)  # 아직 기한 전
    assert f.exists()

    with SessionLocal() as db:
        n = purge_expired_audio(db, now=datetime.now(timezone.utc) + timedelta(days=31))
    assert n >= 1 and not f.exists()
    a = client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"][0]
    assert a["audio_available"] is False and a["audio_deleted_at"] and a["recorded_at"]
    assert client.get(f"/practice/answers/{aid}/audio", headers=h).status_code == 404


def _legacy_answer(db, user_id: str, days_old: int) -> PracticeAnswer:
    q = db.query(Question).filter(Question.user_id.is_(None)).first()
    created = datetime.now(timezone.utc) - timedelta(days=days_old)
    sid, aid = str(uuid.uuid4()), str(uuid.uuid4())
    s = PracticeSession(id=sid, user_id=user_id, mode="free", title="예전 세션", created_at=created)
    a = PracticeAnswer(id=aid, question=q, order_no=1, audio_path=f"{user_id}/{sid}/{aid}.webm", created_at=created)
    s.answers = [a]
    db.add(s)
    db.commit()
    f = settings.local_recordings_dir / a.audio_path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"old")
    return a


def test_purge_legacy_rows_without_expiry(client):
    with SessionLocal() as db:
        old = _legacy_answer(db, "user-legacy", 40)
        recent = _legacy_answer(db, "user-legacy", 5)
        assert old.audio_expires_at is None
        old_file = settings.local_recordings_dir / old.audio_path
        recent_file = settings.local_recordings_dir / recent.audio_path
    with SessionLocal() as db:
        assert purge_expired_audio(db) >= 1
        assert db.get(PracticeAnswer, old.id).audio_path is None
        assert db.get(PracticeAnswer, old.id).audio_deleted_at is not None
        assert db.get(PracticeAnswer, recent.id).audio_path == recent.audio_path
    assert not old_file.exists() and recent_file.exists()


def test_purge_keeps_row_when_storage_delete_fails(client, monkeypatch):
    with SessionLocal() as db:
        a = _legacy_answer(db, "user-storage-down", 60)
    monkeypatch.setattr(storage, "delete", lambda path: False)
    with SessionLocal() as db:
        purge_expired_audio(db)
        assert db.get(PracticeAnswer, a.id).audio_path == a.audio_path  # 다음 정리 때 다시 시도
    monkeypatch.undo()
    with SessionLocal() as db:
        purge_expired_audio(db)
        assert db.get(PracticeAnswer, a.id).audio_path is None


def test_purge_errors_do_not_escape(monkeypatch):
    def boom(db, now=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(retention, "purge_expired_audio", boom)
    assert run_purge() == 0


def test_delete_answer_audio_and_all_recordings(client, consent):
    h = {"X-User-Id": "user-delete-rec"}
    consent(h, keep_audio=True)
    s = _session(client, h, 2)
    a1, a2 = (x["id"] for x in s["answers"])
    f1, f2 = _file(_upload(client, h, a1).json()), _file(_upload(client, h, a2).json())
    client.patch(f"/practice/answers/{a1}", json={"transcript": "직접 입력한 답변"}, headers=h)

    other = {"X-User-Id": "user-delete-rec-other"}
    assert client.delete(f"/practice/answers/{a1}/audio", headers=other).status_code == 404
    assert f1.exists()

    a = client.delete(f"/practice/answers/{a1}/audio", headers=h).json()
    assert a["audio_available"] is False and a["audio_deleted_at"] and a["transcript"] == "직접 입력한 답변"
    assert not f1.exists()
    assert client.get(f"/practice/answers/{a1}/audio", headers=h).json()["detail"] == "원본 녹음은 삭제됐어요"

    assert client.delete("/practice/recordings", headers=other).json() == {"deleted": 0, "failed": 0}
    assert client.delete("/practice/recordings", headers=h).json() == {"deleted": 1, "failed": 0}
    assert not f2.exists()
    me = next(x for x in client.get("/practice/sessions", headers=h).json() if x["id"] == s["id"])
    assert me["recorded_count"] == 2


def test_consent_withdrawal_deletes_audio_and_blocks_upload(client, consent):
    h = {"X-User-Id": "user-withdraw"}
    consent(h, keep_audio=True)
    s = _session(client, h)
    aid = s["answers"][0]["id"]
    f = _file(_upload(client, h, aid).json())
    client.patch(f"/practice/answers/{aid}", json={"transcript": "남아야 하는 전사문", "self_rating": 3}, headers=h)

    st = client.put("/practice/settings", json={"consent": False}, headers=h).json()
    assert st["consented_at"] is None and st["keep_audio"] is True
    assert (st["deleted"], st["failed"]) == (1, 0)
    assert not f.exists()
    a = client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"][0]
    assert a["audio_available"] is False and a["transcript"] == "남아야 하는 전사문" and a["self_rating"] == 3
    assert _upload(client, h, aid).status_code == 403


def test_settings_are_per_user(client, consent):
    h1, h2 = {"X-User-Id": "user-set-1"}, {"X-User-Id": "user-set-2"}
    consent(h1, keep_audio=True)
    assert client.get("/practice/settings", headers=h2).json()["consented_at"] is None
    client.put("/practice/settings", json={"keep_audio": False}, headers=h2)
    st = client.get("/practice/settings", headers=h1).json()
    assert st["consented_at"] and st["keep_audio"] is True
    # keep_audio만 바꾸면 동의 상태는 그대로
    st = client.put("/practice/settings", json={"keep_audio": False}, headers=h1).json()
    assert st["consented_at"] and st["keep_audio"] is False


def test_supabase_delete_results(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://sb.invalid")
    monkeypatch.setattr(settings, "supabase_service_key", "service")
    calls = []

    def respond(status, body=None):
        def fake(url, headers=None, timeout=None):
            calls.append(url)
            return httpx.Response(status, json=body if body is not None else {})
        return fake

    monkeypatch.setattr(storage.httpx, "delete", respond(200))
    assert storage.delete("u/s/a.webm") is True
    assert calls[-1] == "https://sb.invalid/storage/v1/object/recordings/u/s/a.webm"
    monkeypatch.setattr(storage.httpx, "delete", respond(404))
    assert storage.delete("u/s/a.webm") is True
    monkeypatch.setattr(storage.httpx, "delete", respond(400, {"statusCode": "404", "error": "not_found"}))
    assert storage.delete("u/s/a.webm") is True
    monkeypatch.setattr(storage.httpx, "delete", respond(500))
    assert storage.delete("u/s/a.webm") is False

    def down(url, headers=None, timeout=None):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(storage.httpx, "delete", down)
    assert storage.delete("u/s/a.webm") is False


def _storage_down(monkeypatch):
    monkeypatch.setattr(storage, "delete", lambda path: False)


def _purge_now():
    with SessionLocal() as db:
        return purge_expired_audio(db)


def test_failed_delete_after_transcription_is_retried_by_next_purge(client, monkeypatch, consent):
    h = {"X-User-Id": "user-del-fail-stt"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(llm, "transcribe", lambda audio, filename, ctype: "전사된 답변입니다")
    consent(h)
    aid = _session(client, h)["answers"][0]["id"]
    with monkeypatch.context() as m:
        _storage_down(m)
        a = _upload(client, h, aid).json()
    # 전사 직후 지우지 못했으면 보관 기한을 지금으로 당겨, 30일이 아니라 다음 정리 때 다시 지운다
    assert a["stt_status"] == "done" and a["audio_available"]
    assert _ts(a["audio_expires_at"]) <= datetime.now(timezone.utc)
    f = _file(a)
    assert f.exists()
    assert _purge_now() >= 1 and not f.exists()
    assert client.get(f"/practice/answers/{aid}/audio", headers=h).status_code == 404


def test_failed_deletes_are_reported_and_retried(client, monkeypatch, consent):
    h = {"X-User-Id": "user-del-fail-all"}
    consent(h, keep_audio=True)
    s = _session(client, h, 2)
    files = [_file(_upload(client, h, a["id"]).json()) for a in s["answers"]]
    with monkeypatch.context() as m:
        _storage_down(m)
        assert client.delete("/practice/recordings", headers=h).json() == {"deleted": 0, "failed": 2}
        st = client.put("/practice/settings", json={"consent": False}, headers=h).json()
        assert st["consented_at"] is None and (st["deleted"], st["failed"]) == (0, 2)
        assert _purge_now() == 0  # 저장소가 아직 안 되면 그대로 둔다
    assert all(f.exists() for f in files)
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"]
    assert all(_ts(a["audio_expires_at"]) <= datetime.now(timezone.utc) for a in got)
    # 저장소가 돌아오면 다음 만료 정리가(동의를 철회한 사용자라도) 다시 지운다
    assert _purge_now() >= 2 and not any(f.exists() for f in files)
    got = client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"]
    assert all(not a["audio_available"] and a["audio_deleted_at"] for a in got)


def test_failed_delete_answer_audio_is_retried(client, monkeypatch, consent):
    h = {"X-User-Id": "user-del-fail-one"}
    consent(h, keep_audio=True)
    aid = _session(client, h)["answers"][0]["id"]
    f = _file(_upload(client, h, aid).json())
    with monkeypatch.context() as m:
        _storage_down(m)
        r = client.delete(f"/practice/answers/{aid}/audio", headers=h)
    assert r.status_code == 502 and f.exists()
    assert _purge_now() >= 1 and not f.exists()


def test_row_deletes_remove_audio_first_or_keep_rows(client, monkeypatch, consent):
    """세션·질문을 지우면 원본 녹음을 먼저 지우고, 못 지우면 행을 남겨(502) 녹음이 고아가 되지 않게 한다."""
    h = {"X-User-Id": "user-del-rows"}
    consent(h, keep_audio=True)
    q = client.post("/practice/questions", json={"category": "인성", "text": "좌우명이 무엇인가요?"}, headers=h).json()
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"]]}, headers=h).json()
    s2 = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"]]}, headers=h).json()
    f1 = _file(_upload(client, h, s["answers"][0]["id"]).json())
    f2 = _file(_upload(client, h, s2["answers"][0]["id"]).json())

    with monkeypatch.context() as m:
        _storage_down(m)
        assert client.delete(f"/practice/sessions/{s['id']}", headers=h).status_code == 502
        assert client.delete(f"/practice/questions/{q['id']}", headers=h).status_code == 502
    assert client.get(f"/practice/sessions/{s['id']}", headers=h).status_code == 200 and f1.exists()
    assert any(x["id"] == q["id"] for x in client.get("/practice/questions", headers=h).json())

    assert client.delete(f"/practice/sessions/{s['id']}", headers=h).status_code == 204
    assert not f1.exists()
    assert client.delete(f"/practice/questions/{q['id']}", headers=h).status_code == 204
    assert not f2.exists()


def test_rerecord_with_other_extension_keeps_old_path_when_delete_fails(client, monkeypatch, consent):
    h = {"X-User-Id": "user-rerecord-ext"}
    consent(h, keep_audio=True)
    aid = _session(client, h)["answers"][0]["id"]
    old = _upload(client, h, aid).json()
    m4a = {"file": ("a.m4a", b"fake-m4a", "audio/mp4")}
    with monkeypatch.context() as m:
        _storage_down(m)
        r = client.post(f"/practice/answers/{aid}/audio", files=m4a, headers=h)
    assert r.status_code == 502
    a = client.get(f"/practice/sessions/{_session_of(aid)}", headers=h).json()["answers"][0]
    assert a["audio_path"] == old["audio_path"] and _file(old).exists()  # 경로를 잃지 않는다
    new = client.post(f"/practice/answers/{aid}/audio", files=m4a, headers=h).json()
    assert new["audio_path"].endswith(".m4a") and not _file(old).exists() and _file(new).exists()


def _session_of(answer_id: str) -> str:
    with SessionLocal() as db:
        return db.get(PracticeAnswer, answer_id).session_id


def test_retry_transcribe_requires_consent(client, monkeypatch, consent):
    h = {"X-User-Id": "user-retry-consent"}
    consent(h, keep_audio=True)
    aid = _session(client, h)["answers"][0]["id"]
    _upload(client, h, aid)  # 키가 없어 원본이 남는다
    with monkeypatch.context() as m:
        _storage_down(m)  # 철회 때 원본을 못 지운 경우
        client.put("/practice/settings", json={"consent": False}, headers=h)
    sent = []
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(llm, "transcribe", lambda audio, filename, ctype: sent.append(audio) or "보내면 안 됨")
    r = client.post(f"/practice/answers/{aid}/transcribe", headers=h)
    assert r.status_code == 403 and r.json()["detail"] == "녹음 전에 동의가 필요합니다" and sent == []

    # 동의 행이 아예 없는 예전 사용자의 녹음도 마찬가지
    with SessionLocal() as db:
        legacy = _legacy_answer(db, "user-retry-legacy", 3)
        legacy.stt_status = "failed"
        db.commit()
    r = client.post(f"/practice/answers/{legacy.id}/transcribe", headers={"X-User-Id": "user-retry-legacy"})
    assert r.status_code == 403 and sent == []


def test_empty_transcript_counts_as_failed(client, monkeypatch, consent):
    h = {"X-User-Id": "user-empty-stt"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(llm, "transcribe", lambda audio, filename, ctype: "  ")
    consent(h)
    aid = _session(client, h)["answers"][0]["id"]
    a = _upload(client, h, aid).json()
    # 빈 전사는 실패로 보고 원본을 남겨 '전사 다시 시도'를 할 수 있게 한다
    assert a["stt_status"] == "failed" and a["audio_available"] and a["transcript"] is None
    client.patch(f"/practice/answers/{aid}", json={"transcript": "직접 적은 답변"}, headers=h)
    a = client.post(f"/practice/answers/{aid}/transcribe", headers=h).json()
    assert a["stt_status"] == "failed" and a["transcript"] == "직접 적은 답변"  # 빈 전사가 적어 둔 글을 지우지 않는다
    monkeypatch.setattr(llm, "transcribe", lambda audio, filename, ctype: "다시 전사한 답변")
    a = client.post(f"/practice/answers/{aid}/transcribe", headers=h).json()
    assert a["stt_status"] == "done" and not a["audio_available"]


def test_rerecord_drops_previous_transcript(client, monkeypatch, consent):
    """새로 녹음하면 이전 녹음의 전사문·코칭은 버린다. 새 전사가 비어도 옛 글이 새 녹음 옆에 남지 않는다."""
    h = {"X-User-Id": "user-rerecord-empty"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(llm, "transcribe", lambda audio, filename, ctype: "첫 녹음의 답변입니다")
    consent(h)
    aid = _session(client, h)["answers"][0]["id"]
    assert _upload(client, h, aid).json()["transcript"] == "첫 녹음의 답변입니다"
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert client.post(f"/practice/answers/{aid}/coach", headers=h).json()["coaching_report"]["method"] == "basic"
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(llm, "transcribe", lambda audio, filename, ctype: "")
    a = _upload(client, h, aid).json()
    assert a["stt_status"] == "failed" and a["transcript"] is None and a["coaching_report"] is None


def test_audio_path_outside_own_prefix_is_not_trusted(client, consent):
    """다른 사람 파일을 가리키게 바뀐 audio_path로는 읽지도 지우지도 않는다."""
    victim, attacker = {"X-User-Id": "user-path-victim"}, {"X-User-Id": "user-path-attacker"}
    consent(victim, keep_audio=True)
    consent(attacker, keep_audio=True)
    va = _upload(client, victim, _session(client, victim)["answers"][0]["id"]).json()
    aid = _session(client, attacker)["answers"][0]["id"]
    _upload(client, attacker, aid)
    with SessionLocal() as db:
        db.get(PracticeAnswer, aid).audio_path = va["audio_path"]
        db.commit()
    assert client.get(f"/practice/answers/{aid}/audio", headers=attacker).status_code == 404
    client.delete(f"/practice/answers/{aid}/audio", headers=attacker)
    assert _file(va).exists()
    assert client.get(f"/practice/answers/{va['id']}/audio", headers=victim).status_code == 200
