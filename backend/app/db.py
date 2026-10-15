from collections.abc import Iterator
from datetime import timedelta

from sqlalchemy import Engine, create_engine, inspect, select, text, update
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)
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
    """테이블 생성 → 빠진 컬럼 추가 → 예전 행 보정."""
    from . import models  # noqa: F401

    Base.metadata.create_all(bind)
    added = add_missing_columns(bind)
    backfill_legacy(bind)
    return added


def init_db() -> None:
    """로컬 SQLite일 때만 테이블을 만들고 빠진 컬럼을 채운다. Supabase는 supabase/schema.sql·migrations로 만든다."""
    if _is_sqlite:
        upgrade_sqlite(engine)
