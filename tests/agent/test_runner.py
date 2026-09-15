"""에이전트 루프 전체: 대본 모델로 Tool 선택·병렬 호출·후검증 재시도·안전망·SSE를 검증한다."""

import asyncio

import pytest
from langchain_core.messages import HumanMessage

from app.pipeline.progress import PipelineStageError
from app.schemas.recommendation import ErrorEvent, ResultEvent, StageEvent
from tests.agent.fakes import checks, draft, reviews, search

SEARCH = dict(genres=["Adventure"])


def run(recommender, question="어드벤처 게임 2개"):
    return asyncio.run(recommender.run(question))


def test_agent_flow_builds_same_response_shape_as_pipeline(make_recommender, services):
    recommender = make_recommender(
        search(**SEARCH), checks([1, 2, 3]), reviews([3]), draft([3], "답변")
    )

    response = run(recommender)

    assert services.calls == ["parse", "search", "price", "hardware", "reviews", "media"]
    assert response.answer == "답변"
    assert response.conditions == services.parser.conditions
    assert [g.game.igdb_id for g in response.games] == [3]
    assert response.games[0].price.quote.amount_krw == 100
    assert response.games[0].hardware.check.status == "met"
    assert response.games[0].review.summary == "테스트 요약"
    assert response.games[0].media is not None
    assert {g.game.igdb_id for g in response.excluded_games} == {1, 2}
    assert all(g.review is None and g.media is None for g in response.excluded_games)
    assert response.warnings == []
    assert services.reviews.reviewed_ids == [3]
    assert services.media.requested_ids == [3]


def test_stream_emits_tool_stages_and_matches_run(make_recommender):
    script = (search(**SEARCH), checks([1, 2, 3]), reviews([3]), draft([3]))
    events = asyncio.run(_collect(make_recommender(*script).stream("q")))
    plain = run(make_recommender(*script))

    assert isinstance(events[-1], ResultEvent)
    assert events[-1].result.model_dump() == plain.model_dump()
    stages = [(e.stage, e.status) for e in events[:-1] if isinstance(e, StageEvent)]
    assert stages[0] == ("질문 분해", "started")
    assert ("에이전트 추론", "started") in stages
    assert ("게임 검색", "completed") in stages
    assert ("가격", "completed") in stages and ("하드웨어", "completed") in stages
    assert ("리뷰 요약", "completed") in stages
    assert stages.index(("에이전트 추론", "completed")) > stages.index(("리뷰 요약", "completed"))
    detail = next(
        e.detail
        for e in events
        if isinstance(e, StageEvent) and e.stage == "에이전트 추론" and e.status == "completed"
    )
    assert detail == "도구 호출 4회"
    judged = next(e for e in events if isinstance(e, StageEvent) and e.stage == "조건 판정")
    assert judged.detail == "추천 1개, 제외 2개"
    assert stages[-1] == ("미디어", "completed")


def test_rejected_draft_is_retried_with_reasons(make_recommender, services):
    # 1번은 예산 초과인데 추천했다 → 거부 → 3번으로 다시 제출
    recommender = make_recommender(
        search(**SEARCH), checks([1, 2, 3]), draft([1]), draft([3], "수정")
    )

    response = run(recommender)

    assert [g.game.igdb_id for g in response.games] == [3]
    assert response.answer == "수정"
    assert services.calls == ["parse", "search", "price", "hardware", "reviews", "media"]


def test_rejection_message_lists_problems(make_recommender):
    seen: list[list[str]] = []
    recommender = make_recommender(
        search(**SEARCH), checks([1, 2, 3]), draft([1, 2, 3]), draft([3])
    )
    original = recommender._invoke

    async def spy(messages, ctx):
        if isinstance(messages[-1], HumanMessage) and "확정할 수 없습니다" in messages[-1].content:
            seen.append(messages[-1].content.splitlines())
        return await original(messages, ctx)

    recommender._invoke = spy
    run(recommender)

    assert len(seen) == 1
    lines = seen[0]
    assert any("2개 이하" in line for line in lines)
    assert any("Game 1(igdb_id 1)" in line and "가격 미충족" in line for line in lines)
    assert any("Game 2(igdb_id 2)" in line and "사양 확인 불가" in line for line in lines)


def test_draft_rejected_twice_fails_like_required_stage(make_recommender):
    recommender = make_recommender(search(**SEARCH), checks([1, 2, 3]), draft([1]), draft([1]))

    with pytest.raises(PipelineStageError, match="확정하지 못했습니다"):
        run(recommender)

    again = make_recommender(search(**SEARCH), checks([1, 2, 3]), draft([1]), draft([1]))
    events = asyncio.run(_collect(again.stream("q")))
    assert isinstance(events[-1], ErrorEvent)
    assert ("에이전트 추론", "failed") in [(e.stage, e.status) for e in events[:-1]]


def test_runner_fetches_skipped_checks_and_reviews_before_finalizing(make_recommender, services):
    # 에이전트가 가격·사양·리뷰를 건너뛰고 바로 제출해도 러너가 채운다
    recommender = make_recommender(search(**SEARCH), draft([3]))

    response = run(recommender)

    assert services.calls == ["parse", "search", "price", "hardware", "reviews", "media"]
    assert response.games[0].price.quote.amount_krw == 100
    assert response.games[0].hardware.check.status == "met"
    assert response.games[0].review.summary == "테스트 요약"


def test_unknown_id_error_goes_back_to_model_without_warning(make_recommender, services):
    recommender = make_recommender(
        search(**SEARCH), checks([99]), checks([1, 2, 3]), reviews([3]), draft([3])
    )

    response = run(recommender)

    assert response.warnings == []
    assert services.calls.count("price") == 1  # 99번 호출은 팀원 도구에 닿지 않았다


def test_tool_failure_becomes_warning_and_agent_continues(make_recommender, services, monkeypatch):
    async def broken(games):
        raise RuntimeError("steam down")

    monkeypatch.setattr(services.price_hardware, "fetch_prices", broken)
    # 가격을 못 받아 3번도 unknown → 첫 초안 거부 → 빈 추천으로 다시 제출
    recommender = make_recommender(
        search(**SEARCH), checks([1, 2, 3]), draft([3]), draft([], "가격 확인 불가")
    )

    response = run(recommender)

    assert response.games == []
    assert response.answer == "가격 확인 불가"
    assert response.warnings.count("가격 호출 실패: 해당 정보를 확인할 수 없습니다.") == 1
    assert "모든 필수 조건을 충족한다고 확인된 후보가 없습니다." in response.warnings


def test_no_candidates_yields_empty_recommendation(make_recommender, services):
    services.catalog.games = []
    recommender = make_recommender(search(**SEARCH), draft([], "조건에 맞는 게임이 없습니다"))

    response = run(recommender)

    assert response.games == [] and response.excluded_games == []
    assert services.calls == ["parse", "search"]
    assert "모든 필수 조건을 충족한다고 확인된 후보가 없습니다." in response.warnings


def test_parser_failure_is_required_stage(make_recommender, services, monkeypatch):
    async def broken(question):
        raise RuntimeError("llm down")

    monkeypatch.setattr(services.parser, "parse", broken)
    with pytest.raises(PipelineStageError, match="질문 분해"):
        run(make_recommender(draft([])))


def test_model_without_draft_fails_cleanly(make_recommender):
    # 대본이 끝나 모델이 답을 못 내면 (recursion·모델 오류) 502 계열 오류로 끝난다
    with pytest.raises(PipelineStageError):
        run(make_recommender(search(**SEARCH)))


def test_graph_has_model_and_tools_nodes(make_recommender):
    mermaid = make_recommender(draft([])).graph_mermaid()
    assert "model(model)" in mermaid and "tools(tools)" in mermaid


async def _collect(stream):
    return [event async for event in stream]
