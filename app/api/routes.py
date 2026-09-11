from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_recommender
from app.pipeline.orchestrator import PipelineStageError, RecommendationOrchestrator
from app.schemas.recommendation import RecommendationRequest, RecommendationResponse

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/recommend", response_model=RecommendationResponse)
async def recommend(
    body: RecommendationRequest,
    recommender: Annotated[RecommendationOrchestrator, Depends(get_recommender)],
):
    try:
        return await recommender.run(body.question)
    except PipelineStageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
