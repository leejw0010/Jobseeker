"""자소서 답변 버전 만들기. 같은 문항에 동시에 저장해도 버전 번호가 겹치지 않게 문항 행을 잠근 뒤 번호를 정한다."""
from sqlalchemy import inspect, update
from sqlalchemy.orm import Session

from ..models import AnswerVersion, EssayItem


def _lock_latest(db: Session, item: EssayItem) -> AnswerVersion | None:
    """문항 행을 잠그고(짧은 쓰기) 커밋된 최신 버전을 다시 읽는다. 잠근 동안 다른 요청은 이 문항에 버전을 더하지 못한다.

    같은 요청에서 먼저 붙인 버전이 다시 읽기에서 사라지지 않게 먼저 flush한다(세션은 autoflush=False)."""
    db.flush()
    db.execute(update(EssayItem).where(EssayItem.id == item.id).values(question_text=EssayItem.question_text),
               execution_options={"synchronize_session": False})
    db.refresh(item, ["versions"])
    return item.versions[-1] if item.versions else None


def add_version(db: Session, item: EssayItem, content: str, source: str, is_submitted: bool) -> AnswerVersion | None:
    """새 최신 버전을 붙인다(커밋은 호출한 쪽에서). 직전 버전과 내용이 같으면 새 버전 없이 제출 표시만 갱신하고 None.

    아직 DB에 없는 새 문항은 다른 요청이 볼 수 없으므로 잠그지 않는다.
    """
    persisted = inspect(item).persistent
    latest = _lock_latest(db, item) if persisted else (item.versions[-1] if item.versions else None)
    if latest and latest.content == content:
        latest.is_submitted = latest.is_submitted or is_submitted
        return None
    v = AnswerVersion(version_no=(latest.version_no + 1) if latest else 1, content=content,
                      char_count=len(content), source=source, is_submitted=is_submitted)
    item.versions.append(v)
    return v


__all__ = ["add_version"]
