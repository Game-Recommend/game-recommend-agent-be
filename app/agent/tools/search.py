"""IGDB 담당 Tool: 조건으로 후보를 검색해 CandidateStore에 넣는다.

인자는 질문 분해 결과(GameConditions)의 검색 조건 부분과 같다.
에이전트는 [추출한 조건]을 그대로 넘긴다.
예산·사용자 사양·추천 개수는 서버 기준값이라 인자에 없고, `ctx.conditions`에서 유지된다.
실제 검색은 팀원 모듈 `app/tools/game_search.py`(→ IGDB 클라이언트)가 한다.

TODO(IGDB 담당): description과 압축 출력 필드를 다듬고, 특정 게임 이름으로 찾는
`lookup_game`을 검토한다.
"""

from typing import Literal

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field

from app.agent.context import AgentContext
from app.schemas.game import GameCandidate

STAGE = "게임 검색"
SUMMARY_MAX_CHARS = 200  # LLM에 주는 소개 문구 길이. 후보 30개 × 200자면 충분히 작다.


class SearchGamesArgs(BaseModel):
    """search_games 인자. 필드 설명이 LLM에 그대로 보인다."""

    genres: list[str] = Field(
        default_factory=list,
        description="원하는 분류의 영어 이름. 예: Adventure, Shooter, Role-playing (RPG), Horror",
    )
    excluded_genres: list[str] = Field(default_factory=list, description="제외할 분류의 영어 이름")
    players: int | None = Field(default=None, ge=1, description="사용자를 포함한 총 인원")
    connection: Literal["online", "local"] | None = Field(
        default=None, description="online=온라인 멀티, local=한 화면·한 기기"
    )
    play_mode: Literal["singleplayer", "cooperative", "competitive"] | None = Field(
        default=None, description="singleplayer=싱글, cooperative=협동, competitive=경쟁"
    )
    max_playtime_hours: float | None = Field(
        default=None, gt=0, description="전체 완료 시간 상한(시간). 한 판 시간과 혼동하지 않는다"
    )
    max_session_minutes: float | None = Field(
        default=None, gt=0, description="한 판·한 세션 시간 상한(분)"
    )
    platforms: list[str] = Field(
        default_factory=list, description="플랫폼 이름. 예: PC, PlayStation 5"
    )


def compact_candidate(game: GameCandidate) -> dict:
    summary = (game.summary or "").strip()
    if len(summary) > SUMMARY_MAX_CHARS:
        summary = summary[:SUMMARY_MAX_CHARS].rstrip() + "…"
    return {
        "igdb_id": game.igdb_id,
        "name": game.name,
        "genres": game.genres,
        "themes": game.themes,
        "platforms": game.platforms,
        "playtime_hours": game.playtime_hours,
        "on_steam": game.steam_app_id is not None,
        "summary": summary or None,
    }


async def search_candidates(ctx: AgentContext, args: SearchGamesArgs) -> dict:
    # 서버 기준값(hardware, max_price_krw, recommendation_count, preferences)은 유지하고
    # 검색 조건만 바꾼다
    conditions = ctx.conditions.model_copy(update=args.model_dump())
    games = await ctx.tools.game_search.run(conditions)
    ctx.store.add_candidates(games)
    return {"count": len(games), "games": [compact_candidate(game) for game in games]}


@tool("search_games", args_schema=SearchGamesArgs)
async def search_games(
    genres: list[str],
    excluded_genres: list[str],
    players: int | None,
    connection: str | None,
    play_mode: str | None,
    max_playtime_hours: float | None,
    max_session_minutes: float | None,
    platforms: list[str],
    runtime: ToolRuntime[AgentContext],
) -> str:
    """조건에 맞는 게임 후보를 IGDB에서 찾는다. 추천 흐름의 첫 도구다.

    - 입력의 [추출한 조건]을 그대로 인자로 넘긴다. 조건을 완화하거나 없는 조건을 추가하지 않는다.
    - 결과의 igdb_id가 이후 모든 도구의 인자다. 여기 없는 id는 쓸 수 없다.
    - 결과는 검색 우선순위 순이며 최대 30개다. 가격·사양은 아직 확인되지 않았으므로 get_prices와
      assess_hardware로 판정한 뒤 추천한다.
    - 후보가 0개면 조건을 바꿔 다시 검색하지 말고, 조건에 맞는 게임이 없다고 답한다.
    """
    ctx = runtime.context
    args = SearchGamesArgs(
        genres=genres,
        excluded_genres=excluded_genres,
        players=players,
        connection=connection,
        play_mode=play_mode,
        max_playtime_hours=max_playtime_hours,
        max_session_minutes=max_session_minutes,
        platforms=platforms,
    )
    return await ctx.run_stage(
        STAGE, search_candidates(ctx, args), detail=lambda payload: f"후보 {payload['count']}개"
    )
