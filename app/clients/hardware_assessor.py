"""가격·하드웨어 담당: 요구 사양 출처와 무관한 공통 사양 판정.

Steam(steam_store.py)과 PCGamingWiki(pcgamingwiki.py)는 요구 사양을 가져오는 방법만 다르고,
사용자 PC와 비교하는 규칙은 같아야 한다. 메모리 숫자 비교·사용자 입력 검증·GPU·CPU LLM 판정 호출을
여기에 모아 두 출처가 같은 기준으로 판정하게 한다.
"""

import logging
import re

from pydantic import BaseModel

from app.clients.hardware_judge import JudgeRequest, SpecJudge
from app.schemas.common import Language
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs, RequirementSpec

logger = logging.getLogger(__name__)

# 판정 이유. 사양 판정 이유(check.reason)로 그대로 나간다
REASONS: dict[Language, dict[str, str]] = {
    "ko": {
        "no_user_spec": "사용자 사양 조건 없음",
        "no_requirement": "요구 사양 정보 없음",
        "memory_short": "메모리 부족: 최소 {required}, 보유 {owned}",
        "memory_met": "메모리 충족: 최소 {required}",
        "no_common_part": "비교할 공통 GPU·CPU 항목 없음",
        "nothing_to_compare": "비교할 사양 항목 없음",
        "judge_failed": "GPU·CPU 판정 실패",
        "mac": "Mac 사양 판정 미지원",
        "model_needed": "{part} 모델 확인 필요 (예: {examples})",
    },
    "en": {
        "no_user_spec": "No hardware condition",
        "no_requirement": "No system requirements found",
        "memory_short": "Not enough memory: minimum {required}, you have {owned}",
        "memory_met": "Enough memory: minimum {required}",
        "no_common_part": "No GPU or CPU to compare",
        "nothing_to_compare": "No specs to compare",
        "judge_failed": "GPU/CPU check failed",
        "mac": "Mac hardware check not supported",
        "model_needed": "Exact {part} model needed (e.g. {examples})",
    },
}

# 모델명으로 인정하는 조건: 세 자리 이상 숫자가 있거나(RTX 3060, i5-12400, 780M)
# 알려진 내장 그래픽 계열명이 있다. "i5", "Ryzen 5"의 한 자리 숫자는 세대를 말해 주지 않는다.
# "내장그래픽", "GeForce", "i5"처럼 등급을 알 수 없는 값은 비교하지 않는다.
_KNOWN_IGPU_RE = re.compile(r"iris|uhd|arc|vega|radeon graphics", re.IGNORECASE)
# LLM은 처음 보는 이름("ZetaPixel Q999")도 성능이 낮다고 추측해 unmet을 주므로,
# 알려진 제품 계열이 아니면 판정을 보류한다. 계열이 빠져 있으면 여기에 추가한다.
_KNOWN_FAMILY_RE = re.compile(
    r"geforce|gtx|rtx|titan|quadro|radeon|\brx\b|\bhd\b|vega|arc|iris|uhd"
    r"|\bcore\b|\bi[3579]\b|i[3579]-|ryzen|athlon|threadripper|xeon|pentium|celeron|\bfx\b"
    r"|지포스|라데온|라이젠|코어|인텔|엔비디아",  # 한글 별칭
    re.IGNORECASE,
)
_APPLE_SILICON_RE = re.compile(r"\bapple\b|\bm[1-4]\b", re.IGNORECASE)
_MODEL_EXAMPLES = {"gpu": "Iris Xe, Radeon 780M", "cpu": "i5-12400"}


class GameRequirements(BaseModel):
    """출처가 제공한 게임 한 편의 최소·권장 사양. 조회는 됐지만 항목이 없으면 둘 다 None이다."""

    minimum: RequirementSpec | None = None
    recommended: RequirementSpec | None = None


def user_spec_issue(hardware: HardwareSpecs, language: Language = "ko") -> str | None:
    """사용자 GPU·CPU 값이 비교 가능한 모델명이 아니면 그 이유. 문제가 없으면 None."""
    reasons = REASONS[language]
    for component in ("gpu", "cpu"):
        value = getattr(hardware, component)
        if not value:
            continue
        if _APPLE_SILICON_RE.search(value):
            # 스토어 요구 사양은 Windows 기준이라 Apple Silicon과 비교할 수 없다
            return reasons["mac"]
        has_model = re.search(r"\d{3,}", value) or _KNOWN_IGPU_RE.search(value)
        if not (has_model and _KNOWN_FAMILY_RE.search(value)):
            return reasons["model_needed"].format(
                part=component.upper(), examples=_MODEL_EXAMPLES[component]
            )
    return None


async def assess_requirements(
    games: list[GameCandidate],
    hardware: HardwareSpecs | None,
    requirements: dict[int, GameRequirements],
    judge: SpecJudge,
    *,
    language: Language = "ko",
) -> list[HardwareAssessment]:
    """조회한 요구 사양(igdb_id 기준)과 사용자 사양을 비교한다. 조회되지 않은 게임은 unknown."""
    reasons = REASONS[language]
    # 사용자 쪽 정보 부족(모델 없는 내장그래픽, Mac)은 게임과 무관하게 한 번만 판단한다.
    # 이 경우 제외하지 않고 skipped로 통과시켜 답변에서 요구 사양을 보여주고 되묻는다.
    issue = user_spec_issue(hardware, language) if hardware else None
    results: list[HardwareAssessment] = []
    to_judge: list[JudgeRequest] = []
    for game in games:
        spec = requirements.get(game.igdb_id)
        requirement = spec.minimum if spec else None
        if hardware is None:
            # 비교할 조건이 없어도 답변에 보여줄 요구 사양은 싣는다
            results.append(_assessment(game, "skipped", reasons["no_user_spec"], spec))
            continue
        if requirement is None:
            results.append(_assessment(game, "unknown", reasons["no_requirement"], spec))
            continue
        if hardware.ram_gb and requirement.ram_gb and hardware.ram_gb < requirement.ram_gb:
            reason = reasons["memory_short"].format(
                required=_gb(requirement.ram_gb), owned=_gb(hardware.ram_gb)
            )
            results.append(_assessment(game, "unmet", reason, spec))
            continue
        if issue:
            results.append(_assessment(game, "skipped", issue, spec))
            continue
        components = [
            c for c in ("gpu", "cpu") if getattr(hardware, c) and getattr(requirement, c)
        ]
        if components:
            to_judge.append(
                JudgeRequest(
                    igdb_id=game.igdb_id,
                    name=game.name,
                    requirement=requirement,
                    components=components,
                )
            )
        elif hardware.gpu or hardware.cpu:
            results.append(_assessment(game, "unknown", reasons["no_common_part"], spec))
        elif hardware.ram_gb and requirement.ram_gb:
            reason = reasons["memory_met"].format(required=_gb(requirement.ram_gb))
            results.append(_assessment(game, "met", reason, spec))
        else:
            results.append(_assessment(game, "unknown", reasons["nothing_to_compare"], spec))
    if to_judge:
        results.extend(await _judge(hardware, to_judge, requirements, judge, language))
    return results


async def _judge(
    hardware: HardwareSpecs,
    requests: list[JudgeRequest],
    requirements: dict[int, GameRequirements],
    judge: SpecJudge,
    language: Language,
) -> list[HardwareAssessment]:
    # 판정기 실패가 메모리 규칙으로 이미 확정한 결과까지 지우지 않도록 여기서 막는다
    try:
        verdicts = {
            v.igdb_id: v for v in await judge.judge(hardware, requests, language=language)
        }
    except Exception as exc:
        logger.warning("Spec judge failed (%s)", type(exc).__name__)
        verdicts = {}
    results = []
    for request in requests:
        verdict = verdicts.get(request.igdb_id)
        status, reason = (
            (verdict.status, verdict.reason)
            if verdict
            else ("unknown", REASONS[language]["judge_failed"])
        )
        results.append(
            HardwareAssessment(
                igdb_id=request.igdb_id,
                status=status,
                reason=reason,
                requirement=request.requirement,
                recommended=requirements[request.igdb_id].recommended,
            )
        )
    return results


def _assessment(
    game: GameCandidate, status: str, reason: str, spec: GameRequirements | None
) -> HardwareAssessment:
    return HardwareAssessment(
        igdb_id=game.igdb_id,
        status=status,
        reason=reason,
        requirement=spec.minimum if spec else None,
        recommended=spec.recommended if spec else None,
    )


def _gb(value: float) -> str:
    return f"{value:g} GB"
