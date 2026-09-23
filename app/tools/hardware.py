from app.clients.contracts.hardware import HardwareClient
from app.schemas.common import ConditionCheck, Language
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareResult, HardwareSpecs

# 판정 이유. 요구 사양과 비교한 이유는 클라이언트가 같은 언어로 만든다
REASONS: dict[Language, dict[str, str]] = {
    "ko": {"no_user_spec": "사용자 사양 조건 없음", "not_assessed": "사양 호환성 확인 불가"},
    "en": {"no_user_spec": "No hardware condition", "not_assessed": "Compatibility unknown"},
}


class HardwareTool:
    def __init__(self, client: HardwareClient):
        self.client = client

    async def run(
        self,
        games: list[GameCandidate],
        hardware: HardwareSpecs | None,
        *,
        language: Language = "ko",
    ) -> dict[int, HardwareResult]:
        reasons = REASONS[language]
        # 사양 조건이 없어도 답변에 표시할 요구 사양은 조회한다
        assessments = {
            result.igdb_id: result
            for result in await self.client.assess(games, hardware, language=language)
        }
        results = {}
        for game in games:
            assessment = assessments.get(game.igdb_id)
            if assessment is None:
                check = (
                    ConditionCheck(status="skipped", reason=reasons["no_user_spec"])
                    if hardware is None
                    else ConditionCheck(status="unknown", reason=reasons["not_assessed"])
                )
                results[game.igdb_id] = HardwareResult(igdb_id=game.igdb_id, check=check)
                continue
            # 조건이 없으면 클라이언트가 무엇을 돌려주든 판정하지 않고 요구 사양만 남긴다
            check = (
                ConditionCheck(status="skipped", reason=reasons["no_user_spec"])
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
