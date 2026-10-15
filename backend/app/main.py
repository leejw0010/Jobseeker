import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


@app.get("/health")
def health():
    return {"ok": True, "openai": llm.available(), "auth_disabled": settings.auth_disabled}
