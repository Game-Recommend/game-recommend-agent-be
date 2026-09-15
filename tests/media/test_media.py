import asyncio
import json

import httpx2 as httpx
import pytest

from app.clients.igdb_media import Artwork, pick_hero_artwork, trailer_rank
from app.clients.media import STEAM_ASSET_URL, MediaResolver
from app.clients.steamgriddb import GridAsset, GridAssets, SteamGridDBClient, normalize_name
from app.schemas.game import GameCandidate
from app.schemas.media import GameMedia
from app.tools.media import MediaTool
from tests.media.fakes import FakeGridDB, FakeIgdbMedia, FakeMedia, FakeSteamCdn

STEAM_GAME = GameCandidate(igdb_id=1, name="Elden Ring", steam_app_id=1245620)
OTHER_GAME = GameCandidate(igdb_id=2, name="League of Legends")
HERO = GridAsset(url="https://cdn2.example/hero.png", width=1920, height=620, style="alternate")
LOGO = GridAsset(url="https://cdn2.example/logo.png", width=800, height=300, style="official")


def resolve(resolver: MediaResolver, games: list[GameCandidate]) -> dict[int, GameMedia]:
    return {media.igdb_id: media for media in asyncio.run(resolver.fetch_media(games))}


def test_steamgriddb_assets_win_over_other_sources():
    cdn = FakeSteamCdn({STEAM_ASSET_URL.format(app_id=1245620, name="library_hero.jpg")})
    resolver = MediaResolver(
        FakeGridDB({1: GridAssets(hero=HERO, logo=LOGO)}),
        FakeIgdbMedia({1: "abc123XYZ_-"}, {1: Artwork(url="x", width=1920, height=1080)}),
        cdn,
    )
    media = resolve(resolver, [STEAM_GAME])[1]
    assert (media.hero_url, media.hero_source, media.hero_width) == (HERO.url, "steamgriddb", 1920)
    assert (media.logo_url, media.logo_source) == (LOGO.url, "steamgriddb")
    assert (media.trailer_youtube_id, media.trailer_source) == ("abc123XYZ_-", "igdb")
    assert cdn.checked == []  # 이미 찾은 항목은 Steam CDN을 확인하지 않는다


def test_falls_back_to_steam_cdn_then_igdb_artwork():
    hero_url = STEAM_ASSET_URL.format(app_id=1245620, name="library_hero.jpg")
    logo_url = STEAM_ASSET_URL.format(app_id=1245620, name="logo.png")
    artwork = Artwork(url="https://images.igdb.com/x.jpg", width=1920, height=1080)
    resolver = MediaResolver(
        FakeGridDB(), FakeIgdbMedia({}, {1: artwork, 2: artwork}), FakeSteamCdn({hero_url})
    )
    media = resolve(resolver, [STEAM_GAME, OTHER_GAME])
    # Steam 게임: 로고는 CDN에 없고(404) 배너는 있다
    assert media[1].logo_url is None
    assert (media[1].hero_url, media[1].hero_source) == (hero_url, "steam")
    assert media[1].hero_height == 620
    assert logo_url in resolver.steam_cdn.checked
    # 비Steam 게임: Steam CDN을 건너뛰고 IGDB 아트워크로 간다
    assert (media[2].hero_url, media[2].hero_source) == (artwork.url, "igdb")
    assert media[2].logo_url is None and media[2].trailer_youtube_id is None


def test_one_source_failure_keeps_the_others():
    resolver = MediaResolver(
        FakeGridDB(error=RuntimeError("down")), FakeIgdbMedia({2: "vid"}), FakeSteamCdn()
    )
    media = resolve(resolver, [OTHER_GAME])[2]
    assert media.hero_url is None
    assert media.trailer_youtube_id == "vid"


def test_results_are_cached_per_game():
    grid, igdb = FakeGridDB({1: GridAssets(hero=HERO)}), FakeIgdbMedia({1: "vid"})
    resolver = MediaResolver(grid, igdb, FakeSteamCdn())
    first = resolve(resolver, [STEAM_GAME])
    second = resolve(resolver, [STEAM_GAME, STEAM_GAME])
    assert first[1] == second[1]
    assert (grid.calls, igdb.calls) == (1, 1)


def test_media_tool_fills_missing_games_with_empty_media():
    client = FakeMedia([GameMedia(igdb_id=1, hero_url="h")])
    result = asyncio.run(MediaTool(client).run([STEAM_GAME, OTHER_GAME]))
    assert result[1].hero_url == "h"
    assert result[2] == GameMedia(igdb_id=2)
    assert client.requested_ids == [1, 2]


def test_trailer_rank_prefers_cinematic_and_launch_over_gameplay_and_teaser():
    names = ["Gameplay Trailer", "Teaser", "Cinematic Trailer", "Trailer", "Launch Trailer"]
    ranked = sorted(names, key=trailer_rank)
    assert ranked[:2] == ["Cinematic Trailer", "Launch Trailer"]
    assert ranked[-1] == "Teaser"


def test_hero_artwork_picks_landscape_closest_to_hero_ratio_and_fits_1080p():
    rows = [
        {"image_id": "tall", "width": 1200, "height": 1600},
        {"image_id": "small", "width": 800, "height": 300},
        {"image_id": "wide", "width": 4000, "height": 2480},
        {"image_id": "banner", "width": 3204, "height": 1358},
    ]
    artwork = pick_hero_artwork(rows)
    assert artwork is not None
    assert artwork.url.endswith("/t_1080p/banner.jpg")
    assert (artwork.width, artwork.height) == (1920, 814)
    assert pick_hero_artwork([rows[0]]) is None
    # 같은 크기 아트워크가 여럿이어도 dict 비교 없이 첫 항목을 고른다
    same = [{"image_id": f"a{i}", "width": 5000, "height": 1600} for i in range(3)]
    assert pick_hero_artwork(same).url.endswith("/t_1080p/a0.jpg")


def test_normalize_name_ignores_trademarks_case_and_punctuation():
    assert normalize_name("League of Legends™") == normalize_name("league  of legends")
    assert normalize_name("Song of Nunu") != normalize_name("League of Legends")


def _sgdb_transport(recorded: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        path = request.url.path
        if "/search/autocomplete/" in path and "League" in path:
            return httpx.Response(200, json={"success": True, "data": [
                {"id": 5304709, "name": "Song of Nunu: A League of Legends Story™"},
                {"id": 1865, "name": "League of Legends"},
            ]})
        if path.endswith("/heroes/game/1865"):
            return httpx.Response(200, json={"success": True, "data": [
                {"id": 2359, "url": "https://cdn2/hero.png", "width": 1920, "height": 620,
                 "style": "alternate"}]})
        if path.endswith("/logos/game/1865"):
            return httpx.Response(200, json={"success": True, "data": []})
        if "/steam/999" in path:
            return httpx.Response(404, json={"success": False, "errors": ["Game not found"]})
        return httpx.Response(500, json={"success": False, "errors": ["boom"]})
    return httpx.MockTransport(handler)


def test_steamgriddb_client_matches_exact_name_and_treats_404_as_missing(monkeypatch):
    recorded: list[httpx.Request] = []
    transport = _sgdb_transport(recorded)
    real_client = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.clients.steamgriddb.httpx.AsyncClient", patched)
    client = SteamGridDBClient("key")
    games = [OTHER_GAME, GameCandidate(igdb_id=3, name="Gone", steam_app_id=999)]
    assets = asyncio.run(client.fetch_assets(games))

    assert assets[2].hero == GridAsset(url="https://cdn2/hero.png", width=1920, height=620,
                                       style="alternate")
    assert assets[2].logo is None
    assert assets[3] == GridAssets()  # 404는 실패가 아니라 "없음"이다
    hero_request = next(r for r in recorded if r.url.path.endswith("/heroes/game/1865"))
    assert hero_request.headers["Authorization"] == "Bearer key"
    assert dict(hero_request.url.params)["nsfw"] == "false"
    assert dict(hero_request.url.params)["types"] == "static"


def test_steamgriddb_client_requires_key():
    with pytest.raises(ValueError):
        SteamGridDBClient("")


def test_game_media_serializes_for_frontend():
    media = GameMedia(igdb_id=1, hero_url="h", hero_width=1920, hero_height=620,
                      hero_source="steamgriddb", trailer_youtube_id="v", trailer_source="igdb")
    payload = json.loads(media.model_dump_json())
    assert payload["logo_url"] is None
    assert payload["trailer_youtube_id"] == "v"
