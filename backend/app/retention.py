"""원본 녹음 보관 정책: 삭제, 사용자 전체 삭제, 만료 녹음 정리(시작 시 + 주기 실행).

전사문·세션 기록은 남기고 원본 음성만 지운다. 저장소 삭제가 실패하면 보관 기한을 지금으로 당겨
다음 정리(PURGE_INTERVAL_MIN 안)에 다시 시도한다.

답변 행이 가리키지 않는 저장소 파일(고아 파일: 예전 버전이 세션 행만 지우며 남긴 녹음, 지워진 답변에 올라가던 녹음 등)도
지운다. 전체 삭제·동의 철회는 사용자 폴더({user_id}/)를 통째로 훑고, 세션·질문 삭제는 지운 답변의 파일을 경로 규칙으로
찾아 지우고, 만료 정리는 보관 기간이 지난 고아 파일을 지운다.
"""
import asyncio
import logging
import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.orm import Session

from . import storage
from .config import settings
from .db import SessionLocal
from .models import PracticeAnswer, PracticeSession, UserSettings

log = logging.getLogger(__name__)


def _utc(dt: datetime | None = None) -> datetime:
    """시간대 없는 값(SQLite)은 UTC로 보고, 있는 값은 UTC로 바꾼다."""
    if dt is None:
        return datetime.now(timezone.utc)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def retention() -> timedelta:
    return timedelta(days=settings.audio_retention_days)


def cleared_since(prefs: UserSettings, started: datetime) -> bool:
    """started(업로드·다시 전사를 시작한 시각) 뒤에 원본 녹음을 모두 지웠는가(전체 삭제·동의 철회).

    그랬다면 이 요청이 저장·전사하던 녹음도 그 삭제가 지웠거나 지웠어야 한다: 커밋할 때 녹음을 지운 것으로 저장한다.
    """
    return prefs.audio_cleared_at is not None and _utc(prefs.audio_cleared_at) >= _utc(started)


def owned_audio_path(a: PracticeAnswer) -> str | None:
    """audio_path가 이 답변의 경로 규칙({user_id}/{session_id}/{answer_id}.{확장자})과 맞을 때만 돌려준다.

    서비스 키로 저장소를 읽고 지우므로, 다른 사람 파일을 가리키게 바뀐 경로는 믿지 않는다.
    """
    path = a.audio_path
    if not path or not a.session:
        return None
    prefix = f"{a.session.user_id}/{a.session_id}/{a.id}."
    return path if path.startswith(prefix) and re.fullmatch(r"[A-Za-z0-9]{1,10}", path[len(prefix):]) else None


def delete_audio(a: PracticeAnswer, now: datetime | None = None) -> bool:
    """답변의 원본 녹음을 지운다(커밋은 호출한 쪽에서). 지웠으면 True, 녹음이 없거나 저장소 삭제에 실패하면 False.

    실패하면 보관 기한을 지금으로 당겨 다음 만료 정리가 다시 지우게 한다.
    """
    if not a.audio_path:
        return False
    now = _utc(now)
    path = owned_audio_path(a)
    if path is None:  # 경로 규칙에 맞지 않으면 그 파일은 건드리지 않고 연결만 끊는다
        log.warning("경로 규칙에 맞지 않는 녹음 경로(%s): 연결만 끊습니다", a.id)
        ok = True
    else:
        try:
            ok = storage.delete(path)
        except Exception:  # 저장소 오류가 요청·정리 루프를 깨뜨리지 않게
            log.exception("녹음 삭제 중 오류(%s)", path)
            ok = False
    if not ok:
        if a.audio_expires_at is None or _utc(a.audio_expires_at) > now:
            a.audio_expires_at = now
        return False
    a.audio_path = None
    a.audio_deleted_at = now
    return True


def delete_audios(rows, now: datetime | None = None) -> tuple[int, int]:
    """여러 답변의 원본 녹음을 지운다. (지운 개수, 못 지운 개수)."""
    deleted = failed = 0
    for a in rows:
        if not a.audio_path:
            continue
        if delete_audio(a, now):
            deleted += 1
        else:
            failed += 1
    return deleted, failed


def delete_object(path: str) -> bool:
    """행 없이 저장소 파일 하나를 지운다. 이미 없으면 지운 것으로 본다. 실패하면 False(예외 없음)."""
    try:
        return storage.delete(path)
    except Exception:
        log.exception("녹음 파일 삭제 중 오류(%s)", path)
        return False


def _user_folder(user_id: str) -> str | None:
    """사용자 폴더 경로. id가 경로 한 칸으로 쓸 수 없는 값이면(개발 모드의 임의 헤더 등) 훑지 않는다."""
    return f"{user_id}/" if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(user_id)) else None


class UserAudioDeleted(NamedTuple):
    """사용자 원본 녹음 전체 삭제 결과."""

    deleted: int  # 지운 녹음·파일 수
    failed: int  # 저장소 오류로 못 지운 녹음·파일 수
    unchecked: bool  # 폴더 목록을 읽지 못해 행이 없는 파일이 남았는지 모른다
    sweep: bool  # 다음 만료 정리가 폴더를 다시 훑어야 한다(행이 없는 파일을 못 지웠거나 목록을 못 읽음)


def delete_user_audio(db: Session, user_id: str, now: datetime | None = None) -> UserAudioDeleted:
    """사용자의 원본 녹음을 모두 지운다. 지운 시각만 먼저 커밋하고, 녹음을 지운 결과의 커밋은 호출한 쪽에서 한다.

    먼저 지운 시각(audio_cleared_at)을 동의 설정 행에 저장·커밋한다. 올리는 중이거나 다시 전사하는 중인 요청은 커밋하기
    전에 이 행을 잠그고 다시 읽으므로, 이 시각 전에 시작했으면 녹음을 지운 것으로 저장한다(전사문은 남긴다). 그래서
    아직 어떤 행도 가리키지 않는 올리는 중인 녹음도 지운 것으로 세어도 맞다. 이 시각 뒤에 저장된 파일은 그 뒤에 시작한
    업로드의 녹음이라 건드리지 않는다(그 업로드가 직접 커밋한다).

    답변 행이 가리키는 녹음을 지운 뒤 사용자 폴더를 훑어 어떤 행도 가리키지 않는 파일까지 지운다. 행이 있는 녹음을
    못 지우면 보관 기한을 당겨 두고, 행이 없는 파일을 못 지웠거나 폴더 목록을 못 읽으면 sweep이 True: 호출한 쪽이
    request_sweep으로 표시해 다음 만료 정리가 다시 지우게 한다. 목록을 못 읽으면 남은 수를 모르니 세지 않고 unchecked로 알린다.
    """
    now = _utc(now)
    # 업로드·다시 전사가 동의를 다시 읽을 때와 같은 행을 잠가 쓴다: 그 요청은 이 시각을 보거나, 먼저 커밋해 아래에서 읽힌다
    db.execute(update(UserSettings).where(UserSettings.user_id == user_id).values(audio_cleared_at=now),
               execution_options={"synchronize_session": False})
    db.commit()
    rows = db.scalars(
        select(PracticeAnswer).join(PracticeSession)
        .where(PracticeSession.user_id == user_id, PracticeAnswer.audio_path.is_not(None))
    ).all()
    deleted, failed = delete_audios(rows, now)
    folder = _user_folder(user_id)
    if folder is None:
        return UserAudioDeleted(deleted, failed, False, False)
    kept = {a.audio_path for a in rows if a.audio_path}  # 못 지운 녹음은 위에서 이미 셌다
    try:
        objects = storage.list(folder)
    except Exception:
        log.exception("녹음 폴더 목록을 읽지 못했습니다(%s)", folder)
        return UserAudioDeleted(deleted, failed, True, True)
    orphan_failed = 0
    for obj in objects:
        if obj.path in kept:
            continue
        if obj.modified is not None and obj.modified > now:  # 지운 시각 뒤에 시작한 업로드의 녹음(만료 정리의 표시와 같은 비교)
            continue
        if delete_object(obj.path):
            deleted += 1
        else:
            orphan_failed += 1
    return UserAudioDeleted(deleted, failed + orphan_failed, False, orphan_failed > 0)


def delete_session_files(db: Session, user_id: str, session_id: str, answer_ids: Iterable[str] | None = None) -> None:
    """지운 세션(answer_ids를 주면 그 답변들)의 녹음 파일을 경로 규칙({user_id}/{session_id}/{answer_id}.확장자)으로 찾아 지운다.

    답변 행을 지우고 커밋한 뒤에 부른다. 세션·질문 삭제가 답변을 읽은 뒤에 커밋된 업로드의 녹음은 읽은 행에 없어 먼저 지우지
    못했지만 그 행은 함께 지워졌다. 목록을 못 읽었거나 못 지운 파일이 있으면 다음 만료 정리가 다시 지우게 표시한다.
    """
    folder = _user_folder(user_id)
    if folder is None or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(session_id)):
        return
    prefix = f"{folder}{session_id}/"
    names = None if answer_ids is None else tuple(f"{prefix}{answer_id}." for answer_id in answer_ids)
    try:
        objects = storage.list(prefix)
    except Exception:
        log.exception("녹음 폴더 목록을 읽지 못했습니다(%s)", prefix)
        request_sweep(db, user_id)
        return
    failed = [obj.path for obj in objects if (names is None or obj.path.startswith(names)) and not delete_object(obj.path)]
    if failed:
        request_sweep(db, user_id)


def request_sweep(db: Session, user_id: str, now: datetime | None = None) -> None:
    """지금까지 저장된 이 사용자의 고아 파일을 다음 만료 정리가 다시 지우게 표시하고 커밋한다."""
    now = _utc(now)
    p = db.get(UserSettings, user_id)
    if p is None:
        p = UserSettings(user_id=user_id, keep_audio=False)
        db.add(p)
    if p.sweep_audio_before is None or _utc(p.sweep_audio_before) < now:
        p.sweep_audio_before = now
    db.commit()


def purge_orphans(db: Session, now: datetime | None = None) -> int:
    """답변 행이 가리키지 않는 저장소 파일을 지우고 커밋한다. 지운 개수.

    보관 기간이 지난 파일, 그리고 전체 삭제·철회 때 못 지워 표시해 둔 사용자의 그 전에 저장된 파일을 지운다.
    저장 시각을 모르는 파일은 표시가 있을 때만 지운다. 새 파일은 올리는 중인 녹음일 수 있어 기간이 지날 때까지 둔다.
    """
    now = _utc(now)
    owned = {(str(user_id), path) for user_id, path in db.execute(
        select(PracticeSession.user_id, PracticeAnswer.audio_path).join(PracticeSession)
        .where(PracticeAnswer.audio_path.is_not(None))).all()}
    marks = {str(p.user_id): p.sweep_audio_before
             for p in db.scalars(select(UserSettings).where(UserSettings.sweep_audio_before.is_not(None)))}
    n = 0
    failed: set[str] = set()
    for obj in storage.list(""):
        user_id = obj.path.split("/", 1)[0] if "/" in obj.path else None
        if user_id is None or (user_id, obj.path) in owned:
            continue
        mark = marks.get(user_id)
        expired = obj.modified is not None and obj.modified <= now - retention()
        marked = mark is not None and (obj.modified is None or obj.modified <= _utc(mark))
        if not (expired or marked):
            continue
        # 목록을 읽는 동안 올라간 녹음이 막 행에 연결됐을 수 있다
        if db.scalar(select(exists().where(PracticeAnswer.audio_path == obj.path))):
            continue
        if delete_object(obj.path):
            n += 1
        elif mark is not None:
            failed.add(user_id)
    for user_id, mark in marks.items():
        if user_id not in failed:  # 다 지웠다. 그사이 새로 표시했으면 그 표시는 남긴다
            db.execute(update(UserSettings).where(UserSettings.user_id == user_id, UserSettings.sweep_audio_before == mark)
                       .values(sweep_audio_before=None), execution_options={"synchronize_session": False})
    db.commit()
    return n


def purge_expired_audio(db: Session, now: datetime | None = None) -> int:
    """보관 기한이 지난 원본 녹음과 고아 파일을 지우고 커밋한다. 기한이 없는 예전 행은 created_at + 보관 기간으로 본다."""
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
    try:
        n += purge_orphans(db, now)
    except Exception:  # 저장소 목록 오류가 행 정리를 되돌리지 않게
        db.rollback()
        log.exception("고아 녹음 파일 정리 실패")
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
