"""미디어 담당: SteamGridDB API v2로 히어로(가로 배너)와 로고를 조회한다.

- 인증: `Authorization: Bearer <STEAMGRIDDB_API_KEY>`. 키는 프로필 설정에서 무료로 발급한다.
- Steam 게임: `GET /heroes/steam/{appid}`, `GET /logos/steam/{appid}`. 모르는 appid는 404다.
- 비Steam 게임: `GET /search/autocomplete/{name}` 결과 중 정규화한 이름이 정확히 같은 항목만
  인정하고 `GET /heroes/game/{id}`로 조회한다(routing.py 폴백과 같은 규칙). 유사 이름은 잇지 않는다.
- 결과는 점수순이라 첫 항목을 쓴다. 성인·유머·광과민 태그와 애니메이션은 제외한다.
- 커뮤니티 제작물이다. 데모·비상업 용도에 맞고, 서비스화 시 저작권을 따로 검토한다.
- 게임 하나가 실패해도 나머지는 계속한다(미디어는 추천 판정에 영향이 없다).
"""

import asyncio
import logging
import re
import unicodedata
from urllib.parse import quote

import httpx2 as httpx
from pydantic import BaseModel, Field

from app.schemas.game import GameCandidate

logger = logging.getLogger(__name__)

API_URL = "https://www.steamgriddb.com/api/v2"
HERO_PARAMS = {
    "dimensions": "1920x620,3840x1240",
    "types": "static",
    "nsfw": "false",
    "humor": "false",
    "epilepsy": "false",
    "mimes": "image/png,image/jpeg,image/webp",
    "limit": "1",
}
LOGO_PARAMS = {
    "styles": "official,white",
    "types": "static",
    "nsfw": "false",
    "humor": "false",
    "epilepsy": "false",
    "mimes": "image/png,image/webp",
    "limit": "1",
}


class GridAsset(BaseModel):
    url: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    style: str | None = None


class GridAssets(BaseModel):
    hero: GridAsset | None = None
    logo: GridAsset | None = None


def normalize_name(name: str) -> str:
    """상표 기호·대소문자·기호 차이를 무시한다. 'League of Legends™' == 'league of legends'."""
    # NFKC는 ™를 "tm"으로 바꾸므로 상표 기호를 먼저 지운다
    text = unicodedata.normalize("NFKC", re.sub(r"[™®©]", "", name)).casefold()
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


class SteamGridDBClient:
    def __init__(self, api_key: str, *, max_concurrency: int = 4, timeout: float = 15):
        if not api_key:
            raise ValueError("STEAMGRIDDB_API_KEY가 필요합니다.")
        self.api_key = api_key
        self.max_concurrency = max_concurrency
        self.timeout = timeout

    async def fetch_assets(self, games: list[GameCandidate]) -> dict[int, GridAssets]:
        """igdb_id → 히어로·로고. 조회에 실패한 게임은 빠진다."""
        semaphore = asyncio.Semaphore(self.max_concurrency)
        async with httpx.AsyncClient(
            base_url=API_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout,
        ) as client:
            results = await asyncio.gather(
                *(self._guarded(client, semaphore, game) for game in games)
            )
        return {
            game.igdb_id: assets
            for game, assets in zip(games, results, strict=True)
            if assets is not None
        }

    async def _guarded(
        self, client: httpx.AsyncClient, semaphore: asyncio.Semaphore, game: GameCandidate
    ) -> GridAssets | None:
        try:
            async with semaphore:
                return await self._lookup(client, game)
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.warning(
                "SteamGridDB lookup failed: igdb_id=%s (%s)", game.igdb_id, type(exc).__name__
            )
            return None

    async def _lookup(self, client: httpx.AsyncClient, game: GameCandidate) -> GridAssets:
        if game.steam_app_id is not None:
            key = f"steam/{game.steam_app_id}"
        else:
            game_id = await self._find_game_id(client, game.name)
            if game_id is None:
                return GridAssets()
            key = f"game/{game_id}"
        hero, logo = await asyncio.gather(
            self._first(client, f"/heroes/{key}", HERO_PARAMS),
            self._first(client, f"/logos/{key}", LOGO_PARAMS),
        )
        return GridAssets(hero=hero, logo=logo)

    async def _first(
        self, client: httpx.AsyncClient, path: str, params: dict[str, str]
    ) -> GridAsset | None:
        response = await client.get(path, params=params)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json().get("data") or []
        if not data:
            return None
        asset = data[0]
        return GridAsset(
            url=asset["url"], width=asset["width"], height=asset["height"], style=asset.get("style")
        )

    async def _find_game_id(self, client: httpx.AsyncClient, name: str) -> int | None:
        response = await client.get(f"/search/autocomplete/{quote(name, safe='')}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        wanted = normalize_name(name)
        for item in response.json().get("data") or []:
            if normalize_name(item.get("name", "")) == wanted:
                return int(item["id"])
        return None
