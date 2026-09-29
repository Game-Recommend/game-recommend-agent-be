"""LangGraph Studio용 그래프: 서버처럼 JSON 컨텍스트로 돌려도 run()과 같은 실행인지 본다.

langgraph dev 서버는 실행마다 `graph.astream(입력, context=JSON)`을 부른다. JSON에는 컨텍스트
스키마의 필드만 남고, Studio에서 아무것도 정하지 않으면 빈 dict다. 실행 설정에 반복 상한은 없다.
"""

import asyncio

import pytest
from langgraph.errors import GraphRecursionError

from app.agent.context import AgentContext
from app.agent.progress import PipelineStageError
from app.agent.prompts import build_system_prompt
from app.agent.runner import AgentRecommender
from tests.agent.fakes import checks, draft, reviews, scripted, search

SEARCH = dict(genres=["Adventure"])


def script():
    return search(**SEARCH), checks([1, 2, 3]), reviews([3]), draft([3], "Game 3 답변")


def studio_run(graph, context):
    return asyncio.run(graph.ainvoke({"question": "q"}, context=context))


def test_studio_graph_with_empty_context_matches_run(make_recommender):
    expected = asyncio.run(make_recommender(*script()).run("q"))

    state = studio_run(make_recommender(*script()).studio_graph(), {})

    assert state["response"].model_dump() == expected.model_dump()


def test_studio_context_language_reaches_prompt_and_tools(services, toolset):
    model = scripted(*script())
    graph = AgentRecommender(services.parser, toolset, model).studio_graph()

    state = studio_run(graph, {"language": "en"})

    assert {messages[0].content for messages in model.received} == {build_system_prompt("en")}
    assert state["response"].games[0].price.check.reason == "Within budget"
    assert services.reviews.languages == ["en"]


def test_each_studio_run_gets_a_fresh_context(make_recommender):
    # 서버는 한 그래프로 실행을 거듭한다. 컨텍스트를 같이 쓰면 두 번째 실행의 Tool 호출이
    # 첫 실행의 호출 수에 이어 세어져 상한에 걸린다
    graph = make_recommender(*script(), *script()).studio_graph()

    first = studio_run(graph, {})
    second = studio_run(graph, {})

    assert second["response"].model_dump() == first["response"].model_dump()


def test_studio_schemas_show_only_question_and_language(make_recommender):
    recommender = make_recommender()
    graph = recommender.studio_graph()

    assert list(graph.get_input_jsonschema()["properties"]) == ["question"]
    context = graph.get_context_jsonschema()["properties"]
    assert list(context) == ["language"]
    assert context["language"]["enum"] == ["ko", "en"]
    # 운영 그래프는 그대로다
    assert recommender.graph.context_schema is AgentContext


def test_studio_graph_stops_the_agent_loop_where_run_does(make_recommender):
    # 호출 상한에 걸린 search를 계속 부르는 대본. 서버는 실행 설정에 반복 상한을 넣지 않으므로
    # 그래프에 묶어 둔 상한이 agent 서브그래프까지 걸려야 run()과 같다
    def looping():
        return *(search(**SEARCH) for _ in range(12)), checks([1, 2, 3]), draft([3])

    with pytest.raises(PipelineStageError) as failed:
        asyncio.run(make_recommender(*looping()).run("q"))
    assert isinstance(failed.value.__cause__, GraphRecursionError)
    with pytest.raises(GraphRecursionError):
        studio_run(make_recommender(*looping()).studio_graph(), {})
