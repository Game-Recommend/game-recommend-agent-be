import pytest
from pydantic import ValidationError

from app.pipeline.query_processing.conditions import GameConditions


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
