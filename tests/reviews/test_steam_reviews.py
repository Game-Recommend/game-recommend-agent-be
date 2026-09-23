import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.clients.steam_reviews import SteamReviewSummaryClient
from app.schemas.game import GameCandidate


def test_game_without_steam_app_id_is_skipped():
    client = SteamReviewSummaryClient.__new__(SteamReviewSummaryClient)

    client._collect_all_reviews = AsyncMock()

    games = [
        GameCandidate(
            igdb_id=1,
            name="Steam ID 없는 게임",
            steam_app_id=None,
        )
    ]

    result = asyncio.run(client.summarize(games))

    assert result == []
    client._collect_all_reviews.assert_not_called()

def test_korean_reviews_are_used_without_english_when_enough():
    client = SteamReviewSummaryClient.__new__(SteamReviewSummaryClient)

    korean_reviews = [
        {
            "text": f"한국어 리뷰 {i}",
            "source": "steam",
            "language": "koreana",
            "positive": True,
            "votes_up": 100 - i,
            "source_url": "https://example.com",
        }
        for i in range(20)
    ]

    client._get_steam_reviews = AsyncMock(
        side_effect=[korean_reviews]
    )

    result = asyncio.run(
        client._collect_steam_reviews(
            app_id=413150,
            target_count=20,
        )
    )

    assert len(result) == 20
    assert client._get_steam_reviews.call_count == 1
    assert result == korean_reviews

def test_english_reviews_supplement_korean_when_not_enough():
    client = SteamReviewSummaryClient.__new__(SteamReviewSummaryClient)

    korean_reviews = [
        {
            "text": f"한국어 리뷰 {i}",
            "source": "steam",
            "language": "koreana",
            "positive": True,
            "votes_up": 100 - i,
            "source_url": "https://example.com/korean",
        }
        for i in range(5)
    ]

    english_reviews = [
        {
            "text": f"English review {i}",
            "source": "steam",
            "language": "english",
            "positive": True,
            "votes_up": 50 - i,
            "source_url": "https://example.com/english",
        }
        for i in range(20)
    ]

    client._get_steam_reviews = AsyncMock(
        side_effect=[korean_reviews, english_reviews]
    )

    result = asyncio.run(
        client._collect_steam_reviews(
            app_id=413150,
            target_count=20,
        )
    )

    assert len(result) == 20
    assert client._get_steam_reviews.call_count == 2
    assert sum(review["language"] == "koreana" for review in result) == 5
    assert sum(review["language"] == "english" for review in result) == 15

def test_reviews_are_sorted_by_votes_up():
    client = SteamReviewSummaryClient.__new__(SteamReviewSummaryClient)

    reviews = [
        {"text": "리뷰 A", "votes_up": 3},
        {"text": "리뷰 B", "votes_up": 100},
        {"text": "리뷰 C", "votes_up": 20},
    ]

    result = asyncio.run(
        client._select_helpful_reviews(
            reviews,
            limit=2,
        )
    )

    assert len(result) == 2
    assert result[0]["votes_up"] == 100
    assert result[1]["votes_up"] == 20

def test_summary_prompt_asks_for_the_request_language():
    client = SteamReviewSummaryClient.__new__(SteamReviewSummaryClient)
    client.model = "gpt-4o-mini"
    create = AsyncMock(return_value=SimpleNamespace(output_text=" A tight, fast roguelike. "))
    client.llm = SimpleNamespace(responses=SimpleNamespace(create=create))
    # 수집 언어는 요청 언어와 무관하다. 한국어 리뷰를 읽고 영어 한줄평을 쓴다
    reviews = [{"text": "전투가 빠르고 손맛이 좋다 " * 8, "source": "steam", "positive": True}]

    english = asyncio.run(client._summarize_reviews("Hades", reviews, "en"))
    asyncio.run(client._summarize_reviews("Hades", reviews))

    english_prompt, korean_prompt = (call.kwargs["input"] for call in create.call_args_list)
    assert "영어 한줄평을 작성하세요." in english_prompt
    assert "한국어 한줄평을 작성하세요." in korean_prompt
    assert english == "A tight, fast roguelike."


def test_summary_without_reviews_follows_the_request_language():
    client = SteamReviewSummaryClient.__new__(SteamReviewSummaryClient)
    client._semaphore = asyncio.Semaphore(8)
    client._collect_all_reviews = AsyncMock(return_value=[])
    games = [GameCandidate(igdb_id=1, name="Hades", steam_app_id=1145360)]

    english = asyncio.run(client.summarize(games, language="en"))
    korean = asyncio.run(client.summarize(games))

    assert english[0].summary == "Not enough reviews were available to summarize."
    assert korean[0].summary == "리뷰 정보를 충분히 확보하지 못했습니다."
