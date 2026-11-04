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
    assert set(added) == {"questions.question_type","questions.taxonomy_version","questions.tagging_source",
                          "practice_answers.question_classification","practice_answers.recording_transcript_sha256","practice_answers.recorded_at", "practice_answers.audio_expires_at",
                          "practice_answers.audio_deleted_at", "practice_sessions.debrief",
                          "practice_sessions.debrief_status", "practice_sessions.debrief_started_at",
                          "practice_sessions.debrief_heartbeat_at", "practice_sessions.debrief_requested_at"}
    insp = inspect(engine)
    assert {"user_settings", "practice_contexts", "answer_coaching", "practice_private_questions"} <= set(
        insp.get_table_names())
    cols = {c["name"]: c for c in insp.get_columns("practice_sessions")}
    assert {"debrief", "debrief_status", "debrief_started_at", "debrief_heartbeat_at", "debrief_requested_at"} <= set(cols)
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


def test_upgrade_adds_later_columns_to_a_p0_branch_database(tmp_path):
    """P0 브랜치로 만든 로컬 DB(user_settings·debrief_started_at은 이미 있음)에도 나중에 더한 컬럼을 채운다."""
    from app.db import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'p0.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for table, column in (("practice_sessions", "debrief_heartbeat_at"), ("practice_sessions", "debrief_requested_at"),
                              ("user_settings", "sweep_audio_before"), ("user_settings", "audio_cleared_at")):
            conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
        conn.execute(text("INSERT INTO user_settings (user_id, consented_at, keep_audio, updated_at) "
                          "VALUES ('u1', '2026-10-15 00:00:00.000000', 1, '2026-10-15 00:00:00.000000')"))
    assert set(upgrade_sqlite(engine)) == {"practice_sessions.debrief_heartbeat_at",
                                           "practice_sessions.debrief_requested_at", "user_settings.sweep_audio_before",
                                           "user_settings.audio_cleared_at"}
    from app.models import UserSettings
    with Session(engine) as db:
        p = db.get(UserSettings, "u1")
        assert p.keep_audio is True and p.sweep_audio_before is None and p.audio_cleared_at is None
    assert upgrade_sqlite(engine) == []
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


APPS_WITHOUT_URL_INDEX = """CREATE TABLE applications (
    id VARCHAR(36) NOT NULL, user_id VARCHAR(36) NOT NULL, company VARCHAR(100) NOT NULL, position VARCHAR(100) NOT NULL,
    job_category VARCHAR(30) NOT NULL, url TEXT, applied_at DATE, stage VARCHAR(10) NOT NULL, status VARCHAR(10) NOT NULL,
    notes TEXT, source VARCHAR(10) NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id))"""


def _app_row(i: str, url: str | None) -> str:
    u = "NULL" if url is None else f"'{url}'"
    return (f"INSERT INTO applications VALUES ('{i}', 'u1', '회사', '직무', '기타', {u}, NULL, '서류', '진행중', NULL, 'web',"
            " '2026-01-01 00:00:00.000000', '2026-01-01 00:00:00.000000')")


def test_upgrade_adds_the_url_unique_index_like_supabase(tmp_path):
    """예전 로컬 DB의 applications에도 schema.sql과 같은 (user_id, url) 부분 고유 인덱스를 만든다."""
    engine = create_engine(f"sqlite:///{tmp_path / 'apps.db'}")
    with engine.begin() as conn:
        conn.execute(text(APPS_WITHOUT_URL_INDEX))
        conn.execute(text(_app_row("a1", "https://x/1")))
        conn.execute(text(_app_row("a2", None)))
    upgrade_sqlite(engine)
    idx = {i["name"]: i for i in inspect(engine).get_indexes("applications")}
    assert idx["applications_user_url_uq"]["unique"] and idx["applications_user_url_uq"]["column_names"] == ["user_id", "url"]
    with engine.begin() as conn:
        conn.execute(text(_app_row("a3", None)))  # URL 없는 건은 여러 개여도 된다
    import pytest
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text(_app_row("a4", "https://x/1")))
    upgrade_sqlite(engine)  # 두 번 실행해도 안전
    engine.dispose()


def test_upgrade_skips_the_url_index_when_old_rows_already_repeat_a_url(tmp_path, caplog):
    """이미 같은 URL이 두 건 있으면 인덱스를 만들 수 없다: 데이터는 건드리지 않고 경고만 남긴 뒤 계속 뜬다."""
    engine = create_engine(f"sqlite:///{tmp_path / 'dup.db'}")
    with engine.begin() as conn:
        conn.execute(text(APPS_WITHOUT_URL_INDEX))
        conn.execute(text(_app_row("a1", "https://x/dup")))
        conn.execute(text(_app_row("a2", "https://x/dup")))
    upgrade_sqlite(engine)
    assert "applications_user_url_uq" not in {i["name"] for i in inspect(engine).get_indexes("applications")}
    assert "applications_user_url_uq" in caplog.text
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM applications")).scalar() == 2
    engine.dispose()


def test_sqlite_enforces_foreign_keys_like_postgres(tmp_path):
    """로컬 SQLite도 외래 키를 강제한다(Supabase와 같게). 없는 세션을 가리키는 답변은 저장되지 않는다."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    from app.db import make_engine

    engine = make_engine(f"sqlite:///{tmp_path / 'fk.db'}")
    upgrade_sqlite(engine)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text("INSERT INTO practice_answers (id, session_id, question_id, order_no, stt_status, created_at)"
                          " VALUES ('a1', 'no-session', 'no-question', 1, 'none', '2026-01-01 00:00:00')"))
    engine.dispose()
