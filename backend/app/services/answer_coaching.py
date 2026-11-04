"""답변 하나를 점검하고 보고서를 저장한다. /coach·꼬리질문(라우터)과 세션 디브리프(백그라운드 작업)가 함께 쓴다."""
from sqlalchemy import update
from sqlalchemy.orm import Session

from .. import coaching
from ..models import AnswerCoaching, PracticeAnswer


class NoTranscript(Exception):
    """점검할 전사문이 없다(라우터는 422)."""


class TranscriptChanged(Exception):
    """점검하는 동안 전사문이 바뀌었다. 보고서는 버렸고 트랜잭션은 되돌렸다(라우터는 409)."""


def coach(answer: PracticeAnswer, db: Session) -> dict:
    """보고서를 만들어 답변에 붙인다(커밋은 호출한 쪽에서). 앞 순서 답변을 대화 맥락으로 넘긴다.

    외부 모델 요청이 끝난 뒤에만 답변 행을 잠근다: 그사이 전사문을 고쳤으면 옛 근거로 만든 보고서를 저장하지 않는다.
    """
    if not answer.transcript or not answer.transcript.strip():
        raise NoTranscript
    history = [{"question": a.question.text, "answer": a.transcript}
               for a in answer.session.answers if a.order_no < answer.order_no and a.transcript]
    transcript = answer.transcript
    report = coaching.build_report(answer.question.text, transcript, answer.session.context_snapshot or {}, history)
    unchanged = db.execute(update(PracticeAnswer).where(PracticeAnswer.id == answer.id,
                           PracticeAnswer.transcript == transcript).values(transcript=PracticeAnswer.transcript),
                           execution_options={"synchronize_session": False})
    if unchanged.rowcount != 1:
        db.rollback()
        raise TranscriptChanged
    # 모델이 도는 동안 다른 요청이 이 행을 만들었을 수 있다
    saved = db.get(AnswerCoaching, answer.id, populate_existing=True)
    answer.coaching = saved if saved is not None else AnswerCoaching()
    answer.coaching.report = report
    return answer.coaching.report
