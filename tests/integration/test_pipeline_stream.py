"""오케스트레이터 `stream()`은 `run()`과 같은 결과를 마지막 이벤트로 낸다."""

import asyncio

from app.schemas.recommendation import ResultEvent, StageEvent


def test_stream_matches_run_result(recommender, services):
    async def collect():
        return [event async for event in recommender.stream("게임 하나 추천")]

    events = asyncio.run(collect())
    plain = asyncio.run(recommender.run("게임 하나 추천"))

    assert all(isinstance(e, StageEvent) for e in events[:-1])
    assert isinstance(events[-1], ResultEvent)
    assert events[-1].result.model_dump() == plain.model_dump()
    # 가격·하드웨어는 병렬이라 순서가 바뀔 수 있지만 둘 다 리뷰 요약보다 먼저 끝난다
    order = [e.stage for e in events[:-1] if e.status == "completed"]
    assert order.index("가격") < order.index("리뷰 요약")
    assert order.index("하드웨어") < order.index("리뷰 요약")


def test_stream_stops_pipeline_when_consumer_leaves(recommender, services, monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def hang(conditions):
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(services.catalog, "search", hang)

    async def scenario():
        stream = recommender.stream("추천")
        first = await stream.__anext__()
        assert first.stage == "질문 분해"
        await started.wait()
        await stream.aclose()  # 클라이언트가 연결을 끊은 상황
        await asyncio.wait_for(cancelled.wait(), timeout=1)

    asyncio.run(scenario())
