"""FastAPI 앱. 시작 시 `.env` 설정으로 추천 파이프라인을 조립해 `app.state.recommender`에 둔다.

lifespan을 실행하지 않는 환경(Vercel 서버리스 등)에서는 첫 `/recommend` 요청에서 조립한다
(`app/api/dependencies.py`).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.assembly import ensure_assembled, release_assembled
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 테스트는 get_settings를 dependency_overrides로 바꾼다. 여기서도 같은 설정을 읽어야
    # 로컬 .env의 실제 키로 연동을 조립하지 않는다.
    settings = app.dependency_overrides.get(get_settings, get_settings)()
    await ensure_assembled(app.state, settings)
    try:
        yield
    finally:
        await release_assembled(app.state)


app = FastAPI(title="game-recommend-be", lifespan=lifespan)
app.include_router(router)
