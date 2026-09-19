import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.hardware import HardwareSpecs

_PRICE_CONSTRAINT_PATTERN = re.compile(
    r"^\s*"
    r"(?:가격(?:은|이)?\s*)?"
    r"(?:₩\s*)?"
    r"(?:\d[\d,]*\s*원|\d+\s*만\s*원)"
    r"\s*(?:이하|미만|이내|까지)"
    r"\s*$",
    re.IGNORECASE,
)

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

    max_price_krw: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Mandatory maximum price in KRW. "
            "Use 0 only when the user requires free games. "
            "A soft preference for free games remains null."
        ),
    )

    max_playtime_hours: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Maximum total hours required to complete the entire game. "
            "Never store one-session or one-match duration here."
        ),
    )

    max_session_minutes: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Maximum duration in minutes for one session, match, round, "
            "or sitting. Do not duplicate it into max_playtime_hours."
        ),
    )

    platforms: list[str] = Field(default_factory=list)
    recommendation_count: int = Field(default=5, ge=1, le=30)

    @model_validator(mode="after")
    def normalize_conditions(self) -> "GameConditions":
        if self.hardware is not None:
            hardware = self.hardware

            platform_only_os_values = {
                "pc",
                "computer",
                "컴퓨터",
                "노트북",
            }

            if (
                hardware.os is not None
                and hardware.os.strip().casefold()
                in platform_only_os_values
            ):
                hardware.os = None

            has_structured_hardware = any(
                (
                    bool(hardware.cpu and hardware.cpu.strip()),
                    bool(hardware.gpu and hardware.gpu.strip()),
                    hardware.ram_gb is not None,
                    bool(hardware.os and hardware.os.strip()),
                )
            )

            # raw_text만 남아 있다면 실제 비교 가능한 하드웨어 조건이 아니다.
            if not has_structured_hardware:
                self.hardware = None
                
        # max_price_krw로 구조화된 가격 조건을 preferences에 중복하지 않는다.
        if self.max_price_krw is not None:
            self.preferences = [
                preference
                for preference in self.preferences
                if not _PRICE_CONSTRAINT_PATTERN.fullmatch(
                    preference.strip()
                )
            ]
            
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

        # 같은 분류가 원하는 쪽과 제외하는 쪽에 함께 있으면 제외가 이긴다.
        # "공포 게임은 못 하겠어. 협동 게임 추천해줘"에서 모델이 Horror를 양쪽에 다 넣은 적이 있고,
        # 그러면 검색이 "공포이면서 공포가 아닌" 게임을 찾아 후보가 0개가 된다. 싫다고 한 분류를
        # 추천하는 것보다 원한 분류 하나를 놓치는 쪽이 덜 나쁘다.
        excluded = {genre.strip().casefold() for genre in self.excluded_genres}
        self.genres = [
            genre for genre in self.genres if genre.strip().casefold() not in excluded
        ]

        return self
