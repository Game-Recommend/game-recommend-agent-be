"""미디어 담당: SteamGridDB·Steam CDN·IGDB를 폴백 순서로 합쳐 추천 카드 미디어를 만든다.

우선순위
- 로고: SteamGridDB 로고(official/white) → Steam CDN logo.png(Steam 게임만) → 없음
  (없으면 프론트가 게임 이름을 표시한다)
- 배너: SteamGridDB 히어로 → Steam CDN library_hero.jpg → IGDB 가로 아트워크 t_1080p → 없음
- 트레일러: IGDB game_videos의 YouTube ID → 없음

Steam CDN 라이브러리 에셋은 `store_item_assets/steam/apps/{appid}/` 아래에 있고 스토어 API 응답에
나오지 않으므로 HEAD로 존재를 확인한다. 오래된 게임은 없어서 404가 난다.
결과는 igdb_id별로 프로세스 메모리에 캐시한다. 미디어는 거의 바뀌지 않고, SteamGridDB·IGDB 호출을
아낀다. 소스 하나가 실패하면 경고만 남기고 나머지 소스로 채운다.

동작 확인: `python -m app.clients.media "Elden Ring" "League of Legends"`
"""

import asyncio
import json
import logging
import sys

import httpx2 as httpx

from app.clients.igdb_media import Artwork, IgdbMediaClient
from app.clients.steamgriddb import GridAssets, SteamGridDBClient
from app.schemas.game import GameCandidate
from app.schemas.media import GameMedia

logger = logging.getLogger(__name__)

STEAM_ASSET_URL = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/{name}"
STEAM_HERO_SIZE = (1920, 620)


class SteamCdnAssets:
    """Steam 라이브러리 에셋 존재 확인. 키가 없고 HEAD 한 번이면 된다."""

    def __init__(self, *, timeout: float = 10):
        self.timeout = timeout

    async def exists(self, url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.head(url)
        except httpx.HTTPError as exc:
            logger.warning("Steam CDN check failed: %s (%s)", url, type(exc).__name__)
            return False
        return response.status_code == 200


class MediaResolver:
    def __init__(
        self,
        steamgriddb: SteamGridDBClient | None,
        igdb: IgdbMediaClient | None,
        steam_cdn: SteamCdnAssets | None = None,
    ):
        if steamgriddb is None and igdb is None:
            raise ValueError("SteamGridDB나 IGDB 중 하나는 있어야 합니다.")
        self.steamgriddb = steamgriddb
        self.igdb = igdb
        self.steam_cdn = steam_cdn if steam_cdn is not None else SteamCdnAssets()
        self._cache: dict[int, GameMedia] = {}

    async def fetch_media(self, games: list[GameCandidate]) -> list[GameMedia]:
        unseen = {game.igdb_id: game for game in games if game.igdb_id not in self._cache}
        pending = list(unseen.values())
        if pending:
            grid, trailers, artworks = await asyncio.gather(
                self._grid_assets(pending), self._trailers(pending), self._artworks(pending)
            )
            resolved = await asyncio.gather(
                *(
                    self._resolve(game, grid.get(game.igdb_id), trailers.get(game.igdb_id),
                                  artworks.get(game.igdb_id))
                    for game in pending
                )
            )
            for media in resolved:
                self._cache[media.igdb_id] = media
        return [self._cache[game.igdb_id] for game in games if game.igdb_id in self._cache]

    async def _resolve(
        self,
        game: GameCandidate,
        grid: GridAssets | None,
        trailer: str | None,
        artwork: Artwork | None,
    ) -> GameMedia:
        media = GameMedia(igdb_id=game.igdb_id)
        if grid is not None and grid.logo is not None:
            media.logo_url, media.logo_source = grid.logo.url, "steamgriddb"
        if grid is not None and grid.hero is not None:
            media.hero_url, media.hero_source = grid.hero.url, "steamgriddb"
            media.hero_width, media.hero_height = grid.hero.width, grid.hero.height

        if game.steam_app_id is not None and (media.logo_url is None or media.hero_url is None):
            logo_url = STEAM_ASSET_URL.format(app_id=game.steam_app_id, name="logo.png")
            hero_url = STEAM_ASSET_URL.format(app_id=game.steam_app_id, name="library_hero.jpg")
            logo_ok, hero_ok = await asyncio.gather(
                self.steam_cdn.exists(logo_url) if media.logo_url is None else _false(),
                self.steam_cdn.exists(hero_url) if media.hero_url is None else _false(),
            )
            if logo_ok:
                media.logo_url, media.logo_source = logo_url, "steam"
            if hero_ok:
                media.hero_url, media.hero_source = hero_url, "steam"
                media.hero_width, media.hero_height = STEAM_HERO_SIZE

        if media.hero_url is None and artwork is not None:
            media.hero_url, media.hero_source = artwork.url, "igdb"
            media.hero_width, media.hero_height = artwork.width, artwork.height
        if trailer is not None:
            media.trailer_youtube_id, media.trailer_source = trailer, "igdb"
        return media

    async def _grid_assets(self, games: list[GameCandidate]) -> dict[int, GridAssets]:
        if self.steamgriddb is None:
            return {}
        try:
            return await self.steamgriddb.fetch_assets(games)
        except Exception as exc:
            logger.warning("SteamGridDB stage failed (%s)", type(exc).__name__)
            return {}

    async def _trailers(self, games: list[GameCandidate]) -> dict[int, str]:
        if self.igdb is None:
            return {}
        try:
            return await self.igdb.fetch_trailers([game.igdb_id for game in games])
        except Exception as exc:
            logger.warning("IGDB trailer stage failed (%s)", type(exc).__name__)
            return {}

    async def _artworks(self, games: list[GameCandidate]) -> dict[int, Artwork]:
        if self.igdb is None:
            return {}
        try:
            return await self.igdb.fetch_hero_artworks([game.igdb_id for game in games])
        except Exception as exc:
            logger.warning("IGDB artwork stage failed (%s)", type(exc).__name__)
            return {}


async def _false() -> bool:
    return False


async def _main(names: list[str]) -> None:
    from app.config import get_settings

    settings = get_settings()
    igdb = IgdbMediaClient(settings.igdb_client_id, settings.igdb_client_secret)
    games = []
    async with httpx.AsyncClient(base_url="https://api.igdb.com/v4", timeout=20) as client:
        token = await igdb._access_token(client)
        client.headers.update(
            {"Client-ID": settings.igdb_client_id, "Authorization": f"Bearer {token}"}
        )
        for name in names:
            response = await client.post(
                "/games",
                content=(
                    f'search "{name}"; fields id,name,external_games.uid,'
                    "external_games.external_game_source.name; limit 1;"
                ),
            )
            for row in response.json():
                steam_ids = [
                    int(item["uid"]) for item in row.get("external_games", [])
                    if item.get("external_game_source", {}).get("name") == "Steam"
                    and str(item.get("uid", "")).isdigit()
                ]
                games.append(GameCandidate(
                    igdb_id=row["id"], name=row["name"],
                    steam_app_id=steam_ids[0] if len(steam_ids) == 1 else None,
                ))
    resolver = MediaResolver(SteamGridDBClient(settings.steamgriddb_api_key), igdb)
    for media in await resolver.fetch_media(games):
        print(json.dumps(media.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(_main(sys.argv[1:] or ["Elden Ring", "League of Legends"]))
