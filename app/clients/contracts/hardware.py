from typing import Protocol

from app.schemas.common import Language
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs


class HardwareClient(Protocol):
    async def assess(
        self,
        games: list[GameCandidate],
        hardware: HardwareSpecs | None,
        *,
        language: Language = "ko",
    ) -> list[HardwareAssessment]:
        """요구 사양 조회와 사용자 사양 비교. 비교 근거가 없으면 unknown을 반환.

        hardware가 None이면 비교하지 않고 skipped에 요구 사양만 실어 반환한다.
        요구 사양은 판정 상태와 무관하게 조회된 경우 항상 requirement에 싣는다.
        reason은 language로 쓴다.
        """
        ...
