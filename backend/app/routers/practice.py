"""② Practice: 질문은행·맞춤 질문, 모의시험 세션, 녹음·전사, 회고, 코칭·디브리프·재연습, 녹음 동의."""
import random
import secrets
from copy import deepcopy
from typing import Literal
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .. import coaching, llm, storage, stt, taxonomy
from ..auth import current_user_id
from ..config import settings
from ..db import get_db
from ..debrief import debrief_fingerprint, debrief_running, drill_focus, drill_picks, prepare_debrief, run_debrief, weak_answers
from ..models import (
    AnswerCoaching,
    Application,
    PracticeAnswer,
    PracticeContext,
    PracticePrivateQuestion,
    PracticeSession,
    Question,
    UserSettings,
    recording_transcript_hash,
    valid_id,
)
from ..retention import (
    cleared_since,
    delete_audio,
    delete_audios,
    delete_object,
    delete_session_files,
    delete_user_audio,
    owned_audio_path,
    recorded_since,
    request_sweep,
    retention,
)
from ..schemas import (
    AnswerOut,
    DeletedOut,
    GenerateIn,
    PracticeSettingsIn,
    PracticeSettingsOut,
    PracticeSettingsUpdateOut,
    ClassificationIn,
    QuestionIn,
    QuestionOut,
    ReflectionIn,
    SessionIn,
    SessionOut,
    SessionSummary,
)
from ..services import answer_coaching

router = APIRouter(prefix="/practice", tags=["practice"])

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # OpenAI 전사 API의 파일 크기 상한
AUDIO_MEDIA_TYPES = {"webm": "audio/webm", "m4a": "audio/mp4", "mp4": "audio/mp4",
                     "mp3": "audio/mpeg", "mpeg": "audio/mpeg", "mpga": "audio/mpeg",
                     "wav": "audio/wav", "ogg": "audio/ogg", "flac": "audio/flac"}


def _audio_media_type(path: str) -> str:
    extension = path.rsplit(".", 1)[-1].lower()
    if extension not in AUDIO_MEDIA_TYPES:
        raise HTTPException(415, "지원하지 않는 녹음 형식입니다. WebM, MP4, M4A, WAV 등의 오디오 파일을 사용해 주세요")
    return AUDIO_MEDIA_TYPES[extension]


def _visible_questions(user_id: str):
    followup_ids = select(PracticePrivateQuestion.question_id)
    return select(Question).where(or_(Question.user_id.is_(None), Question.user_id == user_id),
                                  Question.id.not_in(followup_ids))


def _own_session(db: Session, user_id: str, session_id: str) -> PracticeSession:
    s = valid_id(session_id) and db.scalar(
        select(PracticeSession)
        .where(PracticeSession.id == session_id, PracticeSession.user_id == user_id)
        .options(selectinload(PracticeSession.answers).selectinload(PracticeAnswer.question))
    )
    if not s:
        raise HTTPException(404, "연습 세션을 찾을 수 없습니다")
    return s


def _own_answer(db: Session, user_id: str, answer_id: str) -> PracticeAnswer:
    a = valid_id(answer_id) and db.scalar(
        select(PracticeAnswer)
        .join(PracticeSession)
        .where(PracticeAnswer.id == answer_id, PracticeSession.user_id == user_id)
        .options(selectinload(PracticeAnswer.question))
    )
    if not a:
        raise HTTPException(404, "답변을 찾을 수 없습니다")
    return a


def _own_application(db: Session, user_id: str, application_id: str | None) -> Application | None:
    if not application_id:
        return None
    application = valid_id(application_id) and db.scalar(
        select(Application).where(Application.id == application_id, Application.user_id == user_id))
    if not application:
        raise HTTPException(404, "지원 건을 찾을 수 없습니다")
    return application


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_out(s: PracticeSession) -> SessionOut:
    """세션 응답. 다시 연습할 답변과 디브리프 작업이 도는 중인지는 저장하지 않고 응답마다 다시 계산한다."""
    out = SessionOut.model_validate(s)
    if s.debrief:
        previous = s.debrief.get("input_sha256")
        if previous is None or (not settings.practice_insights_enabled and previous != debrief_fingerprint(s)):
            # Keep history whose identity cannot be checked, explicitly separate
            # from the current assessment. No migration or extra AI call.
            out.debrief = {**s.debrief, "input_status": "legacy_unverified"}
        elif previous != debrief_fingerprint(s):
            out.debrief=None
            if out.debrief_status=="done": out.debrief_status="none"
    out.redrill = weak_answers(s)
    out.debrief_running = debrief_running(s)
    return out


def _prefs(db: Session, user_id: str) -> UserSettings | None:
    return db.get(UserSettings, user_id)


def _prefs_out(p: UserSettings | None) -> PracticeSettingsOut:
    return PracticeSettingsOut(consented_at=p.consented_at if p else None, keep_audio=bool(p and p.keep_audio),
                               retention_days=settings.audio_retention_days)


NEED_CONSENT = "녹음 전에 동의가 필요합니다"
ANSWER_NOT_FOUND = "답변을 찾을 수 없습니다"


def _require_consent(db: Session, user_id: str) -> UserSettings:
    """녹음을 저장하거나 OpenAI로 보내기 전에 녹음 동의를 확인한다(업로드·전사 다시 시도 공통). 글 답변에는 필요 없다."""
    prefs = _prefs(db, user_id)
    if not prefs or not prefs.consented_at:
        raise HTTPException(403, NEED_CONSENT)
    return prefs


def _lock_answer(db: Session, answer_id: str) -> bool:
    """답변 행을 잠근다(짧은 쓰기). 세션·질문 삭제가 이 요청의 커밋을 기다리게 한다. 이미 지워졌으면 False."""
    session_id = db.scalar(select(PracticeAnswer.session_id).where(PracticeAnswer.id == answer_id))
    if not session_id or not answer_coaching.lock_session(db, session_id):
        return False
    r = db.execute(update(PracticeAnswer).where(PracticeAnswer.id == answer_id).values(order_no=PracticeAnswer.order_no),
                   execution_options={"synchronize_session": False})
    return r.rowcount == 1


def _locked_consent(db: Session, user_id: str) -> UserSettings | None:
    """동의 설정 행을 잠그고 다시 읽는다. 동의를 철회했으면 None.

    녹음 저장·전사는 오래 걸리므로 그동안 다른 탭에서 철회했을 수 있다. 잠근 뒤에는 철회가 이 요청의 커밋을 기다리고,
    철회는 동의를 먼저 저장한 다음 녹음을 지우므로 이 요청이 커밋한 녹음도 놓치지 않는다.
    """
    db.execute(update(UserSettings).where(UserSettings.user_id == user_id).values(updated_at=UserSettings.updated_at),
               execution_options={"synchronize_session": False})
    prefs = db.get(UserSettings, user_id, populate_existing=True)
    return prefs if prefs and prefs.consented_at else None


def _discard(db: Session, user_id: str, path: str) -> None:
    """이 요청이 저장했지만 답변에 연결하지 않을 녹음 파일을 지운다. 못 지우면 다음 만료 정리가 다시 지우게 표시한다."""
    if not delete_object(path):
        request_sweep(db, user_id)


def _invalidate_coaching(answer: PracticeAnswer) -> None:
    answer.ai_feedback = None
    if answer.coaching:
        answer.coaching.report = None


def _report(answer: PracticeAnswer, db: Session) -> dict:
    """답변 점검(services.answer_coaching)을 부르고 그 오류를 HTTP 응답으로 바꾼다."""
    try:
        return answer_coaching.coach(answer, db)
    except answer_coaching.NoTranscript:
        raise HTTPException(422, "답변 전사문을 입력하거나 녹음해 주세요") from None
    except answer_coaching.TranscriptChanged:
        raise HTTPException(409, "점검 중 답변이나 앞선 대화가 바뀌었어요. 현재 대화로 다시 점검해 주세요") from None


def _stt(data: bytes, filename: str, ctype: str) -> str:
    """전사문. 전사하지 못했으면(무음, 잘못된 파일, 모델·제공자 오류, 바쁨 등) 빈 문자열(실패)."""
    try:
        return stt.transcribe(data, filename, ctype).strip()
    except stt.STTError:
        return ""


def _apply_transcript(a: PracticeAnswer, transcript: str) -> None:
    if transcript != a.transcript:
        _invalidate_coaching(a)
    a.transcript = transcript
    if settings.practice_insights_enabled:
        a.recording_transcript_sha256 = recording_transcript_hash(a.recorded_at, transcript) if transcript.strip() and a.recorded_at else None
    a.stt_status = "done"


def _apply_stt(a: PracticeAnswer, transcript: str, keep_audio: bool) -> None:
    """전사 결과를 반영하고, 성공했고 원본 보관을 고르지 않았으면 원본 녹음을 바로 지운다.

    빈 전사문(무음 등)과 잘못된 응답은 실패로 본다: '전사 다시 시도'를 할 수 있게 원본을 남기고(보관 기한 뒤 자동 삭제),
    직접 적어 둔 전사문도 지우지 않는다.
    """
    if not transcript:
        a.stt_status = "failed"
        return
    _apply_transcript(a, transcript)
    if not keep_audio:
        delete_audio(a)  # 실패하면 보관 기한을 당겨 두어 다음 만료 정리가 다시 지운다


# ───────── 질문은행 ─────────

@router.get("/taxonomy")
def get_taxonomy():
    return {"enabled":settings.practice_insights_enabled,"taxonomy_version":taxonomy.TAXONOMY_VERSION,
            "question_types":taxonomy.QUESTION_TYPES,"competencies":taxonomy.COMPETENCIES,"max_competencies":3}


def _classification_filters(stmt, types, keys, match):
    try:
        return taxonomy.filter_questions(stmt,types,keys,match)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None


@router.put("/questions/{question_id}/classification", response_model=QuestionOut)
def edit_classification(question_id: str, body: ClassificationIn, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    if not settings.practice_insights_enabled:
        raise HTTPException(409,"질문 분류 기능이 활성화되지 않았습니다")
    q = valid_id(question_id) and db.scalar(_visible_questions(user_id).where(Question.id==question_id,Question.user_id==user_id))
    if not q:
        raise HTTPException(404,"수정할 수 있는 질문이 아닙니다")
    db.execute(update(Question).where(Question.id==q.id).values(text=Question.text),execution_options={"synchronize_session":False})
    db.refresh(q)
    taxonomy.assign(q,body.question_type,body.competency_keys)
    db.commit()
    return q


@router.get("/questions", response_model=list[QuestionOut])
def list_questions(
    question_type: list[str] = Query(default=[]),
    competency_key: list[str] = Query(default=[]),
    competency_match: Literal["any", "all"] = "any",
    category: str | None = None,
    job_category: str | None = None,
    source: str | None = None,
    q: str | None = None,
    user_id: str = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    stmt = _classification_filters(_visible_questions(user_id),question_type,competency_key,competency_match)
    if category:
        stmt = stmt.where(Question.category == category)
    if job_category:
        stmt = stmt.where(or_(Question.job_category == job_category, Question.job_category.is_(None)))
    if source:
        stmt = stmt.where(Question.source == source)
    if q:
        stmt = stmt.where(Question.text.contains(q))
    return db.scalars(stmt.order_by(Question.source.desc(), Question.created_at)).all()


@router.post("/questions", response_model=QuestionOut, status_code=201)
def add_question(body: QuestionIn, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    if not settings.practice_insights_enabled and (body.question_type or body.competency_keys):
        raise HTTPException(409,"질문 분류 기능이 활성화되지 않았습니다")
    q = Question(user_id=user_id, source="custom", **body.model_dump(exclude={"question_type","competency_keys"}))
    if {"question_type","competency_keys"} & body.model_fields_set:
        taxonomy.assign(q,body.question_type,body.competency_keys)
    db.add(q)
    db.commit()
    return q


@router.delete("/questions/{question_id}", status_code=204)
def delete_question(question_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    q = valid_id(question_id) and db.scalar(select(Question).where(Question.id == question_id, Question.user_id == user_id))
    if not q:
        raise HTTPException(404, "삭제할 수 있는 질문이 아닙니다(공용 질문은 삭제 불가)")
    # Supabase(supabase/schema.sql)는 질문을 지우면 답변 행(on delete cascade)과 그 코칭 행(cascade)을 지우고,
    # 꼬리질문이 가리키던 원 답변 연결은 비운다(on delete set null). 로컬 SQLite는 외래 키를 강제하지 않으므로
    # 같은 일을 여기서 한다(어디서나 같게). 행이 사라지면 만료 정리로는 원본 녹음을 찾을 수 없으므로 녹음을 먼저 지우고,
    # 하나라도 못 지우면 질문을 남긴다
    answers = db.scalars(select(PracticeAnswer).where(PracticeAnswer.question_id == q.id)).all()
    if delete_audios(answers)[1]:
        db.commit()
        raise HTTPException(502, "원본 녹음을 지우지 못해 질문을 삭제하지 않았어요. 잠시 후 다시 시도해 주세요")
    ids = [a.id for a in answers]
    by_session: dict[tuple[str, str], list[str]] = {}
    for a in answers:
        by_session.setdefault((a.session.user_id, a.session_id), []).append(a.id)
    if ids:
        db.execute(update(AnswerCoaching).where(AnswerCoaching.parent_answer_id.in_(ids)).values(parent_answer_id=None),
                   execution_options={"synchronize_session": False})
    for a in answers:
        db.delete(a)  # 코칭 행도 함께(관계 cascade)
    db.delete(q)
    db.commit()
    # 답변을 읽은 뒤 커밋된 업로드의 녹음은 위에서 지우지 못했다: 지운 답변의 파일을 경로로 찾아 지운다
    for (owner, session_id), answer_ids in by_session.items():
        delete_session_files(db, owner, session_id, answer_ids)


@router.post("/questions/generate", response_model=list[QuestionOut], status_code=201)
def generate(body: GenerateIn, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    """지원 건(또는 직접 입력한 회사·직무·자소서)으로 맞춤 질문을 만들어 질문은행에 저장."""
    company, position, job_category, essay = body.company, body.position, body.job_category, body.essay_text
    if body.application_id:
        app = _own_application(db, user_id, body.application_id)
        company, position, job_category = company or app.company, position or app.position, job_category or app.job_category
        if not essay:
            essay = coaching.essay_text(coaching.snapshot(app, body.essay_basis))
    if not (company or position or essay):
        raise HTTPException(422, "회사, 직무, 자소서 중 하나 이상이 필요합니다")
    if not settings.practice_insights_enabled and (body.question_type or body.competency_keys):
        raise HTTPException(409,"질문 분류 기능이 활성화되지 않았습니다")
    preferences={"question_type":body.question_type,"competency_keys":body.competency_keys}
    args=(company or "",position or "",essay or "",body.count)
    generated = llm.generate_questions(*args,classification_preferences=preferences) if body.question_type or body.competency_keys else llm.generate_questions(*args)
    # 이미 가진 질문과 문구가 같으면 다시 저장하지 않는다
    existing = set(db.scalars(select(Question.text).where(Question.user_id == user_id)))
    generated = [g for g in generated if g["text"] not in existing]
    rows = [
        Question(user_id=user_id, category=g["category"], job_category=job_category, text=g["text"],
                 source="generated", application_id=body.application_id)
        for g in generated
    ]
    for row, generated_question in zip(rows,generated):
        # Preferences are goals, never evidence that a generated question has those tags.
        if not {"question_type","competency_keys"} & generated_question.keys():
            continue
        try:
            classification=ClassificationIn.model_validate(generated_question)
            source=generated_question.get("tagging_source")
            if source not in ("ai","rule"):
                source="ai" if llm.available() else "rule"
            taxonomy.assign(row,classification.question_type,classification.competency_keys,source)
        except (ValueError,TypeError):
            pass  # invalid optional metadata never rejects valid core question text
    db.add_all(rows)
    db.commit()
    return rows


# ───────── 세션(자유 연습 / 모의시험) ─────────

@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(body: SessionIn, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    application = _own_application(db, user_id, body.application_id)
    context = coaching.snapshot(application, body.essay_basis, body.job_description)
    if body.question_ids:
        ids = [qid for qid in body.question_ids if valid_id(qid)]
        found = {q.id: q for q in db.scalars(_visible_questions(user_id).where(Question.id.in_(ids)))} if ids else {}
        missing = [qid for qid in body.question_ids if qid not in found]
        if missing:
            raise HTTPException(404, f"질문을 찾을 수 없습니다: {missing}")
        picked = [found[qid] for qid in body.question_ids]
        if body.application_id and any(q.application_id and q.application_id != body.application_id for q in picked):
            raise HTTPException(422, "다른 지원 건에서 만든 질문이 포함되어 있어요. 지원 건과 질문을 맞춰 주세요")
    else:
        stmt = _classification_filters(_visible_questions(user_id),body.question_types,body.competency_keys,body.competency_match)
        if body.categories:
            stmt = stmt.where(Question.category.in_(body.categories))
        if body.application_id:
            stmt = stmt.where(or_(Question.application_id == body.application_id, Question.user_id.is_(None)))
        if body.job_category:
            stmt = stmt.where(or_(Question.job_category == body.job_category, Question.job_category.is_(None)))
        pool = list(db.scalars(stmt))
        if not pool:
            raise HTTPException(422, "조건에 맞는 질문이 없습니다")
        # 맞춤(생성·직접 추가) 질문을 먼저 뽑고 나머지를 공용 질문에서 채운다
        own = [q for q in pool if q.user_id]
        bank = [q for q in pool if not q.user_id]
        random.shuffle(own)
        random.shuffle(bank)
        picked = (own + bank)[: body.count]
        # 모의시험은 실제 면접처럼 자기소개로 시작
        if body.mode == "mock":
            intro = next((q for q in bank if "자기소개" in q.text), None)
            if intro:
                rest = [q for q in picked if q is not intro]
                picked = [intro, *rest][: body.count]
    title = body.title or (
        f"모의 면접 {datetime.now():%m/%d %H:%M}" if body.mode == "mock" else f"자유 연습 {datetime.now():%m/%d %H:%M}"
    )
    s = PracticeSession(user_id=user_id, mode=body.mode, title=title, application_id=body.application_id,
                        prep_sec=body.prep_sec, answer_sec=body.answer_sec)
    if settings.practice_insights_enabled:
        # Serialize capture against classification edits. Stable order avoids PG deadlocks.
        for question in sorted({q.id:q for q in picked}.values(),key=lambda q:q.id):
            db.execute(update(Question).where(Question.id==question.id).values(text=Question.text),execution_options={"synchronize_session":False})
            db.refresh(question)
        if not body.question_ids:
            ids={q.id for q in picked}
            current=set(db.scalars(stmt.with_only_columns(Question.id).where(Question.id.in_(ids))))
            if current!=ids:
                db.rollback()
                raise HTTPException(409,"질문 분류가 선택 중 바뀌었어요. 조건을 확인하고 다시 시작해 주세요")
    s.answers = [PracticeAnswer(question=q, order_no=i + 1, **({"question_classification":taxonomy.capture(q)} if settings.practice_insights_enabled else {})) for i, q in enumerate(picked)]
    s.context = PracticeContext(snapshot=context, followups_enabled=body.followups_enabled)
    db.add(s)
    db.commit()
    return _session_out(_own_session(db, user_id, s.id))


@router.get("/sessions", response_model=list[SessionSummary])
def list_sessions(question_type: list[str] = Query(default=[]), competency_key: list[str] = Query(default=[]),
                  competency_match: Literal["any","all"] = "any",
                  user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    try:
        taxonomy.validate_keys(question_type,competency_key)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None
    sessions = db.scalars(
        select(PracticeSession)
        .where(PracticeSession.user_id == user_id)
        .options(selectinload(PracticeSession.answers))
        .order_by(PracticeSession.created_at.desc())
    ).all()
    out = []
    for s in sessions:
        keys={k for a in s.answers for k in (a.question_classification or {}).get("competency_keys",[])}
        types={(a.question_classification or {}).get("question_type") for a in s.answers}
        if question_type and not types.intersection(question_type):
            continue
        if competency_key and not (set(competency_key)<=keys if competency_match=="all" else keys.intersection(competency_key)):
            continue
        ratings = [a.self_rating for a in s.answers if a.self_rating]
        out.append(SessionSummary(
            id=s.id, mode=s.mode, title=s.title, created_at=s.created_at, finished_at=s.finished_at,
            answer_count=len(s.answers), recorded_count=sum(1 for a in s.answers if a.recorded_at),
            avg_rating=round(sum(ratings) / len(ratings), 2) if ratings else None,
            competency_keys=sorted({k for a in s.answers for k in (a.question_classification or {}).get("competency_keys",[])}),
            classification_missing_count=sum(a.question_classification is None for a in s.answers),
        ))
    return out


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    return _session_out(_own_session(db, user_id, session_id))


@router.post("/sessions/{session_id}/finish", response_model=SessionOut)
def finish_session(
    session_id: str,
    background: BackgroundTasks,
    user_id: str = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """세션을 끝내고 자동 디브리프(답변 점검 + 요약)를 시작한다.

    이미 도는 작업이 있으면 하나 더 붙이지 않고, 그 작업이 결과를 쓰기 전에 한 바퀴 더 돌아 마지막 답변까지 담게 한다.
    """
    s = _own_session(db, user_id, session_id)
    s.finished_at = s.finished_at or _now()
    start = prepare_debrief(db, s)
    db.commit()
    if start:
        background.add_task(run_debrief, s.id)
    return _session_out(s)


@router.post("/sessions/{session_id}/debrief", response_model=SessionOut)
def regenerate_debrief(
    session_id: str,
    background: BackgroundTasks,
    user_id: str = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """디브리프를 (다시) 만든다. 키가 없으면 'unavailable', 전사문이 없으면 'none'을 바로 돌려준다.

    이미 도는 작업이 있으면 하나 더 붙이지 않고, 그 작업이 결과를 쓰기 전에 한 바퀴 더 돌게 한다.
    """
    s = _own_session(db, user_id, session_id)
    start = prepare_debrief(db, s)
    db.commit()
    if start:
        background.add_task(run_debrief, s.id)
    return _session_out(s)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    s = _own_session(db, user_id, session_id)
    # 행이 사라지면 만료 정리로도 못 지우므로 원본 녹음을 먼저 지운다. 하나라도 못 지우면 세션을 남긴다
    if delete_audios(s.answers)[1]:
        db.commit()  # 지운 것은 반영하고, 못 지운 것은 다음 만료 정리가 다시 지운다
        raise HTTPException(502, "원본 녹음을 지우지 못해 세션을 삭제하지 않았어요. 잠시 후 다시 시도해 주세요")
    db.delete(s)
    db.commit()
    # 답변을 읽은 뒤 커밋된 업로드의 녹음은 위에서 지우지 못했지만 그 행은 함께 지워졌다: 세션 폴더에 남은 파일도 지운다
    delete_session_files(db, user_id, session_id)


# ───────── 녹음 동의·개인정보 ─────────

@router.get("/settings", response_model=PracticeSettingsOut)
def get_settings(user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    return _prefs_out(_prefs(db, user_id))


@router.put("/settings", response_model=PracticeSettingsUpdateOut)
def update_settings(body: PracticeSettingsIn, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    """동의·철회와 원본 보관 설정. 철회하면 원본 녹음을 모두 지우고(전사문·기록은 유지) 새 녹음을 막는다.

    못 지운 녹음 수는 failed로 알리고, 그 녹음은 다음 만료 정리 때 다시 지운다.
    """
    p = _prefs(db, user_id)
    if not p:
        p = UserSettings(user_id=user_id, keep_audio=False)
        db.add(p)
    data = body.model_dump(exclude_unset=True)
    deleted = failed = 0
    unchecked = False
    if data.get("consent") is True:
        p.consented_at = p.consented_at or _now()
    elif data.get("consent") is False:
        p.consented_at = None
    if data.get("keep_audio") is not None:
        p.keep_audio = data["keep_audio"]  # 이미 있는 녹음의 보관 기한은 바꾸지 않는다
    # 철회는 먼저 저장해 올리는 중인 녹음도 바로 막는다(업로드는 커밋 직전에 동의를 다시 읽는다). 그다음 녹음을 지운다
    db.commit()
    if data.get("consent") is False:
        r = delete_user_audio(db, user_id)
        db.commit()
        if r.sweep:
            request_sweep(db, user_id)
        deleted, failed, unchecked = r.deleted, r.failed, r.unchecked
    return PracticeSettingsUpdateOut(**_prefs_out(p).model_dump(), deleted=deleted, failed=failed, unchecked=unchecked)


@router.delete("/recordings", response_model=DeletedOut)
def delete_all_recordings(user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    """내 원본 녹음을 지금 모두 지운다(행이 가리키지 않는 내 폴더의 파일까지). 전사문과 세션 기록은 남는다.

    못 지운 것은 failed로 알리고 다음 만료 정리 때 다시 지운다.
    """
    r = delete_user_audio(db, user_id)
    db.commit()
    if r.sweep:
        request_sweep(db, user_id)
    return DeletedOut(deleted=r.deleted, failed=r.failed, unchecked=r.unchecked)


# ───────── 녹음·전사·회고 ─────────

@router.post("/answers/{answer_id}/audio", response_model=AnswerOut)
def upload_audio(
    answer_id: str,
    file: UploadFile = File(...),
    duration_sec: float | None = Form(default=None),
    user_id: str = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """녹음을 저장하고 곧바로 전사한다. 전사에 성공하면 원본은 지우고(보관을 고르지 않았을 때) 전사문만 남긴다.

    전사가 실패하면 다시 시도할 수 있게 원본을 남기되, 보관 기한이 지나면 자동으로 지운다.
    업로드마다 다른 경로({user_id}/{session_id}/{answer_id}.{토큰}.{확장자})에 저장하고, 답변에 연결한 뒤에 이전 녹음 파일을
    지운다. 그래서 겹친 업로드가 서로의 파일을 덮어쓰거나 지우지 않는다. 같은 답변에 업로드가 겹치면 나중에 시작한 녹음이
    이기고, 먼저 시작해 늦게 끝난 업로드는 409로 버린다(그 파일만 지운다).
    저장·전사하는 동안 원본 녹음을 모두 지웠으면(모두 지우기) 녹음은 지운 것으로 저장하고 전사문은 남긴다.
    """
    started = _now()
    a = _own_answer(db, user_id, answer_id)
    _require_consent(db, user_id)
    # A synchronous route runs blocking storage/STT calls in FastAPI's worker pool.
    # Read at most the limit plus one byte so an oversized upload is bounded.
    data = file.file.read(MAX_AUDIO_BYTES + 1)
    if not data:
        raise HTTPException(422, "빈 녹음 파일입니다")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "녹음 파일이 25MB를 넘습니다")
    ext = (file.filename or "rec.webm").rsplit(".", 1)[-1].lower()
    ctype = _audio_media_type(f"recording.{ext}")
    path = f"{user_id}/{a.session_id}/{a.id}.{secrets.token_hex(6)}.{ext}"
    storage.save(path, data, ctype)
    can_stt = stt.available()
    transcript = _stt(data, f"{a.id}.{ext}", ctype) if can_stt else ""
    # 저장·전사하는 동안 세션·질문이 지워졌거나, 동의를 철회했거나, 더 나중에 시작한 녹음이 저장됐을 수 있다:
    # 잠그고 다시 확인한 뒤에 반영한다
    if not _lock_answer(db, a.id):
        db.rollback()
        _discard(db, user_id, path)
        raise HTTPException(404, ANSWER_NOT_FOUND)
    prefs = _locked_consent(db, user_id)
    db.refresh(a)
    if recorded_since(a, started):
        # 이 업로드보다 나중에 시작한 녹음이 이미 저장됐다: 그 녹음과 전사문을 덮지 않는다
        db.commit()
        _discard(db, user_id, path)
        raise HTTPException(409, "더 나중에 녹음한 답변이 이미 저장됐어요. 새로고침해 확인해 주세요")
    previous = owned_audio_path(a)  # 이번 녹음을 연결한 뒤 지울 이전 녹음 파일(그사이 지웠으면 None)
    # 저장·전사하는 동안 원본 녹음을 모두 지웠다(전체 삭제는 아직 행이 가리키지 않는 이 파일도 지우고 센다):
    # 그 삭제 뒤에 커밋한 것과 같게 녹음을 지운 것으로 저장한다
    deleted = prefs is not None and cleared_since(prefs, started)
    if prefs is None and not transcript:
        # 철회했고 전사문도 없다: 이번 녹음은 없던 일로 하고 파일만 지운다(이전 녹음은 철회가 지운다)
        db.commit()
        _discard(db, user_id, path)
        raise HTTPException(403, NEED_CONSENT)
    # 녹음한 시각은 업로드를 시작한 시각이다(겹친 업로드 중 어느 녹음이 나중인지 이 값으로 가린다)
    now = _now()
    a.audio_path, a.duration_sec = path, duration_sec
    a.recorded_at, a.audio_expires_at, a.audio_deleted_at = started, now + retention(), None
    _invalidate_coaching(a)
    a.transcript = None
    if settings.practice_insights_enabled:
        a.recording_transcript_sha256 = None
    if prefs is None:
        # 철회했다: 원본은 지우고 이미 얻은 전사문만 남긴다(철회해도 전사문은 남는 것과 같다)
        _apply_transcript(a, transcript)
        delete_audio(a)  # 못 지우면 보관 기한을 당겨 두어 다음 만료 정리가 지운다
        db.commit()
        _drop_previous(db, user_id, previous, path)
        raise HTTPException(403, NEED_CONSENT)
    if not can_stt:
        a.stt_status = "unavailable"
    else:
        _apply_stt(a, transcript, prefs.keep_audio)
    if deleted:
        delete_audio(a)  # 전사문은 남기고 파일이 아직 있으면 지운다. 못 지우면 보관 기한을 당겨 다음 만료 정리가 지운다
    db.commit()
    _drop_previous(db, user_id, previous, path)
    return a


def _drop_previous(db: Session, user_id: str, previous: str | None, path: str) -> None:
    """새 녹음을 연결·커밋한 뒤 이전 녹음 파일을 지운다. 이제 어떤 행도 가리키지 않으므로, 못 지우면 고아 파일로
    표시해 다음 만료 정리가 지우게 한다."""
    if previous and previous != path:
        _discard(db, user_id, previous)


def _load_audio(path: str) -> bytes | None:
    """녹음 내용(없으면 None). 저장소 오류는 '녹음 없음'이 아니라 502로 알린다."""
    try:
        return storage.load(path)
    except storage.StorageError as e:
        raise HTTPException(502, "녹음 저장소에 연결하지 못했어요. 잠시 후 다시 시도해 주세요") from e


@router.get("/answers/{answer_id}/audio")
def download_audio(answer_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    a = _own_answer(db, user_id, answer_id)
    if a.audio_deleted_at:
        raise HTTPException(404, "원본 녹음은 삭제됐어요")
    path = owned_audio_path(a)
    data = _load_audio(path) if path else None
    if data is None:
        raise HTTPException(404, "녹음이 없습니다")
    return Response(content=data, media_type=_audio_media_type(path))


@router.delete("/answers/{answer_id}/audio", response_model=AnswerOut)
def delete_answer_audio(answer_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    """이 답변의 원본 녹음만 지운다. 전사문은 남는다."""
    a = _own_answer(db, user_id, answer_id)
    if a.audio_path and not delete_audio(a):
        db.commit()  # 보관 기한을 당겨 둔 것을 저장: 다음 만료 정리가 다시 지운다
        raise HTTPException(502, "녹음을 지우지 못했어요. 잠시 뒤 자동으로 다시 지워요")
    db.commit()
    return a


@router.post("/answers/{answer_id}/transcribe", response_model=AnswerOut)
def retry_transcribe(answer_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    """원본 녹음을 다시 전사한다. 원본 보관은 지금 설정을 따른다.

    다시 전사할 수 없는 경우(원본 삭제, 녹음 없음, 자동 전사 꺼짐)는 동의보다 먼저 알린다: 동의해도 할 수 있는 일이 없다.
    전사하는 동안 원본을 지웠으면 이미 얻은 전사문은 남긴다(동의 철회와 같다).
    """
    started = _now()
    a = _own_answer(db, user_id, answer_id)
    if a.audio_deleted_at:
        raise HTTPException(404, "원본 녹음은 삭제됐어요")
    path = owned_audio_path(a)
    if not path:
        raise HTTPException(404, "녹음이 없습니다")
    if not stt.available():
        raise HTTPException(503, stt.unavailable_reason())
    ctype = _audio_media_type(path)
    data = _load_audio(path)
    if data is None:
        raise HTTPException(404, "녹음이 없습니다")
    _require_consent(db, user_id)  # 녹음을 다시 전사하므로(제공자가 openai면 OpenAI로 보낸다) 업로드와 같은 동의가 필요하다
    recorded_at = a.recorded_at
    transcript = _stt(data, path.rsplit("/", 1)[-1], ctype)
    # 전사하는 동안 답변이 지워졌거나, 동의를 철회했거나, 녹음이 바뀌었을 수 있다: 잠그고 다시 확인한 뒤에 반영한다
    if not _lock_answer(db, a.id):
        db.rollback()
        raise HTTPException(404, ANSWER_NOT_FOUND)
    prefs = _locked_consent(db, user_id)
    db.refresh(a)
    if a.recorded_at != recorded_at:
        db.commit()
        raise HTTPException(409, "전사하는 동안 새 녹음이 저장됐어요. 새 녹음으로 확인해 주세요")
    if prefs is None:
        # 철회했다: 원본은 철회가 지운다(아직 남았으면 여기서 지운다). 이미 얻은 전사문만 남긴다
        if a.audio_path:
            delete_audio(a)
        if transcript:
            _apply_transcript(a, transcript)
        db.commit()
        raise HTTPException(403, NEED_CONSENT)
    if a.audio_path != path or cleared_since(prefs, started):
        # 전사하는 동안 원본을 지웠다(녹음 삭제, 원본 녹음 모두 지우기): 이미 얻은 전사문은 남긴다
        if a.audio_path:  # 모두 지우기가 이 행을 아직 커밋하지 않았다
            delete_audio(a)
        if not transcript:
            db.commit()
            raise HTTPException(404, "원본 녹음은 삭제됐어요")
        _apply_transcript(a, transcript)
        db.commit()
        return a
    _apply_stt(a, transcript, prefs.keep_audio)
    db.commit()
    return a


@router.patch("/answers/{answer_id}", response_model=AnswerOut)
def reflect(answer_id: str, body: ReflectionIn, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    a = _own_answer(db, user_id, answer_id)
    if not answer_coaching.lock_session(db, a.session_id):
        raise HTTPException(404, ANSWER_NOT_FOUND)
    db.expire_all()
    a = _own_answer(db, user_id, answer_id)
    if body.input_mode == "text" and a.recorded_at and not settings.practice_insights_enabled:
        from ..services.recording_identity import clear_optional_recording_identity
        clear_optional_recording_identity(db, a.id)
    if settings.practice_insights_enabled and a.recorded_at and "transcript" in body.model_fields_set:
        if body.input_mode == "text":
            a.recording_transcript_sha256 = ""  # typed replacement is never a transcription
        elif a.recording_transcript_sha256 is None:
            # With STT off, the existing UI asks users to enter their first transcription.
            # Later changes (including clearing it) never acquire a fresh identity.
            if not (a.transcript or "").strip() and (body.transcript or "").strip():
                a.recording_transcript_sha256 = recording_transcript_hash(a.recorded_at, body.transcript)
            elif body.transcript != a.transcript:
                a.recording_transcript_sha256 = ""
    if "transcript" in body.model_fields_set and body.transcript != a.transcript:
        _invalidate_coaching(a)
    for k, v in body.model_dump(exclude_unset=True, exclude={"input_mode"}).items():
        setattr(a, k, v)
    db.commit()
    return a


@router.get("/rubric")
def get_rubric():
    """코칭 기준(구체성·질문 적합성·제출본 연결)과 앵커. 화면의 '채점 기준 보기'에 쓴다."""
    return coaching.RUBRIC


@router.post("/answers/{answer_id}/coach", response_model=AnswerOut)
def coach_answer(answer_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    a = _own_answer(db, user_id, answer_id)
    _report(a, db)
    db.commit()
    return a


@router.post("/answers/{answer_id}/followup", response_model=SessionOut, status_code=201)
def followup(answer_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    a = _own_answer(db, user_id, answer_id)
    s = a.session
    if s.finished_at:
        raise HTTPException(409, "종료한 면접입니다. 회고에서 다시 연습해 주세요")
    if not a.transcript or not a.transcript.strip():
        raise HTTPException(422, "답변 전사문을 입력하거나 녹음해 주세요")
    if not s.followups_enabled:
        raise HTTPException(409, "이 세션은 꼬리질문을 사용하지 않도록 설정되어 있습니다")
    if a.parent_answer_id:
        raise HTTPException(409, "꼬리질문은 원 질문당 한 번 진행합니다")
    if db.scalar(select(AnswerCoaching).where(AnswerCoaching.parent_answer_id == a.id)):
        return _session_out(_own_session(db, user_id, s.id))
    if not answer_coaching.current_report(a):
        _report(a, db)
        db.commit()
    # A short database write serializes insertion on SQLite and PostgreSQL alike.
    # No external model request is made while holding this session lock.
    session_id = s.id
    answer_coaching.lock_session(db, session_id)
    db.expire_all()
    a = _own_answer(db, user_id, answer_id)
    s = a.session
    if s.finished_at:
        raise HTTPException(409, "종료한 면접입니다. 회고에서 다시 연습해 주세요")
    if db.scalar(select(AnswerCoaching).where(AnswerCoaching.parent_answer_id == a.id)):
        return _session_out(_own_session(db, user_id, s.id))
    report = answer_coaching.current_report(a)
    if not report:
        raise HTTPException(409, "답변이나 앞선 대화가 바뀌었어요. 현재 대화로 다시 점검해 주세요")
    suggestion = report["followup"]
    q = Question(user_id=user_id, category=a.question.category, source="generated",
                 application_id=s.application_id, job_category=a.question.job_category, text=suggestion["text"],
                 private_scope=PracticePrivateQuestion())
    if settings.practice_insights_enabled and a.question_classification:
        taxonomy.assign(q,a.question_classification["question_type"],a.question_classification.get("competency_keys",[]),"rule")
    child = PracticeAnswer(question=q, order_no=a.order_no + 1,
                           **({"question_classification":taxonomy.recapture(a.question_classification,"followup")} if settings.practice_insights_enabled else {}),
                           coaching=AnswerCoaching(parent_answer_id=a.id, followup_reason=suggestion["reason"]))
    for later in s.answers:
        if later.order_no > a.order_no:
            later.order_no += 1
    s.answers.append(child)
    try:
        db.commit()
    except IntegrityError:
        # The unique parent key also makes concurrent/retried clicks idempotent.
        db.rollback()
        if not db.scalar(select(AnswerCoaching).where(AnswerCoaching.parent_answer_id == answer_id)):
            raise
    db.expire_all()
    return _session_out(_own_session(db, user_id, s.id))


@router.post("/sessions/{session_id}/redrill", response_model=SessionOut, status_code=201)
def redrill(session_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    original = _own_session(db, user_id, session_id)
    targets = []
    picked = []
    # 코칭에 '보완'이 있거나 자기평가가 1~2점인 답변(세션 순서대로 최대 20개). 화면의 목록과 같은 규칙이다
    for a, weak, low in drill_picks(original):
        picked.append(a)
        report = answer_coaching.current_report(a)
        targets.append({"answer_id": a.id, "question_id": a.question_id,
                        "focus": drill_focus(weak, low),
                        "next_action": report["next_action"] if report else
                                       f"지난번 자기평가 {low}점이었던 답변이에요. 아쉬웠던 점을 떠올리며 다시 답해 보세요."})
    if not picked:
        raise HTTPException(422, "먼저 답변을 점검하거나 자기평가를 남겨 주세요. "
                                 "보완 항목이 있거나 자기평가가 1~2점인 답변을 모아 다시 연습합니다")
    frozen = deepcopy(original.context_snapshot or {})
    frozen.update({"origin_session_id": original.id, "drill_targets": targets})
    s = PracticeSession(user_id=user_id, mode="free", title=f"보완 연습 · {original.title}"[:200],
                        application_id=original.application_id, prep_sec=original.prep_sec, answer_sec=original.answer_sec,
                        context=PracticeContext(snapshot=frozen, followups_enabled=True))
    s.answers = [PracticeAnswer(question=a.question, order_no=i + 1, **({"question_classification":taxonomy.recapture(a.question_classification)} if settings.practice_insights_enabled else {})) for i, a in enumerate(picked)]
    db.add(s)
    db.commit()
    return _session_out(_own_session(db, user_id, s.id))


@router.post("/answers/{answer_id}/feedback", response_model=AnswerOut)
def ai_feedback(answer_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    a = _own_answer(db, user_id, answer_id)
    if not a.transcript:
        raise HTTPException(422, "전사문이 있어야 피드백을 받을 수 있습니다")
    if not llm.available():
        raise HTTPException(503, "OPENAI_API_KEY가 설정되지 않아 AI 피드백을 쓸 수 없습니다")
    try:
        a.ai_feedback = llm.feedback(a.question.text, a.transcript, a.duration_sec)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"AI 피드백 요청 실패: {e}") from e
    db.commit()
    return a
