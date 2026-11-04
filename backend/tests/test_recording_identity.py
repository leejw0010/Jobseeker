"""Recording/transcript association survives refresh, corrections and replacement."""
from .test_transcription import provider, session_answer
from app.config import settings
import os
import subprocess
import sys
import pytest


def upload(client, headers, answer_id):
    result = client.post(f"/practice/answers/{answer_id}/audio", headers=headers,
                         files={"file": ("identity.webm", b"simulated-audio", "audio/webm")},
                         data={"duration_sec": "10"})
    assert result.status_code == 200, result.text
    return result.json()


def test_recording_text_identity_survives_refresh_and_replacement(client, monkeypatch):
    provider(monkeypatch, {"text": "제가 오류를 고쳤습니다."})
    h, aid = session_answer(client)
    first = upload(client, h, aid)
    assert first.get("recording_transcript_current") is True
    changed = client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": "완전히 다른 경험입니다."}).json()
    assert changed["recording_transcript_current"] is False
    sessions = client.get("/practice/sessions", headers=h).json()
    refreshed = client.get(f"/practice/sessions/{sessions[0]['id']}", headers=h).json()
    assert refreshed["answers"][0]["recording_transcript_current"] is False
    replaced = upload(client, h, aid)
    assert replaced["recording_transcript_current"] is True
    assert replaced["recorded_at"] != first["recorded_at"]


def test_first_manual_transcription_can_bind_but_later_edits_do_not_rebind(client, monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "off")
    h, aid = session_answer(client)
    assert upload(client, h, aid).get("recording_transcript_current") is False
    first = client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": "제가 직접 확인한 전사문입니다."}).json()
    assert first["recording_transcript_current"] is True
    client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": None})
    later = client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": "다른 내용을 작성했습니다."}).json()
    assert later["recording_transcript_current"] is False


def test_explicit_typed_answer_does_not_acquire_historical_recording_identity(client, monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "off")
    h, aid = session_answer(client)
    original = upload(client, h, aid)
    typed = client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": "녹음 대신 쓴 글 답변", "input_mode": "text"}).json()
    assert typed.get("recording_transcript_current") is False
    assert typed["stt_status"] == original["stt_status"]
    client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": None})
    assert client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": "새 글 답변"}).json()["recording_transcript_current"] is False


@pytest.mark.parametrize("replace_recording", [True, False])
def test_feature_off_changes_cannot_reuse_a_previous_recording_identity(client, monkeypatch, isolated_db, tmp_path, replace_recording):
    text = "제가 오류를 고쳤습니다."
    provider(monkeypatch, {"text": text})
    h, aid = session_answer(client)
    assert upload(client, h, aid)["recording_transcript_current"] is True
    sid = client.get("/practice/sessions", headers=h).json()[0]["id"]
    body = {"transcript": text} if replace_recording else {"transcript": text, "input_mode": "text"}
    code = f'''from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as c:
 if {replace_recording!r}:
  r=c.post("/practice/answers/{aid}/audio", headers={h!r}, files={{"file":("replacement.webm",b"synthetic-new-audio","audio/webm")}}, data={{"duration_sec":"20"}})
  assert r.status_code == 200, r.text
 before=c.get("/practice/sessions/{sid}",headers={h!r}).json()["answers"][0]
 r=c.patch("/practice/answers/{aid}", headers={h!r}, json={body!r})
 assert r.status_code == 200, r.text
 assert r.json()["stt_status"] == before["stt_status"]
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={
        **os.environ, "PRACTICE_INSIGHTS_ENABLED":"false", "STT_PROVIDER":"off",
        "DATABASE_URL":str(isolated_db.kw["bind"].url), "RECORDINGS_DIR":str(tmp_path / "flag-off-recordings"),
    })
    assert result.returncode == 0, result.stderr
    refreshed = client.get(f"/practice/sessions/{sid}", headers=h).json()["answers"][0]
    assert refreshed["recording_transcript_current"] is False


def test_explicit_text_on_an_unmigrated_schema_preserves_recordings_and_stt(tmp_path):
    code = '''from fastapi.testclient import TestClient
from sqlalchemy import inspect
from app.main import app
from app.db import engine
with TestClient(app) as c:
 c.put("/practice/settings", json={"consent":True})
 s=c.post("/practice/sessions",json={"mode":"free","count":1}).json()
 aid=s["answers"][0]["id"]
 original=c.post(f"/practice/answers/{aid}/audio",files={"file":("test.webm",b"synthetic","audio/webm")}).json()
 response=c.patch(f"/practice/answers/{aid}",json={"transcript":"글 답변","input_mode":"text"})
 assert response.status_code==200,response.text
 assert response.json()["stt_status"]==original["stt_status"]=="unavailable"
 assert response.json()["audio_available"] is True
 assert "recording_transcript_sha256" not in {col["name"] for col in inspect(engine).get_columns("practice_answers")}
'''
    result=subprocess.run([sys.executable,"-c",code],capture_output=True,text=True,env={
        **os.environ,"PRACTICE_INSIGHTS_ENABLED":"false","STT_PROVIDER":"off",
        "DATABASE_URL":f"sqlite:///{tmp_path / 'old-schema.db'}","RECORDINGS_DIR":str(tmp_path / "old-schema-recordings"),
    })
    assert result.returncode==0,result.stderr
