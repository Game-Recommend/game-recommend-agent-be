"""Tool별 호출 상한: 넘긴 호출은 실행하지 않고, 거부된 Tool은 다음 모델 호출에서 뺀다."""

import asyncio
import json

from langchain_core.messages import ToolMessage

from app.agent.context import AgentContext
from app.agent.limits import TOOL_CALL_LIMITS
from app.agent.runner import DRAFT_TOOL_NAME, AgentRecommender
from app.agent.tools import build_tools
from tests.agent.fakes import checks, draft, reviews, scripted, search, tool_calls

SEARCH = dict(genres=["Adventure"])


def run_graph(recommender, ctx=None) -> dict:
    ctx = ctx or AgentContext.pending(recommender.tools)
    return asyncio.run(recommender.graph.ainvoke({"question": "q", "messages": []}, context=ctx))


def refusals(state: dict) -> list[str]:
    return [
        json.loads(message.content)["error"]
        for message in state["messages"]
        if isinstance(message, ToolMessage) and message.status == "error"
    ]


def test_limits_cover_every_agent_tool():
    assert set(TOOL_CALL_LIMITS) == {tool.name for tool in build_tools()}


def test_call_over_the_limit_is_not_executed(make_recommender, services):
    # 통과 후보의 리뷰를 한 게임씩 읽어 나가는 반복. 세 번째 호출부터는 팀원 도구에 닿지 않는다
    recommender = make_recommender(
        search(**SEARCH), checks([1, 2, 3]), reviews([3]), reviews([1]), reviews([2]), draft([3])
    )

    state = run_graph(recommender)

    assert services.calls.count("reviews") == 2
    assert [g.game.igdb_id for g in state["response"].games] == [3]
    assert state["response"].warnings == []
    [notice] = refusals(state)
    assert "summarize_reviews" in notice and "2회" in notice and DRAFT_TOOL_NAME in notice


def test_refused_tool_is_withdrawn_from_the_next_model_call(services, toolset):
    model = scripted(
        search(**SEARCH), checks([1, 2, 3]), reviews([3]), reviews([1]), reviews([2]), draft([3])
    )

    run_graph(AgentRecommender(services.parser, toolset, model))

    before, after = model.offered[4], model.offered[5]
    assert "summarize_reviews" in before  # 상한에 닿기만 한 Tool은 그대로 준다
    assert "summarize_reviews" not in after
    # 상한(1회)에 닿았지만 거부된 적 없는 Tool과 최종 출력은 남는다
    assert {"search_games", "get_prices", "assess_hardware", DRAFT_TOOL_NAME} <= set(after)


def test_tool_list_is_untouched_when_nothing_is_refused(services, toolset):
    model = scripted(search(**SEARCH), checks([1, 2, 3]), reviews([3]), draft([3]))

    run_graph(AgentRecommender(services.parser, toolset, model))

    assert all(offered == model.offered[0] for offered in model.offered)


def test_same_tool_twice_in_one_turn_runs_once(make_recommender, services):
    turn = tool_calls(("get_prices", {}), ("get_prices", {}), ("assess_hardware", {}))
    recommender = make_recommender(search(**SEARCH), turn, draft([3]))

    state = run_graph(recommender)

    assert services.calls.count("price") == 1 and services.calls.count("hardware") == 1
    assert len(refusals(state)) == 1
    assert [g.game.igdb_id for g in state["response"].games] == [3]


def test_counts_carry_over_into_the_retry_loop(make_recommender, services):
    # 1번은 예산 초과라 거부된다. 다시 들어온 루프에서 가격·사양을 또 불러도 실행하지 않는다
    recommender = make_recommender(
        search(**SEARCH), checks([1, 2, 3]), draft([1]), checks([1, 2, 3]), draft([3])
    )

    state = run_graph(recommender)

    assert services.calls.count("price") == 1 and services.calls.count("hardware") == 1
    assert len(refusals(state)) == 2
    assert [g.game.igdb_id for g in state["response"].games] == [3]


def test_invalid_arguments_do_not_spend_the_limit(make_recommender, services):
    # 인자 검증에서 걸린 호출은 Tool 본문이 돌지 않았다. 고쳐서 다시 부를 수 있어야 한다
    recommender = make_recommender(
        search(connection="co-op"), search(**SEARCH), checks([1, 2, 3]), draft([3])
    )

    state = run_graph(recommender)

    assert services.calls.count("search") == 1
    assert [g.game.igdb_id for g in state["response"].games] == [3]


def test_runner_side_calls_are_not_counted(make_recommender, services):
    # 에이전트가 가격·사양·리뷰를 건너뛰면 러너가 직접 조회한다. LLM이 부른 것이 아니라 세지 않는다
    recommender = make_recommender(search(**SEARCH), draft([3]))
    ctx = AgentContext.pending(recommender.tools)

    run_graph(recommender, ctx)

    assert {"price", "hardware", "reviews"} <= set(services.calls)
    assert dict(ctx.tool_calls) == {"search_games": 1}


def test_limits_can_be_overridden(make_recommender, services):
    recommender = make_recommender(
        search(**SEARCH),
        checks([1, 2, 3]),
        reviews([3]),
        reviews([1]),
        draft([3]),
        tool_call_limits={"summarize_reviews": 1},
    )

    run_graph(recommender)

    assert services.calls.count("reviews") == 1
