"""가격·하드웨어 담당: assess_hardware가 LLM에 넘기는 압축 출력."""

from app.agent.tools.hardware import compact_hardware, compact_spec
from app.schemas.common import ConditionCheck
from app.schemas.hardware import HardwareResult, RequirementSpec

LONG_CPU = (
    "Intel Core i5-8400 2.8GHz / AMD Ryzen 5 2600 3.4GHz or better, 최신 드라이버 권장, "
    "가상화 환경은 지원하지 않음"
)


def test_fields_become_one_line_and_long_values_are_clipped():
    spec = RequirementSpec(
        os="Windows 10 64-bit",
        cpu=LONG_CPU,
        gpu="GTX 1060",
        ram_gb=8,
        raw_text="원문",
        source_url="https://store.steampowered.com/app/1",
    )
    line = compact_spec(spec)
    assert line is not None
    assert line.startswith("OS Windows 10 64-bit, CPU Intel Core i5-8400")
    assert line.endswith(", GPU GTX 1060, RAM 8GB")
    assert "…" in line and LONG_CPU not in line  # 길면 자르고 잘렸음을 표시한다
    assert "https://" not in line  # URL은 LLM 판단에 쓰지 않는다


def test_falls_back_to_raw_text_only_when_no_field_was_parsed():
    spec = RequirementSpec(raw_text="  Memory:   8 GB RAM\n Graphics: GTX 960 ")
    assert compact_spec(spec) == "Memory: 8 GB RAM Graphics: GTX 960"  # 공백을 정리한다
    assert compact_spec(RequirementSpec(raw_text="   ")) is None
    assert compact_spec(None) is None


def test_compact_hardware_keeps_status_and_reason():
    result = HardwareResult(
        igdb_id=7,
        requirement=RequirementSpec(ram_gb=16, raw_text="Memory: 16 GB RAM"),
        recommended=RequirementSpec(gpu="RTX 4070", raw_text="Graphics: RTX 4070"),
        check=ConditionCheck(status="unmet", reason="메모리 부족"),
    )
    assert compact_hardware(result) == {
        "igdb_id": 7,
        "minimum": "RAM 16GB",
        "status": "unmet",
        "reason": "메모리 부족",
    }
