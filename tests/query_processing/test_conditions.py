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
