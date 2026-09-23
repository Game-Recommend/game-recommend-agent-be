"""에이전트 루프 전체: 대본 모델로 Tool 선택·병렬 호출·후검증 재시도·안전망·SSE를 검증한다."""

import asyncio

import pytest
from langchain_core.messages import HumanMessage

from app.agent.context import AgentContext
from app.agent.progress import PipelineStageError
from app.agent.prompts import AGENT_SYSTEM, build_system_prompt
from app.agent.runner import AgentRecommender
from app.schemas.price import PriceQuote
from app.schemas.recommendation import ErrorEvent, ResultEvent, StageEvent
from tests.agent.fakes import checks, draft, reviews, scripted, search

SEARCH = dict(genres=["Adventure"])


def run(recommender, question="어드벤처 게임 2개"):
    return asyncio.run(recommender.run(question))


def checks_first(calls):
    """가격·사양은 같은 턴에 병렬로 돌아 둘 사이의 순서가 정해져 있지 않다. 비교용으로 맞춘다."""
    calls = list(calls)
    for i in range(len(calls) - 1):
        if calls[i : i + 2] == ["hardware", "price"]:
            calls[i : i + 2] = ["price", "hardware"]
    return calls


def assert_calls(services, *agent_calls):
    """에이전트 구간은 순서대로, 그 뒤 리뷰·미디어는 병렬 노드라 순서를 묻지 않는다."""
    head, tail = services.calls[: len(agent_calls)], services.calls[len(agent_calls) :]
    assert checks_first(head) == list(agent_calls)
    assert sorted(tail) == ["media", "reviews"]


def test_agent_flow_builds_full_response(make_recommender, services):
    recommender = make_recommender(
        search(**SEARCH), checks([1, 2, 3]), reviews([3]), draft([3], "Game 3 답변")
    )

    response = run(recommender)

    assert checks_first(services.calls) == [
        "parse", "search", "price", "hardware", "reviews", "media",
    ]
    assert response.answer == "Game 3 답변"
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
    assert judged.detail == "통과 1개 중 1개 추천, 제외 2개"
    assert stages[-1] == ("미디어", "completed")


def test_rejected_draft_is_retried_with_reasons(make_recommender, services):
    # 1번은 예산 초과인데 추천했다 → 거부 → 3번으로 다시 제출
    recommender = make_recommender(
        search(**SEARCH), checks([1, 2, 3]), draft([1]), draft([3], "Game 3 수정")
    )

    response = run(recommender)

    assert [g.game.igdb_id for g in response.games] == [3]
    assert response.answer == "Game 3 수정"
    assert_calls(services, "parse", "search", "price", "hardware")


def test_rejection_message_lists_problems(make_recommender):
    seen: list[list[str]] = []
    recommender = make_recommender(
        search(**SEARCH), checks([1, 2, 3]), draft([1, 2, 3]), draft([3])
    )
    state = asyncio.run(
        recommender.graph.ainvoke(
            {"question": "q", "messages": []}, context=AgentContext.pending(recommender.tools)
        )
    )
    for message in state["messages"]:
        if isinstance(message, HumanMessage) and "확정할 수 없습니다" in message.content:
            seen.append(message.content.splitlines())

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


def _challenges(recommender) -> list[str]:
    """그래프를 끝까지 돌려 러너가 붙인 빈 초안 되묻기 메시지를 모은다."""
    state = asyncio.run(
        recommender.graph.ainvoke(
            {"question": "q", "messages": []}, context=AgentContext.pending(recommender.tools)
        )
    )
    return [
        message.content
        for message in state["messages"]
        if isinstance(message, HumanMessage) and "재확인" in message.content
    ]


def test_empty_draft_with_passing_candidates_is_asked_once_more(make_recommender, services):
    # 3번이 가격·사양을 통과했는데 빈손으로 제출했다 → 통과 후보를 붙여 되묻는다 → 3번으로 제출
    script = (search(**SEARCH), checks([1, 2, 3]), draft([], "없음"), draft([3], "Game 3 다시"))

    response = run(make_recommender(*script))

    assert [g.game.igdb_id for g in response.games] == [3]
    assert response.answer == "Game 3 다시"
    assert "모든 필수 조건을 충족한다고 확인된 후보가 없습니다." not in response.warnings
    assert_calls(services, "parse", "search", "price", "hardware")

    challenges = _challenges(make_recommender(*script))
    assert len(challenges) == 1
    assert "Game 3(igdb_id 3)" in challenges[0]
    # 조건에 걸린 후보는 되묻기 목록에 없다
    assert "Game 1" not in challenges[0] and "Game 2" not in challenges[0]


def test_second_empty_draft_is_accepted_as_the_agents_judgment(make_recommender):
    # 되물어도 비어 있으면 에이전트의 판단으로 받는다. 502가 아니다
    script = (search(**SEARCH), checks([1, 2, 3]), draft([], "없음"), draft([], "정말 없음"))

    response = run(make_recommender(*script))

    assert response.games == []
    assert response.answer == "정말 없음"
    assert "모든 필수 조건을 충족한다고 확인된 후보가 없습니다." in response.warnings
    assert len(_challenges(make_recommender(*script))) == 1

    events = asyncio.run(_collect(make_recommender(*script).stream("q")))
    judged = next(e for e in events if isinstance(e, StageEvent) and e.stage == "조건 판정")
    assert judged.detail == "통과 1개 중 0개 추천, 제외 2개"


def test_empty_challenge_does_not_spend_the_rejection_retry(make_recommender):
    # 되물은 뒤의 초안이 거부돼도 거부 재시도 한 번은 그대로 남아 있다
    recommender = make_recommender(
        search(**SEARCH), checks([1, 2, 3]), draft([]), draft([1]), draft([3], "Game 3 수정")
    )

    response = run(recommender)

    assert [g.game.igdb_id for g in response.games] == [3]
    assert response.answer == "Game 3 수정"


def test_rejections_after_challenge_fall_back_to_the_empty_draft(make_recommender):
    # 되묻기가 200이던 응답을 502로 바꾸지 않는다: 끝내 검증에 실패하면 처음의 빈 초안으로 돌아간다
    recommender = make_recommender(
        search(**SEARCH), checks([1, 2, 3]), draft([], "없음"), draft([1]), draft([1])
    )

    response = run(recommender)

    assert response.games == []
    assert response.answer == "없음"
    assert "모든 필수 조건을 충족한다고 확인된 후보가 없습니다." in response.warnings


def test_empty_draft_without_passing_candidates_is_not_challenged(make_recommender, services):
    # 3번도 예산을 넘겨 통과 후보가 없다 → 빈 추천이 옳고, 되묻지 않는다
    services.price_hardware.quotes = [PriceQuote(igdb_id=i, amount_krw=150) for i in (1, 2, 3)]
    script = (search(**SEARCH), checks([1, 2, 3]), draft([], "없음"))

    response = run(make_recommender(*script))

    assert response.games == [] and response.answer == "없음"
    assert {g.game.igdb_id for g in response.excluded_games} == {1, 2, 3}
    assert _challenges(make_recommender(*script)) == []


def test_answer_without_recommended_name_is_asked_once_more(make_recommender):
    # 카드는 Game 3인데 본문은 다른 이름을 말한다 → 추천 목록을 붙여 되묻는다 → 이름을 맞춰 제출
    script = (
        search(**SEARCH),
        checks([1, 2, 3]),
        draft([3], "Half-Life를 추천합니다"),
        draft([3], "Game 3을 추천합니다"),
    )

    response = run(make_recommender(*script))

    assert response.answer == "Game 3을 추천합니다"
    challenges = _challenges(make_recommender(*script))
    assert len(challenges) == 1
    assert "Game 3(igdb_id 3)" in challenges[0] and "answer에 이름이 나오지 않는" in challenges[0]


def test_answer_still_missing_the_name_is_accepted_not_failed(make_recommender):
    # 되물어도 이름이 빠져 있으면 그대로 받는다. 표현 문제로 502를 내지 않는다
    script = (search(**SEARCH), checks([1, 2, 3]), draft([3], "첫 답변"), draft([3], "둘째 답변"))

    response = run(make_recommender(*script))

    assert [g.game.igdb_id for g in response.games] == [3]
    assert response.answer == "둘째 답변"
    assert len(_challenges(make_recommender(*script))) == 1


def test_rejections_after_name_challenge_fall_back_to_the_earlier_draft(make_recommender):
    # 되물은 뒤의 초안이 끝내 거부되면, 이름만 어긋났던 처음 초안으로 돌아간다
    recommender = make_recommender(
        search(**SEARCH), checks([1, 2, 3]), draft([3], "첫 답변"), draft([1]), draft([1])
    )

    response = run(recommender)

    assert [g.game.igdb_id for g in response.games] == [3]
    assert response.answer == "첫 답변"


def test_empty_then_name_challenge_are_each_asked_once(make_recommender):
    script = (
        search(**SEARCH),
        checks([1, 2, 3]),
        draft([], "없음"),
        draft([3], "이름 없는 답변"),
        draft([3], "Game 3 답변"),
    )

    response = run(make_recommender(*script))

    assert response.answer == "Game 3 답변"
    assert len(_challenges(make_recommender(*script))) == 2


def test_runner_fetches_skipped_checks_and_reviews_before_finalizing(make_recommender, services):
    # 에이전트가 가격·사양·리뷰를 건너뛰고 바로 제출해도 러너가 채운다
    recommender = make_recommender(search(**SEARCH), draft([3]))

    response = run(recommender)

    assert_calls(services, "parse", "search", "price", "hardware")
    assert response.games[0].price.quote.amount_krw == 100
    assert response.games[0].hardware.check.status == "met"
    assert response.games[0].review.summary == "테스트 요약"


def test_unknown_id_error_goes_back_to_model_without_warning(make_recommender, services):
    recommender = make_recommender(
        search(**SEARCH), checks([1, 2, 3]), reviews([99]), reviews([3]), draft([3])
    )

    response = run(recommender)

    assert response.warnings == []
    assert services.calls.count("reviews") == 1  # 99번 호출은 팀원 도구에 닿지 않았다


def test_price_and_hardware_check_every_candidate_whatever_ids_the_model_passes(make_recommender):
    # 모델이 id를 옮겨 적다 빠뜨리거나(1·2번 누락) 틀려도(99번) 서버는 후보 전체를 조회한다
    script = (search(**SEARCH), checks([99, 3]), draft([3]))

    response = run(make_recommender(*script))
    events = asyncio.run(_collect(make_recommender(*script).stream("q")))

    assert [g.game.igdb_id for g in response.games] == [3]
    # 1·2번도 조회됐으므로 제외 근거가 남는다
    assert {g.game.igdb_id for g in response.excluded_games} == {1, 2}
    failed = [e.stage for e in events if isinstance(e, StageEvent) and e.status == "failed"]
    assert failed == []


def test_tool_failure_becomes_warning_and_agent_continues(make_recommender, services, monkeypatch):
    async def broken(games, **options):
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


def test_media_failure_only_adds_warning(make_recommender, services):
    services.media.error = RuntimeError("down")
    recommender = make_recommender(search(**SEARCH), checks([1, 2, 3]), reviews([3]), draft([3]))

    response = run(recommender)

    assert response.games[0].game.igdb_id == 3
    assert response.games[0].media is None
    assert any(w.startswith("미디어 호출 실패") for w in response.warnings)


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


def test_graph_shows_whole_pipeline(make_recommender):
    mermaid = make_recommender(draft([])).graph_mermaid()
    nodes = ("parse", "safety_net", "validate", "retry", "judge", "reviews", "media", "respond")
    for node in nodes:
        assert f"{node}({node})" in mermaid
    assert "subgraph agent" in mermaid
    assert "validate -.-> retry" in mermaid and "retry --> agent" in mermaid


async def _collect(stream):
    return [event async for event in stream]


# --- 출력 언어 ---


def test_system_prompt_follows_request_language_on_every_model_call(services, toolset):
    # 첫 초안이 거부돼 에이전트 루프에 다시 들어가도 같은 언어로 쓰게 한다
    model = scripted(search(**SEARCH), checks([1, 2, 3]), draft([1]), draft([3]))

    asyncio.run(AgentRecommender(services.parser, toolset, model).run("q", language="en"))

    assert len(model.received) == 4
    assert all(messages[0].type == "system" for messages in model.received)
    assert {messages[0].content for messages in model.received} == {build_system_prompt("en")}


def test_default_language_keeps_the_korean_system_prompt(services, toolset):
    model = scripted(search(**SEARCH), checks([1, 2, 3]), draft([3]))

    asyncio.run(AgentRecommender(services.parser, toolset, model).run("q"))

    assert {messages[0].content for messages in model.received} == {AGENT_SYSTEM}


def test_english_request_writes_warnings_and_unchecked_reasons_in_english(
    make_recommender, services, monkeypatch
):
    async def broken(games, **options):
        raise RuntimeError("steam down")

    monkeypatch.setattr(services.price_hardware, "fetch_prices", broken)
    recommender = make_recommender(
        search(**SEARCH), checks([1, 2, 3]), draft([3]), draft([], "No price was confirmed.")
    )

    response = asyncio.run(recommender.run("q", language="en"))

    assert response.warnings == [
        "Price request failed: this information could not be verified.",
        "No candidate was confirmed to meet all required conditions.",
    ]
    # 가격을 받지 못한 후보의 판정 이유도 요청 언어로 쓴다
    assert {g.price.check.reason for g in response.excluded_games} == {"Price unavailable"}


def test_stream_carries_the_request_language(make_recommender, services):
    recommender = make_recommender(search(**SEARCH), checks([1, 2, 3]), reviews([3]), draft([3]))

    events = asyncio.run(_collect(recommender.stream("q", language="en")))

    assert isinstance(events[-1], ResultEvent)
    assert events[-1].result.games[0].price.check.reason == "Within budget"
    assert services.reviews.languages == ["en"]
