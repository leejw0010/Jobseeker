"""Exercise the real multipart/STT adapter using simulated provider responses.

These tests validate our integration, not a speech model's recognition accuracy.
"""
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from app import llm
from app.config import settings


def session_answer(client):
    headers = {"X-User-Id": f"speech-{uuid.uuid4()}"}
    session = client.post("/practice/sessions", headers=headers, json={"mode": "free", "count": 1}).json()
    return headers, session["answers"][0]["id"]


def provider(monkeypatch, payload=None, *, status=200, raw=None):
    requests = []
    monkeypatch.setattr(settings, "openai_api_key", "test-only-not-a-real-key")
    def post(url, **kwargs):
        requests.append((url, kwargs))
        args = {"content": raw} if raw is not None else {"json": payload}
        return httpx.Response(status, request=httpx.Request("POST", url), **args)
    monkeypatch.setattr(llm.httpx, "post", post)
    return requests


def test_korean_transcript_uses_the_actual_multipart_adapter(client, monkeypatch):
    text = "안녕하세요. 백엔드 개발자로 지원했습니다."
    calls = provider(monkeypatch, {"text": f"  {text}  "})
    h, aid = session_answer(client)
    r = client.post(f"/practice/answers/{aid}/audio", headers=h,
                    files={"file": ("answer.webm", b"simulated-audio", "audio/webm;codecs=opus")})
    assert r.status_code == 200, r.text
    assert r.json()["stt_status"] == "done" and r.json()["transcript"] == text
    url, request = calls[0]
    assert url == "https://api.openai.com/v1/audio/transcriptions"
    assert request["data"] == {"model": settings.openai_stt_model, "language": "ko", "response_format": "json"}
    name, audio, content_type = request["files"]["file"]
    assert name.endswith(".webm") and audio == b"simulated-audio" and content_type == "audio/webm"


@pytest.mark.parametrize("payload,raw", [
    ({"text": "   "}, None), ({"text": None}, None), ({"text": []}, None),
    ({}, None), ([], None), (None, b"invalid json"),
])
def test_empty_or_invalid_transcription_keeps_audio_and_offers_retry(client, monkeypatch, payload, raw):
    provider(monkeypatch, payload, raw=raw)
    h, aid = session_answer(client)
    r = client.post(f"/practice/answers/{aid}/audio", headers=h,
                    files={"file": ("answer.webm", b"simulated-audio", "audio/webm")})
    assert r.status_code == 200, r.text
    assert r.json()["stt_status"] == "failed"
    assert r.json()["transcript"] is None
    assert client.get(f"/practice/answers/{aid}/audio", headers=h).content == b"simulated-audio"


def test_mp4_retry_preserves_format_and_recognizes_the_stored_recording(client, monkeypatch):
    calls = provider(monkeypatch, {"error": "temporarily unavailable"}, status=503)
    h, aid = session_answer(client)
    first = client.post(f"/practice/answers/{aid}/audio", headers=h,
                        files={"file": ("answer.m4a", b"simulated-mp4", "audio/mp4")})
    assert first.json()["stt_status"] == "failed"
    calls = provider(monkeypatch, {"text": "저는 캐시를 직접 설계했습니다."})
    retried = client.post(f"/practice/answers/{aid}/transcribe", headers=h)
    assert retried.status_code == 200 and retried.json()["stt_status"] == "done"
    assert retried.json()["transcript"] == "저는 캐시를 직접 설계했습니다."
    assert retried.json()["audio_path"] == first.json()["audio_path"]
    assert calls[0][1]["files"]["file"][1:] == (b"simulated-mp4", "audio/mp4")
    assert client.get(f"/practice/answers/{aid}/audio", headers=h).headers["content-type"] == "audio/mp4"


def test_failed_retry_keeps_the_users_corrected_transcript(client, monkeypatch):
    provider(monkeypatch, {"text": "첫 인식 결과"})
    h, aid = session_answer(client)
    client.post(f"/practice/answers/{aid}/audio", headers=h,
                files={"file": ("answer.webm", b"simulated-audio", "audio/webm")})
    client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": "사용자가 고친 정확한 답변"})
    provider(monkeypatch, {"text": ""})
    retry = client.post(f"/practice/answers/{aid}/transcribe", headers=h)
    assert retry.status_code == 200 and retry.json()["stt_status"] == "failed"
    assert retry.json()["transcript"] == "사용자가 고친 정확한 답변"


def test_unsupported_recording_type_is_rejected_before_saving(client):
    h, aid = session_answer(client)
    r = client.post(f"/practice/answers/{aid}/audio", headers=h,
                    files={"file": ("answer.txt", b"not-audio", "text/plain")})
    assert r.status_code == 415
    assert client.get(f"/practice/answers/{aid}/audio", headers=h).status_code == 404


def test_slow_transcription_does_not_block_unrelated_api_requests(client, monkeypatch):
    entered, resume = Event(), Event()
    monkeypatch.setattr(settings, "openai_api_key", "test-only-not-a-real-key")
    def post(url, **kwargs):
        entered.set()
        assert resume.wait(5)
        return httpx.Response(200, json={"text": "인식 결과"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(llm.httpx, "post", post)
    h, aid = session_answer(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        upload = pool.submit(client.post, f"/practice/answers/{aid}/audio", headers=h,
                             files={"file": ("answer.webm", b"simulated-audio", "audio/webm")})
        assert entered.wait(5)
        try:
            health = pool.submit(client.get, "/health")
            assert health.result(timeout=1).status_code == 200
        finally:
            resume.set()
        assert upload.result(timeout=5).json()["transcript"] == "인식 결과"
