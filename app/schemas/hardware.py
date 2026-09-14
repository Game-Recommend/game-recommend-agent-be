"""가격·하드웨어 담당: 사용자 사양과 호환성 판정 모델."""

from pydantic import BaseModel, Field

from app.schemas.common import CheckStatus, ConditionCheck


class HardwareSpecs(BaseModel):
    cpu: str | None = None
    gpu: str | None = None
    ram_gb: float | None = Field(default=None, gt=0)
    os: str | None = None
    raw_text: str | None = None


class RequirementSpec(BaseModel):
    """스토어가 제공한 게임의 최소 요구 사양. 항목이 없으면 None이다."""

    os: str | None = None
    cpu: str | None = None
    gpu: str | None = None
    ram_gb: float | None = Field(default=None, gt=0)
    raw_text: str


class HardwareAssessment(BaseModel):
    """클라이언트의 게임별 결과. 사용자 사양 조건이 없으면 skipped에 요구 사양만 싣는다.

    판정은 requirement(최소 사양) 기준이고, recommended(권장 사양)는 표시용이다.
    """

    igdb_id: int
    status: CheckStatus
    reason: str
    requirement: RequirementSpec | None = None
    recommended: RequirementSpec | None = None


class HardwareResult(BaseModel):
    """도구 출력. 판정과 별개로 요구 사양을 답변에 표시할 수 있게 함께 전달한다."""

    igdb_id: int
    requirement: RequirementSpec | None = None  # 최소 사양 (판정 기준)
    recommended: RequirementSpec | None = None  # 권장 사양 (표시용)
    check: ConditionCheck
