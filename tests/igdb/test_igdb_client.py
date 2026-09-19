"""IGDB 어댑터가 search() 행을 GameCandidate로 옮기는지, Twitch 앱 토큰을 재사용하는지 검증한다.

실제 IGDB 호출은 하지 않는다. 토큰 검사는 igdb 모듈의 httpx 참조를 MockTransport로 바꾼다.
"""

import asyncio
import types

import httpx2

from app.clients import igdb
from app.clients.igdb import (
    IgdbCatalogClient,
    TwitchAppToken,
    build_filters,
    classify,
    keyword_stem,
    matching_keyword_ids,
    to_candidate,
)
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


# ---------- 검색 조건과 정렬 ----------


def test_filters_default_to_pc_main_games():
    where = build_filters({})

    assert "game_type = (0,8,9,10)" in where
    assert any(clause.startswith("total_rating_count >=") for clause in where)
    # 플랫폼을 말하지 않으면 PC로 본다
    assert where[-1] == '(platforms.name ~ "pc (microsoft windows)")'
    assert len(where) == 3


def test_categories_are_filtered_by_id_not_by_name():
    where = build_filters({"genres": ["RPG", "Horror"]})

    # RPG는 장르(12), Horror는 테마(19)다
    assert "genres = [12]" in where and "themes = [19]" in where
    assert not any(".name ~" in clause and "platforms" not in clause for clause in where)


def test_two_categories_of_the_same_kind_use_contains_all():
    # Fantasy와 Action은 둘 다 테마다. 이름 조건을 둘 걸면 IGDB는 한 원소가 두 이름을 동시에
    # 만족해야 한다고 읽어 0건을 돌려준다("판타지 액션 RPG"의 후보가 0개였다)
    where = build_filters({"genres": ["Fantasy", "Action", "Role-playing (RPG)", "fantasy"]})

    assert "themes = [17,1]" in where
    assert "genres = [12]" in where


def test_play_mode_words_in_genres_become_game_modes():
    # 파서가 협동을 genres=["Cooperative"]로도 낸다. IGDB에 그런 장르·테마는 없고 게임 모드다
    where = build_filters({"genres": ["Cooperative"], "play_mode": "cooperative", "players": 2})

    assert "game_modes = [3]" in where
    assert not any(clause.startswith(("genres", "themes")) for clause in where)


def test_play_modes_combine_into_one_contains_all_clause():
    assert "game_modes = [2]" in build_filters({"play_mode": "competitive"})
    assert "game_modes = [1]" in build_filters({"play_mode": "singleplayer", "players": 1})
    # 게임 모드도 같은 배열이라 이름 조건 둘은 0건이었다
    both = build_filters({"genres": ["Multiplayer"], "play_mode": "cooperative"})
    assert "game_modes = [2,3]" in both


def test_unknown_categories_are_returned_for_keyword_lookup():
    genres, themes, modes, others = classify({"genres": ["Story-rich", "Puzzle", "Competition"]})

    assert (genres, themes, modes) == ([9], [], [])
    assert others == ["story-rich", "competition"]
    # 키워드는 뜻이 넓은 말을 푼 것이라 하나만 맞아도 된다
    assert "keywords = (7,8)" in build_filters({"genres": ["Story"]}, keyword_ids=[7, 8])
    assert not any(c.startswith("keywords") for c in build_filters({"genres": ["Story"]}))


def test_keyword_stem_and_word_start_matching():
    assert keyword_stem("story") == "story"
    assert keyword_stem("competition") == "competit"  # competitive도 찾는다
    assert keyword_stem("Story-rich".lower()) == "story rich"
    rows = [
        {"id": 1, "name": "story rich"},
        {"id": 2, "name": "emotional story"},
        {"id": 3, "name": "alternate history"},  # 부분 일치로는 딸려 온다
        {"id": 4, "name": "branching storyline"},
        {"id": 5, "name": "competitive multiplayer"},
    ]

    assert matching_keyword_ids(rows, ["story"]) == [1, 2, 4]
    assert matching_keyword_ids(rows, ["story rich"]) == [1]
    assert matching_keyword_ids(rows, ["story", "competit"]) == [1, 2, 4, 5]


def test_platform_aliases_and_explicit_platform_replace_the_pc_default():
    assert build_filters({"platforms": ["노트북"]})[-1] == (
        '(platforms.name ~ "pc (microsoft windows)")'
    )
    console = build_filters({"platforms": ["PS5", "모바일"]})[-1]
    assert console == (
        '(platforms.name ~ "playstation 5" | platforms.name ~ "android" | platforms.name ~ "ios")'
    )


def test_search_sorts_by_rating_count_not_by_id(monkeypatch):
    calls = igdb_http(monkeypatch)
    asyncio.run(igdb.search({"genres": ["Puzzle"]}))

    body = next(c for c in calls if c.url.path.endswith("/games")).content.decode()
    assert "sort total_rating_count desc; limit 500;" in body
    assert "sort id" not in body
    assert "where game_type = (0,8,9,10) & total_rating_count >= 5 & genres = [9] &" in body


def test_unknown_category_is_resolved_to_keyword_ids_before_searching(monkeypatch):
    keywords = [{"id": 11, "name": "story rich"}, {"id": 12, "name": "alternate history"}]
    calls = igdb_http(monkeypatch, keywords=keywords)

    rows = asyncio.run(igdb.search({"genres": ["Story"]}))

    assert [row["name"] for row in rows] == ["The Witcher 3"]
    lookup = next(c for c in calls if c.url.path.endswith("/keywords")).content.decode()
    assert 'name ~ *"story"*' in lookup
    games = next(c for c in calls if c.url.path.endswith("/games")).content.decode()
    assert "keywords = (11)" in games  # history는 단어의 시작이 아니라 빠진다


def test_category_without_any_keyword_yields_no_candidates(monkeypatch):
    # 조건을 버리고 아무 게임이나 돌려주지 않는다
    calls = igdb_http(monkeypatch, keywords=[])

    assert asyncio.run(igdb.search({"genres": ["Zzzz"]})) == []
    assert not any(c.url.path.endswith("/games") for c in calls)


def test_known_categories_do_not_call_the_keyword_endpoint(monkeypatch):
    calls = igdb_http(monkeypatch)
    asyncio.run(igdb.search({"genres": ["Puzzle"], "play_mode": "cooperative"}))

    assert not any(c.url.path.endswith("/keywords") for c in calls)


def _game(igdb_id, genres=("Adventure",), themes=("Fantasy",), modes=()):
    return {
        "id": igdb_id,
        "name": f"Game {igdb_id}",
        "genres": [{"name": name} for name in genres],
        "themes": [{"name": name} for name in themes],
        "multiplayer_modes": list(modes),
    }


def test_excluded_category_matches_by_substring(monkeypatch):
    games = [
        _game(1, genres=("Turn-based strategy (TBS)",)),
        _game(2, genres=("Real Time Strategy (RTS)",)),
        _game(3),
        _game(4, themes=()),  # 테마를 모르면 제외 여부를 확인할 수 없어 뺀다
    ]
    igdb_http(monkeypatch, games=games)

    turn_based = asyncio.run(igdb.search({"excluded_genres": ["Turn-based"]}))
    strategy = asyncio.run(igdb.search({"excluded_genres": ["Strategy"]}))

    assert [row["igdb_id"] for row in turn_based] == [2, 3]
    assert [row["igdb_id"] for row in strategy] == [3]


def test_players_filter_follows_connection(monkeypatch):
    games = [
        _game(1, modes=[{"onlinemax": 4}]),
        _game(2, modes=[{"offlinecoopmax": 4}]),
        _game(3),  # 멀티플레이 정보가 없으면 인원 조건을 확인할 수 없다
    ]
    igdb_http(monkeypatch, games=games)

    def ids(conditions):
        return [row["igdb_id"] for row in asyncio.run(igdb.search(conditions))]

    assert ids({"players": 4}) == [1, 2]
    assert ids({"players": 4, "connection": "online"}) == [1]
    assert ids({"players": 4, "connection": "local"}) == [2]


# ---------- Twitch 앱 토큰 재사용 ----------


def igdb_http(
    monkeypatch,
    *,
    reject: frozenset[str] = frozenset(),
    expires_in: int = 5_000_000,
    games: list[dict] | None = None,
    keywords: list[dict] | None = None,
):
    """Twitch 토큰 발급과 IGDB 두 엔드포인트를 흉내 낸다. reject에 든 토큰은 401로 거부한다."""
    games = games if games is not None else [{"id": 1942, "name": "The Witcher 3"}]
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
            return httpx2.Response(200, json=games)
        if request.url.path.endswith("/keywords"):
            return httpx2.Response(200, json=keywords or [])
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
