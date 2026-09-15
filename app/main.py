"""FastAPI 앱. 시작 시 `.env` 설정으로 추천 파이프라인을 조립해 `app.state.recommender`에 둔다."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.assembly import assemble
from app.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 테스트는 get_settings를 dependency_overrides로 바꾼다. 여기서도 같은 설정을 읽어야
    # 로컬 .env의 실제 키로 연동을 조립하지 않는다.
    settings = app.dependency_overrides.get(get_settings, get_settings)()
    assembled = None
    if getattr(app.state, "recommender", None) is None:  # 미리 주입한 파이프라인은 그대로 둔다
        assembled = assemble(settings)
        if assembled is not None:
            app.state.recommender = assembled.recommender
            logger.info("Recommender assembled from settings")
    try:
        yield
    finally:
        if assembled is not None:
            app.state.recommender = None
            await assembled.aclose()


app = FastAPI(title="game-recommend-be", lifespan=lifespan)
app.include_router(router)
