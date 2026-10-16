"""세션 종료 후 자동 디브리프와 다시 연습할 답변 고르기.

디브리프는 BackgroundTasks로 돌고 자체 DB 세션을 연다. 먼저 코칭 보고서가 없는 답변을 /coach와 같은 경로로
점검하고(키가 없으면 기본 점검), 키가 있을 때만 세션 전체 요약을 만든다. 다시 연습할 답변은 AI 없이 규칙으로 정한다.
점검은 오래 걸리므로(답변마다 LLM 호출) 그 사이 사용자가 전사문을 고칠 수 있다. 고친 답변은 /coach처럼 409로 버리고
다음 바퀴에서 새 전사문으로 다시 점검한다.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import coaching, llm
from .config import settings
from .db import SessionLocal
from .models import PracticeAnswer, PracticeSession
from .schemas import WeakAnswerOut

log = logging.getLogger(__name__)

MAX_DRILL = 20  # 다시 연습 세션에 담는 답변 수 상한
# 작업 시작 시각이 이보다 오래되면 작업이 사라진 것(서버 재시작 등)으로 보고 다시 시작할 수 있다
DEBRIEF_STALE_AFTER = timedelta(minutes=5)


def _has_transcript(a: PracticeAnswer) -> bool:
    return bool((a.transcript or "").strip())


def _needs_coaching(a: PracticeAnswer) -> bool:
    return _has_transcript(a) and not a.coaching_report


def drill_picks(s: PracticeSession) -> list[tuple[PracticeAnswer, list[str], int | None]]:
    """다시 연습할 답변: 코칭에 '보완'이 있거나 자기평가가 1~2점. (답변, 보완 기준 이름, 낮은 자기평가), 세션 순서대로 최대 20개."""
    picked = []
    for a in s.answers:
        weak = [c["label"] for c in (a.coaching_report or {}).get("criteria", []) if c["status"] == "보완"]
        low = a.self_rating if a.self_rating in (1, 2) else None
        if weak or low:
            picked.append((a, weak, low))
        if len(picked) == MAX_DRILL:
            break
    return picked


def drill_focus(weak: list[str], low: int | None) -> list[str]:
    """다시 연습 세션(drill_targets)에 남기는 초점 이름."""
    return [*weak, *([f"자기평가 {low}점"] if low else [])]


def weak_answers(s: PracticeSession) -> list[WeakAnswerOut]:
    """화면의 '다시 연습할 답변' 목록(다시 연습 세션에 담길 답변과 같다). AI 코칭에서 나온 이유에는 'AI ·'를 붙인다."""
    out = []
    for a, weak, low in drill_picks(s):
        prefix = "AI · " if (a.coaching_report or {}).get("method") == "ai" else ""
        reasons = [f"{prefix}{label} 보완" for label in weak] + ([f"자기평가 {low}점"] if low else [])
        out.append(WeakAnswerOut(answer_id=a.id, question_id=a.question_id, order_no=a.order_no,
                                 question_text=a.question.text, reasons=reasons))
    return out


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def debrief_running(s: PracticeSession, now: datetime | None = None) -> bool:
    """디브리프 작업이 아직 도는 중인가. 시작 시각이 없거나 오래됐으면 사라진 작업으로 본다."""
    if not s.debrief_started_at:
        return False
    return (now or datetime.now(timezone.utc)) - _utc(s.debrief_started_at) < DEBRIEF_STALE_AFTER


def prepare_debrief(s: PracticeSession) -> bool:
    """종료·재생성 요청에서 상태를 동기로 정한다. 백그라운드 작업을 붙여야 하면 True.

    키가 없으면 'unavailable'(요약은 만들지 않지만 기본 점검은 돈다), 전사문이 없으면 'none', 그 밖에는 'pending'.
    이미 도는 작업이 있으면 상태를 그대로 두고 작업을 하나 더 붙이지 않는다.
    """
    if debrief_running(s):
        return False
    if not llm.available():
        s.debrief_status = "unavailable"
    elif not any(_has_transcript(a) for a in s.answers):
        s.debrief_status = "none"
    else:
        s.debrief_status = "pending"
    start = s.debrief_status == "pending" or any(_needs_coaching(a) for a in s.answers)
    if start:
        s.debrief_started_at = datetime.now(timezone.utc)
    return start


def _load(db: Session, session_id: str) -> PracticeSession | None:
    return db.scalar(
        select(PracticeSession).where(PracticeSession.id == session_id)
        .options(selectinload(PracticeSession.answers).selectinload(PracticeAnswer.question))
    )


def run_debrief(session_id: str) -> None:
    """코칭 보고서가 없는 답변을 점검한 뒤(키가 있으면) 세션 디브리프를 만든다(BackgroundTask)."""
    try:
        with SessionLocal() as db:
            s = _load(db, session_id)
            if s:
                _run(db, s)
    except Exception:  # 작업 중 세션이 지워지는 등 DB 오류도 로그만 남긴다
        log.exception("세션 디브리프 작업 오류(%s)", session_id)


def _coach_all(db: Session, s: PracticeSession) -> None:
    """코칭 보고서가 없는 답변을 /coach와 같은 경로로 점검한다. 점검 중 전사문이 바뀐 답변(409)은 건너뛴다."""
    from .routers.practice import _report  # 라우터가 이 모듈을 가져오므로 순환을 피해 여기서 가져온다

    # 점검하는 동안 앞 순서 답변이 새로 녹음되거나 고쳐질 수 있으니, 새로 점검할 것이 없을 때까지 다시 돈다.
    # 같은 (답변, 전사문)은 한 번만 시도하므로 실패한 점검을 되풀이하지 않는다.
    tried: set[tuple[str, str]] = set()
    for _ in range(5):
        progressed = False
        for a in list(s.answers):
            db.refresh(a)  # 앞 답변을 점검하는 동안 고친 전사문·새로 받은 보고서를 다시 읽는다
            if not _needs_coaching(a) or (a.id, a.transcript) in tried:
                continue
            tried.add((a.id, a.transcript))
            progressed = True
            try:
                _report(a, db)
                db.commit()
            except HTTPException as e:  # 409: 점검하는 동안 전사문이 바뀜(_report가 이미 rollback)
                log.info("점검하는 동안 답변이 바뀌어 점검을 버렸습니다(%s, %s)", a.id, e.status_code)
            except Exception:  # 한 답변의 점검 실패는 디브리프 전체를 막지 않는다(그 답변은 보고서 없음)
                db.rollback()
                log.exception("디브리프 중 답변 점검 실패(%s)", a.id)
        if not progressed:
            break


def _summarize(db: Session, s: PracticeSession) -> None:
    for a in s.answers:
        db.refresh(a)  # 요약은 지금 전사문과 보고서로 만든다
    try:
        items = []
        for a in s.answers:
            report = a.coaching_report or {}
            items.append({"answer_id": a.id, "order_no": a.order_no, "question": a.question.text,
                          "transcript": a.transcript or "", "self_rating": a.self_rating,
                          "reflection_note": a.reflection_note, "coaching_method": report.get("method"),
                          "coaching": {c["label"]: c["status"] for c in report.get("criteria", [])}})
        summary = llm.debrief_summary(items, {c["label"]: c["checks"] for c in coaching.CRITERIA})
        # 요약을 만드는 동안 전사문이 바뀌었으면 지금 전사문에 없는 '주목할 순간'은 뺀다
        now_text = dict(db.execute(select(PracticeAnswer.id, PracticeAnswer.transcript)
                                   .where(PracticeAnswer.session_id == s.id)).all())
        summary["moments"] = [m for m in summary["moments"]
                              if llm.verify_quote(m["quote"], now_text.get(m["answer_id"]) or "")[1]]
        s.debrief = {**summary, "generated_at": datetime.now(timezone.utc).isoformat(),
                     "model": settings.openai_feedback_model}
        s.debrief_status = "done"
    except Exception:  # 점검 결과(앞 단계)는 그대로 두고 상태만 실패로
        db.rollback()
        log.exception("세션 디브리프 생성 실패(%s)", s.id)
        s.debrief_status = "failed"


def _run(db: Session, s: PracticeSession) -> None:
    try:
        _coach_all(db, s)
        db.refresh(s)
        if not llm.available():
            s.debrief_status = "unavailable"
        elif not any(_has_transcript(a) for a in s.answers):
            s.debrief_status = "none"
        else:
            _summarize(db, s)
    finally:
        s.debrief_started_at = None  # 작업이 끝났다(다음 종료·재생성 요청은 새로 시작할 수 있다)
        db.commit()
