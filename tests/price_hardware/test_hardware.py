import asyncio

from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareAssessment, HardwareSpecs
from app.tools.hardware import HardwareTool
from tests.price_hardware.fakes import FakePriceHardware


def test_absent_user_specs_skip_external_assessment():
    client = FakePriceHardware(quotes=[], assessments=[])
    result = asyncio.run(HardwareTool(client).run([GameCandidate(igdb_id=1, name="게임")], None))
    assert result[1].status == "skipped"
    assert client.calls == []


def test_missing_assessment_is_unknown_and_failure_reason_is_preserved():
    games = [GameCandidate(igdb_id=i, name=str(i)) for i in (1, 2)]
    client = FakePriceHardware(
        quotes=[],
        assessments=[HardwareAssessment(igdb_id=2, status="unmet", reason="메모리 부족")],
    )
    result = asyncio.run(HardwareTool(client).run(games, HardwareSpecs(ram_gb=4)))
    assert result[1].status == "unknown"
    assert result[2].status == "unmet"
    assert result[2].reason == "메모리 부족"
