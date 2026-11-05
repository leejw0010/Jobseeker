import hashlib
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .config import settings

STAGES = ["서류", "인적성", "1차면접", "2차면접", "최종"]
STATUSES = ["진행중", "합격", "불합격", "보류"]
QUESTION_CATEGORIES = ["인성", "직무", "기업", "상황", "인적성"]
DEBRIEF_STATUSES = ["none", "pending", "done", "failed", "unavailable"]

# SQLite에서는 JSON, Supabase(Postgres)에서는 jsonb
JSONType = JSON().with_variant(JSONB(), "postgresql")
# id 컬럼: SQLite에서는 문자열, Supabase(Postgres)에서는 uuid로 바인딩해야 uuid = varchar 비교 오류가 나지 않는다
ID = String(36).with_variant(UUID(as_uuid=False), "postgresql")


def _uuid() -> str:
    return str(uuid.uuid4())


def valid_id(value) -> bool:
    """uuid로 읽을 수 있는 id인가. 아니면 DB에 보내지 않고 '찾을 수 없음'으로 답한다(Postgres는 uuid 컬럼에 넣으면 오류)."""
    try:
        uuid.UUID(value)
    except (TypeError, ValueError, AttributeError):
        return False
    return True


def transcript_hash(text: str | None) -> str:
    """코칭 보고서가 채점한 전사문의 지문(보고서에 함께 저장한다)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def recording_transcript_hash(recorded_at: datetime, transcript: str | None) -> str:
    """Bind text to its recording revision, including across schema-off rollbacks."""
    stamp = recorded_at.replace(tzinfo=timezone.utc) if recorded_at.tzinfo is None else recorded_at.astimezone(timezone.utc)
    return transcript_hash(stamp.isoformat() + "\0" + (transcript or ""))


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ───────────── ② Practice ─────────────

class Question(Base):
    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(ID, index=True)
    category: Mapped[str] = mapped_column(String(10))
    job_category: Mapped[str | None] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10), default="bank")
    application_id: Mapped[str | None] = mapped_column(ID)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    if settings.practice_insights_enabled:
        question_type: Mapped[str | None] = mapped_column(String(30))
        taxonomy_version: Mapped[str | None] = mapped_column(String(30))
        tagging_source: Mapped[str | None] = mapped_column(String(10))
        competency_tags: Mapped[list["QuestionCompetency"]] = relationship(cascade="all, delete-orphan", lazy="selectin", order_by="QuestionCompetency.position")
    else:
        question_type = None
        taxonomy_version = None
        tagging_source = None

    @property
    def competency_keys(self) -> list[str]:
        return [t.competency_key for t in self.competency_tags] if settings.practice_insights_enabled else []

    private_scope: Mapped["PracticePrivateQuestion | None"] = relationship(cascade="all, delete-orphan")


if settings.practice_insights_enabled:
    class QuestionCompetency(Base):
        __tablename__ = "question_competencies"
        __table_args__ = (Index("question_competencies_position_uq", "question_id", "position", unique=True),)
        question_id: Mapped[str] = mapped_column(ID, ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True)
        competency_key: Mapped[str] = mapped_column(String(40), primary_key=True)
        position: Mapped[int] = mapped_column(Integer)


class PracticePrivateQuestion(Base):
    """An answer-dependent question never becomes reusable after its session is deleted."""
    __tablename__ = "practice_private_questions"
    question_id: Mapped[str] = mapped_column(ID, ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True)


class PracticeSession(Base):
    __tablename__ = "practice_sessions"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ID, index=True)
    mode: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))
    application_id: Mapped[str | None] = mapped_column(ID)
    prep_sec: Mapped[int] = mapped_column(Integer, default=30)
    answer_sec: Mapped[int] = mapped_column(Integer, default=90)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 세션 종료 후 자동 디브리프(핵심 교훈·다음 행동·주목할 순간)
    debrief: Mapped[dict | None] = mapped_column(JSONType)
    debrief_status: Mapped[str] = mapped_column(String(12), default="none", server_default="none")
    # 디브리프 작업(답변 코칭 + 요약)을 시작한 시각. 작업이 끝나면 비운다. 작업마다 달라 그 작업의 표시로도 쓴다
    debrief_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 작업이 마지막으로 살아 있다고 알린 시각(답변 하나를 점검할 때마다, 요약 전에).
    # 이 시각이 오래되면(서버 재시작 등) 작업이 사라진 것으로 보고 다시 시작한다
    debrief_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 작업이 도는 동안 들어온 종료·재생성 요청 시각. 작업은 결과를 쓰기 전에 보고 한 바퀴 더 돈다
    debrief_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answers: Mapped[list["PracticeAnswer"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="PracticeAnswer.order_no"
    )
    context: Mapped["PracticeContext | None"] = relationship(cascade="all, delete-orphan", lazy="selectin")

    @property
    def context_snapshot(self) -> dict | None:
        return self.context.snapshot if self.context else None

    @property
    def followups_enabled(self) -> bool:
        return bool(self.context and self.context.followups_enabled)


class PracticeAnswer(Base):
    __tablename__ = "practice_answers"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ID, ForeignKey("practice_sessions.id", ondelete="CASCADE"))
    question_id: Mapped[str] = mapped_column(ID, ForeignKey("questions.id", ondelete="CASCADE"))
    order_no: Mapped[int] = mapped_column(Integer)
    audio_path: Mapped[str | None] = mapped_column(Text)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    transcript: Mapped[str | None] = mapped_column(Text)
    stt_status: Mapped[str] = mapped_column(String(12), default="none")
    self_rating: Mapped[int | None] = mapped_column(Integer)
    reflection_note: Mapped[str | None] = mapped_column(Text)
    ai_feedback: Mapped[str | None] = mapped_column(Text)
    # 녹음한 시각. "이 질문에 녹음으로 답했다"는 audio_path가 아니라 이 값으로 판단한다(원본은 전사 후 지워질 수 있음)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audio_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audio_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    if settings.practice_insights_enabled:
        question_classification: Mapped[dict | None] = mapped_column(JSONType)
        # Original STT/first user-confirmed transcription; empty string marks explicit text mode.
        recording_transcript_sha256: Mapped[str | None] = mapped_column(String(64))
    else:
        question_classification = None
        recording_transcript_sha256 = None
    session: Mapped[PracticeSession] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()
    coaching: Mapped["AnswerCoaching | None"] = relationship(
        foreign_keys="AnswerCoaching.answer_id", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def recording_transcript_current(self) -> bool:
        return bool(self.recorded_at and self.recording_transcript_sha256 and (self.transcript or "").strip()
                    and self.recording_transcript_sha256 == recording_transcript_hash(self.recorded_at, self.transcript))

    @property
    def coaching_report(self) -> dict | None:
        """지금 전사문을 채점한 보고서. 다른 전사문을 채점한 보고서(점검과 수정이 겹친 경우)는 없는 것으로 본다.
        지문이 없는 보고서(main이 만든 것)는 지금 전사문의 것으로 본다."""
        report = self.coaching.report if self.coaching else None
        if report and report.get("transcript_sha256") not in (None, transcript_hash(self.transcript)):
            return None
        if report:
            fingerprint = report.get("input_sha256")
            if fingerprint:
                from .services.answer_coaching import input_fingerprint
                if fingerprint != input_fingerprint(self):
                    return None
            report = {**report, "input_status": "current" if fingerprint else "legacy_unverified"}
        if report and report.get("competency_evidence") is not None:
            from .taxonomy import current_evidence
            # Optional classification must not hide transcript-valid core coaching on rollback.
            evidence = current_evidence(report["competency_evidence"],self.transcript,self.question_classification) if settings.practice_insights_enabled else None
            return {**report,"competency_evidence":evidence}
        return report

    @property
    def parent_answer_id(self) -> str | None:
        return self.coaching.parent_answer_id if self.coaching else None

    @property
    def followup_reason(self) -> str | None:
        return self.coaching.followup_reason if self.coaching else None


class PracticeContext(Base):
    """Separate tables also upgrade existing SQLite databases without ALTERs."""
    __tablename__ = "practice_contexts"
    session_id: Mapped[str] = mapped_column(ID, ForeignKey("practice_sessions.id", ondelete="CASCADE"), primary_key=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    followups_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class AnswerCoaching(Base):
    __tablename__ = "answer_coaching"
    answer_id: Mapped[str] = mapped_column(ID, ForeignKey("practice_answers.id", ondelete="CASCADE"), primary_key=True)
    parent_answer_id: Mapped[str | None] = mapped_column(
        ID, ForeignKey("practice_answers.id", ondelete="SET NULL"), unique=True
    )
    followup_reason: Mapped[str | None] = mapped_column(Text)
    report: Mapped[dict | None] = mapped_column(JSON)


class UserSettings(Base):
    """사용자별 녹음 동의·원본 보관 설정. 행이 없으면 미동의·보관 안 함."""

    __tablename__ = "user_settings"
    user_id: Mapped[str] = mapped_column(ID, primary_key=True)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    keep_audio: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # 전체 삭제·동의 철회 때 답변이 가리키지 않는 저장소 파일을 못 지웠으면 그 요청 시각.
    # 다음 만료 정리가 이 시각 전에 저장된 그런 파일을 다시 지우고, 다 지우면 비운다
    sweep_audio_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 원본 녹음을 모두 지운(내 원본 녹음 모두 지우기·동의 철회) 마지막 시각. 그 전에 시작해 아직 저장·전사 중이던
    # 업로드·다시 전사는 커밋할 때 이 시각을 보고 녹음을 지운 것으로 저장한다(전사문은 남긴다)
    audio_cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


# ───────────── ③ Track ─────────────

class Application(Base):
    __tablename__ = "applications"
    # 사용자마다 공고 URL은 한 건(supabase/schema.sql의 applications_user_url_uq와 같다). URL이 없는 건은 제한 없음
    __table_args__ = (Index("applications_user_url_uq", "user_id", "url", unique=True,
                            sqlite_where=text("url IS NOT NULL"), postgresql_where=text("url IS NOT NULL")),)
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ID, index=True)
    company: Mapped[str] = mapped_column(String(100))
    position: Mapped[str] = mapped_column(String(100))
    job_category: Mapped[str] = mapped_column(String(30), default="기타")
    url: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[date | None] = mapped_column(Date)
    stage: Mapped[str] = mapped_column(String(10), default="서류")
    status: Mapped[str] = mapped_column(String(10), default="진행중")
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10), default="web")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    events: Mapped[list["StageEvent"]] = relationship(
        cascade="all, delete-orphan", order_by="StageEvent.created_at"
    )
    essay_items: Mapped[list["EssayItem"]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="EssayItem.created_at"
    )
    state_control: Mapped["ApplicationState | None"] = relationship(cascade="all, delete-orphan", lazy="selectin")

    @property
    def state_source(self) -> str:
        return (self.state_control.override_origin or "events") if self.state_control else "legacy"

    @property
    def state_revision(self) -> int:
        return self.state_control.revision if self.state_control else 0

    @property
    def state_requires_baseline(self) -> bool:
        return not self.state_control or self.state_control.baseline_stage is None


class ApplicationState(Base):
    """Explicit provenance; old rows without metadata retain their current state."""
    __tablename__ = "application_states"
    application_id: Mapped[str] = mapped_column(ID, ForeignKey("applications.id", ondelete="CASCADE"), primary_key=True)
    baseline_stage: Mapped[str | None] = mapped_column(String(10))
    baseline_status: Mapped[str | None] = mapped_column(String(10))
    override_stage: Mapped[str | None] = mapped_column(String(10))
    override_status: Mapped[str | None] = mapped_column(String(10))
    override_origin: Mapped[str | None] = mapped_column(String(10))
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class StageEvent(Base):
    __tablename__ = "stage_events"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(ID, ForeignKey("applications.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(10))
    result: Mapped[str] = mapped_column(String(10))
    event_date: Mapped[date] = mapped_column(Date, default=date.today)
    memo: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EssayItem(Base):
    __tablename__ = "essay_items"
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(ID, ForeignKey("applications.id", ondelete="CASCADE"))
    question_text: Mapped[str] = mapped_column(Text)
    char_limit: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    application: Mapped[Application] = relationship(back_populates="essay_items")
    versions: Mapped[list["AnswerVersion"]] = relationship(
        cascade="save-update, merge", passive_deletes="all", order_by="AnswerVersion.version_no"
    )
    submissions: Mapped[list["EssaySubmission"]] = relationship(cascade="save-update, merge", passive_deletes="all", order_by="EssaySubmission.sequence", lazy="selectin")

    @property
    def submission_revision(self) -> int:
        return self.submissions[-1].sequence if self.submissions else 0

    @property
    def submitted_version_id(self) -> str | None:
        if self.submissions:
            return self.submissions[-1].version_id
        return next((v.id for v in reversed(self.versions) if v.is_submitted), None)

    @property
    def submission_confirmation(self) -> str:
        return "confirmed" if self.submissions else "legacy_unverified" if self.submitted_version_id else "none"


class AnswerVersion(Base):
    __tablename__ = "answer_versions"
    __table_args__ = (UniqueConstraint("essay_item_id", "version_no"),)
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=_uuid)
    essay_item_id: Mapped[str] = mapped_column(ID, ForeignKey("essay_items.id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(10), default="web")
    is_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EssaySubmission(Base):
    __tablename__ = "essay_submissions"
    __table_args__ = (UniqueConstraint("essay_item_id", "sequence"),)
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=_uuid)
    essay_item_id: Mapped[str] = mapped_column(ID, ForeignKey("essay_items.id", ondelete="CASCADE"))
    version_id: Mapped[str] = mapped_column(ID, ForeignKey("answer_versions.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    source: Mapped[str] = mapped_column(String(10))
