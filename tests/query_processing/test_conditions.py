import pytest
from pydantic import ValidationError

from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.hardware import HardwareSpecs


@pytest.mark.parametrize(
    "data",
    [
        {"players": 0},
        {"max_price_krw": -1},
        {"max_playtime_hours": 0},
        {"max_session_minutes": -1},
        {"recommendation_count": 0},
        {"hardware": {"ram_gb": -1}},
    ],
)
def test_invalid_conditions_are_rejected(data):
    with pytest.raises(ValidationError):
        GameConditions(**data)

def test_empty_hardware_is_normalized_to_none():
    conditions = GameConditions(
        hardware=HardwareSpecs(),
    )

    assert conditions.hardware is None


def test_soft_free_preference_removes_hard_free_budget():
    conditions = GameConditions(
        preferences=["무료 선호"],
        max_price_krw=0,
    )

    assert conditions.max_price_krw is None


def test_mandatory_free_budget_remains_zero():
    conditions = GameConditions(
        preferences=[],
        max_price_krw=0,
    )

    assert conditions.max_price_krw == 0


def test_soft_turn_based_preference_removes_duplicate_exclusion():
    conditions = GameConditions(
        excluded_genres=["Horror", "Turn-based"],
        preferences=["턴제 비선호"],
    )

    assert conditions.excluded_genres == ["Horror"]
    assert conditions.preferences == ["턴제 비선호"]


def test_explicit_turn_based_exclusion_remains_without_soft_preference():
    conditions = GameConditions(
        excluded_genres=["Turn-based"],
        preferences=[],
    )

    assert conditions.excluded_genres == ["Turn-based"]


def test_category_in_both_lists_is_excluded_not_wanted():
    # 모델이 싫다고 한 분류를 양쪽에 다 넣은 적이 있다. 그러면 검색 후보가 0개가 된다
    conditions = GameConditions(
        genres=["Horror", "Adventure"],
        excluded_genres=["horror "],
        play_mode="cooperative",
    )

    assert conditions.genres == ["Adventure"]
    assert conditions.excluded_genres == ["horror "]


def test_distinct_wanted_and_excluded_categories_are_untouched():
    conditions = GameConditions(genres=["Adventure"], excluded_genres=["Horror"])

    assert conditions.genres == ["Adventure"]
    assert conditions.excluded_genres == ["Horror"]


def test_pc_platform_is_not_hardware():
    conditions = GameConditions(
        hardware=HardwareSpecs(
            os="PC",
            raw_text="PC",
        ),
        platforms=["PC"],
    )

    assert conditions.hardware is None
    assert conditions.platforms == ["PC"]


def test_raw_text_only_is_not_hardware():
    conditions = GameConditions(
        hardware=HardwareSpecs(
            raw_text="PC",
        ),
        platforms=["PC"],
    )

    assert conditions.hardware is None


def test_specific_windows_os_remains_hardware():
    conditions = GameConditions(
        hardware=HardwareSpecs(
            os="Windows 11",
            raw_text="Windows 11 PC",
        ),
        platforms=["PC"],
    )

    assert conditions.hardware is not None
    assert conditions.hardware.os == "Windows 11"


def test_price_constraint_is_not_duplicated_in_preferences():
    conditions = GameConditions(
        preferences=[
            "3만 원 이하",
            "Steam 평가가 좋은 게임",
        ],
        max_price_krw=30000,
    )

    assert conditions.preferences == [
        "Steam 평가가 좋은 게임"
    ]
    assert conditions.max_price_krw == 30000


def test_soft_price_preference_is_preserved():
    conditions = GameConditions(
        preferences=[
            "저렴한 게임 선호",
        ],
        max_price_krw=30000,
    )

    assert conditions.preferences == [
        "저렴한 게임 선호"
    ]


def test_explicit_free_preference_is_preserved_with_budget():
    conditions = GameConditions(
        preferences=[
            "무료 선호",
        ],
        max_price_krw=30000,
    )

    assert conditions.preferences == [
        "무료 선호"
    ]
    assert conditions.max_price_krw == 30000
