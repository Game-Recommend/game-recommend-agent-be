"""조건 JSON → 지정된 조건만 적용 → 1차 후보 최대 30개. 가격·사양은 후속 단계 담당."""

import asyncio
import json
from pathlib import Path

import httpx2 as httpx

from app.config import get_settings

ALIASES = {
    "pc": "PC (Microsoft Windows)", "windows": "PC (Microsoft Windows)",
    "rpg": "Role-playing (RPG)", "롤플레잉": "Role-playing (RPG)",
    "어드벤처": "Adventure", "공포": "Horror", "액션": "Action",
    "퍼즐": "Puzzle", "전략": "Strategy", "슈팅": "Shooter",
    "ps5": "PlayStation 5", "switch": "Nintendo Switch",
}


def normalize(value: str) -> str:
    return ALIASES.get(value.strip().lower(), value.strip()).lower()


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
        # 1. Twitch 인증
        response = await client.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": settings.igdb_client_id,
                "client_secret": settings.igdb_client_secret,
                "grant_type": "client_credentials",
            },
        )
        client.headers.update({
            "Client-ID": settings.igdb_client_id,
            "Authorization": f"Bearer {response.json()['access_token']}",
        })

        response = await client.post(
            "https://api.igdb.com/v4/games",
            content=(
                "fields name,summary,url,genres.name,themes.name,platforms.name,"
                "external_games.uid,external_games.external_game_source.name,"
                "multiplayer_modes.platform,multiplayer_modes.offlinecoopmax,"
                "multiplayer_modes.onlinecoopmax,multiplayer_modes.onlinemax,"
                "multiplayer_modes.offlinemax; "
                f"{query_filter}sort id asc; limit 500;"
            ),
        )
        games = response.json()
        if not games:
            return []

        # 3. 전체 완료 시간을 조회하고 초 → 시간으로 변환
        ids = ",".join(str(game["id"]) for game in games)
        response = await client.post(
            "https://api.igdb.com/v4/game_time_to_beats",
            content=f"fields game_id,normally; where game_id = ({ids}); limit 500;",
        )
        hours = {row["game_id"]: row["normally"] / 3600
                 for row in response.json() if row.get("normally", 0) > 0}

    # 4. 지정된 제외 장르·인원·시간 검사
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


if __name__ == "__main__":
    path = Path(__file__).resolve().parents[2] / "tests/igdb/examples/playtime_conditions.json"
    conditions = json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(asyncio.run(search(conditions)), ensure_ascii=False, indent=2))
