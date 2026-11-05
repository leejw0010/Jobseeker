import logging
from collections.abc import Iterator
from datetime import timedelta

from sqlalchemy import Engine, create_engine, event, inspect, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

log = logging.getLogger(__name__)


def make_engine(url: str) -> Engine:
    """DB 엔진. SQLite는 연결마다 외래 키를 켠다(기본은 꺼져 있다): Supabase(Postgres)처럼 없는 행을 가리키지 못하고
    on delete cascade·set null도 같게 동작한다."""
    sqlite = url.startswith("sqlite")
    eng = create_engine(url, connect_args={"check_same_thread": False} if sqlite else {})
    if sqlite:
        @event.listens_for(eng, "connect")
        def _foreign_keys(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return eng


_is_sqlite = settings.database_url.startswith("sqlite")
engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def add_missing_columns(bind: Engine) -> list[str]:
    """모델에는 있지만 기존 테이블에 없는 컬럼을 ALTER TABLE로 추가한다. 추가한 "테이블.컬럼" 목록을 돌려준다.

    create_all은 이미 있는 테이블에 컬럼을 더하지 않으므로, 팀원이 쓰던 로컬 jobseeker.db를 살리려고 쓴다.
    """
    dialect = bind.dialect
    quote = dialect.identifier_preparer.quote
    ddl = dialect.ddl_compiler(dialect, None)
    insp = inspect(bind)
    tables = set(insp.get_table_names())
    added: list[str] = []
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have or col.primary_key:
                    continue
                stmt = f"ALTER TABLE {quote(table.name)} ADD COLUMN {quote(col.name)} {col.type.compile(dialect=dialect)}"
                default = ddl.get_column_default_string(col)
                if default is not None:
                    # SQLite는 기본값이 있어야 NOT NULL 컬럼을 추가할 수 있다
                    stmt += f" DEFAULT {default}" + ("" if col.nullable else " NOT NULL")
                conn.execute(text(stmt))
                added.append(f"{table.name}.{col.name}")
    return added


def add_missing_indexes(bind: Engine) -> list[str]:
    """모델에는 있지만 기존 테이블에 없는 인덱스를 만든다. 만든 인덱스 이름 목록.

    create_all은 이미 있는 테이블에 인덱스를 더하지 않는다. 고유 인덱스를 만들 수 없을 만큼 예전 행이 이미 겹치면
    (같은 URL의 지원 건 두 개 등) 데이터는 건드리지 않고 경고만 남긴다. 그 DB는 겹친 행을 정리한 뒤 다시 시작하면 된다.
    """
    insp = inspect(bind)
    tables = set(insp.get_table_names())
    added: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue
        have = {i["name"] for i in insp.get_indexes(table.name)}
        for index in table.indexes:
            if index.name in have:
                continue
            try:
                index.create(bind)
            except (IntegrityError, OperationalError) as e:
                log.warning("인덱스 %s를 만들지 못했어요(이미 겹치는 행이 있을 수 있어요): %s", index.name, e.orig)
                continue
            added.append(index.name)
    return added


def backfill_legacy(bind: Engine) -> None:
    """예전 행 보정: 녹음이 있는 답변은 만든 시각을 녹음 시각으로 보고, 보관 기한(만든 시각 + 보관 기간)을 붙인다.

    Supabase는 migrations/20261015_practice_p0.sql이 같은 보정을 한다.
    """
    from . import models  # noqa: F401

    t = Base.metadata.tables["practice_answers"]
    has_audio = t.c.audio_path.is_not(None)
    with bind.begin() as conn:
        conn.execute(update(t).where(has_audio, t.c.recorded_at.is_(None)).values(recorded_at=t.c.created_at))
        keep = timedelta(days=settings.audio_retention_days)
        for answer_id, created_at in conn.execute(
            select(t.c.id, t.c.created_at).where(has_audio, t.c.audio_expires_at.is_(None))
        ).all():
            conn.execute(update(t).where(t.c.id == answer_id).values(audio_expires_at=created_at + keep))


def upgrade_sqlite(bind: Engine) -> list[str]:
    """테이블 생성 → 빠진 컬럼·인덱스 추가 → 예전 행 보정. 추가한 컬럼 목록을 돌려준다."""
    from . import models  # noqa: F401

    Base.metadata.create_all(bind)
    added = add_missing_columns(bind)
    add_missing_indexes(bind)
    if settings.practice_insights_enabled:
        validate_insights_schema(bind)
    protect_sqlite_version_history(bind)
    backfill_legacy(bind)
    return added


def protect_sqlite_version_history(bind: Engine) -> None:
    """Match PostgreSQL history guards; parent deletion uses database cascades."""
    fields = ('id', 'essay_item_id', 'version_no', 'content', 'char_count', 'source', 'created_at')
    changed = ' OR '.join(f'NEW.{name} IS NOT OLD.{name}' for name in fields)
    with bind.begin() as conn:
        conn.execute(text(f"""CREATE TRIGGER IF NOT EXISTS answer_versions_immutable_update
          BEFORE UPDATE ON answer_versions WHEN {changed} OR (OLD.is_submitted AND NOT NEW.is_submitted)
          BEGIN SELECT RAISE(ABORT, 'Answer version history is immutable'); END"""))
        conn.execute(text("""CREATE TRIGGER IF NOT EXISTS answer_versions_immutable_delete
          BEFORE DELETE ON answer_versions
          WHEN EXISTS(SELECT 1 FROM essay_items WHERE id=OLD.essay_item_id)
          BEGIN SELECT RAISE(ABORT, 'Delete the parent essay or application explicitly'); END"""))


def init_db() -> None:
    """로컬 SQLite일 때만 테이블을 만들고 빠진 컬럼을 채운다. Supabase는 supabase/schema.sql·migrations로 만든다."""
    if _is_sqlite:
        upgrade_sqlite(engine)
    else:
        validate_track_schema(engine)
        if settings.practice_insights_enabled:
            validate_insights_schema(engine)


def validate_track_schema(bind: Engine) -> None:
    required = {"application_states": {"application_id", "baseline_stage", "baseline_status", "override_stage", "override_status", "override_origin", "revision"},
                "essay_submissions": {"id", "essay_item_id", "version_id", "sequence", "confirmed_at", "source"}}
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    missing = []
    for table, columns in required.items():
        actual = {c['name'] for c in inspector.get_columns(table)} if table in tables else set()
        missing.extend(f'{table}.{name}' for name in sorted(columns-actual))
    if missing:
        raise RuntimeError('Track requires manual migration 20261105_track_integrity.sql; missing: ' + ', '.join(missing))
    if bind.dialect.name == 'postgresql':
        with bind.connect() as conn:
            present = conn.execute(text("""SELECT EXISTS(
              SELECT 1 FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
              JOIN pg_namespace n ON n.oid=c.relnamespace
              WHERE n.nspname='public' AND c.relname='answer_versions'
                AND t.tgname='answer_versions_history_guard' AND NOT t.tgisinternal AND t.tgenabled <> 'D')""")).scalar_one()
        if not present:
            raise RuntimeError('Track requires manual migration 20261105_version_immutability.sql')


def validate_insights_schema(bind: Engine) -> None:
    """Read-only schema capability check; PostgreSQL migrations are always manual."""
    required={"questions":{"question_type","taxonomy_version","tagging_source"},
              "question_competencies":{"question_id","competency_key","position"},
              "practice_answers":{"question_classification","recording_transcript_sha256"}}
    inspector=inspect(bind)
    tables=set(inspector.get_table_names())
    missing=[]
    for table,columns in required.items():
        actual={c["name"] for c in inspector.get_columns(table)} if table in tables else set()
        missing.extend(f"{table}.{c}" for c in sorted(columns-actual))
    if "question_competencies" in tables:
        indexes = {i['name'] for i in inspector.get_indexes('question_competencies') if i['unique']}
        if 'question_competencies_position_uq' not in indexes:
            missing.append('question_competencies_position_uq')
    if missing:
        raise RuntimeError("PRACTICE_INSIGHTS_ENABLED requires manual migrations 20261104_practice_insights.sql and 20261105_practice_integrity.sql; missing: "+", ".join(missing))
