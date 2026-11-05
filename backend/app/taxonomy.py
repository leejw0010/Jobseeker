"""Versioned question intent and frozen evidence; these are never skill scores."""
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone

from .config import settings

TAXONOMY_VERSION = "interview-v1"
QUESTION_TYPES = [
    {"key": "self_description", "label": "자기소개·자기이해",
     "definition": "자신의 특성, 가치관, 강점과 한계를 설명하는 질문"},
    {"key": "motivation", "label": "지원 동기·목표",
     "definition": "회사와 직무를 선택한 이유와 앞으로의 목표를 설명하는 질문"},
    {"key": "behavioral", "label": "경험·행동",
     "definition": "과거의 구체적인 상황에서 취한 행동과 결과를 설명하는 질문"},
    {"key": "situational", "label": "가상 상황·판단",
     "definition": "가정된 상황에서의 판단 기준과 대응 행동을 설명하는 질문"},
    {"key": "project_deep_dive", "label": "프로젝트 심층",
     "definition": "특정 프로젝트의 역할, 선택 근거와 결과를 깊이 확인하는 질문"},
    {"key": "knowledge", "label": "지식·원리·추론",
     "definition": "직무 지식, 원리 또는 추론 과정을 설명하는 질문"},
]
COMPETENCIES = [
    {"key": "problem_solving", "label": "문제 해결",
     "definition": "문제를 정의하고 대안을 선택해 해결하는 과정"},
    {"key": "communication", "label": "의사소통",
     "definition": "생각과 정보를 분명히 전달하고 상대의 관점을 확인하는 행동"},
    {"key": "collaboration", "label": "협업",
     "definition": "공동 목표를 위해 역할과 의견을 조율하는 행동"},
    {"key": "leadership", "label": "리더십",
     "definition": "방향을 제시하고 책임을 나누며 구성원의 실행을 돕는 행동"},
    {"key": "technical_expertise", "label": "직무 전문성",
     "definition": "직무의 지식과 도구를 이해하고 적용하는 과정"},
    {"key": "adaptability", "label": "적응·학습",
     "definition": "변화와 피드백을 받아들이고 학습을 행동에 반영하는 과정"},
    {"key": "analytical_thinking", "label": "분석적 사고",
     "definition": "근거를 나누어 살피고 가설과 결과를 검증하는 과정"},
]
TYPE_BY_KEY = {item["key"]: item for item in QUESTION_TYPES}
COMPETENCY_BY_KEY = {item["key"]: item for item in COMPETENCIES}
TAGGING_SOURCES = {"curated", "manual", "ai", "rule"}
MAX_COMPETENCIES = 3


def validate_keys(question_types=(), competency_keys=()) -> None:
    if (any(key not in TYPE_BY_KEY for key in question_types)
            or any(key not in COMPETENCY_BY_KEY for key in competency_keys)):
        raise ValueError("알 수 없는 질문 유형 또는 역량입니다")
    if len(set(question_types)) != len(question_types) or len(set(competency_keys)) != len(competency_keys):
        raise ValueError("중복된 분류 키입니다")


def classification_hash(value) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def capture(question, role: str = "primary") -> dict | None:
    if not settings.practice_insights_enabled or not question.taxonomy_version:
        return None
    question_type = TYPE_BY_KEY.get(question.question_type, {"key": None, "label": None, "definition": None})
    return {
        "schema_version": 1, "taxonomy_version": question.taxonomy_version,
        "question_type": question_type["key"], "question_type_label": question_type["label"],
        "question_type_definition": question_type["definition"],
        "competencies": [deepcopy(COMPETENCY_BY_KEY[key]) for key in question.competency_keys],
        "competency_keys": list(question.competency_keys), "tagging_source": question.tagging_source,
        "question_role": role, "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def recapture(snapshot: dict | None, role: str = "primary") -> dict | None:
    if snapshot is None:
        return None
    return {**deepcopy(snapshot), "question_role": role, "captured_at": datetime.now(timezone.utc).isoformat()}


def assign(question, question_type: str | None, competency_keys: list[str], source: str = "manual") -> None:
    """Replace the bundle atomically; flush removals before reusing unique positions."""
    if not settings.practice_insights_enabled:
        return
    from .models import QuestionCompetency

    validate_keys([question_type] if question_type else [], competency_keys)
    if len(competency_keys) > MAX_COMPETENCIES or source not in TAGGING_SOURCES:
        raise ValueError("역량은 최대 3개이며 분류 출처는 서버에서 지정합니다")
    question.question_type = question_type
    question.taxonomy_version = TAXONOMY_VERSION
    question.tagging_source = source
    from sqlalchemy.orm import object_session
    question.competency_tags.clear()
    session = object_session(question)
    if session is not None:
        session.flush()
    question.competency_tags = [
        QuestionCompetency(competency_key=key, position=index)
        for index, key in enumerate(competency_keys)
    ]


def filter_questions(stmt, question_types: list[str], competency_keys: list[str], match: str = "any"):
    validate_keys(question_types, competency_keys)
    if not settings.practice_insights_enabled:
        return stmt.where(False) if question_types or competency_keys else stmt
    from .models import Question, QuestionCompetency

    if question_types:
        stmt = stmt.where(Question.question_type.in_(question_types))
    if competency_keys:
        if match == "all":
            for key in competency_keys:
                stmt = stmt.where(Question.competency_tags.any(QuestionCompetency.competency_key == key))
        else:
            stmt = stmt.where(Question.competency_tags.any(QuestionCompetency.competency_key.in_(competency_keys)))
    return stmt


def current_evidence(raw, transcript: str | None, snapshot: dict | None) -> dict | None:
    """Read-time validation isolates malformed/stale extensions from core coaching."""
    from pydantic import ValidationError
    from .models import transcript_hash
    from .schemas import CompetencyEvidence

    try:
        evidence = CompetencyEvidence.model_validate(raw)
        if snapshot is None or evidence.transcript_sha256 != transcript_hash(transcript):
            return None
        if evidence.question_classification_sha256 != classification_hash(snapshot):
            return None
        if evidence.taxonomy_version != snapshot.get("taxonomy_version"):
            return None
        allowed = set(COMPETENCY_BY_KEY)
        keys = [observation.competency_key for observation in evidence.observations]
        if len(keys) != len(set(keys)) or not set(keys) <= allowed:
            return None
        if bool(evidence.observations) != (evidence.status == "analyzed"):
            return None
        if any(len(item.quote.strip()) < 4 or item.quote not in (transcript or "") for item in evidence.observations):
            return None
        return evidence.model_dump()
    except (ValidationError, TypeError, ValueError, KeyError):
        return None
