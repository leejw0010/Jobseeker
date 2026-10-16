"""예전 스키마의 로컬 SQLite DB에 빠진 컬럼을 채우는 마이그레이션."""
from datetime import timedelta

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.db import upgrade_sqlite
from app.models import PracticeAnswer, PracticeSession

# P0 이전 모델이 만들던 테이블(코칭용 새 테이블은 create_all이 따로 만든다)
OLD_SCHEMA = [
    """CREATE TABLE questions (
        id VARCHAR(36) NOT NULL, user_id VARCHAR(36), category VARCHAR(10) NOT NULL, job_category VARCHAR(30),
        text TEXT NOT NULL, source VARCHAR(10) NOT NULL, application_id VARCHAR(36), created_at DATETIME NOT NULL,
        PRIMARY KEY (id))""",
    """CREATE TABLE practice_sessions (
        id VARCHAR(36) NOT NULL, user_id VARCHAR(36) NOT NULL, mode VARCHAR(10) NOT NULL, title VARCHAR(200) NOT NULL,
        application_id VARCHAR(36), prep_sec INTEGER NOT NULL, answer_sec INTEGER NOT NULL,
        created_at DATETIME NOT NULL, finished_at DATETIME, PRIMARY KEY (id))""",
    """CREATE TABLE practice_answers (
        id VARCHAR(36) NOT NULL, session_id VARCHAR(36) NOT NULL, question_id VARCHAR(36) NOT NULL,
        order_no INTEGER NOT NULL, audio_path TEXT, duration_sec FLOAT, transcript TEXT, stt_status VARCHAR(12) NOT NULL,
        self_rating INTEGER, reflection_note TEXT, ai_feedback TEXT, created_at DATETIME NOT NULL, PRIMARY KEY (id),
        FOREIGN KEY(session_id) REFERENCES practice_sessions (id) ON DELETE CASCADE,
        FOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE CASCADE)""",
    "INSERT INTO questions VALUES ('q1', NULL, '인성', NULL, '질문', 'bank', NULL, '2026-01-01 00:00:00.000000')",
    "INSERT INTO practice_sessions VALUES ('s1', 'u1', 'free', '예전 세션', NULL, 30, 90,"
    " '2026-01-01 00:00:00.000000', NULL)",
    "INSERT INTO practice_answers VALUES ('a1', 's1', 'q1', 1, 'u1/s1/a1.webm', 10, '전사문', 'done', 4, NULL,"
    " '잘한 점: 결론부터', '2026-01-02 03:04:05.000000')",
    "INSERT INTO practice_answers VALUES ('a2', 's1', 'q1', 2, NULL, NULL, NULL, 'none', NULL, NULL, NULL,"
    " '2026-01-02 03:04:05.000000')",
]


def test_upgrade_old_sqlite_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        for stmt in OLD_SCHEMA:
            conn.execute(text(stmt))

    added = upgrade_sqlite(engine)
    assert set(added) == {"practice_answers.recorded_at", "practice_answers.audio_expires_at",
                          "practice_answers.audio_deleted_at", "practice_sessions.debrief",
                          "practice_sessions.debrief_status", "practice_sessions.debrief_started_at"}
    insp = inspect(engine)
    assert {"user_settings", "practice_contexts", "answer_coaching", "practice_private_questions"} <= set(
        insp.get_table_names())
    cols = {c["name"]: c for c in insp.get_columns("practice_sessions")}
    assert {"debrief", "debrief_status", "debrief_started_at"} <= set(cols)
    assert cols["debrief_status"]["nullable"] is False

    with Session(engine) as db:
        s = db.get(PracticeSession, "s1")
        assert s.debrief_status == "none" and s.debrief is None and s.debrief_started_at is None
        a1, a2 = db.scalars(select(PracticeAnswer).order_by(PracticeAnswer.order_no)).all()
        # 녹음이 있던 답변은 녹음 시각과 보관 기한(만든 시각 + 30일)을 채운다
        assert a1.recorded_at == a1.created_at and a1.audio_expires_at == a1.created_at + timedelta(days=30)
        assert a2.recorded_at is None and a2.audio_expires_at is None
        assert a1.ai_feedback.startswith("잘한 점") and a1.coaching_report is None
        s.debrief = {"lesson": "교훈", "moments": []}
        db.commit()
    with Session(engine) as db:
        assert db.get(PracticeSession, "s1").debrief == {"lesson": "교훈", "moments": []}

    assert upgrade_sqlite(engine) == []  # 두 번 실행해도 안전
    engine.dispose()


def test_every_id_column_binds_as_uuid_on_postgres():
    """Supabase(Postgres)의 uuid 컬럼과 비교할 때 uuid = varchar 오류가 나지 않게 모든 id·외래 키를 uuid로 바인딩한다."""
    from sqlalchemy.dialects import postgresql, sqlite

    from app.db import Base

    ids = [(t.name, c) for t in Base.metadata.sorted_tables for c in t.columns
           if c.name == "id" or c.name.endswith("_id") or c.foreign_keys]
    names = {f"{t}.{c.name}" for t, c in ids}
    # 코칭용 새 테이블의 키도 포함한다
    assert {"practice_contexts.session_id", "answer_coaching.answer_id", "answer_coaching.parent_answer_id",
            "practice_private_questions.question_id", "user_settings.user_id", "questions.user_id"} <= names
    for table, c in ids:
        assert c.type.compile(dialect=postgresql.dialect()) == "UUID", f"{table}.{c.name}"
        assert c.type.compile(dialect=sqlite.dialect()) == "VARCHAR(36)", f"{table}.{c.name}"
