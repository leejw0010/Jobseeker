from datetime import date, datetime, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, computed_field, model_validator

Stage = Literal["서류", "인적성", "1차면접", "2차면접", "최종"]
Status = Literal["진행중", "합격", "불합격", "보류"]
Category = Literal["인성", "직무", "기업", "상황", "인적성"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _as_utc(v: datetime) -> datetime:
    # SQLite는 시간대 없는 값을 돌려준다. 저장은 항상 UTC라 UTC로 붙여 내보낸다
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v


UTCDatetime = Annotated[datetime, AfterValidator(_as_utc)]


def _blank_as_none(v):
    # 빈 공고 URL은 '없음'이다(고유 제약 applications_user_url_uq는 URL이 있는 건만 센다)
    return None if isinstance(v, str) and not v.strip() else v


OptionalURL = Annotated[str | None, BeforeValidator(_blank_as_none)]


# ───────────── ② Practice ─────────────

class ClassificationIn(BaseModel):
    question_type: str | None = None
    competency_keys: list[str] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def classification_valid(self):
        from .taxonomy import validate_keys
        validate_keys([self.question_type] if self.question_type else [], self.competency_keys)
        return self


class QuestionIn(ClassificationIn):
    category: Category
    job_category: str | None = None
    text: str = Field(min_length=2)


class QuestionOut(ORM):
    question_type: str | None = None
    competency_keys: list[str] = Field(default_factory=list)
    taxonomy_version: str | None = None
    tagging_source: str | None = None
    id: str
    category: str
    job_category: str | None
    text: str
    source: str
    application_id: str | None


class GenerateIn(ClassificationIn):
    application_id: str | None = None
    company: str | None = None
    position: str | None = None
    job_category: str | None = None
    essay_text: str | None = Field(default=None, description="비우면 선택한 지원 건의 제출본 우선 사용")
    essay_basis: Literal["submitted", "latest"] = "submitted"
    count: int = Field(default=5, ge=1, le=10)


class SessionIn(BaseModel):
    question_types: list[str] = Field(default_factory=list)
    competency_keys: list[str] = Field(default_factory=list)
    competency_match: Literal["any", "all"] = "any"

    @model_validator(mode="after")
    def filters_valid(self):
        from .taxonomy import validate_keys
        validate_keys(self.question_types,self.competency_keys)
        return self

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


class CompetencyObservation(BaseModel):
    competency_key: str
    basis: Literal["past_action","proposed_action","explanation"]
    quote: str = Field(min_length=4,max_length=500)
    reason: str = Field(min_length=1,max_length=1000)


class CompetencyEvidence(BaseModel):
    status: Literal["analyzed","unavailable"]
    method: Literal["ai"] = "ai"
    taxonomy_version: str
    assessment_version: str
    generated_at: str
    model: str
    transcript_sha256: str
    question_classification_sha256: str
    observations: list[CompetencyObservation] = Field(default_factory=list,max_length=3)


class CoachingReport(BaseModel):
    input_sha256: str | None = None
    input_status: Literal["current", "legacy_unverified"] = "legacy_unverified"
    competency_evidence: CompetencyEvidence | None = None
    transcript_sha256: str | None = None
    question_classification_sha256: str | None = None
    method: Literal["basic", "ai"] = "basic"
    # 새 보고서는 coaching.RUBRIC_VERSION을 찍는다. 버전이 없는 보고서는 첫 기준(2026-10-15)으로 본다
    rubric_version: str = "2026-10-15"
    summary: str = Field(min_length=1, max_length=1000)
    next_action: str = Field(min_length=1, max_length=1000)
    criteria: list[CoachingCriterion] = Field(min_length=3, max_length=3)
    followup: FollowupSuggestion


class AnswerOut(ORM):
    recording_transcript_current: bool = False
    question_classification: dict | None = None
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
    # 녹음한 시각("녹음으로 답했다"의 기준). 원본은 전사가 끝나면 지워질 수 있다
    recorded_at: UTCDatetime | None = None
    audio_expires_at: UTCDatetime | None = None
    audio_deleted_at: UTCDatetime | None = None

    @computed_field
    @property
    def audio_available(self) -> bool:
        return self.audio_path is not None


class WeakAnswerOut(BaseModel):
    """다시 연습할 답변과 그 이유(보완 항목, 자기평가 1~2점)."""

    answer_id: str
    question_id: str
    order_no: int
    question_text: str
    reasons: list[str]


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
    debrief: dict | None = None
    debrief_status: str = "none"
    redrill: list[WeakAnswerOut] = Field(default=[], description="다시 연습할 답변(응답마다 다시 계산)")
    debrief_running: bool = Field(default=False, description="디브리프 작업이 도는 중(다시 요청해도 새로 시작하지 않음)")


class SessionSummary(ORM):
    competency_keys: list[str] = Field(default_factory=list)
    classification_missing_count: int = 0
    id: str
    mode: str
    title: str
    created_at: datetime
    finished_at: datetime | None
    answer_count: int
    recorded_count: int
    avg_rating: float | None


class ReflectionIn(BaseModel):
    input_mode: Literal["text", "transcript"] | None = None
    self_rating: int | None = Field(default=None, ge=1, le=5)
    reflection_note: str | None = None
    transcript: str | None = Field(default=None, description="전사문 수동 수정")


class PracticeSettingsIn(BaseModel):
    consent: bool | None = Field(default=None, description="true=녹음 동의, false=동의 철회(원본 녹음 삭제)")
    keep_audio: bool | None = Field(default=None, description="원본 녹음 보관(새 녹음과 다시 전사하는 녹음에 적용)")


class PracticeSettingsOut(BaseModel):
    consented_at: UTCDatetime | None
    keep_audio: bool
    retention_days: int


class DeletedOut(BaseModel):
    """원본 녹음 삭제 결과. failed는 저장소 오류로 못 지운 개수(다음 만료 정리 때 다시 지운다).

    unchecked는 저장소 폴더 목록을 읽지 못해 행이 없는 파일이 남았는지 모른다는 뜻(다음 만료 정리 때 다시 훑어 지운다).
    """

    deleted: int
    failed: int = 0
    unchecked: bool = False


class PracticeSettingsUpdateOut(PracticeSettingsOut):
    """설정 변경 결과. 동의를 철회했으면 지운·못 지운 원본 녹음 수를 함께 돌려준다."""

    deleted: int = 0
    failed: int = 0
    unchecked: bool = False


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


class StageEventPatch(BaseModel):
    stage: Stage | None = None
    result: Literal["대기", "합격", "불합격"] | None = None
    event_date: date | None = None
    memo: str | None = None

    @model_validator(mode="after")
    def required_fields(self):
        if any(k in self.model_fields_set and getattr(self, k) is None for k in ("stage", "result", "event_date")):
            raise ValueError("단계·결과·날짜는 비울 수 없습니다")
        return self


class EventStateIn(BaseModel):
    baseline_stage: Stage | None = None
    baseline_status: Status | None = None


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
    submitted_version_id: str | None = None
    submission_confirmation: Literal["confirmed", "legacy_unverified", "none"] = "none"
    submission_revision: int = 0


class ApplicationIn(BaseModel):
    company: str
    position: str
    job_category: str = "기타"
    url: OptionalURL = None
    applied_at: date | None = None
    stage: Stage = "서류"
    status: Status = "진행중"
    notes: str | None = None


class ApplicationPatch(BaseModel):
    """보낸 필드만 바꾼다. 필수 필드(회사·직무·분류·단계·상태)는 null로 비울 수 없고, 나머지는 null이면 비운다."""

    company: str | None = None
    position: str | None = None
    job_category: str | None = None
    url: OptionalURL = None
    applied_at: date | None = None
    stage: Stage | None = None
    status: Status | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _required_not_null(self):
        nulls = [k for k in ("company", "position", "job_category", "stage", "status")
                 if k in self.model_fields_set and getattr(self, k) is None]
        if nulls:
            raise ValueError(f"비울 수 없는 항목이에요: {', '.join(nulls)}")
        return self


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
    state_source: Literal["events", "manual", "legacy"] = "legacy"
    state_revision: int = 0
    state_requires_baseline: bool = True


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
