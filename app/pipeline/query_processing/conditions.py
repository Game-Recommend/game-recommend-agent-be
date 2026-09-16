from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.hardware import HardwareSpecs


class GameConditions(BaseModel):
    """질문 가공 결과이자 게임 검색 도구의 입력."""

    hardware: HardwareSpecs | None = None

    genres: list[str] = Field(default_factory=list)
    excluded_genres: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)

    players: int | None = Field(default=None, ge=1)
    connection: Literal["online", "local"] | None = None
    play_mode: Literal[
        "singleplayer",
        "cooperative",
        "competitive",
    ] | None = None

    max_price_krw: int | None = Field(default=None, ge=0)
    max_playtime_hours: float | None = Field(default=None, gt=0)
    max_session_minutes: float | None = Field(default=None, gt=0)

    platforms: list[str] = Field(default_factory=list)
    recommendation_count: int = Field(default=3, ge=1, le=30)

    @model_validator(mode="after")
    def normalize_conditions(self) -> "GameConditions":
        # CPU·GPU·RAM·OS·원문이 모두 없으면 하드웨어 조건이 아니다.
        if (
            self.hardware is not None
            and not self.hardware.model_dump(exclude_none=True)
        ):
            self.hardware = None

        # "무료 선호"는 부드러운 선호이며 무료 게임만을 의미하지 않는다.
        if (
            self.max_price_krw == 0
            and any(
                preference.strip() == "무료 선호"
                for preference in self.preferences
            )
        ):
            self.max_price_krw = None

        # "턴제 비선호"가 preferences에 있으면 동일한 의도를
        # excluded_genres의 하드 필터로 중복 적용하지 않는다.
        has_soft_turn_based_preference = any(
            preference.strip() == "턴제 비선호"
            for preference in self.preferences
        )

        if has_soft_turn_based_preference:
            turn_based_filters = {
                "turn-based",
                "turn based",
                "turn-based strategy (tbs)",
                "턴제",
            }

            self.excluded_genres = [
                genre
                for genre in self.excluded_genres
                if genre.strip().casefold() not in turn_based_filters
            ]

        return self
