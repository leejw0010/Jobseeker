from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Stage = Literal["서류", "인적성", "1차면접", "2차면접", "최종"]
Status = Literal["진행중", "합격", "불합격", "보류"]
Category = Literal["인성", "직무", "기업", "상황", "인적성"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ───────────── ② Practice ─────────────

class QuestionIn(BaseModel):
    category: Category
    job_category: str | None = None
    text: str = Field(min_length=2)


class QuestionOut(ORM):
    id: str
    category: str
    job_category: str | None
    text: str
    source: str
    application_id: str | None


class GenerateIn(BaseModel):
    application_id: str | None = None
    company: str | None = None
    position: str | None = None
    job_category: str | None = None
    essay_text: str | None = Field(default=None, description="비우면 선택한 지원 건의 제출본 우선 사용")
    essay_basis: Literal["submitted", "latest"] = "submitted"
    count: int = Field(default=5, ge=1, le=10)


class SessionIn(BaseModel):
    mode: Literal["free", "mock"]
    title: str | None = None
    application_id: str | None = None
    question_ids: list[str] | None = Field(default=None, description="비우면 조건에 맞게 무작위 추출")
    count: int = Field(default=5, ge=1, le=20)
    categories: list[Category] | None = None
    job_category: str | None = None
    prep_sec: int = Field(default=30, ge=0, le=300)
    answer_sec: int = Field(default=90, ge=10, le=600)
    essay_basis: Literal["submitted", "latest"] = "submitted"
    job_description: str = Field(default="", max_length=12000)
    followups_enabled: bool = False


Focus = Literal["specificity", "relevance", "consistency"]


class CoachingCriterion(BaseModel):
    key: Focus
    label: str = Field(max_length=50)
    status: Literal["충분", "보완", "판단유보"]
    reason: str = Field(min_length=1, max_length=1000)
    answer_quote: str = Field(default="", max_length=1000)
    source_quote: str = Field(default="", max_length=1000)
    source_version_id: str | None = None


class FollowupSuggestion(BaseModel):
    text: str = Field(min_length=5, max_length=1000)
    focus: Focus
    reason: str = Field(min_length=1, max_length=1000)
    answer_quote: str = Field(min_length=1, max_length=1000)
    source_quote: str = Field(default="", max_length=1000)
    source_version_id: str | None = None


class CoachingReport(BaseModel):
    method: Literal["basic", "ai"] = "basic"
    rubric_version: str = "2026-10-15"
    summary: str = Field(min_length=1, max_length=1000)
    next_action: str = Field(min_length=1, max_length=1000)
    criteria: list[CoachingCriterion] = Field(min_length=3, max_length=3)
    followup: FollowupSuggestion


class AnswerOut(ORM):
    id: str
    order_no: int
    question: QuestionOut
    audio_path: str | None
    duration_sec: float | None
    transcript: str | None
    stt_status: str
    self_rating: int | None
    reflection_note: str | None
    ai_feedback: str | None
    coaching_report: CoachingReport | None = None
    parent_answer_id: str | None = None
    followup_reason: str | None = None


class SessionOut(ORM):
    id: str
    mode: str
    title: str
    application_id: str | None
    prep_sec: int
    answer_sec: int
    created_at: datetime
    finished_at: datetime | None
    answers: list[AnswerOut]
    context_snapshot: dict | None = None
    followups_enabled: bool = False


class SessionSummary(ORM):
    id: str
    mode: str
    title: str
    created_at: datetime
    finished_at: datetime | None
    answer_count: int
    recorded_count: int
    avg_rating: float | None


class ReflectionIn(BaseModel):
    self_rating: int | None = Field(default=None, ge=1, le=5)
    reflection_note: str | None = None
    transcript: str | None = Field(default=None, description="전사문 수동 수정")


# ───────────── ③ Track ─────────────

class StageEventIn(BaseModel):
    stage: Stage
    result: Literal["대기", "합격", "불합격"]
    event_date: date | None = None
    memo: str | None = None


class StageEventOut(ORM):
    id: str
    stage: str
    result: str
    event_date: date
    memo: str | None


class VersionIn(BaseModel):
    content: str
    source: Literal["web", "extension"] = "web"
    is_submitted: bool = False


class VersionOut(ORM):
    id: str
    version_no: int
    content: str
    char_count: int
    source: str
    is_submitted: bool
    created_at: datetime


class EssayItemIn(BaseModel):
    question_text: str
    char_limit: int | None = None
    content: str | None = Field(default=None, description="있으면 첫 버전으로 저장")


class EssayItemOut(ORM):
    id: str
    question_text: str
    char_limit: int | None
    versions: list[VersionOut]


class ApplicationIn(BaseModel):
    company: str
    position: str
    job_category: str = "기타"
    url: str | None = None
    applied_at: date | None = None
    stage: Stage = "서류"
    status: Status = "진행중"
    notes: str | None = None


class ApplicationPatch(BaseModel):
    company: str | None = None
    position: str | None = None
    job_category: str | None = None
    url: str | None = None
    applied_at: date | None = None
    stage: Stage | None = None
    status: Status | None = None
    notes: str | None = None


class ApplicationOut(ORM):
    id: str
    company: str
    position: str
    job_category: str
    url: str | None
    applied_at: date | None
    stage: str
    status: str
    notes: str | None
    source: str
    created_at: datetime
    updated_at: datetime


class ApplicationDetail(ApplicationOut):
    events: list[StageEventOut]
    essay_items: list[EssayItemOut]


class SyncEssay(BaseModel):
    question_text: str
    content: str
    char_limit: int | None = None


class SyncIn(BaseModel):
    """크롬 확장(①)이 지원서를 제출할 때 보내는 데이터."""

    company: str
    position: str
    job_category: str = "기타"
    url: str
    applied_at: date | None = None
    essays: list[SyncEssay] = []
    submitted: bool = True


class SyncOut(BaseModel):
    application_id: str
    created: bool
    new_versions: int
