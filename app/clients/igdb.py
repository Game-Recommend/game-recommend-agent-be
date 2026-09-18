"""조건 JSON → 지정된 조건만 적용 → 1차 후보 최대 30개. 가격·사양은 후속 단계 담당.

IGDB 인증은 Twitch 앱 토큰(client credentials)이다. 토큰은 약 60일 유효하므로 검색마다 새로 받지
않고 프로세스 안에서 만료 전까지 재사용한다(`TwitchAppToken`, igdb_media.py와 같은 방식). 검색마다
토큰 요청 왕복(0.3~0.5초)을 없앤다. IGDB가 토큰을 거부하면(401) 버리고 한 번 다시 받는다.
"""

import asyncio
import json
import time
from pathlib import Path

import httpx2 as httpx

from app.config import Settings, get_settings
from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.game import GameCandidate

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API_URL = "https://api.igdb.com/v4"

ALIASES = {
    "pc": "PC (Microsoft Windows)", "windows": "PC (Microsoft Windows)",
    "rpg": "Role-playing (RPG)", "롤플레잉": "Role-playing (RPG)",
    "어드벤처": "Adventure", "공포": "Horror", "액션": "Action",
    "퍼즐": "Puzzle", "전략": "Strategy", "슈팅": "Shooter",
    "ps5": "PlayStation 5", "switch": "Nintendo Switch",
}


def normalize(value: str) -> str:
    return ALIASES.get(value.strip().lower(), value.strip()).lower()


class TwitchAppToken:
    """Twitch client credentials 앱 토큰.

    만료 1분 전까지 재사용하고, 자격 증명이 바뀌면 다시 받는다.
    """

    def __init__(self) -> None:
        self._client_id: str | None = None
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get(self, client: httpx.AsyncClient, client_id: str, client_secret: str) -> str:
        async with self._lock:
            if (
                self._token
                and self._client_id == client_id
                and time.monotonic() < self._expires_at
            ):
                return self._token
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "client_credentials",
                },
            )
            response.raise_for_status()
            payload = response.json()
            self._client_id = client_id
            self._token = payload["access_token"]
            # 만료 1분 전에 갱신한다
            self._expires_at = time.monotonic() + max(payload.get("expires_in", 0) - 60, 0)
            return self._token

    def invalidate(self) -> None:
        """IGDB가 토큰을 거부했을 때 다음 호출이 새로 받게 한다."""
        self._token = None


# 프로세스 전체가 공유한다. search()는 호출마다 HTTP 클라이언트를 새로 만들지만 토큰은 여기 남는다
_app_token = TwitchAppToken()


async def _post(
    client: httpx.AsyncClient, settings: Settings, endpoint: str, body: str
) -> list[dict]:
    """앱 토큰으로 IGDB 엔드포인트를 부른다. 토큰이 거부되면(401) 새로 받아 한 번 더 시도한다."""
    response = await _post_once(client, settings, endpoint, body)
    if response.status_code == 401:
        _app_token.invalidate()
        response = await _post_once(client, settings, endpoint, body)
    response.raise_for_status()
    return response.json()


async def _post_once(
    client: httpx.AsyncClient, settings: Settings, endpoint: str, body: str
) -> httpx.Response:
    token = await _app_token.get(client, settings.igdb_client_id, settings.igdb_client_secret)
    return await client.post(
        f"{API_URL}/{endpoint}",
        headers={"Client-ID": settings.igdb_client_id, "Authorization": f"Bearer {token}"},
        content=body,
    )


async def search(conditions: dict) -> list[dict]:
    conditions = conditions or {}
    excluded = {normalize(name) for name in conditions.get("excluded_genres") or []}
    platforms = [name for value in conditions.get("platforms") or []
                 for name in (["Android", "iOS"] if value.lower() in ("mobile", "모바일")
                              else [value])]
    players = conditions.get("players")
    max_hours = conditions.get("max_playtime_hours")

    # 없는 조건은 생략. 장르는 AND, 플랫폼은 OR로 조합한다.
    where = []
    for genre in conditions.get("genres") or []:
        name = json.dumps(normalize(genre))
        where.append(f"(genres.name ~ {name} | themes.name ~ {name})")
    if platforms:
        names = " | ".join(f"platforms.name ~ {json.dumps(normalize(name))}"
                           for name in platforms)
        where.append(f"({names})")
    if players == 1:
        where.append('game_modes.name = "Single player"')
    query_filter = f"where {' & '.join(where)}; " if where else ""

    settings = get_settings()
    async with httpx.AsyncClient(timeout=30) as client:
        # 1. 후보 검색. Twitch 앱 토큰은 _post가 붙이며 만료 전까지 재사용한다
        games = await _post(
            client,
            settings,
            "games",
            (
                "fields name,summary,url,genres.name,themes.name,platforms.name,"
                "external_games.uid,external_games.external_game_source.name,"
                "multiplayer_modes.platform,multiplayer_modes.offlinecoopmax,"
                "multiplayer_modes.onlinecoopmax,multiplayer_modes.onlinemax,"
                "multiplayer_modes.offlinemax; "
                f"{query_filter}sort id asc; limit 500;"
            ),
        )
        if not games:
            return []

        # 2. 전체 완료 시간을 조회하고 초 → 시간으로 변환
        ids = ",".join(str(game["id"]) for game in games)
        rows = await _post(
            client,
            settings,
            "game_time_to_beats",
            f"fields game_id,normally; where game_id = ({ids}); limit 500;",
        )
        hours = {row["game_id"]: row["normally"] / 3600
                 for row in rows if row.get("normally", 0) > 0}

    # 3. 지정된 제외 장르·인원·시간 검사
    result = []
    for game in games:
        genres = [item["name"] for item in game.get("genres", [])]
        themes = [item["name"] for item in game.get("themes", [])]
        if excluded and (not genres or not themes
                         or excluded & {normalize(name) for name in genres + themes}):
            continue
        if (players or 1) > 1:
            platform_ids = {item["id"] for item in game.get("platforms", [])
                            if normalize(item["name"]) in {normalize(p) for p in platforms}}
            if not any(
                (not platforms or row.get("platform") in platform_ids)
                and max(row.get(field, 0) for field in (
                    "onlinemax", "offlinemax", "onlinecoopmax", "offlinecoopmax"
                )) >= players
                for row in game.get("multiplayer_modes", [])
            ):
                continue
        playtime = hours.get(game["id"])
        if max_hours is not None and (playtime is None or playtime > max_hours):
            continue
        steam_ids = {int(item["uid"]) for item in game.get("external_games", [])
                     if item.get("external_game_source", {}).get("name") == "Steam"
                     and str(item.get("uid", "")).isascii()
                     and str(item.get("uid", "")).isdigit() and int(item["uid"]) > 0}
        result.append({
            "igdb_id": game["id"], "name": game["name"],
            "steam_app_id": next(iter(steam_ids)) if len(steam_ids) == 1 else None,
            "genres": genres, "themes": themes,
            "platforms": [item["name"] for item in game.get("platforms", [])],
            "summary": game.get("summary"), "source_url": game.get("url"),
            "playtime_hours": playtime,
        })
        if len(result) == 30:
            break
    return result


def to_candidate(row: dict) -> GameCandidate:
    """`search()`의 행 하나를 후보 모델로 바꾼다. 소개·분류·완료 시간은 최종 답변 재료다."""
    return GameCandidate(
        igdb_id=row["igdb_id"],
        name=row["name"],
        steam_app_id=row.get("steam_app_id"),
        platforms=row.get("platforms") or [],
        source_url=row.get("source_url"),
        summary=row.get("summary") or None,
        genres=row.get("genres") or [],
        themes=row.get("themes") or [],
        playtime_hours=row.get("playtime_hours"),
    )


class IgdbCatalogClient:
    """`GameCatalogClient` 구현. 오케스트레이터에 주입할 때 이 클래스를 쓴다."""

    async def search(self, conditions: GameConditions) -> list[GameCandidate]:
        return [to_candidate(row) for row in await search(conditions.model_dump())]


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[2] / "tests/igdb/examples/playtime_conditions.json"
    conditions = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(asyncio.run(search(conditions)), ensure_ascii=False, indent=2))
