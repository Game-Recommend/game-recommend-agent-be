from typing import Protocol

from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.game import GameCandidate


class GameCatalogClient(Protocol):
    async def search(self, conditions: GameConditions) -> list[GameCandidate]:
        """명시된 장르·인원·모드·시간·플랫폼 조건을 검증한 후보를 우선순위순 반환.

        구현 시 IGDB 필드와 게임 ID를 매핑한다. 완료 시간과 세션 시간은 구분한다.
        필수 조건을 검증할 수 없는 후보를 조건 충족 후보로 반환하지 않는다.
        """
        ...
