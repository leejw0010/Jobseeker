import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

STAGES = ["서류", "인적성", "1차면접", "2차면접", "최종"]
STATUSES = ["진행중", "합격", "불합격", "보류"]
QUESTION_CATEGORIES = ["인성", "직무", "기업", "상황", "인적성"]


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ───────────── ② Practice ─────────────

class Question(Base):
    __tablename__ = "questions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    category: Mapped[str] = mapped_column(String(10))
    job_category: Mapped[str | None] = mapped_column(String(30))
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10), default="bank")
    application_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    private_scope: Mapped["PracticePrivateQuestion | None"] = relationship(cascade="all, delete-orphan")


class PracticePrivateQuestion(Base):
    """An answer-dependent question never becomes reusable after its session is deleted."""
    __tablename__ = "practice_private_questions"
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True)


class PracticeSession(Base):
    __tablename__ = "practice_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    mode: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))
    application_id: Mapped[str | None] = mapped_column(String(36))
    prep_sec: Mapped[int] = mapped_column(Integer, default=30)
    answer_sec: Mapped[int] = mapped_column(Integer, default=90)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("practice_sessions.id", ondelete="CASCADE"))
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    order_no: Mapped[int] = mapped_column(Integer)
    audio_path: Mapped[str | None] = mapped_column(Text)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    transcript: Mapped[str | None] = mapped_column(Text)
    stt_status: Mapped[str] = mapped_column(String(12), default="none")
    self_rating: Mapped[int | None] = mapped_column(Integer)
    reflection_note: Mapped[str | None] = mapped_column(Text)
    ai_feedback: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    session: Mapped[PracticeSession] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()
    coaching: Mapped["AnswerCoaching | None"] = relationship(
        foreign_keys="AnswerCoaching.answer_id", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def coaching_report(self) -> dict | None:
        return self.coaching.report if self.coaching else None

    @property
    def parent_answer_id(self) -> str | None:
        return self.coaching.parent_answer_id if self.coaching else None

    @property
    def followup_reason(self) -> str | None:
        return self.coaching.followup_reason if self.coaching else None


class PracticeContext(Base):
    """Separate tables also upgrade existing SQLite databases without ALTERs."""
    __tablename__ = "practice_contexts"
    session_id: Mapped[str] = mapped_column(ForeignKey("practice_sessions.id", ondelete="CASCADE"), primary_key=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    followups_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class AnswerCoaching(Base):
    __tablename__ = "answer_coaching"
    answer_id: Mapped[str] = mapped_column(ForeignKey("practice_answers.id", ondelete="CASCADE"), primary_key=True)
    parent_answer_id: Mapped[str | None] = mapped_column(
        ForeignKey("practice_answers.id", ondelete="SET NULL"), unique=True
    )
    followup_reason: Mapped[str | None] = mapped_column(Text)
    report: Mapped[dict | None] = mapped_column(JSON)


# ───────────── ③ Track ─────────────

class Application(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
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


class StageEvent(Base):
    __tablename__ = "stage_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(10))
    result: Mapped[str] = mapped_column(String(10))
    event_date: Mapped[date] = mapped_column(Date, default=date.today)
    memo: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EssayItem(Base):
    __tablename__ = "essay_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    question_text: Mapped[str] = mapped_column(Text)
    char_limit: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    application: Mapped[Application] = relationship(back_populates="essay_items")
    versions: Mapped[list["AnswerVersion"]] = relationship(
        cascade="all, delete-orphan", order_by="AnswerVersion.version_no"
    )


class AnswerVersion(Base):
    __tablename__ = "answer_versions"
    __table_args__ = (UniqueConstraint("essay_item_id", "version_no"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    essay_item_id: Mapped[str] = mapped_column(ForeignKey("essay_items.id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(10), default="web")
    is_submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
