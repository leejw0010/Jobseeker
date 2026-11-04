"""로컬 STT(faster-whisper) 제공자. 실제 모델 대신 가짜 모델을 끼우고, 녹음은 PyAV로 만든 진짜 WebM/Opus를 쓴다.

모델의 인식 정확도는 검사하지 않는다(실제 음성으로 잰 결과는 docs/progress.md).
"""
import io
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from app import llm, stt  # noqa: E402
from app.config import settings  # noqa: E402

SPEECH = ["  안녕하세요. ", "", "저는 캐시를 직접 설계했습니다."]


def webm(seconds: float = 1.0, amplitude: float = 0.3) -> bytes:
    """브라우저 MediaRecorder와 같은 형식(WebM/Opus 48kHz 모노). amplitude 0이면 무음."""
    rate = 48000
    t = np.arange(int(seconds * rate)) / rate
    pcm = (np.sin(2 * np.pi * 440 * t) * amplitude * 32767).astype(np.int16)
    buf = io.BytesIO()
    with av.open(buf, "w", format="webm") as c:
        st = c.add_stream("libopus", rate=rate, layout="mono")
        for i in range(0, pcm.size, 960):
            chunk = np.pad(pcm[i:i + 960], (0, max(0, 960 - pcm[i:i + 960].size)))
            frame = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate, frame.pts = rate, i
            for p in st.encode(frame):
                c.mux(p)
        for p in st.encode(None):
            c.mux(p)
    return buf.getvalue()


class Fake:
    """가짜 faster-whisper. 만든 모델 수, 받은 인자, 전사 호출을 기록한다."""

    def __init__(self, segments=None):
        self.segments = SPEECH if segments is None else segments
        self.models, self.calls, self.downloads = [], [], []
        self.cached = True  # 캐시에 모델이 있는가
        self.download_error: Exception | None = None
        self.load_error: Exception | None = None
        self.transcribe_error: Exception | None = None
        fake = self

        class WhisperModel:
            def __init__(self, path, **kwargs):
                if fake.load_error:
                    raise fake.load_error
                fake.models.append((path, kwargs))

            def transcribe(self, audio, **kwargs):
                fake.calls.append((audio, kwargs))
                if fake.transcribe_error:
                    raise fake.transcribe_error
                return (SimpleNamespace(text=t) for t in fake.segments), None

        def download_model(name, local_files_only=False, cache_dir=None):
            fake.downloads.append((name, local_files_only, cache_dir))
            if name not in ("tiny", "base", "small"):
                raise ValueError(f"Invalid model size '{name}'")
            if local_files_only and not fake.cached:
                raise FileNotFoundError("not in cache")
            if not local_files_only and fake.download_error:
                raise fake.download_error
            fake.cached = True
            return f"/cache/{name}"

        self.backend = (WhisperModel, download_model)


@pytest.fixture
def local(monkeypatch):
    """로컬 제공자를 새로 만들어(모델을 불러오지 않은 상태) 가짜 faster-whisper를 끼운다. OpenAI 키는 비운다."""
    fake = Fake()
    monkeypatch.setattr(settings, "stt_provider", "local")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "local_stt_model", "base")
    monkeypatch.setattr(settings, "local_stt_model_dir", "")
    monkeypatch.setattr(settings, "local_stt_allow_download", True)
    monkeypatch.setitem(stt._PROVIDERS, "local", stt._Local())
    monkeypatch.setattr(stt._PROVIDERS["local"], "_installed", True)
    monkeypatch.setattr(stt, "_backend", lambda: fake.backend)
    return fake


def answer(client, keep_audio=False):
    h = {"X-User-Id": f"local-stt-{uuid.uuid4()}"}
    r = client.put("/practice/settings", headers=h, json={"consent": True, "keep_audio": keep_audio})
    assert r.status_code == 200, r.text
    s = client.post("/practice/sessions", headers=h, json={"mode": "free", "count": 1}).json()
    return h, s["answers"][0]["id"]


def upload(client, h, aid, data):
    return client.post(f"/practice/answers/{aid}/audio", headers=h, data={"duration_sec": "1"},
                       files={"file": ("answer.webm", data, "audio/webm;codecs=opus")})


def test_local_transcribes_korean_without_openai_key(client, local, monkeypatch):
    sent = []
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: sent.append(a) or pytest.fail("OpenAI를 부르면 안 된다"))
    h, aid = answer(client)
    r = upload(client, h, aid, webm(1.0))
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["stt_status"] == "done" and a["transcript"] == "안녕하세요. 저는 캐시를 직접 설계했습니다."
    # 전사에 성공했고 보관을 고르지 않았으니 원본은 바로 지운다
    assert a["audio_available"] is False and a["audio_deleted_at"]
    assert sent == []
    audio, kwargs = local.calls[0]
    assert audio.dtype == np.float32 and abs(audio.size - 16000) < 1600  # 16kHz 모노 약 1초
    assert kwargs["language"] == "ko" and kwargs["task"] == "transcribe" and kwargs["vad_filter"] is True
    assert kwargs["beam_size"] == settings.local_stt_beam_size


def test_model_loads_lazily_once_with_cpu_int8_defaults(client, local, monkeypatch):
    monkeypatch.setattr(settings, "local_stt_device", "cpu")
    monkeypatch.setattr(settings, "local_stt_compute_type", "int8")
    monkeypatch.setattr(settings, "local_stt_cpu_threads", 3)
    assert client.get("/health").json()["stt"]["state"] == "not_loaded"
    assert local.models == []  # 상태 확인이나 앱 시작만으로는 불러오지 않는다
    for _ in range(3):
        h, aid = answer(client)
        assert upload(client, h, aid, webm()).json()["stt_status"] == "done"
    assert local.models == [("/cache/base", {"device": "cpu", "compute_type": "int8", "cpu_threads": 3})]
    assert len(local.calls) == 3
    # 캐시에 있으면 네트워크로 받지 않는다(오프라인 재사용)
    assert local.downloads == [("base", True, None)]
    assert client.get("/health").json()["stt"] == {"provider": "local", "available": True, "model": "base",
                                                   "state": "ready", "error": None}


def test_concurrent_first_requests_load_the_model_once(local):
    p = stt._PROVIDERS["local"]
    with ThreadPoolExecutor(8) as pool:
        models = list(pool.map(lambda _: p.model(), range(8)))
    assert len(local.models) == 1 and all(m is models[0] for m in models)


def test_changed_model_size_reloads(local, monkeypatch):
    p = stt._PROVIDERS["local"]
    p.model()
    monkeypatch.setattr(settings, "local_stt_model", "small")
    p.model()
    assert [m[0] for m in local.models] == ["/cache/base", "/cache/small"]


def test_downloads_once_when_not_cached_then_reuses(local, monkeypatch):
    local.cached = False
    monkeypatch.setattr(settings, "local_stt_model_dir", "/models")
    p = stt._PROVIDERS["local"]
    p.model()
    assert local.downloads == [("base", True, "/models"), ("base", False, "/models")]
    monkeypatch.setitem(stt._PROVIDERS, "local", stt._Local())  # 서버 재시작
    stt._PROVIDERS["local"].model()
    assert local.downloads[2:] == [("base", True, "/models")]


def test_model_folder_path_is_used_without_download(local, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "local_stt_model", str(tmp_path))
    stt._PROVIDERS["local"].model()
    assert local.models[0][0] == str(tmp_path) and local.downloads == []


def test_download_failure_keeps_audio_reports_health_and_retries_later(client, local):
    local.cached, local.download_error = False, OSError("network unreachable")
    h, aid = answer(client)
    a = upload(client, h, aid, webm()).json()
    assert a["stt_status"] == "failed" and a["transcript"] is None and a["audio_available"]
    st = client.get("/health").json()["stt"]
    assert st["available"] is True and st["state"] == "error" and "내려받지 못했어요" in st["error"]
    assert "network" not in st["error"]  # 내부 예외 문구는 내보내지 않는다
    # 실패를 기억하지 않는다: 네트워크가 돌아오면 다시 전사가 모델을 받아 성공한다
    local.download_error = None
    r = client.post(f"/practice/answers/{aid}/transcribe", headers=h)
    assert r.status_code == 200 and r.json()["stt_status"] == "done"
    assert client.get("/health").json()["stt"]["state"] == "ready"


def test_missing_model_with_download_disabled_fails_without_network(client, local, monkeypatch):
    local.cached = False
    monkeypatch.setattr(settings, "local_stt_allow_download", False)
    h, aid = answer(client)
    assert upload(client, h, aid, webm()).json()["stt_status"] == "failed"
    assert all(only for _, only, _ in local.downloads)
    assert "LOCAL_STT_ALLOW_DOWNLOAD" in client.get("/health").json()["stt"]["error"]


@pytest.mark.parametrize("name", ["huge", "base"])
def test_model_load_failure_is_a_retryable_failure(client, local, monkeypatch, name):
    monkeypatch.setattr(settings, "local_stt_model", name)
    if name == "base":
        local.load_error = RuntimeError("Unable to open file 'model.bin'")
    h, aid = answer(client)
    a = upload(client, h, aid, webm()).json()
    assert a["stt_status"] == "failed" and a["audio_available"]
    st = client.get("/health").json()["stt"]
    assert st["state"] == "error" and ("알 수 없는 모델" in st["error"] if name == "huge" else "불러오지 못했어요" in st["error"])


def test_broken_install_is_a_failure_not_a_server_error(client, local, monkeypatch):
    def broken():
        raise ImportError("libctranslate2.so: cannot open shared object file")

    monkeypatch.setattr(stt, "_backend", broken)
    h, aid = answer(client)
    r = upload(client, h, aid, webm())
    assert r.status_code == 200 and r.json()["stt_status"] == "failed" and r.json()["audio_available"]
    assert "라이브러리를 불러오지 못했어요" in client.get("/health").json()["stt"]["error"]


def test_silence_fails_before_the_model_and_retry_succeeds(client, local, monkeypatch):
    h, aid = answer(client)
    a = upload(client, h, aid, webm(1.0, amplitude=0)).json()
    assert a["stt_status"] == "failed" and a["audio_available"] and local.calls == [] and local.models == []
    # 같은 원본을 다시 전사해도 무음이면 실패한다. 직접 적은 전사문은 지우지 않는다
    assert client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": "직접 적은 답변"}).status_code == 200
    r = client.post(f"/practice/answers/{aid}/transcribe", headers=h).json()
    assert r["stt_status"] == "failed" and r["transcript"] == "직접 적은 답변" and r["audio_available"]


def test_model_finding_no_speech_is_a_failure(client, local):
    local.segments = ["   ", ""]  # VAD가 모두 걸렀거나 빈 문장뿐
    h, aid = answer(client)
    a = upload(client, h, aid, webm()).json()
    assert a["stt_status"] == "failed" and a["transcript"] is None and a["audio_available"]


@pytest.mark.parametrize("data", [b"not audio at all" * 50, webm()[:200]])
def test_invalid_or_truncated_file_keeps_audio_for_retry(client, local, data):
    h, aid = answer(client)
    a = upload(client, h, aid, data).json()
    assert a["stt_status"] == "failed" and a["audio_available"] and local.calls == []


def test_too_long_recording_is_not_transcribed(client, local, monkeypatch):
    monkeypatch.setattr(settings, "local_stt_max_audio_sec", 0.5)
    h, aid = answer(client)
    a = upload(client, h, aid, webm(1.0)).json()
    assert a["stt_status"] == "failed" and a["audio_available"] and local.calls == []


def test_model_error_during_transcription_keeps_audio(client, local):
    local.transcribe_error = RuntimeError("ctranslate2 failure")
    h, aid = answer(client)
    a = upload(client, h, aid, webm()).json()
    assert a["stt_status"] == "failed" and a["audio_available"]


def test_busy_cpu_fails_fast_instead_of_piling_up(client, local, monkeypatch):
    """다른 전사가 도는 동안에는 잠깐만 기다리고 실패로 돌려준다(원본은 남아 다시 시도할 수 있다)."""
    monkeypatch.setattr(settings, "local_stt_queue_timeout_sec", 0.05)
    p = stt._PROVIDERS["local"]
    assert p._slot.acquire(timeout=1)  # 다른 요청이 전사 중
    try:
        h, aid = answer(client)
        a = upload(client, h, aid, webm()).json()
        assert a["stt_status"] == "failed" and a["audio_available"] and local.calls == []
    finally:
        p._slot.release()
    assert client.post(f"/practice/answers/{aid}/transcribe", headers=h).json()["stt_status"] == "done"


def test_transcriptions_run_one_at_a_time(local, monkeypatch):
    running, peak, lock = 0, 0, threading.Lock()
    model_cls, download = local.backend

    class Slow(model_cls):
        def transcribe(self, audio, **kwargs):
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
            threading.Event().wait(0.05)
            with lock:
                running -= 1
            return super().transcribe(audio, **kwargs)

    monkeypatch.setattr(stt, "_backend", lambda: (Slow, download))
    data = webm()
    with ThreadPoolExecutor(3) as pool:
        texts = list(pool.map(lambda _: stt.transcribe(data, "a.webm", "audio/webm"), range(3)))
    assert peak == 1 and len(set(texts)) == 1


def test_keep_audio_then_edit_coach_and_delete_still_work(client, local):
    h, aid = answer(client, keep_audio=True)
    a = upload(client, h, aid, webm()).json()
    assert a["stt_status"] == "done" and a["audio_available"]  # 보관을 골랐으니 남긴다
    edited = client.patch(f"/practice/answers/{aid}", headers=h, json={"transcript": "제가 직접 캐시를 설계해 응답 시간을 40% 줄였습니다."})
    assert edited.status_code == 200 and edited.json()["transcript"].startswith("제가 직접")
    coached = client.post(f"/practice/answers/{aid}/coach", headers=h).json()
    assert coached["coaching_report"]["method"] == "basic"  # 키가 없으니 기본 점검
    deleted = client.delete(f"/practice/answers/{aid}/audio", headers=h).json()
    assert deleted["audio_available"] is False and deleted["transcript"].startswith("제가 직접")
    assert client.get(f"/practice/answers/{aid}/audio", headers=h).status_code == 404


def test_local_upload_still_requires_consent(client, local):
    h, aid = answer(client)
    assert client.put("/practice/settings", headers=h, json={"consent": False}).status_code == 200
    r = upload(client, h, aid, webm())
    assert r.status_code == 403 and local.calls == []


def test_not_installed_is_unavailable(client, local, monkeypatch):
    monkeypatch.setattr(stt._PROVIDERS["local"], "_installed", False)
    h, aid = answer(client)
    a = upload(client, h, aid, webm()).json()
    assert a["stt_status"] == "unavailable" and a["audio_available"]
    r = client.post(f"/practice/answers/{aid}/transcribe", headers=h)
    assert r.status_code == 503 and "faster-whisper" in r.json()["detail"]


def test_off_provider_is_unavailable_even_with_openai_key(client, local, monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "off")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(llm, "transcribe", lambda *a: pytest.fail("off이면 전사하지 않는다"))
    h, aid = answer(client)
    assert upload(client, h, aid, webm()).json()["stt_status"] == "unavailable"
    r = client.post(f"/practice/answers/{aid}/transcribe", headers=h)
    assert r.status_code == 503 and "STT_PROVIDER=off" in r.json()["detail"]
    health = client.get("/health").json()
    assert health["openai"] is True and health["stt"]["provider"] == "off" and health["stt"]["available"] is False


def test_health_separates_stt_from_ai_coaching(client, local):
    health = client.get("/health").json()
    assert health["openai"] is False  # AI 코칭·질문 생성·디브리프는 꺼짐
    assert health["stt"]["provider"] == "local" and health["stt"]["available"] is True


def test_openai_provider_still_uses_openai_with_key(client, monkeypatch):
    monkeypatch.setattr(settings, "stt_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert client.get("/health").json()["stt"] == {"provider": "openai", "available": False,
                                                   "model": settings.openai_stt_model, "state": None, "error": None}
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(llm, "transcribe", lambda audio, filename, ctype: "오픈AI 전사")
    h, aid = answer(client)
    assert upload(client, h, aid, b"simulated").json()["transcript"] == "오픈AI 전사"
