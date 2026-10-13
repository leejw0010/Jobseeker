"""OpenAI 호출(맞춤 질문 생성, 음성 전사, 답변 피드백).

OPENAI_API_KEY가 없으면 생성은 템플릿 기반으로 대체하고, 전사·피드백은 None을 돌려준다.
SDK 버전 차이를 피하려고 REST 엔드포인트를 httpx로 직접 호출한다.
"""
import json
import re

import httpx

from .config import settings

API = "https://api.openai.com/v1"


def available() -> bool:
    return bool(settings.openai_api_key)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.openai_api_key}"}


def _chat(system: str, user: str, json_mode: bool = False) -> str:
    body: dict = {
        "model": settings.openai_chat_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.7,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = httpx.post(f"{API}/chat/completions", headers=_headers(), json=body, timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


# ───────── 맞춤 질문 생성 ─────────

_GEN_SYSTEM = (
    "너는 한국 기업의 면접관이다. 지원자의 회사·직무·자기소개서를 보고 실제 면접에서 나올 법한 "
    "질문을 만든다. 자소서 내용을 구체적으로 파고드는 꼬리질문을 절반 이상 포함한다. "
    'JSON {"questions":[{"category":"인성|직무|기업|상황","text":"..."}]} 형식으로만 답한다.'
)


def generate_questions(company: str, position: str, essay: str, count: int) -> list[dict]:
    if not available():
        return _template_questions(company, position, essay, count)
    user = f"회사: {company}\n직무: {position}\n질문 수: {count}\n\n[자기소개서]\n{essay or '(없음)'}"
    try:
        data = json.loads(_chat(_GEN_SYSTEM, user, json_mode=True))
        out = [
            {"category": q.get("category", "인성") if q.get("category") in ("인성", "직무", "기업", "상황") else "인성",
             "text": q["text"].strip()}
            for q in data.get("questions", []) if q.get("text")
        ]
        return out[:count] or _template_questions(company, position, essay, count)
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError):
        return _template_questions(company, position, essay, count)


_EXPERIENCE_HINT = re.compile(r"(경험|프로젝트|담당|개선|해결|협업|리더|성과|달성|극복|도전)")


def _template_questions(company: str, position: str, essay: str, count: int) -> list[dict]:
    """API 키가 없을 때 쓰는 규칙 기반 질문. 자소서 문장 중 경험 서술을 골라 꼬리질문을 만든다."""
    company = company or "저희 회사"
    position = position or "해당 직무"
    qs: list[dict] = []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n+", essay or "") if len(s.strip()) >= 15]
    for s in sentences:
        if _EXPERIENCE_HINT.search(s):
            quote = s if len(s) <= 60 else s[:57] + "…"
            qs.append({"category": "직무", "text": f"자기소개서에 \"{quote}\"라고 쓰셨는데, 그때 본인의 역할과 결과를 구체적으로 설명해 주세요."})
        if len(qs) >= max(1, count // 2):
            break
    base = [
        {"category": "기업", "text": f"{company}에 지원한 이유와, 입사 후 {position}로서 이루고 싶은 목표를 말씀해 주세요."},
        {"category": "직무", "text": f"{position} 직무에 필요한 역량은 무엇이라고 생각하며, 본인은 그 역량을 어떻게 갖췄나요?"},
        {"category": "상황", "text": "팀원과 의견이 크게 엇갈렸던 상황에서 어떻게 조율했는지 말씀해 주세요."},
        {"category": "인성", "text": "가장 크게 실패했던 경험과 그 경험에서 배운 점을 말씀해 주세요."},
        {"category": "기업", "text": f"{company}의 최근 사업이나 서비스 중 관심 있게 본 것과, 개선하고 싶은 점이 있다면 말씀해 주세요."},
        {"category": "직무", "text": f"입사 후 3년 안에 {position}로서 어떤 전문성을 쌓고 싶은지 말씀해 주세요."},
    ]
    for q in base:
        if len(qs) >= count:
            break
        qs.append(q)
    return qs[:count]


# ───────── 음성 전사 ─────────

def transcribe(audio: bytes, filename: str, content_type: str) -> str | None:
    if not available():
        return None
    r = httpx.post(
        f"{API}/audio/transcriptions",
        headers=_headers(),
        data={"model": settings.openai_stt_model, "language": "ko", "response_format": "json"},
        files={"file": (filename, audio, content_type or "audio/webm")},
        timeout=120,
    )
    r.raise_for_status()
    return r.json().get("text", "").strip()


# ───────── 답변 피드백 ─────────

_FEEDBACK_SYSTEM = (
    "너는 면접 코치다. 면접 질문과 지원자의 답변 전사문을 보고 한국어로 간결하게 피드백한다. "
    "형식: '잘한 점' 2개, '보완할 점' 2개, '한 줄 개선 예시' 1개. 각 항목은 한 문장. "
    "말버릇(음, 어 등)이나 답변 길이 문제가 있으면 보완할 점에 포함한다."
)


def feedback(question: str, transcript: str, duration_sec: float | None) -> str | None:
    if not available():
        return None
    dur = f"{duration_sec:.0f}초" if duration_sec else "알 수 없음"
    return _chat(_FEEDBACK_SYSTEM, f"[질문]\n{question}\n\n[답변 길이] {dur}\n\n[답변 전사문]\n{transcript}").strip()
