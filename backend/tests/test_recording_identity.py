"""Recording/transcript association survives refresh, corrections and replacement."""
from .test_transcription import provider, session_answer
from app.config import settings


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
    upload(client, h, aid)
    typed = client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": "녹음 대신 쓴 글 답변", "input_mode": "text"}).json()
    assert typed.get("recording_transcript_current") is False
    client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": None})
    assert client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": "새 글 답변"}).json()["recording_transcript_current"] is False
