from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.hardware import HardwareSpecs


class GameConditions(BaseModel):
    """질문 가공 결과이자 게임 검색 도구의 입력.

    genres와 excluded_genres는 서비스에서 사용하는 통합 게임 분류다.
    IGDB의 genre/theme 필드 구분과 반드시 일치하지는 않는다.
    질문에 없는 조건은 None이나 빈 목록으로 둔다.
    """

    hardware: HardwareSpecs | None = None

    genres: list[str] = Field(default_factory=list)
    excluded_genres: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)

    players: int | None = Field(default=None, ge=1)
    connection: Literal["online", "local"] | None = None
    play_mode: Literal["singleplayer", "cooperative", "competitive"] | None = None

    max_price_krw: int | None = Field(default=None, ge=0)
    max_playtime_hours: float | None = Field(default=None, gt=0)
    max_session_minutes: float | None = Field(default=None, gt=0)

    platforms: list[str] = Field(default_factory=list)
    recommendation_count: int = Field(default=3, ge=1, le=30)
