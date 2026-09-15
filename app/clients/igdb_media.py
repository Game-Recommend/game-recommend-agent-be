"""미디어 담당: IGDB에서 트레일러(YouTube ID)와 배너 대체용 가로 아트워크를 조회한다.

- 인증은 igdb.py와 같은 Twitch client credentials다. 앱 토큰은 약 60일 유효하므로 만료 전까지
  프로세스 안에서 재사용한다.
- `POST /v4/game_videos` fields game,name,video_id; where game = (ids). video_id는 YouTube ID다.
- `POST /v4/artworks` fields game,image_id,width,height. 이미지 URL은
  `https://images.igdb.com/igdb/image/upload/t_1080p/{image_id}.jpg`이며 1920×1080 안에 맞추고
  확대하지 않는다.
- 제한: 초당 4회, 동시 8개. id를 최대 500개씩 묶어 게임 수와 무관하게 호출 수를 고정한다.
- 비상업 무료(Twitch Developer Service Agreement). 상업 이용은 partner@igdb.com.
"""

import asyncio
import logging
import time

import httpx2 as httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API_URL = "https://api.igdb.com/v4"
IMAGE_URL = "https://images.igdb.com/igdb/image/upload/t_1080p/{image_id}.jpg"
FIT_WIDTH, FIT_HEIGHT = 1920, 1080
# 배너로 쓸 만한 가로 비율 범위와 목표 비율(SteamGridDB 히어로 1920×620 ≈ 3.1)
MIN_ASPECT, MAX_ASPECT, TARGET_ASPECT = 1.5, 6.5, 3.1
MIN_ARTWORK_WIDTH = 1280
# 이름 규칙으로 트레일러를 고른다. 시네마틱·출시 트레일러가 게임 플레이·티저보다 카드에 어울린다.
_TRAILER_RANKS = (
    ("cinematic", 0),
    ("launch", 1),
    ("announce", 3),
    ("gameplay", 4),
    ("teaser", 5),
    ("trailer", 2),
)


class Artwork(BaseModel):
    url: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)


def trailer_rank(name: str) -> int:
    lowered = name.casefold()
    for keyword, rank in _TRAILER_RANKS:
        if keyword in lowered:
            return rank
    return 6


def pick_hero_artwork(rows: list[dict]) -> Artwork | None:
    """가로형 아트워크 중 히어로 비율에 가장 가까운 것. 1920×1080 안에 맞춘 크기를 함께 돌려준다."""
    candidates = []
    for index, row in enumerate(rows):
        width, height = row.get("width") or 0, row.get("height") or 0
        if width < MIN_ARTWORK_WIDTH or height <= 0:
            continue
        aspect = width / height
        if not MIN_ASPECT <= aspect <= MAX_ASPECT:
            continue
        # 비율·너비가 같으면 앞선 항목. index를 넣어 dict끼리 비교하지 않게 한다
        candidates.append((abs(aspect - TARGET_ASPECT), -width, index, row))
    if not candidates:
        return None
    row = min(candidates)[3]
    scale = min(FIT_WIDTH / row["width"], FIT_HEIGHT / row["height"], 1.0)
    return Artwork(
        url=IMAGE_URL.format(image_id=row["image_id"]),
        width=max(1, round(row["width"] * scale)),
        height=max(1, round(row["height"] * scale)),
    )


class IgdbMediaClient:
    def __init__(self, client_id: str, client_secret: str, *, timeout: float = 20):
        if not client_id or not client_secret:
            raise ValueError("IGDB_CLIENT_ID와 IGDB_CLIENT_SECRET이 필요합니다.")
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def fetch_trailers(self, igdb_ids: list[int]) -> dict[int, str]:
        """igdb_id → YouTube ID. 게임마다 가장 카드에 어울리는 영상 하나."""
        best: dict[int, tuple[int, int, str]] = {}
        for row in await self._query("game_videos", "game,name,video_id", igdb_ids):
            video_id = row.get("video_id")
            if not video_id:
                continue
            # 같은 등급이면 나중에 등록된(id가 큰) 영상을 고른다
            key = (trailer_rank(row.get("name", "")), -row["id"], video_id)
            if row["game"] not in best or key < best[row["game"]]:
                best[row["game"]] = key
        return {game_id: key[2] for game_id, key in best.items()}

    async def fetch_hero_artworks(self, igdb_ids: list[int]) -> dict[int, Artwork]:
        rows_by_game: dict[int, list[dict]] = {}
        for row in await self._query("artworks", "game,image_id,width,height", igdb_ids):
            rows_by_game.setdefault(row["game"], []).append(row)
        picked = {game_id: pick_hero_artwork(rows) for game_id, rows in rows_by_game.items()}
        return {game_id: artwork for game_id, artwork in picked.items() if artwork is not None}

    async def _query(self, endpoint: str, fields: str, igdb_ids: list[int]) -> list[dict]:
        ids = sorted({int(value) for value in igdb_ids})
        if not ids:
            return []
        rows: list[dict] = []
        async with httpx.AsyncClient(base_url=API_URL, timeout=self.timeout) as client:
            token = await self._access_token(client)
            client.headers.update(
                {"Client-ID": self.client_id, "Authorization": f"Bearer {token}"}
            )
            for start in range(0, len(ids), 500):
                chunk = ",".join(str(value) for value in ids[start : start + 500])
                response = await client.post(
                    f"/{endpoint}",
                    content=f"fields {fields}; where game = ({chunk}); limit 500;",
                )
                response.raise_for_status()
                rows.extend(response.json())
        return rows

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        async with self._token_lock:
            if self._token and time.monotonic() < self._token_expires_at:
                return self._token
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials",
                },
            )
            response.raise_for_status()
            payload = response.json()
            self._token = payload["access_token"]
            # 만료 1분 전에 갱신한다
            self._token_expires_at = time.monotonic() + max(payload.get("expires_in", 0) - 60, 0)
            return self._token
