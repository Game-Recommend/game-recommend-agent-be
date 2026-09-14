from app.clients.contracts.hardware import HardwareClient
from app.schemas.common import ConditionCheck
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareResult, HardwareSpecs


class HardwareTool:
    def __init__(self, client: HardwareClient):
        self.client = client

    async def run(
        self, games: list[GameCandidate], hardware: HardwareSpecs | None
    ) -> dict[int, HardwareResult]:
        # 사양 조건이 없어도 답변에 표시할 요구 사양은 조회한다
        assessments = {
            result.igdb_id: result for result in await self.client.assess(games, hardware)
        }
        results = {}
        for game in games:
            assessment = assessments.get(game.igdb_id)
            if assessment is None:
                check = (
                    ConditionCheck(status="skipped", reason="사용자 사양 조건 없음")
                    if hardware is None
                    else ConditionCheck(status="unknown", reason="사양 호환성 확인 불가")
                )
                results[game.igdb_id] = HardwareResult(igdb_id=game.igdb_id, check=check)
                continue
            # 조건이 없으면 클라이언트가 무엇을 돌려주든 판정하지 않고 요구 사양만 남긴다
            check = (
                ConditionCheck(status="skipped", reason="사용자 사양 조건 없음")
                if hardware is None
                else ConditionCheck(status=assessment.status, reason=assessment.reason)
            )
            results[game.igdb_id] = HardwareResult(
                igdb_id=game.igdb_id,
                requirement=assessment.requirement,
                recommended=assessment.recommended,
                check=check,
            )
        return results
