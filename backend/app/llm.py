"""OpenAI 호출(맞춤 질문 생성, 음성 전사, 답변 피드백, 세션 디브리프).

OPENAI_API_KEY가 없으면 생성은 템플릿 기반으로 대체하고, 전사·피드백·디브리프는 쓰지 않는다.
SDK 버전 차이를 피하려고 REST 엔드포인트를 httpx로 직접 호출한다. 주소는 OPENAI_BASE_URL(기본 OpenAI)이다.
"""
import json
import re

import httpx

from .config import settings


class AIResponseError(ValueError):
    """모델 응답이 약속한 JSON 형식이 아닐 때."""


def available() -> bool:
    return bool(settings.openai_api_key)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.openai_api_key}"}


def _chat(system: str, user: str, json_mode: bool = False, temperature: float = 0.7, model: str | None = None) -> str:
    body: dict = {
        "model": model or settings.openai_chat_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = httpx.post(f"{settings.openai_base_url}/chat/completions", headers=_headers(), json=body, timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _chat_json(system: str, user: str) -> dict:
    """디브리프용 호출: 피드백 모델, 낮은 temperature, JSON 응답."""
    try:
        raw = _chat(system, user, json_mode=True, temperature=0.2, model=settings.openai_feedback_model)
        raw = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw or "")
        data = json.loads(raw)
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise AIResponseError("AI 응답을 해석하지 못했습니다") from e
    if not isinstance(data, dict):
        raise AIResponseError("AI 응답을 해석하지 못했습니다")
    return data


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

class TranscriptionError(ValueError):
    """A provider response contained no usable transcript."""


def transcribe(audio: bytes, filename: str, content_type: str) -> str | None:
    if not available():
        return None
    r = httpx.post(
        f"{settings.openai_base_url}/audio/transcriptions",
        headers=_headers(),
        data={"model": settings.openai_stt_model, "language": "ko", "response_format": "json"},
        files={"file": (filename, audio, content_type or "audio/webm")},
        timeout=120,
    )
    r.raise_for_status()
    try:
        payload = r.json()
    except ValueError as exc:
        raise TranscriptionError("Invalid transcription response") from exc
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise TranscriptionError("No speech recognized")
    return text.strip()


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


# ───────── 세션 디브리프 ─────────

# 인용 앞뒤에 붙는 따옴표·말줄임표
_QUOTE_EDGES = re.compile(r"^(?:[\s\"'“”‘’「」『』…]|\.{2,})+|(?:[\s\"'“”‘’「」『』…]|\.{2,})+$")
# 느슨한 인용 비교: 문장부호·따옴표로 끊고, 홀로 쓰인 말버릇은 뺀다
_WORD = re.compile(r"[^\s.,!?…~·\"'“”‘’「」『』()\[\]]+")
_FILLERS = {"음", "어", "그"}
MIN_QUOTE_CHARS = 4  # 근거로 인정하는 인용의 최소 글자 수(공백·문장부호·말버릇 제외)


def _squash(text: str) -> str:
    return " ".join(text.split())


def _clip(value, limit: int = 200) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip()[:limit] or None


def _loose(text: str) -> tuple[str, list[int]]:
    """문장부호·말버릇을 뺀 비교용 문자열과, 그 글자마다 원래 문자열에서의 위치."""
    out: list[str] = []
    pos: list[int] = []
    for m in _WORD.finditer(text or ""):
        if m.group() in _FILLERS:
            continue
        if out:
            out.append(" ")
            pos.append(m.start())
        out.extend(m.group())
        pos.extend(range(m.start(), m.end()))
    return "".join(out), pos


def verify_quote(quote, transcript: str) -> tuple[str | None, bool | None]:
    """인용이 전사문의 실제 구간인지 확인한다. (인용, 확인 여부) — 비었으면 (None, None), 지어냈으면 (None, False).

    문장부호나 말버릇(음·어·그)만 다르면 같은 구간으로 보고, 화면에는 전사문의 그 구간을 그대로 보여준다.
    """
    if not isinstance(quote, str):
        return None, None
    q = _squash(_QUOTE_EDGES.sub("", quote))
    if not q:
        return None, None
    lq, _ = _loose(q)
    if not lq:  # 말버릇·문장부호뿐인 인용은 빈 인용으로 본다
        return None, None
    if len(lq.replace(" ", "")) < MIN_QUOTE_CHARS:  # '네', '저는'처럼 짧은 인용은 근거로 치지 않는다
        return None, False
    if q in _squash(transcript or ""):
        return q, True
    lt, pos = _loose(transcript or "")
    i = lt.find(lq)
    if i < 0:
        return None, False
    return _squash((transcript or "")[pos[i]: pos[i + len(lq) - 1] + 1]), True


_DEBRIEF_SYSTEM = (
    "너는 면접 연습 세션을 돌아보는 코치다. 질문별 답변 전사문, 자기평가(1~5), 회고 메모, 답변 코칭의 기준별 상태"
    "(충분|보완|판단유보)를 보고 다음 연습에 바로 쓸 디브리프를 만든다.\n"
    "규칙: 칭찬이나 격려로 채우지 마라. 근거가 있는 말만 한다. 인용은 전사문에서 정확한 구간을 그대로 복사한다. "
    "말의 내용만 다루고 목소리·감정·성격·외모는 추정하지 마라. 말버릇·더듬음은 무시한다. "
    "전사문에 없는 사실·수치는 지어내지 마라. 기준의 뜻은 criteria에 있다. coaching_method가 basic이면 "
    "규칙 기반 점검이라 의미를 판정한 결과가 아니다. 말한 내용이 맞는지(정답 여부)는 판단하지 않는다. "
    "'우리'를 '저'로 바꾸라는 조언은 하지 않는다. 팀이 한 일은 그대로 두고, 그 안에서 본인이 맡은 몫과 판단을 "
    "구체적 행동으로 덧붙이도록 조언한다.\n"
    'JSON으로만 답한다: {"lesson":"이번 세션의 핵심 교훈 한 문장","next_action":"다음 연습에서 할 구체적 행동 한 문장",'
    '"moments":[{"order_no":1,"quote":"전사문 그대로","why":"한 문장"}]}\n'
    "moments는 다시 들여다볼 가치가 있는 구간(가장 고칠 만한 부분)을 최대 2개 고른다."
)


def debrief_summary(items: list[dict], criteria: dict[str, str]) -> dict:
    """세션 전체 디브리프. items: {answer_id, order_no, question, transcript, self_rating, reflection_note,
    coaching_method, coaching}. criteria: 코칭 기준 이름 → 무엇을 보는지."""
    payload = [
        {"order_no": it["order_no"], "question": it["question"],
         "transcript": (it.get("transcript") or "")[:1500] or "(전사문 없음)",
         "self_rating": it.get("self_rating"), "reflection_note": it.get("reflection_note"),
         "coaching_method": it.get("coaching_method"), "coaching": it.get("coaching") or {}}
        for it in items
    ]
    raw = _chat_json(_DEBRIEF_SYSTEM, json.dumps({"criteria": criteria, "answers": payload}, ensure_ascii=False))
    lesson, next_action = _clip(raw.get("lesson")), _clip(raw.get("next_action"))
    if not (lesson or next_action):
        raise AIResponseError("AI 응답을 해석하지 못했습니다")
    by_no = {it["order_no"]: it for it in items}
    moments = []
    for m in raw.get("moments") if isinstance(raw.get("moments"), list) else []:
        if not isinstance(m, dict) or len(moments) >= 2:
            continue
        try:
            it = by_no.get(int(m.get("order_no")))
        except (TypeError, ValueError):
            continue
        if not it:
            continue
        quote, verified = verify_quote(m.get("quote"), it.get("transcript") or "")
        if verified:
            moments.append({"answer_id": it["answer_id"], "order_no": it["order_no"], "quote": quote,
                            "why": _clip(m.get("why"))})
    return {"lesson": lesson, "next_action": next_action, "moments": moments}
