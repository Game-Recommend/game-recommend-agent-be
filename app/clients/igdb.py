"""조건 JSON → 지정된 조건만 적용 → 1차 후보 최대 30개. 가격·사양은 후속 단계 담당.

후보는 **많이 평가된 순**(`total_rating_count desc`)으로 뽑는다. 전에는 `sort id asc`였는데,
IGDB id는 등록 순서라 1번 Thief II, 2번 Thief: The Dark Project, 5번 Baldur's Gate처럼 질문과
무관하게 같은 1990~2000년대 게임이 앞에 왔다(evals/search_pool/REPORT.md). 본편·리메이크·리마스터만
보고, 플랫폼을 말하지 않으면 PC로 본다. 가격·사양 판정이 PC(Steam·PCGamingWiki) 기준이기 때문이다.
Steam에 없는 PC 게임(LoL 등)은 비Steam 폴백이 다루므로 Steam 연결을 요구하지는 않는다.

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

PC = "PC (Microsoft Windows)"

ALIASES = {
    "pc": PC, "windows": PC, "노트북": PC, "laptop": PC, "데스크톱": PC, "데스크탑": PC,
    "desktop": PC, "컴퓨터": PC, "computer": PC, "steam": PC, "스팀": PC,
    "ps5": "PlayStation 5", "ps4": "PlayStation 4", "switch": "Nintendo Switch",
    "rpg": "Role-playing (RPG)", "롤플레잉": "Role-playing (RPG)",
    "어드벤처": "Adventure", "공포": "Horror", "액션": "Action",
    "퍼즐": "Puzzle", "전략": "Strategy", "슈팅": "Shooter",
    "fps": "Shooter", "sports": "Sport", "스포츠": "Sport", "simulation": "Simulator",
    "시뮬레이션": "Simulator", "platformer": "Platform", "레이싱": "Racing", "격투": "Fighting",
    "sci-fi": "Science fiction", "scifi": "Science fiction", "sf": "Science fiction",
    "판타지": "Fantasy", "open-world": "Open world", "오픈월드": "Open world",
    "rts": "Real Time Strategy (RTS)", "tbs": "Turn-based strategy (TBS)",
    "turn-based": "Turn-based strategy (TBS)", "turn based": "Turn-based strategy (TBS)",
    "턴제": "Turn-based strategy (TBS)", "hack and slash": "Hack and slash/Beat 'em up",
    "card game": "Card & Board Game", "board game": "Card & Board Game",
    "파티": "Party", "아케이드": "Arcade", "인디": "Indie", "생존": "Survival",
}

# IGDB의 장르 23개와 테마 22개(2026-09 조회). 검색은 이 둘을 한 분류로 본다.
# 여기에 없는 분류어는 게임 모드(GAME_MODES)나 키워드로 찾는다. 전에는 장르·테마 이름으로만 찾아서
# 파서가 genres=["Cooperative"]를 내면 후보가 0개였다.
CATEGORIES = frozenset(
    name.lower()
    for name in (
        "Point-and-click", "Fighting", "Shooter", "Music", "Platform", "Puzzle", "Racing",
        "Real Time Strategy (RTS)", "Role-playing (RPG)", "Simulator", "Sport", "Strategy",
        "Turn-based strategy (TBS)", "Tactical", "Hack and slash/Beat 'em up", "Quiz/Trivia",
        "Pinball", "Adventure", "Indie", "Arcade", "Visual Novel", "Card & Board Game", "MOBA",
        "Action", "Fantasy", "Science fiction", "Horror", "Thriller", "Survival", "Historical",
        "Stealth", "Comedy", "Business", "Drama", "Non-fiction", "Sandbox", "Educational", "Kids",
        "Open world", "Warfare", "Party", "4X (explore, expand, exploit, and exterminate)",
        "Erotic", "Mystery", "Romance",
    )
)  # fmt: skip

# 분류 자리에 온 플레이 방식 표현 → IGDB game_modes 이름
GAME_MODES = {
    "cooperative": "Co-operative", "co-operative": "Co-operative", "co-op": "Co-operative",
    "coop": "Co-operative", "협동": "Co-operative",
    "multiplayer": "Multiplayer", "멀티플레이": "Multiplayer", "멀티": "Multiplayer",
    "single player": "Single player", "singleplayer": "Single player", "싱글": "Single player",
    "split screen": "Split screen", "battle royale": "Battle Royale", "배틀로얄": "Battle Royale",
    "mmo": "Massively Multiplayer Online (MMO)",
}  # fmt: skip
# 질문 분해의 play_mode. 경쟁은 IGDB에 따로 없어 멀티플레이로 본다
PLAY_MODES = {
    "singleplayer": "Single player", "cooperative": "Co-operative", "competitive": "Multiplayer",
}  # fmt: skip

GAME_TYPES = "0,8,9,10"  # 본편, 리메이크, 리마스터, 확장판(Expanded Game). DLC·번들·모드는 뺀다
MIN_RATING_COUNT = 5  # 평가가 거의 없는 항목은 정렬 끝에서도 후보로 삼지 않는다
# 인원 조건을 볼 multiplayer_modes 필드. 연결 방식을 말했으면 그쪽 인원만 본다
PLAYER_FIELDS = {
    "online": ("onlinemax", "onlinecoopmax"),
    "local": ("offlinemax", "offlinecoopmax"),
    None: ("onlinemax", "offlinemax", "onlinecoopmax", "offlinecoopmax"),
}


def normalize(value: str) -> str:
    return ALIASES.get(value.strip().lower(), value.strip()).lower()


def quote(value: str) -> str:
    """IGDB 질의 문자열. 한글을 \\u 이스케이프로 바꾸지 않는다."""
    return json.dumps(value, ensure_ascii=False)


def expand_platforms(values: list[str]) -> list[str]:
    return [
        name
        for value in values
        for name in (["Android", "iOS"] if value.lower() in ("mobile", "모바일") else [value])
    ]


def build_filters(conditions: dict) -> list[str]:
    """IGDB where 절의 조건들. 없는 조건은 생략한다. 분류는 AND, 플랫폼은 OR로 조합한다."""
    where = [f"game_type = ({GAME_TYPES})", f"total_rating_count >= {MIN_RATING_COUNT}"]
    modes = []
    for genre in conditions.get("genres") or []:
        name = normalize(genre)
        if name in CATEGORIES:
            where.append(f"(genres.name ~ {quote(name)} | themes.name ~ {quote(name)})")
        elif name in GAME_MODES:
            modes.append(GAME_MODES[name])
        else:
            # IGDB 장르·테마에 없는 분류어(roguelike, story-rich 등)는 키워드로 찾는다.
            # 조건을 버리지 않는다. 맞는 키워드가 없으면 후보가 0개인 것이 옳다
            spaced = name.replace("-", " ")
            where.append(f"(keywords.name ~ {quote(name)} | keywords.name ~ {quote(spaced)})")
    if mode := PLAY_MODES.get(conditions.get("play_mode") or ""):
        modes.append(mode)
    if conditions.get("players") == 1:
        modes.append("Single player")
    where.extend(f"game_modes.name = {quote(mode)}" for mode in dict.fromkeys(modes))
    # 플랫폼을 말하지 않으면 PC로 본다. 가격·사양 판정이 PC 기준이다
    platforms = expand_platforms(conditions.get("platforms") or []) or [PC]
    names = " | ".join(f"platforms.name ~ {quote(normalize(name))}" for name in platforms)
    where.append(f"({names})")
    return where


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
    platforms = expand_platforms(conditions.get("platforms") or [])
    players = conditions.get("players")
    player_fields = PLAYER_FIELDS.get(conditions.get("connection"), PLAYER_FIELDS[None])
    max_hours = conditions.get("max_playtime_hours")
    query_filter = f"where {' & '.join(build_filters(conditions))}; "

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
                f"{query_filter}sort total_rating_count desc; limit 500;"
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
        # 제외 분류는 이름에 들어 있기만 해도 거른다("strategy"는 RTS·TBS도 거른다)
        labels = [normalize(name) for name in genres + themes]
        if excluded and (not genres or not themes
                         or any(name in label for name in excluded for label in labels)):
            continue
        if (players or 1) > 1:
            platform_ids = {item["id"] for item in game.get("platforms", [])
                            if normalize(item["name"]) in {normalize(p) for p in platforms}}
            if not any(
                (not platforms or row.get("platform") in platform_ids)
                and max(row.get(field, 0) for field in player_fields) >= players
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
