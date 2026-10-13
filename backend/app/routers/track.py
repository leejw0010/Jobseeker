"""③ Track: 지원 이력·단계 결과, 자소서 답변 버전, 확장 동기화, 통계."""
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth import current_user_id
from ..db import get_db
from ..models import STAGES, AnswerVersion, Application, EssayItem, StageEvent
from ..schemas import (
    ApplicationDetail,
    ApplicationIn,
    ApplicationOut,
    ApplicationPatch,
    EssayItemIn,
    EssayItemOut,
    StageEventIn,
    StageEventOut,
    SyncIn,
    SyncOut,
    VersionIn,
    VersionOut,
)

router = APIRouter(prefix="/track", tags=["track"])


def _own_app(db: Session, user_id: str, app_id: str) -> Application:
    app = db.scalar(
        select(Application)
        .where(Application.id == app_id, Application.user_id == user_id)
        .options(selectinload(Application.events),
                 selectinload(Application.essay_items).selectinload(EssayItem.versions))
    )
    if not app:
        raise HTTPException(404, "지원 건을 찾을 수 없습니다")
    return app


def _own_item(db: Session, user_id: str, item_id: str) -> EssayItem:
    item = db.scalar(
        select(EssayItem).join(Application)
        .where(EssayItem.id == item_id, Application.user_id == user_id)
        .options(selectinload(EssayItem.versions))
    )
    if not item:
        raise HTTPException(404, "자소서 문항을 찾을 수 없습니다")
    return item


def _add_version(item: EssayItem, content: str, source: str, is_submitted: bool) -> AnswerVersion | None:
    """직전 버전과 내용이 같으면 새 버전을 만들지 않는다(제출 표시만 갱신)."""
    latest = item.versions[-1] if item.versions else None
    if latest and latest.content == content:
        latest.is_submitted = latest.is_submitted or is_submitted
        return None
    v = AnswerVersion(version_no=(latest.version_no + 1) if latest else 1, content=content,
                      char_count=len(content), source=source, is_submitted=is_submitted)
    item.versions.append(v)
    return v


# ───────── 지원 건 ─────────

@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(
    status: str | None = None,
    stage: str | None = None,
    job_category: str | None = None,
    q: str | None = None,
    user_id: str = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    stmt = select(Application).where(Application.user_id == user_id)
    if status:
        stmt = stmt.where(Application.status == status)
    if stage:
        stmt = stmt.where(Application.stage == stage)
    if job_category:
        stmt = stmt.where(Application.job_category == job_category)
    if q:
        stmt = stmt.where(Application.company.contains(q) | Application.position.contains(q))
    return db.scalars(stmt.order_by(Application.updated_at.desc())).all()


@router.post("/applications", response_model=ApplicationDetail, status_code=201)
def create_application(body: ApplicationIn, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    app = Application(user_id=user_id, source="web", **body.model_dump())
    db.add(app)
    db.commit()
    return _own_app(db, user_id, app.id)


@router.get("/applications/{app_id}", response_model=ApplicationDetail)
def get_application(app_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    return _own_app(db, user_id, app_id)


@router.patch("/applications/{app_id}", response_model=ApplicationDetail)
def update_application(app_id: str, body: ApplicationPatch, user_id: str = Depends(current_user_id),
                       db: Session = Depends(get_db)):
    app = _own_app(db, user_id, app_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(app, k, v)
    db.commit()
    return _own_app(db, user_id, app_id)


@router.delete("/applications/{app_id}", status_code=204)
def delete_application(app_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    db.delete(_own_app(db, user_id, app_id))
    db.commit()


# ───────── 단계별 결과 ─────────

@router.post("/applications/{app_id}/events", response_model=ApplicationDetail, status_code=201)
def add_event(app_id: str, body: StageEventIn, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    """단계 결과를 기록하고 지원 건의 현재 단계·상태를 함께 갱신한다.

    합격 → 다음 단계로 진행(최종 합격이면 상태 '합격'), 불합격 → 상태 '불합격', 대기 → 해당 단계 진행중.
    """
    app = _own_app(db, user_id, app_id)
    app.events.append(StageEvent(stage=body.stage, result=body.result,
                                 event_date=body.event_date or date.today(), memo=body.memo))
    idx = STAGES.index(body.stage)
    if body.result == "합격":
        if idx == len(STAGES) - 1:
            app.stage, app.status = body.stage, "합격"
        else:
            app.stage, app.status = STAGES[idx + 1], "진행중"
    elif body.result == "불합격":
        app.stage, app.status = body.stage, "불합격"
    else:
        app.stage, app.status = body.stage, "진행중"
    db.commit()
    return _own_app(db, user_id, app_id)


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    ev = db.scalar(select(StageEvent).join(Application)
                   .where(StageEvent.id == event_id, Application.user_id == user_id))
    if not ev:
        raise HTTPException(404, "기록을 찾을 수 없습니다")
    db.delete(ev)
    db.commit()


# ───────── 자소서 문항·버전 ─────────

@router.post("/applications/{app_id}/essays", response_model=EssayItemOut, status_code=201)
def add_essay_item(app_id: str, body: EssayItemIn, user_id: str = Depends(current_user_id),
                   db: Session = Depends(get_db)):
    app = _own_app(db, user_id, app_id)
    item = EssayItem(question_text=body.question_text, char_limit=body.char_limit)
    app.essay_items.append(item)
    if body.content:
        _add_version(item, body.content, "web", False)
    db.commit()
    return _own_item(db, user_id, item.id)


@router.delete("/essays/{item_id}", status_code=204)
def delete_essay_item(item_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    db.delete(_own_item(db, user_id, item_id))
    db.commit()


@router.get("/essays/{item_id}/versions", response_model=list[VersionOut])
def list_versions(item_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    return _own_item(db, user_id, item_id).versions


@router.post("/essays/{item_id}/versions", response_model=EssayItemOut, status_code=201)
def add_version(item_id: str, body: VersionIn, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    item = _own_item(db, user_id, item_id)
    _add_version(item, body.content, body.source, body.is_submitted)
    db.commit()
    return _own_item(db, user_id, item_id)


@router.post("/versions/{version_id}/restore", response_model=EssayItemOut)
def restore_version(version_id: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    """예전 버전 내용을 새 최신 버전으로 복사한다(이력은 지우지 않음)."""
    v = db.scalar(select(AnswerVersion).join(EssayItem).join(Application)
                  .where(AnswerVersion.id == version_id, Application.user_id == user_id))
    if not v:
        raise HTTPException(404, "버전을 찾을 수 없습니다")
    item = _own_item(db, user_id, v.essay_item_id)
    _add_version(item, v.content, "web", False)
    db.commit()
    return _own_item(db, user_id, item.id)


@router.get("/answers/search", response_model=list[dict])
def search_answers(q: str, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    """예전에 쓴 답변 재사용용 검색(문항·내용). 확장 프로그램(①)도 이 API를 쓸 수 있다."""
    rows = db.execute(
        select(Application.company, Application.position, EssayItem.question_text, AnswerVersion)
        .join(EssayItem, EssayItem.application_id == Application.id)
        .join(AnswerVersion, AnswerVersion.essay_item_id == EssayItem.id)
        .where(Application.user_id == user_id)
        .where(EssayItem.question_text.contains(q) | AnswerVersion.content.contains(q))
        .order_by(AnswerVersion.created_at.desc())
        .limit(30)
    ).all()
    return [
        {"company": c, "position": p, "question_text": qt, "version_id": v.id, "version_no": v.version_no,
         "content": v.content, "char_count": v.char_count, "is_submitted": v.is_submitted}
        for c, p, qt, v in rows
    ]


# ───────── 확장 프로그램 동기화 ─────────

@router.post("/sync", response_model=SyncOut)
def sync_from_extension(body: SyncIn, user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    """크롬 확장이 지원서를 제출하면 호출. 같은 URL의 지원 건이 있으면 갱신, 없으면 생성.
    문항은 질문 텍스트로 매칭하고, 내용이 바뀐 경우에만 새 버전을 쌓는다."""
    app = db.scalar(select(Application).where(Application.user_id == user_id, Application.url == body.url))
    created = app is None
    if created:
        app = Application(user_id=user_id, company=body.company, position=body.position,
                          job_category=body.job_category, url=body.url,
                          applied_at=body.applied_at or (date.today() if body.submitted else None),
                          source="extension")
        db.add(app)
        db.flush()
    elif body.submitted and not app.applied_at:
        app.applied_at = body.applied_at or date.today()
    app = _own_app(db, user_id, app.id) if not created else app
    by_text = {i.question_text.strip(): i for i in app.essay_items}
    new_versions = 0
    for e in body.essays:
        item = by_text.get(e.question_text.strip())
        if item is None:
            item = EssayItem(question_text=e.question_text.strip(), char_limit=e.char_limit)
            app.essay_items.append(item)
            by_text[item.question_text] = item
        if _add_version(item, e.content, "extension", body.submitted):
            new_versions += 1
    db.commit()
    return SyncOut(application_id=app.id, created=created, new_versions=new_versions)


# ───────── 통계 ─────────

def _passed_stage(app: Application, stage: str) -> bool:
    idx = STAGES.index(stage)
    cur = STAGES.index(app.stage)
    if cur > idx:
        return True
    if cur == idx and app.status == "합격":
        return True
    return any(e.stage == stage and e.result == "합격" for e in app.events)


@router.get("/stats")
def stats(user_id: str = Depends(current_user_id), db: Session = Depends(get_db)):
    """단계별 통과율은 결과가 확정된 건(합격+불합격)만 분모로 쓴다. 진행중인 건은 'pending'으로 따로 센다."""
    apps = db.scalars(select(Application).where(Application.user_id == user_id)
                      .options(selectinload(Application.events))).all()

    def funnel(subset: list[Application]) -> list[dict]:
        rows = []
        for i, stage in enumerate(STAGES):
            reached = [a for a in subset if STAGES.index(a.stage) >= i]
            passed = sum(1 for a in reached if _passed_stage(a, stage))
            failed = sum(1 for a in reached if a.stage == stage and a.status == "불합격")
            pending = len(reached) - passed - failed
            decided = passed + failed
            rows.append({"stage": stage, "reached": len(reached), "passed": passed, "failed": failed,
                         "pending": pending, "pass_rate": round(passed / decided, 3) if decided else None})
        return rows

    by_cat: dict[str, list[Application]] = defaultdict(list)
    for a in apps:
        by_cat[a.job_category].append(a)
    status_counts = {s: sum(1 for a in apps if a.status == s) for s in ["진행중", "합격", "불합격", "보류"]}
    monthly: dict[str, int] = defaultdict(int)
    for a in apps:
        d = a.applied_at or a.created_at.date()
        monthly[d.strftime("%Y-%m")] += 1
    return {
        "total": len(apps),
        "status": status_counts,
        "funnel": funnel(list(apps)),
        "by_job_category": [
            {"job_category": c, "total": len(lst),
             "final_pass": sum(1 for a in lst if a.status == "합격"),
             "funnel": funnel(lst)}
            for c, lst in sorted(by_cat.items(), key=lambda kv: -len(kv[1]))
        ],
        "monthly": [{"month": m, "count": n} for m, n in sorted(monthly.items())],
    }
