import asyncio
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