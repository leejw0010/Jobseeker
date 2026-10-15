"""원본 녹음 보관 정책: 삭제, 사용자 전체 삭제, 만료 녹음 정리(시작 시 + 주기 실행).

전사문·세션 기록은 남기고 원본 음성만 지운다. 저장소 삭제가 실패하면 행을 그대로 두어 다음 정리 때 다시 시도한다.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from . import storage
from .config import settings
from .db import SessionLocal
from .models import PracticeAnswer, PracticeSession

log = logging.getLogger(__name__)


def _utc(dt: datetime | None = None) -> datetime:
    """시간대 없는 값(SQLite)은 UTC로 보고, 있는 값은 UTC로 바꾼다."""
    if dt is None:
        return datetime.now(timezone.utc)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def retention() -> timedelta:
    return timedelta(days=settings.audio_retention_days)


def delete_audio(a: PracticeAnswer, now: datetime | None = None) -> bool:
    """답변의 원본 녹음을 지운다. 지웠으면 True, 녹음이 없거나 저장소 삭제에 실패하면 False(행은 그대로)."""
    if not a.audio_path:
        return False
    try:
        ok = storage.delete(a.audio_path)
    except Exception:  # 저장소 오류가 요청·정리 루프를 깨뜨리지 않게
        log.exception("녹음 삭제 중 오류(%s)", a.audio_path)
        ok = False
    if not ok:
        return False
    a.audio_path = None
    a.audio_deleted_at = _utc(now)
    return True


def delete_user_audio(db: Session, user_id: str, now: datetime | None = None) -> int:
    """사용자의 원본 녹음을 모두 지운다(커밋은 호출한 쪽에서). 지운 개수를 돌려준다."""
    rows = db.scalars(
        select(PracticeAnswer).join(PracticeSession)
        .where(PracticeSession.user_id == user_id, PracticeAnswer.audio_path.is_not(None))
    ).all()
    return sum(1 for a in rows if delete_audio(a, now))


def purge_expired_audio(db: Session, now: datetime | None = None) -> int:
    """보관 기한이 지난 원본 녹음을 지우고 커밋한다. 기한이 없는 예전 행은 created_at + 보관 기간으로 본다."""
    now = _utc(now)
    rows = db.scalars(
        select(PracticeAnswer).where(
            PracticeAnswer.audio_path.is_not(None),
            or_(
                PracticeAnswer.audio_expires_at <= now,
                and_(PracticeAnswer.audio_expires_at.is_(None), PracticeAnswer.created_at <= now - retention()),
            ),
        )
    ).all()
    n = sum(1 for a in rows if delete_audio(a, now))
    db.commit()
    return n


def run_purge() -> int:
    """자체 DB 세션으로 한 번 정리한다. 어떤 오류도 밖으로 던지지 않는다."""
    try:
        with SessionLocal() as db:
            n = purge_expired_audio(db)
    except Exception:
        log.exception("만료된 녹음 정리 실패")
        return 0
    if n:
        log.info("만료된 원본 녹음 %d개를 지웠습니다", n)
    return n


async def purge_loop() -> None:
    """PURGE_INTERVAL_MIN분마다 만료 녹음을 정리한다(앱 종료 시 취소)."""
    interval = max(settings.purge_interval_min, 1) * 60
    while True:
        await asyncio.sleep(interval)
        await asyncio.to_thread(run_purge)
