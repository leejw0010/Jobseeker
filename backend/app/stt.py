"""음성 전사(STT) 제공자. STT_PROVIDER=local|openai|off 중 하나를 쓴다.

local  : faster-whisper(다국어 Whisper)로 이 서버의 CPU에서 한국어로 전사한다. 녹음을 외부로 보내지 않는다.
         모델은 첫 전사 때 한 번 불러와 재사용한다. 캐시에 있으면 네트워크 없이 쓰고, 없을 때만 한 번 내려받는다.
openai : OpenAI 음성 인식 API(llm.transcribe). OPENAI_API_KEY가 있어야 한다.
off    : 자동 전사를 끈다. 녹음은 저장하고 stt_status는 unavailable.

전사 가능 여부는 LLM(맞춤 질문·답변 코칭·디브리프)의 OpenAI 키와 따로 판단한다.
전사하지 못한 녹음은 STTError로 알린다. 라우터는 이를 실패(stt_status=failed)로 보고 원본을 남겨 다시 시도하게 한다.
"""
import gc
import importlib.util
import io
import logging
import os
import sys
import threading
import time

import httpx

from . import llm
from .config import settings

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
SILENCE_PEAK = 1e-3  # 이보다 작은 진폭뿐이면 말소리가 없는 녹음으로 본다(16비트 기준 약 33)


class STTError(Exception):
    """이번 녹음을 전사하지 못했다. reason: no_speech | invalid_audio | too_long | busy | model_download |
    model_load | provider_error. 메시지는 사용자에게 보여도 되는 문장이다(경로·키 같은 내부 정보는 넣지 않는다)."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


# ───────── 꺼짐 ─────────

class _Off:
    name = "off"

    def available(self) -> bool:
        return False

    def unavailable_reason(self) -> str:
        return "자동 전사가 꺼져 있습니다(STT_PROVIDER=off)"

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> str:
        raise STTError("provider_error", self.unavailable_reason())

    def details(self) -> dict:
        return {}


# ───────── OpenAI ─────────

class _OpenAI:
    """기존 OpenAI 음성 인식. 호출 시점에 llm.transcribe를 찾으므로 테스트가 바꿔 끼울 수 있다."""

    name = "openai"

    def available(self) -> bool:
        return llm.available()

    def unavailable_reason(self) -> str:
        return "OPENAI_API_KEY가 설정되지 않아 전사를 할 수 없습니다"

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> str:
        try:
            text = llm.transcribe(audio, filename, content_type)
        except httpx.HTTPError as e:
            raise STTError("provider_error", "음성 인식 요청이 실패했어요") from e
        except llm.TranscriptionError as e:
            raise STTError("no_speech", "말소리를 인식하지 못했어요") from e
        if not (text or "").strip():
            raise STTError("no_speech", "말소리를 인식하지 못했어요")
        return text.strip()

    def details(self) -> dict:
        return {"model": settings.openai_stt_model}


# ───────── 로컬 faster-whisper ─────────

def _backend():
    """(WhisperModel, download_model). 무거운 import를 첫 전사까지 미룬다. 테스트는 이 함수를 가짜로 바꾼다."""
    from faster_whisper import WhisperModel
    from faster_whisper.utils import download_model
    return WhisperModel, download_model


def decode(data: bytes, max_sec: float) -> "numpy.ndarray":  # noqa: F821 (numpy는 첫 전사 때 불러온다)
    """녹음(WebM/Opus, MP4/AAC, WAV 등)을 PyAV로 16kHz 모노 float32 배열로 푼다.

    max_sec를 넘으면 끝까지 풀지 않고 too_long으로 멈춘다(메모리·CPU 보호). 풀 수 없으면 invalid_audio.
    """
    import av
    import numpy as np

    limit = int(max_sec * SAMPLE_RATE)
    chunks, n = [], 0
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    try:
        with av.open(io.BytesIO(data), mode="r") as container:
            if not container.streams.audio:
                raise STTError("invalid_audio", "녹음에서 오디오를 찾지 못했어요")
            frames = container.decode(audio=0)
            while True:
                try:
                    frame = next(frames)
                except StopIteration:
                    break
                except av.error.InvalidDataError:
                    continue  # MediaRecorder가 끝에 남기는 깨진 프레임 등은 건너뛴다
                for out in resampler.resample(frame):
                    chunks.append(out.to_ndarray().reshape(-1))
                    n += chunks[-1].size
                if n > limit:
                    raise STTError("too_long", f"녹음이 {max_sec / 60:.0f}분을 넘어 자동 전사하지 않았어요")
            for out in resampler.resample(None):
                chunks.append(out.to_ndarray().reshape(-1))
    except STTError:
        raise
    except Exception as e:  # PyAV는 형식마다 다른 예외(FFmpegError, ValueError, IndexError…)를 낸다
        log.info("local STT: cannot decode audio: %r", e)
        raise STTError("invalid_audio", "녹음 파일을 읽지 못했어요") from e
    finally:
        # PyAV 리샘플러가 잡은 메모리는 gc가 돌아야 풀린다(faster-whisper decode_audio와 같은 처리. 그 함수는 PyAV 19에서
        # 없어진 metadata_errors 인자를 넘겨 쓸 수 없어 직접 푼다)
        del resampler
        gc.collect()
    if not chunks:
        raise STTError("invalid_audio", "녹음에서 소리를 찾지 못했어요")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def run_whisper(model, samples, **overrides) -> tuple:
    """(전사문, 세그먼트 목록, info). 운영 전사와 STT 평가(backend/evals/stt)가 같은 인자·같은 결합을 쓰게 하는 한 곳.
    overrides는 평가에서만 쓴다(beam_size, vad_filter, hotwords, initial_prompt 등)."""
    options = dict(
        language="ko", task="transcribe", beam_size=settings.local_stt_beam_size,
        # 무음 구간을 미리 잘라 Whisper가 침묵에서 문장을 지어내는 것을 줄인다
        vad_filter=True, condition_on_previous_text=False,
    )
    options.update(overrides)
    segments, info = model.transcribe(samples, **options)
    segments = list(segments)
    return " ".join(t for t in (s.text.strip() for s in segments) if t), segments, info


class _Local:
    name = "local"

    def __init__(self):
        self._model = None
        self._key: tuple | None = None
        self._state = "not_loaded"  # not_loaded | loading | ready | error
        self._error: str | None = None
        self._load_lock = threading.Lock()
        # 노트북 CPU에서 전사를 겹쳐 돌리면 둘 다 느려진다: 한 번에 하나만 돌리고 나머지는 잠시 기다리게 한다
        self._slot = threading.Semaphore(1)
        self._installed: bool | None = None

    # 설정

    def _config(self) -> tuple:
        return (settings.local_stt_model, settings.local_stt_device, settings.local_stt_compute_type,
                settings.local_stt_cpu_threads, settings.local_stt_model_dir)

    def available(self) -> bool:
        if self._installed is None:
            self._installed = all(importlib.util.find_spec(m) is not None for m in ("faster_whisper", "av"))
        return self._installed

    def unavailable_reason(self) -> str:
        return "faster-whisper가 설치되지 않아 로컬 전사를 할 수 없습니다(pip install -r requirements.txt)"

    def details(self) -> dict:
        return {"model": settings.local_stt_model, "state": self._state, "error": self._error}

    # 모델

    def _resolve(self, download_model) -> str:
        """모델 경로. 폴더를 직접 지정했으면 그대로, 아니면 캐시를 먼저 보고 없을 때만 내려받는다."""
        name, cache = settings.local_stt_model, settings.local_stt_model_dir or None
        if os.path.isdir(name):
            return name
        try:
            return download_model(name, local_files_only=True, cache_dir=cache)
        except ValueError:
            raise STTError("model_load", f"알 수 없는 모델 이름이에요: {name}")
        except Exception:
            pass  # 캐시에 없다
        if not settings.local_stt_allow_download:
            raise STTError("model_download", "모델이 캐시에 없고 내려받기가 꺼져 있어요(LOCAL_STT_ALLOW_DOWNLOAD)")
        log.info("local STT: downloading model %s", name)
        try:
            return download_model(name, cache_dir=cache)
        except Exception as e:
            log.warning("local STT: model download failed: %r", e)
            raise STTError("model_download", "음성 인식 모델을 내려받지 못했어요. 네트워크를 확인한 뒤 다시 시도해 주세요") from e

    def model(self):
        """불러 둔 모델. 처음 한 번만 불러오고(동시에 들어와도 한 번), 설정이 바뀌었으면 다시 불러온다.

        실패는 기억하지 않는다: 다음 전사가 다시 시도한다(네트워크가 돌아왔거나 파일을 받아 둔 경우).
        """
        key = self._config()
        if self._model is not None and self._key == key:
            return self._model
        with self._load_lock:
            if self._model is not None and self._key == key:
                return self._model
            self._state, self._model = "loading", None
            started = time.monotonic()
            try:
                try:
                    WhisperModel, download_model = _backend()
                except Exception as e:  # 설치는 됐지만 CTranslate2 등을 불러오지 못했다
                    log.warning("local STT: cannot import faster-whisper: %r", e)
                    raise STTError("model_load", "음성 인식 라이브러리를 불러오지 못했어요. 설치 상태를 확인해 주세요") from e
                path = self._resolve(download_model)
                try:
                    model = WhisperModel(path, device=settings.local_stt_device,
                                         compute_type=settings.local_stt_compute_type,
                                         cpu_threads=settings.local_stt_cpu_threads)
                except Exception as e:
                    log.warning("local STT: model load failed: %r", e)
                    raise STTError("model_load", "음성 인식 모델을 불러오지 못했어요. 모델 파일이나 설정을 확인해 주세요") from e
            except STTError as e:
                self._state, self._error = "error", e.message
                raise
            self._model, self._key, self._state, self._error = model, key, "ready", None
            log.info("local STT: loaded %s (%s, %s, %d threads) in %.1fs", settings.local_stt_model,
                     settings.local_stt_device, settings.local_stt_compute_type, settings.local_stt_cpu_threads,
                     time.monotonic() - started)
            return model

    # 전사

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> str:
        samples = decode(audio, settings.local_stt_max_audio_sec)
        if float(abs(samples).max()) < SILENCE_PEAK:
            raise STTError("no_speech", "녹음에 말소리가 없어요")
        if not self._slot.acquire(timeout=settings.local_stt_queue_timeout_sec):
            raise STTError("busy", "다른 녹음을 전사하느라 바빠요. 잠시 뒤 다시 시도해 주세요")
        try:
            model = self.model()
            started = time.monotonic()
            try:
                text, _, _ = run_whisper(model, samples)
            except Exception as e:
                log.warning("local STT: transcription failed: %r", e)
                raise STTError("provider_error", "음성 인식 중 오류가 났어요. 다시 시도해 주세요") from e
            log.info("local STT: %.1fs audio in %.1fs", samples.size / SAMPLE_RATE, time.monotonic() - started)
        finally:
            self._slot.release()
        if not text:
            raise STTError("no_speech", "말소리를 인식하지 못했어요")
        return text


# ───────── 선택 ─────────

_PROVIDERS = {"off": _Off(), "openai": _OpenAI(), "local": _Local()}


def provider():
    """지금 설정(STT_PROVIDER)의 제공자. 알 수 없는 값은 꺼짐으로 본다(앱이 시작할 때 경고를 남긴다)."""
    return _PROVIDERS.get(settings.stt_provider, _PROVIDERS["off"])


def available() -> bool:
    return provider().available()


def unavailable_reason() -> str:
    return provider().unavailable_reason()


def transcribe(audio: bytes, filename: str, content_type: str) -> str:
    """전사문. 전사하지 못했으면(무음·잘못된 파일·모델 실패·바쁨 등) STTError."""
    p = provider()
    try:
        return p.transcribe(audio, filename, content_type)
    except STTError as e:
        log.warning("STT (%s) failed: %s", p.name, e.reason)
        raise


def status() -> dict:
    """/health용. 모델을 불러오지는 않는다."""
    p = provider()
    return {"provider": p.name, "available": p.available(), "model": None, "state": None, "error": None,
            **p.details()}


if __name__ == "__main__":
    # 오프라인에서 쓰기 전에 모델을 미리 받아 두기: python -m app.stt download
    if sys.argv[1:] != ["download"]:
        sys.exit("usage: python -m app.stt download")
    local = _PROVIDERS["local"]
    if not local.available():
        sys.exit(local.unavailable_reason())
    try:
        local.model()
    except STTError as e:
        sys.exit(e.message)
    print(f"ready: {settings.local_stt_model} ({settings.local_stt_device}, {settings.local_stt_compute_type})")
