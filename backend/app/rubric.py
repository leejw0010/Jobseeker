"""STAR 루브릭 정의. 채점 프롬프트(llm.py)와 GET /practice/rubric이 함께 쓴다.

숫자 점수 대신 행동 기준(앵커)이 있는 3단계 등급을 쓰고, 모든 판단은 전사문 인용을 붙인다.
어떤 기준이 '해당 없음'인지는 모델에 맡기지 않고 질문 유형(question_type)으로 서버가 정한다.
"""
import hashlib
import re

RUBRIC = {
    "version": "star-v1",
    "bands": ["충분", "일부", "부족", "해당 없음"],
    "criteria": [
        {"key": "situation", "label": "상황·과제",
         "question": "언제, 어떤 상황에서 무엇을 해내야 했는지 분명한가?",
         "anchors": {"충분": "시기·맥락과 본인이 맡은 과제를 한두 문장으로 분명히 말한다",
                     "일부": "맥락은 있지만 과제나 목표가 흐릿하다",
                     "부족": "상황 설명 없이 결론이나 일반론만 말한다"}},
        {"key": "action", "label": "본인 행동",
         "question": "팀 맥락 안에서 본인이 직접 한 일과 그 판단 근거가 드러나는가?",
         "anchors": {"충분": "본인이 직접 한 행동을 구체적으로, 왜 그렇게 했는지와 함께 말한다",
                     "일부": "행동은 있지만 '열심히 했다' 수준이거나 팀이 한 일과 본인 몫이 섞여 있다",
                     "부족": "행동 설명 없이 다짐이나 성격 묘사만 있다"}},
        {"key": "result", "label": "결과·배운 점",
         "question": "결과를 확인할 수 있는 사실이나 수치로 말하고, 배운 점을 덧붙이는가?",
         "anchors": {"충분": "결과를 수치나 확인 가능한 사실로 말하고 배운 점을 덧붙인다",
                     "일부": "결과는 있지만 '좋아졌다'처럼 막연하다",
                     "부족": "결과를 말하지 않는다"}},
        {"key": "relevance", "label": "질문·직무 연결",
         "question": "첫 문장에서 질문에 답하고, 지원 직무·회사와 연결하는가?",
         "anchors": {"충분": "첫 문장에서 질문에 바로 답하고 끝에서 직무·회사와 연결한다",
                     "일부": "질문에는 답하지만 결론이 늦거나 직무 연결이 약하다",
                     "부족": "질문과 다른 이야기를 하거나 무엇을 말하려는지 드러나지 않는다"}},
    ],
    # 질문 유형에 따라 바꿔 쓰는 앵커
    "variants": [
        {"key": "action", "when": "가상 상황·대처 방식 질문",
         "anchors": {"충분": "구체적인 대응 순서와 그렇게 하는 이유를 말한다",
                     "일부": "대응 방향은 있지만 '잘 소통하겠다'처럼 막연하다",
                     "부족": "대응 없이 다짐이나 일반론만 말한다"}},
        {"key": "relevance", "when": "지식·의견·인적성·가상 상황 질문이거나 지원 회사·직무 정보가 없을 때(직무 연결은 보지 않음)",
         "anchors": {"충분": "첫 문장에서 질문에 바로 답하고 끝까지 질문 범위 안에서 말한다",
                     "일부": "답은 하지만 결론이 늦거나 질문과 상관없는 이야기가 섞여 있다",
                     "부족": "질문과 다른 이야기를 하거나 무엇을 말하려는지 드러나지 않는다"}},
    ],
    "question_types": {
        "experience": "과거 경험 질문",
        "hypothetical": "가상 상황·대처 방식 질문",
        "self": "자기소개·지원 동기·포부·장단점 질문",
        "knowledge": "지식·의견 질문",
        "aptitude": "인적성 연습 문제",
        "general": "유형을 정하지 못한 질문",
    },
    "note": "AI 채점은 참고용이에요. 연구에서 LLM 채점과 전문가 채점의 일치도는 높지 않았어요(Kendall's τ=.19–.44). "
            "말한 내용이 맞는지(정답 여부)는 채점하지 않아요.",
}

BANDS: list[str] = RUBRIC["bands"]
CRITERIA: list[dict] = RUBRIC["criteria"]
LABELS: dict[str, str] = {c["key"]: c["label"] for c in CRITERIA}
# 유형을 정하지 못한 질문에서 모델이 '해당 없음'을 고를 수 있는 기준(relevance는 항상 채점)
NA_ALLOWED = {"situation", "action", "result"}
QUESTION_TYPES: dict[str, str] = RUBRIC["question_types"]
VARIANTS: dict[str, dict] = {v["key"]: v for v in RUBRIC["variants"]}

# 질문 유형별로 서버가 '해당 없음'으로 정하는 기준. general은 모델이 판단한다(None)
_NOT_APPLICABLE: dict[str, set[str] | None] = {
    "experience": set(),
    "hypothetical": {"situation", "result"},
    "self": {"situation", "action", "result"},
    "knowledge": {"situation", "action", "result"},
    "aptitude": {"situation", "action", "result"},
    "general": None,
}


def not_applicable(qtype: str | None) -> set[str] | None:
    """이 유형에서 채점하지 않는(해당 없음) 기준. None이면 서버가 정하지 않는다."""
    return _NOT_APPLICABLE.get(qtype or "general")


def relevance_ties_to_job(qtype: str | None, job_hint: str | None) -> bool:
    """질문·직무 연결에서 끝의 직무·회사 연결을 볼지. 경험·자기소개류 질문이고 지원 건의 회사·직무를 알 때만 본다."""
    return bool(job_hint) and (qtype or "general") in ("experience", "self", "general")


# 질문 유형 판별(규칙 기반). 인적성 → 과거 경험 → 가상 상황·대처 방식 → 자기소개류 순으로 보고,
# 단서가 없으면 공용 질문은 분류로 정하고 맞춤·직접 추가 질문은 'general'(모델이 판단)로 둔다
_SS = "".join(chr(0xAC00 + i * 28 + 20) for i in range(19 * 21))  # 받침이 ㅆ인 글자(했·었·았·였…)
_EXPERIENCE = re.compile(rf"경험|겪|그때|당시|사례를 들어|프로젝트를 소개|맡았|[{_SS}](?:던|는지)")
# 마지막 문장이 과거형 질문으로 끝나면(해결했나요·하셨나요·했습니까) '~했을 때 어떻게'가 있어도 과거 경험이다
_PAST_SS = _SS.replace("겠", "").replace("있", "")  # 받침 ㅆ이어도 과거가 아닌 '겠'(추측)·'있'(존재)은 뺀다
_PAST_ENDING = re.compile(rf"[{_PAST_SS}](?:나요|습니까|어요|니)\s*[?？]?\s*$")
_HYPOTHETICAL = re.compile(r"겠습니까|겠나요|겠어요|[다라]면 어떻게|때 .*어떻게")
_SELF = re.compile(r"자기소개(?!서)|지원(?:한)? ?(?:동기|이유)|입사 후|장점|단점|포부|목표|년 [뒤후]|1순위|"
                   r"하고 싶은 말|어떤 사람|좌우명|가치관|성격")
_BANK_FALLBACK = {"인성": "self", "기업": "self", "상황": "hypothetical", "직무": "knowledge", "인적성": "aptitude"}


def question_type(category: str | None, text: str | None, source: str | None = "bank") -> str:
    """질문 분류(Question.category)와 문구로 질문 유형을 정한다."""
    t = (text or "").strip()
    if category == "인적성" or re.match(r"\[(?:언어|수리|추리)\]", t):
        return "aptitude"
    if _EXPERIENCE.search(t) or _PAST_ENDING.search(t):
        return "experience"
    if _HYPOTHETICAL.search(t):
        return "hypothetical"
    if _SELF.search(t):
        return "self"
    return _BANK_FALLBACK.get(category or "", "general") if source == "bank" else "general"


# ───────── 피드백이 지금 전사문을 채점한 것인지 ─────────

def transcript_sha(text: str | None) -> str:
    """피드백에 남기는 '채점한 전사문'의 지문."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def feedback_current(fb, transcript: str | None) -> bool:
    """낡지 않았고 지금 전사문을 채점한 피드백인가. 지문이 없는 예전 피드백은 stale 표시만 본다."""
    if not isinstance(fb, dict) or fb.get("stale"):
        return False
    sha = fb.get("transcript_sha")
    return sha is None or sha == transcript_sha(transcript)
