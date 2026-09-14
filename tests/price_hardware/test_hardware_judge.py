"""판정기 출력 합성: 전체 판정과 이유 문장은 코드가 만들고 LLM은 부품별 status·note만 준다."""

from app.clients.hardware_judge import JudgeRequest, _ComponentVerdict, _Verdict, compose_assessment
from app.schemas.hardware import HardwareSpecs, RequirementSpec

HARDWARE = HardwareSpecs(gpu="RTX 3060", cpu="i5", ram_gb=16)
REQUIREMENT = RequirementSpec(gpu="GTX 1060", cpu="i5-8400", ram_gb=8, raw_text="...")


def request(components):
    return JudgeRequest(igdb_id=1, name="게임", requirement=REQUIREMENT, components=components)


def verdict(**statuses):
    return _Verdict(
        igdb_id=1,
        components=[
            _ComponentVerdict(component=c, status=s, note=f"{c} 근거") for c, s in statuses.items()
        ],
    )


def test_all_compared_components_met_is_met_and_reason_quotes_inputs():
    result = compose_assessment(request(["gpu", "cpu"]), HARDWARE, verdict(gpu="met", cpu="met"))
    assert result.status == "met"
    assert result.reason == (
        "GPU RTX 3060 vs 최소 'GTX 1060' → 충족 (gpu 근거); "
        "CPU i5 vs 최소 'i5-8400' → 충족 (cpu 근거)"
    )
    assert result.requirement == REQUIREMENT


def test_any_unmet_wins_over_unknown_and_met():
    result = compose_assessment(
        request(["gpu", "cpu"]), HARDWARE, verdict(gpu="unknown", cpu="unmet")
    )
    assert result.status == "unmet"
    assert "CPU i5 vs 최소 'i5-8400' → 미달" in result.reason


def test_gpu_met_alone_cannot_pass_when_cpu_is_unknown_or_missing():
    unknown_cpu = compose_assessment(
        request(["gpu", "cpu"]), HARDWARE, verdict(gpu="met", cpu="unknown")
    )
    assert unknown_cpu.status == "unknown"
    # LLM이 compare에 있는 항목을 빠뜨리면 그 항목은 판단 불가로 본다
    missing_cpu = compose_assessment(request(["gpu", "cpu"]), HARDWARE, verdict(gpu="met"))
    assert missing_cpu.status == "unknown"
    assert "CPU i5 vs 최소 'i5-8400' → 판단 불가" in missing_cpu.reason


def test_missing_verdict_is_unknown_for_every_component():
    result = compose_assessment(request(["gpu"]), HARDWARE, None)
    assert result.status == "unknown"
    assert result.reason == "GPU RTX 3060 vs 최소 'GTX 1060' → 판단 불가"


def test_components_outside_compare_are_ignored():
    result = compose_assessment(request(["gpu"]), HARDWARE, verdict(gpu="met", cpu="unmet"))
    assert result.status == "met"
    assert "CPU" not in result.reason
