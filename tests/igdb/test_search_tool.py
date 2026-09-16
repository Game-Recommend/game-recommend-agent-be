"""등록된 Tool을 Agent가 호출해 기존 IGDB 검색 함수까지 연결하는지 검증한다."""

import asyncio
import json

import pytest
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import ToolMessage

from app.agent.context import AgentContext, CandidateStore, ToolSet
from app.agent.schemas import RecommendationDraft
from app.agent.tools import build_tools
from app.clients import igdb
from app.pipeline.query_processing.conditions import GameConditions
from app.tools.game_search import GameSearchTool
from tests.agent.fakes import draft, scripted, search


def invoke_search(monkeypatch, args, rows=None, error=None):
    received = []

    async def fake_search(conditions):
        received.append(conditions)
        if error is not None:
            raise error
        return rows or []

    # LangChain Tool・サービス・実アダプターを通し、外部検索の境界だけ置き換える。
    monkeypatch.setattr(igdb, "search", fake_search)
    conditions = GameConditions(max_price_krw=10000, recommendation_count=2)
    store = CandidateStore(conditions)
    events = []
    ctx = AgentContext(
        conditions=conditions,
        store=store,
        tools=ToolSet(
            game_search=GameSearchTool(igdb.IgdbCatalogClient()),
            price=None,
            hardware=None,
            review_summary=None,
        ),
        progress=lambda *event: events.append(event),
    )
    agent = create_agent(
        scripted(search(**args), draft([])),
        build_tools(),
        context_schema=AgentContext,
        response_format=ToolStrategy(RecommendationDraft),
    )
    result = asyncio.run(agent.ainvoke({"messages": [("user", "게임 추천")]}, context=ctx))
    message = next(
        message for message in result["messages"]
        if isinstance(message, ToolMessage) and message.name == "search_games"
    )
    return json.loads(message.content), store, received, events


@pytest.mark.parametrize("args", [{}, {"genres": ["RPG"]}])
def test_agent_calls_existing_igdb_search_with_optional_arguments(monkeypatch, args):
    row = {
        "igdb_id": 123,
        "name": "Example Game",
        "steam_app_id": 456,
        "genres": ["Role-playing (RPG)"],
        "summary": "소개" * 150,
    }
    payload, store, received, events = invoke_search(monkeypatch, args, [row, row])

    assert len(received) == 1
    assert received[0]["genres"] == args.get("genres", [])
    assert received[0]["platforms"] == []
    assert received[0]["players"] is None
    assert received[0]["max_price_krw"] == 10000
    assert received[0]["recommendation_count"] == 2
    assert payload["count"] == 1
    assert payload["games"][0]["igdb_id"] == 123
    assert payload["games"][0]["on_steam"] is True
    assert payload["games"][0]["summary"] == row["summary"][:200] + "…"
    assert store.resolve([123])[0].steam_app_id == 456
    assert store.resolve([123])[0].summary == row["summary"]
    assert events == [("게임 검색", "started", None), ("게임 검색", "completed", "후보 1개")]


def test_agent_search_returns_empty_list(monkeypatch):
    payload, store, _, _ = invoke_search(monkeypatch, {})
    assert payload == {"count": 0, "games": []}
    assert store.candidates == {}


def test_agent_search_returns_error_json_on_lookup_failure(monkeypatch):
    payload, store, _, events = invoke_search(monkeypatch, {}, error=RuntimeError("offline"))
    assert "error" in payload
    assert store.candidates == {}
    assert store.warnings == ["게임 검색 호출 실패: 해당 정보를 확인할 수 없습니다."]
    assert events[-1] == ("게임 검색", "failed", None)
