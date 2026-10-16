import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

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
    # 디브리프 작업을 시작한 시각. 'pending'이 오래 이어지면(서버 재시작 등) 작업이 사라진 것으로 보고 다시 시작한다
    debrief_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 약점 재연습 세션이면 원래 세션 id
    redrill_of: Mapped[str | None] = mapped_column(ID)
    answers: Mapped[list["PracticeAnswer"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="PracticeAnswer.order_no"
    )


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
    ai_feedback: Mapped[str | None] = mapped_column(Text)  # 예전 자유 서술 피드백(새 채점은 feedback에 저장)
    feedback: Mapped[dict | None] = mapped_column(JSONType)  # 루브릭 피드백(rubric.py)
    # 녹음한 시각. "이 질문에 답했다"는 audio_path가 아니라 이 값으로 판단한다(원본은 지워질 수 있음)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audio_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audio_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    session: Mapped[PracticeSession] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()


class UserSettings(Base):
    """사용자별 녹음 동의·원본 보관 설정. 행이 없으면 미동의·보관 안 함."""

    __tablename__ = "user_settings"
    user_id: Mapped[str] = mapped_column(ID, primary_key=True)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    keep_audio: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


# ───────────── ③ Track ─────────────

class Application(Base):
    __tablename__ = "applications"
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
        cascade="all, delete-orphan", order_by="AnswerVersion.version_no"
    )


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
