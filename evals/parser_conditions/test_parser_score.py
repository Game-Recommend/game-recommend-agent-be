"""채점기 검사. API를 부르지 않는다.

채점기가 틀리면 평가 결과 전체가 틀리므로, 통과·실패 양쪽을 모두 고정한다.
"""

import json
from pathlib import Path

from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.hardware import HardwareSpecs
from evals.parser_conditions.score import check_invariants, norm_model, score_case

DATA = json.loads((Path(__file__).parent / "dataset.json").read_text(encoding="utf-8"))
BY_ID = {item["id"]: item for item in DATA}


def test_dataset_has_200_unique_cases():
    assert len(DATA) == 200
    assert len({item["id"] for item in DATA}) == 200


def test_every_case_records_its_basis():
    assert all(item["basis"] for item in DATA)


def test_gold_fields_exist_on_the_model():
    """정답이 존재하지 않는 필드를 가리키면 채점이 조용히 통과해 버린다."""
    allowed = set(GameConditions.model_fields)
    for item in DATA:
        unknown = set(item["gold"]) - allowed
        assert not unknown, f"{item['id']}의 정답에 없는 필드: {unknown}"


def test_gold_hardware_fields_exist():
    allowed = set(HardwareSpecs.model_fields)
    for item in DATA:
        gold = item["gold"].get("hardware")
        if isinstance(gold, dict):
            unknown = set(gold) - allowed
            assert not unknown, f"{item['id']}의 hardware 정답에 없는 필드: {unknown}"


def test_norm_model_ignores_spacing_and_case():
    assert norm_model("RTX 3060") == norm_model("rtx3060")
    assert norm_model("i5-12400") == norm_model("i5 12400")
    assert norm_model(None) is None
    assert norm_model("RTX 3060") != norm_model("RTX 3070")


def test_matching_result_passes():
    item = BY_ID["Q001"]  # "3만 원 이하로 살 수 있는 게임 추천해줘"
    result = GameConditions(max_price_krw=30000, recommendation_count=5)
    assert score_case(item, result)["passed"]


def test_wrong_price_fails_on_fields():
    item = BY_ID["Q001"]
    scored = score_case(item, GameConditions(max_price_krw=29999, recommendation_count=5))
    assert not scored["passed"]
    assert not scored["fields_passed"]
    assert scored["field_problems"]


def test_price_duplicated_into_preferences_fails():
    """전용 필드가 있는 가격 조건을 preferences에 복사하면 실패한다."""
    item = BY_ID["Q001"]
    result = GameConditions(
        max_price_krw=30000, preferences=["3만 원 이하 선호"], recommendation_count=5
    )
    scored = score_case(item, result)
    assert not scored["passed"]
    assert not scored["invariants_passed"]


def test_platform_only_os_is_caught_in_some_layer():
    """os="PC"는 어느 층에서든 걸러져야 한다.

    두 저장소의 층이 다르다. 에이전트 저장소는 conditions.py의 validator가 지우고,
    원본 game-recommend-be는 validator가 없어 채점기의 공통 불변식이 잡는다.
    어느 쪽이든 통과로 넘어가지 않는다는 것이 계약이다(프롬프트 1절).
    """
    result = GameConditions(hardware=HardwareSpecs(os="PC"), recommendation_count=5)
    stripped_by_validator = result.hardware is None
    caught_by_invariant = bool(check_invariants(result))
    assert stripped_by_validator or caught_by_invariant


def test_platform_phrase_in_hardware_os_fails_invariant():
    """validator의 정확 일치 그물을 빠져나가는 값은 불변식이 잡는다."""
    result = GameConditions(hardware=HardwareSpecs(os="구형 노트북"), recommendation_count=5)
    assert result.hardware is not None  # validator가 지우지 못한다
    assert any("플랫폼" in problem for problem in check_invariants(result))


def test_real_os_name_with_platform_word_passes_invariant():
    result = GameConditions(hardware=HardwareSpecs(os="윈도우 PC"), recommendation_count=5)
    assert check_invariants(result) == []


def test_same_duration_in_both_time_fields_fails_invariant():
    result = GameConditions(
        max_playtime_hours=0.5, max_session_minutes=30, recommendation_count=5
    )
    assert any("같은 시간" in problem for problem in check_invariants(result))


def test_different_durations_in_both_time_fields_pass_invariant():
    result = GameConditions(
        max_playtime_hours=20, max_session_minutes=30, recommendation_count=5
    )
    assert check_invariants(result) == []


def test_genres_compared_as_a_set():
    """카테고리 순서는 채점하지 않는다."""
    item = BY_ID["Q132"]  # "액션 슈팅 게임 추천해줘. 공포는 빼고"
    assert item["gold"]["genres"] == ["Action", "Shooter"]
    result = GameConditions(
        genres=["Shooter", "Action"],
        excluded_genres=item["gold"]["excluded_genres"],
        recommendation_count=item["gold"]["recommendation_count"],
    )
    assert score_case(item, result)["fields_passed"]


def test_genres_and_excluded_genres_are_not_interchangeable():
    """원하는 카테고리를 excluded_genres에 넣으면 실패한다(실측 Q200의 실패 형태)."""
    item = BY_ID["Q132"]
    result = GameConditions(
        genres=[],
        excluded_genres=["Action", "Shooter"],
        recommendation_count=item["gold"]["recommendation_count"],
    )
    assert not score_case(item, result)["fields_passed"]


def test_hardware_expected_null_but_present_fails():
    item = BY_ID["Q107"]  # "구형 노트북으로 할 게임 알려줘" → hardware=null
    assert item["gold"]["hardware"] is None
    result = GameConditions(hardware=HardwareSpecs(os="구형 노트북"), recommendation_count=5)
    scored = score_case(item, result)
    assert not scored["passed"]


def test_missing_required_preference_fails():
    """무료 선호를 preferences에 남기지 않으면 실패한다."""
    item = BY_ID["Q021"]  # "무료면 좋겠다. 게임 추천해줘"
    assert item["pref_has"] == ["무료 선호"]
    scored = score_case(item, GameConditions(max_price_krw=None, recommendation_count=5))
    assert not scored["passed"]
    assert not scored["preferences_passed"]


def test_present_required_preference_passes():
    item = BY_ID["Q021"]
    result = GameConditions(
        max_price_krw=None, preferences=["무료 선호"], recommendation_count=5
    )
    assert score_case(item, result)["passed"]
