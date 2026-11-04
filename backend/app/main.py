import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError

from . import llm
from .config import settings
from .db import SessionLocal, init_db
from .retention import purge_loop, run_purge
from .routers import practice, track
from .seed import seed_question_bank


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed_question_bank(db)
    # 만료된 원본 녹음: 시작할 때 한 번, 이후 PURGE_INTERVAL_MIN분마다 정리(실패해도 앱은 계속 뜬다)
    await asyncio.to_thread(run_purge)
    purger = asyncio.create_task(purge_loop())
    try:
        yield
    finally:
        purger.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await purger


app = FastAPI(title="JobSeeker API (Practice · Track)", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # 크롬 확장(①)에서의 호출 허용
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(practice.router)
app.include_router(track.router)


@app.exception_handler(DataError)
async def invalid_id(_: Request, exc: DataError):
    """uuid가 아닌 id가 Postgres까지 갔을 때(라우터가 미처 거르지 못한 경우) 500 대신 404로 답한다."""
    orig = exc.orig
    if getattr(orig, "sqlstate", None) == "22P02" and "uuid" in str(orig):
        return JSONResponse(status_code=404, content={"detail": "요청한 항목을 찾을 수 없어요"})
    raise exc


@app.get("/health")
def health():
    return {"ok": True, "openai": llm.available(), "auth_disabled": settings.auth_disabled}
