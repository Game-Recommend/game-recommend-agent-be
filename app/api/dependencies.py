from fastapi import HTTPException, Request

from app.pipeline.orchestrator import RecommendationOrchestrator


def get_recommender(request: Request) -> RecommendationOrchestrator:
    """앱 시작 시 조립한 파이프라인을 app.state.recommender로 주입한다."""
    recommender = getattr(request.app.state, "recommender", None)
    if recommender is None:
        raise HTTPException(
            status_code=503, detail="추천 서비스의 외부 연동이 설정되지 않았습니다."
        )
    return recommender
