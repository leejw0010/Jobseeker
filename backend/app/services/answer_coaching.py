"""Shared answer coaching with a complete, versioned input identity."""
from copy import deepcopy

from sqlalchemy import update
from sqlalchemy.orm import Session

from .. import coaching
from ..models import AnswerCoaching, PracticeAnswer, PracticeSession


class NoTranscript(Exception):
    """점검할 전사문이 없다(라우터는 422)."""


class TranscriptChanged(Exception):
    """점검하는 동안 대화 입력이 바뀌었다(라우터는 409)."""


def history_for(answer: PracticeAnswer) -> list[dict]:
    # Include unanswered questions: insertion before this answer changes its context too.
    return [{"question": a.question.text, "answer": a.transcript}
            for a in sorted(answer.session.answers, key=lambda a: (a.order_no, a.id))
            if a.order_no < answer.order_no]


def input_fingerprint(answer: PracticeAnswer) -> str:
    return coaching.input_fingerprint(answer.question.text, answer.transcript,
                                      answer.session.context_snapshot or {}, history_for(answer))


def lock_session(db: Session, session_id: str) -> bool:
    """Common short write lock for transcript edits, result commits and followups."""
    result = db.execute(update(PracticeSession).where(PracticeSession.id == session_id)
                        .values(title=PracticeSession.title),
                        execution_options={"synchronize_session": False})
    return result.rowcount == 1


def current_report(answer: PracticeAnswer) -> dict | None:
    report = answer.coaching_report
    return report if report and report.get("input_status") != "legacy_unverified" else None


def coach(answer: PracticeAnswer, db: Session) -> dict:
    """Call the model without a session write lock, then verify all inputs under it."""
    if not answer.transcript or not answer.transcript.strip():
        raise NoTranscript
    aid, sid = answer.id, answer.session_id
    question, transcript = answer.question.text, answer.transcript
    context, history = deepcopy(answer.session.context_snapshot or {}), history_for(answer)
    classification = deepcopy(answer.question_classification)
    before = coaching.input_fingerprint(question, transcript, context, history)
    # Release any prior read transaction before waiting on external work.
    db.commit()
    # Keep the existing external data scope: only earlier answered turns go to the model.
    # The saved identity additionally covers unanswered entries to detect insertions.
    model_history = [entry for entry in history if entry["answer"]]
    report = coaching.build_report(question, transcript, context, model_history, classification=classification)
    if not lock_session(db, sid):
        db.rollback()
        raise TranscriptChanged
    db.expire_all()
    current = db.get(PracticeAnswer, aid, populate_existing=True)
    if current is None or input_fingerprint(current) != before:
        db.rollback()
        raise TranscriptChanged
    # Classification is optional and cannot invalidate current core coaching.
    from ..taxonomy import current_evidence
    if report.get("competency_evidence") is not None:
        report = {**report, "competency_evidence": current_evidence(
            report["competency_evidence"], current.transcript, current.question_classification)}
    saved = db.get(AnswerCoaching, aid, populate_existing=True)
    current.coaching = saved if saved is not None else AnswerCoaching()
    current.coaching.report = {**report, "input_sha256": before}
    return current.coaching.report
