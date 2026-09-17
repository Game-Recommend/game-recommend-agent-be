"""질문 파서 채점기. LLM을 쓰지 않고 정답과 코드로 비교한다.

정답은 부분 정답이다. `gold`에 적은 필드만 채점하고 적지 않은 필드는 보지 않는다.
자유 어휘인 preferences는 정확 일치 대신 포함·불포함만 본다.

전 문항 공통 불변식(`INVARIANTS`)은 프롬프트 총칙에서 나온 것으로, gold와 무관하게 늘 검사한다.
"""

import re

from app.pipeline.query_processing.conditions import GameConditions

# 프롬프트 1절: hardware.os에 플랫폼 표현을 넣지 않는다.
# conditions.py의 validator는 os가 정확히 {"pc","computer","컴퓨터","노트북"}일 때만 지운다.
# 실측에서 os="구형 노트북"이 그 그물을 빠져나갔으므로(REPORT.md의 관찰 4) 여기서는 부분 일치로
# 본다. 단 실제 OS 이름을 담은 값("윈도우 PC")은 OS를 말한 것이므로 통과시킨다.
PLATFORM_WORDS = ("pc", "컴퓨터", "노트북", "랩탑", "데스크탑", "computer", "laptop", "desktop")
OS_WORDS = ("windows", "윈도우", "윈도", "mac", "맥", "linux", "리눅스", "ubuntu", "우분투")
# 프롬프트 4절: 필수 가격 조건을 preferences에 복사하지 않는다
PRICE_IN_PREF = re.compile(r"(원\s*(이하|미만|이내|까지))|(무료\s*선호)")

# 하드웨어 모델명 비교용. 표기 차이(대소문자·공백·하이픈)는 같은 것으로 본다
_NORMALIZE = re.compile(r"[\s\-_]+")


def norm_model(value: str | None) -> str | None:
    if value is None:
        return None
    return _NORMALIZE.sub("", value).casefold()


def check_invariants(result: GameConditions) -> list[str]:
    """gold와 무관하게 늘 성립해야 하는 규칙. 위반 사유 목록을 낸다."""
    problems = []

    # 1절: hardware.os는 플랫폼 표현이 될 수 없다
    if result.hardware and result.hardware.os:
        os_value = result.hardware.os.strip().casefold()
        names_platform = any(word in os_value for word in PLATFORM_WORDS)
        names_os = any(word in os_value for word in OS_WORDS)
        if names_platform and not names_os:
            problems.append(f"hardware.os가 플랫폼 표현이다: {result.hardware.os!r}")

    # 4절: 가격 상한이 있으면 preferences에 가격 표현을 복사하지 않는다
    if result.max_price_krw is not None:
        for pref in result.preferences:
            if PRICE_IN_PREF.search(pref):
                problems.append(f"가격 조건이 preferences에 중복됐다: {pref!r}")

    # 4절: 무료 강제와 '무료 선호'는 함께 있을 수 없다
    if result.max_price_krw == 0:
        if any("무료" in pref for pref in result.preferences):
            problems.append("max_price_krw=0인데 preferences에 무료 표현이 남았다")

    # 5절: 같은 수치를 두 시간 필드에 옮겨 적지 않는다(분↔시간 환산 중복)
    if result.max_playtime_hours is not None and result.max_session_minutes is not None:
        if abs(result.max_playtime_hours * 60 - result.max_session_minutes) < 1e-6:
            problems.append("세션 길이와 총 플레이타임이 같은 시간을 가리킨다")

    # 1절: hardware가 비어 있으면 None이어야 한다(validator 계약)
    if result.hardware is not None:
        specs = (
            result.hardware.cpu,
            result.hardware.gpu,
            result.hardware.ram_gb,
            result.hardware.os,
        )
        if not any(value for value in specs):
            problems.append("hardware에 비교 가능한 항목이 없는데 null이 아니다")

    return problems


def compare_hardware(gold: dict | None, actual) -> list[str]:
    """hardware는 gold에 적은 항목만 본다. raw_text는 채점하지 않는다."""
    if gold is None:
        return [] if actual is None else [f"hardware가 null이어야 하는데 {actual!r}"]
    if actual is None:
        return [f"hardware가 {gold!r}여야 하는데 null"]

    problems = []
    for field, want in gold.items():
        got = getattr(actual, field)
        if field in {"cpu", "gpu", "os"}:
            # 모델명은 표기 차이를 허용하되, gold가 None이면 반드시 None이어야 한다
            if want is None:
                if got is not None:
                    problems.append(f"hardware.{field}가 null이어야 하는데 {got!r}")
            elif norm_model(want) != norm_model(got):
                problems.append(f"hardware.{field}: {want!r} 기대, {got!r} 나옴")
        elif want != got:
            problems.append(f"hardware.{field}: {want!r} 기대, {got!r} 나옴")
    return problems


def score_case(item: dict, result: GameConditions) -> dict:
    """문항 하나를 채점한다. 축별 통과 여부와 사유를 남긴다."""
    field_problems: list[str] = []
    for field, want in item["gold"].items():
        if field == "hardware":
            field_problems += compare_hardware(want, result.hardware)
            continue
        got = getattr(result, field)
        if field in {"genres", "excluded_genres", "platforms"}:
            # 순서는 보지 않고 집합으로 비교한다
            if {value.casefold() for value in want} != {value.casefold() for value in got}:
                field_problems.append(f"{field}: {want!r} 기대, {got!r} 나옴")
        elif want != got:
            field_problems.append(f"{field}: {want!r} 기대, {got!r} 나옴")

    pref_problems: list[str] = []
    joined = " / ".join(result.preferences)
    for needle in item.get("pref_has", []):
        if needle not in joined:
            pref_problems.append(f"preferences에 {needle!r}가 없다: {result.preferences!r}")
    for needle in item.get("pref_lacks", []):
        if needle in joined:
            pref_problems.append(f"preferences에 {needle!r}가 남았다: {result.preferences!r}")
    if item.get("pref_nonempty") and not result.preferences:
        pref_problems.append("preferences가 비어 있다")

    invariant_problems = check_invariants(result)
    return {
        "id": item["id"],
        "family": item["family"],
        "fields_passed": not field_problems,
        "preferences_passed": not pref_problems,
        "invariants_passed": not invariant_problems,
        "passed": not (field_problems or pref_problems or invariant_problems),
        "field_problems": field_problems,
        "preference_problems": pref_problems,
        "invariant_problems": invariant_problems,
    }
