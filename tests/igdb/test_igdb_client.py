"""IGDB 어댑터가 search() 행을 GameCandidate로 옮기는지 검증. 실제 IGDB 호출은 하지 않는다."""

import asyncio

from app.clients import igdb
from app.clients.igdb import IgdbCatalogClient, to_candidate
from app.pipeline.query_processing.conditions import GameConditions

ROW = {
    "igdb_id": 1942, "name": "The Witcher 3", "steam_app_id": 292030,
    "genres": ["Role-playing (RPG)", "Adventure"], "themes": ["Fantasy", "Open world"],
    "platforms": ["PC (Microsoft Windows)", "PlayStation 5"],
    "summary": "Geralt hunts monsters.", "source_url": "https://www.igdb.com/games/the-witcher-3",
    "playtime_hours": 51.5,
}


def test_to_candidate_keeps_answer_material():
    candidate = to_candidate(ROW)

    assert candidate.igdb_id == 1942
    assert candidate.steam_app_id == 292030
    assert candidate.genres == ["Role-playing (RPG)", "Adventure"]
    assert candidate.themes == ["Fantasy", "Open world"]
    assert candidate.summary == "Geralt hunts monsters."
    assert candidate.playtime_hours == 51.5


def test_to_candidate_tolerates_missing_optional_fields():
    candidate = to_candidate({"igdb_id": 7, "name": "Bare", "summary": None, "platforms": None})

    assert candidate.steam_app_id is None
    assert candidate.summary is None
    assert candidate.genres == [] and candidate.themes == [] and candidate.platforms == []
    assert candidate.playtime_hours is None


def test_client_passes_conditions_as_dict_and_maps_rows(monkeypatch):
    received = {}

    async def fake_search(conditions: dict) -> list[dict]:
        received.update(conditions)
        return [ROW]

    monkeypatch.setattr(igdb, "search", fake_search)
    conditions = GameConditions(genres=["RPG"], players=1, max_playtime_hours=60)

    result = asyncio.run(IgdbCatalogClient().search(conditions))

    assert received["genres"] == ["RPG"]
    assert received["players"] == 1
    assert received["max_playtime_hours"] == 60
    assert [game.name for game in result] == ["The Witcher 3"]
