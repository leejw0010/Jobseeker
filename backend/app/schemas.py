from datetime import date, datetime, timezone
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)

from .rubric import feedback_current

Stage = Literal["서류", "인적성", "1차면접", "2차면접", "최종"]
Status = Literal["진행중", "합격", "불합격", "보류"]
Category = Literal["인성", "직무", "기업", "상황", "인적성"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _as_utc(v: datetime) -> datetime:
    # SQLite는 시간대 없는 값을 돌려준다. 저장은 항상 UTC라 UTC로 붙여 내보낸다
    return v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v


UTCDatetime = Annotated[datetime, AfterValidator(_as_utc)]


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
    essay_text: str | None = Field(default=None, description="자소서 내용. 비우면 지원 건의 최신 버전을 사용")
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
    ai_feedback: str | None  # 예전 자유 서술 피드백(새 채점은 feedback)
    feedback: dict | None  # 루브릭 피드백
    recorded_at: UTCDatetime | None
    audio_expires_at: UTCDatetime | None
    audio_deleted_at: UTCDatetime | None

    @computed_field
    @property
    def audio_available(self) -> bool:
        return self.audio_path is not None

    @model_validator(mode="after")
    def _mark_stale(self):
        # 지금 전사문을 채점한 피드백이 아니면(채점 중에 고친 경우 등) 낡은 것으로 내보낸다
        if isinstance(self.feedback, dict) and not self.feedback.get("stale") \
                and not feedback_current(self.feedback, self.transcript):
            self.feedback = {**self.feedback, "stale": True}
        return self


class WeakAnswerOut(BaseModel):
    """다시 연습할 약점 질문과 그 이유."""

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
    debrief: dict | None
    debrief_status: str
    redrill_of: str | None
    answers: list[AnswerOut]
    redrill: list[WeakAnswerOut] = Field(default=[], description="약점 재연습 후보(응답마다 다시 계산)")


class SessionSummary(ORM):
    id: str
    mode: str
    title: str
    created_at: datetime
    finished_at: datetime | None
    answer_count: int
    recorded_count: int
    avg_rating: float | None
    redrill_of: str | None


class ReflectionIn(BaseModel):
    self_rating: int | None = Field(default=None, ge=1, le=5)
    reflection_note: str | None = None
    transcript: str | None = Field(default=None, description="전사문 수동 수정")


class RedrillIn(BaseModel):
    answer_ids: list[str] | None = Field(default=None, description="비우면 약점 목록 전체")


class PracticeSettingsIn(BaseModel):
    consent: bool | None = Field(default=None, description="true=녹음 동의, false=동의 철회(원본 녹음 삭제)")
    keep_audio: bool | None = Field(default=None, description="원본 녹음 보관(새 녹음부터 적용)")


class PracticeSettingsOut(BaseModel):
    consented_at: UTCDatetime | None
    keep_audio: bool
    retention_days: int


class DeletedOut(BaseModel):
    """원본 녹음 삭제 결과. failed는 저장소 오류로 못 지운 개수(다음 만료 정리 때 다시 지운다)."""

    deleted: int
    failed: int = 0


class PracticeSettingsUpdateOut(PracticeSettingsOut):
    """설정 변경 결과. 동의를 철회했으면 지운·못 지운 원본 녹음 수를 함께 돌려준다."""

    deleted: int = 0
    failed: int = 0


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
