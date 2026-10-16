"""OpenAI 호출(맞춤 질문 생성, 음성 전사, 루브릭 채점, 세션 디브리프).

OPENAI_API_KEY가 없으면 생성은 템플릿 기반으로 대체하고, 전사·채점·디브리프는 쓰지 않는다.
SDK 버전 차이를 피하려고 REST 엔드포인트를 httpx로 직접 호출한다.
"""
import json
import re
from datetime import datetime, timezone

import httpx

from .config import settings
from .rubric import (
    BANDS,
    CRITERIA,
    LABELS,
    NA_ALLOWED,
    QUESTION_TYPES,
    RUBRIC,
    VARIANTS,
    not_applicable,
    relevance_ties_to_job,
    transcript_sha,
)


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
    hypo, plain = VARIANTS["action"], VARIANTS["relevance"]
    lines += [
        "",
        "[가상 상황 앵커] 가상 상황·대처 방식 질문의 action은 아래로 채점한다",
        *[f"  · {band}: {anchor}" for band, anchor in hypo["anchors"].items()],
        "[직무 연결 없는 앵커] [질문·직무 연결]이 '보지 않음'일 때 relevance는 아래로 채점한다",
        *[f"  · {band}: {anchor}" for band, anchor in plain["anchors"].items()],
        "",
        f"[등급] {' | '.join(BANDS)}",
        "- 어떤 기준이 '해당 없음'인지는 사용자 메시지의 [질문 유형]을 따른다. "
        "'해당 없음'으로 정해진 기준은 band만 '해당 없음'으로 두고 quote와 comment는 비운다.",
        "- relevance는 항상 채점한다.",
        "",
        "[규칙]",
        "1. 앵커에 엄격히 맞춰 채점하고 후하게 주지 마라. LLM 채점자는 사람보다 관대하다고 알려져 있다. "
        "두 등급 사이에서 망설여지면 낮은 쪽(충분 → 일부 → 부족)을 준다. '해당 없음'은 이 순서에 들지 않는다: "
        "채점할 기준을 '해당 없음'으로 피하지 말고, 해당 없는 기준을 '부족'으로 만들지도 마라.",
        "2. 장점을 지어내지 마라. 잘한 점을 몇 개 말해야 한다는 규칙은 없다.",
        "3. 모든 판단에는 전사문을 그대로 인용한다. 전사문에서 정확한 구간을 복사하고 고치거나 요약하지 마라. "
        "인용할 때는 말버릇·문장부호도 전사문 그대로 둔다(규칙 5는 등급 판단에만 적용한다). "
        "인용을 비워 두는 것은 무언가가 없어서 등급이 '부족' 또는 '해당 없음'일 때뿐이다.",
        "4. 말의 내용만 판단한다. 목소리, 감정, 성격, 외모는 추정하지도 평가하지도 마라.",
        "5. 등급을 정할 때 말버릇·더듬음(음, 어 등)은 무시한다. 전사 과정에서 빠졌을 수 있다.",
        "6. '본인 행동'은 팀 안에서 말하는 사람이 직접 맡은 역할과 한 일을 뜻한다. '나', '제가' 같은 단어 수로 판단하지 마라. "
        "'우리'를 '저'로 바꾸라는 조언은 하지 않는다. 팀이 한 일은 그대로 두고, 그 안에서 본인이 맡은 몫과 판단을 "
        "구체적 행동으로 덧붙이도록 조언한다.",
        "7. 답의 내용이 맞는지(정답 여부)는 채점하지 않는다. 답변의 구조와 근거만 본다.",
        "",
        "JSON으로만 답한다:",
        '{"criteria":[{"key":"situation|action|result|relevance","band":"충분|일부|부족|해당 없음",'
        '"quote":"전사문 그대로","comment":"판단 근거 한 문장"}],'
        '"rewrite":["개선 문장 1","개선 문장 2(선택)"],"summary":"한 문장"}',
        "criteria에는 네 기준을 루브릭 순서대로 한 번씩 넣는다. rewrite에는 이 답변을 낫게 만들 실제 문장을 1~2개 쓴다. "
        "전사문에 없는 사실·수치·역할은 지어내지 말고 [수치]·[기간]·[본인 역할] 같은 빈칸으로 남긴다. "
        "말한 내용의 순서와 표현만 고친다.",
    ]
    return "\n".join(lines)


_GRADE_SYSTEM = _grade_system()

# 인용 앞뒤에 붙는 따옴표·말줄임표
_QUOTE_EDGES = re.compile(r"^(?:[\s\"'“”‘’「」『』…]|\.{2,})+|(?:[\s\"'“”‘’「」『』…]|\.{2,})+$")
# 느슨한 인용 비교: 문장부호·따옴표로 끊고, 홀로 쓰인 말버릇은 뺀다
_WORD = re.compile(r"[^\s.,!?…~·\"'“”‘’「」『』()\[\]]+")
_FILLERS = {"음", "어", "그"}
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


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
    if q in _squash(transcript or ""):
        return q, True
    lq, _ = _loose(q)
    if not lq:  # 말버릇·문장부호뿐인 인용은 빈 인용으로 본다
        return None, None
    lt, pos = _loose(transcript or "")
    i = lt.find(lq)
    if i < 0:
        return None, False
    return _squash((transcript or "")[pos[i]: pos[i + len(lq) - 1] + 1]), True


def _blank_new_numbers(line: str, known: set[str]) -> str:
    """개선 문장에서 전사문·질문에 없던 숫자는 [수치] 빈칸으로 바꾼다(지어낸 성과를 연습하지 않게)."""
    return _NUM.sub(lambda m: m.group() if m.group() in known else "[수치]", line)


def _not_applicable_row(key: str) -> dict:
    return {"key": key, "label": LABELS[key], "band": "해당 없음", "quote": None, "quote_verified": None,
            "comment": None}


def normalize_feedback(raw: dict, transcript: str, qtype: str | None = None, question: str | None = None) -> dict:
    """모델 응답을 루브릭에 맞춰 거른다: 아는 기준만 루브릭 순서로 한 번씩, 올바른 등급만, 인용은 전사문에 있는 것만.

    qtype(질문 유형)이 있으면 '해당 없음'은 서버가 정한다: 해당 없는 기준은 모델 답과 상관없이 '해당 없음',
    채점할 기준에 모델이 '해당 없음'을 주면 '부족'으로 본다. 인용으로 확인되지 않은 '충분'은 '일부'로 낮춘다.
    """
    forced = not_applicable(qtype)  # None이면 모델이 '해당 없음'을 판단
    given: dict[str, dict] = {}
    items = raw.get("criteria") if isinstance(raw, dict) else None
    for c in items if isinstance(items, list) else []:
        if not isinstance(c, dict):
            continue
        key, band = c.get("key"), c.get("band")
        if not isinstance(key, str) or not isinstance(band, str):
            continue
        if key not in LABELS or key in given or band not in BANDS:
            continue
        if forced is not None and key in forced:
            continue  # 아래에서 '해당 없음'으로 채운다
        if band == "해당 없음":
            if forced is None and key not in NA_ALLOWED:
                continue
            if forced is not None:
                # 채점해야 하는 기준을 '해당 없음'으로 피해 가지 않게(관대한 채점 방지)
                given[key] = {**_not_applicable_row(key), "band": "부족"}
                continue
        quote, verified = verify_quote(c.get("quote"), transcript)
        item = {"key": key, "label": LABELS[key], "band": band, "quote": quote,
                "quote_verified": verified, "comment": _clip(c.get("comment"))}
        if band in ("충분", "일부") and verified is not True:
            # 전사문 인용으로 확인되지 않은 긍정 판단은 근거 없음으로 표시하고, '충분'은 '일부'로 낮춘다
            item["evidence_missing"] = True
            if band == "충분":
                item["band"], item["model_band"] = "일부", "충분"
        given[key] = item
    for key in forced or ():
        given[key] = _not_applicable_row(key)
    known = set(_NUM.findall(transcript or "")) | set(_NUM.findall(question or ""))
    rewrite = raw.get("rewrite") if isinstance(raw, dict) else None
    if isinstance(rewrite, str):
        rewrite = [rewrite]
    rewrite = [_blank_new_numbers(r, known) for r in (_clip(x) for x in rewrite) if r][:2] \
        if isinstance(rewrite, list) else []
    return {
        "criteria": [given[c["key"]] for c in CRITERIA if c["key"] in given],
        "rewrite": rewrite,
        "summary": _clip(raw.get("summary")) if isinstance(raw, dict) else None,
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _type_instruction(qtype: str) -> str:
    label = QUESTION_TYPES[qtype]
    if qtype == "general":
        return f"{label}: 질문이 과거 경험을 묻지 않으면 situation·action·result에 '해당 없음'을 쓸 수 있다."
    na = not_applicable(qtype) or set()
    if not na:
        return f"{label}: 네 기준을 모두 채점한다. '해당 없음'을 쓰지 않는다."
    names = "·".join(c["key"] for c in CRITERIA if c["key"] in na)
    extra = " action은 [가상 상황 앵커]로 채점한다." if qtype == "hypothetical" else " relevance만 채점한다."
    return f"{label}: {names}는 '해당 없음'(quote·comment 비움).{extra}"


def grade_answer(question: str, transcript: str, job_hint: str | None, qtype: str = "general") -> dict:
    """전사문을 루브릭으로 채점해 저장할 피드백 객체를 돌려준다. 형식이 틀리면 AIResponseError.

    qtype(rubric.question_type)으로 어떤 기준이 '해당 없음'인지와 직무 연결을 볼지를 서버가 정한다.
    """
    qtype = qtype if qtype in QUESTION_TYPES else "general"
    tie = relevance_ties_to_job(qtype, job_hint)
    user = "\n\n".join([
        f"[질문]\n{question}",
        f"[질문 유형]\n{_type_instruction(qtype)}",
        f"[지원 회사·직무]\n{job_hint or '(정보 없음)'}",
        "[질문·직무 연결]\n" + ("봄: 끝에서 지원 직무·회사와 연결하는지도 본다(루브릭 기본 앵커)." if tie
                              else "보지 않음: 직무·회사 연결은 보지 않고 [직무 연결 없는 앵커]로 채점한다."),
        f"[답변 전사문]\n{transcript}",
    ])
    fb = normalize_feedback(_chat_json(_GRADE_SYSTEM, user), transcript, qtype, question)
    forced = not_applicable(qtype) or set()
    if not any(c["key"] not in forced for c in fb["criteria"]):  # 모델이 실제로 채점한 기준이 하나도 없음
        raise AIResponseError("AI 응답을 해석하지 못했습니다")
    return {"rubric": RUBRIC["version"], "model": settings.openai_feedback_model, "question_type": qtype, **fb,
            "transcript_sha": transcript_sha(transcript), "graded_at": _utc_now_iso(), "stale": False}


# ───────── 세션 디브리프 ─────────

_DEBRIEF_SYSTEM = (
    "너는 면접 연습 세션을 돌아보는 코치다. 질문별 답변 전사문, 자기평가(1~5), 회고 메모, 루브릭 등급을 보고 "
    "다음 연습에 바로 쓸 디브리프를 만든다.\n"
    "규칙: 칭찬이나 격려로 채우지 마라. 근거가 있는 말만 한다. 인용은 전사문에서 정확한 구간을 그대로 복사한다. "
    "말의 내용만 다루고 목소리·감정·성격·외모는 추정하지 마라. 말버릇·더듬음은 무시한다. "
    "전사문에 없는 사실·수치는 지어내지 마라. 등급의 뜻은 rubric에 있다. "
    "'우리'를 '저'로 바꾸라는 조언은 하지 않는다. 팀이 한 일은 그대로 두고, 그 안에서 본인이 맡은 몫과 판단을 "
    "구체적 행동으로 덧붙이도록 조언한다.\n"
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
    rubric = {c["label"]: c["question"] for c in CRITERIA}  # bands의 각 기준이 무엇을 보는지
    raw = _chat_json(_DEBRIEF_SYSTEM, json.dumps({"rubric": rubric, "answers": payload}, ensure_ascii=False))
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
