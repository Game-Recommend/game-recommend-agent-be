"""진행 콜백, 단계 실패 예외, `run()`을 SSE 이벤트 스트림으로 바꾸는 helper, 추천기 계약."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

from app.schemas.recommendation import (
    ErrorEvent,
    PipelineEvent,
    RecommendationResponse,
    ResultEvent,
    StageEvent,
)

logger = logging.getLogger(__name__)

# (단계 이름, started/completed/failed, 부가 설명). SSE 진행 표시에 쓴다.
Progress = Callable[[str, str, str | None], None]


def silent(stage: str, status: str, detail: str | None = None) -> None:
    return None


class PipelineStageError(Exception):
    """질문 분해나 에이전트 루프처럼 계속 진행할 수 없는 단계의 실패. HTTP 502가 된다."""


class Recommender(Protocol):
    """`/recommend`가 기대하는 추천기 계약. `AgentRecommender`가 구현한다."""

    async def run(self, question: str, progress: Progress = silent) -> RecommendationResponse: ...

    def stream(self, question: str) -> AsyncIterator[PipelineEvent]: ...


async def stream_progress(
    run: Callable[[str, Progress], Awaitable[RecommendationResponse]], question: str
) -> AsyncIterator[PipelineEvent]:
    """`run(question, progress)`를 실행하며 진행 이벤트를 흘린다.

    마지막에 result나 error 이벤트를 낸다.

    소비자가 먼저 끊으면 진행 중인 외부 호출도 취소한다.
    """
    queue: asyncio.Queue[PipelineEvent | None] = asyncio.Queue()

    def progress(stage: str, status: str, detail: str | None) -> None:
        queue.put_nowait(StageEvent(stage=stage, status=status, detail=detail))

    async def runner() -> None:
        try:
            queue.put_nowait(ResultEvent(result=await run(question, progress)))
        except PipelineStageError as exc:
            queue.put_nowait(ErrorEvent(detail=str(exc)))
        except Exception as exc:  # 예상 밖 오류도 스트림을 닫기 전에 알린다
            logger.exception("Unexpected recommendation failure (%s)", type(exc).__name__)
            queue.put_nowait(ErrorEvent(detail="추천 처리 중 오류가 발생했습니다."))
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(runner())
    try:
        while (event := await queue.get()) is not None:
            yield event
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
