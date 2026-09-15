"""미디어 단계는 선택 사항이다. 있으면 추천 카드에 붙고, 실패해도 추천은 그대로 나간다."""

import asyncio

from app.pipeline.orchestrator import RecommendationOrchestrator
from app.schemas.media import GameMedia
from app.tools.game_search import GameSearchTool
from app.tools.hardware import HardwareTool
from app.tools.media import MediaTool
from app.tools.price import PriceTool
from app.tools.review_summary import ReviewSummaryTool
from tests.media.fakes import FakeMedia


def build(services, media_client):
    return RecommendationOrchestrator(
        parser=services.parser,
        game_search=GameSearchTool(services.catalog),
        price=PriceTool(services.price_hardware),
        hardware=HardwareTool(services.price_hardware),
        review_summary=ReviewSummaryTool(services.reviews),
        answerer=services.answerer,
        media=MediaTool(media_client),
    )


def test_media_is_attached_only_to_selected_games(services):
    client = FakeMedia([GameMedia(igdb_id=3, hero_url="h", trailer_youtube_id="v")], services.calls)
    response = asyncio.run(build(services, client).run("게임 추천"))

    assert response.games[0].game.igdb_id == 3
    assert response.games[0].media.hero_url == "h"
    assert response.games[0].media.trailer_youtube_id == "v"
    assert client.requested_ids == [3]  # 추천 개수로 자른 뒤에만 조회한다
    assert all(result.media is None for result in response.excluded_games)


def test_media_failure_only_adds_warning(services):
    client = FakeMedia(error=RuntimeError("down"), calls=services.calls)
    response = asyncio.run(build(services, client).run("게임 추천"))

    assert response.games[0].game.igdb_id == 3
    assert response.games[0].media is None
    assert any(warning.startswith("미디어 호출 실패") for warning in response.warnings)


def test_without_media_tool_field_is_null(recommender):
    response = asyncio.run(recommender.run("게임 추천"))
    assert response.games[0].media is None
