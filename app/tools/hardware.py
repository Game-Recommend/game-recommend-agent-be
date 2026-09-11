from app.clients.contracts.hardware import HardwareClient
from app.schemas.common import ConditionCheck
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareSpecs


class HardwareTool:
    def __init__(self, client: HardwareClient):
        self.client = client

    async def run(
        self, games: list[GameCandidate], hardware: HardwareSpecs | None
    ) -> dict[int, ConditionCheck]:
        if hardware is None:
            return {
                game.igdb_id: ConditionCheck(status="skipped", reason="사용자 사양 조건 없음")
                for game in games
            }
        assessments = {
            result.igdb_id: result for result in await self.client.assess(games, hardware)
        }
        return {
            game.igdb_id: (
                ConditionCheck(
                    status=assessments[game.igdb_id].status,
                    reason=assessments[game.igdb_id].reason,
                )
                if game.igdb_id in assessments
                else ConditionCheck(status="unknown", reason="사양 호환성 확인 불가")
            )
            for game in games
        }
