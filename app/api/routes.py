"""HTTP 엔드포인트. `/recommend`는 `Accept: text/event-stream`이면 진행 상황을 SSE로 흘린다."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

from app.agent.progress import PipelineStageError, Recommender
from app.api.dependencies import get_recommender, require_api_key
from app.schemas.recommendation import (
    PipelineEvent,
    RecommendationRequest,
    RecommendationResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()

SSE_MEDIA_TYPE = "text/event-stream"
HEARTBEAT_SECONDS = 15  # 단계 하나가 최대 30초라 그 사이 프록시가 연결을 끊지 않게 주석 줄을 보낸다


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post(
    "/recommend",
    response_model=RecommendationResponse,
    dependencies=[Depends(require_api_key)],
    responses={
        200: {
            "description": (
                "JSON 응답. 요청 헤더가 `Accept: text/event-stream`이면 대신 SSE로 "
                "`stage`(진행) 이벤트를 흘리고 마지막에 `result`(JSON 응답과 같은 본문) 또는 "
                "`error`(502와 같은 detail) 이벤트를 보낸다."
            ),
            "content": {"application/json": {}, SSE_MEDIA_TYPE: {}},
        }
    },
)
async def recommend(
    body: RecommendationRequest,
    recommender: Annotated[Recommender, Depends(get_recommender)],
    accept: Annotated[str | None, Header()] = None,
):
    if accept and SSE_MEDIA_TYPE in accept:
        return StreamingResponse(
            encode_sse(recommender.stream(body.question, language=body.language)),
            media_type=SSE_MEDIA_TYPE,
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    try:
        return await recommender.run(body.question, language=body.language)
    except PipelineStageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


async def encode_sse(
    events: AsyncIterator[PipelineEvent], heartbeat_seconds: float = HEARTBEAT_SECONDS
) -> AsyncIterator[str]:
    """이벤트를 `event:`/`data:` 프레임으로 바꾸고, 조용한 동안에는 주석 줄로 연결을 유지한다."""
    iterator = events.__aiter__()
    pending: asyncio.Task | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=heartbeat_seconds)
            if not done:
                yield ": keep-alive\n\n"
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            yield f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            await aclose()
