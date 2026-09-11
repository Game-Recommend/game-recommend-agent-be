from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.hardware import HardwareSpecs


class GameConditions(BaseModel):
    """질문 가공(1단계)의 출력이자 도구 호출(2단계)의 입력.

    구상의 예상 Input 여섯 가지를 옮긴 초안이다. 질문에 없는 조건은 None이나 빈 목록으로
    둔다 — LLM이 추측해 채우면 사용자가 말하지 않은 조건으로 후보가 걸러진다.
    """

    hardware: HardwareSpecs | None = None
    genres: list[str] = Field(default_factory=list)
    excluded_genres: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)  # 스토리 등 부드러운 선호
    players: int | None = Field(default=None, ge=1)  # 본인 포함 총인원
    connection: Literal["online", "local"] | None = None
    play_mode: Literal["singleplayer", "cooperative", "competitive"] | None = None
    max_price_krw: int | None = Field(default=None, ge=0)
    max_playtime_hours: float | None = Field(default=None, gt=0)  # 전체 완료 시간
    max_session_minutes: float | None = Field(default=None, gt=0)  # 한 판/한 세션
    platforms: list[str] = Field(default_factory=list)
    recommendation_count: int = Field(default=3, ge=1, le=20)
