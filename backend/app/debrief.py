"""세션 종료 후 자동 디브리프와 약점 재연습(Re-drill) 대상 고르기.

디브리프는 BackgroundTasks로 돌고 자체 DB 세션을 연다. 약점 목록은 AI 없이 규칙으로만 정한다.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import llm
from .config import settings
from .db import SessionLocal
from .models import Application, PracticeAnswer, PracticeSession, Question
from .schemas import WeakAnswerOut

log = logging.getLogger(__name__)

MAX_WEAK = 10


def _has_transcript(a: PracticeAnswer) -> bool:
    return bool((a.transcript or "").strip())


def _fresh_feedback(a: PracticeAnswer) -> dict | None:
    fb = a.feedback
    return fb if isinstance(fb, dict) and not fb.get("stale") else None


def job_hint(db: Session, s: PracticeSession, q: Question) -> str | None:
    """채점 프롬프트에 넣을 지원 회사·직무. 지원 건이 없으면 질문의 직무 분류."""
    if s.application_id:
        app = db.scalar(select(Application).where(Application.id == s.application_id,
                                                  Application.user_id == s.user_id))
        if app:
            return f"{app.company} · {app.position}"
    return q.job_category


def prepare_debrief(s: PracticeSession) -> str:
    """종료·재생성 요청에서 상태를 동기로 정한다. 'pending'일 때만 백그라운드 작업을 붙인다."""
    if not llm.available():
        s.debrief_status = "unavailable"
    elif not any(_has_transcript(a) for a in s.answers):
        s.debrief_status = "none"
    else:
        s.debrief_status = "pending"
    return s.debrief_status


def _load(db: Session, session_id: str) -> PracticeSession | None:
    return db.scalar(
        select(PracticeSession).where(PracticeSession.id == session_id)
        .options(selectinload(PracticeSession.answers).selectinload(PracticeAnswer.question))
    )


def run_debrief(session_id: str) -> None:
    """채점이 없거나 낡은 답변을 채점한 뒤 세션 디브리프를 만든다(BackgroundTask)."""
    try:
        with SessionLocal() as db:
            s = _load(db, session_id)
            if s:
                _run(db, s)
    except Exception:  # 작업 중 세션이 지워지는 등 DB 오류도 로그만 남긴다
        log.exception("세션 디브리프 작업 오류(%s)", session_id)


def _run(db: Session, s: PracticeSession) -> None:
    if not llm.available():
        s.debrief_status = "unavailable"
        db.commit()
        return
    answered = [a for a in s.answers if _has_transcript(a)]
    if not answered:
        s.debrief_status = "none"
        db.commit()
        return
    for a in answered:
        if _fresh_feedback(a):
            continue
        try:
            a.feedback = llm.grade_answer(a.question.text, a.transcript, job_hint(db, s, a.question))
            db.commit()
        except Exception:  # 한 답변의 채점 실패는 디브리프 전체를 막지 않는다(그 답변은 피드백 없음)
            db.rollback()
            log.exception("디브리프 중 답변 채점 실패(%s)", a.id)
    try:
        items = [
            {"answer_id": a.id, "order_no": a.order_no, "question": a.question.text,
             "transcript": a.transcript or "", "self_rating": a.self_rating,
             "reflection_note": a.reflection_note,
             "bands": {c.get("label"): c.get("band") for c in (_fresh_feedback(a) or {}).get("criteria", [])}}
            for a in s.answers
        ]
        summary = llm.debrief_summary(items)
        s.debrief = {**summary, "generated_at": datetime.now(timezone.utc).isoformat(),
                     "model": settings.openai_feedback_model}
        s.debrief_status = "done"
    except Exception:  # 채점 결과(위 단계)는 그대로 두고 상태만 실패로
        db.rollback()
        log.exception("세션 디브리프 생성 실패(%s)", s.id)
        s.debrief_status = "failed"
    db.commit()


def weak_answers(s: PracticeSession) -> list[WeakAnswerOut]:
    """다시 연습할 약점 질문: 건너뜀(종료된 세션), 자기평가 1~2점, 루브릭 '부족'."""
    out: list[WeakAnswerOut] = []
    for a in sorted(s.answers, key=lambda x: x.order_no):
        reasons: list[str] = []
        if s.finished_at and not a.recorded_at and not _has_transcript(a):
            reasons.append("건너뜀")
        if a.self_rating in (1, 2):
            reasons.append(f"자기평가 {a.self_rating}점")
        for c in (_fresh_feedback(a) or {}).get("criteria") or []:
            if isinstance(c, dict) and c.get("band") == "부족":
                reasons.append(f"{c.get('label') or c.get('key')} 부족")
        if reasons:
            out.append(WeakAnswerOut(answer_id=a.id, question_id=a.question_id, order_no=a.order_no,
                                     question_text=a.question.text, reasons=reasons))
    return out[:MAX_WEAK]
