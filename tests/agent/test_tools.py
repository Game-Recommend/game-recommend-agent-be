"""Tool 어댑터: 팀원 도구를 부르고, store에 전체 결과를 쌓고, LLM에는 압축 JSON을 돌려준다."""

import asyncio
import json

import pytest

from app.agent.context import AgentContext, CandidateStore
from app.agent.tools import build_tools
from app.agent.tools.hardware import assess
from app.agent.tools.price import fetch_prices
from app.agent.tools.reviews import summarize
from app.agent.tools.search import SearchGamesArgs, search_candidates
from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.hardware import HardwareSpecs


def test_tool_schemas_hide_runtime_and_server_criteria():
    tools = {tool.name: tool for tool in build_tools()}
    assert set(tools) == {"search_games", "get_prices", "assess_hardware", "summarize_reviews"}
    for name in ("get_prices", "assess_hardware", "summarize_reviews"):
        assert list(tools[name].tool_call_schema.model_json_schema()["properties"]) == ["igdb_ids"]
    search = tools["search_games"].tool_call_schema.model_json_schema()["properties"]
    assert "max_price_krw" not in search and "hardware" not in search
    assert {"genres", "players", "play_mode", "platforms"} <= set(search)
    for tool in tools.values():
        assert tool.description.strip()


def test_fetch_prices_updates_store_and_returns_compact_payload(context, services):
    payload = asyncio.run(fetch_prices(context, [3, 1]))

    assert services.calls == ["price"]
    assert payload["budget_krw"] == 100
    assert payload["prices"] == [
        {"igdb_id": 3, "amount_krw": 100, "status": "met", "reason": "예산 이하"},
        {"igdb_id": 1, "amount_krw": 150, "status": "unmet", "reason": "예산 초과"},
    ]
    assert set(context.store.prices) == {1, 3}
    assert context.store.prices[3].quote.amount_krw == 100


def test_assess_updates_store_with_user_hardware(context, services):
    payload = asyncio.run(assess(context, [2, 3]))

    assert services.calls == ["hardware"]
    assert payload["user_hardware"] == {"cpu": "test CPU"}
    assert [(a["igdb_id"], a["status"]) for a in payload["assessments"]] == [
        (2, "unknown"),
        (3, "met"),
    ]
    assert context.store.hardware[3].check.status == "met"


def test_search_keeps_server_criteria_and_stores_candidates(toolset, services):
    conditions = GameConditions(
        max_price_krw=100,
        hardware=HardwareSpecs(cpu="c"),
        preferences=["스토리"],
        recommendation_count=2,
    )
    context = AgentContext(conditions=conditions, store=CandidateStore(conditions), tools=toolset)
    args = SearchGamesArgs(genres=["Adventure"], players=2, connection="online")

    payload = asyncio.run(search_candidates(context, args))

    sent = services.catalog.conditions
    assert sent.genres == ["Adventure"] and sent.players == 2 and sent.connection == "online"
    assert sent.max_price_krw == 100 and sent.hardware.cpu == "c" and sent.preferences == ["스토리"]
    assert payload["count"] == 3
    assert payload["games"][0] == {
        "igdb_id": 1,
        "name": "Game 1",
        "genres": [],
        "themes": [],
        "platforms": [],
        "playtime_hours": None,
        "on_steam": True,
        "summary": None,
    }
    assert list(context.store.candidates) == [1, 2, 3]


def test_summarize_marks_missing_reviews_as_null(context, services):
    services.reviews.summarize = _only_first(services.reviews.summarize)
    payload = asyncio.run(summarize(context, [3, 2]))

    assert payload["reviews"] == [
        {"igdb_id": 3, "name": "Game 3", "summary": "테스트 요약"},
        {"igdb_id": 2, "name": "Game 2", "summary": None},
    ]
    assert set(context.store.reviews) == {3}


def _only_first(summarize):
    async def wrapper(games):
        return await summarize(games[:1])

    return wrapper


def test_run_stage_reports_progress_and_returns_json(context):
    events = []
    context.progress = lambda stage, status, detail: events.append((stage, status, detail))

    async def work():
        return {"count": 2}

    text = asyncio.run(
        context.run_stage("게임 검색", work(), detail=lambda p: f"후보 {p['count']}개")
    )

    assert json.loads(text) == {"count": 2}
    assert events == [("게임 검색", "started", None), ("게임 검색", "completed", "후보 2개")]
    assert context.stages == ["게임 검색"]


def test_run_stage_turns_failures_into_error_json_with_warning(context):
    async def fail():
        raise RuntimeError("boom")

    text = asyncio.run(context.run_stage("가격", fail()))

    assert "가격 조회에 실패" in json.loads(text)["error"]
    assert context.store.warnings == ["가격 호출 실패: 해당 정보를 확인할 수 없습니다."]


def test_run_stage_times_out_like_pipeline_stage(context):
    context.stage_timeout_seconds = 0.01

    async def hang():
        await asyncio.sleep(1)
        return {}

    text = asyncio.run(context.run_stage("리뷰 요약", hang()))

    assert "error" in json.loads(text)
    assert context.store.warnings == ["리뷰 요약 호출 실패: 해당 정보를 확인할 수 없습니다."]


def test_unknown_igdb_id_is_returned_to_model_without_warning(context, services):
    text = asyncio.run(context.run_stage("가격", fetch_prices(context, [1, 99])))

    assert "[99]" in json.loads(text)["error"]
    assert context.store.warnings == []
    assert services.calls == []  # 팀원 도구를 부르기 전에 거른다


@pytest.mark.parametrize("igdb_ids", [[], [3]])
def test_summarize_handles_empty_and_single(context, igdb_ids):
    payload = asyncio.run(summarize(context, igdb_ids))
    assert [r["igdb_id"] for r in payload["reviews"]] == igdb_ids
