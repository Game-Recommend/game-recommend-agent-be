"""최종 답변 입출력 연결 검증. 실제 LLM 품질은 연동 구현 후 별도 검증한다."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.pipeline.orchestrator import PipelineStageError, RecommendationOrchestrator
from app.pipeline.query_processing.conditions import GameConditions
from app.schemas.common import ConditionCheck
from app.schemas.game import GameCandidate
from app.schemas.hardware import HardwareResult
from app.schemas.price import PriceQuote, PriceResult
from app.schemas.review import ReviewSummary
from tests.price_hardware.final_answer.fakes import FakeAnswerer


@pytest.fixture
def answer_pipeline():
    """다른 담당자의 구현·대역 없이 최종 답변 단계만 교체할 수 있는 입력을 구성한다."""
    game = GameCandidate(igdb_id=1, name="후보 게임")
    answerer = FakeAnswerer(answer="독립적으로 생성한 답변")
    pipeline = RecommendationOrchestrator(
        parser=AsyncMock(parse=AsyncMock(return_value=GameConditions(max_price_krw=100))),
        game_search=AsyncMock(run=AsyncMock(return_value=[game])),
        price=AsyncMock(
            run=AsyncMock(
                return_value={
                    1: PriceResult(
                        igdb_id=1,
                        quote=PriceQuote(igdb_id=1, amount_krw=50),
                        check=ConditionCheck(status="met", reason="예산 이하"),
                    )
                }
            )
        ),
        hardware=AsyncMock(
            run=AsyncMock(
                return_value={
                    1: HardwareResult(
                        igdb_id=1, check=ConditionCheck(status="skipped", reason="사양 미지정")
                    )
                }
            )
        ),
        review_summary=AsyncMock(
            run=AsyncMock(return_value={1: ReviewSummary(igdb_id=1, summary="리뷰 근거")})
        ),
        answerer=answerer,
    )
    return pipeline, answerer


def test_final_answer_receives_question_and_evidence_after_reviews(answer_pipeline):
    pipeline, answerer = answer_pipeline
    response = asyncio.run(pipeline.run("100원 이하 게임 추천"))

    assert answerer.question == "100원 이하 게임 추천"
    assert answerer.evidence.conditions.max_price_krw == 100
    assert answerer.evidence.games[0].price.quote.amount_krw == 50
    assert answerer.evidence.games[0].review.summary == "리뷰 근거"
    assert response.answer == "독립적으로 생성한 답변"
    assert answerer.calls == ["answer"]


def test_final_answer_receives_empty_candidates_and_reason(answer_pipeline):
    pipeline, answerer = answer_pipeline
    pipeline.game_search.run.return_value = []
    response = asyncio.run(pipeline.run("조건에 맞는 게임 추천"))

    assert answerer.evidence.games == []
    assert answerer.evidence.warnings
    assert response.answer == answerer.answer
    pipeline.review_summary.run.assert_not_awaited()


def test_final_answer_failure_is_reported_as_required_stage_error(answer_pipeline, monkeypatch):
    pipeline, answerer = answer_pipeline
    monkeypatch.setattr(answerer, "generate", AsyncMock(side_effect=ConnectionError("LLM 실패")))
    with pytest.raises(PipelineStageError, match="최종 답변 생성"):
        asyncio.run(pipeline.run("추천"))
