from typing import Protocol

from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs


class HardwareClient(Protocol):
    async def assess(
        self, games: list[GameCandidate], hardware: HardwareSpecs
    ) -> list[HardwareAssessment]:
        """요구 사양 조회와 사용자 사양 비교. 비교 근거가 없으면 unknown을 반환."""
        ...
