"""서버 시작 시 실제 어댑터 조립. 클라이언트를 만들기만 하고 외부 호출은 하지 않는다."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.agent.runner import AgentRecommender
from app.assembly import assemble, missing_settings
from app.clients.igdb import IgdbCatalogClient
from app.clients.media import MediaResolver
from app.clients.routing import RoutedHardwareClient, RoutedPriceClient
from app.clients.steam_reviews import SteamReviewSummaryClient
from app.clients.steam_store import SteamStoreClient
from app.config import Settings, get_settings
from app.main import app
from app.pipeline.final_answer.llm_answerer import OpenAIAnswerer
from app.pipeline.orchestrator import RecommendationOrchestrator
from app.pipeline.query_processing.llm_parser import LLMQueryParser

FULL = {
    "api_key": "k",
    "recommender_mode": "pipeline",
    "openai_api_key": "sk-test",
    "igdb_client_id": "id",
    "igdb_client_secret": "secret",
    "steamgriddb_api_key": "grid",
}


@pytest.fixture(autouse=True)
def openai_env(monkeypatch):
    # 리뷰 클라이언트(steam_reviews.py)는 생성자에서 환경 변수 OPENAI_API_KEY를 직접 읽는다
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


def settings(**overrides) -> Settings:
    return Settings(**{**FULL, **overrides}, _env_file=None)


def test_missing_required_keys_skip_assembly():
    # openai_env 픽스처가 넣은 환경 변수와 무관하게 비어 있는 설정을 만든다
    empty = settings(openai_api_key="", igdb_client_id="", igdb_client_secret="")

    assert missing_settings(empty) == ["OPENAI_API_KEY", "IGDB_CLIENT_ID", "IGDB_CLIENT_SECRET"]
    assert assemble(empty) is None
    assert assemble(settings(igdb_client_secret="")) is None


def test_full_settings_wire_each_role_implementation():
    assembled = assemble(settings())
    try:
        recommender = assembled.recommender
        assert isinstance(recommender, RecommendationOrchestrator)
        assert isinstance(recommender.parser, LLMQueryParser)
        assert isinstance(recommender.game_search.client, IgdbCatalogClient)
        assert isinstance(recommender.price.client, RoutedPriceClient)
        assert isinstance(recommender.hardware.client, RoutedHardwareClient)
        assert isinstance(recommender.price.client.steam, SteamStoreClient)
        # 가격·사양이 같은 Steam 인스턴스를 써야 appdetails 조회를 공유한다
        assert recommender.hardware.client.steam is recommender.price.client.steam
        assert isinstance(recommender.review_summary.client, SteamReviewSummaryClient)
        assert isinstance(recommender.answerer, OpenAIAnswerer)
        assert isinstance(recommender.media.client, MediaResolver)
        assert recommender.media.client.steamgriddb is not None
    finally:
        asyncio.run(assembled.aclose())


def test_media_without_steamgriddb_key_still_uses_igdb():
    assembled = assemble(settings(steamgriddb_api_key=""))
    try:
        assert assembled.recommender.media.client.steamgriddb is None
        assert assembled.recommender.media.client.igdb is not None
    finally:
        asyncio.run(assembled.aclose())


def test_first_request_assembles_when_lifespan_did_not_run(recommender, monkeypatch):
    from app import assembly
    from app.api import dependencies

    fake = assembly.AssembledRecommender(recommender, http=None, openai=None)
    monkeypatch.setattr(assembly, "assemble", lambda settings: fake)
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings())
    # with 블록이 아니어서 lifespan이 돌지 않는다
    client = TestClient(app, headers={"X-API-Key": "k"})
    try:
        response = client.post("/recommend", json={"question": "게임 추천"})
        assert response.status_code == 200
        assert response.json()["answer"] == "테스트 답변"
        assert app.state.recommender is recommender
    finally:
        app.state.recommender = None
        app.state.assembled = None
    assert dependencies.missing_settings(settings()) == []


def test_unconfigured_503_names_missing_keys(monkeypatch):
    empty = settings(openai_api_key="", igdb_client_id="", igdb_client_secret="")
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: empty)
    with TestClient(app, headers={"X-API-Key": "k"}) as client:
        response = client.post("/recommend", json={"question": "게임 추천"})
    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_lifespan_assembles_from_overridden_settings_and_releases(monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, get_settings, settings)
    with TestClient(app) as client:
        assert isinstance(app.state.recommender, RecommendationOrchestrator)
        assert client.get("/health").status_code == 200
    assert getattr(app.state, "recommender", None) is None


def test_agent_mode_wires_same_tools_into_agent_recommender():
    assembled = assemble(settings(recommender_mode="agent", openai_agent_model="gpt-test"))
    try:
        recommender = assembled.recommender
        assert isinstance(recommender, AgentRecommender)
        assert isinstance(recommender.parser, LLMQueryParser)
        tools = recommender.tools
        assert isinstance(tools.game_search.client, IgdbCatalogClient)
        assert isinstance(tools.price.client, RoutedPriceClient)
        assert isinstance(tools.hardware.client, RoutedHardwareClient)
        assert tools.hardware.client.steam is tools.price.client.steam
        assert isinstance(tools.review_summary.client, SteamReviewSummaryClient)
        assert isinstance(tools.media.client, MediaResolver)
        assert recommender.agent is not None
    finally:
        asyncio.run(assembled.aclose())


def test_default_mode_is_agent():
    without_mode = {key: value for key, value in FULL.items() if key != "recommender_mode"}
    assert Settings(**without_mode, _env_file=None).recommender_mode == "agent"
