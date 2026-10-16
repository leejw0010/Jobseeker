"""세션 종료 후 자동 디브리프와 약점 재연습(Re-drill) 대상 고르기.

디브리프는 BackgroundTasks로 돌고 자체 DB 세션을 연다. 약점 목록은 AI 없이 규칙으로만 정한다.
채점은 오래 걸리므로(답변마다 LLM 호출) 그 사이 사용자가 전사문을 고칠 수 있다. 피드백은 채점한 전사문이
그대로일 때만 저장하고(save_feedback), 채점한 전사문의 지문(transcript_sha)과 지금 전사문이 다르면 낡은 것으로 본다.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from . import llm
from .config import settings
from .db import SessionLocal
from .models import Application, PracticeAnswer, PracticeSession, Question
from .rubric import feedback_current, question_type
from .schemas import WeakAnswerOut

log = logging.getLogger(__name__)

MAX_WEAK = 10
# 'pending'이 이보다 오래되면 작업이 사라진 것(서버 재시작 등)으로 보고 다시 시작할 수 있다
DEBRIEF_STALE_AFTER = timedelta(minutes=10)


def _has_transcript(a: PracticeAnswer) -> bool:
    return bool((a.transcript or "").strip())


def _fresh_feedback(a: PracticeAnswer) -> dict | None:
    fb = a.feedback
    return fb if feedback_current(fb, a.transcript) else None


def qtype(q: Question) -> str:
    """채점에 넘길 질문 유형(rubric.question_type)."""
    return question_type(q.category, q.text, q.source)


def save_feedback(db: Session, a: PracticeAnswer, fb: dict, graded: str) -> bool:
    """채점한 전사문이 그대로일 때만 피드백을 저장하고 커밋한다. 그 사이 전사문이 바뀌었으면 버리고 False.

    채점 중에 고친(또는 새로 녹음한) 전사문 위에 옛 전사문의 채점을 덮어쓰지 않게 조건부 UPDATE를 쓴다.
    """
    r = db.execute(
        update(PracticeAnswer)
        .where(PracticeAnswer.id == a.id, PracticeAnswer.transcript == graded)
        .values(feedback=fb)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    db.refresh(a)
    return r.rowcount == 1


def job_hint(db: Session, s: PracticeSession, q: Question) -> str | None:
    """채점 프롬프트에 넣을 지원 회사·직무. 지원 건이 없으면 질문의 직무 분류."""
    if s.application_id:
        app = db.scalar(select(Application).where(Application.id == s.application_id,
                                                  Application.user_id == s.user_id))
        if app:
            return f"{app.company} · {app.position}"
    return q.job_category


def debrief_running(s: PracticeSession, now: datetime | None = None) -> bool:
    """디브리프 작업이 아직 도는 중인가. 시작 시각이 없거나 오래된 'pending'은 사라진 작업으로 본다."""
    if s.debrief_status != "pending" or not s.debrief_started_at:
        return False
    started = s.debrief_started_at
    started = started.replace(tzinfo=timezone.utc) if started.tzinfo is None else started
    return (now or datetime.now(timezone.utc)) - started < DEBRIEF_STALE_AFTER


def prepare_debrief(s: PracticeSession) -> str:
    """종료·재생성 요청에서 상태를 동기로 정한다. 'pending'일 때만 백그라운드 작업을 붙인다.

    이미 도는 작업이 있으면 상태를 그대로 두고 'running'을 돌려준다(작업을 하나 더 붙이지 않는다).
    """
    if debrief_running(s):
        return "running"
    if not llm.available():
        s.debrief_status = "unavailable"
    elif not any(_has_transcript(a) for a in s.answers):
        s.debrief_status = "none"
    else:
        s.debrief_status = "pending"
        s.debrief_started_at = datetime.now(timezone.utc)
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
    if not any(_has_transcript(a) for a in s.answers):
        s.debrief_status = "none"
        db.commit()
        return
    for a in s.answers:
        db.refresh(a)  # 앞 답변을 채점하는 동안 고친 전사문·새로 받은 채점을 다시 읽는다
        if not _has_transcript(a) or _fresh_feedback(a):
            continue
        graded = a.transcript
        try:
            fb = llm.grade_answer(a.question.text, graded, job_hint(db, s, a.question), qtype(a.question))
            if not save_feedback(db, a, fb, graded):
                log.info("채점하는 동안 전사문이 바뀌어 채점을 버렸습니다(%s)", a.id)
        except Exception:  # 한 답변의 채점 실패는 디브리프 전체를 막지 않는다(그 답변은 피드백 없음)
            db.rollback()
            log.exception("디브리프 중 답변 채점 실패(%s)", a.id)
    for a in s.answers:
        db.refresh(a)  # 요약은 지금 전사문과 채점으로 만든다
    try:
        items = [
            {"answer_id": a.id, "order_no": a.order_no, "question": a.question.text,
             "transcript": a.transcript or "", "self_rating": a.self_rating,
             "reflection_note": a.reflection_note,
             "bands": {c.get("label"): c.get("band") for c in (_fresh_feedback(a) or {}).get("criteria", [])}}
            for a in s.answers
        ]
        summary = llm.debrief_summary(items)
        # 요약을 만드는 동안 전사문이 바뀌었으면 지금 전사문에 없는 '주목할 순간'은 뺀다
        now_text = dict(db.execute(select(PracticeAnswer.id, PracticeAnswer.transcript)
                                   .where(PracticeAnswer.session_id == s.id)).all())
        summary["moments"] = [m for m in summary["moments"]
                              if llm.verify_quote(m["quote"], now_text.get(m["answer_id"]) or "")[1]]
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
