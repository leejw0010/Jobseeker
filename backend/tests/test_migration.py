"""예전 스키마의 로컬 SQLite DB에 빠진 컬럼을 채우는 마이그레이션."""
from datetime import timedelta

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.db import upgrade_sqlite
from app.models import PracticeAnswer, PracticeSession

# main 브랜치 모델이 만들던 테이블(P0 이전)
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
    assert {"practice_answers.recorded_at", "practice_answers.audio_expires_at", "practice_answers.audio_deleted_at",
            "practice_answers.feedback", "practice_sessions.debrief", "practice_sessions.debrief_status",
            "practice_sessions.redrill_of"} <= set(added)
    insp = inspect(engine)
    assert "user_settings" in insp.get_table_names()
    cols = {c["name"]: c for c in insp.get_columns("practice_sessions")}
    assert {"debrief", "debrief_status", "redrill_of"} <= set(cols)
    assert cols["debrief_status"]["nullable"] is False

    with Session(engine) as db:
        s = db.get(PracticeSession, "s1")
        assert s.debrief_status == "none" and s.debrief is None and s.redrill_of is None
        a1, a2 = db.scalars(select(PracticeAnswer).order_by(PracticeAnswer.order_no)).all()
        # 녹음이 있던 답변은 녹음 시각과 보관 기한(만든 시각 + 30일)을 채운다
        assert a1.recorded_at == a1.created_at and a1.audio_expires_at == a1.created_at + timedelta(days=30)
        assert a2.recorded_at is None and a2.audio_expires_at is None
        assert a1.feedback is None and a1.ai_feedback.startswith("잘한 점")
        a1.feedback = {"rubric": "star-v1", "criteria": []}
        db.commit()
    with Session(engine) as db:
        assert db.get(PracticeAnswer, "a1").feedback == {"rubric": "star-v1", "criteria": []}

    assert upgrade_sqlite(engine) == []  # 두 번 실행해도 안전
    engine.dispose()
