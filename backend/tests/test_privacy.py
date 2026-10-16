"""P0-1: 녹음 동의, 원본 녹음 기본 삭제·보관 기한, 만료 정리."""
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import httpx
import pytest

from app import llm, retention, storage
from app.config import settings
from app.db import SessionLocal
from app.models import AnswerCoaching, PracticeAnswer, PracticeSession, Question, UserSettings
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
    # 다시 전사할 녹음이 없으면 동의를 묻지 않고 그렇게 알린다(동의해도 할 수 있는 일이 없다)
    r = client.post(f"/practice/answers/{aid}/transcribe", headers=h)
    assert r.status_code == 404 and r.json()["detail"] == "녹음이 없습니다"
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

    assert client.delete("/practice/recordings", headers=other).json() == {"deleted": 0, "failed": 0, "unchecked": False}
    assert client.delete("/practice/recordings", headers=h).json() == {"deleted": 1, "failed": 0, "unchecked": False}
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
        assert client.delete("/practice/recordings", headers=h).json() == {"deleted": 0, "failed": 2, "unchecked": False}
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


# ───────── 행이 가리키지 않는 저장소 파일(고아 파일) ─────────

def _orphan(user_id: str, age_days: float = 0) -> "os.PathLike":
    """어떤 답변 행도 가리키지 않는 저장소 파일. age_days만큼 예전에 저장한 것으로 만든다."""
    f = settings.local_recordings_dir / user_id / str(uuid.uuid4()) / f"{uuid.uuid4()}.webm"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"orphan")
    if age_days:
        t = time.time() - age_days * 86400
        os.utime(f, (t, t))
    return f


def _drop_rows_like_main(session_id: str) -> None:
    """예전 버전(main)의 세션 삭제: 행만 지우고 저장소의 녹음은 남겼다."""
    with SessionLocal() as db:
        db.delete(db.get(PracticeSession, session_id))
        db.commit()


def test_delete_all_and_withdrawal_also_remove_files_no_row_points_to(client, consent):
    """업그레이드한 설치에는 행 없이 남은 녹음이 있다. '모두 지우기'와 동의 철회는 사용자 폴더의 파일을 모두 지운다."""
    h, w, other = ({"X-User-Id": f"user-orphan-{x}"} for x in ("all", "withdraw", "other"))
    left = []
    for x in (h, w):
        consent(x, keep_audio=True)
        s = _session(client, x)
        left.append(_file(_upload(client, x, s["answers"][0]["id"]).json()))
        _drop_rows_like_main(s["id"])
    kept = _file(_upload(client, h, _session(client, h)["answers"][0]["id"]).json())
    theirs = _orphan(other["X-User-Id"])
    assert all(f.exists() for f in left)

    assert client.delete("/practice/recordings", headers=h).json() == {"deleted": 2, "failed": 0, "unchecked": False}
    assert not left[0].exists() and not kept.exists()
    assert client.delete("/practice/recordings", headers=h).json() == {"deleted": 0, "failed": 0, "unchecked": False}
    st = client.put("/practice/settings", json={"consent": False}, headers=w).json()
    assert (st["deleted"], st["failed"]) == (1, 0) and not left[1].exists()
    assert theirs.exists()  # 다른 사용자의 폴더는 건드리지 않는다


def test_purge_removes_orphan_files_after_the_retention_window(client):
    u = "user-orphan-purge"
    old, fresh = _orphan(u, age_days=31), _orphan(u)
    _purge_now()
    # 보관 기간이 지난 고아 파일은 지우고, 새 파일(올리는 중인 녹음일 수 있다)은 기간이 지날 때까지 둔다
    assert not old.exists() and fresh.exists()
    with SessionLocal() as db:
        assert purge_expired_audio(db, now=datetime.now(timezone.utc) + timedelta(days=31)) >= 1
    assert not fresh.exists()


def test_orphan_files_that_could_not_be_deleted_are_retried_by_the_next_purge(client, monkeypatch, consent):
    """화면은 못 지운 녹음을 '잠시 뒤 자동으로 다시 지워요'라고 알린다. 행이 없는 파일도 다음 만료 정리가 다시 지운다."""
    h, w = {"X-User-Id": "user-orphan-fail"}, {"X-User-Id": "user-orphan-fail-withdraw"}
    f, g = _orphan(h["X-User-Id"]), _orphan(w["X-User-Id"])
    consent(w)
    with monkeypatch.context() as m:
        _storage_down(m)
        assert client.delete("/practice/recordings", headers=h).json() == {"deleted": 0, "failed": 1, "unchecked": False}
        st = client.put("/practice/settings", json={"consent": False}, headers=w).json()
        assert (st["deleted"], st["failed"]) == (0, 1)
        assert _purge_now() == 0 and f.exists() and g.exists()
    later = _orphan(h["X-User-Id"])  # 삭제를 요청한 뒤에 저장된 파일은 보관 기간을 따른다
    t = time.time() + 60
    os.utime(later, (t, t))
    assert _purge_now() >= 2 and not f.exists() and not g.exists() and later.exists()
    with SessionLocal() as db:
        assert db.get(UserSettings, h["X-User-Id"]).sweep_audio_before is None  # 다 지웠으면 표시를 지운다
        assert db.get(UserSettings, w["X-User-Id"]).sweep_audio_before is None
    assert _purge_now() == 0 and later.exists()


def test_unreadable_folder_is_reported_without_a_made_up_count(client, monkeypatch, consent):
    """폴더 목록을 못 읽으면 남은 파일 수를 모른다: 개수를 지어내지 않고 unchecked로 알리며, 다음 만료 정리가 다시 훑는다."""
    h, w = {"X-User-Id": "user-list-down"}, {"X-User-Id": "user-list-down-withdraw"}
    f, g = _orphan(h["X-User-Id"]), _orphan(w["X-User-Id"])
    consent(w)

    def down(prefix=""):
        raise OSError("storage list down")

    with monkeypatch.context() as m:
        m.setattr(storage, "list", down)
        assert client.delete("/practice/recordings", headers=h).json() == {"deleted": 0, "failed": 0, "unchecked": True}
        st = client.put("/practice/settings", json={"consent": False}, headers=w).json()
        assert st["consented_at"] is None and (st["deleted"], st["failed"], st["unchecked"]) == (0, 0, True)
        assert _purge_now() == 0 and f.exists() and g.exists()
    assert _purge_now() >= 2 and not f.exists() and not g.exists()
    with SessionLocal() as db:
        assert db.get(UserSettings, h["X-User-Id"]).sweep_audio_before is None


def test_supabase_list_walks_folders_and_pages(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://sb.invalid")
    monkeypatch.setattr(settings, "supabase_service_key", "service")
    monkeypatch.setattr(storage, "_SB_LIST_LIMIT", 2)
    folder = {"id": None, "updated_at": None, "created_at": None, "metadata": None}
    tree = {"u1/": [{"name": "s1", **folder}, {"name": "s2", **folder}],
            "u1/s1/": [{"name": "a.webm", "id": "1", "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-10-01T00:00:00Z"},
                       {"name": "b.webm", "id": "2", "created_at": "2026-10-02T03:04:05.123+00:00"},
                       {"name": "c.m4a", "id": "3"}],
            "u1/s2/": []}
    calls = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append((url, json))
        assert headers["Authorization"] == "Bearer service"
        rows = tree[json["prefix"]][json["offset"]: json["offset"] + json["limit"]]
        return httpx.Response(200, json=rows, request=httpx.Request("POST", url))

    monkeypatch.setattr(storage.httpx, "post", post)
    got = storage.list("u1/")
    utc = timezone.utc
    assert [(o.path, o.modified) for o in got] == [
        ("u1/s1/a.webm", datetime(2026, 10, 1, tzinfo=utc)),
        ("u1/s1/b.webm", datetime(2026, 10, 2, 3, 4, 5, 123000, tzinfo=utc)),
        ("u1/s1/c.m4a", None)]  # 저장 시각을 모르면 None(만료 정리는 건드리지 않는다)
    assert {u for u, _ in calls} == {"https://sb.invalid/storage/v1/object/list/recordings"}
    assert [(b["prefix"], b["offset"]) for _, b in calls] == [
        ("u1/", 0), ("u1/", 2), ("u1/s1/", 0), ("u1/s1/", 2), ("u1/s2/", 0)]


# ───────── 업로드·다시 전사 중의 동의 철회와 삭제 ─────────

def _blocking_stt(monkeypatch, result):
    """전사 요청이 끝나기 전에 다른 요청을 끼워 넣는다. result: 전사문 또는 던질 예외."""
    entered, resume = Event(), Event()

    def stt(audio, filename, ctype):
        entered.set()
        assert resume.wait(5)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(llm, "transcribe", stt)
    return entered, resume


def _while_transcribing(monkeypatch, result, request, during):
    """request()가 전사를 기다리는 동안 during()을 실행한다. (request 응답, during 결과)"""
    entered, resume = _blocking_stt(monkeypatch, result)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(request)
        assert entered.wait(5)
        try:
            out = during()
        finally:
            resume.set()
        return pending.result(timeout=5), out


def _user_files(user_id: str):
    return [p for p in (settings.local_recordings_dir / user_id).rglob("*") if p.is_file()]


@pytest.mark.parametrize("keep_audio,stt", [(True, "철회하는 동안 전사된 답변"), (False, httpx.ConnectError("down"))])
def test_withdrawal_during_upload_deletes_that_recording(client, monkeypatch, consent, keep_audio, stt):
    h = {"X-User-Id": f"user-withdraw-inflight-{keep_audio}"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    consent(h, keep_audio=keep_audio)
    s = _session(client, h)
    aid = s["answers"][0]["id"]
    r, st = _while_transcribing(monkeypatch, stt, lambda: _upload(client, h, aid),
                                lambda: client.put("/practice/settings", json={"consent": False}, headers=h).json())
    assert st["consented_at"] is None
    assert r.status_code == 403 and r.json()["detail"] == "녹음 전에 동의가 필요합니다"
    assert _user_files(h["X-User-Id"]) == []
    a = client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"][0]
    assert a["audio_available"] is False
    assert client.get(f"/practice/answers/{aid}/audio", headers=h).status_code == 404
    if isinstance(stt, str):  # 전사에 성공했으면 전사문만 남긴다
        assert (a["transcript"], a["stt_status"]) == (stt, "done") and a["audio_deleted_at"] and a["recorded_at"]
    else:  # 전사문도 없으면 이번 녹음은 없던 일로 한다
        assert (a["transcript"], a["stt_status"], a["recorded_at"]) == (None, "none", None)


def test_withdrawal_during_retry_transcribe_keeps_only_the_transcript(client, monkeypatch, consent):
    h = {"X-User-Id": "user-withdraw-retry"}
    consent(h, keep_audio=True)
    s = _session(client, h)
    aid = s["answers"][0]["id"]
    _upload(client, h, aid)  # 키가 없어 원본이 남는다
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    r, st = _while_transcribing(monkeypatch, "다시 전사한 답변", lambda: client.post(f"/practice/answers/{aid}/transcribe", headers=h),
                                lambda: client.put("/practice/settings", json={"consent": False}, headers=h).json())
    assert st["deleted"] == 1
    assert r.status_code == 403 and r.json()["detail"] == "녹음 전에 동의가 필요합니다"
    a = client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"][0]
    assert (a["transcript"], a["stt_status"], a["audio_available"]) == ("다시 전사한 답변", "done", False)
    assert a["audio_deleted_at"] and _user_files(h["X-User-Id"]) == []


@pytest.mark.parametrize("target", ["session", "question"])
def test_deleting_the_session_or_question_during_upload_leaves_no_file(client, monkeypatch, consent, target):
    h = {"X-User-Id": f"user-delete-inflight-{target}"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    consent(h)  # 기본값(원본 보관 안 함)과 전사 성공에서도 일어났다
    q = client.post("/practice/questions", json={"category": "인성", "text": "좌우명이 무엇인가요?"}, headers=h).json()
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"]]}, headers=h).json()
    aid = s["answers"][0]["id"]
    url = f"/practice/sessions/{s['id']}" if target == "session" else f"/practice/questions/{q['id']}"
    r, deleted = _while_transcribing(monkeypatch, "전사된 답변", lambda: _upload(client, h, aid),
                                     lambda: client.delete(url, headers=h).status_code)
    assert deleted == 204
    assert r.status_code == 404 and r.json()["detail"] == "답변을 찾을 수 없습니다"
    assert _user_files(h["X-User-Id"]) == []
    assert client.delete("/practice/recordings", headers=h).json() == {"deleted": 0, "failed": 0, "unchecked": False}


def test_deleting_the_session_during_retry_transcribe_returns_404(client, monkeypatch, consent):
    h = {"X-User-Id": "user-delete-inflight-retry"}
    consent(h, keep_audio=True)
    s = _session(client, h)
    aid = s["answers"][0]["id"]
    _upload(client, h, aid)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    r, deleted = _while_transcribing(monkeypatch, "다시 전사한 답변", lambda: client.post(f"/practice/answers/{aid}/transcribe", headers=h),
                                     lambda: client.delete(f"/practice/sessions/{s['id']}", headers=h).status_code)
    assert deleted == 204
    assert r.status_code == 404 and r.json()["detail"] == "답변을 찾을 수 없습니다"
    assert _user_files(h["X-User-Id"]) == []


@pytest.mark.parametrize("keep_audio,stt", [(True, "모두 지우는 동안 전사된 답변"), (False, httpx.ConnectError("down"))])
def test_delete_all_during_upload_counts_and_deletes_that_recording(client, monkeypatch, consent, keep_audio, stt):
    """'내 원본 녹음 모두 지우기'는 올리는 중(전사 대기)이라 아직 행이 가리키지 않는 녹음도 지우고 센다. 업로드는 지운 파일을
    다시 가리키지 않고, 그 삭제 직후에 커밋한 것처럼 녹음을 지운 것으로 저장한다(전사문은 남긴다)."""
    h = {"X-User-Id": f"user-clear-inflight-{keep_audio}"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    consent(h, keep_audio=keep_audio)  # 원본 보관을 골랐거나 전사에 실패하면 원본이 남는 경우다
    s = _session(client, h)
    aid = s["answers"][0]["id"]
    r, d = _while_transcribing(monkeypatch, stt, lambda: _upload(client, h, aid),
                               lambda: client.delete("/practice/recordings", headers=h).json())
    assert d == {"deleted": 1, "failed": 0, "unchecked": False}
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["audio_available"] is False and a["audio_deleted_at"] and a["recorded_at"]
    assert _user_files(h["X-User-Id"]) == []
    assert client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"][0]["audio_available"] is False
    assert client.get(f"/practice/answers/{aid}/audio", headers=h).json()["detail"] == "원본 녹음은 삭제됐어요"
    if isinstance(stt, str):
        assert (a["transcript"], a["stt_status"]) == (stt, "done")
    else:
        assert (a["transcript"], a["stt_status"]) == (None, "failed")
        retry = client.post(f"/practice/answers/{aid}/transcribe", headers=h)
        assert retry.status_code == 404 and retry.json()["detail"] == "원본 녹음은 삭제됐어요"


def test_upload_started_after_delete_all_keeps_its_recording(client, monkeypatch, consent):
    """모두 지우기가 지운 시각을 저장한 뒤에 시작한 업로드는 새 녹음이다.
    모두 지우기가 폴더를 훑기 전에 파일을 저장했어도 지우지 않는다."""
    h = {"X-User-Id": "user-clear-then-upload"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    consent(h, keep_audio=True)
    s = _session(client, h)
    aid = s["answers"][0]["id"]
    entered, resume = _blocking_stt(monkeypatch, "지운 뒤에 녹음한 답변")
    real_list = storage.list
    with ThreadPoolExecutor(max_workers=1) as pool:
        started = []

        def list_after_upload(prefix=""):
            started.append(pool.submit(lambda: _upload(client, h, aid)))
            assert entered.wait(5)  # 업로드가 파일을 저장하고 전사를 기다린다
            return real_list(prefix)

        monkeypatch.setattr(storage, "list", list_after_upload)
        try:
            d = client.delete("/practice/recordings", headers=h).json()
        finally:
            monkeypatch.setattr(storage, "list", real_list)
            resume.set()
        r = started[0].result(timeout=5)
    assert d == {"deleted": 0, "failed": 0, "unchecked": False}
    assert r.status_code == 200 and r.json()["audio_available"] is True and r.json()["audio_deleted_at"] is None
    assert client.get(f"/practice/answers/{aid}/audio", headers=h).status_code == 200


def test_deleting_the_overwritten_recording_during_upload_deletes_the_new_one(client, monkeypatch, consent):
    """다시 녹음하면 같은 경로에 덮어쓴다. 전사하는 동안 다른 탭에서 이전 녹음을 지우면 그 삭제가 새 파일을 지웠으므로
    업로드도 녹음을 지운 것으로 저장한다(없는 파일을 가리키지 않는다)."""
    h = {"X-User-Id": "user-overwrite-delete"}
    consent(h, keep_audio=True)
    s = _session(client, h)
    aid = s["answers"][0]["id"]
    _upload(client, h, aid)  # 키가 없어 원본이 남는다
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    r, deleted = _while_transcribing(monkeypatch, "다시 녹음한 답변", lambda: _upload(client, h, aid),
                                     lambda: client.delete(f"/practice/answers/{aid}/audio", headers=h).status_code)
    assert deleted == 200 and r.status_code == 200, r.text
    a = r.json()
    assert (a["transcript"], a["stt_status"], a["audio_available"]) == ("다시 녹음한 답변", "done", False)
    assert a["audio_deleted_at"] and _user_files(h["X-User-Id"]) == []


@pytest.mark.parametrize("during", ["delete-all", "delete-one"])
@pytest.mark.parametrize("stt", ["다시 전사한 답변", httpx.ConnectError("down")])
def test_deleting_the_recording_during_retry_transcribe_keeps_the_transcript(client, monkeypatch, consent, during, stt):
    """다시 전사하는 동안 원본을 지워도(모두 지우기, 녹음 삭제) 이미 얻은 전사문은 남긴다(동의 철회와 같다).
    원본은 이미 OpenAI로 보냈다."""
    h = {"X-User-Id": f"user-retry-{during}-{isinstance(stt, str)}"}
    consent(h, keep_audio=True)
    s = _session(client, h)
    aid = s["answers"][0]["id"]
    _upload(client, h, aid)  # 키가 없어 원본이 남는다
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    url = "/practice/recordings" if during == "delete-all" else f"/practice/answers/{aid}/audio"
    r, deleted = _while_transcribing(monkeypatch, stt, lambda: client.post(f"/practice/answers/{aid}/transcribe", headers=h),
                                     lambda: client.delete(url, headers=h).status_code)
    assert deleted == 200
    a = client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"][0]
    assert a["audio_available"] is False and a["audio_deleted_at"] and _user_files(h["X-User-Id"]) == []
    if isinstance(stt, str):
        assert r.status_code == 200 and r.json()["transcript"] == stt
        assert (a["transcript"], a["stt_status"]) == (stt, "done")
    else:  # 전사문도 없으면 지웠다고 알린다
        assert r.status_code == 404 and r.json()["detail"] == "원본 녹음은 삭제됐어요"
        assert (a["transcript"], a["stt_status"]) == (None, "unavailable")


@pytest.mark.parametrize("target", ["session", "question"])
def test_upload_committed_while_deleting_the_session_or_question_leaves_no_file(client, monkeypatch, consent, target):
    """세션·질문 삭제가 답변을 읽고 다른 녹음을 지우는 동안 업로드가 먼저 커밋해도, 함께 지워진 답변의 녹음 파일이 남지 않는다."""
    h = {"X-User-Id": f"user-delete-after-commit-{target}"}
    consent(h, keep_audio=True)
    q = client.post("/practice/questions", json={"category": "인성", "text": "좌우명이 무엇인가요?"}, headers=h).json()
    if target == "session":
        bank = client.get("/practice/questions", params={"source": "bank"}, headers=h).json()[0]
        s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"], bank["id"]]}, headers=h).json()
        a1, a2 = (a["id"] for a in s["answers"])
        url = f"/practice/sessions/{s['id']}"
    else:  # 같은 질문으로 연습한 두 세션
        a1, a2 = (client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"]]}, headers=h).json()
                  ["answers"][0]["id"] for _ in range(2))
        url = f"/practice/questions/{q['id']}"
    _upload(client, h, a1)  # 키가 없어 원본이 남는다
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    entered, resume = _blocking_stt(monkeypatch, "올리던 답변")
    real_delete = storage.delete
    deleting, go = Event(), Event()

    def slow_delete(path):
        deleting.set()
        assert go.wait(5)
        return real_delete(path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        upload = pool.submit(lambda: _upload(client, h, a2))
        assert entered.wait(5)
        monkeypatch.setattr(storage, "delete", slow_delete)
        removal = pool.submit(lambda: client.delete(url, headers=h).status_code)
        try:
            assert deleting.wait(5)  # 삭제가 답변을 읽고 a1의 녹음을 지우는 중
            monkeypatch.setattr(storage, "delete", real_delete)
            resume.set()
            r = upload.result(timeout=5)  # 그사이 업로드가 a2의 녹음을 커밋한다
        finally:
            resume.set()
            go.set()
        assert removal.result(timeout=5) == 204
    assert r.status_code == 200 and r.json()["audio_available"] is True
    with SessionLocal() as db:
        assert db.get(PracticeAnswer, a1) is None and db.get(PracticeAnswer, a2) is None
    assert _user_files(h["X-User-Id"]) == []


# ───────── 맞춤 질문 삭제(로컬 SQLite도 Supabase의 외래 키 동작과 같게) ─────────

def test_deleting_a_custom_question_deletes_its_answers_like_supabase(client, consent):
    """Supabase는 질문을 지우면 답변(on delete cascade)과 코칭 행(cascade)을 지우고 꼬리질문의 원 답변 연결을 비운다
    (on delete set null). 로컬 SQLite는 외래 키를 강제하지 않으므로 같은 일을 코드로 해야 세션 화면이 깨지지 않는다."""
    h = {"X-User-Id": "user-question-delete"}
    consent(h, keep_audio=True)
    q = client.post("/practice/questions", json={"category": "인성", "text": "좌우명이 무엇인가요?"}, headers=h).json()
    bank = client.get("/practice/questions", params={"source": "bank"}, headers=h).json()[0]
    s = client.post("/practice/sessions", json={"mode": "free", "question_ids": [q["id"], bank["id"]],
                                                "followups_enabled": True}, headers=h).json()
    aid, other = (a["id"] for a in s["answers"])
    f = _file(_upload(client, h, aid).json())
    client.patch(f"/practice/answers/{aid}", json={"transcript": "제가 직접 정한 좌우명입니다.", "reflection_note": "메모"},
                 headers=h)
    child = client.post(f"/practice/answers/{aid}/followup", headers=h).json()["answers"][1]
    assert child["parent_answer_id"] == aid

    assert client.delete(f"/practice/questions/{q['id']}", headers=h).status_code == 204
    got = client.get(f"/practice/sessions/{s['id']}", headers=h)
    assert got.status_code == 200, got.text
    answers = {a["id"]: a for a in got.json()["answers"]}
    assert set(answers) == {child["id"], other} and answers[child["id"]]["parent_answer_id"] is None
    assert not f.exists()
    with SessionLocal() as db:
        assert db.get(PracticeAnswer, aid) is None and db.get(AnswerCoaching, aid) is None
    assert client.delete(f"/practice/sessions/{s['id']}", headers=h).status_code == 204


# ───────── 다시 전사: 할 수 없는 경우를 동의보다 먼저 알린다 ─────────

def test_retry_after_the_recording_is_gone_says_so_before_asking_consent(client, monkeypatch, consent):
    """동의를 철회해 원본이 지워진 뒤 오래된 탭에서 '음성 인식 다시 시도'를 누르면, 동의를 다시 받지 않고 삭제를 알린다."""
    h = {"X-User-Id": "user-retry-gone"}
    consent(h, keep_audio=True)
    s = _session(client, h, 2)
    a1, a2 = (a["id"] for a in s["answers"])
    _upload(client, h, a1)
    _upload(client, h, a2)  # 키가 없어 둘 다 원본이 남는다
    assert client.put("/practice/settings", json={"consent": False}, headers=h).json()["deleted"] == 2
    sent = []
    monkeypatch.setattr(llm, "transcribe", lambda audio, filename, ctype: sent.append(audio) or "보내면 안 됨")
    r = client.post(f"/practice/answers/{a1}/transcribe", headers=h)
    assert r.status_code == 404 and r.json()["detail"] == "원본 녹음은 삭제됐어요"  # 키가 없어도 삭제를 먼저 알린다
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    r = client.post(f"/practice/answers/{a1}/transcribe", headers=h)
    assert r.status_code == 404 and r.json()["detail"] == "원본 녹음은 삭제됐어요" and sent == []
    assert client.get("/practice/settings", headers=h).json()["consented_at"] is None

    # 원본이 남아 있어도 키가 없으면 동의를 묻지 않는다(동의해도 전사할 수 없다)
    consent(h, keep_audio=True)
    monkeypatch.setattr(settings, "openai_api_key", "")
    _upload(client, h, a2)
    with monkeypatch.context() as m:
        _storage_down(m)  # 철회 때 원본을 못 지운 경우
        client.put("/practice/settings", json={"consent": False}, headers=h)
    r = client.post(f"/practice/answers/{a2}/transcribe", headers=h)
    assert r.status_code == 503 and sent == []


def test_keep_audio_change_applies_to_new_and_retried_recordings_only(client, monkeypatch, consent):
    """설정 화면 문구: 바꾸면 새 녹음과 음성 인식을 다시 시도하는 녹음에 적용되고, 이미 저장된 녹음은 원래 삭제 예정일을 따른다."""
    h = {"X-User-Id": "user-keep-change"}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(llm, "transcribe", lambda audio, filename, ctype: "")  # 전사 실패: 원본을 남긴다
    consent(h, keep_audio=True)
    s = _session(client, h, 2)
    a1, a2 = (_upload(client, h, a["id"]).json() for a in s["answers"])
    assert a1["audio_available"] and a2["audio_available"]
    client.put("/practice/settings", json={"keep_audio": False}, headers=h)
    monkeypatch.setattr(llm, "transcribe", lambda audio, filename, ctype: "다시 전사한 답변")
    retried = client.post(f"/practice/answers/{a1['id']}/transcribe", headers=h).json()
    assert retried["stt_status"] == "done" and retried["audio_available"] is False  # 지금 설정(보관 안 함)을 따른다
    untouched = client.get(f"/practice/sessions/{s['id']}", headers=h).json()["answers"][1]
    assert untouched["audio_available"] and untouched["audio_expires_at"] == a2["audio_expires_at"]
