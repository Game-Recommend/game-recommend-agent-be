import asyncio
from unittest.mock import AsyncMock

import pytest

from app.schemas.game import GameCandidate
from app.tools.review_summary import ReviewSummaryTool
from tests.reviews.fakes import FakeReviews


def test_empty_candidates_do_not_call_summary_api():
    client = FakeReviews()
    assert asyncio.run(ReviewSummaryTool(client).run([])) == {}
    assert client.calls == []


def test_summary_api_failure_is_left_for_orchestrator_to_handle():
    client = FakeReviews()
    client.summarize = AsyncMock(side_effect=ConnectionError("리뷰 API 연결 실패"))
    with pytest.raises(ConnectionError):
        asyncio.run(ReviewSummaryTool(client).run([GameCandidate(igdb_id=1, name="게임")]))
