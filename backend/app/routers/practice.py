"""② Practice: 질문은행·맞춤 질문, 모의시험 세션, 녹음·전사, 회고."""
import random
from copy import deepcopy
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .. import coaching, llm, storage
from ..auth import current_user_id
from ..db import get_db
from ..models import AnswerCoaching, Application, PracticeAnswer, PracticeContext, PracticePrivateQuestion, PracticeSession, Question
from ..schemas import (
    AnswerOut,
    GenerateIn,
    QuestionIn,
    QuestionOut,
    ReflectionIn,
    SessionIn,
    SessionOut,
    SessionSummary,
)

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
    s = db.scalar(
        select(PracticeSession)
        .where(PracticeSession.id == session_id, PracticeSession.user_id == user_id)
        .options(selectinload(PracticeSession.answers).selectinload(PracticeAnswer.question))
    )
    if not s:
        raise HTTPException(404, "연습 세션을 찾을 수 없습니다")
    return s


def _own_answer(db: Session, user_id: str, answer_id: str) -> PracticeAnswer:
    a = db.scalar(
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
    application = db.scalar(select(Application).where(Application.id == application_id, Application.user_id == user_id))
    if not application:
        raise HTTPException(404, "지원 건을 찾을 수 없습니다")
    return application


def _invalidate_coaching(answer: PracticeAnswer) -> None:
    answer.ai_feedback = None
    if answer.coaching:
        answer.coaching.report = None


def _report(answer: PracticeAnswer, db: Session) -> dict:
    if not answer.transcript or not answer.transcript.strip():
        raise HTTPException(422, "답변 전사문을 입력하거나 녹음해 주세요")
    history = [{"question": a.question.text, "answer": a.transcript}
               for a in answer.session.answers if a.order_no < answer.order_no and a.transcript]
    transcript = answer.transcript
    report = coaching.build_report(answer.question.text, transcript, answer.session.context_snapshot or {}, history)
    # Lock only after the external request. An edit while it ran must not revive stale evidence.
    unchanged = db.execute(update(PracticeAnswer).where(PracticeAnswer.id == answer.id,
                           PracticeAnswer.transcript == transcript).values(transcript=PracticeAnswer.transcript),
                           execution_options={"synchronize_session": False})
    if unchanged.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "점검 중 답변이 바뀌었어요. 수정한 답변으로 다시 점검해 주세요")
    # Another request may have created this row while the model was running.
    saved = db.get(AnswerCoaching, answer.id, populate_existing=True)
    answer.coaching = saved if saved is not None else AnswerCoaching()
    answer.coaching.report = report
    return answer.coaching.report


# ───────── 질문은행 ─────────

@router.get("/questions", response_model=list[QuestionOut])
def list_questions(
    category: str | None = None,
    job_category: str | None = None,
    source: str | None = None,
    q: str | None = None,
    user_id: str = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    stmt = _visible_questions(user_id)
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
    q = Question(user_id=user_id, source="custom", **body.model_dump())
    db.add(q)
    db.commit()
    return q


@router.delete("/questions/{question_id}", status_code=204)
def delete_question(question_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    q = db.scalar(select(Question).where(Question.id == question_id, Question.user_id == user_id))
    if not q:
        raise HTTPException(404, "삭제할 수 있는 질문이 아닙니다(공용 질문은 삭제 불가)")
    db.delete(q)
    db.commit()


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
    generated = llm.generate_questions(company or "", position or "", essay or "", body.count)
    # 이미 가진 질문과 문구가 같으면 다시 저장하지 않는다
    existing = set(db.scalars(select(Question.text).where(Question.user_id == user_id)))
    generated = [g for g in generated if g["text"] not in existing]
    rows = [
        Question(user_id=user_id, category=g["category"], job_category=job_category, text=g["text"],
                 source="generated", application_id=body.application_id)
        for g in generated
    ]
    db.add_all(rows)
    db.commit()
    return rows


# ───────── 세션(자유 연습 / 모의시험) ─────────

@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(body: SessionIn, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    application = _own_application(db, user_id, body.application_id)
    context = coaching.snapshot(application, body.essay_basis, body.job_description)
    if body.question_ids:
        found = {q.id: q for q in db.scalars(_visible_questions(user_id).where(Question.id.in_(body.question_ids)))}
        missing = [qid for qid in body.question_ids if qid not in found]
        if missing:
            raise HTTPException(404, f"질문을 찾을 수 없습니다: {missing}")
        picked = [found[qid] for qid in body.question_ids]
        if body.application_id and any(q.application_id and q.application_id != body.application_id for q in picked):
            raise HTTPException(422, "다른 지원 건에서 만든 질문이 포함되어 있어요. 지원 건과 질문을 맞춰 주세요")
    else:
        stmt = _visible_questions(user_id)
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
    s.answers = [PracticeAnswer(question=q, order_no=i + 1) for i, q in enumerate(picked)]
    s.context = PracticeContext(snapshot=context, followups_enabled=body.followups_enabled)
    db.add(s)
    db.commit()
    return _own_session(db, user_id, s.id)


@router.get("/sessions", response_model=list[SessionSummary])
def list_sessions(user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    sessions = db.scalars(
        select(PracticeSession)
        .where(PracticeSession.user_id == user_id)
        .options(selectinload(PracticeSession.answers))
        .order_by(PracticeSession.created_at.desc())
    ).all()
    out = []
    for s in sessions:
        ratings = [a.self_rating for a in s.answers if a.self_rating]
        out.append(SessionSummary(
            id=s.id, mode=s.mode, title=s.title, created_at=s.created_at, finished_at=s.finished_at,
            answer_count=len(s.answers), recorded_count=sum(1 for a in s.answers if a.audio_path),
            avg_rating=round(sum(ratings) / len(ratings), 2) if ratings else None,
        ))
    return out


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    return _own_session(db, user_id, session_id)


@router.post("/sessions/{session_id}/finish", response_model=SessionOut)
def finish_session(session_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    s = _own_session(db, user_id, session_id)
    s.finished_at = s.finished_at or datetime.now(timezone.utc)
    db.commit()
    return s


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    db.delete(_own_session(db, user_id, session_id))
    db.commit()


# ───────── 녹음·전사·회고 ─────────

@router.post("/answers/{answer_id}/audio", response_model=AnswerOut)
def upload_audio(
    answer_id: str,
    file: UploadFile = File(...),
    duration_sec: float | None = Form(default=None),
    user_id: str = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """녹음을 저장하고 곧바로 전사한다. 전사가 실패해도 녹음은 남는다."""
    a = _own_answer(db, user_id, answer_id)
    # A synchronous route runs blocking storage/STT calls in FastAPI's worker pool.
    # Read at most the limit plus one byte so an oversized upload is bounded.
    data = file.file.read(MAX_AUDIO_BYTES + 1)
    if not data:
        raise HTTPException(422, "빈 녹음 파일입니다")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "녹음 파일이 25MB를 넘습니다")
    ext = (file.filename or "rec.webm").rsplit(".", 1)[-1].lower()
    ctype = _audio_media_type(f"recording.{ext}")
    path = f"{user_id}/{a.session_id}/{a.id}.{ext}"
    storage.save(path, data, ctype)
    a.audio_path, a.duration_sec = path, duration_sec
    _invalidate_coaching(a)
    a.transcript = None
    if not llm.available():
        a.stt_status = "unavailable"
    else:
        try:
            a.transcript = llm.transcribe(data, f"{a.id}.{ext}", ctype)
            a.stt_status = "done"
        except (httpx.HTTPError, llm.TranscriptionError):
            a.stt_status = "failed"
    db.commit()
    return a


@router.get("/answers/{answer_id}/audio")
def download_audio(answer_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    a = _own_answer(db, user_id, answer_id)
    data = storage.load(a.audio_path) if a.audio_path else None
    if data is None:
        raise HTTPException(404, "녹음이 없습니다")
    return Response(content=data, media_type=_audio_media_type(a.audio_path))


@router.post("/answers/{answer_id}/transcribe", response_model=AnswerOut)
def retry_transcribe(answer_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    a = _own_answer(db, user_id, answer_id)
    if not llm.available():
        raise HTTPException(503, "OPENAI_API_KEY가 설정되지 않아 전사를 할 수 없습니다")
    data = storage.load(a.audio_path) if a.audio_path else None
    if data is None:
        raise HTTPException(404, "녹음이 없습니다")
    try:
        transcript = llm.transcribe(data, a.audio_path.rsplit("/", 1)[-1], _audio_media_type(a.audio_path))
        if transcript != a.transcript:
            _invalidate_coaching(a)
        a.transcript = transcript
        a.stt_status = "done"
    except (httpx.HTTPError, llm.TranscriptionError):
        a.stt_status = "failed"
    db.commit()
    return a


@router.patch("/answers/{answer_id}", response_model=AnswerOut)
def reflect(answer_id: str, body: ReflectionIn, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    a = _own_answer(db, user_id, answer_id)
    if "transcript" in body.model_fields_set and body.transcript != a.transcript:
        _invalidate_coaching(a)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    db.commit()
    return a


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
        return _own_session(db, user_id, s.id)
    if not a.coaching_report:
        _report(a, db)
        db.commit()
    # A short database write serializes insertion on SQLite and PostgreSQL alike.
    # No external model request is made while holding this session lock.
    session_id = s.id
    db.execute(update(PracticeSession).where(PracticeSession.id == session_id).values(title=PracticeSession.title),
               execution_options={"synchronize_session": False})
    db.expire_all()
    a = _own_answer(db, user_id, answer_id)
    s = a.session
    if s.finished_at:
        raise HTTPException(409, "종료한 면접입니다. 회고에서 다시 연습해 주세요")
    if db.scalar(select(AnswerCoaching).where(AnswerCoaching.parent_answer_id == a.id)):
        return _own_session(db, user_id, s.id)
    report = a.coaching_report
    if not report:
        raise HTTPException(409, "답변이 바뀌었어요. 수정한 답변으로 다시 점검해 주세요")
    suggestion = report["followup"]
    q = Question(user_id=user_id, category=a.question.category, source="generated",
                 application_id=s.application_id, job_category=a.question.job_category, text=suggestion["text"],
                 private_scope=PracticePrivateQuestion())
    child = PracticeAnswer(question=q, order_no=a.order_no + 1,
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
    return _own_session(db, user_id, s.id)


@router.post("/sessions/{session_id}/redrill", response_model=SessionOut, status_code=201)
def redrill(session_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    original = _own_session(db, user_id, session_id)
    targets = []
    picked = []
    for a in original.answers:
        weak = [c for c in (a.coaching_report or {}).get("criteria", []) if c["status"] == "보완"]
        if weak:
            picked.append(a)
            targets.append({"answer_id": a.id, "question_id": a.question_id,
                            "focus": [c["label"] for c in weak],
                            "next_action": a.coaching_report["next_action"]})
        if len(picked) == 20:
            break
    if not picked:
        raise HTTPException(422, "먼저 답변을 점검해 주세요. 보완 항목이 있는 답변을 모아 다시 연습합니다")
    frozen = deepcopy(original.context_snapshot or {})
    frozen.update({"origin_session_id": original.id, "drill_targets": targets})
    s = PracticeSession(user_id=user_id, mode="free", title=f"보완 연습 · {original.title}"[:200],
                        application_id=original.application_id, prep_sec=original.prep_sec, answer_sec=original.answer_sec,
                        context=PracticeContext(snapshot=frozen, followups_enabled=True))
    s.answers = [PracticeAnswer(question=a.question, order_no=i + 1) for i, a in enumerate(picked)]
    db.add(s)
    db.commit()
    return _own_session(db, user_id, s.id)


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
