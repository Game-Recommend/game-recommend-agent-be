import asyncio

from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs, RequirementSpec
from app.tools.hardware import HardwareTool
from tests.price_hardware.fakes import FakePriceHardware


def test_absent_user_specs_skip_check_but_keep_requirement():
    requirement = RequirementSpec(
        gpu="GTX 960", ram_gb=8, raw_text="Memory: 8 GB RAM, Graphics: GTX 960"
    )
    client = FakePriceHardware(
        quotes=[],
        assessments=[
            HardwareAssessment(
                igdb_id=1,
                status="skipped",
                reason="조건 없음",
                requirement=requirement,
                recommended=RequirementSpec(gpu="RTX 2060", raw_text="Graphics: RTX 2060"),
            )
        ],
    )
    games = [GameCandidate(igdb_id=i, name="게임") for i in (1, 2)]
    result = asyncio.run(HardwareTool(client).run(games, None))
    assert client.calls == ["hardware"]
    assert result[1].check.status == "skipped"
    assert result[1].requirement == requirement
    assert result[1].recommended is not None and result[1].recommended.gpu == "RTX 2060"
    assert result[2].check.status == "skipped"
    assert result[2].requirement is None


def test_missing_assessment_is_unknown_and_failure_reason_is_preserved():
    games = [GameCandidate(igdb_id=i, name=str(i)) for i in (1, 2)]
    client = FakePriceHardware(
        quotes=[],
        assessments=[HardwareAssessment(igdb_id=2, status="unmet", reason="메모리 부족")],
    )
    result = asyncio.run(HardwareTool(client).run(games, HardwareSpecs(ram_gb=4)))
    assert result[1].check.status == "unknown"
    assert result[2].check.status == "unmet"
    assert result[2].check.reason == "메모리 부족"
