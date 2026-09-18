"""IGDB 어댑터가 search() 행을 GameCandidate로 옮기는지, Twitch 앱 토큰을 재사용하는지 검증한다.

실제 IGDB 호출은 하지 않는다. 토큰 검사는 igdb 모듈의 httpx 참조를 MockTransport로 바꾼다.
"""

import asyncio
import types

import httpx2

from app.clients import igdb
from app.clients.igdb import IgdbCatalogClient, TwitchAppToken, to_candidate
from app.config import Settings
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


# ---------- Twitch 앱 토큰 재사용 ----------


def igdb_http(monkeypatch, *, reject: frozenset[str] = frozenset(), expires_in: int = 5_000_000):
    """Twitch 토큰 발급과 IGDB 두 엔드포인트를 흉내 낸다. reject에 든 토큰은 401로 거부한다."""
    calls: list[httpx2.Request] = []
    issued = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal issued
        calls.append(request)
        if str(request.url) == igdb.TOKEN_URL:
            issued += 1
            payload = {"access_token": f"token-{issued}", "expires_in": expires_in}
            return httpx2.Response(200, json=payload)
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token in reject:
            return httpx2.Response(401)
        if request.url.path.endswith("/games"):
            return httpx2.Response(200, json=[{"id": 1942, "name": "The Witcher 3"}])
        return httpx2.Response(200, json=[])

    def make_client(**kwargs):
        return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))

    monkeypatch.setattr(igdb, "httpx", types.SimpleNamespace(AsyncClient=make_client))
    monkeypatch.setattr(igdb, "_app_token", TwitchAppToken())
    settings = Settings(igdb_client_id="id", igdb_client_secret="secret", _env_file=None)
    monkeypatch.setattr(igdb, "get_settings", lambda: settings)
    return calls


def token_requests(calls: list[httpx2.Request]) -> int:
    return sum(str(call.url) == igdb.TOKEN_URL for call in calls)


def test_search_reuses_twitch_token_across_calls(monkeypatch):
    calls = igdb_http(monkeypatch)
    rows = asyncio.run(igdb.search({}))
    asyncio.run(igdb.search({"genres": ["Horror"]}))

    assert [row["name"] for row in rows] == ["The Witcher 3"]
    igdb_calls = [call for call in calls if call.url.host == "api.igdb.com"]
    assert token_requests(calls) == 1  # 두 번째 검색은 토큰을 다시 받지 않는다
    assert len(igdb_calls) == 4  # 검색마다 games + game_time_to_beats
    assert {call.headers["Authorization"] for call in igdb_calls} == {"Bearer token-1"}
    assert {call.headers["Client-ID"] for call in igdb_calls} == {"id"}


def test_search_refetches_token_when_igdb_rejects_it(monkeypatch):
    calls = igdb_http(monkeypatch, reject=frozenset({"token-1"}))
    rows = asyncio.run(igdb.search({}))

    assert [row["name"] for row in rows] == ["The Witcher 3"]
    # 토큰 → games(401) → 새 토큰 → games → game_time_to_beats
    assert [call.url.host for call in calls] == [
        "id.twitch.tv", "api.igdb.com", "id.twitch.tv", "api.igdb.com", "api.igdb.com",
    ]
    assert calls[-1].headers["Authorization"] == "Bearer token-2"


def test_search_refetches_token_after_expiry(monkeypatch):
    calls = igdb_http(monkeypatch, expires_in=90)  # 만료 1분 전에 갱신하므로 30초 뒤가 기한이다
    clock = [1000.0]
    monkeypatch.setattr(igdb, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))

    asyncio.run(igdb.search({}))
    clock[0] += 29
    asyncio.run(igdb.search({}))
    assert token_requests(calls) == 1

    clock[0] += 2
    asyncio.run(igdb.search({}))
    assert token_requests(calls) == 2
