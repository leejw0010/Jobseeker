"""OpenAI 호출(맞춤 질문 생성, 음성 전사, 루브릭 채점, 세션 디브리프).

OPENAI_API_KEY가 없으면 생성은 템플릿 기반으로 대체하고, 전사·채점·디브리프는 쓰지 않는다.
SDK 버전 차이를 피하려고 REST 엔드포인트를 httpx로 직접 호출한다.
"""
import json
import re
from datetime import datetime, timezone

import httpx

from .config import settings
from .rubric import BANDS, CRITERIA, LABELS, NA_ALLOWED, RUBRIC


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
    """채점·디브리프용 호출: 피드백 모델, 낮은 temperature, JSON 응답."""
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
    return r.json().get("text", "").strip()




# ───────── 루브릭 채점 ─────────

def _grade_system() -> str:
    lines = [
        "너는 한국어 면접 답변을 채점하는 평가자다. 아래 루브릭의 기준 문장(앵커)에만 맞춰 등급을 매긴다.",
        "",
        "[루브릭]",
    ]
    for c in CRITERIA:
        lines.append(f"- {c['key']} ({c['label']}): {c['question']}")
        lines += [f"  · {band}: {anchor}" for band, anchor in c["anchors"].items()]
    lines += [
        "",
        f"[등급] {' | '.join(BANDS)}",
        "- '해당 없음'은 질문이 과거 경험을 묻지 않을 때(예: 지원 동기, 지식 질문) situation·action·result에만 쓴다. "
        "relevance는 항상 채점한다.",
        "",
        "[규칙]",
        "1. 앵커에 엄격히 맞춰 채점하고 후하게 주지 마라. LLM 채점자는 사람보다 관대하다고 알려져 있다. "
        "두 등급 사이에서 망설여지면 낮은 쪽을 준다.",
        "2. 장점을 지어내지 마라. 잘한 점을 몇 개 말해야 한다는 규칙은 없다.",
        "3. 모든 판단에는 전사문을 그대로 인용한다. 전사문에서 정확한 구간을 복사하고 고치거나 요약하지 마라. "
        "인용을 비워 두는 것은 무언가가 없어서 등급이 '부족' 또는 '해당 없음'일 때뿐이다.",
        "4. 말의 내용만 판단한다. 목소리, 감정, 성격, 외모는 추정하지도 평가하지도 마라.",
        "5. 말버릇·더듬음(음, 어 등)은 무시한다. 전사 과정에서 빠졌을 수 있다.",
        "6. '본인 행동'은 팀 안에서 말하는 사람이 직접 맡은 역할과 한 일을 뜻한다. '나', '제가' 같은 단어 수로 판단하지 마라.",
        "",
        "JSON으로만 답한다:",
        '{"criteria":[{"key":"situation|action|result|relevance","band":"충분|일부|부족|해당 없음",'
        '"quote":"전사문 그대로","comment":"판단 근거 한 문장"}],'
        '"rewrite":["개선 문장 1","개선 문장 2(선택)"],"summary":"한 문장"}',
        "criteria에는 네 기준을 루브릭 순서대로 한 번씩 넣는다. rewrite에는 이 답변을 낫게 만들 실제 문장을 1~2개 쓴다.",
    ]
    return "\n".join(lines)


_GRADE_SYSTEM = _grade_system()

# 인용 앞뒤에 붙는 따옴표·말줄임표
_QUOTE_EDGES = re.compile(r"^(?:[\s\"'“”‘’「」『』…]|\.{2,})+|(?:[\s\"'“”‘’「」『』…]|\.{2,})+$")


def _squash(text: str) -> str:
    return " ".join(text.split())


def _clip(value, limit: int = 200) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip()[:limit] or None


def verify_quote(quote, transcript: str) -> tuple[str | None, bool | None]:
    """인용이 전사문의 실제 구간인지 확인한다. (인용, 확인 여부) — 비었으면 (None, None), 지어냈으면 (None, False)."""
    if not isinstance(quote, str):
        return None, None
    q = _squash(_QUOTE_EDGES.sub("", quote))
    if not q:
        return None, None
    if q in _squash(transcript or ""):
        return q, True
    return None, False


def normalize_feedback(raw: dict, transcript: str) -> dict:
    """모델 응답을 루브릭에 맞춰 거른다: 아는 기준만 루브릭 순서로 한 번씩, 올바른 등급만, 인용은 전사문에 있는 것만."""
    given: dict[str, dict] = {}
    items = raw.get("criteria") if isinstance(raw, dict) else None
    for c in items if isinstance(items, list) else []:
        if not isinstance(c, dict):
            continue
        key, band = c.get("key"), c.get("band")
        if key not in LABELS or key in given or band not in BANDS:
            continue
        if band == "해당 없음" and key not in NA_ALLOWED:
            continue
        quote, verified = verify_quote(c.get("quote"), transcript)
        given[key] = {"key": key, "label": LABELS[key], "band": band, "quote": quote,
                      "quote_verified": verified, "comment": _clip(c.get("comment"))}
    rewrite = raw.get("rewrite") if isinstance(raw, dict) else None
    if isinstance(rewrite, str):
        rewrite = [rewrite]
    rewrite = [r for r in (_clip(x) for x in rewrite) if r][:2] if isinstance(rewrite, list) else []
    return {
        "criteria": [given[c["key"]] for c in CRITERIA if c["key"] in given],
        "rewrite": rewrite,
        "summary": _clip(raw.get("summary")) if isinstance(raw, dict) else None,
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def grade_answer(question: str, transcript: str, job_hint: str | None) -> dict:
    """전사문을 루브릭으로 채점해 저장할 피드백 객체를 돌려준다. 형식이 틀리면 AIResponseError."""
    user = f"[질문]\n{question}\n\n[지원 회사·직무]\n{job_hint or '(정보 없음)'}\n\n[답변 전사문]\n{transcript}"
    fb = normalize_feedback(_chat_json(_GRADE_SYSTEM, user), transcript)
    if not fb["criteria"]:
        raise AIResponseError("AI 응답을 해석하지 못했습니다")
    return {"rubric": RUBRIC["version"], "model": settings.openai_feedback_model, **fb,
            "graded_at": _utc_now_iso(), "stale": False}


# ───────── 세션 디브리프 ─────────

_DEBRIEF_SYSTEM = (
    "너는 면접 연습 세션을 돌아보는 코치다. 질문별 답변 전사문, 자기평가(1~5), 회고 메모, 루브릭 등급을 보고 "
    "다음 연습에 바로 쓸 디브리프를 만든다.\n"
    "규칙: 칭찬이나 격려로 채우지 마라. 근거가 있는 말만 한다. 인용은 전사문에서 정확한 구간을 그대로 복사한다. "
    "말의 내용만 다루고 목소리·감정·성격·외모는 추정하지 마라. 말버릇·더듬음은 무시한다.\n"
    'JSON으로만 답한다: {"lesson":"이번 세션의 핵심 교훈 한 문장","next_action":"다음 연습에서 할 구체적 행동 한 문장",'
    '"moments":[{"order_no":1,"quote":"전사문 그대로","why":"한 문장"}]}\n'
    "moments는 다시 들여다볼 가치가 있는 구간(가장 고칠 만한 부분)을 최대 2개 고른다."
)


def debrief_summary(items: list[dict]) -> dict:
    """세션 전체 디브리프. items: {answer_id, order_no, question, transcript, self_rating, reflection_note, bands}."""
    payload = [
        {"order_no": it["order_no"], "question": it["question"],
         "transcript": (it.get("transcript") or "")[:1500] or "(전사문 없음)",
         "self_rating": it.get("self_rating"), "reflection_note": it.get("reflection_note"),
         "bands": it.get("bands") or {}}
        for it in items
    ]
    raw = _chat_json(_DEBRIEF_SYSTEM, json.dumps({"answers": payload}, ensure_ascii=False))
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
